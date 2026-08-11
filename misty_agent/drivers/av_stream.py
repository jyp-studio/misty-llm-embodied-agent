"""Misty's video stream: RTSP in, timestamped frames out.

Two modules live here because the AV service and the video reader have
different lifetimes and different failure modes:

``AvSession``       owns the robot-side service. Enabling AV streaming is a
                    per-process, once-only operation that both video and audio
                    depend on; it hands out the single RTSP URL they share.
``RtspVideoStream`` owns the client-side reader thread and the frame buffer.

Callers see ``start / stop / read / flush / backlog`` and nothing else. They do
not start threads, do not know the URL, and do not touch a queue — all three
were things the previous code (``CUBS_Misty.Robot``) required of them.

**Frames are timestamped at capture**, which is the whole point of doing this
before the replay harness: ``CapturedFrame.captured_at`` is read immediately
after ``VideoCapture.read()`` returns, so downstream age filters can ask "how
old is this picture?" rather than "how long ago did I finish thinking about
it?". See PLAN.md §5 defect A2. Nothing consumes the field yet — M5 rewires
the consumer, and until it does M4's harness must stay red.

``opencv`` is imported inside ``start()`` rather than at module scope so that
this module — and the contract tests over ``AvSession`` — import on a machine
with no camera stack installed.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, runtime_checkable

import numpy as np

from misty_agent.config import settings
from misty_agent.drivers.robot_commands import RobotCommands

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapturedFrame:
    """One camera frame and the instant it was pulled off the wire.

    ``captured_at`` is a ``time.monotonic()`` reading. Compare it only against
    other monotonic readings — it is not a wall-clock time, deliberately, so
    that the lag measurements the harness makes cannot be corrupted by an NTP
    step mid-episode.
    """

    image: np.ndarray
    captured_at: float

    def age_s(self, now: Optional[float] = None) -> float:
        """Seconds since this frame left the camera pipeline."""
        return (time.monotonic() if now is None else now) - self.captured_at


class WorkerThread:
    """A background loop with a stop flag, started and stopped idempotently.

    Three things now run a producer or consumer loop behind a
    :class:`VideoSource`-shaped interface — the RTSP reader, the replay
    harness's camera, and the harness's pipeline — and each needs the same
    six lines of thread bookkeeping. This is that, once. The same argument as
    :class:`FrameBuffer`: two copies are two things that can drift apart while
    both keep passing (PLAN.md §10).

    ``run`` is the whole loop, and receives the stop event to poll. It is
    expected to return promptly once that is set. An exception escaping it is
    logged rather than swallowed: a dead worker is indistinguishable from a
    very slow one at the seam — the reader just gets nothing — so a silent
    death would be measured as enormous latency with no clue why.
    """

    def __init__(
        self, run: "Callable[[threading.Event], None]", *, name: str
    ) -> None:
        self._run = run
        self._name = name
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._guarded, name=self._name, daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _guarded(self) -> None:
        try:
            self._run(self._stop)
        except Exception as exc:
            log.exception("%s stopped unexpectedly: %s", self._name, exc)


class FrameBuffer:
    """What a video source holds between producing a frame and it being read.

    Every :class:`VideoSource` needs the same thing here, and the replay
    harness's camera needs it to behave *identically* to the RTSP stream —
    otherwise the harness measures its own buffering rather than the system's.
    Two copies of this would be two things that could drift apart while both
    kept passing, which is the failure PLAN.md §10 records against the control
    law.

    **Unbounded, deliberately.** Producing faster than the consumer reads makes
    it grow without limit, and nothing here stops that: the growth is PLAN.md
    defect A1, and the harness exists to measure it. Bounding it is a decision
    for the pipeline rewrite (§12.3), not a property of the container.
    """

    def __init__(self) -> None:
        self._frames: "queue.Queue[CapturedFrame]" = queue.Queue()

    def put(self, frame: CapturedFrame) -> None:
        self._frames.put(frame)

    def read(self, timeout: float) -> Optional[CapturedFrame]:
        """Next frame, or ``None`` if none arrived within ``timeout``."""
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    @property
    def depth(self) -> int:
        return self._frames.qsize()


@runtime_checkable
class VideoSource(Protocol):
    """A source of timestamped camera frames.

    Everything a caller must know:

    * ``start()`` before any ``read()``, ``stop()`` when finished. Both are
      idempotent; ``stop()`` is safe even if ``start()` failed.
    * ``read(timeout)`` blocks up to ``timeout`` seconds and returns ``None``
      if no frame arrived. It never raises on an empty buffer.
    * Frames are delivered in capture order.
    * ``flush()`` discards everything buffered. Call it after any action that
      invalidates the robot's viewpoint.
    * ``backlog`` counts frames waiting to be read. It is a diagnostic, not a
      guarantee: the production adapter's buffer is currently unbounded and
      grows without limit whenever the consumer is slower than the camera
      (PLAN.md §5 defect A1).

    Two adapters satisfy this: ``RtspVideoStream`` against a real Misty, and
    the replay harness's synthetic source in M4.
    """

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read(self, timeout: float) -> Optional[CapturedFrame]: ...

    def flush(self) -> None: ...

    @property
    def backlog(self) -> int: ...


class AvSession:
    """Misty's AV streaming service, and the RTSP URL it publishes.

    One per process. Misty will not start a second stream while one is already
    running, and a crashed process leaves the previous one running, so
    ``open()`` resets the services before enabling them.

    The reset previously lived in the application layer and POSTed to
    ``/api/avstreaming/disable`` and ``/api/audio/recording/stop`` by hand.
    Neither path appears in the REST reference; the documented ones are
    ``/api/services/avstreaming/disable`` and ``/api/audio/record/stop``, which
    is what the SDK methods used below send. See PLAN.md §10 (M3).
    """

    def __init__(
        self,
        commands: RobotCommands,
        *,
        port: int = settings.av_stream_port,
        width: int = settings.av_stream_width,
        height: int = settings.av_stream_height,
        reset_settle_s: float = settings.av_reset_settle_s,
    ) -> None:
        self._commands = commands
        self._port = port
        self._width = width
        self._height = height
        self._reset_settle_s = reset_settle_s
        self._url: Optional[str] = None

    @property
    def url(self) -> Optional[str]:
        """The RTSP URL, or ``None`` while the session is closed."""
        return self._url

    def open(self) -> str:
        """Reset, enable and start AV streaming. Returns the RTSP URL.

        Raises ``RuntimeError`` if Misty rejects either request. The reset step
        is best-effort: a robot that has never streamed will refuse it, and
        that is not an error.
        """
        if self._url is not None:
            return self._url

        self._reset()

        response = self._commands.enable_av_streaming_service()
        if response.status_code != 200:
            raise RuntimeError(
                f"Misty refused to enable AV streaming (HTTP {response.status_code})"
            )

        response = self._commands.start_av_streaming(
            url=f"rtspd:{self._port}", width=self._width, height=self._height
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Misty refused to start AV streaming (HTTP {response.status_code})"
            )

        self._url = f"rtsp://{self._commands.ip}:{self._port}"
        log.info("AV streaming started at %s", self._url)
        return self._url

    def close(self) -> None:
        """Stop streaming. Safe to call on a session that was never opened."""
        self._url = None
        try:
            self._commands.stop_av_streaming()
        except Exception as exc:  # the robot may already be unreachable
            log.warning("stop_av_streaming failed: %s", exc)

    def _reset(self) -> None:
        """Clear whatever a previous run left running."""
        for command in (
            self._commands.disable_av_streaming_service,
            self._commands.stop_recording_audio,
        ):
            try:
                command()
            except Exception as exc:
                log.warning("AV reset step %s failed: %s", command.__name__, exc)
        if self._reset_settle_s:
            time.sleep(self._reset_settle_s)


class RtspVideoStream:
    """Reads Misty's RTSP video into a buffer of timestamped frames.

    Satisfies :class:`VideoSource`.

    Misty's camera is mounted rotated; ``rotate_degrees`` puts the picture
    upright before anyone downstream looks for a face in it.
    """

    _ROTATIONS = {90: "ROTATE_90_CLOCKWISE", 180: "ROTATE_180", 270: "ROTATE_90_COUNTERCLOCKWISE"}

    def __init__(
        self,
        session: AvSession,
        *,
        rotate_degrees: int = settings.camera_rotate_degrees,
        producer_pause_s: float = settings.video_producer_pause_s,
    ) -> None:
        if rotate_degrees not in (0, *self._ROTATIONS):
            raise ValueError(
                f"rotate_degrees must be one of 0, 90, 180, 270 — got {rotate_degrees}"
            )
        self._session = session
        self._rotate_degrees = rotate_degrees
        self._producer_pause_s = producer_pause_s
        self._buffer = FrameBuffer()
        self._worker = WorkerThread(self._read_loop, name="rtsp-video")

    # ---------- VideoSource ----------

    def start(self) -> None:
        if self._worker.is_running:
            return
        self._session.open()
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()
        self._session.close()

    def read(self, timeout: float) -> Optional[CapturedFrame]:
        return self._buffer.read(timeout)

    def flush(self) -> None:
        self._buffer.flush()

    @property
    def backlog(self) -> int:
        return self._buffer.depth

    # ---------- implementation ----------

    def _read_loop(self, stop: threading.Event) -> None:
        import cv2

        url = self._session.url
        if url is None:
            log.error("video reader started before the AV session was opened")
            return

        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not capture.isOpened():
            log.error("cannot open RTSP video at %s", url)
            return

        rotation = (
            getattr(cv2, self._ROTATIONS[self._rotate_degrees])
            if self._rotate_degrees
            else None
        )
        log.info("RTSP video reader started")
        try:
            while not stop.is_set():
                ok, image = capture.read()
                # Stamp the instant the frame arrived, before any work is done
                # on it. Everything after this point is measurable lag.
                captured_at = time.monotonic()
                if not ok:
                    log.warning("RTSP video read failed; reader exiting")
                    break
                if rotation is not None:
                    image = cv2.rotate(image, rotation)
                self._buffer.put(
                    CapturedFrame(image=image, captured_at=captured_at)
                )
                # Producer throttle carried over from the original reader. It
                # does not prevent the backlog in defect A1 — the consumer is
                # slower than 100 fps — it only slows the growth.
                if self._producer_pause_s:
                    time.sleep(self._producer_pause_s)
        finally:
            capture.release()
            log.info("RTSP video reader stopped")

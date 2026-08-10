"""Misty's audio stream: RTSP in, transcribed utterances out.

The pipeline is decode → voice activity detection → transcription, and
:class:`AudioStream` hides all three: callers ask for the next
:class:`Utterance` and never see a PCM sample, a silence threshold, or a
thread.

:class:`UtteranceDetector` is an internal seam. Deciding where one utterance
ends is the only part of this module with interesting behaviour, and as a pure
state machine it can be tested exhaustively without a socket, a thread, or a
media stack. It is not part of the interface — callers get utterances, not a
detector.

``PyAV`` is imported inside the decode thread rather than at module scope, so
this module imports on a machine with no media stack — which is where the
tests run.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from misty_agent.config import settings
from misty_agent.drivers.av_stream import AvSession
from misty_agent.perception.asr import Transcriber

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Utterance:
    """One stretch of speech, and when it happened.

    Both timestamps are ``time.monotonic()`` readings, matching
    ``CapturedFrame.captured_at`` — the two sensor streams share a clock so
    that "did the user speak before or after the robot moved?" is answerable.
    """

    text: str
    started_at: float
    ended_at: float


@dataclass(frozen=True)
class Segment:
    """Audio judged to be one utterance, before anyone has transcribed it."""

    pcm: np.ndarray
    started_at: float
    ended_at: float


def is_silent(pcm: np.ndarray, threshold_db: float) -> bool:
    """True when a block of audio is quieter than ``threshold_db`` RMS.

    Digital silence is reported as -1000 dB rather than -inf so the comparison
    stays finite for any threshold a caller might configure.
    """
    if pcm.size == 0:
        return True
    rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float64)))))
    level_db = 20.0 * np.log10(rms) if rms > 0 else -1000.0
    return level_db < threshold_db


class UtteranceDetector:
    """Splits a stream of audio blocks into utterances.

    Feed it blocks with :meth:`push`; it returns a :class:`Segment` on the
    block that completes an utterance and ``None`` otherwise. Call
    :meth:`timed_out` when the stream goes quiet, which closes an utterance in
    progress rather than leaving it hanging.

    Two rules define an utterance:

    * it starts at the first block louder than ``silence_threshold_db``, and
      carries up to ``preroll_s`` of the audio just before it so the first
      phoneme is not clipped;
    * it ends after ``silence_duration_s`` of continuous quiet, and is
      discarded entirely if it holds less than ``min_utterance_s`` of audio.

    While no utterance is in progress the retained audio is capped at the
    pre-roll. The code this replaces buffered every block from process start
    and emptied only on utterance end, so an idle robot grew the buffer
    without bound and every transcript carried all the silence before it.
    """

    def __init__(
        self,
        *,
        sample_rate: int = settings.audio_sample_rate_hz,
        silence_threshold_db: float = settings.silence_threshold_db,
        silence_duration_s: float = settings.silence_duration_s,
        min_utterance_s: float = settings.min_utterance_s,
        preroll_s: float = settings.audio_preroll_s,
    ) -> None:
        self._sample_rate = sample_rate
        self._silence_threshold_db = silence_threshold_db
        self._silence_duration_s = silence_duration_s
        self._min_utterance_s = min_utterance_s
        self._preroll_samples = int(preroll_s * sample_rate)

        self._buffer = np.array([], dtype=np.float32)
        self._speaking = False
        self._started_at: Optional[float] = None
        self._last_voice_at: Optional[float] = None

    @property
    def speaking(self) -> bool:
        """Whether an utterance is currently in progress."""
        return self._speaking

    @property
    def buffered_samples(self) -> int:
        """How much audio is retained. Bounded by the pre-roll when idle."""
        return int(self._buffer.size)

    def push(self, arrived_at: float, block: np.ndarray) -> Optional[Segment]:
        block = np.asarray(block, dtype=np.float32)
        self._buffer = np.concatenate((self._buffer, block))

        if not is_silent(block, self._silence_threshold_db):
            if not self._speaking:
                log.debug("voice activity started")
                self._speaking = True
                self._started_at = arrived_at
            self._last_voice_at = arrived_at
            return None

        if not self._speaking:
            if self._preroll_samples:
                self._buffer = self._buffer[-self._preroll_samples :]
            else:
                self._buffer = np.array([], dtype=np.float32)
            return None

        # `is None`, not a falsiness test: a monotonic clock can legitimately
        # read 0.0, and `0.0 or arrived_at` would silently restart the timer.
        last_voice_at = arrived_at if self._last_voice_at is None else self._last_voice_at
        if arrived_at - last_voice_at >= self._silence_duration_s:
            return self._close(last_voice_at)
        return None

    def timed_out(self, at: float) -> Optional[Segment]:
        """The audio stream stopped delivering. Close anything in progress."""
        if not self._speaking:
            return None
        return self._close(at if self._last_voice_at is None else self._last_voice_at)

    def _close(self, ended_at: float) -> Optional[Segment]:
        pcm, started_at = self._buffer, self._started_at
        self._buffer = np.array([], dtype=np.float32)
        self._speaking = False
        self._started_at = None
        self._last_voice_at = None

        duration_s = pcm.size / self._sample_rate
        if duration_s < self._min_utterance_s:
            log.debug("discarding %.2fs utterance (too short)", duration_s)
            return None
        return Segment(
            pcm=pcm,
            started_at=started_at if started_at is not None else ended_at,
            ended_at=ended_at,
        )


class AudioStream:
    """Listens to Misty and reports what was said.

    Everything a caller must know:

    * ``start()`` before any ``read()``, ``stop()`` when finished. Both are
      idempotent. The :class:`AvSession` must be the same one the video stream
      uses; there is only one RTSP stream and it carries both.
    * ``read(timeout)`` blocks up to ``timeout`` seconds and returns ``None``
      if nobody spoke.
    * ``flush()`` discards utterances already recognised but not yet read.
    * ``mute_for(seconds)`` drops utterances that end within the next
      ``seconds`` — used so Misty does not transcribe her own text-to-speech.
      Calls do not stack; the later deadline wins.

    Transcription runs on the voice-detection thread, so a slow round trip
    lets decoded audio queue up behind it. That matches the behaviour of the
    code this replaces; the fix belongs with the rest of the latency work.
    """

    def __init__(
        self,
        session: AvSession,
        transcriber: Transcriber,
        *,
        sample_rate: int = settings.audio_sample_rate_hz,
        detector: Optional[UtteranceDetector] = None,
    ) -> None:
        self._session = session
        self._transcriber = transcriber
        self._sample_rate = sample_rate
        self._detector = detector or UtteranceDetector(sample_rate=sample_rate)

        self._blocks: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()
        self._utterances: "queue.Queue[Utterance]" = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._muted_until = 0.0

    # ---------- interface ----------

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._session.open()
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._decode_loop, name="rtsp-audio", daemon=True),
            threading.Thread(target=self._detect_loop, name="audio-vad", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        threads, self._threads = self._threads, []
        for thread in threads:
            thread.join(timeout=2.0)

    def read(self, timeout: float) -> Optional[Utterance]:
        try:
            return self._utterances.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while True:
            try:
                self._utterances.get_nowait()
            except queue.Empty:
                return

    def mute_for(self, seconds: float) -> None:
        """Ignore anything heard for the next ``seconds``."""
        self._muted_until = max(self._muted_until, time.monotonic() + seconds)

    # ---------- implementation ----------

    def _decode_loop(self) -> None:
        import av

        url = self._session.url
        if url is None:
            log.error("audio stream started before the AV session was opened")
            return

        try:
            container = av.open(
                url, options={"rtsp_transport": "tcp", "stimeout": "5000000"}
            )
        except Exception as exc:
            log.error("cannot open RTSP audio at %s: %s", url, exc)
            return

        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            log.error("RTSP stream at %s carries no audio", url)
            container.close()
            return

        log.info("RTSP audio decoder started")
        try:
            for packet in container.demux(stream):
                if self._stop.is_set():
                    break
                for frame in packet.decode():
                    block = frame.to_ndarray()
                    if block.ndim > 1 and block.shape[0] > 1:
                        block = np.mean(block, axis=0)  # downmix to mono
                    self._blocks.put((time.monotonic(), block.flatten()))
        except Exception as exc:
            log.exception("RTSP audio decoder crashed: %s", exc)
        finally:
            container.close()
            log.info("RTSP audio decoder stopped")

    def _detect_loop(self) -> None:
        while not self._stop.is_set():
            try:
                arrived_at, block = self._blocks.get(timeout=1.0)
            except queue.Empty:
                segment = self._detector.timed_out(time.monotonic())
            else:
                segment = self._detector.push(arrived_at, block)

            if segment is not None:
                self._publish(segment)

    def _publish(self, segment: Segment) -> None:
        if time.monotonic() < self._muted_until:
            log.debug("dropping utterance heard while muted")
            return
        text = self._transcriber.transcribe(segment.pcm, self._sample_rate)
        if not text:
            return
        log.info("heard: %s", text)
        self._utterances.put(
            Utterance(
                text=text, started_at=segment.started_at, ended_at=segment.ended_at
            )
        )

"""Misty's bounded audio stream: RTSP in, VAD segments out.

The pipeline is decode → voice activity detection. Ticket 04's
``LiveInputAdapter`` consumes the resulting :class:`Segment` and is the sole
owner of the decision to send audio to hosted transcription.

:class:`UtteranceDetector` is an internal seam. Deciding where one utterance
ends is the only part of this module with interesting behaviour, and as a pure
state machine it can be tested exhaustively without a socket, a thread, or a
media stack. It is not part of the interface — callers get segments, not a
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
from enum import Enum
from typing import Callable, Optional

import numpy as np

from misty_agent.config import settings
from misty_agent.drivers.av_stream import AvSession

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    """Audio judged to be one utterance, before anyone has transcribed it."""

    pcm: np.ndarray
    started_at: float
    ended_at: float


class AudioPipelineEnding(str, Enum):
    """Why the complete decode/VAD pipeline stopped producing segments."""

    ENDED = "ended"
    ERROR = "error"


@dataclass(frozen=True)
class AudioPipelineTerminal:
    """The final outcome of one audio decode/VAD pipeline run."""

    ending: AudioPipelineEnding
    error_type: Optional[str] = None


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
        max_utterance_s: float = settings.max_utterance_s,
    ) -> None:
        self._sample_rate = sample_rate
        self._silence_threshold_db = silence_threshold_db
        self._silence_duration_s = silence_duration_s
        self._min_utterance_s = min_utterance_s
        self._preroll_samples = int(preroll_s * sample_rate)
        self._max_utterance_samples = round(max_utterance_s * sample_rate)

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
                preroll_samples = max(0, self._buffer.size - block.size)
                self._started_at = (
                    arrived_at - preroll_samples / self._sample_rate
                )
            self._last_voice_at = arrived_at
            if self._buffer.size >= self._max_utterance_samples:
                assert self._started_at is not None
                self._buffer = self._buffer[: self._max_utterance_samples]
                return self._close(
                    self._started_at
                    + self._max_utterance_samples / self._sample_rate
                )
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
    """Decode Misty's audio into bounded VAD segments.

    Everything a caller must know:

    * ``start()`` before ``read_segment()``, ``stop()`` when finished. Both
      are idempotent. The :class:`AvSession` must be the same one the video
      stream uses; there is only one RTSP stream and it carries both.
    * ``read_segment(timeout)`` blocks up to ``timeout`` seconds and returns
      ``None`` if no VAD-completed segment is ready.
    * ``flush()`` discards completed segments not yet read.
    * ``mute_for(seconds)`` drops utterances that end within the next
      ``seconds`` — used so Misty does not transcribe her own text-to-speech.
      Calls do not stack; the later deadline wins. This is the whole of the
      suppression window: it covers **playback and nothing else**, so someone
      interrupting the moment Misty stops talking is heard. The old script
      deafened perception for the entire action sequence, which lost whatever
      was said during it (`PLAN.md` §15.29).

    The clock is injectable so that window can be tested without waiting for
    it. Nothing here calls ``time`` directly.

    Both decoded blocks and VAD-completed segments have fixed capacities.
    When a producer outruns a consumer, the oldest queued item is discarded
    and ``take_dropped`` reports the loss. Hosted transcription never runs on
    either producer thread.
    """

    def __init__(
        self,
        session: AvSession,
        *,
        sample_rate: int = settings.audio_sample_rate_hz,
        detector: Optional[UtteranceDetector] = None,
        monotonic: Optional[Callable[[], float]] = None,
        block_queue_capacity: int = settings.audio_block_queue_capacity,
        segment_queue_capacity: int = settings.audio_segment_queue_capacity,
    ) -> None:
        if block_queue_capacity <= 0 or segment_queue_capacity <= 0:
            raise ValueError("audio queue capacity must be greater than zero")
        self._session = session
        self._sample_rate = sample_rate
        self._detector = detector or UtteranceDetector(sample_rate=sample_rate)
        self._monotonic = monotonic or time.monotonic

        self._blocks: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue(
            maxsize=block_queue_capacity
        )
        self._segments: "queue.Queue[Segment]" = queue.Queue(
            maxsize=segment_queue_capacity
        )
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._muted_until = 0.0
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._decoder_done = threading.Event()
        self._vad_done = threading.Event()
        self._terminal: Optional[AudioPipelineTerminal] = None
        self._terminal_delivered = False
        self._terminal_lock = threading.Lock()

    # ---------- interface ----------

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._session.open()
        self._stop.clear()
        self._decoder_done.clear()
        self._vad_done.clear()
        with self._terminal_lock:
            self._terminal = None
            self._terminal_delivered = False
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

    def read_segment(self, timeout: float) -> Optional[Segment]:
        """Return one VAD-completed segment without invoking hosted ASR."""
        try:
            return self._segments.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        while True:
            try:
                self._segments.get_nowait()
            except queue.Empty:
                return

    def take_dropped(self) -> int:
        """Consume the number of block/segment items lost to backpressure."""
        with self._dropped_lock:
            dropped, self._dropped = self._dropped, 0
        return dropped

    def take_terminal(self) -> Optional[AudioPipelineTerminal]:
        """Return the final pipeline fact once, after accepted work drains."""
        if (
            not self._decoder_done.is_set()
            or not self._vad_done.is_set()
            or not self._segments.empty()
        ):
            return None
        with self._terminal_lock:
            if self._terminal_delivered or self._terminal is None:
                return None
            self._terminal_delivered = True
            return self._terminal

    @property
    def exhausted(self) -> bool:
        """Whether the decoder ended and every accepted block was drained."""
        return (
            self._decoder_done.is_set()
            and self._vad_done.is_set()
            and self._segments.empty()
        )

    def mute_for(self, seconds: float) -> None:
        """Ignore anything heard for the next ``seconds``.

        Deadlines do not stack — the later one wins — because two overlapping
        utterances should end the window when the *last* of them does, not at
        the sum of both.
        """
        self._muted_until = max(self._muted_until, self._monotonic() + seconds)

    def muted(self) -> bool:
        """Whether the window is currently shut. For tests and diagnostics."""
        return self._monotonic() < self._muted_until

    # ---------- implementation ----------

    def _decode_loop(self) -> None:
        url = self._session.url
        if url is None:
            log.error("audio stream started before the AV session was opened")
            self._decoder_finished(
                AudioPipelineEnding.ERROR, error_type="MissingStreamUrl"
            )
            return

        try:
            import av

            container = av.open(
                url, options={"rtsp_transport": "tcp", "stimeout": "5000000"}
            )
        except Exception as exc:
            log.error("cannot open RTSP audio at %s: %s", url, exc)
            self._decoder_finished(
                AudioPipelineEnding.ERROR, error_type=type(exc).__name__
            )
            return

        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            log.error("RTSP stream at %s carries no audio", url)
            container.close()
            self._decoder_finished(
                AudioPipelineEnding.ERROR, error_type="MissingAudioTrack"
            )
            return

        log.info("RTSP audio decoder started")
        ending = AudioPipelineEnding.ENDED
        error_type = None
        try:
            for packet in container.demux(stream):
                if self._stop.is_set():
                    break
                for frame in packet.decode():
                    block = frame.to_ndarray()
                    if block.ndim > 1 and block.shape[0] > 1:
                        block = np.mean(block, axis=0)  # downmix to mono
                    self._offer_block(self._monotonic(), block.flatten())
        except Exception as exc:
            log.exception("RTSP audio decoder crashed: %s", exc)
            ending = AudioPipelineEnding.ERROR
            error_type = type(exc).__name__
        finally:
            container.close()
            self._decoder_finished(
                None if self._stop.is_set() else ending,
                error_type=error_type,
            )
            log.info("RTSP audio decoder stopped")

    def _detect_loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    arrived_at, block = self._blocks.get(timeout=1.0)
                except queue.Empty:
                    self._flush_detector()
                    if self._decoder_done.is_set():
                        return
                    continue

                segment = self._detector.push(arrived_at, block)
                if segment is not None:
                    self._publish(segment)
                if self._decoder_done.is_set() and self._blocks.empty():
                    self._flush_detector()
                    return
        except Exception as exc:
            log.exception("audio VAD worker crashed: %s", exc)
            self._record_terminal(
                AudioPipelineEnding.ERROR,
                error_type=type(exc).__name__,
            )
            self._stop.set()
        finally:
            self._vad_done.set()

    def _flush_detector(self) -> None:
        """Publish speech still buffered when input stalls or reaches EOF."""
        segment = self._detector.timed_out(self._monotonic())
        if segment is not None:
            self._publish(segment)

    def _decoder_finished(
        self,
        ending: Optional[AudioPipelineEnding],
        *,
        error_type: Optional[str] = None,
    ) -> None:
        """Record the decoder outcome and release the VAD drain loop."""
        if ending is not None:
            self._record_terminal(ending, error_type=error_type)
        self._decoder_done.set()

    def _record_terminal(
        self,
        ending: AudioPipelineEnding,
        *,
        error_type: Optional[str] = None,
    ) -> None:
        """Retain one final outcome, allowing an error to replace normal EOF."""
        with self._terminal_lock:
            if self._terminal_delivered:
                return
            if (
                self._terminal is None
                or ending is AudioPipelineEnding.ERROR
                and self._terminal.ending is not AudioPipelineEnding.ERROR
            ):
                self._terminal = AudioPipelineTerminal(
                    ending=ending,
                    error_type=error_type,
                )

    def _publish(self, segment: Segment) -> None:
        if self.muted():
            log.debug("dropping utterance heard while muted")
            return
        self._offer_bounded(self._segments, segment)

    def _offer_block(self, arrived_at: float, block: np.ndarray) -> None:
        self._offer_bounded(self._blocks, (arrived_at, block))

    def _offer_bounded(self, work: queue.Queue, item) -> None:
        try:
            work.put_nowait(item)
            return
        except queue.Full:
            dropped = False
            try:
                work.get_nowait()
                dropped = True
            except queue.Empty:  # another consumer won the race
                pass
        try:
            work.put_nowait(item)
        except queue.Full:  # another producer refilled it
            dropped = True
        if dropped:
            with self._dropped_lock:
                self._dropped += 1

"""Turn external AV audio into Explicit Request inputs behind one deep seam.

``LiveInputAdapter`` owns the local wake gate, bounded capture and hosted-ASR
decision.  ``SocialAgentRuntime`` sees only its existing ``InputSource``
interface.  The adapter can consume ``AudioStream`` on the vendor AV path or
``WavAudioFixtureSource`` in deterministic no-hardware scenarios.

The vendor path is hardware-unverified: nothing in this project has received
audio from a Misty II.  The local detector is verified only on synthetic WAV
fixtures, not on a robot microphone or in a real room.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Optional, Protocol, Tuple

import numpy as np

from misty_agent.config import Settings, settings as default_settings
from misty_agent.drivers.audio_stream import (
    AudioPipelineEnding,
    AudioPipelineTerminal,
    Segment,
    UtteranceDetector,
    is_silent,
)
from misty_agent.perception.listening import ListeningEnding, ListeningResult
from misty_agent.perception.asr import (
    Transcription,
    TranscriptionEnding,
    wav_to_pcm,
)
from misty_agent.perception.wake import WakeDetector, WakeMatch
from misty_agent.runtime import (
    AudioAttentionNotice,
    AudioAttentionOutcome,
    AudioAttentionStage,
    EvidenceKind,
    InputArrival,
    TimedText,
)


class AudioSegmentSource(Protocol):
    """The bounded raw-audio interface required by the wake adapter."""

    def start(self) -> None: ...

    def read_segment(self, timeout: float) -> Optional[Segment]: ...

    def take_dropped(self) -> int: ...

    def take_terminal(self) -> Optional[AudioPipelineTerminal]: ...

    @property
    def exhausted(self) -> bool: ...

    def stop(self) -> None: ...


class BoundedTranscriber(Protocol):
    def transcribe_bounded(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        *,
        timeout_s: float,
    ) -> Transcription: ...


class AudioSourceFailure(RuntimeError):
    """The audio provider ended abnormally after its typed notice was read."""


@dataclass(frozen=True)
class _PendingWake:
    match: WakeMatch
    observed_at: float
    facts: dict[str, Any]
    expires_at: float


@dataclass(frozen=True)
class _ObservedInput:
    item: AudioAttentionNotice | TimedText
    observed_at: float


class LiveInputAdapter:
    """Gate AV audio locally and expose only qualified Runtime inputs.

    ``read`` may block inside the supplied audio adapter. ``read_available``
    never blocks. This adapter creates no thread; queue ownership and
    backpressure remain with the audio stream that receives AV data.
    """

    def __init__(
        self,
        *,
        audio: AudioSegmentSource,
        wake_detector: WakeDetector,
        transcriber: BoundedTranscriber,
        clock,
        config: Settings = default_settings,
        sample_rate: int = 16_000,
    ) -> None:
        self._audio = audio
        self._wake_detector = wake_detector
        self._transcriber = transcriber
        self._clock = clock
        self._config = config
        self._sample_rate = sample_rate
        self._ready: Deque[_ObservedInput] = deque()
        self._pending_wake: Optional[_PendingWake] = None
        self._source_failure: Optional[AudioSourceFailure] = None
        self._started = False
        self._stopped = threading.Event()

    def start(self) -> None:
        if self._started:
            raise RuntimeError("this live input adapter has already started")
        self._started = True
        self._audio.start()

    def read(self) -> Optional[InputArrival]:
        self._require_running()
        while not self._stopped.is_set():
            self._collect_drops()
            if self._ready:
                return self._take_ready()
            self._raise_source_failure()
            segment = self._audio.read_segment(timeout=0.05)
            if segment is not None:
                self._process(segment)
                continue
            self._collect_terminal()
            self._expire_pending(force=self._audio.exhausted)
            if self._ready:
                continue
            if self._audio.exhausted:
                return None
        return None

    def read_available(self) -> Tuple[InputArrival, ...]:
        self._require_running()
        self._collect_drops()
        while True:
            segment = self._audio.read_segment(timeout=0.0)
            if segment is None:
                break
            self._process(segment)
            self._collect_drops()
        self._collect_terminal()
        if self._source_failure is not None and not self._ready:
            self._raise_source_failure()
        self._expire_pending(force=self._audio.exhausted)
        ready = tuple(self._take_ready() for _ in range(len(self._ready)))
        if not ready:
            self._raise_source_failure()
        return ready

    def stop(self) -> None:
        self._stopped.set()
        self._audio.stop()

    def poll_utterance(self, *, timeout_s: float):
        """A listen Tool authorises one ASR attempt, without another wake.

        Called by the single Episode owner, never in parallel with Attention.
        An already pending wake remains Attention's; listen cannot steal it.
        """
        self._require_running()
        if self._pending_wake is not None:
            return ListeningResult(ListeningEnding.UNAVAILABLE, source="pending_wake")
        segment = self._audio.read_segment(timeout=0)
        if segment is None:
            self._collect_terminal()
            self._raise_source_failure()
            return None
        age = max(0.0, self._clock.monotonic() - segment.ended_at)
        if age > 5.0 or is_silent(segment.pcm, self._config.silence_threshold_db):
            return None
        max_samples = round(self._config.max_utterance_s * self._sample_rate)
        attempt = self._transcriber.transcribe_bounded(
            segment.pcm[:max_samples], self._sample_rate,
            timeout_s=min(timeout_s, self._config.asr_timeout_s),
        )
        if attempt.ending is not TranscriptionEnding.TRANSCRIBED:
            return ListeningResult(ListeningEnding.ERROR, source="hosted_asr")
        if not attempt.text.strip():
            return ListeningResult(ListeningEnding.SILENCE, source="hosted_asr")
        return ListeningResult(
            ListeningEnding.HEARD, attempt.text.strip()[:4000], source="hosted_asr",
            age_s=max(0.0, self._clock.monotonic() - segment.ended_at),
        )

    @property
    def exhausted(self) -> bool:
        """Whether a finite provider has no notices or cues left to emit."""
        return (
            self._audio.exhausted
            and self._source_failure is None
            and self._pending_wake is None
            and not self._ready
        )

    def _require_running(self) -> None:
        if not self._started or self._stopped.is_set():
            raise RuntimeError("live input adapter is not running")

    def _collect_drops(self) -> None:
        dropped = self._audio.take_dropped()
        if dropped:
            self._emit(
                AudioAttentionNotice(
                    stage=AudioAttentionStage.BACKLOG,
                    outcome=AudioAttentionOutcome.BACKLOG_DROPPED,
                    facts={"dropped": dropped},
                ),
                observed_at=self._clock.monotonic(),
            )

    def _collect_terminal(self) -> None:
        terminal = self._audio.take_terminal()
        if terminal is None:
            return
        outcome = (
            AudioAttentionOutcome.SOURCE_ERROR
            if terminal.ending is AudioPipelineEnding.ERROR
            else AudioAttentionOutcome.SOURCE_ENDED
        )
        self._emit(
            AudioAttentionNotice(
                stage=AudioAttentionStage.SOURCE,
                outcome=outcome,
                facts=(
                    {"error_type": terminal.error_type}
                    if terminal.error_type
                    else {}
                ),
            ),
            observed_at=self._clock.monotonic(),
        )
        if terminal.ending is AudioPipelineEnding.ERROR:
            detail = terminal.error_type or "unknown audio source failure"
            self._source_failure = AudioSourceFailure(detail)

    def _raise_source_failure(self) -> None:
        if self._source_failure is not None:
            raise self._source_failure

    def _process(self, segment: Segment) -> None:
        if self._pending_wake is not None:
            if segment.started_at > self._pending_wake.expires_at:
                self._expire_pending(force=True)
            else:
                self._continue_capture(segment)
                return

        match = self._wake_detector.detect(segment.pcm, self._sample_rate)
        if match is None:
            self._emit(
                AudioAttentionNotice(
                    stage=AudioAttentionStage.WAKE,
                    outcome=AudioAttentionOutcome.NO_MATCH,
                ),
                observed_at=segment.ended_at,
            )
            return

        self._accept_wake(
            segment,
            match,
            outcome=AudioAttentionOutcome.MATCHED,
        )

    def _accept_wake(
        self,
        segment: Segment,
        match: WakeMatch,
        *,
        outcome: AudioAttentionOutcome,
    ) -> None:
        """Record one wake and make it the sole pending capture owner."""
        wake_at = segment.started_at + match.end_sample / self._sample_rate
        wake_facts = {
            "wake_phrase": match.phrase.value,
            "confidence": round(match.confidence, 3),
            "detector": "pocketsphinx-local",
        }
        self._emit(
            AudioAttentionNotice(
                stage=AudioAttentionStage.WAKE,
                outcome=outcome,
                facts=wake_facts,
            ),
            observed_at=wake_at,
        )

        self._pending_wake = _PendingWake(
            match=match,
            observed_at=wake_at,
            facts=wake_facts,
            expires_at=wake_at + self._config.silence_timeout_s,
        )
        captured = np.asarray(segment.pcm[match.end_sample:], dtype=np.float32)
        if captured.size == 0:
            return
        if is_silent(captured, self._config.silence_threshold_db):
            return
        self._finish_capture(captured, observed_at=segment.ended_at)

    def _continue_capture(self, segment: Segment) -> None:
        pending = self._pending_wake
        assert pending is not None
        repeated = self._wake_detector.detect(segment.pcm, self._sample_rate)
        if repeated is not None:
            self._accept_wake(
                segment,
                repeated,
                outcome=AudioAttentionOutcome.REPEATED_WAKE,
            )
            return
        captured = np.asarray(segment.pcm, dtype=np.float32)

        if captured.size == 0:
            return
        if is_silent(captured, self._config.silence_threshold_db):
            return
        self._finish_capture(captured, observed_at=segment.ended_at)

    def _finish_capture(
        self, captured: np.ndarray, *, observed_at: float
    ) -> None:
        pending = self._pending_wake
        assert pending is not None
        max_samples = round(
            self._config.max_utterance_s * self._sample_rate
        )
        was_limited = captured.size > max_samples
        captured = captured[:max_samples]
        capture_outcome = (
            AudioAttentionOutcome.MAX_DURATION
            if was_limited
            else AudioAttentionOutcome.CAPTURED
        )
        self._emit(
            AudioAttentionNotice(
                stage=AudioAttentionStage.CAPTURE,
                outcome=capture_outcome,
                facts={
                    "duration_s": round(
                        captured.size / self._sample_rate, 3
                    )
                },
            ),
            observed_at=observed_at,
        )
        # A wake authorises exactly one hosted attempt. Clear the state before
        # crossing that boundary so timeout/error cannot consume later audio.
        self._pending_wake = None
        try:
            attempt = self._transcriber.transcribe_bounded(
                captured,
                self._sample_rate,
                timeout_s=self._config.asr_timeout_s,
            )
        except Exception as exc:
            attempt = Transcription(
                text="",
                ending=TranscriptionEnding.ERROR,
                error_type=type(exc).__name__,
            )
        asr_outcome = {
            TranscriptionEnding.TRANSCRIBED: AudioAttentionOutcome.TRANSCRIBED,
            TranscriptionEnding.EMPTY: AudioAttentionOutcome.ASR_EMPTY,
            TranscriptionEnding.TIMEOUT: AudioAttentionOutcome.ASR_TIMEOUT,
            TranscriptionEnding.ERROR: AudioAttentionOutcome.ASR_ERROR,
        }[attempt.ending]
        self._emit(
            AudioAttentionNotice(
                stage=AudioAttentionStage.ASR,
                outcome=asr_outcome,
                facts=(
                    {"error_type": attempt.error_type}
                    if attempt.error_type
                    else {}
                ),
            ),
            observed_at=self._clock.monotonic(),
        )
        if attempt.ending is not TranscriptionEnding.TRANSCRIBED:
            return
        self._emit(
            TimedText(
                text=attempt.text,
                evidence_kind=EvidenceKind.SPEECH,
                facts={**pending.facts, "capture": capture_outcome.value},
                uncertainty=(
                    "local wake detection is verified only on synthetic fixtures",
                ),
                deduplication_key=f"wake:{pending.match.phrase.value}",
            ),
            observed_at=pending.observed_at,
        )

    def _expire_pending(self, *, force: bool) -> None:
        pending = self._pending_wake
        if pending is None:
            return
        now = self._clock.monotonic()
        if not force and now < pending.expires_at:
            return
        outcome = (
            AudioAttentionOutcome.EMPTY_UTTERANCE
            if force and now < pending.expires_at
            else AudioAttentionOutcome.SILENCE_TIMEOUT
        )
        self._emit_capture_ending(outcome)

    def _emit_capture_ending(self, outcome: AudioAttentionOutcome) -> None:
        pending = self._pending_wake
        assert pending is not None
        self._emit(
            AudioAttentionNotice(
                stage=AudioAttentionStage.CAPTURE,
                outcome=outcome,
                facts={"wake_phrase": pending.match.phrase.value},
            ),
            observed_at=self._clock.monotonic(),
        )
        self._pending_wake = None

    def _emit(
        self,
        item: AudioAttentionNotice | TimedText,
        *,
        observed_at: float,
    ) -> None:
        if self._clock.monotonic() - observed_at < -1e-9:
            raise ValueError("audio observation cannot be in the future")
        self._ready.append(_ObservedInput(item=item, observed_at=observed_at))

    def _take_ready(self) -> InputArrival:
        observed = self._ready.popleft()
        age_s = self._clock.monotonic() - observed.observed_at
        if age_s < -1e-9:
            raise ValueError("audio observation cannot be in the future")
        return InputArrival(age_s=max(0.0, age_s), input=observed.item)


class WavAudioFixtureSource:
    """A synthetic WAV passed through the same local VAD state machine."""

    def __init__(
        self,
        path: Path,
        *,
        clock,
        detector: Optional[UtteranceDetector] = None,
    ) -> None:
        self._path = path
        self._clock = clock
        self._detector = detector
        self._segments: Deque[tuple[Segment, float]] = deque()
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("this WAV fixture source has already started")
        self._started = True
        pcm, sample_rate = wav_to_pcm(self._path.read_bytes())
        if sample_rate != 16_000:
            raise ValueError("wake fixtures must be 16 kHz PCM WAV")
        began = self._clock.monotonic()
        detector = self._detector or UtteranceDetector(
            sample_rate=sample_rate,
            max_utterance_s=default_settings.max_utterance_s,
        )
        block_samples = round(0.02 * sample_rate)
        for offset in range(0, pcm.size, block_samples):
            block = pcm[offset : offset + block_samples]
            segment = detector.push(
                began + offset / sample_rate,
                block,
            )
            if segment is not None:
                available_at = began + (offset + block.size) / sample_rate
                self._segments.append((segment, available_at))
        file_ended_at = began + pcm.size / sample_rate
        final = detector.timed_out(file_ended_at)
        if final is not None:
            self._segments.append((final, file_ended_at))

    def read_segment(self, timeout: float) -> Optional[Segment]:
        if not self._started or self._stopped:
            raise RuntimeError("WAV fixture source is not running")
        if not self._segments:
            return None
        if timeout < 0:
            raise ValueError("audio read timeout cannot be negative")
        segment, available_at = self._segments[0]
        wait_s = max(0.0, available_at - self._clock.monotonic())
        if wait_s > timeout:
            if timeout:
                self._clock.sleep(timeout)
            return None
        self._segments.popleft()
        if wait_s:
            self._clock.sleep(wait_s)
        return segment

    def take_dropped(self) -> int:
        return 0

    def take_terminal(self) -> Optional[AudioPipelineTerminal]:
        return None

    @property
    def exhausted(self) -> bool:
        return self._started and not self._segments

    def stop(self) -> None:
        self._stopped = True


__all__ = [
    "AudioSegmentSource",
    "AudioSourceFailure",
    "BoundedTranscriber",
    "LiveInputAdapter",
    "WavAudioFixtureSource",
]

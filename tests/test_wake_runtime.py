"""Ticket 04 acceptance coverage through ``SocialAgentRuntime``.

The seam is the same one used by every other Interaction Cue.  Audio is not
allowed to open an Episode directly: it must cross the local wake gate, become
typed Trigger Evidence, and only then reach the first model Turn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pytest

from misty_agent.agent.react import Decision
from misty_agent.app import simulated_session
from misty_agent.audio_input import LiveInputAdapter, WavAudioFixtureSource
from misty_agent.config import Settings
from misty_agent.drivers.audio_stream import (
    AudioPipelineEnding,
    AudioPipelineTerminal,
    Segment,
)
from misty_agent.fakes import FakeClock
from misty_agent.perception.asr import (
    Transcription,
    TranscriptionEnding,
    wav_to_pcm,
)
from misty_agent.perception.wake import (
    PocketSphinxWakeDetector,
    WakeMatch,
    WakePhrase,
)
from misty_agent.runtime import (
    AudioAttentionRecorded,
    RuntimeEnding,
    RuntimeFailed,
    SocialAgentRuntime,
)
from misty_agent.scenarios import ScenarioModel


FIXTURES = Path(__file__).parent / "fixtures" / "wake"


class ScriptedTranscriber:
    def __init__(
        self,
        text: str = "Hello Misty",
        ending: TranscriptionEnding = TranscriptionEnding.TRANSCRIBED,
        error_type: Optional[str] = None,
    ) -> None:
        self.calls = []
        self._result = Transcription(
            text=text, ending=ending, error_type=error_type
        )

    def transcribe_bounded(self, pcm, sample_rate, *, timeout_s):
        self.calls.append((pcm.copy(), sample_rate, timeout_s))
        return self._result


class CapturesFirstTurn(ScenarioModel):
    def __init__(self) -> None:
        super().__init__(
            (
                Decision(
                    tool="speak",
                    args={"text": "Hi!"},
                    tokens_in=12,
                    tokens_out=3,
                ),
                Decision(tool="done", args={}, tokens_in=12, tokens_out=1),
            )
        )
        self.contexts = []

    def decide(self, working_context, tools):
        self.contexts.append(tuple(working_context))
        return super().decide(working_context, tools)


def run_fixture(name: str):
    clock = FakeClock()
    transcriber = ScriptedTranscriber()
    model = CapturesFirstTurn()
    source = WavAudioFixtureSource(FIXTURES / name, clock=clock)
    runtime = SocialAgentRuntime(
        source=LiveInputAdapter(
            audio=source,
            wake_detector=PocketSphinxWakeDetector(),
            transcriber=transcriber,
            clock=clock,
        ),
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    )
    return runtime.run(), transcriber, model


def audio_records(result):
    return [
        (record.stage.value, record.outcome.value)
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
    ]


class SequenceAudioSource:
    """Finite deterministic source for multi-segment attention cases."""

    def __init__(self, names, *, clock, dropped=0, final_delay=0.0):
        self._clock = clock
        self._names = iter(names)
        self._dropped = dropped
        self._final_delay = final_delay
        self._exhausted = False
        self._started = False

    def start(self):
        self._started = True

    def read_segment(self, timeout):
        assert self._started
        try:
            name = next(self._names)
        except StopIteration:
            self._clock.sleep(self._final_delay)
            self._exhausted = True
            return None
        pcm, rate = wav_to_pcm((FIXTURES / name).read_bytes())
        assert rate == 16_000
        began = self._clock.monotonic()
        duration = pcm.size / rate
        self._clock.sleep(duration)
        return Segment(pcm, began, began + duration)

    def take_dropped(self):
        dropped, self._dropped = self._dropped, 0
        return dropped

    def take_terminal(self):
        return None

    @property
    def exhausted(self):
        return self._exhausted

    def stop(self):
        pass


def run_source(
    source,
    *,
    clock,
    transcriber=None,
    detector=None,
    config=None,
):
    transcriber = transcriber or ScriptedTranscriber()
    model = CapturesFirstTurn()
    runtime = SocialAgentRuntime(
        source=LiveInputAdapter(
            audio=source,
            wake_detector=detector or PocketSphinxWakeDetector(),
            transcriber=transcriber,
            clock=clock,
            config=config or Settings(),
        ),
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    )
    return runtime.run(), transcriber, model


@pytest.mark.parametrize(
    ("fixture", "phrase"),
    [
        ("hey_misty_normal.wav", "hey misty"),
        ("hi_misty_slow.wav", "hi misty"),
        ("hey_misty_fast.wav", "hey misty"),
        ("hey_misty_pause.wav", "hey misty"),
    ],
)
def test_a_local_wake_phrase_opens_one_bounded_episode(fixture, phrase):
    result, transcriber, model = run_fixture(fixture)

    assert len(result.episodes) == 1
    assert len(transcriber.calls) == 1
    evidence = next(
        item for item in model.contexts[0] if item["role"] == "user"
    )["content"][0]["text"]["trigger_evidence"]
    assert evidence["transcript"] == "Hello Misty"
    assert evidence["facts"]["wake_phrase"] == phrase
    assert audio_records(result) == [
        ("wake", "matched"),
        ("capture", "captured"),
        ("asr", "transcribed"),
    ]


def test_ambient_speech_neither_opens_an_episode_nor_reaches_hosted_asr():
    result, transcriber, _ = run_fixture("ambient_question.wav")

    assert result.episodes == ()
    assert transcriber.calls == []
    assert audio_records(result) == [("wake", "no_match")]


def test_a_finite_wake_fixture_without_a_request_ends_as_empty():
    result, transcriber, _ = run_fixture("hey_misty_only.wav")

    assert result.episodes == ()
    assert transcriber.calls == []
    assert audio_records(result) == [
        ("wake", "matched"),
        ("capture", "empty_utterance"),
    ]


def test_waiting_after_wake_cannot_outlive_the_silence_timeout():
    clock = FakeClock()
    source = SequenceAudioSource(
        ("hey_misty_only.wav",), clock=clock, final_delay=5.0
    )

    result, transcriber, _ = run_source(source, clock=clock)

    assert result.episodes == ()
    assert transcriber.calls == []
    assert audio_records(result)[-1] == ("capture", "silence_timeout")


def test_a_repeated_wake_is_observable_but_still_opens_only_one_episode():
    clock = FakeClock()
    source = SequenceAudioSource(
        ("hey_misty_only.wav", "hi_misty_slow.wav"), clock=clock
    )

    result, transcriber, _ = run_source(source, clock=clock)

    assert len(result.episodes) == 1
    assert len(transcriber.calls) == 1
    assert audio_records(result) == [
        ("wake", "matched"),
        ("wake", "repeated_wake"),
        ("capture", "captured"),
        ("asr", "transcribed"),
    ]


@pytest.mark.parametrize(
    ("ending", "error_type", "outcome"),
    [
        (TranscriptionEnding.EMPTY, None, "asr_empty"),
        (TranscriptionEnding.TIMEOUT, "APITimeoutError", "asr_timeout"),
        (TranscriptionEnding.ERROR, "ConnectionError", "asr_error"),
    ],
)
def test_every_non_transcript_asr_ending_is_bounded_and_observable(
    ending, error_type, outcome
):
    clock = FakeClock()
    transcriber = ScriptedTranscriber(
        text="", ending=ending, error_type=error_type
    )
    source = WavAudioFixtureSource(
        FIXTURES / "hey_misty_normal.wav", clock=clock
    )

    result, transcriber, _ = run_source(
        source, clock=clock, transcriber=transcriber
    )

    assert result.episodes == ()
    assert len(transcriber.calls) == 1
    assert audio_records(result)[-1] == ("asr", outcome)


def test_an_unexpected_asr_exception_is_closed_as_an_observable_error():
    class ExplodingTranscriber:
        def transcribe_bounded(self, pcm, sample_rate, *, timeout_s):
            raise ConnectionError("offline")

    clock = FakeClock()
    source = WavAudioFixtureSource(
        FIXTURES / "hey_misty_normal.wav", clock=clock
    )

    result, _, _ = run_source(
        source, clock=clock, transcriber=ExplodingTranscriber()
    )

    assert result.episodes == ()
    error = next(
        record
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
        and record.outcome.value == "asr_error"
    )
    assert error.facts == {"error_type": "ConnectionError"}


def test_observation_times_do_not_move_forward_during_hosted_asr():
    clock = FakeClock()

    class SlowTranscriber(ScriptedTranscriber):
        def transcribe_bounded(self, pcm, sample_rate, *, timeout_s):
            clock.sleep(2.0)
            return super().transcribe_bounded(
                pcm, sample_rate, timeout_s=timeout_s
            )

    source = WavAudioFixtureSource(
        FIXTURES / "hey_misty_normal.wav", clock=clock
    )

    result, _, _ = run_source(
        source, clock=clock, transcriber=SlowTranscriber()
    )

    wake, _, asr = [
        record
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
    ]
    assert asr.t - wake.t >= 2.0


def test_fixture_nonblocking_read_does_not_consume_future_audio():
    clock = FakeClock()
    source = WavAudioFixtureSource(
        FIXTURES / "hey_misty_normal.wav", clock=clock
    )
    source.start()

    assert source.read_segment(timeout=0.0) is None
    assert clock.monotonic() == 0.0
    assert source.read_segment(timeout=0.05) is None
    assert clock.monotonic() == pytest.approx(0.05)


class StartsWithWake:
    def detect(self, pcm, sample_rate):
        return WakeMatch(WakePhrase.HEY_MISTY, 1.0, 1)


def test_capture_is_cut_at_the_maximum_before_hosted_asr():
    clock = FakeClock()
    source = SequenceAudioSource(("hey_misty_normal.wav",), clock=clock)
    config = Settings(max_utterance_s=0.25)

    result, transcriber, _ = run_source(
        source, clock=clock, detector=StartsWithWake(), config=config
    )

    assert len(result.episodes) == 1
    assert transcriber.calls[0][0].size == 4_000
    assert ("capture", "max_duration") in audio_records(result)


def test_audio_backlog_loss_is_reported_before_processing_continues():
    clock = FakeClock()
    source = SequenceAudioSource(
        ("hey_misty_normal.wav",), clock=clock, dropped=7
    )

    result, _, _ = run_source(source, clock=clock)

    assert len(result.episodes) == 1
    assert audio_records(result)[0] == ("backlog", "backlog_dropped")
    backlog = next(
        record
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
        and record.outcome.value == "backlog_dropped"
    )
    assert backlog.facts == {"dropped": 7}


def test_audio_source_failure_is_bounded_and_observable():
    class FailedAudioSource:
        def __init__(self):
            self._terminal = AudioPipelineTerminal(
                AudioPipelineEnding.ERROR,
                error_type="ConnectionError",
            )

        def start(self):
            pass

        def read_segment(self, timeout):
            return None

        def take_dropped(self):
            return 0

        def take_terminal(self):
            terminal, self._terminal = self._terminal, None
            return terminal

        @property
        def exhausted(self):
            return True

        def stop(self):
            pass

    clock = FakeClock()

    result, transcriber, _ = run_source(FailedAudioSource(), clock=clock)

    assert result.episodes == ()
    assert result.ending is RuntimeEnding.RUNTIME_ERROR
    assert transcriber.calls == []
    source_record = next(
        record
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
    )
    assert (source_record.stage.value, source_record.outcome.value) == (
        "source",
        "source_error",
    )
    assert source_record.facts == {"error_type": "ConnectionError"}
    failure = next(
        record for record in result.records if isinstance(record, RuntimeFailed)
    )
    assert failure.error_type == "AudioSourceFailure"

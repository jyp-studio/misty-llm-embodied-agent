"""Bounded speech acquisition, without changing the cheap Snapshot."""

from types import SimpleNamespace

from misty_agent.fakes import FakeClock
from misty_agent.perception.listening import BoundedListener, TranscriptSource


def test_listen_waits_for_new_speech_and_reports_silence_without_inventing_words():
    clock = FakeClock()

    class Ears:
        def read(self, timeout):
            if clock.monotonic() >= 0.2:
                return SimpleNamespace(text="安靜陪我就好")

    heard = BoundedListener(TranscriptSource(Ears()), clock).listen(timeout_s=1)
    assert heard.ending.value == "heard"
    assert heard.transcript == "安靜陪我就好"
    assert heard.age_s == 0
    assert 0.2 <= clock.monotonic() < 1

    silent = BoundedListener(None, clock).listen(timeout_s=1)
    assert silent.ending.value == "unavailable"
    assert silent.transcript is None


def test_live_audio_listen_transcribes_one_bounded_segment_without_a_second_wake():
    import numpy as np
    from misty_agent.audio_input import LiveInputAdapter
    from misty_agent.config import Settings
    from misty_agent.drivers.audio_stream import Segment
    from misty_agent.perception.asr import Transcription, TranscriptionEnding

    clock = FakeClock()

    class Audio:
        def start(self):
            pass

        def read_segment(self, timeout):
            return Segment(np.ones(16000, dtype=np.float32), 0, 0)

    class NoWake:
        def detect(self, *args):
            raise AssertionError("An explicit listen does not need another wake")

    class ASR:
        def transcribe_bounded(self, pcm, rate, *, timeout_s):
            assert 0 < timeout_s <= 1
            return Transcription("請安靜陪我", TranscriptionEnding.TRANSCRIBED)

    source = LiveInputAdapter(audio=Audio(), wake_detector=NoWake(), transcriber=ASR(), clock=clock, config=Settings())
    source.start()
    result = BoundedListener(source, clock).listen(timeout_s=1)
    assert result.ending.value == "heard"
    assert result.transcript == "請安靜陪我"
    assert result.source == "hosted_asr"


def test_silence_is_bounded_by_the_injected_clock_and_stop_interrupts_wait():
    clock = FakeClock()

    class Quiet:
        def poll_utterance(self, *, timeout_s):
            assert 0 < timeout_s <= 0.3
            return None

    result = BoundedListener(Quiet(), clock).listen(timeout_s=0.3)
    assert result.ending.value == "silence"
    assert clock.monotonic() == 0.3
    assert result.transcript is None

    class Stop:
        def requested(self):
            return clock.monotonic() >= 0.4

    stopped = BoundedListener(Quiet(), clock, Stop()).listen(timeout_s=0.3)
    assert stopped.ending.value == "aborted"
    assert clock.monotonic() < 0.6


def test_source_error_is_not_silence_or_an_invented_answer():
    class Broken:
        def poll_utterance(self, *, timeout_s):
            raise OSError("microphone unavailable")

    result = BoundedListener(Broken(), FakeClock()).listen(timeout_s=1)
    assert result.ending.value == "error"
    assert result.transcript is None

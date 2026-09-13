"""Contract tests for misty_agent.drivers.

What these prove: the requests this code emits match the shapes documented at
https://docs.mistyrobotics.com/misty-ii/reference/rest/ and
https://docs.mistyrobotics.com/misty-ii/robot/sensor-data/ — endpoint paths,
JSON bodies, and websocket frames.

What these do not prove: that a Misty II answers them, or does what the
documentation says it does. No hardware exists for this project (PLAN.md §1),
and no line of the driver layer has ever run against a robot. That distinction
belongs in the README, not just here.

Two of the assertions below are regressions for defects found while rewriting
the layer, both of which would have made a real robot silently ignore us:

* the AV reset used undocumented endpoints (``avstreaming/disable``,
  ``audio/recording/stop``);
* the websocket subscribe frame was serialised with ``str(dict)``, which is
  not JSON.
"""

import json

import io
import wave

import numpy as np
import pytest

from misty_agent.config import Settings
from misty_agent.drivers.audio_stream import (
    AudioPipelineEnding,
    AudioStream,
    Segment,
    UtteranceDetector,
    is_silent,
)
from misty_agent.drivers.av_stream import (
    AvSession,
    CapturedFrame,
    RtspVideoStream,
    VideoSource,
)
from misty_agent.drivers.events import (
    event_condition,
    subscribe_message,
    unsubscribe_message,
)
from misty_agent.fakes import RecordingCommands
from misty_agent.perception.asr import (
    OpenAITranscriber,
    TranscriptionEnding,
    pcm_to_wav,
)


# ---------------------------------------------------------------------------
# AvSession — REST contract
# ---------------------------------------------------------------------------

def _session(commands, **kwargs):
    return AvSession(commands, reset_settle_s=0.0, **kwargs)


def test_open_resets_then_enables_then_starts():
    commands = RecordingCommands("10.0.0.5")

    _session(commands).open()

    assert commands.endpoints == [
        "services/avstreaming/disable",
        "audio/record/stop",
        "services/avstreaming/enable",
        "avstreaming/start",
    ]


def test_reset_uses_the_documented_endpoints():
    # The application layer previously POSTed to `avstreaming/disable` and
    # `audio/recording/stop` by hand. Neither path is in the REST reference.
    commands = RecordingCommands()

    _session(commands).open()

    assert "avstreaming/disable" not in commands.endpoints
    assert "audio/recording/stop" not in commands.endpoints


def test_start_av_streaming_body_matches_the_rest_reference():
    commands = RecordingCommands()

    _session(commands, port=1935, width=640, height=480).open()

    request = commands.last("avstreaming/start")
    assert request.verb == "post"
    assert request.body_without_defaults() == {
        "url": "rtspd:1935",
        "width": 640,
        "height": 480,
    }


def test_open_returns_the_rtsp_url_for_the_configured_port():
    commands = RecordingCommands("192.168.1.237")

    assert _session(commands, port=1935).open() == "rtsp://192.168.1.237:1935"


def test_open_is_idempotent():
    commands = RecordingCommands()
    session = _session(commands)

    first = session.open()
    commands.clear()
    second = session.open()

    assert first == second
    assert commands.requests == []


def test_open_raises_when_the_robot_refuses_to_enable():
    commands = RecordingCommands(fail_endpoints=["services/avstreaming/enable"])

    with pytest.raises(RuntimeError, match="enable"):
        _session(commands).open()


def test_open_raises_when_the_robot_refuses_to_start():
    commands = RecordingCommands(fail_endpoints=["avstreaming/start"])

    with pytest.raises(RuntimeError, match="start"):
        _session(commands).open()


def test_a_failed_open_leaves_no_url_behind():
    commands = RecordingCommands(fail_endpoints=["avstreaming/start"])
    session = _session(commands)

    with pytest.raises(RuntimeError):
        session.open()

    assert session.url is None


def test_reset_failures_do_not_abort_the_session():
    # A robot that has never streamed refuses the teardown. That is not an error.
    commands = RecordingCommands(fail_endpoints=["services/avstreaming/disable"])

    assert _session(commands).open().startswith("rtsp://")


def test_close_stops_streaming_and_forgets_the_url():
    commands = RecordingCommands()
    session = _session(commands)
    session.open()

    session.close()

    assert commands.endpoints[-1] == "avstreaming/stop"
    assert session.url is None


def test_close_without_open_is_safe():
    _session(RecordingCommands()).close()


# ---------------------------------------------------------------------------
# VideoSource
# ---------------------------------------------------------------------------

def test_rtsp_stream_satisfies_the_video_source_interface():
    stream = RtspVideoStream(_session(RecordingCommands()))

    assert isinstance(stream, VideoSource)


def test_an_unstarted_stream_reads_nothing_rather_than_raising():
    stream = RtspVideoStream(_session(RecordingCommands()))

    assert stream.read(timeout=0.01) is None
    assert stream.backlog == 0


def test_flush_on_an_empty_stream_is_safe():
    RtspVideoStream(_session(RecordingCommands())).flush()


@pytest.mark.parametrize("degrees", [45, -90, 360, 1])
def test_an_unsupported_rotation_is_rejected_at_construction(degrees):
    with pytest.raises(ValueError, match="rotate_degrees"):
        RtspVideoStream(_session(RecordingCommands()), rotate_degrees=degrees)


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_the_supported_rotations_are_accepted(degrees):
    RtspVideoStream(_session(RecordingCommands()), rotate_degrees=degrees)


def test_frame_age_is_measured_from_process_arrival():
    frame = CapturedFrame(image=np.zeros((2, 2, 3), dtype=np.uint8), arrived_at=100.0)

    assert frame.age_s(now=100.75) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Events — websocket contract
# ---------------------------------------------------------------------------

def test_subscribe_message_matches_the_sensor_data_reference():
    assert subscribe_message("BumpSensor", "estop-1", debounce_ms=1000) == {
        "Operation": "subscribe",
        "Type": "BumpSensor",
        "DebounceMs": 1000,
        "EventName": "estop-1",
        "Message": "",
    }


def test_conditions_are_attached_only_when_present():
    condition = [event_condition("isContacted", "=", True)]

    with_condition = subscribe_message("BumpSensor", "e", condition=condition)
    without = subscribe_message("BumpSensor", "e")

    assert with_condition["EventConditions"] == [
        {"Property": "isContacted", "Inequality": "=", "Value": True}
    ]
    assert "EventConditions" not in without


def test_unsubscribe_message_matches_the_sensor_data_reference():
    assert unsubscribe_message("estop-1") == {
        "Operation": "unsubscribe",
        "EventName": "estop-1",
        "Message": "",
    }


def test_subscribe_frames_serialise_as_json():
    # Regression: the original sent `str(dict)`, whose single quotes are not
    # JSON and which renders Python's True as `True`, not `true`.
    frame = json.dumps(
        subscribe_message(
            "BumpSensor",
            "estop-1",
            condition=[event_condition("isContacted", "=", True)],
        )
    )

    assert "'" not in frame
    assert '"Value": true' in frame
    assert json.loads(frame)["Operation"] == "subscribe"


# ---------------------------------------------------------------------------
# Speech recognition — WAV encoding
# ---------------------------------------------------------------------------

def _wav_header(data: bytes) -> dict:
    import io
    import wave

    with wave.open(io.BytesIO(data), "rb") as wav:
        return {
            "channels": wav.getnchannels(),
            "sample_width": wav.getsampwidth(),
            "frame_rate": wav.getframerate(),
            "frames": wav.getnframes(),
        }


def test_a_wav_comes_back_as_the_samples_that_went_in():
    """`wav_to_pcm` is `pcm_to_wav` backwards, and M8 #10 is its caller: a
    browser hands over a file, the transcriber takes samples."""
    from misty_agent.perception.asr import wav_to_pcm

    spoken = np.linspace(-0.8, 0.8, 480, dtype=np.float32)

    heard, rate = wav_to_pcm(pcm_to_wav(spoken, 16000))

    assert rate == 16000
    assert heard.shape == spoken.shape
    assert np.allclose(heard, spoken, atol=1e-4)


def test_two_channels_are_averaged_rather_than_half_of_them_dropped():
    """A stereo recording of one person must not lose whichever side they sat
    on. Taking the left channel passes any test that only counts samples."""
    from misty_agent.perception.asr import wav_to_pcm

    left, right = np.full(4, -0.5, np.float32), np.full(4, 0.5, np.float32)
    interleaved = np.empty(8, np.float32)
    interleaved[0::2], interleaved[1::2] = left, right
    stereo = io.BytesIO()
    with wave.open(stereo, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes((interleaved * 32767).astype("<i2").tobytes())

    heard, _ = wav_to_pcm(stereo.getvalue())

    assert heard.shape == (4,)
    assert np.allclose(heard, 0.0, atol=1e-4)


def test_audio_that_is_not_sixteen_bit_is_refused_by_name():
    """Read as 16-bit anyway it becomes noise, and a transcriber given noise
    returns something — which is worse than a refusal."""
    from misty_agent.perception.asr import wav_to_pcm

    eight_bit = io.BytesIO()
    with wave.open(eight_bit, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(1)
        out.setframerate(16000)
        out.writeframes(b"\x80" * 64)

    with pytest.raises(ValueError, match="8-bit audio"):
        wav_to_pcm(eight_bit.getvalue())


def test_wav_encoding_is_mono_16_bit_at_the_source_rate():
    pcm = np.zeros(4410, dtype=np.float32)

    assert _wav_header(pcm_to_wav(pcm, 44100)) == {
        "channels": 1,
        "sample_width": 2,
        "frame_rate": 44100,
        "frames": 4410,
    }


def test_the_source_sample_rate_is_carried_through_rather_than_resampled():
    # The old pipeline decimated 44.1 kHz to 16 kHz without a low-pass filter.
    assert _wav_header(pcm_to_wav(np.zeros(16, dtype=np.float32), 16000))[
        "frame_rate"
    ] == 16000


def test_loud_samples_clip_instead_of_wrapping():
    encoded = pcm_to_wav(np.array([2.0, -2.0], dtype=np.float32), 44100)

    samples = np.frombuffer(encoded[-4:], dtype="<i2")
    assert samples.tolist() == [32767, -32767]


# ---------------------------------------------------------------------------
# Voice activity detection
# ---------------------------------------------------------------------------

SAMPLE_RATE = 1000  # small and exact: 1 sample == 1 ms


def _detector(**kwargs):
    defaults = dict(
        sample_rate=SAMPLE_RATE,
        silence_threshold_db=-40.0,
        silence_duration_s=0.5,
        min_utterance_s=0.3,
        preroll_s=0.1,
    )
    return UtteranceDetector(**{**defaults, **kwargs})


def _loud(samples: int) -> np.ndarray:
    return np.full(samples, 0.5, dtype=np.float32)


def _quiet(samples: int) -> np.ndarray:
    return np.zeros(samples, dtype=np.float32)


def test_digital_silence_is_silent():
    assert is_silent(_quiet(100), threshold_db=-40.0)


def test_speech_is_not_silent():
    assert not is_silent(_loud(100), threshold_db=-40.0)


def test_an_empty_block_is_silent():
    assert is_silent(np.array([], dtype=np.float32), threshold_db=-40.0)


def test_speech_followed_by_enough_silence_closes_an_utterance():
    detector = _detector()

    assert detector.push(0.0, _loud(500)) is None
    segment = detector.push(0.6, _quiet(500))

    assert isinstance(segment, Segment)
    assert segment.started_at == 0.0
    assert segment.ended_at == 0.0  # the last instant speech was heard


def test_a_short_silence_does_not_close_an_utterance():
    detector = _detector()
    detector.push(0.0, _loud(500))

    assert detector.push(0.2, _quiet(200)) is None
    assert detector.speaking


def test_an_utterance_shorter_than_the_minimum_is_discarded():
    detector = _detector(preroll_s=0.0)
    detector.push(0.0, _loud(100))  # 0.1s of speech, minimum is 0.3s

    assert detector.push(0.6, _quiet(100)) is None


def test_the_detector_is_ready_for_the_next_utterance_after_closing_one():
    detector = _detector()
    detector.push(0.0, _loud(500))
    detector.push(0.6, _quiet(500))

    assert not detector.speaking
    assert detector.push(1.0, _loud(500)) is None
    assert detector.speaking


def test_a_stalled_stream_closes_the_utterance_in_progress():
    detector = _detector()
    detector.push(0.0, _loud(500))

    segment = detector.timed_out(at=5.0)

    assert isinstance(segment, Segment)
    assert segment.started_at == 0.0


def test_a_stalled_stream_with_nothing_in_progress_yields_nothing():
    assert _detector().timed_out(at=5.0) is None


def test_idle_audio_is_bounded_by_the_preroll():
    # The code this replaces concatenated every block from process start and
    # emptied only on utterance end, so an idle robot grew without bound.
    detector = _detector(preroll_s=0.1)  # 100 samples at SAMPLE_RATE

    for tick in range(200):
        detector.push(float(tick), _quiet(100))

    assert detector.buffered_samples == 100


def test_the_preroll_is_carried_into_the_utterance():
    detector = _detector(preroll_s=0.1)
    detector.push(0.0, _quiet(500))  # only the last 100 samples survive

    detector.push(1.0, _loud(400))
    segment = detector.push(1.6, _quiet(100))

    assert segment is not None
    # 100 pre-roll + 400 speech + 100 trailing silence
    assert segment.pcm.size == 600
    assert segment.started_at == 0.9


def test_zero_preroll_retains_no_silence():
    detector = _detector(preroll_s=0.0)

    for tick in range(50):
        detector.push(float(tick), _quiet(100))

    assert detector.buffered_samples == 0


def test_the_detector_defaults_to_the_configured_values():
    settings = Settings()
    detector = UtteranceDetector()

    assert detector._silence_threshold_db == settings.silence_threshold_db
    assert detector._min_utterance_s == settings.min_utterance_s


def test_continuous_voice_is_closed_at_the_maximum_utterance_length():
    detector = _detector(preroll_s=0.0, max_utterance_s=0.5)

    assert detector.push(0.0, _loud(300)) is None
    segment = detector.push(0.3, _loud(300))

    assert segment is not None
    assert segment.pcm.size == 500
    assert segment.ended_at == 0.5
    assert not detector.speaking


def test_audio_backpressure_keeps_only_bounded_recent_work():
    stream = AudioStream(
        session=None,
        sample_rate=SAMPLE_RATE,
        block_queue_capacity=2,
        segment_queue_capacity=2,
    )
    for number in range(5):
        stream._offer_block(float(number), _loud(10))
        stream._publish(
            Segment(_loud(10), float(number), float(number) + 0.1)
        )

    first = stream.read_segment(timeout=0)
    second = stream.read_segment(timeout=0)

    assert (first.started_at, second.started_at) == (3.0, 4.0)
    assert stream.read_segment(timeout=0) is None
    assert stream.take_dropped() == 6
    assert stream.take_dropped() == 0


@pytest.mark.parametrize(
    ("block_capacity", "segment_capacity"),
    [(0, 1), (-1, 1), (1, 0), (1, -1)],
)
def test_audio_stream_refuses_a_capacity_that_would_be_unbounded(
    block_capacity, segment_capacity
):
    with pytest.raises(ValueError, match="capacity"):
        AudioStream(
            session=None,
            sample_rate=SAMPLE_RATE,
            block_queue_capacity=block_capacity,
            segment_queue_capacity=segment_capacity,
        )


def test_decoder_failure_becomes_a_typed_terminal_state():
    stream = AudioStream(session=None, sample_rate=SAMPLE_RATE)

    stream._decoder_finished(
        AudioPipelineEnding.ERROR, error_type="ConnectionError"
    )
    stream._vad_done.set()

    terminal = stream.take_terminal()
    assert terminal is not None
    assert terminal.ending is AudioPipelineEnding.ERROR
    assert terminal.error_type == "ConnectionError"
    assert stream.take_terminal() is None


def test_decoder_eof_is_not_exhausted_until_the_vad_worker_finishes():
    stream = AudioStream(session=None, sample_rate=SAMPLE_RATE)

    stream._decoder_finished(AudioPipelineEnding.ENDED)

    assert not stream.exhausted
    stream._vad_done.set()
    assert stream.exhausted


def test_terminal_waits_until_the_last_vad_segment_is_drained():
    stream = AudioStream(session=None, sample_rate=SAMPLE_RATE)
    stream._publish(Segment(_loud(10), 0.0, 0.01))
    stream._decoder_finished(
        AudioPipelineEnding.ERROR, error_type="ConnectionError"
    )
    stream._vad_done.set()

    assert stream.take_terminal() is None
    assert stream.read_segment(timeout=0) is not None
    terminal = stream.take_terminal()
    assert terminal is not None
    assert terminal.ending is AudioPipelineEnding.ERROR


def test_pipeline_terminal_is_delivered_exactly_once():
    stream = AudioStream(session=None, sample_rate=SAMPLE_RATE)
    stream._decoder_finished(
        AudioPipelineEnding.ERROR, error_type="ConnectionError"
    )
    stream._vad_done.set()

    assert stream.take_terminal() is not None
    stream._decoder_finished(AudioPipelineEnding.ENDED)
    assert stream.take_terminal() is None


def test_vad_failure_replaces_a_pending_normal_decoder_ending():
    class ExplodingDetector:
        speaking = False

        def push(self, arrived_at, block):
            raise ValueError("bad samples")

        def timed_out(self, at):
            return None

    stream = AudioStream(
        session=None,
        detector=ExplodingDetector(),
        sample_rate=SAMPLE_RATE,
    )
    stream._offer_block(0.0, _loud(10))
    stream._decoder_finished(AudioPipelineEnding.ENDED)

    stream._detect_loop()

    assert stream._vad_done.is_set()
    terminal = stream.take_terminal()
    assert terminal is not None
    assert terminal.ending is AudioPipelineEnding.ERROR
    assert terminal.error_type == "ValueError"


def test_decoder_eof_flushes_the_last_in_progress_utterance():
    stream = AudioStream(
        session=None,
        detector=_detector(preroll_s=0.0),
        monotonic=lambda: 1.0,
        sample_rate=SAMPLE_RATE,
    )
    stream._offer_block(0.0, _loud(400))
    stream._decoder_finished(AudioPipelineEnding.ENDED)

    stream._detect_loop()

    segment = stream.read_segment(timeout=0)
    assert segment is not None
    assert segment.pcm.size == 400
    terminal = stream.take_terminal()
    assert terminal is not None
    assert terminal.ending is AudioPipelineEnding.ENDED


class _TimeoutClient:
    def __init__(self):
        self.audio = self
        self.transcriptions = self
        self.timeout = None

    def with_options(self, *, timeout, max_retries):
        self.timeout = timeout
        self.max_retries = max_retries
        return self

    def create(self, **kwargs):
        raise TimeoutError("provider took too long")


def test_hosted_asr_timeout_is_named_and_uses_the_configured_bound():
    transcriber = OpenAITranscriber.__new__(OpenAITranscriber)
    transcriber._client = _TimeoutClient()
    transcriber._model = "scripted"
    transcriber._language = "en"
    transcriber._ignored_phrases = ()

    result = transcriber.transcribe_bounded(
        _loud(100), SAMPLE_RATE, timeout_s=1.25
    )

    assert transcriber._client.timeout == 1.25
    assert transcriber._client.max_retries == 0
    assert result.ending is TranscriptionEnding.TIMEOUT
    assert result.error_type == "TimeoutError"

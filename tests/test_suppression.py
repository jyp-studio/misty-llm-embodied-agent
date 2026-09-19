"""Not transcribing yourself, without going deaf to everyone else.

The script this replaces muted perception for the whole action and then slept
through it, so anything the person said while the robot was talking — "no",
"stop", "wrong way" — was gone. The window here covers **playback and nothing
else**, and the moment it lapses an interruption gets through.

## Why this is an estimate at all

`PLAN.md` §4 originally said to use the `spoken_ms` that `speak` returns.
There is no such return value: Misty's TTS answers with nothing about timing
(`PLAN.md` §15.4). So the length of the window is a guess from the text, every
constant behind it is UNCALIBRATED and lives in `Settings`, and the honest
claim is only that the window opens before the sound and closes on schedule.

## Why the clock is injected

Testing a two-second window by waiting two seconds makes a suite that is slow
and, on a loaded machine, wrong. The clock goes in from outside, so "during"
and "after" are two assertions rather than two sleeps.
"""

from __future__ import annotations

import pytest

from misty_agent.agent.tools import (
    _CJK,
    ToolContext,
    build_registry,
    dispatch,
    estimate_speech_ms,
)
from misty_agent.agent.journal import Journal
from misty_agent.config import Settings
from misty_agent.drivers.audio_stream import AudioStream, Segment
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter


class Ticking:
    """A clock that only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def a_stream(clock):
    return AudioStream(
        session=None,
        sample_rate=16000,
        monotonic=clock,
    )


def a_segment(stream, at=0.0):
    import numpy as np

    return Segment(
        pcm=np.zeros(160, dtype=np.int16), started_at=at, ended_at=at + 0.5
    )


def spoke(text, *, ears, config=None):
    """Run the real `speak` Tool with a microphone attached."""
    registry = build_registry()
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()),
        readings=None,
        config=config or Settings(),
        clock=FakeClock(),
        ears=ears,
    )
    return dispatch(
        registry, "speak", {"text": text}, ctx, Journal(episode_id="ep-1"), turn=1
    )


# ---------------------------------------------------------------------------
# Inside the window
# ---------------------------------------------------------------------------

def test_speech_heard_while_the_robot_is_talking_is_dropped():
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(2.0)
    clock.advance(1.0)
    stream._publish(a_segment(stream))

    assert stream.read_segment(timeout=0) is None


def test_nothing_is_even_sent_to_the_transcriber_while_muted():
    """Dropping it afterwards would still pay for the round trip, on the
    thread that is supposed to be listening for the next thing said."""
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(5.0)
    for _ in range(3):
        stream._publish(a_segment(stream))

    assert stream.read_segment(timeout=0) is None


# ---------------------------------------------------------------------------
# After the window
# ---------------------------------------------------------------------------

def test_speech_heard_after_the_robot_stops_gets_through():
    """Without this, an implementation that muted forever would pass every
    test above — and the robot would never hear anyone again."""
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(2.0)
    clock.advance(2.01)
    stream._publish(a_segment(stream))

    heard = stream.read_segment(timeout=0)
    assert heard is not None


def test_the_window_closes_on_time_not_early_and_not_late():
    """Both edges, because a window that is out by a second in either
    direction is a different defect and both are silent."""
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(2.0)
    clock.advance(1.999)
    assert stream.muted()
    clock.advance(0.002)
    assert not stream.muted()


def test_an_unmuted_stream_hears_everything():
    """The negative control. A `_publish` that dropped everything would
    satisfy both of the muted tests."""
    clock = Ticking()
    stream = a_stream(clock)

    stream._publish(a_segment(stream))

    assert stream.read_segment(timeout=0) is not None


# ---------------------------------------------------------------------------
# Overlapping windows
# ---------------------------------------------------------------------------

def test_two_utterances_end_the_window_when_the_later_one_does():
    """Not at the sum of both: the robot is not talking twice as long for
    having been asked twice."""
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(2.0)
    clock.advance(1.0)
    stream.mute_for(2.0)

    clock.advance(1.99)
    assert stream.muted()
    clock.advance(0.02)
    assert not stream.muted()


def test_a_shorter_window_does_not_cut_a_longer_one_short():
    clock = Ticking()
    stream = a_stream(clock)

    stream.mute_for(5.0)
    stream.mute_for(0.1)

    clock.advance(1.0)
    assert stream.muted()


# ---------------------------------------------------------------------------
# The window `speak` actually opens
# ---------------------------------------------------------------------------

class RecordingEars:
    def __init__(self) -> None:
        self.muted_for = []

    def mute_for(self, seconds):
        self.muted_for.append(seconds)


class OrderWatchingRobot(RecordingCommands):
    def __init__(self, ears) -> None:
        super().__init__()
        self._ears = ears
        self.muted_before_speaking = None

    def speak(self, **kwargs):
        self.muted_before_speaking = bool(self._ears.muted_for)
        return super().speak(**kwargs)


def test_speaking_mutes_for_as_long_as_it_expects_to_take():
    ears = RecordingEars()

    outcome = spoke("Coming over.", ears=ears)

    assert ears.muted_for == [outcome.result["estimated_speech_ms"] / 1000.0]


def test_the_microphone_is_shut_before_the_request_goes_out():
    """`POST /tts/speak` is a round trip and Misty starts talking at the far
    end of it. Muting after it returns leaves a gap she can hear herself in.
    """
    ears = RecordingEars()
    robot = OrderWatchingRobot(ears)
    registry = build_registry()
    ctx = ToolContext(
        robot=RealMistyAdapter(robot), readings=None, config=Settings(),
        clock=FakeClock(), ears=ears,
    )

    dispatch(
        registry, "speak", {"text": "Coming over."}, ctx,
        Journal(episode_id="ep-1"), turn=1,
    )

    assert robot.muted_before_speaking is True


def test_speaking_does_not_wait_out_its_own_window():
    """The defect this ticket exists to fix.

    The old script muted *and then slept* for the same duration, so the whole
    action was deaf — someone saying "stop" while the robot talked was never
    heard at all. Muting without waiting is the difference.
    """
    clock = FakeClock()
    ears = RecordingEars()
    registry = build_registry()
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()), readings=None, config=Settings(),
        clock=clock, ears=ears,
    )

    dispatch(
        registry, "speak", {"text": "a much longer sentence than this one"},
        ctx, Journal(episode_id="ep-1"), turn=1,
    )

    assert ears.muted_for and ears.muted_for[0] > 1.0
    assert clock.slept == [], "the Tool waited out its own suppression window"


def test_speaking_without_a_microphone_still_works():
    """An Episode with nothing listening is still a valid Episode, and
    `speak` must not require one to exist."""
    from misty_agent.agent.tools import HEARS_NOTHING

    outcome = spoke("Coming over.", ears=HEARS_NOTHING)

    assert outcome.accepted


# ---------------------------------------------------------------------------
# The estimate the window is opened on
# ---------------------------------------------------------------------------

def test_a_chinese_sentence_is_not_billed_as_one_word():
    """The bug ticket 05's review found and left for this ticket.

    `split()` counts whitespace tokens and Chinese has none, so
    「你好，我過來一點」 estimated at 0.95 s — the window reopened while Misty
    was still talking and she transcribed herself. That is this ticket's own
    defect, arriving by another route.
    """
    settings = Settings()

    estimate = estimate_speech_ms("你好，我過來一點", settings)

    assert estimate > 1500, f"{estimate}ms is still the one-word estimate"


@pytest.mark.parametrize(
    "text", ["你好我過來一點", "こんにちはそちらへ行きます", "안녕하세요지금갈게요"]
)
def test_every_script_without_spaces_gets_its_own_rate(text):
    """Chinese, Japanese and Korean all write without spaces between words.

    Asserted against the character formula rather than a loose lower bound: a
    rule that recognised only Han ideographs would fall back to counting the
    whole thing as words, and for a spaced Korean sentence that lands above
    any threshold worth writing.
    """
    settings = Settings()
    expected_ms = round(
        (len(text) / settings.speech_cjk_chars_per_second
         + settings.speech_overhead_s) * 1000
    )

    assert estimate_speech_ms(text, settings) == expected_ms


def test_a_longer_chinese_sentence_takes_longer():
    """A constant would satisfy the tests above."""
    settings = Settings()

    short = estimate_speech_ms("你好", settings)
    long = estimate_speech_ms("你好我現在過來找你我們可以聊聊天", settings)

    assert long > short


def test_latin_text_is_unchanged_by_the_cjk_rule():
    """Four golden Journals are built on this number.

    `episode_ends_after_several_turns.jsonl` records 1409 ms for "Coming
    over.", written before any of this existed.
    """
    assert estimate_speech_ms("Coming over.", Settings()) == 1409


def test_a_sentence_with_no_spaces_is_billed_for_no_words():
    """The characters are removed *before* the words are counted.

    Without that, `split()` sees one token — the whole sentence — and the
    estimate charges a word for it on top of every character. Comparing two
    CJK estimates cannot see this: both gain the same spurious word, and the
    difference between them is unchanged.
    """
    settings = Settings()
    text = "你好我過來"

    expected_ms = round(
        (len(text) / settings.speech_cjk_chars_per_second
         + settings.speech_overhead_s) * 1000
    )

    assert estimate_speech_ms(text, settings) == expected_ms


def test_mixed_text_counts_each_script_once():
    """One Latin word costs one Latin word, whatever it is next to."""
    settings = Settings()

    chinese = estimate_speech_ms("你好我過來", settings)
    with_a_name = estimate_speech_ms("你好我過來 Ana", settings)

    words_worth = 1 / settings.speech_words_per_second * 1000
    assert with_a_name == pytest.approx(chinese + words_worth, abs=1)


def test_the_cjk_rate_comes_from_config():
    """UNCALIBRATED means adjustable from outside, not a literal in a file."""
    slow = estimate_speech_ms("你好我過來", Settings(speech_cjk_chars_per_second=1.0))
    fast = estimate_speech_ms("你好我過來", Settings(speech_cjk_chars_per_second=20.0))

    assert slow > fast


def test_the_estimate_is_still_capped():
    """A very long utterance must not hold the window shut indefinitely."""
    settings = Settings(speech_estimate_cap_s=3.0)

    assert estimate_speech_ms("你好" * 500, settings) == 3000


# ---------------------------------------------------------------------------
# The return value that never existed
# ---------------------------------------------------------------------------

def test_nothing_looks_for_a_spoken_ms_return_value():
    """`PLAN.md` §4 originally said to use one. Misty's TTS returns no timing
    at all, so any code reaching for it would be reading `None` and calling it
    a duration.
    """
    import pathlib

    package = pathlib.Path(__file__).parent.parent / "misty_agent"
    for source in package.rglob("*.py"):
        assert "spoken_ms" not in source.read_text(), source


def test_the_estimate_is_rounded_not_truncated():
    """Every fixture above happens to land on a whole millisecond, so
    `int(round(x))` and `int(x)` agree on all of them — which means neither is
    actually pinned by any of them.
    """
    settings = Settings()

    # 3 words: 3/2.2 + 0.5 = 1.86363... s, which is 1864 ms rounded and 1863
    # truncated.
    assert estimate_speech_ms("one two three", settings) == 1864


@pytest.mark.parametrize(
    "mark,name",
    [("\u3001", "ideographic comma"), ("\u3002", "ideographic full stop"),
     ("\u300c", "corner bracket"), ("\u301c", "wave dash")],
)
def test_cjk_punctuation_counts_as_a_character(mark, name):
    """That whole punctuation range was untested: the Chinese fixture's comma
    is the *fullwidth* one at U+FF0C, so dropping the CJK-punctuation range
    left every test green.

    Four marks spread across the range, because one of them is its first
    character — a range narrowed to just that one would pass a test written
    with only that mark.
    """
    settings = Settings()
    text = f"\u4f60\u597d{mark}\u6211\u4f86\u4e86"

    assert len(_CJK.findall(text)) == 6, name
    assert estimate_speech_ms(text, settings) == estimate_speech_ms(
        "\u4f60\u597d\u4f60\u6211\u4f86\u4e86", settings
    )


def test_fullwidth_latin_is_not_billed_as_syllables():
    """Halfwidth and Fullwidth Forms holds the fullwidth alphabet as well as
    the fullwidth comma. Taking the whole block made `Ｈｅｌｌｏ ｗｏｒｌｄ`
    eleven syllables — nearly three seconds for two words.
    """
    settings = Settings()

    assert estimate_speech_ms("Ｈｅｌｌｏ　ｗｏｒｌｄ", settings) == estimate_speech_ms(
        "Hello world", settings
    )


def test_a_tool_that_makes_no_sound_leaves_the_microphone_open():
    """Only `speak` should ever shut the ears.

    Structurally true — it is the one Tool that touches `ctx.ears` — but
    nothing said so, and a `dispatch` that muted on every call would leave the
    robot deaf for most of an Episode.
    """
    ears = RecordingEars()
    registry = build_registry()
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()), readings=None, config=Settings(),
        clock=FakeClock(), ears=ears,
    )

    for name, args in (
        ("move_head", {"pitch": 0}),
        ("change_led", {"red": 1}),
        ("display_image", {"expression": "happy"}),
        ("done", {}),
    ):
        dispatch(registry, name, args, ctx, Journal(episode_id="ep-1"), turn=1)

    assert ears.muted_for == []


def test_an_episode_with_no_microphone_needs_no_none_check():
    """`HEARS_NOTHING` matches `NEVER_STOPS`: the caller reads
    one shape rather than testing for `None`."""
    from misty_agent.agent.tools import HEARS_NOTHING

    ctx = ToolContext(robot=RealMistyAdapter(RecordingCommands()), readings=None, config=Settings())

    assert ctx.ears is HEARS_NOTHING
    ctx.ears.mute_for(1.0)

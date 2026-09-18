"""The seven Tools the model can use to do something visible.

`PLAN.md` §4: with AutoMisty gone, expressiveness comes from **composition** —
a wave is the model putting arm positions together across Turns, not a `wave`
Tool. So these seven primitives are the whole of what the agent can express,
and the only thing standing between the model and the robot is each Tool's
argument type.

## What these tests are careful about

**Every bound is checked from both sides.** Ticket 04's lesson (`PLAN.md`
§15.9) was that a rule with one example cannot be told from a coincidence: the
`ends_episode` mutation survived because the only Tool that ended an Episode
was also the only Tool named `done`. A clamp that is only shown accepting
legal values would survive being deleted, so each one is shown refusing the
value just outside it too.

**The bounds are not a shared template.** Head pitch, head yaw, arm position,
RGB and volume have five different documented ranges. `test_no_two_of_these_
ranges_are_the_same` is what stops someone tidying them into one constant.

**What reaches the robot is asserted against the REST reference**, using the
same `RecordingCommands` seam `tests/test_drivers_contract.py` uses. No new
test seam: `ToolContext.robot` is the one ticket 04 defined.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from misty_agent.agent.journal import Journal
from misty_agent.agent.tools import (
    SCAN_YAWS,
    SPEECH_MAX_CHARS,
    ToolContext,
    build_registry,
    dispatch,
)
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter
from misty_agent.perception.distance import DistanceReading


class Readings:
    """A `ReadingSource` that answers with whatever it was told to answer.

    `look_around` asks it once per scan position, so a list of answers is
    also a description of where the person is standing.
    """

    def __init__(self, *answers) -> None:
        self._answers = list(answers)

    def latest_reading(self):
        return self._answers.pop(0) if self._answers else None


def a_reading(distance_cm=142):
    return DistanceReading(
        distance_cm=distance_cm, frame_arrived_at=0.0, detected_at=0.0
    )


@pytest.fixture
def registry():
    return build_registry()


@pytest.fixture
def robot():
    return RecordingCommands("10.0.0.5")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def ctx(robot, clock):
    return ToolContext(
        robot=RealMistyAdapter(robot), readings=None, config=Settings(), clock=clock
    )


def call(registry, name, args, ctx):
    return dispatch(registry, name, args, ctx, Journal(episode_id="ep-1"), turn=1)


EXPRESSIONS = [
    "happy", "sad", "angry", "surprised", "love", "afraid", "neutral"
]
SOUNDS = ["joy", "amazement", "awe", "anger", "acceptance", "annoyance"]

THE_SEVEN = [
    "speak",
    "display_image",
    "move_arms",
    "move_head",
    "change_led",
    "play_audio",
    "look_around",
]

PERCEPTION_TOOLS = ["observe_target", "inspect_scene"]


# ---------------------------------------------------------------------------
# All seven are there and the model can see them
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", THE_SEVEN)
def test_the_tool_is_registered(registry, name):
    assert name in registry.names()


@pytest.mark.parametrize("name", THE_SEVEN)
def test_the_model_is_handed_a_schema_for_it(registry, name):
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == name
    )

    assert schema["function"]["description"].strip()
    assert schema["function"]["parameters"]["type"] == "object"


@pytest.mark.parametrize("name", THE_SEVEN)
def test_none_of_them_ends_the_episode(registry, name, ctx):
    """Only `done` does. A Tool that ended the Episode as a side effect of
    doing something visible would end it without the model choosing to."""
    tool = registry.get(name)

    assert not tool.ends_episode


@pytest.mark.parametrize("name", PERCEPTION_TOOLS)
def test_active_perception_tools_are_registered_and_never_end_the_episode(
    registry, name
):
    tool = registry.get(name)

    assert tool is not None
    assert not tool.ends_episode
    assert tool.schema()["function"]["parameters"]["properties"] == {}


# ---------------------------------------------------------------------------
# Every clamp, from both sides
# ---------------------------------------------------------------------------

#: (tool, argument, other arguments, lowest legal, highest legal)
#:
#: Each range is quoted from the Misty II REST reference in `tools.py`. They
#: are listed here rather than read off the schema on purpose: reading them
#: off the schema would make this test agree with the code by construction,
#: which is the thing `tests/goldens/README.md` is about.
BOUNDS = [
    ("move_head", "pitch", {}, -40, 26),
    ("move_head", "roll", {}, -40, 40),
    ("move_head", "yaw", {}, -81, 81),
    ("move_arms", "left", {}, -29, 90),
    ("move_arms", "right", {}, -29, 90),
    ("change_led", "red", {"green": 0, "blue": 0}, 0, 255),
    ("change_led", "green", {"red": 0, "blue": 0}, 0, 255),
    ("change_led", "blue", {"red": 0, "green": 0}, 0, 255),
    ("play_audio", "volume", {"sound": "joy"}, 0, 100),
]


@pytest.mark.parametrize("tool,argument,rest,low,high", BOUNDS)
def test_the_bounds_themselves_are_accepted(
    registry, ctx, tool, argument, rest, low, high
):
    """The negative control. A Tool that refused everything would satisfy the
    test below, and a clamp one degree too tight is a clamp that is wrong."""
    for value in (low, high):
        outcome = call(registry, tool, {argument: value, **rest}, ctx)

        assert outcome.accepted, f"{tool}.{argument}={value}: {outcome.reason}"


@pytest.mark.parametrize("tool,argument,rest,low,high", BOUNDS)
def test_just_outside_each_bound_is_refused(
    registry, ctx, tool, argument, rest, low, high
):
    """Delete any one clamp and exactly one of these goes red."""
    for value in (low - 1, high + 1):
        outcome = call(registry, tool, {argument: value, **rest}, ctx)

        assert not outcome.accepted, f"{tool}.{argument}={value} was allowed"
        assert argument in outcome.reason
        assert str(value) in outcome.reason, "the reason does not say what was sent"


@pytest.mark.parametrize("tool,argument,rest,low,high", BOUNDS)
def test_an_out_of_range_argument_never_reaches_the_robot(
    registry, ctx, robot, tool, argument, rest, low, high
):
    """`PLAN.md` §14.6: the check has to be *before* the driver, not after."""
    call(registry, tool, {argument: high + 1, **rest}, ctx)

    assert robot.requests == []


def test_every_documented_range_is_its_own():
    """Six ranges, spelled out, and none of them is a shared template.

    The ticket asks for each clamp to come from that parameter's own range.
    Collapsing them into one bound would pass every test above except this
    one. Written as the whole set rather than a count so that adding a
    seventh parameter has to say what its range is.
    """
    ranges = {(low, high) for _, _, _, low, high in BOUNDS}

    assert ranges == {
        (-40, 26),   # head pitch
        (-40, 40),   # head roll
        (-81, 81),   # head yaw
        (-29, 90),   # arm position
        (0, 255),    # LED channel
        (0, 100),    # volume
    }


# ---------------------------------------------------------------------------
# What actually reaches the robot
# ---------------------------------------------------------------------------

def test_move_head_sends_all_three_axes_it_was_given(registry, ctx, robot):
    """Three different non-default values, so a handler that dropped one — or
    passed the same one twice — cannot pass this."""
    outcome = call(
        registry, "move_head", {"pitch": -10, "roll": 15, "yaw": 20}, ctx
    )

    request = robot.last("head")
    assert outcome.accepted
    assert request.verb == "post"
    assert request.json["pitch"] == -10
    assert request.json["roll"] == 15
    assert request.json["yaw"] == 20


def test_move_head_recentres_when_told_nothing(registry, ctx, robot):
    """0/0/0 is what the reference calls looking straight ahead."""
    call(registry, "move_head", {}, ctx)

    assert robot.last("head").json == {
        "pitch": 0.0, "roll": 0.0, "yaw": 0.0, "units": "degrees",
        "velocity": None, "duration": None,
    }


def test_move_arms_sends_the_documented_body(registry, ctx, robot):
    call(registry, "move_arms", {"left": 0, "right": 90}, ctx)

    request = robot.last("arms/set")
    assert request.verb == "post"
    assert request.json["leftArmPosition"] == 0
    assert request.json["rightArmPosition"] == 90


def test_change_led_sends_the_documented_body(registry, ctx, robot):
    call(registry, "change_led", {"red": 255, "green": 128, "blue": 0}, ctx)

    request = robot.last("led")
    assert request.json == {"red": 255, "green": 128, "blue": 0}


def test_speak_sends_the_text_to_the_tts_endpoint(registry, ctx, robot):
    call(registry, "speak", {"text": "Coming over."}, ctx)

    request = robot.last("tts/speak")
    assert request.verb == "post"
    assert request.json["text"] == "Coming over."


def test_display_image_sends_a_filename_that_ships_on_the_robot(
    registry, ctx, robot
):
    """The model picks a feeling; the Tool picks the file.

    A free-text filename would let the model name an image that is not on the
    robot, and the failure would arrive as a 404 from the driver with nothing
    in the Journal saying why.
    """
    call(registry, "display_image", {"expression": "happy"}, ctx)

    assert robot.last("images/display").json["fileName"] == "e_Joy.jpg"


def test_the_files_these_two_tools_name_are_the_documented_ones(registry, ctx, robot):
    """Asserting only the extension would let any invented filename through,
    and a filename Misty does not ship fails as a 404 inside the driver with
    nothing in the Journal explaining it. `PLAN.md` §8's first bullet already
    says none of this has met a robot; the least it can do is match the docs.

    https://docs.mistyrobotics.com/misty-ii/robot/misty-ii/#images
    https://lessons.mistyrobotics.com/resource-database/audio-files
    """
    seen = {}
    for expression in EXPRESSIONS:
        robot.clear()
        call(registry, "display_image", {"expression": expression}, ctx)
        seen[expression] = robot.last("images/display").json["fileName"]

    assert seen == {
        "happy": "e_Joy.jpg",
        "sad": "e_Sadness.jpg",
        "angry": "e_Anger.jpg",
        "surprised": "e_Surprise.jpg",
        "love": "e_Love.jpg",
        "afraid": "e_ApprehensionConcerned.jpg",
        "neutral": "e_DefaultContent.jpg",
    }

    heard = {}
    for sound in SOUNDS:
        robot.clear()
        call(registry, "play_audio", {"sound": sound, "volume": 50}, ctx)
        heard[sound] = robot.last("audio/play").json["fileName"]

    assert heard == {
        "joy": "s_Joy.wav",
        "amazement": "s_Amazement.wav",
        "awe": "s_Awe.wav",
        "anger": "s_Anger.wav",
        "acceptance": "s_Acceptance.wav",
        "annoyance": "s_Annoyance.wav",
    }


def test_play_audio_sends_a_filename_that_ships_on_the_robot(
    registry, ctx, robot
):
    # Not 50: that is the argument's own default, so a handler that ignored
    # the model entirely would still look right.
    call(registry, "play_audio", {"sound": "joy", "volume": 17}, ctx)

    request = robot.last("audio/play")
    assert request.json["fileName"] == "s_Joy.wav"
    assert request.json["volume"] == 17


# ---------------------------------------------------------------------------
# The two Tools whose arguments are a set, not a range
# ---------------------------------------------------------------------------

def test_an_expression_the_robot_does_not_have_is_refused(registry, ctx, robot):
    outcome = call(registry, "display_image", {"expression": "smug"}, ctx)

    assert not outcome.accepted
    assert robot.requests == []


def test_a_sound_the_robot_does_not_have_is_refused(registry, ctx, robot):
    outcome = call(
        registry, "play_audio", {"sound": "bagpipes", "volume": 50}, ctx
    )

    assert not outcome.accepted
    assert robot.requests == []


def test_the_model_is_told_which_expressions_exist(registry):
    """An enum in the schema is the difference between the model guessing and
    the model choosing."""
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == "display_image"
    )

    options = schema["function"]["parameters"]["properties"]["expression"]["enum"]
    assert "happy" in options and "neutral" in options


def test_every_offered_expression_actually_works(registry, ctx, robot):
    """A schema that offered a name the Tool cannot map would be a lie."""
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == "display_image"
    )

    for expression in schema["function"]["parameters"]["properties"]["expression"]["enum"]:
        robot.clear()
        outcome = call(registry, "display_image", {"expression": expression}, ctx)

        assert outcome.accepted, expression
        assert robot.last("images/display").json["fileName"]


def test_every_offered_sound_actually_works(registry, ctx, robot):
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == "play_audio"
    )

    for sound in schema["function"]["parameters"]["properties"]["sound"]["enum"]:
        robot.clear()
        outcome = call(registry, "play_audio", {"sound": sound, "volume": 50}, ctx)

        assert outcome.accepted, sound
        assert robot.last("audio/play").json["fileName"]


# ---------------------------------------------------------------------------
# `speak`
# ---------------------------------------------------------------------------

def test_empty_speech_is_refused(registry, ctx, robot):
    """Nothing to say is not something to say — and it would still cost a Turn
    and open a suppression window (ticket 10)."""
    outcome = call(registry, "speak", {"text": "   "}, ctx)

    assert not outcome.accepted
    assert robot.requests == []


def test_speech_longer_than_the_bound_is_refused(registry, ctx, robot):
    outcome = call(registry, "speak", {"text": "word " * 500}, ctx)

    assert not outcome.accepted
    assert robot.requests == []


# ---------------------------------------------------------------------------
# `look_around` — the one that is not a single command
# ---------------------------------------------------------------------------

def test_look_around_turns_the_head_to_more_than_one_place(
    registry, ctx, robot
):
    """This is why it is not the same Tool as `move_head`.

    `PLAN.md` §15.2 cut `back_up` because two Tools doing one thing means the
    model picks wrong and the Journal does not show why. `look_around` earns
    its place only by being a scan the model cannot express in one Turn.
    """
    call(registry, "look_around", {}, ctx)

    yaws = [r.json["yaw"] for r in robot.requests if r.endpoint == "head"]
    assert len(yaws) >= 3
    assert len(set(yaws)) >= 3


def test_look_around_pauses_between_positions(registry, ctx, clock):
    """Without a settle the head never arrives anywhere and the last command
    wins. Asserted on the injected clock, so no test waits."""
    call(registry, "look_around", {}, ctx)

    assert len(clock.slept) >= 2
    assert all(seconds > 0 for seconds in clock.slept)


def test_look_around_leaves_the_head_where_it_can_see_ahead(
    registry, ctx, robot
):
    """A scan that finished looking over its shoulder would leave every later
    Snapshot reading the wrong direction."""
    call(registry, "look_around", {}, ctx)

    assert robot.last("head").json["yaw"] == 0


def test_look_around_stays_inside_the_documented_yaw_range(
    registry, ctx, robot
):
    call(registry, "look_around", {}, ctx)

    for request in robot.requests:
        if request.endpoint == "head":
            assert -81 <= request.json["yaw"] <= 81


# ---------------------------------------------------------------------------
# The layering claim, asserted on what the model is actually handed
# ---------------------------------------------------------------------------

def test_no_tool_offers_the_model_a_velocity_or_a_drive_duration(registry):
    """§4, checked against the schemas rather than the source.

    The driver's `move_head` and `move_arms` both take `velocity` and
    `duration`; these Tools must not pass either through to the model.
    """
    handed_over = json.dumps(registry.schemas()).lower()

    for forbidden in ("velocity", "timems", "time_ms", "drive"):
        assert forbidden not in handed_over, forbidden


# ---------------------------------------------------------------------------
# The parts a handler could quietly drop
# ---------------------------------------------------------------------------

def test_both_joint_commands_say_what_unit_they_are_in(registry, ctx, robot):
    """`MoveArms` and `MoveHead` both take `position`, `degrees` or `radians`.

    Sent without `units`, the driver puts a null in the body and the robot
    falls back to whatever its default is — 90 *position* is not 90 *degrees*.
    """
    call(registry, "move_arms", {"left": 0, "right": 0}, ctx)
    call(registry, "move_head", {"yaw": 10}, ctx)

    assert robot.last("arms/set").json["units"] == "degrees"
    assert robot.last("head").json["units"] == "degrees"


def test_look_around_settles_for_as_long_as_the_config_says(registry, robot):
    """The settle is `ctx.config`'s to set, so a hard-coded one must fail.

    It is UNCALIBRATED (`PLAN.md` §8): MoveHead is issued with no velocity or
    duration, so how long the head really takes is unknown, and the number has
    to stay adjustable from outside.
    """
    clock = FakeClock()
    ctx = ToolContext(
        robot=RealMistyAdapter(robot),
        readings=None,
        config=Settings(look_around_settle_s=1.25),
        clock=clock,
    )

    call(registry, "look_around", {}, ctx)

    # Three scan positions and the recentre at the end, nobody found.
    assert clock.slept == [1.25] * (len(SCAN_YAWS) + 1)


def test_look_around_keeps_the_head_level_while_it_scans(registry, ctx, robot):
    """A scan tilted at the ceiling sees the ceiling."""
    call(registry, "look_around", {}, ctx)

    for request in robot.requests:
        if request.endpoint == "head":
            assert request.json["pitch"] == 0.0
            assert request.json["roll"] == 0.0


def test_look_around_actually_looks_somewhere_else(registry, ctx, robot):
    """Wide enough to find someone standing off to one side.

    A scan of ±1 degree would satisfy "more than one position" while seeing
    exactly what looking straight ahead already saw.
    """
    call(registry, "look_around", {}, ctx)
    yaws = [r.json["yaw"] for r in robot.requests if r.endpoint == "head"]

    assert max(yaws) - min(yaws) >= 60


# ---------------------------------------------------------------------------
# The exact edge of the one bound that is not Misty's
# ---------------------------------------------------------------------------

def test_the_speech_bound_is_the_number_it_is_supposed_to_be():
    """Spelled out, because every other test here reads the constant.

    Tests written against `SPEECH_MAX_CHARS` move with it: widen the constant
    and they widen too, still green. That is the same failure the golden
    Journals exist to prevent (`tests/goldens/README.md`) — an assertion that
    agrees with the code by construction. This one disagrees on purpose.

    150 characters is not from Misty; the reference documents no maximum. It
    is derived from `PLAN.md` §4's estimate saturating at 12 s — about 25
    words — so that `speak` never returns a duration shorter than the speech
    it just started. Changing it is a decision, and the next test is what
    makes it one.
    """
    assert SPEECH_MAX_CHARS == 150


def test_the_longest_allowed_utterance_is_accepted(registry, ctx):
    outcome = call(registry, "speak", {"text": "a" * SPEECH_MAX_CHARS}, ctx)

    assert outcome.accepted


def test_one_character_more_is_refused(registry, ctx, robot):
    """Pinned to the constant, so widening the bound cannot go unnoticed."""
    outcome = call(registry, "speak", {"text": "a" * (SPEECH_MAX_CHARS + 1)}, ctx)

    assert not outcome.accepted
    assert robot.requests == []


# ---------------------------------------------------------------------------
# What the model reads back
# ---------------------------------------------------------------------------

def test_a_result_does_not_repeat_the_arguments_back(registry, ctx):
    """`PLAN.md` §15.4: the Observation must not carry one fact twice.

    What the model asked for is already on the `tool_called` record ticket 04
    writes. Echoing it into the result would put the same string in the
    Journal twice, and two copies are what drift.
    """
    shown = call(registry, "display_image", {"expression": "sad"}, ctx)
    played = call(registry, "play_audio", {"sound": "awe", "volume": 30}, ctx)

    assert shown.result == {"ok": True}
    assert played.result == {"ok": True}


def test_speech_is_sent_stripped(registry, ctx, robot):
    """The argument type strips, so the robot must get the stripped text —
    otherwise the Journal records something that was never spoken."""
    call(registry, "speak", {"text": "  hello  "}, ctx)

    assert robot.last("tts/speak").json["text"] == "hello"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_the_defaults_are_the_resting_pose(registry, ctx, robot):
    """Every default is a position the model would want as a starting point,
    and each is a different number — arms down, head level, light off."""
    call(registry, "move_arms", {}, ctx)
    call(registry, "change_led", {}, ctx)

    assert robot.last("arms/set").json["leftArmPosition"] == 90
    assert robot.last("arms/set").json["rightArmPosition"] == 90
    assert robot.last("led").json == {"red": 0, "green": 0, "blue": 0}


def test_volume_defaults_to_something_audible_but_not_full(registry, ctx, robot):
    call(registry, "play_audio", {"sound": "joy"}, ctx)

    volume = robot.last("audio/play").json["volume"]
    assert 0 < volume < 100


# ---------------------------------------------------------------------------
# `look_around` earns its place only by looking while it turns
# ---------------------------------------------------------------------------

def a_scanning_ctx(robot, clock, *answers):
    return ToolContext(
        robot=RealMistyAdapter(robot), readings=Readings(*answers), config=Settings(), clock=clock
    )


@pytest.mark.parametrize("position", [0, 1, 2])
def test_the_scan_reports_which_way_it_was_looking(registry, robot, clock, position):
    """Every scan position, because two of the three would not catch a
    constant: the middle one is 0.0, and reporting a fixed 0.0 would look
    right there and be wrong everywhere else."""
    answers = [None] * position + [a_reading()]
    ctx = a_scanning_ctx(robot, clock, *answers)

    outcome = call(registry, "look_around", {}, ctx)

    assert outcome.result["found_at_yaw"] == SCAN_YAWS[position]


def test_the_scan_leaves_the_head_pointing_at_whoever_it_found(
    registry, robot, clock
):
    """This is the whole reason it is not `move_head` under another name.

    Ticket 07 appends the Snapshot *after* the Tool returns. If the head swept
    back to centre, the result would say "found someone at -60" and the
    Snapshot beside it would describe an empty room — the model would be
    handed two facts that contradict each other in the same record.
    """
    ctx = a_scanning_ctx(robot, clock, a_reading())

    call(registry, "look_around", {}, ctx)

    assert robot.last("head").json["yaw"] == SCAN_YAWS[0]


def test_the_scan_stops_turning_once_it_has_found_someone(
    registry, robot, clock
):
    """Carrying on would walk the head straight past them."""
    ctx = a_scanning_ctx(robot, clock, a_reading())

    call(registry, "look_around", {}, ctx)

    yaws = [r.json["yaw"] for r in robot.requests if r.endpoint == "head"]
    assert yaws == [SCAN_YAWS[0]]


def test_finding_nobody_says_so_and_faces_forward(registry, robot, clock):
    """A scan that reported nothing and left the head over its shoulder would
    make every later Snapshot describe the wrong direction."""
    ctx = a_scanning_ctx(robot, clock)

    outcome = call(registry, "look_around", {}, ctx)

    assert outcome.result["found_at_yaw"] is None
    assert robot.last("head").json["yaw"] == 0.0


def test_the_scan_does_not_repeat_what_the_snapshot_already_says(
    registry, robot, clock
):
    """§15.4 fixes the Snapshot at three facts and refuses to carry them
    twice. The angle is the one thing the Snapshot cannot say."""
    ctx = a_scanning_ctx(robot, clock, a_reading())

    outcome = call(registry, "look_around", {}, ctx)

    assert set(outcome.result) == {"ok", "found_at_yaw"}


# ---------------------------------------------------------------------------
# The speech estimate, checked against the golden that predates it
# ---------------------------------------------------------------------------

def test_speak_reports_how_long_it_expects_to_take(registry, ctx):
    """Ticket 10 opens its suppression window on this number."""
    outcome = call(registry, "speak", {"text": "Coming over."}, ctx)

    assert outcome.result["estimated_speech_ms"] > 0


def test_the_estimate_is_the_one_the_golden_journal_was_built_from(registry, ctx):
    """Read out of the golden, not copied from it.

    `episode_ends_after_several_turns.jsonl` records `estimated_speech_ms:
    1409` for a `speak` of "Coming over.", and that file was written before
    any of this existed. Ticket 07 has to reproduce it, so the estimator
    either lands on that number or the golden changes and `PLAN.md` says why
    (`tests/goldens/README.md`).
    """
    golden = pathlib.Path(__file__).parent / "goldens" / (
        "episode_ends_after_several_turns.jsonl"
    )
    records = [json.loads(line) for line in golden.read_text().splitlines()]
    spoke = next(
        r for r in records
        if r["type"] == "tool_called" and r["tool"] == "speak"
    )
    observed = next(
        r for r in records
        if r["type"] == "observation" and "estimated_speech_ms" in r["result"]
    )

    outcome = call(registry, "speak", {"text": spoke["args"]["text"]}, ctx)

    assert outcome.result["estimated_speech_ms"] == (
        observed["result"]["estimated_speech_ms"]
    )


def test_the_estimate_never_exceeds_the_configured_cap(registry, robot, clock):
    """An unbounded estimate would hold ticket 10's window shut for as long as
    the model cared to talk."""
    ctx = ToolContext(
        robot=RealMistyAdapter(robot), readings=None,
        config=Settings(speech_estimate_cap_s=2.0), clock=clock,
    )

    outcome = call(registry, "speak", {"text": "word " * 25}, ctx)

    assert outcome.result["estimated_speech_ms"] == 2000


def test_the_estimate_grows_with_the_number_of_words(registry, ctx):
    """A constant would satisfy every other test here."""
    short = call(registry, "speak", {"text": "hi"}, ctx)
    longer = call(registry, "speak", {"text": "one two three four five"}, ctx)

    assert longer.result["estimated_speech_ms"] > short.result["estimated_speech_ms"]


def test_the_rate_comes_from_config_not_from_this_module(registry, robot, clock):
    """§15.4 asked for the rate to leave the old script and be marked
    UNCALIBRATED. A second copy here would be the thing that drifts."""
    fast = ToolContext(
        robot=RealMistyAdapter(robot), readings=None,
        config=Settings(speech_words_per_second=100.0), clock=clock,
    )
    slow = ToolContext(
        robot=RealMistyAdapter(robot), readings=None,
        config=Settings(speech_words_per_second=0.5), clock=clock,
    )

    quick = call(registry, "speak", {"text": "one two three"}, fast)
    slower = call(registry, "speak", {"text": "one two three"}, slow)

    assert quick.result["estimated_speech_ms"] < slower.result["estimated_speech_ms"]

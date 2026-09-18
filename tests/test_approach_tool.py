"""The one Tool that does not tell the robot how to move.

`PLAN.md` §4 is this project's central claim: **the model decides whether to
approach, and the control layer decides how far each Step goes.** Every other
Tool takes an angle or a colour and passes it straight through. This one takes
*nothing*, and behind it is M5's closed loop — read a distance, plan a bounded
Step, drive it, read again.

So the thing to test here is not the control law. That is `tests/test_approach.py`,
which is why this file **imports its worlds instead of building new ones**: a
second `SimulatedMistyAdapter` would be a second definition of what the robot does, and
the point of a thin adapter is that it adds nothing. If these fakes drift from
the ones M5 was verified against, that is a fact worth finding out about.

What this file tests is the seam:

* the four states arrive at the model **unchanged** — not renamed, not folded
  into "ok / not ok";
* `linearVelocity` and `timeMs` are on every drive the loop issues, and reach
  the model in **nothing** — asserted on the bytes the model is handed, not on
  the Tool's signature, which could be clean while the result leaked;
* too close is `approach` too. `PLAN.md` §15.2 cut `back_up` on exactly this
  claim, so it needs an executable version.
"""

from __future__ import annotations

import dataclasses

import json

import pytest

from misty_agent.agent.journal import Journal, Observation, Snapshot
from misty_agent.agent.tools import ToolContext, build_registry, dispatch
from misty_agent.config import Settings
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.fakes import (
    FakeClock,
    RecordingCommands,
    a_reading,
)
from misty_agent.robot import RealMistyAdapter, SimulatedMistyAdapter

from test_approach import (
    ExplodingRobot,
    ScheduledReading,
    ScheduledReadings,
    TickReadings,
    WorldThatLosesTheUserAfterAStep,
)


@pytest.fixture
def registry():
    return build_registry()


def run(registry, *, robot, readings, config=None, clock=None):
    ctx = ToolContext(
        robot=robot,
        readings=readings,
        config=config or Settings(),
        clock=clock,
    )
    return dispatch(
        registry, "approach", {}, ctx, Journal(episode_id="ep-1"), turn=1
    )


# ---------------------------------------------------------------------------
# The model can ask for it, and cannot ask for anything else
# ---------------------------------------------------------------------------

def test_approach_is_registered(registry):
    assert "approach" in registry.names()


def test_it_takes_no_arguments_at_all(registry):
    """Not "no *physical* arguments" — none.

    §15.2 leaves the door open to a clamped target distance later, and this
    ticket is not that.
    """
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == "approach"
    )

    assert schema["function"]["parameters"].get("properties", {}) == {}


def test_an_argument_is_refused_rather_than_ignored(registry):
    """A model that sent a distance and was silently obeyed-minus-the-distance
    would believe it had control it does not have."""
    clock = FakeClock()
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()),
        readings=TickReadings(clock, distance_cm=100),
        config=Settings(),
        clock=clock,
    )

    outcome = dispatch(
        registry,
        "approach",
        {"target_distance_cm": 60},
        ctx,
        Journal(episode_id="ep-1"),
        turn=1,
    )

    assert not outcome.accepted


def test_it_does_not_end_the_episode(registry):
    """Arriving is not a reason to stop; the model may still want to speak."""
    assert not registry.get("approach").ends_episode


# ---------------------------------------------------------------------------
# The four states, driven for real, arriving unchanged
# ---------------------------------------------------------------------------

def arrived(registry):
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = SimulatedMistyAdapter(
        clock, start_cm=config.target_distance_cm, actual_motion_multiplier=1.0,
        config=config,
    )
    return run(registry, robot=world, readings=world, config=config, clock=clock)


def lost_user(registry):
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = WorldThatLosesTheUserAfterAStep(clock, start_cm=200.0, config=config)
    return run(registry, robot=world, readings=world, config=config, clock=clock)


def step_limited(registry):
    clock = FakeClock()
    return run(
        registry,
        robot=RealMistyAdapter(RecordingCommands()),
        readings=TickReadings(clock, distance_cm=100),
        config=Settings(max_approach_steps=2, post_step_settle_s=0.0),
        clock=clock,
    )


def timed_out(registry):
    clock = FakeClock()
    return run(
        registry,
        robot=RealMistyAdapter(RecordingCommands()),
        readings=TickReadings(clock, distance_cm=100),
        config=Settings(approach_timeout_s=0.3, post_step_settle_s=0.0),
        clock=clock,
    )


class StaleReadings:
    """Readings keep arriving but were all captured before the call began."""

    def __init__(self, clock):
        self._clock = clock

    def latest_reading(self):
        self._clock.sleep(0.001)
        return a_reading(100, -5.0)


class DistanceOnly:
    """What the live pipeline gives: a distance and no bearing."""

    def __init__(self, clock):
        self._clock = clock

    def latest_reading(self):
        self._clock.sleep(0.001)
        return a_reading(100, self._clock.monotonic(), bearing_deg=None, uncertainty=())


class SlipsSideways(SimulatedMistyAdapter):
    """However far the base turns, the person is still 40 degrees off."""

    def latest_reading(self):
        reading = super().latest_reading()
        return dataclasses.replace(reading, bearing_deg=40.0)


def stale_reading(registry):
    clock = FakeClock()
    return run(
        registry,
        robot=RealMistyAdapter(RecordingCommands()),
        readings=StaleReadings(clock),
        config=Settings(approach_reading_timeout_s=0.05),
        clock=clock,
    )


def bearing_unavailable(registry):
    clock = FakeClock()
    return run(
        registry,
        robot=RealMistyAdapter(RecordingCommands()),
        readings=DistanceOnly(clock),
        config=Settings(post_step_settle_s=0.0),
        clock=clock,
    )


def alignment_failed(registry):
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = SlipsSideways(clock, start_cm=150.0, bearing_deg=40.0, config=config)
    return run(registry, robot=world, readings=world, config=config, clock=clock)


def drive_error(registry):
    clock = FakeClock()
    return run(
        registry,
        robot=RealMistyAdapter(ExplodingRobot()),
        readings=TickReadings(clock, distance_cm=100),
        clock=clock,
    )


SCENARIOS = [
    ("arrived", arrived),
    ("lost_user", lost_user),
    ("stale_reading", stale_reading),
    ("bearing_unavailable", bearing_unavailable),
    ("alignment_failed", alignment_failed),
    ("step_limit", step_limited),
    ("timeout", timed_out),
    ("drive_error", drive_error),
]


@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_each_state_reaches_the_model_under_its_own_name(
    registry, expected, scenario
):
    """Four states, four names. Not three, and not "ok: false".

    Folding `lost_user` and `drive_error` together would leave the model
    unable to tell "they walked away" from "the robot refused to move" — and
    the Journal unable to show a reader which one happened.
    """
    outcome = scenario(registry)

    assert outcome.accepted
    assert outcome.result["result"] == expected


def test_between_them_the_scenarios_cover_every_state_there_is():
    """A fifth state added to the control layer and not passed through would
    otherwise be invisible here."""
    covered = {name for name, _ in SCENARIOS}

    assert covered == {status.value for status in ApproachStatus}


@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_the_step_count_reaches_the_model_too(registry, expected, scenario):
    """`episode_finished.steps` in the goldens is the sum of these."""
    outcome = scenario(registry)

    assert isinstance(outcome.result["steps"], int)
    assert outcome.result["steps"] >= 0


def test_the_steps_reported_are_the_drives_that_actually_happened(registry):
    clock = FakeClock()
    robot = RealMistyAdapter(RecordingCommands())

    outcome = run(
        registry,
        robot=robot,
        readings=TickReadings(clock, distance_cm=100),
        config=Settings(max_approach_steps=2, post_step_settle_s=0.0),
        clock=clock,
    )

    drives = [r for r in robot.commands.requests if r.endpoint == "drive/time"]
    assert outcome.result["steps"] == len(drives) == 2


def test_a_refused_drive_is_not_counted_as_a_step(registry):
    """The negative control for the count: a Tool that reported the steps it
    *intended* would say 1 here."""
    clock = FakeClock()

    outcome = run(
        registry,
        robot=RealMistyAdapter(RecordingCommands(fail_endpoints=["drive/time"])),
        readings=TickReadings(clock, distance_cm=100),
        clock=clock,
    )

    assert outcome.result["result"] == "drive_error"
    assert outcome.result["steps"] == 0


# ---------------------------------------------------------------------------
# Nothing physical escapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_no_drive_parameter_reaches_the_model(registry, expected, scenario):
    """Asserted on what is handed over, not on the signature.

    The loop underneath issues `linearVelocity` and `timeMs` on every Step —
    a signature with no parameters proves nothing about what comes back.
    """
    outcome = scenario(registry)

    handed_over = json.dumps(outcome.result).lower()
    for forbidden in ("velocity", "timems", "time_ms", "cm_per_sec", "drive_ms"):
        assert forbidden not in handed_over, forbidden


def test_the_drives_underneath_really_do_carry_what_must_not_escape(registry):
    """Otherwise the test above would pass on a loop that never drove.

    This is the negative control for the whole layering claim: the physical
    parameters exist, one layer down, and are the control layer's.
    """
    clock = FakeClock()
    robot = RealMistyAdapter(RecordingCommands())

    run(
        registry,
        robot=robot,
        readings=TickReadings(clock, distance_cm=100),
        config=Settings(max_approach_steps=1, post_step_settle_s=0.0),
        clock=clock,
    )

    drive = robot.commands.last("drive/time").json
    assert "linearVelocity" in drive
    assert "timeMs" in drive


@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_the_result_can_be_recorded_in_an_observation(registry, expected, scenario):
    """The Journal refuses to carry a control parameter (`layering.py`), and
    an Observation is where this result ends up in ticket 07. A result that
    leaked one would raise here rather than reaching a golden."""
    outcome = scenario(registry)

    record = Observation(
        t=0.0,
        episode_id="ep-1",
        turn=1,
        result=outcome.result,
        snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
    )

    assert record.result == outcome.result


def test_the_schema_the_model_sees_says_nothing_about_how_far_or_how_fast(
    registry,
):
    schema = next(
        s for s in registry.schemas() if s["function"]["name"] == "approach"
    )

    described = json.dumps(schema).lower()
    for forbidden in ("velocity", "timems", "cm", "centimet", "distance"):
        assert forbidden not in described, forbidden


# ---------------------------------------------------------------------------
# Too close is `approach` too — why there is no `back_up`
# ---------------------------------------------------------------------------

def test_standing_too_close_makes_this_tool_reverse(registry):
    """`PLAN.md` §15.2 cut `back_up` on this claim, so here it is executable.

    The same Tool, the same empty arguments, and the robot goes backwards —
    the model never learns that "closer" and "further" are different verbs,
    which is precisely the distinction it would have picked wrong.
    """
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, a_reading(30, 0.10)),
        ScheduledReading(0.20, a_reading(30, 0.20)),
        ScheduledReading(1.17, a_reading(50, 1.17)),
        ScheduledReading(1.18, a_reading(51, 1.18)),
    )
    robot = RealMistyAdapter(RecordingCommands())

    outcome = run(
        registry,
        robot=robot,
        readings=readings,
        config=Settings(approach_reading_timeout_s=0.5, post_step_settle_s=0.0),
        clock=clock,
    )

    assert outcome.result["result"] == "arrived"
    assert robot.commands.last("drive/time").json["linearVelocity"] < 0


def test_there_is_no_second_tool_for_going_backwards(registry):
    """§15.2: two Tools doing one thing means the model picks wrong, and the
    Journal cannot show why it picked wrong."""
    assert "back_up" not in registry.names()


# ---------------------------------------------------------------------------
# It is an adapter, not a second implementation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_the_tool_says_exactly_what_the_backend_said(registry, expected, scenario):
    """Same world, same config, same clock — once through the Tool and once
    through `approach()` directly.

    What this catches is renaming, folding, dropping and adding keys: the
    comparison is on the whole dict. What it does **not** catch is a retry,
    because every double here is deterministic and a second pass would agree
    with the first — `test_the_tool_does_not_retry_a_failed_drive` is what
    sees that, and it needs a double that answers differently the second time.
    Saying so here rather than claiming otherwise: `PLAN.md` §15.9 is about a
    docstring that asserted what its test could not check.
    """
    through_the_tool = scenario(registry)

    direct = {
        "arrived": lambda: _direct_arrived(),
        "lost_user": lambda: _direct_lost_user(),
        "stale_reading": lambda: _direct_stale_reading(),
        "bearing_unavailable": lambda: _direct_bearing_unavailable(),
        "alignment_failed": lambda: _direct_alignment_failed(),
        "step_limit": lambda: _direct_step_limit(),
        "timeout": lambda: _direct_timeout(),
        "drive_error": lambda: _direct_drive_error(),
    }[expected]()

    assert through_the_tool.result["result"] == direct.status.value
    assert through_the_tool.result["steps"] == direct.steps
    assert through_the_tool.result["turns"] == direct.turns
    assert len(through_the_tool.result["trace"]) == len(direct.trace)


def _direct_arrived():
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = SimulatedMistyAdapter(
        clock, start_cm=config.target_distance_cm, actual_motion_multiplier=1.0,
        config=config,
    )
    return approach(world, world, config=config, clock=clock)


def _direct_lost_user():
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = WorldThatLosesTheUserAfterAStep(clock, start_cm=200.0, config=config)
    return approach(world, world, config=config, clock=clock)


def _direct_step_limit():
    clock = FakeClock()
    return approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(RecordingCommands()),
        config=Settings(max_approach_steps=2, post_step_settle_s=0.0),
        clock=clock,
    )


def _direct_timeout():
    clock = FakeClock()
    return approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(RecordingCommands()),
        config=Settings(approach_timeout_s=0.3, post_step_settle_s=0.0),
        clock=clock,
    )


def _direct_stale_reading():
    clock = FakeClock()
    return approach(
        StaleReadings(clock), RealMistyAdapter(RecordingCommands()),
        config=Settings(approach_reading_timeout_s=0.05), clock=clock,
    )


def _direct_bearing_unavailable():
    clock = FakeClock()
    return approach(
        DistanceOnly(clock), RealMistyAdapter(RecordingCommands()),
        config=Settings(post_step_settle_s=0.0), clock=clock,
    )


def _direct_alignment_failed():
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = SlipsSideways(clock, start_cm=150.0, bearing_deg=40.0, config=config)
    return approach(world, world, config=config, clock=clock)


def _direct_drive_error():
    clock = FakeClock()
    return approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(ExplodingRobot()),
        config=Settings(),
        clock=clock,
    )


# ---------------------------------------------------------------------------
# The adapter must not become a second implementation — for real this time
# ---------------------------------------------------------------------------

class FlakyRobot(RecordingCommands):
    """Refuses the first drive and accepts the rest.

    `ExplodingRobot` is deterministic, so a Tool that quietly *retried* after a
    `drive_error` would get the same answer twice and every assertion built on
    it would still agree. That is `PLAN.md` §15.9's failure — a docstring
    claiming what its test cannot see — and this is what discriminates it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.drives = 0

    def drive_time(self, **kwargs):
        self.drives += 1
        if self.drives == 1:
            raise RuntimeError("the motors were busy")
        return super().drive_time(**kwargs)


def test_the_tool_does_not_retry_a_failed_drive(registry):
    """One call in, one attempt out.

    Retrying here would be the Tool deciding how the robot moves — §4 says
    that decision is the control layer's, and the control layer already made
    it: `drive_error` means stop and tell the model.
    """
    clock = FakeClock()
    robot = RealMistyAdapter(FlakyRobot())

    outcome = run(
        registry,
        robot=robot,
        readings=TickReadings(clock, distance_cm=100),
        clock=clock,
    )

    assert outcome.result["result"] == "drive_error"
    assert outcome.result["steps"] == 0
    assert robot.commands.drives == 1


def test_a_failed_drive_is_never_reported_as_success(registry):
    """Ticket 08 leans on this: an abort arrives as a failure part way
    through, and a Tool that swallowed it would let the Journal claim the
    robot finished a drive it was stopped from finishing.
    """
    clock = FakeClock()

    outcome = run(
        registry,
        robot=RealMistyAdapter(ExplodingRobot()),
        readings=TickReadings(clock, distance_cm=100),
        clock=clock,
    )

    assert outcome.result["result"] != "arrived"
    assert outcome.result["result"] == "drive_error"


# ---------------------------------------------------------------------------
# What a reader of the Journal sees
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected,scenario", SCENARIOS)
def test_the_state_reads_as_itself_in_the_rendered_journal(
    registry, expected, scenario
):
    """`ApproachStatus` is a `str` mixin, so returning the member instead of
    its value compares equal, serialises to the same JSON, and round-trips
    through `from_jsonl` unchanged — every other test here passes either way.

    It is the renderer that tells them apart, because an f-string calls
    `__format__` and a 3.11 mixin enum formats as `ApproachStatus.ARRIVED`.
    `PLAN.md` §4 makes that renderer a first-class Journal subscriber, so
    this is a reader of the Journal being lied to, not a cosmetic difference.
    """
    from misty_agent.agent.journal import describe_line

    outcome = scenario(registry)
    record = Observation(
        t=0.0,
        episode_id="ep-1",
        turn=1,
        result=outcome.result,
        snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
    )

    line = describe_line(record)
    assert expected in line
    assert "ApproachStatus" not in line


# ---------------------------------------------------------------------------
# The context this Tool cannot work without
# ---------------------------------------------------------------------------

def test_a_context_without_a_config_says_which_field_is_missing(registry):
    """Otherwise the failure is an `AttributeError` on `NoneType` raised from
    inside the control layer, naming neither this Tool nor the field.
    """
    ctx = ToolContext(robot=RealMistyAdapter(RecordingCommands()), readings=None)

    with pytest.raises(ValueError, match="ToolContext.config"):
        dispatch(
            registry, "approach", {}, ctx, Journal(episode_id="ep-1"), turn=1
        )


# ---------------------------------------------------------------------------
# The description promises only what M5 can deliver
# ---------------------------------------------------------------------------

def test_the_description_makes_no_safety_promise(registry):
    """`PLAN.md` §8's last bullet: `approach()` has never run on a robot.

    A description saying it will not collide would be a hardware claim this
    project has no evidence for, in the one string the model reads as fact.
    """
    described = registry.get("approach").description.lower()

    for promise in ("guarantee", "guaranteed", "never", "safe", "safely",
                    "always", "won't hit", "will not hit", "collide"):
        assert promise not in described, promise


class ReadingsThatFail:
    """A perception seam that dies part way through.

    `approach()` catches failures from the *robot* and turns them into
    `drive_error`, so a `try/except` wrapped around it looks harmless in every
    scenario above — nothing ever reaches it. What does reach it is a failure
    from anywhere else, and ticket 08's emergency stop is exactly that: it
    arrives from another thread while the Tool is running.
    """

    def latest_reading(self):
        raise RuntimeError("the episode was aborted")


def test_a_failure_from_outside_the_control_loop_is_not_turned_into_success(
    registry,
):
    """The Tool adds no `try/except` of its own, and this is what says so.

    `tests/goldens/README.md` records the decision this protects: an aborted
    Episode's `approach` reports `timeout`, **not** `arrived`, because "an
    `arrived` after a stop would say the robot completed a drive it was
    forbidden to finish." A Tool that swallowed the abort would produce
    exactly that record.
    """
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="aborted"):
        run(
            registry,
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ReadingsThatFail(),
            clock=clock,
        )

"""Ticket 11: every movement checkpoint consults the target and the safety
state, and nothing drives after a stop.

The controller here is the same simulated closed loop as ticket 10. Passing
these tests proves the control law's shape under scenario-provided safety
state; it is not a hardware safety certification, and no hazard signal has
ever been read from a Misty II.
"""

from __future__ import annotations

import json

from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.agent.journal import EpisodeFinished, Journal, Observation, ToolCalled
from misty_agent.agent.react import Decision, run_episode
from misty_agent.agent.tools import ToolContext, build_registry, dispatch
from misty_agent.app import LivePerception
from misty_agent.config import Settings
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.control.safety import ALWAYS_CLEAR, NO_HAZARD_SOURCE, HazardState
from misty_agent.fakes import FakeClock
from misty_agent.robot import SimulatedMistyAdapter
from misty_agent.scenarios import ScenarioModel

from test_approach_tool import StopAt

CONFIG = Settings(post_step_settle_s=0.0)


def room(clock, **placement):
    return SimulatedMistyAdapter(clock, start_cm=150.0, config=CONFIG, **placement)


def test_a_hazard_between_steps_stops_further_drives_and_halts():
    clock = FakeClock()
    world = room(clock, hazard_at_s=1.2)

    result = approach(world, world, config=CONFIG, clock=clock, hazards=world)

    assert result.status is ApproachStatus.BLOCKED
    assert len(world.directions) == 1
    assert result.steps == 1
    assert world.halted is True
    assert "hazard" in result.reason


def test_the_person_leaving_mid_approach_ends_as_lost_with_no_more_drives():
    clock = FakeClock()
    world = room(clock, leaves_at_s=1.2)

    result = approach(world, world, config=CONFIG, clock=clock, hazards=world)

    assert result.status is ApproachStatus.LOST_USER
    assert result.steps == len(world.directions) == 1
    assert world.halted is False


def test_a_stop_during_the_motion_wait_aborts_before_the_next_drive():
    clock = FakeClock()
    world = room(clock)

    result = approach(world, world, config=CONFIG, clock=clock, stop=StopAt(clock, 0.8), hazards=world)

    assert result.status is ApproachStatus.ABORTED
    assert len(world.directions) == 1
    assert result.motions[-1].interrupted is True
    assert "during motion 1" in result.reason
    # The stop's owner halted the motors; the controller only stops asking.
    assert world.halted is False
    assert "stop" in result.reason
    # Promptly: the wait was interrupted at the stop, not ridden out.
    assert clock.monotonic() < 0.8 + CONFIG.movement_poll_s + 0.01


def test_without_a_hazard_source_movement_fails_closed():
    """Real mode today: no hazard signal reaches the controller, so it must
    not move at all, however fresh the target reading is."""
    clock = FakeClock()
    world = room(clock)

    result = approach(world, world, config=CONFIG, clock=clock, hazards=NO_HAZARD_SOURCE)

    assert result.status is ApproachStatus.HAZARD_UNAVAILABLE
    assert world.directions == []
    assert result.steps == 0


def test_a_stale_hazard_reading_counts_as_unavailable():
    clock = FakeClock()
    world = room(clock)

    class StaleHazard:
        def latest_hazard(self):
            return HazardState(blocked=False, observed_at=-5.0, uncertainty=("old",))

    result = approach(world, world, config=CONFIG, clock=clock, hazards=StaleHazard())

    assert result.status is ApproachStatus.HAZARD_UNAVAILABLE
    assert world.directions == []


def test_a_hazard_during_a_motion_is_caught_by_the_in_motion_checkpoint():
    """Negative control for a removed checkpoint: the halt must land within
    one poll of the hazard, not at the end of the commanded motion. A
    controller that only checked between Steps would halt later than this."""
    clock = FakeClock()
    world = room(clock, hazard_at_s=0.3)

    result = approach(world, world, config=CONFIG, clock=clock, hazards=world)

    first_motion_s = result.motions[0].move_cm / CONFIG.cm_per_sec_at_percent
    assert first_motion_s > 0.6
    assert result.status is ApproachStatus.BLOCKED
    assert world.halted_at is not None
    assert 0.3 <= world.halted_at <= 0.3 + CONFIG.movement_poll_s + 0.01


def test_a_hazard_that_appears_while_settling_is_caught_before_the_next_motion():
    """Negative control for the before-motion checkpoint. With a settle
    window the last in-motion poll sees a clear path; only the check before
    the next motion can see the hazard that appeared while settling. A
    controller without that check would issue a second drive."""
    settling = Settings(post_step_settle_s=0.5)
    clock = FakeClock()
    world = SimulatedMistyAdapter(clock, start_cm=150.0, config=settling)
    first_motion_s = 35.0 / settling.cm_per_sec_at_percent
    world = SimulatedMistyAdapter(clock, start_cm=150.0, config=settling, hazard_at_s=first_motion_s + 0.2)

    result = approach(world, world, config=settling, clock=clock, hazards=world)

    assert result.status is ApproachStatus.BLOCKED
    assert len(world.directions) == 1
    assert result.motions[-1].interrupted is False
    assert "before a motion" in result.reason
    assert world.halted_at is not None and world.halted_at >= first_motion_s + settling.post_step_settle_s


def test_a_real_session_without_a_hazard_signal_refuses_to_move():
    """The Session seam, not just the Tool: a real Session has no hazard
    source, so its approach ends at the first checkpoint with no drive."""
    from misty_agent.agent.memory import Memory
    from misty_agent.app import Session
    from misty_agent.fakes import RecordingCommands, a_reading
    from misty_agent.robot import RealMistyAdapter

    clock = FakeClock()
    commands = RecordingCommands()

    class Aligned:
        def latest_reading(self):
            clock.sleep(0.001)
            return a_reading(150, clock.monotonic())

    session = Session(
        robot=RealMistyAdapter(commands), readings=Aligned(),
        model=ScenarioModel((Decision("approach", {}, 1, 1), Decision("done", {}, 1, 1))),
        memory=Memory(), config=CONFIG, clock=clock,
    )
    outcome, journal = session.episode(
        TriggerEvidence(source=EvidenceKind.SPEECH, observed_at_s=0.0, transcript="過來"), render=False,
    )

    approached = next(r for r in journal.records if isinstance(r, Observation))
    assert approached.result["result"] == "hazard_unavailable"
    assert "drive/time" not in commands.endpoints
    assert outcome.outcome == "done"


def test_a_hazard_before_the_first_motion_means_no_drive_at_all():
    clock = FakeClock()
    world = room(clock, hazard_at_s=0.0)

    result = approach(world, world, config=CONFIG, clock=clock, hazards=world)

    assert result.status is ApproachStatus.BLOCKED
    assert world.directions == [] and result.steps == 0


def test_the_stop_reason_reaches_the_model_and_it_may_speak_or_finish():
    clock = FakeClock()
    world = room(clock, hazard_at_s=1.2)
    journal = Journal(episode_id="ep-blocked", clock=clock)
    script = (
        Decision("approach", {}, 1, 1),
        Decision("speak", {"text": "前面有東西，我先停在這裡。"}, 1, 1),
        Decision("done", {}, 1, 1),
    )
    outcome = run_episode(
        TriggerEvidence(source=EvidenceKind.SPEECH, observed_at_s=0.0, transcript="過來"),
        model=ScenarioModel(script),
        registry=build_registry(),
        ctx=ToolContext(robot=world, readings=world, config=CONFIG, clock=clock, hazards=world),
        journal=journal,
        perception=LivePerception(world),
    )

    assert outcome.outcome == "done"
    approached = next(r for r in journal.records if isinstance(r, Observation) and r.turn == 1)
    assert approached.result["result"] == "blocked"
    assert approached.result["steps"] == 1
    assert approached.result["reason"]
    assert approached.snapshot.distance_cm is not None
    assert [r.tool for r in journal.records if isinstance(r, ToolCalled)] == ["approach", "speak", "done"]
    assert next(r for r in journal.records if isinstance(r, EpisodeFinished)).steps == 1


def test_the_tool_result_names_every_stop_distinctly():
    values = {status.value for status in ApproachStatus}
    assert {"arrived", "lost_user", "blocked", "aborted", "timeout", "drive_error", "hazard_unavailable"} <= values


def test_the_demo_stops_the_chassis_at_the_right_moment_for_both_built_in_cases():
    from misty_agent.demo import answer

    listed = json.loads(answer("GET", "/scenarios").body)
    keys = {f["key"] for f in listed[0]["fixtures"]}
    assert {"come-closer-target-lost", "come-closer-hazard"} <= keys

    lost = json.loads(answer("POST", "/scenarios/greeting/run", b'{"fixture":"come-closer-target-lost"}').body)
    beats = lost["execution"]["flow"]
    approach_beat = next(b for b in beats if b["kind"] == "approach")
    assert approach_beat["headline"].startswith("lost_user")
    steps = [b for b in beats if b["kind"] == "movement_step"]
    assert 1 <= len(steps) < 4
    assert lost["robot"]["halted"] is False
    assert lost["episodes"][0]["outcome"]["outcome"] == "done"

    hazard = json.loads(answer("POST", "/scenarios/greeting/run", b'{"fixture":"come-closer-hazard"}').body)
    beats = hazard["execution"]["flow"]
    approach_beat = next(b for b in beats if b["kind"] == "approach")
    assert approach_beat["headline"].startswith("blocked")
    assert hazard["robot"]["halted"] is True
    assert "hazard" in approach_beat["detail"]
    # The chassis stopped at the Moment the scenario's hazard appeared, within
    # one poll, and the page says so; nothing on the page claims certification.
    halted_at = hazard["robot"]["halted_at_s"]
    assert 1.2 <= halted_at <= 1.2 + CONFIG.movement_poll_s + 0.01
    assert f"{halted_at:g}" in approach_beat["detail"]
    assert all("certification" not in b["detail"] for b in beats)
    assert hazard["episodes"][0]["outcome"]["outcome"] == "done"

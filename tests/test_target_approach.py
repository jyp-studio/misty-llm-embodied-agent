"""Ticket 10: the chassis aligns to the Interaction Target, then approaches.

Every number here is a simulation constant. Nothing about turning rates,
travel speed or camera bearing has been measured on a Misty II; these tests
prove the control law's shape, not hardware safety.
"""

from __future__ import annotations

import json


from misty_agent.agent.evidence import EvidenceKind
from misty_agent.agent.journal import Journal
from misty_agent.agent.layering import control_parameter
from misty_agent.agent.target import InteractionTarget
from misty_agent.agent.tools import ToolContext, build_registry, dispatch
from misty_agent.config import Settings
from misty_agent.control.safety import ALWAYS_CLEAR
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.fakes import FakeClock, RecordingCommands, a_reading
from misty_agent.robot import RealMistyAdapter, SimulatedMistyAdapter

from test_approach_tool import DistanceOnly, SlipsSideways, StaleReadings

CONFIG = Settings(post_step_settle_s=0.0)


def world(start_cm=150.0, bearing_deg=0.0, **overrides):
    clock = FakeClock()
    return clock, SimulatedMistyAdapter(
        clock, start_cm=start_cm, bearing_deg=bearing_deg, config=CONFIG, **overrides
    )


def test_a_side_target_is_aligned_by_the_chassis_before_any_forward_step():
    clock, room = world(150.0, bearing_deg=25.0)
    # The head already looks at the person. That must not count as alignment.
    room.move_head(0.0, 0.0, 25.0)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ARRIVED
    kinds = [motion.kind.value for motion in result.motions]
    assert kinds[0] == "rotate"
    assert "forward" in kinds
    # No forward step is ever planned while the base is not facing the person;
    # re-aligning as the distance closes is allowed, driving sideways is not.
    assert all(
        abs(motion.bearing_deg) <= CONFIG.align_tolerance_deg
        for motion in result.motions if motion.kind.value != "rotate"
    )
    assert result.rotations >= 1
    assert result.steps == len(result.motions)
    assert result.uncertainty == ("simulated relative bearing, not a camera measurement",)
    assert abs(room.target_bearing_deg) <= CONFIG.align_tolerance_deg
    assert room.heading_deg > 0
    assert room.pose.head == (0.0, 0.0, 25.0)
    assert room.closest_cm >= CONFIG.min_safe_distance_cm
    assert abs(room.distance_cm - CONFIG.target_distance_cm) <= CONFIG.distance_tolerance_cm


def test_a_target_within_the_alignment_tolerance_needs_no_turn():
    clock, room = world(150.0, bearing_deg=2.0)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ARRIVED
    assert result.rotations == 0
    assert room.heading_deg == 0.0


def test_too_close_backs_up_into_the_arrival_band():
    clock, room = world(30.0)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ARRIVED
    assert set(room.directions) == {-1}
    assert abs(room.distance_cm - CONFIG.target_distance_cm) <= CONFIG.distance_tolerance_cm


def test_already_in_the_band_moves_nothing_and_says_so():
    clock, room = world(CONFIG.target_distance_cm)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 0 and result.motions == ()
    assert result.distance_cm == CONFIG.target_distance_cm
    assert result.bearing_deg == 0.0


def test_the_overshoot_assumption_still_holds_with_a_side_target():
    clock, room = world(150.0, bearing_deg=20.0, actual_motion_multiplier=2.0)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ARRIVED
    assert room.closest_cm >= CONFIG.min_safe_distance_cm


def test_a_target_that_keeps_slipping_sideways_ends_as_alignment_failed():
    clock = FakeClock()
    room = SlipsSideways(clock, start_cm=150.0, bearing_deg=40.0, config=CONFIG)

    result = approach(room, room, config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.ALIGNMENT_FAILED
    assert result.rotations == CONFIG.max_align_steps
    assert room.directions == []
    assert all(motion.kind.value == "rotate" for motion in result.motions)
    assert all(motion.rotate_deg <= CONFIG.max_turn_deg for motion in result.motions)


def test_a_reading_without_a_bearing_fails_closed():
    """The live distance pipeline reports no bearing. Not knowing where the
    person is relative to the chassis is not permission to drive."""
    clock = FakeClock()
    commands = RecordingCommands()
    result = approach(DistanceOnly(clock), RealMistyAdapter(commands), config=CONFIG, clock=clock, hazards=ALWAYS_CLEAR)

    assert result.status is ApproachStatus.BEARING_UNAVAILABLE
    assert result.steps == 0
    assert "drive/time" not in commands.endpoints


def test_stale_readings_are_reported_as_stale_and_a_vanished_person_as_lost():
    clock = FakeClock()
    stale = approach(StaleReadings(clock), RealMistyAdapter(RecordingCommands()), config=Settings(approach_reading_timeout_s=0.05), clock=clock, hazards=ALWAYS_CLEAR)
    assert stale.status is ApproachStatus.STALE_READING
    assert stale.steps == 0

    class Nobody:
        def latest_reading(self):
            clock.sleep(0.001)
            return None

    lost = approach(Nobody(), RealMistyAdapter(RecordingCommands()), config=Settings(approach_reading_timeout_s=0.05), clock=clock, hazards=ALWAYS_CLEAR)
    assert lost.status is ApproachStatus.LOST_USER


def test_the_step_cap_is_a_typed_bound_distinct_from_the_deadline():
    clock, room = world(400.0)

    capped = approach(room, room, config=replace_settings(max_approach_steps=2), clock=clock, hazards=ALWAYS_CLEAR)
    assert capped.status is ApproachStatus.STEP_LIMIT
    assert capped.steps == 2

    clock, room = world(400.0)
    late = approach(room, room, config=replace_settings(approach_timeout_s=0.3), clock=clock, hazards=ALWAYS_CLEAR)
    assert late.status is ApproachStatus.TIMEOUT


def replace_settings(**overrides):
    return Settings(post_step_settle_s=0.0, **overrides)


def test_the_tool_reports_a_typed_result_with_turns_and_a_bounded_trace():
    clock, room = world(150.0, bearing_deg=25.0)
    target = InteractionTarget("anon-1", EvidenceKind.VISUAL, 0.0)
    ctx = ToolContext(robot=room, readings=room, config=CONFIG, clock=clock, target=target, hazards=ALWAYS_CLEAR)

    outcome = dispatch(build_registry(), "approach", {}, ctx, Journal(episode_id="ep-1"), turn=1)

    result = outcome.result
    assert result["result"] == "arrived"
    assert result["rotations"] >= 1
    assert result["steps"] == len(result["motions"]) == outcome.steps
    assert result["target"]["track_reference"] == "anon-1"
    assert {"kind", "rotate_deg", "move_cm", "distance_cm", "bearing_deg"} <= set(result["motions"][0])
    assert result["uncertainty"] == ["simulated relative bearing, not a camera measurement"]
    # A result is the system reporting back, so it is screened the way the
    # Journal screens an Observation: no rates, no drive-command names.
    def keys_of(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys_of(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys_of(inner)
    assert [k for k in keys_of(result) if control_parameter(k, commanded=False)] == []
    schema = next(s for s in build_registry().schemas() if s["function"]["name"] == "approach")
    assert schema["function"]["parameters"].get("properties", {}) == {}
    assert "Interaction Target" in schema["function"]["description"]


def test_the_greeting_card_shows_an_approach_with_turns_steps_and_distance_changes():
    from misty_agent.demo import answer

    listed = json.loads(answer("GET", "/scenarios").body)
    assert any(f["key"] == "come-closer" for f in listed[0]["fixtures"])
    run = json.loads(answer("POST", "/scenarios/greeting/run", b'{"fixture":"come-closer"}').body)

    beats = run["execution"]["flow"]
    approach_beats = [beat for beat in beats if beat["kind"] == "approach"]
    assert approach_beats and approach_beats[0]["headline"].startswith("arrived")
    step_beats = [beat for beat in beats if beat["kind"] == "movement_step"]
    assert step_beats[0]["headline"].startswith("Step 1")
    assert "turn" in step_beats[0]["headline"]
    assert any("forward" in beat["headline"] for beat in step_beats)
    robot = run["robot"]
    assert robot["heading_deg"] > 0
    assert abs(robot["target"]["bearing_deg"]) <= CONFIG.align_tolerance_deg
    assert robot["pose"]["head"][2] == 0.0
    assert run["episodes"][0]["outcome"]["outcome"] == "done"

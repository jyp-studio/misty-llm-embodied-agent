"""The scripted person: where they are, at any instant.

Pure arithmetic over a declared script — no camera, no detector, no clock. It
is the harness's definition of truth, so it is worth being able to check by
reading it.
"""

from __future__ import annotations

import pytest

from harness.trajectory import Trajectory


def test_a_trajectory_starts_where_it_was_told_to():
    assert Trajectory.starting_at(130.0).distance_at(0.0) == 130.0


def test_a_walk_interpolates_between_its_endpoints():
    walk = Trajectory.starting_at(100.0).walk_to(60.0, over=4.0)

    assert walk.distance_at(0.0) == pytest.approx(100.0)
    assert walk.distance_at(2.0) == pytest.approx(80.0)
    assert walk.distance_at(4.0) == pytest.approx(60.0)


def test_a_hold_keeps_the_person_still():
    script = Trajectory.starting_at(90.0).hold(3.0)

    assert script.distance_at(0.0) == 90.0
    assert script.distance_at(1.5) == 90.0
    assert script.distance_at(3.0) == 90.0


def test_a_step_moves_the_person_without_taking_time():
    # The robot drove forward; the view changed between one frame and the next.
    script = Trajectory.starting_at(90.0).hold(1.0).step_to(65.0).hold(1.0)

    assert script.distance_at(0.99) == 90.0
    assert script.distance_at(1.0) == 65.0
    assert script.duration_s == pytest.approx(2.0)


def test_segments_run_back_to_back():
    script = (
        Trajectory.starting_at(130.0).walk_to(90.0, over=4.0).hold(2.0).step_to(65.0)
    )

    assert script.distance_at(4.0) == pytest.approx(90.0)
    assert script.distance_at(5.0) == pytest.approx(90.0)  # holding
    assert script.distance_at(6.0) == pytest.approx(65.0)  # stepped
    assert script.duration_s == pytest.approx(6.0)


def test_time_past_the_end_holds_the_final_position():
    script = Trajectory.starting_at(100.0).walk_to(70.0, over=2.0)

    assert script.distance_at(99.0) == pytest.approx(70.0)


def test_time_before_the_start_is_rejected():
    with pytest.raises(ValueError):
        Trajectory.starting_at(100.0).hold(1.0).distance_at(-0.1)


def test_the_same_instant_always_gives_the_same_distance():
    # The ground truth has to be reproducible even though the measurement
    # around it is not — that asymmetry is the point of the harness.
    script = Trajectory.starting_at(130.0).walk_to(90.0, over=4.0).step_to(65.0)
    instants = [i * 0.037 for i in range(200)]

    assert [script.distance_at(t) for t in instants] == [
        script.distance_at(t) for t in instants
    ]


def test_a_trajectory_describes_itself_for_the_record():
    # 06 and 09 have to state what was replayed alongside the numbers; a
    # latency figure without its trajectory is not reproducible.
    description = (
        Trajectory.starting_at(130.0).walk_to(90.0, over=4.0).step_to(65.0).describe()
    )

    assert "130" in description and "90" in description and "65" in description


def test_a_walk_must_take_time():
    with pytest.raises(ValueError):
        Trajectory.starting_at(100.0).walk_to(60.0, over=0.0)


def test_distances_must_be_positive():
    with pytest.raises(ValueError):
        Trajectory.starting_at(0.0)


# ---------------------------------------------------------------------------
# The default script
# ---------------------------------------------------------------------------

def test_the_default_script_covers_the_three_cases_the_ticket_names():
    from harness.trajectory import APPROACH_HOLD_STEP

    kinds = [segment.kind for segment in APPROACH_HOLD_STEP.segments]

    assert "walk" in kinds and "hold" in kinds and "step" in kinds


def test_the_default_script_stays_inside_the_fixtures_accurate_range():
    # The first frame of a replay is cold, and cold-start error grows with
    # distance (PLAN.md §12.5 as amended). Beyond ~195cm nothing is detected at
    # all. A script that wandered out there would measure the fixture, not the
    # pipeline.
    from harness.trajectory import APPROACH_HOLD_STEP

    reached = [
        APPROACH_HOLD_STEP.distance_at(t * 0.05)
        for t in range(int(APPROACH_HOLD_STEP.duration_s / 0.05) + 1)
    ]

    assert max(reached) <= 130.0
    assert min(reached) >= 48.0  # below the arrival band there is nothing to test


def test_the_default_script_crosses_the_distance_the_controller_acts_on():
    # The controller commands a forward step above target + tolerance. A script
    # that never crosses it would never exercise the loop it exists to measure.
    from misty_agent.config import settings
    from harness.trajectory import APPROACH_HOLD_STEP

    threshold = settings.target_distance_cm + settings.distance_tolerance_cm
    reached = [
        APPROACH_HOLD_STEP.distance_at(t * 0.05)
        for t in range(int(APPROACH_HOLD_STEP.duration_s / 0.05) + 1)
    ]

    assert max(reached) > threshold and min(reached) < threshold


def test_the_default_steps_by_what_the_control_law_would_command():
    """The step must be a move the robot would really make.

    A step of an arbitrary size would still exercise the code, but it would
    stop being a simulation of anything — and the number it produces is the
    one 06 turns into a latency figure. Pinning it here means a change to the
    control law surfaces as a failing test rather than as a script that has
    quietly drifted away from the robot it stands for.
    """
    from misty_agent.config import settings
    from misty_agent.control.step_policy import plan_step
    from harness.trajectory import APPROACH_HOLD_STEP

    step = next(s for s in APPROACH_HOLD_STEP.segments if s.kind == "step")
    commanded = plan_step(step.start_cm, settings)

    assert step.start_cm - step.end_cm == pytest.approx(commanded.commanded_cm)


def test_a_bare_starting_position_describes_itself_without_trailing_punctuation():
    assert Trajectory.starting_at(100.0).describe() == "start 100cm"

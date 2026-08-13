"""Tests for misty_agent.control.step_policy.

Three groups:

1. ``plan_step`` behaves as the control law is documented to behave.

2. The reachability functions reproduce, as executable assertions, the manual
   analysis recorded in PLAN.md §5 (defects B and C): three branches of the
   approach loop are unreachable at the default values, and defect C's branch
   becomes reachable as soon as ``distance_tolerance_cm`` drops. That second
   half is the "unexploded ordnance" claim — the code is not merely dead, it is
   dead *conditionally*.

3. A regression test for the bug the M2 code review found: the first version of
   this analysis used hand-derived closed forms, and the one for the forward
   clamp modelled only the gain term. It answered "unreachable" for a legal
   configuration in which the clamp does in fact bind.
"""

import pytest

from misty_agent.config import Settings
from misty_agent.control.step_policy import (
    ARRIVED,
    INSIDE_FLOOR,
    Step,
    arrival_bound_is_reachable,
    forward_clamp_is_reachable,
    min_forward_trigger_cm,
    min_step_is_reachable,
    plan_step,
    safety_floor_is_reachable,
)


# ---------------------------------------------------------------------------
# plan_step
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("distance", [48.1, 55.0, 60.0, 65.0, 71.9])
def test_inside_the_arrival_band_is_arrived(distance):
    assert plan_step(distance, Settings()) is ARRIVED


def test_too_far_commands_a_forward_step():
    step = plan_step(100.0, Settings())
    assert isinstance(step, Step)
    assert step.direction == 1


def test_too_close_commands_a_backward_step():
    step = plan_step(30.0, Settings())
    assert isinstance(step, Step)
    assert step.direction == -1


def test_step_yields_to_the_calibration_aware_arrival_bound():
    # Preferred: (100 - 60) * .7 = 28.  The 2x bound reserves the 52cm
    # headroom to the far edge of the arrival band, so the command is 26cm.
    step = plan_step(100.0, Settings())
    assert step.commanded_cm == pytest.approx(26.0)
    assert step.clamped_by_arrival_band is True


def test_step_is_capped_by_max_step_cm():
    # 500 - 60 = 440 remaining; the gain term is far above the 35 cm cap.
    assert plan_step(500.0, Settings()).commanded_cm == pytest.approx(35.0)


def test_backward_direction_uses_the_shared_arrival_bound():
    step = plan_step(10.0, Settings())
    assert step.direction == -1
    assert step.clamped_by_floor is False
    assert step.clamped_by_arrival_band is True


def test_commanded_distance_is_always_positive():
    for d in [1.0, 10.0, 30.0, 100.0, 500.0]:
        outcome = plan_step(d, Settings())
        if isinstance(outcome, Step):
            assert outcome.commanded_cm > 0


def test_config_names_the_uncalibrated_actual_motion_bound():
    cfg = Settings()

    assert cfg.max_actual_motion_multiplier == pytest.approx(2.0)
    assert "UNCALIBRATED" in Settings.model_fields[
        "max_actual_motion_multiplier"
    ].description


def test_each_direction_is_bounded_by_the_far_edge_of_the_arrival_band():
    cfg = Settings(
        distance_tolerance_cm=5.0,
        approach_gain=0.2,
        min_step_cm=30.0,
    )
    lower = cfg.target_distance_cm - cfg.distance_tolerance_cm
    upper = cfg.target_distance_cm + cfg.distance_tolerance_cm

    forward = plan_step(80.0, cfg)
    backward = plan_step(50.0, cfg)

    assert isinstance(forward, Step)
    assert isinstance(backward, Step)
    assert (
        80.0 - forward.commanded_cm * cfg.max_actual_motion_multiplier
        >= lower
    )
    assert (
        50.0 + backward.commanded_cm * cfg.max_actual_motion_multiplier
        <= upper
    )


# ---------------------------------------------------------------------------
# Reachability — PLAN.md §5 defects B and C
# ---------------------------------------------------------------------------

def test_forward_steps_only_start_beyond_the_trigger_distance():
    assert min_forward_trigger_cm(Settings()) == 72.0


def test_defect_B_safety_floor_branch_is_unreachable_by_default():
    """A forward step needs d > 72 cm; the floor guard needs d <= 45 cm."""
    assert safety_floor_is_reachable(Settings()) is False


def test_defect_B_forward_clamp_never_binds_by_default():
    """The arrival-band bound is stricter than the defensive floor bound."""
    assert forward_clamp_is_reachable(Settings()) is False


def test_shared_arrival_bound_is_reachable_by_default():
    assert arrival_bound_is_reachable(Settings()) is True


def test_defect_C_min_step_bound_is_unreachable_by_default():
    """abs(delta) > 12 implies abs(delta) * 0.7 > 8.4 > 8."""
    assert min_step_is_reachable(Settings()) is False


def test_defect_B_safety_floor_branch_is_unreachable_for_EVERY_valid_config():
    """Stronger than "dead at the defaults": dead by construction.

    The guard fires only when ``min_safe > target + tolerance``, while the
    config validator demands ``target - tolerance > min_safe``. Together those
    give ``tolerance < 0``, which the field constraints forbid. So no
    configuration ``Settings`` accepts can ever reach that branch.

    Travel beyond ``max_actual_motion_multiplier`` is still unknown; this only
    proves the old fallback branch cannot be selected by a valid config.
    """
    from pydantic import ValidationError

    grid = [10.0, 30.0, 45.0, 60.0, 90.0, 150.0]
    accepted = 0
    for target in grid:
        for tol in [1.0, 5.0, 12.0, 20.0, 40.0]:
            for floor in grid:
                try:
                    s = Settings(
                        target_distance_cm=target,
                        distance_tolerance_cm=tol,
                        min_safe_distance_cm=floor,
                    )
                except ValidationError:
                    continue
                accepted += 1
                assert safety_floor_is_reachable(s) is False, (
                    f"target={target} tol={tol} floor={floor}"
                )
    assert accepted > 0, "the sweep rejected every configuration — check the grid"


@pytest.mark.parametrize(
    "override",
    [
        {"distance_tolerance_cm": 11.0},  # 11 * 0.7 = 7.7 < 8
        {"approach_gain": 0.5},           # 12 * 0.5 = 6.0 < 8
        {"min_step_cm": 10.0},            # 12 * 0.7 = 8.4 < 10
    ],
)
def test_defect_C_min_step_bound_becomes_live(override):
    """Dead only at the current values — three separate ways to wake it."""
    assert min_step_is_reachable(Settings(**override)) is True


# ---------------------------------------------------------------------------
# Regression — the M2 code review finding
# ---------------------------------------------------------------------------

def test_arrival_bound_reachability_accounts_for_the_min_step_floor():
    """Regression: reachability must scan the real law, not hand-copy it.

    ``min_step_cm=30`` passes every validator. At d = 73 cm the gain term is
    13 * 0.7 = 9.1, raised to the 30 cm preference.  The shared 2x bound
    shortens that to 12.5 cm, so maximum assumed travel stops at 48 cm.
    """
    cfg = Settings(min_step_cm=30.0)

    step = plan_step(73.0, cfg)
    assert step.clamped_by_arrival_band is True
    assert step.clamped_by_floor is False
    assert step.commanded_cm == pytest.approx(12.5)

    assert arrival_bound_is_reachable(cfg) is True


def test_bounded_step_never_crosses_the_floor_at_the_assumed_maximum():
    """Conditional property: actual travel is at most the configured bound."""
    cfg = Settings(min_step_cm=30.0)
    d = 45.05
    while d <= 500.0:
        outcome = plan_step(d, cfg)
        if isinstance(outcome, Step) and outcome.direction == 1:
            maximum_travel = (
                outcome.commanded_cm * cfg.max_actual_motion_multiplier
            )
            assert d - maximum_travel >= cfg.min_safe_distance_cm - 1e-9, (
                f"d={d} step={outcome.commanded_cm}"
            )
        d += 0.05

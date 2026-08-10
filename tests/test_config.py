"""Tests for misty_agent.config.

Two things are being pinned down here:

1. The cross-field validators reject configurations in which the arrival band
   overlaps the safety floor. That relationship is the one thing standing
   between "converges to a social distance" and "declares success at a
   distance it is forbidden to occupy".

2. The reachability properties reproduce, as executable assertions, the manual
   analysis recorded in PLAN.md §5 (defects B and C): three branches of
   ``approach_user`` are unreachable at the default values, and defect C's
   branch becomes reachable as soon as ``distance_tolerance_cm`` drops. That
   second half is the "unexploded ordnance" claim — the code is not merely
   dead, it is dead *conditionally*.
"""

import pytest
from pydantic import ValidationError

from misty_agent.config import Settings


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_defaults_load():
    s = Settings()
    assert s.target_distance_cm == 60.0
    assert s.distance_tolerance_cm == 12.0
    assert s.min_safe_distance_cm == 45.0
    assert s.max_approach_steps == 8


def test_settings_are_frozen():
    s = Settings()
    with pytest.raises(ValidationError):
        s.target_distance_cm = 99.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MISTY_TARGET_DISTANCE_CM", "80")
    monkeypatch.setenv("MISTY_ROBOT_IP", "10.0.0.5")
    s = Settings(_env_file=None)
    assert s.target_distance_cm == 80.0
    assert s.robot_ip == "10.0.0.5"


# ---------------------------------------------------------------------------
# Cross-field validators
# ---------------------------------------------------------------------------

def test_arrival_band_must_clear_the_safety_floor():
    # 60 - 20 = 40, which is inside the 45 cm floor: the loop could report
    # "arrived" while standing closer than it is ever allowed to be.
    with pytest.raises(ValidationError, match="arrival band"):
        Settings(distance_tolerance_cm=20.0)


def test_arrival_band_exactly_on_the_floor_is_rejected():
    # 60 - 15 == 45 exactly. Touching the floor is not clearing it.
    with pytest.raises(ValidationError, match="arrival band"):
        Settings(distance_tolerance_cm=15.0)


def test_min_step_must_be_below_max_step():
    with pytest.raises(ValidationError, match="min_step_cm"):
        Settings(min_step_cm=40.0, max_step_cm=35.0)


def test_fold_size_cannot_exceed_window():
    with pytest.raises(ValidationError, match="memory_fold_size"):
        Settings(memory_window=4, memory_fold_size=10)


@pytest.mark.parametrize(
    "field, value",
    [
        ("drive_percent", 0),
        ("drive_percent", 101),
        ("approach_gain", 0.0),
        ("approach_gain", 1.5),
        ("max_approach_steps", 0),
        ("cm_per_sec_at_percent", 0.0),
        ("focal_length", -1.0),
        ("sensor_transport_lag_s", -0.1),
    ],
)
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_sensor_transport_lag_may_be_zero():
    # Zero is the honest default: it is not a measurement, it is "unmodelled".
    assert Settings(sensor_transport_lag_s=0.0).sensor_transport_lag_s == 0.0


# ---------------------------------------------------------------------------
# Reachability — PLAN.md §5 defects B and C, as executable assertions
# ---------------------------------------------------------------------------

def test_defect_B_safety_floor_branch_is_unreachable_by_default():
    """A forward step needs d > 72 cm; the floor guard needs d <= 45 cm."""
    s = Settings()
    assert s.min_forward_trigger_cm == 72.0
    assert s.safety_floor_is_reachable is False


def test_defect_B_forward_clamp_never_binds_by_default():
    """0.7 * (d - 60) < d - 45 holds for every d > 10, so the clamp is inert."""
    assert Settings().forward_clamp_is_reachable is False


def test_defect_C_min_step_bound_is_unreachable_by_default():
    """abs(delta) > 12 implies abs(delta) * 0.7 > 8.4 > 8."""
    assert Settings().min_step_is_reachable is False


def test_defect_C_min_step_bound_becomes_live_when_tolerance_drops():
    """The unexploded-ordnance claim: dead only at the current values.

    Lower the tolerance to 11 and the 8 cm floor starts binding again — and
    the backward direction has no clamp at all, so the step it forces can
    overshoot and oscillate until the step cap stops it.
    """
    s = Settings(distance_tolerance_cm=11.0)
    assert s.min_step_is_reachable is True


def test_defect_B_safety_floor_branch_is_unreachable_for_EVERY_valid_config():
    """Stronger than "dead at the defaults": dead by construction.

    The guard fires only when ``min_safe > target + tolerance``, while the
    validator demands ``target - tolerance > min_safe``. Together those give
    ``tolerance < 0``, which the field constraints forbid. So no configuration
    this module accepts can ever reach that branch.

    The consequence for PLAN.md §5 defect B: the runtime guard is redundant,
    because the invariant is enforced at load time instead. What the validator
    does NOT address — and what M6 still must — is that the floor clamps the
    *commanded* distance rather than the *travelled* distance, so calibration
    error can still carry the robot past it.
    """
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
                assert s.safety_floor_is_reachable is False, (
                    f"target={target} tol={tol} floor={floor}"
                )
    assert accepted > 0, "the sweep rejected every configuration — check the grid"


def test_reachability_properties_agree_with_a_brute_force_sweep():
    """Cross-check the closed-form properties against enumeration.

    The properties are algebra; this walks the actual decision the control law
    makes over the reachable distance domain and confirms the same answer.
    """
    s = Settings()
    floor_fired = False
    clamp_bit = False
    min_step_bound_bit = False

    d = 0.1
    while d <= 1000.0:
        delta = d - s.target_distance_cm
        if abs(delta) > s.distance_tolerance_cm and delta > 0:  # forward step
            gain_step = abs(delta) * s.approach_gain
            step = min(s.max_step_cm, max(s.min_step_cm, gain_step))
            if gain_step < s.min_step_cm:
                min_step_bound_bit = True
            max_forward = d - s.min_safe_distance_cm
            if max_forward <= 0:
                floor_fired = True
            elif max_forward < step:
                clamp_bit = True
        d += 0.1

    assert floor_fired == s.safety_floor_is_reachable
    assert clamp_bit == s.forward_clamp_is_reachable
    assert min_step_bound_bit == s.min_step_is_reachable

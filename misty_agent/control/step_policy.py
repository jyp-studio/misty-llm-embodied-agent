"""The approach controller's step decision, in one place.

`plan_step` is the single implementation of "given a measured distance, what
does the robot do next". It has three consumers — the runtime controller, the
reachability analysis below, and the tests — so that none of them can drift
from the others. A copy of this logic living in a test was how the bug in the
first version of the reachability analysis stayed invisible.

Nothing here imports the config module: callers pass their settings object in.
That keeps the dependency pointing one way (config -> nothing) and lets tests
drive the policy with throwaway parameter sets.

None of this touches hardware or measures anything. It is arithmetic over a
measured distance, and it is therefore fully verifiable without a robot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class StepPolicyConfig(Protocol):
    """The slice of the settings this module reads."""

    target_distance_cm: float
    distance_tolerance_cm: float
    min_safe_distance_cm: float
    max_step_cm: float
    min_step_cm: float
    approach_gain: float


@dataclass(frozen=True)
class Step:
    """A commanded step. `commanded_cm` is always positive; see `direction`."""

    direction: int  # +1 toward the user, -1 away
    commanded_cm: float
    #: True when the forward step was shortened to stop at the safety floor.
    clamped_by_floor: bool
    #: True when the gain term was below `min_step_cm` and got raised to it.
    raised_to_min_step: bool


#: Returned instead of a Step when no motion is wanted.
ARRIVED = "arrived"
#: Returned when a forward step was called for but the robot is already inside
#: the safety floor. Unreachable for any configuration `Settings` accepts —
#: see `safety_floor_is_reachable`.
INSIDE_FLOOR = "inside_floor"


def plan_step(
    measured_cm: float, cfg: StepPolicyConfig
) -> Step | str:
    """Decide the next move. Returns a `Step`, `ARRIVED`, or `INSIDE_FLOOR`.

    The command is a *distance*, never a velocity or a duration — converting it
    to `drive_time` arguments is the caller's job, and it is the only place a
    calibration constant enters.
    """
    delta = measured_cm - cfg.target_distance_cm
    if abs(delta) <= cfg.distance_tolerance_cm:
        return ARRIVED

    direction = 1 if delta > 0 else -1

    gain_step = abs(delta) * cfg.approach_gain
    commanded = min(cfg.max_step_cm, max(cfg.min_step_cm, gain_step))
    raised_to_min_step = gain_step < cfg.min_step_cm

    clamped_by_floor = False
    if direction > 0:
        headroom = measured_cm - cfg.min_safe_distance_cm
        if headroom <= 0:
            return INSIDE_FLOOR
        if headroom < commanded:
            commanded = headroom
            clamped_by_floor = True

    return Step(
        direction=direction,
        commanded_cm=commanded,
        clamped_by_floor=clamped_by_floor,
        raised_to_min_step=raised_to_min_step,
    )


def min_forward_trigger_cm(cfg: StepPolicyConfig) -> float:
    """Smallest measured distance at which a FORWARD step is commanded."""
    return cfg.target_distance_cm + cfg.distance_tolerance_cm


# ---------------------------------------------------------------------------
# Reachability analysis — PLAN.md §5, defects B and C
#
# These answer "can this branch ever execute for this configuration?". They are
# computed by sweeping `plan_step` rather than by closed-form algebra: the first
# version of this analysis used hand-derived formulas, and the one for the
# forward clamp was wrong because it modelled only the gain term and forgot
# that `min_step_cm` can raise the commanded step above it. Sweeping the real
# function cannot make that class of mistake.
# ---------------------------------------------------------------------------

#: Distance domain the sweep covers, in cm, and its resolution. The upper bound
#: is far beyond any distance a face-width estimate stays meaningful at.
_SWEEP_MAX_CM = 2000.0
_SWEEP_STEP_CM = 0.05


def _sweep(cfg: StepPolicyConfig):
    d = _SWEEP_STEP_CM
    while d <= _SWEEP_MAX_CM:
        yield d, plan_step(d, cfg)
        d += _SWEEP_STEP_CM


def safety_floor_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether `plan_step` can ever return `INSIDE_FLOOR`.

    False for every configuration `misty_agent.config.Settings` accepts: its
    validator demands ``target - tolerance > min_safe``, while this branch needs
    ``min_safe > target + tolerance``; together they give ``tolerance < 0``.
    The invariant is enforced at config load instead of at runtime.

    This does NOT dispose of PLAN.md defect B. The floor bounds the *commanded*
    distance, not the distance actually travelled, so calibration error can
    still carry the robot past it. That is M6's problem.
    """
    return any(outcome is INSIDE_FLOOR for _, outcome in _sweep(cfg))


def forward_clamp_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether the safety floor ever actually shortens a forward step."""
    return any(
        isinstance(outcome, Step) and outcome.clamped_by_floor
        for _, outcome in _sweep(cfg)
    )


def min_step_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether `min_step_cm` ever raises a commanded step.

    False at the default values (PLAN.md defect C): a step is only commanded
    when ``abs(delta) > distance_tolerance_cm``, so the gain term always exceeds
    ``12 * 0.7 = 8.4``, which is above the 8 cm floor. Lower the tolerance to 11
    — or the gain to 0.5 — and it starts binding. The backward direction has no
    clamp at all, so the step it forces there can overshoot.
    """
    return any(
        isinstance(outcome, Step) and outcome.raised_to_min_step
        for _, outcome in _sweep(cfg)
    )

"""The approach controller's step decision, in one place.

`plan_step` is the single implementation of "given a measured distance, what
does the robot do next". The runtime controller, reachability analysis,
robustness sweep (through public ``approach``), and tests all use it, so none
of them can drift. A copy of this logic living in a test was how the bug in the
first version of the reachability analysis stayed invisible.

Nothing here imports the config module: callers pass their settings object in.
That keeps the dependency pointing one way (config -> nothing) and lets tests
drive the policy with throwaway parameter sets.

None of this touches hardware or measures anything. It is arithmetic over a
measured distance, and it is therefore fully verifiable without a robot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StepPolicyConfig(Protocol):
    """The slice of the settings this module reads."""

    target_distance_cm: float
    distance_tolerance_cm: float
    min_safe_distance_cm: float
    max_step_cm: float
    min_step_cm: float
    approach_gain: float
    max_actual_motion_multiplier: float


@dataclass(frozen=True)
class Step:
    """A commanded step. `commanded_cm` is always positive; see `direction`."""

    direction: int  # +1 toward the user, -1 away
    commanded_cm: float
    #: True when the explicit forward safety-floor cap shortened the step.
    clamped_by_floor: bool
    #: True when the shared arrival-band cap shortened either direction.
    clamped_by_arrival_band: bool
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

    First choose the gain/min/max preference.  Then cap both directions so an
    actual monotone excursion up to ``max_actual_motion_multiplier`` times the
    command cannot cross the far edge of the arrival band.  Forward motion also
    carries an explicit safety-floor cap; the valid-config invariant makes the
    arrival cap stricter, but keeping both makes the safety premise visible.

    The multiplier is UNCALIBRATED.  This is a conditional software guarantee,
    not a hardware claim; excursions beyond the configured bound are unknown.
    Conversion of the returned distance to velocity and duration remains the
    caller's responsibility.
    """
    delta = measured_cm - cfg.target_distance_cm
    if abs(delta) <= cfg.distance_tolerance_cm:
        return ARRIVED

    direction = 1 if delta > 0 else -1

    gain_step = abs(delta) * cfg.approach_gain
    preferred = min(cfg.max_step_cm, max(cfg.min_step_cm, gain_step))
    raised_to_min_step = gain_step < cfg.min_step_cm

    lower_arrival_cm = cfg.target_distance_cm - cfg.distance_tolerance_cm
    upper_arrival_cm = cfg.target_distance_cm + cfg.distance_tolerance_cm
    if direction > 0:
        distance_to_far_edge = measured_cm - lower_arrival_cm
    else:
        distance_to_far_edge = upper_arrival_cm - measured_cm
    arrival_cap = max(
        0.0,
        distance_to_far_edge / cfg.max_actual_motion_multiplier,
    )

    floor_cap = float("inf")
    if direction > 0:
        headroom = measured_cm - cfg.min_safe_distance_cm
        if headroom <= 0:
            return INSIDE_FLOOR
        floor_cap = headroom / cfg.max_actual_motion_multiplier

    commanded = min(preferred, arrival_cap, floor_cap)
    clamped_by_arrival_band = arrival_cap < preferred
    clamped_by_floor = floor_cap < min(preferred, arrival_cap)

    return Step(
        direction=direction,
        commanded_cm=commanded,
        clamped_by_floor=clamped_by_floor,
        clamped_by_arrival_band=clamped_by_arrival_band,
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

    M5 closes the calibration-error hole conditionally: each forward command
    is divided by the configured maximum actual-motion multiplier.  Exceeding
    that uncalibrated assumption remains unknown.
    """
    return any(outcome is INSIDE_FLOOR for _, outcome in _sweep(cfg))


def forward_clamp_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether the explicit floor cap ever shortens a forward step.

    The arrival band's lower edge is required to sit outside the floor, so its
    shared cap is normally stricter.  Keeping this scan makes that relationship
    executable rather than silently deleting the defensive floor bound.
    """
    return any(
        isinstance(outcome, Step) and outcome.clamped_by_floor
        for _, outcome in _sweep(cfg)
    )


def arrival_bound_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether the shared arrival-band bound shortens a preferred step."""
    return any(
        isinstance(outcome, Step) and outcome.clamped_by_arrival_band
        for _, outcome in _sweep(cfg)
    )


def min_step_is_reachable(cfg: StepPolicyConfig) -> bool:
    """Whether `min_step_cm` ever raises a commanded step.

    False at the default values (PLAN.md defect C): a step is only commanded
    when ``abs(delta) > distance_tolerance_cm``, so the gain term always exceeds
    ``12 * 0.7 = 8.4``, which is above the 8 cm floor. Lower the tolerance to 11
    — or the gain to 0.5 — and it starts binding.  The shared arrival-band cap
    takes precedence in both directions, so a live minimum cannot force an
    overshoot through the band.
    """
    return any(
        isinstance(outcome, Step) and outcome.raised_to_min_step
        for _, outcome in _sweep(cfg)
    )

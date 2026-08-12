"""How much unmeasurable delay the approach controller can absorb.

Tickets 04–07 watch the perception pipeline with the robot standing still.
This closes the loop: the robot moves because of what it was told, and what it
was told is out of date. The question is how out of date it can be before the
controller stops converging.

## Why this is a sweep and not a measurement

The path from the world to a distance reading has two halves:

```
[truth] ─ exposure → encode → RTSP over WiFi ─▶ [in process] ─ buffer/detect ─▶ [reading]
        └────── segment A: needs hardware ─────┘  └──── segment B: ticket 06 measured this ────┘
```

Segment B is 43 ms, measured. **Segment A has never been measured and cannot
be** — it needs a robot on a network, and this project has neither and will
have neither (PLAN.md §1). ``settings.sensor_transport_lag_s`` has carried an
``UNCALIBRATED`` marker since M2 with nothing reading it; this is what reads it.

The honest response to an unknown number is not to guess it. It is to show how
large it would have to be before it mattered. Every figure this module produces
is a **parameter sweep**, and every summary says so.

## The perception model

A delay line with centimetre quantisation, holding the last value rather than
interpolating — frames are discrete arrivals, not a continuous signal. Both
properties are what ticket 06 *measured* the real pipeline to do, not
assumptions about it, and ``test_the_model_reproduces_the_lag_it_was_given``
checks the model with the same estimator that measured the real thing.

What the model leaves out, beyond the obvious: the controller under review
does not read a single sample. ``get_distance`` takes the **median of a window**
of recent samples and refuses to answer with fewer than two, which is defect A3
and adds staleness this model does not have. The delay line matches the
*reference* pipeline ticket 06 measured, not the one in ``full_robot_v3``, so
every figure here **understates** how bad the current controller is. It also
leaves out MediaPipe's per-frame cost, its cross-frame tracking, and the
detection dropouts beyond 195 cm. Including them would mean
running the real detector through eight control steps per configuration and
several seconds of settle each — minutes per sweep, and non-deterministic.
The omission is defensible because ticket 06 measured the real pipeline's
behaviour to be a delay of 43 ms plus 1 cm quantisation and very little else;
it is recorded here because "defensible" is not "identical".

## Nothing here is a threshold

Where convergence stops is a fact to report. It is not a standard the code has
to pass, and no test asserts a limit on it — the number is about a quantity
nobody has measured.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from misty_agent.config import Settings, settings as default_settings
from misty_agent.control import step_policy
from misty_agent.control.step_policy import plan_step

#: Segment B, as ticket 06 measured it. See
#: docs/measurements/m4-latency-baseline.md — this one *is* a measurement, and
#: it is added to every swept transport lag so the sweep asks about total
#: staleness rather than about segment A alone.
MEASURED_PIPELINE_LAG_S = 0.043

#: How finely the simulated world is sampled, in seconds. One camera frame at
#: 30 fps: sampling the world more finely than the camera does would give the
#: delay line information the pipeline could never have had.
WORLD_STEP_S = 1.0 / 30.0


class DelayedPerception:
    """Reports where the person was, one lag ago, to the nearest centimetre.

    Zero-order hold, not interpolation: a reading comes from a frame, and the
    most recent frame to have arrived is the last one taken at or before
    ``t - lag``. Interpolating would invent a reading between two frames and
    make the model smoother than the thing it stands for.

    ``read`` returns ``None`` when the delayed instant predates anything
    observed — the state a pipeline is in before its first frame has been
    through, which the controller sees as having no distance at all.
    """

    def __init__(self, lag_s: float) -> None:
        if lag_s < 0:
            raise ValueError(f"lag cannot be negative, got {lag_s}")
        self._lag_s = lag_s
        self._times: List[float] = []
        self._distances: List[float] = []

    def observe(self, t: float, distance_cm: float) -> None:
        """The world was ``distance_cm`` at instant ``t``.

        Observations must arrive in ascending time order. ``read`` bisects
        them, so an out-of-order one does not raise — it makes every later
        lookup wrong, which is how the first version of the priming loop
        turned a 0.1 s lag into "the pipeline never reported anything".
        """
        if self._times and t < self._times[-1]:
            raise ValueError(
                f"observations must arrive in time order: {t} after "
                f"{self._times[-1]}"
            )
        self._times.append(t)
        self._distances.append(distance_cm)

    def read(self, t: float) -> Optional[int]:
        """What the pipeline would report at ``t``, or ``None`` if nothing yet."""
        delayed_to = t - self._lag_s
        index = bisect_right(self._times, delayed_to) - 1
        if index < 0:
            return None
        # Truncated, matching FaceReading.distance_cm.
        return int(self._distances[index])


@dataclass(frozen=True)
class ApproachOutcome:
    """What one approach did, under one assumed transport lag."""

    transport_lag_s: float
    outcome: str  # "arrived" | "timeout" | "lost"
    steps: int
    closest_cm: float
    final_cm: float
    settings: Settings

    @property
    def inside_safety_floor(self) -> bool:
        """Whether the robot ever got closer than it is allowed to.

        PLAN.md defect B: the floor clamps the *commanded* distance, never the
        distance actually travelled, so a miscalibrated robot walks through it
        without the clamp ever firing.
        """
        return self.closest_cm < self.settings.min_safe_distance_cm

    @property
    def converged(self) -> bool:
        """Arrived, in the band, without having breached the floor on the way."""
        band = self.settings.distance_tolerance_cm
        target = self.settings.target_distance_cm
        return (
            self.outcome == "arrived"
            and abs(self.final_cm - target) <= band
            and not self.inside_safety_floor
        )


def simulate_approach(
    *,
    transport_lag_s: float,
    start_cm: float = 130.0,
    speed_error: float = 1.0,
    settings: Optional[Settings] = None,
    pipeline_lag_s: float = MEASURED_PIPELINE_LAG_S,
) -> ApproachOutcome:
    """Drive the real control law with readings that are ``lag`` seconds old.

    ``speed_error`` multiplies the distance actually travelled against the
    distance commanded: 1.0 is a perfectly calibrated robot, 2.0 one that moves
    twice as far as it thinks. That constant — ``cm_per_sec_at_percent`` — has
    never been measured either.

    The control law is *called*, not modelled. PLAN.md §10 records a
    hand-derived closed form of this same logic that was wrong and passed its
    tests anyway.
    """
    cfg = settings or default_settings
    eyes = DelayedPerception(lag_s=transport_lag_s + pipeline_lag_s)

    # The person was already standing there before the robot woke up, so the
    # delay line has something to report on the first look. Primed forwards:
    # observations must arrive in ascending time order or the lookup, which
    # bisects them, silently returns nonsense.
    t, distance = 0.0, start_cm
    priming_frames = int((transport_lag_s + pipeline_lag_s) / WORLD_STEP_S) + 2
    for frame in range(priming_frames, 0, -1):
        eyes.observe(-frame * WORLD_STEP_S, start_cm)
    eyes.observe(t, distance)

    closest = distance
    for step_index in range(cfg.max_approach_steps):
        reported = eyes.read(t)
        if reported is None or reported <= 0:
            return ApproachOutcome(
                transport_lag_s, "lost", step_index, closest, distance, cfg
            )

        decision = plan_step(float(reported), cfg)
        if decision is step_policy.ARRIVED or decision is step_policy.INSIDE_FLOOR:
            return ApproachOutcome(
                transport_lag_s, "arrived", step_index, closest, distance, cfg
            )

        travelled = decision.commanded_cm * speed_error * decision.direction
        drive_s = decision.commanded_cm / cfg.cm_per_sec_at_percent
        t, distance = _advance(eyes, t, distance, distance - travelled, drive_s)
        closest = min(closest, distance)
        # The robot waits for the motion to finish and for fresh frames. This
        # is where most of a transport lag goes to die: anything shorter than
        # the settle has expired before the next reading is taken.
        t, distance = _advance(eyes, t, distance, distance, cfg.post_step_settle_s)

    return ApproachOutcome(
        transport_lag_s, "timeout", cfg.max_approach_steps, closest, distance, cfg
    )


def _advance(
    eyes: DelayedPerception,
    t: float,
    from_cm: float,
    to_cm: float,
    duration_s: float,
) -> Tuple[float, float]:
    """Run the world forward, letting the camera see every frame of it."""
    frames = max(1, int(duration_s / WORLD_STEP_S))
    for frame in range(1, frames + 1):
        fraction = frame / frames
        eyes.observe(
            t + duration_s * fraction, from_cm + (to_cm - from_cm) * fraction
        )
    return t + duration_s, to_cm


#: Resolution the published sweep is run at, in seconds. Coarser grids do not
#: merely lose precision — they report the wrong *failure mode*. The first
#: published table stepped 1.5 → 2.0 and so never saw the overshoot band at
#: 1.60–1.70, reporting the collision beyond it as the first failure.
SWEEP_STEP_S = 0.05


def default_sweep_lags(
    upto_s: float = 3.0, step_s: float = SWEEP_STEP_S
) -> Tuple[float, ...]:
    """The lags the published sweep covers, starting from the configured value.

    ``settings.sensor_transport_lag_s`` has carried an ``UNCALIBRATED`` marker
    since M2. This is what finally reads it: it is where the sweep starts, so
    that anyone who does calibrate it sees their own value at the left edge
    rather than a hard-coded zero.
    """
    start = default_settings.sensor_transport_lag_s
    count = int((upto_s - start) / step_s) + 1
    return tuple(round(start + i * step_s, 6) for i in range(max(1, count)))


def sweep_transport_lag(
    lags_s: Optional[Sequence[float]] = None, **kwargs
) -> Tuple[ApproachOutcome, ...]:
    """One approach per assumed transport lag, in the order given."""
    lags = default_sweep_lags() if lags_s is None else lags_s
    return tuple(
        simulate_approach(transport_lag_s=lag, **kwargs) for lag in lags
    )


@dataclass(frozen=True)
class RobustnessEnvelope:
    """Where the controller stops converging, and how it breaks past there."""

    largest_converging_lag_s: Optional[float]
    first_failing_lag_s: Optional[float]
    failure_mode: Optional[str]
    #: Smallest swept lag at which the robot broke the safety floor. Reported
    #: separately from the first failure because they need not be the same
    #: value — the controller overshoots the arrival band before it gets close
    #: enough to be dangerous, and reporting only the collision hides a whole
    #: band of failure.
    first_floor_breach_s: Optional[float]
    #: Spacing of the swept values. The boundary can only ever be located to
    #: within this, and a coarse grid does not merely blur it — it can skip an
    #: entire failure mode and report the next one as the first.
    resolution_s: Optional[float]
    outcomes: Tuple[ApproachOutcome, ...]

    def summary(self) -> str:
        if self.largest_converging_lag_s is None:
            head = "the controller converged at no swept lag"
        elif self.first_failing_lag_s is None:
            head = (
                f"the controller converged at every swept lag, up to "
                f"{self.largest_converging_lag_s:.2f}s"
            )
        else:
            head = (
                f"converges up to {self.largest_converging_lag_s:.2f}s of "
                f"transport lag; at {self.first_failing_lag_s:.2f}s it fails by "
                f"{self.failure_mode}"
            )
            if self.first_floor_breach_s is not None:
                head += (
                    f", and breaches the safety floor from "
                    f"{self.first_floor_breach_s:.2f}s"
                )
        grid = (
            "" if self.resolution_s is None
            else f" (located to ±{self.resolution_s:.2f}s by the sweep grid)"
        )
        return (
            f"{head}{grid} [parameter sweep, NOT a measurement — "
            f"sensor_transport_lag_s has never been measured and cannot be "
            f"without hardware]"
        )


def envelope(outcomes: Sequence[ApproachOutcome]) -> RobustnessEnvelope:
    """Read the boundary out of a sweep.

    ``largest_converging_lag_s`` is the largest lag that converged, and
    ``first_failing_lag_s`` the smallest that did not. They are reported
    separately rather than as one boundary because the two need not be
    adjacent — a controller that fails, recovers, and fails again is telling
    you something, and collapsing it to a single number would hide it.
    """
    ordered = sorted(outcomes, key=lambda o: o.transport_lag_s)
    converging = [o for o in ordered if o.converged]
    failing = [o for o in ordered if not o.converged]

    first_failure = failing[0] if failing else None
    breaches = [o for o in ordered if o.inside_safety_floor]
    spacings = [
        b.transport_lag_s - a.transport_lag_s for a, b in zip(ordered, ordered[1:])
    ]
    return RobustnessEnvelope(
        largest_converging_lag_s=(
            converging[-1].transport_lag_s if converging else None
        ),
        first_failing_lag_s=(
            first_failure.transport_lag_s if first_failure else None
        ),
        failure_mode=_failure_mode(first_failure) if first_failure else None,
        first_floor_breach_s=breaches[0].transport_lag_s if breaches else None,
        resolution_s=max(spacings) if spacings else None,
        outcomes=tuple(ordered),
    )


def _failure_mode(outcome: ApproachOutcome) -> str:
    """What went wrong, in the vocabulary the ticket asks about.

    ``overshoot`` comes before ``collision`` as the lag grows: the controller
    ends outside the arrival band well before it ends inside the safety floor.
    A sweep coarse enough to skip the overshoot band reports the collision as
    the first failure, which is what the first published table did.
    """
    if outcome.inside_safety_floor:
        return "collision"
    if outcome.outcome != "arrived":
        return outcome.outcome
    return "overshoot"

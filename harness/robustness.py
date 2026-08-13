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

The sweep now enters through public ``approach()``.  It therefore exercises
the real two-reading minimum, freshness epochs, median aggregation, settling,
step cap, timeout, and the one formal ``plan_step`` implementation.  What it
does not rerun at every grid point is MediaPipe: the delay line substitutes the
43 ms process lag and 1 cm quantisation measured by ticket 06.  Cross-frame
tracking, detection dropouts beyond 195 cm, focal-length error, and motor
transients remain outside the model.  The separate real-time replay keeps the
production DistancePipeline under the M4 latency bound.

## Nothing here is a threshold

Where convergence stops is a fact to report. It is not a standard the code has
to pass, and no test asserts a limit on it — the number is about a quantity
nobody has measured.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from types import SimpleNamespace
from typing import List, Literal, Optional, Sequence, Tuple

from misty_agent.config import Settings, settings as default_settings
from misty_agent.control.approach import approach
from misty_agent.perception.distance import DistanceReading

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
        sample = self.sample(t)
        return sample[1] if sample is not None else None

    def sample(self, t: float) -> Optional[Tuple[float, int]]:
        """Latest available ``(capture time, distance)`` at ``t``."""
        delayed_to = t - self._lag_s
        index = bisect_right(self._times, delayed_to) - 1
        if index < 0:
            return None
        # Truncated, matching FaceReading.distance_cm.
        return self._times[index], int(self._distances[index])


@dataclass(frozen=True)
class ApproachOutcome:
    """What one approach did, under one assumed transport lag."""

    transport_lag_s: float
    outcome: Literal["arrived", "lost_user", "timeout", "drive_error"]
    steps: int
    closest_cm: float
    final_cm: float
    settings: Settings
    actual_motion_multiplier: float

    @property
    def inside_safety_floor(self) -> bool:
        """Whether the robot ever got closer than it is allowed to.

        This is simulator truth, not something the runtime controller can
        observe through a delayed distance reading.
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

    @property
    def audited_outcome(self) -> str:
        """Truth-audited result; stale-reading success cannot hide failure."""
        if self.inside_safety_floor:
            return "safety_floor_breach"
        if self.outcome != "arrived":
            return self.outcome
        if not self.converged:
            return "overshoot"
        return "arrived"


@dataclass(frozen=True)
class _Motion:
    start_s: float
    end_s: float
    from_cm: float
    to_cm: float


class _SimulatedWorld:
    """Fake clock, reading source, and robot adapter for public ``approach``.

    Frames are captured at 30 fps.  A frame reaches the process after the
    swept transport lag, then becomes a reading after the measured process
    lag.  Consequently ``frame_arrived_at`` exposes only process-local age,
    exactly like the production pipeline: transport staleness cannot be
    detected from inside the process.
    """

    def __init__(
        self,
        *,
        transport_lag_s: float,
        pipeline_lag_s: float,
        start_cm: float,
        actual_motion_multiplier: float,
        config: Settings,
    ) -> None:
        if transport_lag_s < 0 or pipeline_lag_s < 0:
            raise ValueError("perception lags cannot be negative")
        if actual_motion_multiplier < 0:
            raise ValueError("actual motion multiplier cannot be negative")

        self._transport_lag_s = transport_lag_s
        self._pipeline_lag_s = pipeline_lag_s
        self._actual_motion_multiplier = actual_motion_multiplier
        self._config = config
        self._now_s = 0.0
        self._distance_cm = start_cm
        self.closest_cm = start_cm
        self._motion: Optional[_Motion] = None
        self._eyes = DelayedPerception(transport_lag_s + pipeline_lag_s)

        total_lag_s = transport_lag_s + pipeline_lag_s
        priming_frames = int(total_lag_s / WORLD_STEP_S) + 2
        for frame in range(priming_frames, -1, -1):
            self._eyes.observe(-frame * WORLD_STEP_S, start_cm)
        self._next_capture_s = WORLD_STEP_S

    @property
    def distance_cm(self) -> float:
        return self._distance_cm

    def monotonic(self) -> float:
        return self._now_s

    def latest_reading(self) -> Optional[DistanceReading]:
        sample = self._eyes.sample(self._now_s)
        if sample is None:
            return None
        captured_at, distance_cm = sample
        frame_arrived_at = captured_at + self._transport_lag_s
        return DistanceReading(
            distance_cm=distance_cm,
            frame_arrived_at=frame_arrived_at,
            detected_at=frame_arrived_at + self._pipeline_lag_s,
        )

    def drive_time(
        self,
        linearVelocity: float,
        angularVelocity: float,
        timeMs: int,
        timeout: float,
    ):
        del angularVelocity, timeout
        duration_s = timeMs / 1000.0
        commanded_cm = duration_s * self._config.cm_per_sec_at_percent
        direction = 1 if linearVelocity > 0 else -1
        travelled_cm = commanded_cm * self._actual_motion_multiplier
        self._motion = _Motion(
            start_s=self._now_s,
            end_s=self._now_s + duration_s,
            from_cm=self._distance_cm,
            to_cm=self._distance_cm - direction * travelled_cm,
        )
        return SimpleNamespace(status_code=200)

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep cannot go backwards")
        end_s = self._now_s + seconds
        while self._next_capture_s <= end_s + 1e-12:
            distance_cm = self._distance_at(self._next_capture_s)
            self._eyes.observe(self._next_capture_s, distance_cm)
            self.closest_cm = min(self.closest_cm, distance_cm)
            self._next_capture_s += WORLD_STEP_S

        self._distance_cm = self._distance_at(end_s)
        self.closest_cm = min(self.closest_cm, self._distance_cm)
        self._now_s = end_s
        if self._motion is not None and end_s >= self._motion.end_s - 1e-12:
            self._distance_cm = self._motion.to_cm
            self.closest_cm = min(self.closest_cm, self._distance_cm)
            self._motion = None

    def _distance_at(self, instant_s: float) -> float:
        motion = self._motion
        if motion is None:
            return self._distance_cm
        if instant_s <= motion.start_s:
            return motion.from_cm
        if instant_s >= motion.end_s:
            return motion.to_cm
        fraction = (instant_s - motion.start_s) / (motion.end_s - motion.start_s)
        return motion.from_cm + (motion.to_cm - motion.from_cm) * fraction


def simulate_approach(
    *,
    transport_lag_s: float,
    start_cm: float = 130.0,
    speed_error: Optional[float] = None,
    settings: Optional[Settings] = None,
    pipeline_lag_s: float = MEASURED_PIPELINE_LAG_S,
) -> ApproachOutcome:
    """Drive public :func:`approach` with readings that are ``lag`` seconds old.

    ``speed_error`` multiplies the distance actually travelled against the
    distance commanded: 1.0 is a perfectly calibrated robot, 2.0 one that moves
    twice as far as it thinks. That constant — ``cm_per_sec_at_percent`` — has
    never been measured either.

    ``None`` uses the configured maximum actual-motion multiplier, so the
    published sweep exercises the edge of the conditional calibration
    assumption.  Values above it may still be simulated, but are explicitly
    outside the guarantee.
    """
    cfg = settings or default_settings
    actual_multiplier = (
        cfg.max_actual_motion_multiplier if speed_error is None else speed_error
    )
    world = _SimulatedWorld(
        transport_lag_s=transport_lag_s,
        pipeline_lag_s=pipeline_lag_s,
        start_cm=start_cm,
        actual_motion_multiplier=actual_multiplier,
        config=cfg,
    )
    result = approach(world, world, config=cfg, clock=world)
    return ApproachOutcome(
        transport_lag_s=transport_lag_s,
        outcome=result.status.value,
        steps=result.steps,
        closest_cm=world.closest_cm,
        final_cm=world.distance_cm,
        settings=cfg,
        actual_motion_multiplier=actual_multiplier,
    )


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
    failure_mode: Optional[
        Literal[
            "arrived",
            "overshoot",
            "safety_floor_breach",
            "lost_user",
            "timeout",
            "drive_error",
        ]
    ]
    #: Smallest swept lag at which the robot broke the safety floor. Reported
    #: separately from the first failure because they need not be the same.
    #: Under M5's published 2x sweep they coincide at 0.70s; retaining both
    #: fields prevents a future control-law change from hiding either fact.
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
                    f", and the first swept safety-floor breach is at "
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
    """What went wrong according to simulator truth, never raw status alone."""
    return outcome.audited_outcome

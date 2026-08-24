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

Tests do pin the *counters* in fully specified scenarios — a fixed lag and a
fixed travel multiplier make a deterministic run, and its reversal count is a
property of the model rather than a claim about where any envelope lands.
Pinning those numbers is what stops the published table drifting away from the
code that produced it.
"""

from __future__ import annotations

import random
from bisect import bisect_right
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Literal, Optional, Sequence, Tuple

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

    ## Reading noise, and why it is measured in pixels

    ``jitter_px`` perturbs the *apparent face width* of each frame, not its
    distance. That is where detector error actually lives: ``FaceDetector``
    divides a calibration constant by the pixel width between the cheeks, so a
    wobble of a fixed number of pixels costs centimetres in proportion to the
    **square** of distance. Under the default constants one pixel is 0.21 cm
    at the 45 cm safety floor and 4.10 cm at 200 cm.

    The deleted simulation runner injected a flat ±N centimetres instead,
    which demanded physically impossible wobble close up — 17 % of the face at
    the floor — while under-supplying it far away. It was wrong in both
    directions at once, and wrong hardest exactly where the safety conclusion
    is decided.

    The wobble of a given frame is keyed on **when that frame was taken**,
    not on how many frames came before it. Keying it on call order would
    confound the two swept parameters: the world primes the delay line with
    one frame per lag-second before the run starts, so a longer lag would
    consume more draws and hand the controller a different noise realisation.
    A row-to-row difference would then mix transport lag with a fresh draw,
    and the two-dimensional sweep would be reading its own bookkeeping.

    ``jitter_px`` is **UNCALIBRATED**, in the same sense
    ``sensor_transport_lag_s`` is: it has never been measured, and it cannot
    be without a robot and a real scene. Sweeping it says how much wobble the
    controller could absorb. It says nothing about how much there is.
    """

    def __init__(
        self,
        lag_s: float,
        *,
        jitter_px: float = 0.0,
        focal_length: float = default_settings.focal_length,
        real_face_width_cm: float = default_settings.real_face_width_cm,
        seed: int = 0,
    ) -> None:
        if lag_s < 0:
            raise ValueError(f"lag cannot be negative, got {lag_s}")
        if jitter_px < 0:
            raise ValueError(f"jitter cannot be negative, got {jitter_px}")
        self._lag_s = lag_s
        self._jitter_px = jitter_px
        self._px_cm = focal_length * real_face_width_cm
        self._seed = seed
        self._times: List[float] = []
        self._distances: List[float] = []

    def observe(self, t: float, distance_cm: float) -> None:
        """The world was ``distance_cm`` at instant ``t``.

        Observations must arrive in ascending time order. ``read`` bisects
        them, so an out-of-order one does not raise — it makes every later
        lookup wrong, which is how the first version of the priming loop
        turned a 0.1 s lag into "the pipeline never reported anything".

        Jitter is applied **here**, once per frame, rather than at read time.
        A frame is detected once; if the same frame reported differently on
        each poll, ``approach``'s median would average away noise that no real
        pipeline can average away, and the sweep would describe a steadier
        controller than the one that exists.
        """
        if self._times and t < self._times[-1]:
            raise ValueError(
                f"observations must arrive in time order: {t} after "
                f"{self._times[-1]}"
            )
        detected_cm = self._detect(t, distance_cm)
        if detected_cm is None:
            # No usable face in this frame. `DistancePipeline` skips such a
            # frame rather than storing an unknown distance, so the previous
            # reading stays on offer until it ages out; recording nothing here
            # is what reproduces that.
            return
        self._times.append(t)
        self._distances.append(detected_cm)

    def _detect(self, t: float, distance_cm: float) -> Optional[float]:
        """One detection of a person at ``distance_cm``, wobble included."""
        if self._jitter_px == 0.0:
            return distance_cm
        true_width_px = self._px_cm / distance_cm
        # Seeded with a string rather than a tuple: `random` hashes str with
        # SHA-512, so the draw is identical across processes and unaffected by
        # PYTHONHASHSEED. Python 3.11 refuses tuples outright.
        wobble_px = random.Random(f"{self._seed}:{t!r}").uniform(
            -self._jitter_px, self._jitter_px
        )
        detected_width_px = true_width_px + wobble_px
        if detected_width_px <= 0.0:
            return None
        return self._px_cm / detected_width_px

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
    #: How many times two consecutive commands went in opposite directions.
    #:
    #: Neither other axis can see this one. A controller that chatters at the
    #: edge of the arrival band breaches no floor and can still report
    #: `arrived`, so `inside_safety_floor` and `converged` both call it a
    #: success. It is noise's characteristic failure, which is why it is
    #: counted rather than left for the noise sweep to happen to notice.
    #:
    #: What the sweep found, stated carefully. At the *configured* travel
    #: multiplier this is zero at every swept lag — but that is a fact about
    #: one multiplier, not about the assumption it stands for: at 1.5x, which
    #: the same assumption covers, 12 of the 61 published lags reverse.
    #: Reversal is not monotone in travel multiplier (PLAN.md §14.8), so no
    #: row can be inferred from a neighbouring one.
    #:
    #: A clean count is also not a safety result. The worst floor breach in
    #: that table reverses zero times and reports `arrived`.
    direction_reversals: int = 0
    #: Which point of the two-dimensional sweep this row is. Carried on the
    #: outcome so that everything downstream — grouping, aggregating,
    #: rendering — is a pure function of the rows, testable in milliseconds
    #: without running a simulation, let alone a camera.
    jitter_px: float = 0.0
    seed: int = 0

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
        jitter_px: float = 0.0,
        seed: int = 0,
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
        self._last_direction: Optional[int] = None
        self.direction_reversals = 0
        self._eyes = DelayedPerception(
            transport_lag_s + pipeline_lag_s,
            jitter_px=jitter_px,
            focal_length=config.focal_length,
            real_face_width_cm=config.real_face_width_cm,
            seed=seed,
        )

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
        # Counted per command issued. This world never refuses one, so issued
        # and completed do not part company here; a world that could refuse
        # would have to count after the refusal check instead.
        if self._last_direction is not None and direction != self._last_direction:
            self.direction_reversals += 1
        self._last_direction = direction
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
    jitter_px: float = 0.0,
    seed: int = 0,
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

    ``jitter_px`` is detector wobble in pixels of apparent face width — see
    :class:`DelayedPerception` for why the parameter is pixels and not
    centimetres. It is UNCALIBRATED. ``seed`` selects which realisation of
    that wobble is simulated: one seed is one draw, and a single draw is not a
    result. `report.PUBLISHED_RUNS` exists because a single run was published
    as one once already.
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
        jitter_px=jitter_px,
        seed=seed,
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
        direction_reversals=world.direction_reversals,
        jitter_px=jitter_px,
        seed=seed,
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


# ---------------------------------------------------------------------------
# The second dimension
#
# Two unknowns, not one. Transport lag makes the controller act on old data —
# a systematic error. Jitter makes it act on wrong data — a zero-mean one the
# median mostly absorbs. Sweeping only the second, with lag pinned at zero,
# would miss the combination that matters: lag has already carried the robot
# too close when a reading that reads *further* than the truth calls for one
# more step forward.
#
# Two dimensions is the shape of the experiment. It is emphatically not the
# shape of the report — see `boundary_curve`.
# ---------------------------------------------------------------------------

#: Detector wobble the published sweep covers, in pixels of apparent face
#: width. Geometric rather than linear because the interesting question is an
#: order of magnitude, not a decimal place: under the default calibration one
#: pixel is 0.2 cm at the safety floor and 4.1 cm at 200 cm, so 16 px is
#: already far past anything a working detector would produce.
#:
#: UNCALIBRATED, exactly as `sensor_transport_lag_s` is. Sweeping it says how
#: much wobble the controller could absorb. It says nothing about how much
#: there is, and there is no way to find out without a robot and a real scene.
DEFAULT_SWEEP_JITTERS_PX = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)

#: How many noise realisations each grid point is run at. One draw is not a
#: result — ticket 03 measured the outcome moving between seeds at high
#: jitter, and `report.PUBLISHED_RUNS` exists because a single run was once
#: published as one.
DEFAULT_SWEEP_SEEDS = (0, 1, 2, 3, 4)


def sweep_lag_and_jitter(
    *,
    jitters_px: Sequence[float] = DEFAULT_SWEEP_JITTERS_PX,
    lags_s: Optional[Sequence[float]] = None,
    seeds: Sequence[int] = DEFAULT_SWEEP_SEEDS,
    **kwargs,
) -> Tuple[ApproachOutcome, ...]:
    """One approach per (lag, jitter, seed). Every row carries its coordinates."""
    lags = default_sweep_lags() if lags_s is None else lags_s
    return tuple(
        simulate_approach(
            transport_lag_s=lag_s, jitter_px=jitter_px, seed=seed, **kwargs
        )
        for jitter_px in jitters_px
        for seed in seeds
        for lag_s in lags
    )


@dataclass(frozen=True)
class JitterRow:
    """What one jitter level did, across every seed and lag."""

    jitter_px: float
    seeds: Tuple[int, ...]
    #: How many grid points this row summarises. Carried because the failure
    #: counts below are meaningless without it: the lag axis is deliberately
    #: swept far past the boundary, so most rows failing is the shape of the
    #: experiment rather than a finding.
    rows_swept: int
    #: The largest lag at which **every** seed still converged. The pessimistic
    #: reading is the honest one for an envelope: a controller is only as
    #: robust as its unlucky draw.
    largest_converging_lag_s: Optional[float]
    #: The luckiest seed's answer, kept so the spread is visible rather than
    #: averaged away.
    best_case_lag_s: Optional[float]
    first_failing_lag_s: Optional[float]
    failure_mode: Optional[str]
    #: The three failure modes, counted apart. They are not the same event and
    #: each can hide the others — M6 #04 found the worst floor breach in its
    #: table reversing zero times, and reversal is invisible to both other
    #: axes.
    floor_breaching_rows: int
    non_converging_rows: int
    reversing_rows: int
    #: Reversals among runs that still converged. So far always zero, which is
    #: what makes reversal a symptom of an already-failing run rather than a
    #: mode of its own. If it ever stops being zero the report has to say so.
    reversing_rows_inside_envelope: int

    @property
    def seeds_disagree(self) -> bool:
        return self.largest_converging_lag_s != self.best_case_lag_s


@dataclass(frozen=True)
class BoundaryCurve:
    """The surface, reduced to the one line anybody can read.

    A two-dimensional sweep produces a surface, and a surface printed in full
    is a table nobody reads. The question it exists to answer is single: how
    far does detector wobble move the transport-lag envelope? One row per
    jitter level answers it, and if the answer is "hardly at all" that is a
    result rather than a disappointment.
    """

    rows: Tuple[JitterRow, ...]
    lag_resolution_s: Optional[float]
    jitter_resolution_px: Optional[float]

    def summary(self) -> str:
        quiet = [row for row in self.rows if row.largest_converging_lag_s is None]
        known = [
            row for row in self.rows if row.largest_converging_lag_s is not None
        ]
        if not known:
            head = "no swept jitter level converged at any lag"
        else:
            baseline = known[0]
            lo = min(row.largest_converging_lag_s for row in known)
            hi = max(row.largest_converging_lag_s for row in known)
            head = (
                f"across {self.rows[-1].jitter_px:.0f}px of detector wobble the "
                f"transport-lag envelope moves between {lo:.2f}s and {hi:.2f}s, "
                f"against {baseline.largest_converging_lag_s:.2f}s with no "
                f"wobble at all"
            )
            if self.lag_resolution_s is not None:
                steps = round((hi - lo) / self.lag_resolution_s)
                head += (
                    f" — a spread of {steps} grid step"
                    f"{'' if steps == 1 else 's'}"
                )
        if quiet:
            head += f"; {len(quiet)} level(s) converged nowhere"
        grid = ""
        if self.lag_resolution_s is not None:
            grid = f" (located to ±{self.lag_resolution_s:.2f}s by the lag grid"
            if self.jitter_resolution_px is not None:
                grid += (
                    f", the jitter grid's widest step being "
                    f"{self.jitter_resolution_px:.0f}px"
                )
            grid += ")"
        return (
            f"{head}{grid} [parameter sweep, NOT a measurement — both "
            f"sensor_transport_lag_s and detector jitter are UNCALIBRATED and "
            f"neither can be measured without hardware]"
        )


def boundary_curve(outcomes: Sequence[ApproachOutcome]) -> BoundaryCurve:
    """Reduce a two-dimensional sweep to one row per jitter level.

    Pure: rows in, curve out. Nothing here simulates anything, so the report
    it feeds can be tested in milliseconds against hand-built rows.
    """
    if not outcomes:
        raise ValueError("a boundary curve needs at least one swept outcome")

    by_jitter: Dict[float, List[ApproachOutcome]] = {}
    for outcome in outcomes:
        by_jitter.setdefault(outcome.jitter_px, []).append(outcome)

    rows = []
    for jitter_px in sorted(by_jitter):
        at_jitter = by_jitter[jitter_px]
        seeds = tuple(sorted({outcome.seed for outcome in at_jitter}))

        per_seed = []
        for seed in seeds:
            converging = [
                outcome.transport_lag_s
                for outcome in at_jitter
                if outcome.seed == seed and outcome.converged
            ]
            per_seed.append(max(converging) if converging else None)

        failing = sorted(
            (outcome for outcome in at_jitter if not outcome.converged),
            key=lambda outcome: outcome.transport_lag_s,
        )
        known = [lag for lag in per_seed if lag is not None]
        rows.append(
            JitterRow(
                jitter_px=jitter_px,
                seeds=seeds,
                rows_swept=len(at_jitter),
                largest_converging_lag_s=(
                    min(per_seed) if per_seed and None not in per_seed else None
                ),
                best_case_lag_s=max(known) if known else None,
                first_failing_lag_s=(
                    failing[0].transport_lag_s if failing else None
                ),
                failure_mode=_failure_mode(failing[0]) if failing else None,
                floor_breaching_rows=sum(
                    1 for outcome in at_jitter if outcome.inside_safety_floor
                ),
                non_converging_rows=len(failing),
                reversing_rows=sum(
                    1 for outcome in at_jitter if outcome.direction_reversals
                ),
                reversing_rows_inside_envelope=sum(
                    1
                    for outcome in at_jitter
                    if outcome.direction_reversals and outcome.converged
                ),
            )
        )

    return BoundaryCurve(
        rows=tuple(rows),
        lag_resolution_s=_step({o.transport_lag_s for o in outcomes}),
        jitter_resolution_px=_step(set(by_jitter)),
    )


def _step(values: Sequence[float]) -> Optional[float]:
    """The widest gap between adjacent swept values, or ``None`` if only one.

    The widest, not the average: the boundary can only ever be located to
    within the coarsest part of the grid, and quoting the average would flatter
    it.
    """
    ordered = sorted(values)
    gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
    return max(gaps) if gaps else None

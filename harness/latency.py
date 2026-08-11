"""How far behind reality the pipeline's distance readings are.

Reads a :class:`Trace` and nothing else — no camera, no detector, no clock — so
a trace recorded once can be re-analysed without replaying it, and a
disagreement about how to compute lag does not cost ten seconds of wall time.

Two estimators, because neither alone answers the question:

:func:`lag_samples` inverts the truth curve: for each reading, how long ago the
truth last equalled it. One number per sample, so percentiles mean something.
**It is only defined while the world is changing.** With nobody moving, every
recent instant matches the reading equally well; the estimator returns nothing
rather than inventing a number. That blind spot is not an accident of the
method — it is the reason a stale reading went unnoticed for so long. A robot
facing a stationary person cannot tell.

:func:`lag_by_correlation` shifts the whole reported series against the whole
truth series and keeps the alignment that fits best. One number, no
distribution, but it uses every row — including the step, where inversion has
nothing to work with. Its job is to disagree: if the two methods diverge on a
trace where both are defined, one of them is wrong and the number should not be
published.

:func:`throughput` answers the separate question PLAN.md §12.2 raised. The
pipeline has no backpressure, so nothing stops the buffer growing except the
consumer happening to be faster than the producer. This reports both costs and
the frame rate at which they cross.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from harness.replay import Sample, Trace

#: How far above the physical floor a pipeline's p95 lag may sit.
#:
#: Deliberately **not an absolute millisecond figure**. PLAN.md §12.2 measured
#: the same code running an order of magnitude faster on one machine than the
#: plan assumed on another, so a fixed threshold would encode this laptop into
#: the test suite and fail on the Docker image for reasons that have nothing to
#: do with the pipeline. Expressed against ``ThroughputReport.lag_floor_s`` it
#: scales with the host and still says something real: *the pipeline may not
#: cost more than the delivery and detection it cannot avoid.*
#:
#: 2.0 is where the reference pipeline sits with room to spare — measured p95
#: 43 ms against a 38 ms floor, a ratio of 1.13 — so a rewrite that doubled the
#: overhead would still pass, while one that queued frames or filtered over a
#: stale window would not. See docs/measurements/m4-latency-baseline.md.
MAX_LAG_OVER_FLOOR = 2.0

#: A reading is only invertible where the truth is actually moving. Below this
#: rate the curve is flat enough that many instants match equally well, and the
#: answer would be an artefact of where the search happened to stop.
MIN_MEASURABLE_SPEED_CM_S = 5.0

#: Faster than any person walks. A change above this between two adjacent
#: samples is not somebody moving — it is the robot having driven, and the
#: scene jumping between one frame and the next.
#:
#: Inversion must not go anywhere near such a jump. A value that occurs on both
#: sides of it has two crossings, and matching the wrong one produces an answer
#: off by however long the script spent between them. That is not a small
#: error: on a trace built with exactly 40 ms of lag, four samples straddling
#: the default script's step came back at **+1.5 seconds**. They passed the
#: speed filter precisely because the jump made the local speed enormous.
MAX_HUMAN_SPEED_CM_S = 300.0

#: ``FaceReading.distance_cm`` is a truncated whole number, so a reported 89
#: means the pipeline believed something in [89, 90). Both estimators here work
#: by matching a reported value against the truth curve, and on a *falling*
#: curve a value biased low matches a *later* instant — so untreated,
#: truncation makes the pipeline look faster than it is.
#:
#: The bias is not small. It is half a centimetre of distance, which converts
#: to ``0.5 / speed`` seconds: **75 ms at the default script's 6.7 cm/s**, which
#: is larger than the lag being measured. Adding half the quantum back is the
#: midpoint of the interval the reading actually denotes, and removes the bias
#: exactly rather than approximately.
QUANTISATION_CM = 1.0


def lag_resolution_s(trace: Trace) -> Optional[float]:
    """The finest lag this trace could possibly show.

    Readings are quantised to whole centimetres, so the earliest and latest
    instants consistent with one reading are ``1 cm / speed`` apart. A lag
    below that is not resolvable however the numbers are crunched — the
    information is not in the trace. Ticket 06 has to print this next to the
    figure, or a 25 ms answer read off a 150 ms grid looks like a measurement.
    """
    times, truths = _truth_curve(trace.samples)
    speeds = [
        speed
        for i in range(len(times))
        if (speed := _local_speed_cm_s(times, truths, i)) >= MIN_MEASURABLE_SPEED_CM_S
    ]
    if not speeds:
        return None
    # The median, not the maximum. A step is an instantaneous change, so its
    # local speed is enormous and taking the maximum would report a resolution
    # of a few milliseconds for a script that in fact cannot resolve anything
    # finer than a tenth of a second.
    return QUANTISATION_CM / statistics.median(speeds)


@dataclass(frozen=True)
class LagReport:
    """How far behind the readings ran, and under what conditions.

    ``p50_s`` and ``p95_s`` are ``None`` when nothing in the trace was
    measurable — a replay of someone standing still, or one where the pipeline
    never reported. That is a different statement from "the lag was zero", and
    conflating the two would let a broken run look like a perfect one.
    """

    p50_s: Optional[float]
    p95_s: Optional[float]
    correlation_s: Optional[float]
    measured_samples: int
    total_samples: int
    #: Finest lag the trace could resolve; see :func:`lag_resolution_s`.
    resolution_s: Optional[float]
    trajectory: str
    environment: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if self.p50_s is None:
            return (
                f"no measurable lag in {self.total_samples} samples "
                f"({self.trajectory})"
            )
        resolution = (
            "" if self.resolution_s is None
            else f", resolvable to {self.resolution_s * 1000:.0f}ms"
        )
        return (
            f"lag p50 {self.p50_s * 1000:.0f}ms, p95 {self.p95_s * 1000:.0f}ms "
            f"over {self.measured_samples}/{self.total_samples} samples"
            f"{resolution} ({self.trajectory})"
        )


@dataclass(frozen=True)
class ThroughputReport:
    """What keeps the frame buffer empty, and when it would stop working."""

    producer_interval_s: float
    consumer_cost_s: float
    observed_backlog_max: int

    @property
    def ratio(self) -> float:
        """Consumer cost over producer interval. Above 1.0 the buffer grows."""
        return self.consumer_cost_s / self.producer_interval_s

    @property
    def inversion_fps(self) -> float:
        """Frame rate at which the consumer stops keeping up."""
        return 1.0 / self.consumer_cost_s

    @property
    def lag_floor_s(self) -> float:
        """The least lag any pipeline on this hardware could show.

        A reading cannot describe the world more recently than the frame it
        came from, and that frame is on average half a frame period old before
        it is even delivered — a whole one by the time the next would arrive.
        Add the cost of looking at it and you have the floor. Nothing in the
        rewrite can go below this without changing the frame rate or the
        detector.
        """
        return self.producer_interval_s + self.consumer_cost_s

    def summary(self) -> str:
        return (
            f"consumer {self.consumer_cost_s * 1000:.1f}ms vs producer "
            f"{self.producer_interval_s * 1000:.1f}ms (ratio {self.ratio:.2f}); "
            f"buffer grows above {self.inversion_fps:.0f} fps; "
            f"lag floor {self.lag_floor_s * 1000:.0f}ms"
        )


# ---------------------------------------------------------------------------
# Inversion
# ---------------------------------------------------------------------------

def _truth_curve(samples: Sequence[Sample]) -> Tuple[List[float], List[float]]:
    return [s.t for s in samples], [s.truth_cm for s in samples]


#: Half-width, in samples, of the window local speed is measured over.
_SPEED_WINDOW = 2


def _local_speed_cm_s(times: List[float], truths: List[float], i: int) -> float:
    """How fast the truth is changing around sample ``i``.

    Returns 0.0 across a discontinuity rather than the enormous rate the jump
    implies, so a step is treated as "not measurable here" instead of "moving
    very fast indeed".
    """
    lo, hi = max(0, i - _SPEED_WINDOW), min(len(times) - 1, i + _SPEED_WINDOW)
    span = times[hi] - times[lo]
    if span <= 0 or _contains_jump(times, truths, lo, hi):
        return 0.0
    return abs(truths[hi] - truths[lo]) / span


def _contains_jump(
    times: List[float], truths: List[float], lo: int, hi: int
) -> bool:
    """Whether the truth jumps discontinuously anywhere in ``[lo, hi]``."""
    for j in range(lo + 1, hi + 1):
        interval = times[j] - times[j - 1]
        if interval <= 0:
            continue
        if abs(truths[j] - truths[j - 1]) / interval > MAX_HUMAN_SPEED_CM_S:
            return True
    return False


def _continuous_run(
    times: List[float], truths: List[float], around: int
) -> Tuple[int, int]:
    """The stretch either side of ``around`` with no discontinuity in it.

    Inversion searches only here. Searching the whole trace would let a reading
    match a moment on the far side of a step, where the person was at the same
    distance for an entirely unrelated reason.
    """
    lo = around
    while lo > 0 and not _contains_jump(times, truths, lo - 1, lo):
        lo -= 1
    hi = around
    last = len(times) - 1
    while hi < last and not _contains_jump(times, truths, hi, hi + 1):
        hi += 1
    return lo, hi


def _instant_truth_equalled(
    times: List[float],
    truths: List[float],
    near: int,
    value: float,
    bounds: Tuple[int, int],
) -> Optional[float]:
    """When the truth was ``value``, at the crossing nearest to sample ``near``.

    Interpolates across the recorded pair that brackets the value. Returns
    ``None`` when the curve never reached it — which happens early in a replay,
    before the pipeline has caught up with anything.

    **The search runs both directions.** Looking only backwards would be the
    physical story — a reading can only come from the past — but it makes the
    estimator incapable of returning a negative number, and quantisation noise
    scatters individual estimates either side of the truth. Truncating that
    scatter at zero biases the mean upward by half the noise: on a trace built
    with no lag at all, a backwards-only search reports 30 ms. That is the same
    order as the lag actually being measured, so the bias would have been
    indistinguishable from the result.

    ``bounds`` confines the search to a stretch with no discontinuity in it,
    within which a falling curve crosses a value once. Without that confinement
    a reading can match a moment on the far side of a step — the person was at
    that distance then too, for an unrelated reason — and the answer is out by
    however long the script spent in between.
    """
    lo, hi = bounds
    best: Optional[float] = None
    for j in range(lo + 1, hi + 1):
        earlier, later = truths[j - 1], truths[j]
        if earlier == later or (earlier - value) * (later - value) > 0:
            continue
        fraction = (value - earlier) / (later - earlier)
        instant = times[j - 1] + fraction * (times[j] - times[j - 1])
        if best is None or abs(instant - times[near]) < abs(best - times[near]):
            best = instant
    return best


def lag_samples(trace: Trace) -> Tuple[float, ...]:
    """Per-sample lag, in seconds, wherever it is defined.

    Empty when nothing in the trace was moving fast enough to invert, or when
    the pipeline reported nothing. Both are honest answers.
    """
    samples = trace.samples
    if len(samples) < 3:
        return ()

    times, truths = _truth_curve(samples)
    lags = []
    for i, sample in enumerate(samples):
        if not sample.has_reading:
            continue
        if _local_speed_cm_s(times, truths, i) < MIN_MEASURABLE_SPEED_CM_S:
            continue
        # The midpoint of the interval the truncated reading denotes.
        believed_cm = sample.reported_cm + QUANTISATION_CM / 2.0
        instant = _instant_truth_equalled(
            times, truths, i, believed_cm, _continuous_run(times, truths, i)
        )
        if instant is None:
            continue
        # Negative lags are kept. A reading cannot really precede the world,
        # but quantisation noise scatters individual estimates either side of
        # the truth, and discarding the low half leaves the mean of what
        # survives biased upward — by 30 ms on a trace built with no lag at
        # all, which is the same order as the lag being measured.
        lags.append(sample.t - instant)
    return tuple(lags)


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def lag_by_correlation(trace: Trace) -> Optional[float]:
    """The shift that best aligns the reported series with the truth series.

    Searches whole-sample shifts and returns the one minimising squared
    difference, then refines to sub-sample precision by fitting a parabola
    through the best shift and its neighbours — the sampling grid would
    otherwise quantise every answer to a multiple of the sample interval, which
    is coarser than the lag being measured.
    """
    readable = [s for s in trace.samples if s.has_reading]
    if len(readable) < 8:
        return None

    times, truths = _truth_curve(trace.samples)
    reported = {s.t: s.reported_cm + QUANTISATION_CM / 2.0 for s in readable}
    interval = 1.0 / trace.sample_hz
    max_shift = min(len(trace.samples) // 2, int(2.0 / interval))

    def cost(shift: int) -> float:
        total, count = 0.0, 0
        for i, t in enumerate(times):
            if t not in reported or i - shift < 0:
                continue
            total += (reported[t] - truths[i - shift]) ** 2
            count += 1
        return total / count if count else float("inf")

    costs = [cost(shift) for shift in range(max_shift + 1)]
    best = min(range(len(costs)), key=lambda s: costs[s])

    # Parabolic refinement between the neighbours of the best whole shift.
    if 0 < best < len(costs) - 1:
        left, middle, right = costs[best - 1], costs[best], costs[best + 1]
        denominator = left - 2 * middle + right
        if denominator != 0:
            offset = 0.5 * (left - right) / denominator
            # Not clamped at zero: the same argument as in
            # _instant_truth_equalled — truncating the low side of the
            # noise biases the result upward.
            return (best + offset) * interval
    return best * interval


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def estimate_lag(trace: Trace) -> LagReport:
    """Everything ticket 06 needs from one trace."""
    lags = lag_samples(trace)
    return LagReport(
        p50_s=statistics.median(lags) if lags else None,
        p95_s=_percentile(lags, 0.95) if lags else None,
        correlation_s=lag_by_correlation(trace),
        measured_samples=len(lags),
        total_samples=len(trace.samples),
        resolution_s=lag_resolution_s(trace),
        trajectory=trace.trajectory,
        environment=dict(trace.environment),
    )


def throughput(trace: Trace, *, producer_fps: float) -> Optional[ThroughputReport]:
    """What the buffer's emptiness actually rests on.

    ``None`` when the trace carries no frame timestamps — an older trace, or a
    pipeline that does not report which frame it read. Consumer cost is taken
    as the median frame age, which is the detection cost only while the buffer
    is empty; once frames are queueing, age includes the wait and this
    overstates it. That is the right direction to be wrong in: it brings the
    estimated inversion point closer, never further away.
    """
    ages = [s.frame_age_s for s in trace.samples if s.frame_age_s is not None]
    if not ages:
        return None
    return ThroughputReport(
        producer_interval_s=1.0 / producer_fps,
        consumer_cost_s=statistics.median(ages),
        observed_backlog_max=max((s.backlog for s in trace.samples), default=0),
    )

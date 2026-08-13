"""Why the readings lag: buffer depth and frame age.

Ticket 06 measures the symptom — how far behind the distance readings run.
This is the mechanism. Two numbers, both already present in a
:class:`~harness.replay.Trace` and neither requiring any instrumentation the
system does not already carry:

**Buffer depth** made PLAN.md defect A1 visible in M4: the old frame buffer was
unbounded, so a slow consumer made it grow without limit. M5 replaced that
behaviour with a one-frame latest-value buffer. The diagnostic still reads old
traces faithfully and confirms new production traces remain bounded.

**Frame age** is defect A2 made visible: how long a frame sat between entering
this process and being looked at. That is precisely the process-local quantity
``get_distance(max_age_sec=...)`` was written to bound and does not, because it
filters on when a reading was *computed* instead. Reading it here uses
``CapturedFrame.arrived_at`` records. It deliberately excludes unmeasurable
camera-to-process transport lag.

## Nothing here bounds normal operation

No function returns a pass or a fail, and **nothing asserts an upper limit on
either number**. Two reasons, and the ticket is explicit about both.

The first is that a limit would be measuring the wrong thing. PLAN.md §5 rules
the backlog a **correctness** problem, not a performance one: the defect is
that nothing bounds the queue, not that the queue is a particular size today. A
numeric ceiling invites making the detector cheaper until it passes, which
changes the number without touching the defect.

The second is that such an assertion is flaky by construction. One existed
briefly in ``test_latency_bound.py`` — buffer depth must be zero — and failed
intermittently under the full suite, where other tests compete for the same
cores. That was not a flaky test. It was defect A1 occurring, and a CI that
goes red when the machine is busy teaches people to ignore it.

One test does assert *lower* bounds on these numbers — that a deliberately
crippled consumer really did fill the buffer. That is the opposite operation:
it demands the defect appear, so the diagnostic is known to fire rather than
merely known to compile. Load makes it pass more easily, not less.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional, Sequence

from harness.latency import estimate_lag, percentile, throughput
from harness.replay import Trace

#: How much deeper the buffer must end up, in frames, for it to count as
#: *growing* rather than noisy — measured as the second half's mean depth
#: against the first half's.
#:
#: An earlier version tested the least-squares slope against a rate. That was
#: worse in both directions: a genuine but slow accumulation (backlog 0 → 29
#: over four minutes, monotonic) fell under the rate and read as *not growing*,
#: while three late frames at the end of a two-second trace cleared it and read
#: as growing. Comparing halves is indifferent to how long the trace ran and to
#: where the spikes landed.
#:
#: The slope is still reported, because the rate is the interesting number once
#: growth is established. This only decides which sentence the summary prints.
GROWTH_FRAMES = 1.0


def _drift(values: Sequence[int]) -> float:
    """How much deeper the second half ran than the first."""
    if len(values) < 4:
        return 0.0
    middle = len(values) // 2
    first, second = values[:middle], values[middle:]
    return sum(second) / len(second) - sum(first) / len(first)


def _slope_per_s(times: List[float], values: List[float]) -> float:
    """Least-squares slope of ``values`` against ``times``."""
    if len(times) < 2:
        return 0.0
    mean_t = sum(times) / len(times)
    mean_v = sum(values) / len(values)
    covariance = sum((t - mean_t) * (v - mean_v) for t, v in zip(times, values))
    variance = sum((t - mean_t) ** 2 for t in times)
    return 0.0 if variance == 0 else covariance / variance


@dataclass(frozen=True)
class Diagnostics:
    """Buffer depth and frame age over one replay.

    **Every field is diagnostic.** None of them is bounded, asserted, or
    intended to be — see the module docstring for why. They exist to explain a
    latency figure, and a latency figure is the thing with a bound on it.

    Frame-age fields are ``None`` when the trace carried no frame timestamps,
    which means either an older trace or a pipeline that does not report which
    frame it read.
    """

    backlog_max: int
    backlog_p95: int
    backlog_trend_per_s: float
    frame_age_p50_s: Optional[float]
    frame_age_p95_s: Optional[float]
    frame_age_max_s: Optional[float]
    aged_samples: int
    total_samples: int

    #: Mean depth over the second half of the replay minus the first half's.
    backlog_drift: float

    @property
    def backlog_is_growing(self) -> bool:
        """Whether frames were still accumulating when the replay ended.

        The distinction that matters. A deep buffer that drains is a hiccup; a
        shallow one that keeps rising is defect A1 in progress and will be a
        deep one given a longer run.
        """
        return self.backlog_drift > GROWTH_FRAMES and self.backlog_trend_per_s > 0

    def summary(self) -> str:
        if self.frame_age_p95_s is None:
            age = "frame age unavailable"
        else:
            age = (
                f"frame age p50 {self.frame_age_p50_s * 1000:.1f}ms, "
                f"p95 {self.frame_age_p95_s * 1000:.1f}ms, "
                f"max {self.frame_age_max_s * 1000:.1f}ms"
            )
        trend = (
            f"growing {self.backlog_trend_per_s:+.1f} frames/s"
            if self.backlog_is_growing
            else "not growing"
        )
        return (
            f"buffer max {self.backlog_max}, p95 {self.backlog_p95}, {trend}; "
            f"{age} over {self.aged_samples}/{self.total_samples} samples "
            f"[diagnostic — no threshold, see harness/diagnostics.py]"
        )


def diagnose(trace: Trace) -> Diagnostics:
    """Read the mechanism behind a trace's latency."""
    samples = trace.samples
    backlogs = [sample.backlog for sample in samples]
    times = [sample.t for sample in samples]
    ages = [s.frame_age_s for s in samples if s.frame_age_s is not None]

    return Diagnostics(
        backlog_max=max(backlogs, default=0),
        backlog_p95=int(percentile(backlogs, 0.95)) if backlogs else 0,
        backlog_trend_per_s=_slope_per_s(times, [float(b) for b in backlogs]),
        backlog_drift=_drift(backlogs),
        frame_age_p50_s=statistics.median(ages) if ages else None,
        frame_age_p95_s=percentile(ages, 0.95) if ages else None,
        frame_age_max_s=max(ages) if ages else None,
        aged_samples=len(ages),
        total_samples=len(samples),
    )


def report_lines(trace: Trace, *, producer_fps: float = 30.0) -> List[str]:
    """Latency and the diagnostics that explain it, as one block.

    The ticket asks for these together, and the reason is that apart they
    mislead in opposite directions. A latency figure alone says how bad it is
    but not why; a buffer depth alone invites being read as a score. Side by
    side, the lag is the number with a bound on it and the other two are
    labelled as what they are.
    """
    rates = throughput(trace, producer_fps=producer_fps)
    return [
        f"latency   {estimate_lag(trace).summary()}",
        f"mechanism {diagnose(trace).summary()}",
        (
            "throughput unavailable — no frame arrived to an empty buffer"
            if rates is None
            else f"headroom  {rates.summary()}"
        ),
    ]

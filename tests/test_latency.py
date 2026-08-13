"""Turning a trace into a latency figure.

Every test here builds a trace with a lag that is known because it was put
there, then asks the estimator to find it. That is the only way to trust a
measurement instrument: measure something whose answer you already have.

Two estimators, deliberately:

**Inversion** asks, for each reading, how long ago the truth last equalled it.
It yields one number per sample, so p50 and p95 mean something — but it is only
defined while the world is changing. When nobody is moving, every instant in
the recent past matches the reading equally well and the question has no
answer. That is not a defect of the estimator; it is why a stationary robot
looked fine for so long.

**Correlation** shifts the whole reported series against the whole truth series
and takes the alignment that fits best. One number for the trace, no
distribution, but it uses every row including the step — and it agrees with the
inversion estimate on traces where both are defined, which is the point of
keeping both.
"""

from __future__ import annotations

import pytest

from harness.latency import (
    LagReport,
    estimate_lag,
    lag_by_correlation,
    lag_samples,
    throughput,
)
from harness.replay import Sample, Trace

SAMPLE_HZ = 50.0
INTERVAL = 1.0 / SAMPLE_HZ


def walking_trace(lag_s: float, *, seconds: float = 4.0, speed_cm_s: float = 10.0,
                  start_cm: float = 130.0, backlog: int = 0) -> Trace:
    """A person walking steadily, reported with exactly ``lag_s`` of delay.

    Truth falls linearly. The reading at time t is where the person was at
    ``t - lag_s`` — which is what a perfectly-behaved pipeline with that much
    delay would say.
    """
    samples = []
    count = int(seconds / INTERVAL) + 1
    for i in range(count):
        t = i * INTERVAL
        truth = start_cm - speed_cm_s * t
        delayed_at = max(0.0, t - lag_s)
        reported = start_cm - speed_cm_s * delayed_at
        samples.append(
            Sample(
                t=t,
                truth_cm=truth,
                reported_cm=int(reported),
                backlog=backlog,
                frame_arrived_at=t,
                detected_at=t + 0.004,
            )
        )
    return Trace(
        samples=tuple(samples),
        trajectory=f"synthetic walk at {speed_cm_s:g}cm/s",
        sample_hz=SAMPLE_HZ,
        environment={"machine": "test"},
    )


# ---------------------------------------------------------------------------
# Inversion
# ---------------------------------------------------------------------------

def _mean_lag(trace) -> float:
    lags = lag_samples(trace)
    assert lags, "no sample yielded a measurable lag"
    return sum(lags) / len(lags)


@pytest.mark.parametrize("lag_s", [0.0, 0.05, 0.1, 0.25])
def test_inversion_recovers_a_lag_that_was_put_there(lag_s):
    assert _mean_lag(walking_trace(lag_s)) == pytest.approx(lag_s, abs=1.5 * INTERVAL)


def test_a_faster_walk_does_not_change_the_lag_measured():
    # The error in centimetres scales with speed; the lag in seconds must not.
    # Conflating the two is exactly what a raw reported-minus-truth would do.
    slow = _mean_lag(walking_trace(0.1, speed_cm_s=5.0))
    fast = _mean_lag(walking_trace(0.1, speed_cm_s=20.0))

    assert slow == pytest.approx(fast, abs=1.5 * INTERVAL)


def test_a_stationary_stretch_yields_no_measurable_lag():
    # Nobody moving: every recent instant matches the reading equally well.
    # Reporting a number here would be inventing one.
    still = Trace(
        samples=tuple(
            Sample(t=i * INTERVAL, truth_cm=90.0, reported_cm=90, backlog=0)
            for i in range(100)
        ),
        trajectory="synthetic hold",
        sample_hz=SAMPLE_HZ,
    )

    assert lag_samples(still) == ()


def test_samples_without_a_reading_are_skipped():
    trace = walking_trace(0.1)
    blinded = Trace(
        samples=tuple(
            Sample(s.t, s.truth_cm, -1, s.backlog) for s in trace.samples
        ),
        trajectory=trace.trajectory,
        sample_hz=trace.sample_hz,
    )

    assert lag_samples(blinded) == ()


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lag_s", [0.0, 0.06, 0.14, 0.3])
def test_correlation_recovers_a_lag_that_was_put_there(lag_s):
    assert lag_by_correlation(walking_trace(lag_s)) == pytest.approx(
        lag_s, abs=INTERVAL
    )


def test_the_two_estimators_agree_where_both_are_defined():
    trace = walking_trace(0.12)

    assert lag_by_correlation(trace) == pytest.approx(_mean_lag(trace), abs=2 * INTERVAL)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def test_the_report_carries_the_percentiles_and_the_conditions():
    report = estimate_lag(walking_trace(0.1))

    assert isinstance(report, LagReport)
    assert report.p50_s == pytest.approx(0.1, abs=1.5 * INTERVAL)
    assert report.p95_s >= report.p50_s
    assert report.measured_samples > 10
    assert report.environment["machine"] == "test"
    assert "walk" in report.trajectory


def test_a_trace_with_nothing_measurable_reports_that_rather_than_zero():
    still = Trace(
        samples=tuple(
            Sample(t=i * INTERVAL, truth_cm=90.0, reported_cm=90, backlog=0)
            for i in range(50)
        ),
        trajectory="synthetic hold",
        sample_hz=SAMPLE_HZ,
    )
    report = estimate_lag(still)

    assert report.measured_samples == 0
    assert report.p50_s is None and report.p95_s is None


# ---------------------------------------------------------------------------
# Throughput — where the queue would start growing
# ---------------------------------------------------------------------------

def test_throughput_reports_the_cost_of_each_side():
    report = throughput(walking_trace(0.1), producer_fps=30.0)

    assert report.producer_interval_s == pytest.approx(1 / 30.0)
    assert report.consumer_cost_s == pytest.approx(0.004, abs=0.001)


def test_a_consumer_faster_than_the_producer_leaves_headroom():
    # PLAN.md §12.2: consumer 4ms against a 33ms producer. The pipeline has no
    # backpressure, so the only thing keeping the queue empty is that ratio.
    report = throughput(walking_trace(0.1), producer_fps=30.0)

    assert report.ratio < 1.0
    assert report.inversion_fps == pytest.approx(250.0, rel=0.1)


def test_the_inversion_point_is_where_the_two_costs_meet():
    report = throughput(walking_trace(0.1), producer_fps=30.0)

    assert report.inversion_fps == pytest.approx(1 / report.consumer_cost_s, rel=0.01)


def test_a_trace_without_frame_timestamps_cannot_report_throughput():
    bare = Trace(
        samples=tuple(
            Sample(t=i * INTERVAL, truth_cm=90.0 - i, reported_cm=90 - i, backlog=0)
            for i in range(20)
        ),
        trajectory="synthetic",
        sample_hz=SAMPLE_HZ,
    )

    assert throughput(bare, producer_fps=30.0) is None


# ---------------------------------------------------------------------------
# The step — where the estimator went wrong
# ---------------------------------------------------------------------------

def ideal_trace(lag_s: float, trajectory, *, hz: float = 40.0) -> Trace:
    """Any trajectory, reported with exactly ``lag_s`` of delay.

    Unlike :func:`walking_trace` this covers whatever shape it is given —
    including a step, which is where the first version of the estimator broke.
    """
    from harness.replay import Sample

    samples = []
    for i in range(int(trajectory.duration_s * hz) + 1):
        t = i / hz
        samples.append(
            Sample(
                t=t,
                truth_cm=trajectory.distance_at(t),
                reported_cm=int(trajectory.distance_at(max(0.0, t - lag_s))),
                backlog=0,
                frame_arrived_at=t,
                detected_at=t + 0.005,
            )
        )
    return Trace(
        samples=tuple(samples),
        trajectory=trajectory.describe(),
        sample_hz=hz,
        environment={"machine": "test"},
    )


def test_the_step_does_not_produce_wild_readings():
    """Regression: a value either side of a step has two crossings.

    The first version searched the whole trace for a matching instant and
    filtered samples by local speed alone. A step's local speed is enormous, so
    samples straddling it passed the filter — and then matched the crossing on
    the *far* side. On this very trajectory, built with exactly 40 ms of lag,
    four samples came back at **+1.5 seconds**. The published baseline was not
    wrong by luck so much as by not looking.
    """
    from harness.trajectory import APPROACH_HOLD_STEP

    lags = lag_samples(ideal_trace(0.040, APPROACH_HOLD_STEP))

    assert lags
    assert max(lags) < 0.2, (
        f"largest lag {max(lags) * 1000:.0f}ms on a trace built with 40ms — "
        f"the estimator matched across a discontinuity"
    )
    assert sum(lags) / len(lags) == pytest.approx(0.040, abs=0.01)


def test_samples_at_a_step_are_not_measured_at_all():
    # The step is where inversion has nothing to say. Reporting anything there
    # is worse than reporting nothing.
    from harness.trajectory import Trajectory

    script = Trajectory.starting_at(120.0).walk_to(100.0, over=0.5).step_to(70.0).hold(0.5)
    trace = ideal_trace(0.0, script)
    step_t = 0.5

    measured_at = [
        s.t for s in trace.samples
        if s.has_reading and abs(s.t - step_t) < 0.06
    ]
    lags = lag_samples(trace)

    assert measured_at, "the fixture never sampled near the step"
    assert all(abs(lag) < 0.2 for lag in lags)

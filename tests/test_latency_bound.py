"""The bound the rewritten pipeline has to meet.

Separate from ``test_latency.py`` because this one replays for real: it starts
a camera, runs MediaPipe over four seconds of composed frames, and measures.
The estimators' own tests use synthetic traces and finish in milliseconds; this
is the one that costs wall-clock time, and it is the one that would fail if the
pipeline regressed rather than the arithmetic.

It is **green today**, and that is intended. The milestone's original plan had
this assertion failing, to prove a defect existed before it was fixed; the
project moved to rewriting rather than patching (PLAN.md §12.3), so the job of
this file changed with it. It is a specification now: the number M5's pipeline
has to come in under.

Numbers and their derivation are in docs/measurements/m4-latency-baseline.md.
"""

from __future__ import annotations

import pytest
from conftest import SKIP_REASON

from harness.latency import MAX_LAG_OVER_FLOOR, estimate_lag, throughput
from harness.trajectory import APPROACH_HOLD_STEP

CAMERA_FPS = 30.0


@pytest.fixture(scope="module")
def baseline_trace(portrait):
    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.replay import default_replay

    return default_replay(portrait, trajectory=APPROACH_HOLD_STEP, sample_hz=40)


def test_the_replay_measured_something(baseline_trace):
    # Guard the guard: a trace where nothing was measurable would sail through
    # every assertion below by having no numbers to fail with.
    report = estimate_lag(baseline_trace)

    assert report.measured_samples >= 20, report.summary()
    assert report.p95_s is not None


def test_the_script_can_resolve_the_lag_it_is_being_asked_about(baseline_trace):
    # Readings are whole centimetres, so the script's walking pace sets a floor
    # on what any estimator can see. If the lag ever drops below it, this test
    # fails and the script — not the threshold — is what needs revisiting.
    report = estimate_lag(baseline_trace)

    assert report.resolution_s is not None
    assert report.resolution_s < report.p95_s, (
        f"lag {report.p95_s * 1000:.0f}ms is finer than the "
        f"{report.resolution_s * 1000:.0f}ms this script can resolve — the "
        f"number is quantisation noise, not a measurement"
    )


def test_lag_stays_within_the_bound(baseline_trace):
    """The specification M5's rewritten pipeline has to meet."""
    report = estimate_lag(baseline_trace)
    rates = throughput(baseline_trace, producer_fps=CAMERA_FPS)
    limit = MAX_LAG_OVER_FLOOR * rates.lag_floor_s

    assert report.p95_s <= limit, (
        f"lag p95 {report.p95_s * 1000:.0f}ms exceeds "
        f"{limit * 1000:.0f}ms = {MAX_LAG_OVER_FLOOR}x the "
        f"{rates.lag_floor_s * 1000:.0f}ms floor "
        f"({rates.summary()}). {report.summary()}"
    )


def test_the_two_estimators_do_not_contradict_each_other(baseline_trace):
    # They measure the same thing by different routes, and both are bimodal
    # on this script — readings land one sampling interval apart depending on
    # whether the recorder polled before or after the pipeline updated. Over
    # five runs inversion's p95 held at 42.5ms while correlation ranged
    # 25–49ms, so the tolerance cannot be tighter than that spread without
    # becoming flaky. It exists to catch a disagreement of kind rather than
    # degree: if one said 40ms and the other 400ms, neither should be published.
    report = estimate_lag(baseline_trace)

    assert report.correlation_s == pytest.approx(report.p95_s, abs=0.03), (
        f"inversion says {report.p95_s * 1000:.0f}ms, correlation says "
        f"{report.correlation_s * 1000:.0f}ms — they disagree about what "
        f"was measured"
    )


def test_the_consumer_outruns_the_producer_on_this_machine(baseline_trace):
    """The ratio PLAN.md §5's defect A1 turns on.

    The buffer is unbounded and has no backpressure at all; it stays empty only
    because detection is cheaper than frame delivery. This asserts that ratio,
    which is a cost and reasonably stable.

    It deliberately does **not** assert that the buffer stayed empty. An
    earlier version did, and it failed intermittently — under the full suite,
    with other tests running MediaPipe on the same cores, the consumer slows
    and frames genuinely queue up. That is not a regression to catch; it is
    defect A1 happening, and it is the clearest demonstration yet that whether
    the queue grows is a property of the host rather than of the code. Ticket
    07 reports buffer depth as a diagnostic with no threshold, for this exact
    reason.
    """
    rates = throughput(baseline_trace, producer_fps=CAMERA_FPS)

    assert rates.ratio < 1.0, rates.summary()

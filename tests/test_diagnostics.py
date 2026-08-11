"""Why the readings lag — the mechanism behind ticket 06's symptom.

Every trace here is built with the behaviour already known, so the diagnostics
can be checked against an answer rather than against themselves.

**Nothing in this module is a threshold, and no test here asserts a limit on
buffer depth or frame age.** That is the ticket's rule, and it is not
squeamishness: PLAN.md §5 rules the backlog a correctness problem rather than a
performance one, so a numeric limit would invite tuning the detector to pass
it. It would also be flaky by construction — an earlier attempt at exactly that
lived in `test_latency_bound.py` and failed intermittently whenever the rest of
the suite competed for the same cores, which is not a regression but defect A1
happening.
"""

from __future__ import annotations

import pytest

from harness.diagnostics import diagnose
from harness.replay import Sample, Trace

HZ = 40.0
INTERVAL = 1.0 / HZ


def trace_with(backlogs, *, frame_ages=None) -> Trace:
    """A trace carrying the given per-sample backlog and frame age."""
    samples = []
    for i, depth in enumerate(backlogs):
        t = i * INTERVAL
        age = None if frame_ages is None else frame_ages[i]
        samples.append(
            Sample(
                t=t,
                truth_cm=100.0 - i,
                reported_cm=100 - i,
                backlog=depth,
                frame_captured_at=None if age is None else t,
                detected_at=None if age is None else t + age,
            )
        )
    return Trace(
        samples=tuple(samples),
        trajectory="synthetic",
        sample_hz=HZ,
        environment={"machine": "test"},
    )


# ---------------------------------------------------------------------------
# Buffer depth
# ---------------------------------------------------------------------------

def test_an_empty_buffer_is_reported_as_empty():
    report = diagnose(trace_with([0] * 50))

    assert report.backlog_max == 0
    assert report.backlog_p95 == 0


def test_the_deepest_the_buffer_got_is_reported():
    report = diagnose(trace_with([0, 1, 7, 2, 0]))

    assert report.backlog_max == 7


def test_a_single_spike_does_not_look_like_growth():
    # One frame arriving late is not a queue building up. Distinguishing the
    # two is the whole point of reporting a trend as well as a maximum.
    report = diagnose(trace_with([0] * 20 + [9] + [0] * 20))

    assert report.backlog_max == 9
    assert report.backlog_trend_per_s == pytest.approx(0.0, abs=2.0)
    assert not report.backlog_is_growing


def test_a_buffer_that_fills_steadily_is_reported_as_growing():
    # The signature of PLAN.md defect A1: a consumer slower than the producer
    # never catches up, so depth rises without limit.
    report = diagnose(trace_with(list(range(80))))

    assert report.backlog_is_growing
    # One frame per sample at 40 Hz is 40 frames per second of growth.
    assert report.backlog_trend_per_s == pytest.approx(40.0, rel=0.05)


def test_a_buffer_that_drains_is_not_reported_as_growing():
    report = diagnose(trace_with(list(range(60, 0, -1))))

    assert not report.backlog_is_growing
    assert report.backlog_trend_per_s < 0


# ---------------------------------------------------------------------------
# Frame age
# ---------------------------------------------------------------------------

def test_frame_age_percentiles_come_from_the_frames_own_timestamps():
    # 90/10 rather than 95/5: at exactly 5% the 95th percentile sits on the
    # boundary and which side it lands on is a convention rather than a fact,
    # so the test would be asserting the convention.
    ages = [0.004] * 90 + [0.050] * 10
    report = diagnose(trace_with([0] * 100, frame_ages=ages))

    assert report.frame_age_p50_s == pytest.approx(0.004)
    assert report.frame_age_p95_s == pytest.approx(0.050)
    assert report.frame_age_max_s == pytest.approx(0.050)


def test_a_trace_without_frame_timestamps_reports_no_frame_age():
    report = diagnose(trace_with([0] * 20))

    assert report.frame_age_p95_s is None
    assert report.aged_samples == 0


def test_frame_age_counts_only_the_samples_that_carried_one():
    ages = [0.004] * 10
    trace = trace_with([0] * 10, frame_ages=ages)
    blinded = Trace(
        samples=trace.samples[:5]
        + tuple(
            Sample(s.t, s.truth_cm, s.reported_cm, s.backlog)
            for s in trace.samples[5:]
        ),
        trajectory=trace.trajectory,
        sample_hz=trace.sample_hz,
    )

    assert diagnose(blinded).aged_samples == 5


# ---------------------------------------------------------------------------
# How it presents itself
# ---------------------------------------------------------------------------

def test_the_summary_says_out_loud_that_it_is_not_a_threshold():
    # A reader who sees a number next to a lag figure that *is* bounded will
    # assume this one is too, and the next person to touch CI will add the
    # assertion. Saying so in the line itself is cheaper than hoping.
    summary = diagnose(trace_with([0] * 20, frame_ages=[0.004] * 20)).summary()

    assert "diagnostic" in summary.lower()
    assert "no threshold" in summary.lower()


def test_the_summary_survives_a_trace_with_nothing_to_say():
    assert diagnose(trace_with([0] * 3)).summary()


def test_an_empty_trace_does_not_crash_the_diagnostics():
    empty = Trace(samples=(), trajectory="none", sample_hz=HZ)
    report = diagnose(empty)

    assert report.backlog_max == 0
    assert report.frame_age_p95_s is None
    assert not report.backlog_is_growing


# ---------------------------------------------------------------------------
# The defect, on purpose
# ---------------------------------------------------------------------------

def test_a_slow_consumer_really_does_make_the_buffer_grow(portrait):
    """Defect A1, produced deliberately, through the real pipeline.

    Everything above tests the arithmetic against traces built by hand. This
    tests the thing the arithmetic is about: that when detection costs more
    than a frame period, the unbounded buffer fills and keeps filling.

    It matters because the reference pipeline never shows it. On this machine
    detection costs 5 ms against a 33 ms frame period, so the buffer stays
    empty and `backlog_is_growing` has nothing to report — a diagnostic that
    has never been seen to fire is not a diagnostic. PLAN.md §5 assumed 30–50 ms
    per frame, which is what the delay below imitates; at that cost the defect
    is not conditional at all.
    """
    pytest.importorskip("cv2", reason="needs the media stack")
    pytest.importorskip("mediapipe", reason="needs the media stack")

    import threading
    import time

    from harness.replay import Reading, replay
    from harness.synthetic_camera import FaceComposer, SyntheticCamera
    from harness.trajectory import Trajectory
    from misty_agent.drivers.av_stream import WorkerThread

    class SlowPipeline:
        """A consumer that costs more than a frame period, as PLAN.md assumed.

        Written out rather than subclassing ``DirectPipeline`` because the cost
        has to land in the *consuming* loop. An earlier attempt overrode
        ``latest_reading``, which the recorder calls — that slowed the
        measurement instead of the pipeline, and the buffer stayed empty.
        """

        def __init__(self, source, *, cost_s: float) -> None:
            self._source = source
            self._cost_s = cost_s
            self._latest = None
            self._worker = WorkerThread(self._consume, name="slow-pipeline")

        def latest_reading(self):
            return self._latest

        def start(self):
            self._worker.start()

        def stop(self):
            self._worker.stop()

        def _consume(self, stop: threading.Event) -> None:
            from misty_agent.perception.face import FaceDetector

            with FaceDetector() as detector:
                while not stop.is_set():
                    frame = self._source.read(timeout=0.5)
                    if frame is None:
                        continue
                    time.sleep(self._cost_s)
                    reading = detector.detect(frame.image)
                    if reading.has_human:
                        self._latest = Reading(
                            distance_cm=reading.distance_cm,
                            frame_captured_at=frame.captured_at,
                            detected_at=time.monotonic(),
                        )

    camera = SyntheticCamera(FaceComposer(portrait), start_distance_cm=100.0)
    pipeline = SlowPipeline(camera, cost_s=0.05)  # 50ms, PLAN.md §5's assumption
    camera.start()
    pipeline.start()
    try:
        trace = replay(
            Trajectory.starting_at(100.0).walk_to(80.0, over=2.0),
            camera,
            pipeline,
            sample_hz=10,
        )
    finally:
        pipeline.stop()
        camera.stop()

    report = diagnose(trace)

    assert report.backlog_max > 5, report.summary()
    assert report.backlog_is_growing, (
        f"the buffer did not accumulate under a deliberately slow consumer: "
        f"{report.summary()}"
    )
    # And the frames it did get through were correspondingly stale — defect A2
    # is what defect A1 turns into once the queue is deep.
    assert report.frame_age_max_s > 0.2, report.summary()


# ---------------------------------------------------------------------------
# Growth, at the awkward scales
# ---------------------------------------------------------------------------

def test_a_slow_but_relentless_accumulation_still_counts_as_growing():
    # An earlier version tested a rate and missed this: 29 frames over four
    # minutes is 0.05/s, under the rate it used, but the buffer never once
    # drained and never would.
    depths = [i * 29 // 2000 for i in range(2000)]

    assert diagnose(trace_with(depths)).backlog_is_growing


def test_a_late_flurry_at_the_end_of_a_short_trace_is_not_growth():
    # And missed this the other way: three frames arriving late in the last
    # tenth of a second cleared the rate and read as a growing queue.
    report = diagnose(trace_with([0] * 77 + [1, 2, 3]))

    assert not report.backlog_is_growing
    assert report.backlog_max == 3


def test_latency_and_the_diagnostics_are_reported_together():
    from harness.diagnostics import report_lines

    lines = report_lines(trace_with([0] * 40, frame_ages=[0.004] * 40))

    assert any("latency" in line for line in lines)
    assert any("no threshold" in line for line in lines)
    assert len(lines) == 3

"""Driving a script through a pipeline and writing down what happened.

Two halves, tested apart:

The **recorder** is bookkeeping — move the person, ask the pipeline, write a
row — and is tested against stand-ins so it runs in milliseconds and needs no
media stack. What it must get right is that every row is internally consistent:
the truth written down is the truth *at the instant the reading was taken*, not
at some other instant, because that offset is the quantity the whole harness
exists to measure and an error here would be invisible and fatal.

The **pipeline** is the thing under test, and the one test of it here uses the
real detector on real composed frames. It is deliberately the simplest possible
consumer — read a frame, detect, keep the answer — because the pipeline that
will replace it does not exist yet (PLAN.md §12.3). That makes it the floor:
whatever lag it shows is the lag of detection and buffering alone, before any
filtering or sample window is added on top.
"""

from __future__ import annotations

import json
import time

import pytest
from conftest import SKIP_REASON

from harness.replay import Reading, replay
from harness.trajectory import Trajectory


class FakeCamera:
    """Records where it was told the person is. Never renders anything."""

    def __init__(self, backlog: int = 0) -> None:
        self.placements: list[float] = []
        self._backlog = backlog

    def place(self, distance_cm: float) -> None:
        self.placements.append(distance_cm)

    @property
    def backlog(self) -> int:
        return self._backlog


class EchoPipeline:
    """Reports whatever the camera was last shown, with no lag at all.

    A pipeline this honest cannot exist — that is the point. It gives the
    recorder a known-zero baseline, so a non-zero lag in a real run is
    attributable to the pipeline rather than to the recorder's own bookkeeping.
    """

    def __init__(self, camera: FakeCamera) -> None:
        self._camera = camera

    def latest_reading(self):
        if not self._camera.placements:
            return None
        now = time.monotonic()
        return Reading(
            distance_cm=int(self._camera.placements[-1]),
            frame_captured_at=now,
            detected_at=now,
        )


class SilentPipeline:
    """Never reports anything, the way a pipeline looks before its first frame."""

    def latest_reading(self):
        return None


SHORT = Trajectory.starting_at(100.0).walk_to(80.0, over=0.3)


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------

def test_a_replay_produces_samples_spanning_the_script():
    camera = FakeCamera()
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    assert len(trace.samples) > 1
    assert trace.samples[0].t == pytest.approx(0.0, abs=0.05)
    assert trace.samples[-1].t >= SHORT.duration_s


def test_the_person_is_moved_as_the_script_says():
    camera = FakeCamera()
    replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    assert camera.placements[0] == pytest.approx(100.0, abs=2.0)
    assert camera.placements[-1] == pytest.approx(80.0, abs=2.0)
    assert camera.placements == sorted(camera.placements, reverse=True)


def test_each_row_records_the_truth_at_the_instant_it_was_sampled():
    # The row's truth must be the script evaluated at the row's own timestamp.
    # If those two ever drift apart the recorder invents lag that the pipeline
    # never had, and nothing downstream could tell.
    camera = FakeCamera()
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    for sample in trace.samples:
        assert sample.truth_cm == pytest.approx(SHORT.distance_at(sample.t))


def test_a_pipeline_with_nothing_to_say_is_recorded_as_such():
    from misty_agent.perception.face import UNKNOWN_DISTANCE_CM

    camera = FakeCamera()
    trace = replay(SHORT, camera, SilentPipeline(), sample_hz=40)

    assert all(s.reported_cm == UNKNOWN_DISTANCE_CM for s in trace.samples)
    assert not any(sample.has_reading for sample in trace.samples)
    assert all(sample.frame_age_s is None for sample in trace.samples)


def test_buffer_depth_is_recorded_alongside():
    camera = FakeCamera(backlog=7)
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    assert all(sample.backlog == 7 for sample in trace.samples)


def test_samples_advance_in_time():
    camera = FakeCamera()
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    times = [sample.t for sample in trace.samples]
    assert times == sorted(times)


def test_the_trace_records_what_was_replayed_and_where():
    # PLAN.md §12.2 measured the same pipeline running an order of magnitude
    # faster on one machine than the plan assumed on another. A latency number
    # without its machine is not a result.
    camera = FakeCamera()
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    assert "100" in trace.trajectory
    assert trace.environment["machine"]
    assert trace.environment["python"]
    assert trace.sample_hz == 40


def test_a_trace_round_trips_through_jsonl():
    camera = FakeCamera()
    trace = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    lines = trace.to_jsonl().splitlines()
    header = json.loads(lines[0])
    rows = [json.loads(line) for line in lines[1:]]

    assert header["trajectory"] == trace.trajectory
    assert len(rows) == len(trace.samples)
    assert rows[0]["truth_cm"] == pytest.approx(trace.samples[0].truth_cm)


def test_replaying_the_same_script_twice_gives_the_same_truth_curve():
    # Not the same *rows*: the sampling instants differ run to run, because the
    # spec forbids a virtual clock (a real detector's real cost is the thing
    # being measured). What must not vary is the script itself — the same
    # instant always describes the same world.
    camera = FakeCamera()
    first = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)
    second = replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)

    for sample in list(first.samples) + list(second.samples):
        assert sample.truth_cm == pytest.approx(SHORT.distance_at(sample.t))


def test_the_replay_takes_about_as_long_as_the_script_says():
    camera = FakeCamera()

    started = time.monotonic()
    replay(SHORT, camera, EchoPipeline(camera), sample_hz=40)
    elapsed = time.monotonic() - started

    assert SHORT.duration_s <= elapsed < SHORT.duration_s + 0.5


def test_a_sample_rate_must_be_positive():
    camera = FakeCamera()
    with pytest.raises(ValueError):
        replay(SHORT, camera, EchoPipeline(camera), sample_hz=0)


# ---------------------------------------------------------------------------
# The pipeline under test — the real one, on real frames
# ---------------------------------------------------------------------------

def test_the_direct_pipeline_reports_the_distance_it_was_shown(portrait):
    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.replay import DirectPipeline
    from harness.synthetic_camera import FaceComposer, SyntheticCamera

    camera = SyntheticCamera(FaceComposer(portrait), start_distance_cm=90.0)
    pipeline = DirectPipeline(camera)
    camera.start()
    pipeline.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and pipeline.latest_reading() is None:
            time.sleep(0.02)
        reading = pipeline.latest_reading()
    finally:
        pipeline.stop()
        camera.stop()

    assert reading is not None
    assert reading.distance_cm == pytest.approx(90.0, rel=0.02)
    # The frame it came from is carried through, so 07 can age it without
    # adding instrumentation of its own.
    assert 0.0 <= reading.frame_age_s < 1.0


def test_a_full_replay_through_the_real_detector_records_real_readings(portrait):
    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.replay import DirectPipeline
    from harness.synthetic_camera import FaceComposer, SyntheticCamera

    script = Trajectory.starting_at(110.0).walk_to(80.0, over=1.5)
    camera = SyntheticCamera(FaceComposer(portrait), start_distance_cm=110.0)
    pipeline = DirectPipeline(camera)
    camera.start()
    pipeline.start()
    try:
        trace = replay(script, camera, pipeline, sample_hz=20)
    finally:
        pipeline.stop()
        camera.stop()

    readings = [s for s in trace.samples if s.has_reading]
    assert len(readings) > 5, "the detector never reported anything"
    # Not a latency assertion — that is 06's job. Just: the readings track the
    # script rather than being noise.
    assert readings[0].reported_cm > readings[-1].reported_cm


def test_all_three_scripted_cases_survive_a_real_replay(portrait):
    """Walk, hold and step, through MediaPipe, in one run.

    The ticket names three cases and says why each is there. Until this test
    existed only the walk had ever been replayed through the real detector, so
    "the script covers three cases" was a claim about the script rather than
    about anything that had run.

    Shortened from the default script — same shape, a third of the wall clock —
    because this runs on every commit.
    """
    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.replay import default_replay

    script = (
        Trajectory.starting_at(120.0)
        .walk_to(90.0, over=1.5)
        .hold(0.6)
        .step_to(69.0)
        .hold(0.6)
    )
    trace = default_replay(portrait, trajectory=script, sample_hz=40)

    walk = [s for s in trace.samples if s.t < 1.5 and s.has_reading]
    hold = [s for s in trace.samples if 1.6 < s.t < 2.1 and s.has_reading]
    after_step = [s for s in trace.samples if s.t > 2.3 and s.has_reading]

    assert walk and hold and after_step, "a scripted phase produced no readings"
    assert walk[0].reported_cm > walk[-1].reported_cm, "the walk was not tracked"
    assert max(s.reported_cm for s in hold) - min(s.reported_cm for s in hold) <= 3, (
        "readings wandered while nobody was moving"
    )
    assert after_step[-1].reported_cm == pytest.approx(69.0, rel=0.05), (
        "the pipeline never caught up with the step"
    )
    # Every reading carries the frame it came from, which is what 07 ages.
    assert all(s.frame_age_s is not None and s.frame_age_s >= 0 for s in after_step)

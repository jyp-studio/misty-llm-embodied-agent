"""The fake camera, and the proof that it is not lying.

The replay harness rests entirely on this module. If the composer renders a
face at the wrong size, every latency number measured downstream is measured
against a ground truth that was never true, and nothing later would reveal it.

So the central test here is a self-validation: composite a face at a commanded
distance, run the **real** detector over the result, and require the two to
agree. It is not circular. The composer inverts the calibration formula to get
a pixel width; the detector recovers a pixel width from rendered pixels and
applies the formula forward. Between them sit resampling, JPEG-decoded source
detail, and MediaPipe's landmark regression — all of which can and do shift the
answer. Below 50 px of face they shift it to "no face at all".

Each self-validation reading uses a **fresh** detector. MediaPipe tracks across
frames, so a detector that has seen other distances carries them into the next
reading; that temporal behaviour belongs to the detector's own tests, not to a
test of whether the composer draws the right size.
"""

from __future__ import annotations

import pytest
from conftest import SKIP_REASON

# mediapipe as well as cv2: FaceComposer locates the face during construction,
# so every test in this file reaches it. Guarding only cv2 turned the whole
# file into 18 errors in a bare environment instead of 18 skips.
pytest.importorskip("cv2", reason=SKIP_REASON)
pytest.importorskip("mediapipe", reason=SKIP_REASON)
pytest.importorskip("numpy", reason=SKIP_REASON)

from harness.synthetic_camera import FaceComposer, SyntheticCamera  # noqa: E402

#: Distances the fixture renders accurately at 640x480 (PLAN.md §12.5). The
#: control law commands a forward step above 72 cm, and the fixture holds to
#: within 1.5% out to 130 cm — the whole range the controller works over.
ACCURATE_RANGE_CM = [72, 85, 100, 115, 130]


@pytest.fixture(scope="module")
def composer(portrait):
    return FaceComposer(portrait)


# ---------------------------------------------------------------------------
# The composer: does it draw a face the size it was asked for?
# ---------------------------------------------------------------------------

def test_the_commanded_distance_sets_the_face_width_by_the_calibration_formula(
    portrait,
):
    # Worked examples, not the formula restated: at focal 650 and a 15 cm face,
    # a metre away subtends 650 * 15 / 100 = 97.5 px and half a metre 195 px.
    # Recomputing them from `settings` would assert the code against itself.
    composer = FaceComposer(portrait, focal_length=650.0, real_face_width_cm=15.0)

    assert composer.face_width_px(100.0) == pytest.approx(97.5)
    assert composer.face_width_px(50.0) == pytest.approx(195.0)


def test_a_nearer_person_is_drawn_larger(composer):
    assert composer.face_width_px(60.0) > composer.face_width_px(120.0)


def test_frames_come_out_at_the_configured_canvas_size(composer):
    frame = composer.frame_at(100.0)

    assert frame.shape == (composer.height, composer.width, 3)


def test_the_same_distance_renders_identically_every_time(composer):
    import numpy as np

    assert np.array_equal(composer.frame_at(90.0), composer.frame_at(90.0))


@pytest.mark.parametrize("distance_cm", ACCURATE_RANGE_CM)
def test_the_detector_recovers_the_distance_the_composer_was_given(
    composer, distance_cm
):
    """The self-validation. Everything downstream depends on this holding."""
    from misty_agent.perception.face import FaceDetector

    with FaceDetector() as detector:
        reading = detector.detect(composer.frame_at(distance_cm))

    assert reading.has_human, f"no face found in a frame composed at {distance_cm}cm"
    # 2%, not 5%: the measured worst case across this range is 1.5% (at 130cm),
    # and a tolerance three times looser than the claim would wave through a
    # composer regression the ticket calls load-bearing.
    assert reading.distance_cm == pytest.approx(distance_cm, rel=0.02), (
        f"composed at {distance_cm}cm but the detector read "
        f"{reading.distance_cm}cm — the harness's ground truth is not ground truth"
    )


def test_a_person_composed_beyond_the_fixtures_range_is_reported_honestly(composer):
    # PLAN.md §12.5: below ~50 px of face MediaPipe finds nothing. The composer
    # must not pretend otherwise — a trajectory that reaches out here should
    # show up as dropped readings, not as silently wrong ones.
    from misty_agent.perception.face import FaceDetector

    with FaceDetector() as detector:
        reading = detector.detect(composer.frame_at(250.0))

    assert not reading.has_human


# ---------------------------------------------------------------------------
# The camera: does it satisfy the seam the harness injects at?
# ---------------------------------------------------------------------------

def test_the_camera_satisfies_the_video_source_interface(composer):
    from misty_agent.drivers.av_stream import VideoSource

    assert isinstance(SyntheticCamera(composer), VideoSource)


def test_an_unstarted_camera_yields_nothing_rather_than_raising(composer):
    camera = SyntheticCamera(composer)

    assert camera.read(timeout=0.01) is None
    assert camera.backlog == 0


def test_a_started_camera_delivers_frames_of_the_person_it_was_given(composer):
    camera = SyntheticCamera(composer, start_distance_cm=100.0)
    camera.start()
    try:
        frame = camera.read(timeout=2.0)
    finally:
        camera.stop()

    assert frame is not None
    assert frame.image.shape == (composer.height, composer.width, 3)


def test_frames_carry_a_process_arrival_timestamp_on_the_drivers_clock(composer):
    import time

    camera = SyntheticCamera(composer)
    before = time.monotonic()   # before start(): the first frame may beat us to it
    camera.start()
    try:
        frame = camera.read(timeout=2.0)
        after = time.monotonic()
    finally:
        camera.stop()

    assert before <= frame.arrived_at <= after


def test_moving_the_person_changes_what_later_frames_show(composer):
    from misty_agent.perception.face import FaceDetector

    camera = SyntheticCamera(composer, start_distance_cm=120.0)
    camera.start()
    try:
        far = camera.read(timeout=2.0)
        camera.place(75.0)
        camera.flush()
        near = camera.read(timeout=2.0)
    finally:
        camera.stop()

    with FaceDetector() as detector:
        far_cm = detector.detect(far.image).distance_cm
    with FaceDetector() as detector:
        near_cm = detector.detect(near.image).distance_cm

    assert far_cm > near_cm


def _wait_until(predicate, *, what, state=None, timeout_s=10.0):
    """Block until `predicate()` holds, or fail saying what never happened.

    Tests here drive a real producer thread, which is the point: the contract
    under test is what happens when frames arrive faster than anyone reads
    them. What is *not* under test is whether that thread gets scheduled
    inside some fixed number of milliseconds.

    Sleeping for a duration and assuming a frame count is a bet on the
    scheduler. It pays off when the file runs alone — twenty consecutive runs,
    and ten more under eight busy loops — and was once seen not to during a
    full-suite run, on the assertion about which scene the buffered frame
    showed.

    **That single failure was never reproduced**, so what starved the producer
    is conjecture, not a finding: the full suite shares the process with
    MediaPipe's Metal and TensorFlow threads, which is a plausible cause and
    not an established one. What is not conjecture is that the old assertion
    could fail without the code being wrong, and that a flaky assertion in a
    suite whose every ticket is signed off as "green, zero skips" quietly
    devalues all of them.

    The timeout is deliberately far longer than the wait should ever need. It
    exists to fail with an explanation rather than to hang, not to encode an
    expectation about speed.
    """
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    # `state` is read only here, so a timeout says what was actually observed
    # rather than only what was hoped for.
    observed = f" (observed {state()})" if state is not None else ""
    raise AssertionError(
        f"waited {timeout_s}s for {what}, which never happened{observed}"
    )


def test_an_unread_camera_keeps_only_the_latest_scene(composer):
    # A controller wants the world now, not every world it failed to process.
    # The public contract is a bounded latest value plus an observable drop
    # count, so the drop count is also what the test waits on: it rises only
    # when an unread frame is replaced, which is direct evidence that another
    # frame was produced. No wall-clock duration stands in for that.
    from misty_agent.perception.face import FaceDetector

    camera = SyntheticCamera(composer, fps=60, start_distance_cm=120.0)
    camera.start()
    try:
        _wait_until(
            lambda: camera.dropped_frames >= 2,
            what="the producer to outrun the absent consumer",
            state=lambda: f"dropped={camera.dropped_frames}",
        )

        camera.place(70.0)
        # Snapshotted *after* `place`, and that ordering is load-bearing: read
        # before, and a replacement that happened while the subject was still
        # at 120 cm would count towards the two below.
        replaced_before = camera.dropped_frames
        # Two, not one: the frame being composed when `place` landed may still
        # show the old scene, so one replacement is not yet proof. After two,
        # whatever is buffered was composed after the subject moved.
        _wait_until(
            lambda: camera.dropped_frames >= replaced_before + 2,
            what="two frames of the new scene to replace their predecessors",
            state=lambda: f"dropped={camera.dropped_frames}, "
            f"wanted {replaced_before + 2}",
        )

        depth = camera.backlog
        dropped = camera.dropped_frames
        latest = camera.read(timeout=1.0)
    finally:
        camera.stop()

    assert latest is not None
    with FaceDetector() as detector:
        latest_distance_cm = detector.detect(latest.image).distance_cm

    assert depth == 1
    assert dropped > 1
    assert latest_distance_cm == pytest.approx(70.0, rel=0.05)


def test_flush_discards_what_was_waiting(composer):
    """Stop the producer before flushing, or the assertion cannot fail.

    `depth <= 1` is an invariant of the one-slot buffer, so the previous
    version passed with `flush` replaced by `pass` — and with an unbounded
    queue, and with a camera that never produced a frame at all. Waiting for a
    frame fixed the last of those and none of the others.

    With the producer stopped, nothing can land during or after the flush, so
    `depth == 0` is a claim about `flush` and only about `flush`.
    """
    camera = SyntheticCamera(composer, fps=60)
    camera.start()
    _wait_until(
        lambda: camera.backlog >= 1,
        what="a frame to be waiting unread",
        state=lambda: f"backlog={camera.backlog}",
    )
    camera.stop()

    assert camera.backlog == 1, "stopping should not have consumed the frame"
    camera.flush()

    assert camera.backlog == 0


def test_stopping_a_camera_that_never_started_is_safe(composer):
    SyntheticCamera(composer).stop()

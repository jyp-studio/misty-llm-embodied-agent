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


def test_frames_carry_a_capture_timestamp_on_the_drivers_clock(composer):
    import time

    camera = SyntheticCamera(composer)
    before = time.monotonic()   # before start(): the first frame may beat us to it
    camera.start()
    try:
        frame = camera.read(timeout=2.0)
        after = time.monotonic()
    finally:
        camera.stop()

    assert before <= frame.captured_at <= after


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


def test_an_unread_camera_accumulates_a_backlog(composer):
    # Deliberately unbounded, exactly like the RTSP source: the backlog is a
    # thing the harness measures, not a thing it prevents.
    import time

    camera = SyntheticCamera(composer, fps=60)
    camera.start()
    try:
        time.sleep(0.4)
        depth = camera.backlog
    finally:
        camera.stop()

    assert depth > 1


def test_flush_discards_what_was_waiting(composer):
    import time

    camera = SyntheticCamera(composer, fps=60)
    camera.start()
    try:
        time.sleep(0.3)
        camera.flush()
        depth = camera.backlog
    finally:
        camera.stop()

    assert depth <= 1  # the producer may land one frame during the flush


def test_stopping_a_camera_that_never_started_is_safe(composer):
    SyntheticCamera(composer).stop()

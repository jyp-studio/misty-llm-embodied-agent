"""What ``misty_agent.perception.face`` reports about a single image.

What these prove: given a photograph of a face scaled to a known apparent
width, the module reports the distance that width projects to, through the
calibration constants it was given; the estimate is a genuine inverse relation
rather than a constant that happens to be near the right value; a reading is
*not* a pure function of the image, because MediaPipe tracks a face across
frames; and the module imports on a machine with no camera stack installed.

That tracking result was not anticipated by the milestone and matters beyond
this file: it is a source of lag inside the detector, on top of the buffering
and timestamping lag of PLAN.md defect A, and the replay harness measures their
sum. See ``test_a_reading_depends_on_the_frames_that_came_before_it``.

What these do not prove: that the calibration constants are right. They cannot
be measured without hardware (PLAN.md §1), so ``focal_length`` is an assumption
and every distance here is "the distance implied by that assumption". The
replay harness sweeps it rather than trusting it.

The ground truth here is the apparent width of the face in pixels, which is set
by construction: the fixture portrait is scaled by a chosen factor and
composited onto a frame-sized canvas. The scale factor is derived from one
measurement of the unscaled portrait, made against MediaPipe directly rather
than through the module under test — the expected value must not come from the
thing being tested. ``tests/test_perception_stack.py`` pins the landmark
topology that measurement relies on.

The apparent widths below stay at 75 px and above, which is where that
construction is faithful. Measured on this fixture at 640x480, MediaPipe
recovers the width it was given to within 1.2% from 75 px up; at 60 px it
under-measures by 8%, and below 50 px it finds no face at all. That is the
fixture's envelope, not this module's — the arithmetic is the same at every
width — but it bounds how far away the replay harness can credibly place a
person: 75 px is 130 cm at the calibration below, and the approach controller
engages from around 160 cm. Tickets 04 and 05 need that number.

Gaze has no negative control here, and that is a real gap. The repository has
one face fixture and it is frontal. Simulating a turned head by warping the
image plane was tried: MediaPipe's response was erratic — the nose offset
crossed the threshold at one warp strength and detection dropped out entirely
at the neighbouring ones — so a test built on it would fail for reasons having
nothing to do with this code. Closing the gap needs a second fixture of a head
turned away, with its own provenance entry.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from dataclasses import dataclass

import numpy as np
import pytest
from conftest import SKIP_REASON

from misty_agent.config import settings
# Imported at module scope on purpose. The module under test must load with no
# camera stack present, so it is not eligible for importorskip — a missing one
# is a failure, not a skip.
from misty_agent.perception.face import (
    FACE_MESH_SETTINGS,
    UNKNOWN_DISTANCE_CM,
    FaceDetector,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The calibration this module's expectations are computed at, restated rather
#: than read from config so that re-calibrating the robot does not silently
#: move them. Every detector below is constructed with these explicitly.
FOCAL_LENGTH = 650.0
REAL_FACE_WIDTH_CM = 15.0

#: Frame size Misty streams at, and therefore the canvas the harness will
#: composite onto.
CANVAS_HEIGHT, CANVAS_WIDTH = 480, 640

#: Face-mesh landmarks at the cheeks, from the canonical topology. Spelled out
#: rather than imported from the module, deliberately: they are this file's
#: independent statement of what "how wide the face looks" means. Importing
#: them would make the ground truth follow the module wherever it went, and a
#: module that started measuring ear to ear would still pass.
LEFT_CHEEK, RIGHT_CHEEK = 234, 454


@dataclass(frozen=True)
class Geometry:
    """Where the face sits in an image, in that image's pixels.

    The centre is the midpoint of the two cheek landmarks, which is mid-face
    horizontally and roughly mid-face vertically. It only has to be a stable
    point on the face — it decides where the face lands on the canvas, not
    what the face measures.
    """

    width_px: float
    center_x: float
    center_y: float


@pytest.fixture(scope="module")
def geometry(portrait):
    """The face in the unscaled portrait, measured against MediaPipe directly.

    This is the only measurement in the file. Everything downstream is a scale
    factor applied to it, so the apparent width of a composited face is known
    by construction rather than estimated after the fact.

    The mesh is configured from ``FACE_MESH_SETTINGS`` — the same object the
    detector builds itself from. Measuring the fixture under a different
    configuration than the code under test uses would measure a different
    thing, and every expectation below rests on this number.
    """
    mp = pytest.importorskip("mediapipe", reason=SKIP_REASON)
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)

    with mp.solutions.face_mesh.FaceMesh(**FACE_MESH_SETTINGS) as face_mesh:
        result = face_mesh.process(cv2.cvtColor(portrait, cv2.COLOR_BGR2RGB))

    assert result.multi_face_landmarks, "no face in the fixture portrait"
    landmarks = result.multi_face_landmarks[0].landmark
    height, width = portrait.shape[:2]
    left = landmarks[LEFT_CHEEK].x * width
    right = landmarks[RIGHT_CHEEK].x * width
    return Geometry(
        width_px=abs(right - left),
        center_x=(left + right) / 2,
        center_y=(landmarks[LEFT_CHEEK].y + landmarks[RIGHT_CHEEK].y) / 2 * height,
    )


def composite(portrait, geometry: Geometry, face_px: float):
    """The portrait, scaled so the face spans ``face_px``, centred on a canvas.

    A generalised version of this is what the replay harness turns a ground
    truth distance into a frame with (ticket 04); here it exists to make the
    apparent width an input rather than an observation.
    """
    import cv2

    scale = face_px / geometry.width_px
    height, width = portrait.shape[:2]
    scaled = cv2.resize(
        portrait,
        (round(width * scale), round(height * scale)),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )

    canvas = np.full((CANVAS_HEIGHT, CANVAS_WIDTH, 3), 255, dtype=np.uint8)
    # Offset that lands the scaled face centre on the canvas centre. Faces
    # bigger than the canvas overflow it, and the intersection below crops
    # them the way a real camera would.
    offset_x = round(CANVAS_WIDTH / 2 - geometry.center_x * scale)
    offset_y = round(CANVAS_HEIGHT / 2 - geometry.center_y * scale)

    left, top = max(0, offset_x), max(0, offset_y)
    right = min(CANVAS_WIDTH, offset_x + scaled.shape[1])
    bottom = min(CANVAS_HEIGHT, offset_y + scaled.shape[0])
    canvas[top:bottom, left:right] = scaled[
        top - offset_y : bottom - offset_y, left - offset_x : right - offset_x
    ]
    return canvas


def calibrated() -> FaceDetector:
    """A detector at this file's calibration, with no history behind it."""
    return FaceDetector(
        focal_length=FOCAL_LENGTH, real_face_width_cm=REAL_FACE_WIDTH_CM
    )


@pytest.fixture
def detector():
    pytest.importorskip("mediapipe", reason=SKIP_REASON)
    pytest.importorskip("cv2", reason=SKIP_REASON)
    with calibrated() as instance:
        yield instance


# ---------------------------------------------------------------------------
# The distance estimate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "face_px, expected_cm",
    [
        # 650 px focal length * 15 cm face / apparent width in px, worked out
        # by hand at the calibration above.
        (75, 130),
        (100, 97),
        (140, 69),
        (200, 48),
        (300, 32),
    ],
)
def test_a_face_of_known_apparent_width_is_reported_at_the_distance_it_projects(
    detector, portrait, geometry, face_px, expected_cm
):
    reading = detector.detect(composite(portrait, geometry, face_px))

    assert reading.has_human
    # Two sources of slack, neither of them the arithmetic under test.
    # Re-detection: MediaPipe places the cheek landmarks slightly differently
    # on a rescaled picture, costing up to 1.2% across this range. Truncation:
    # a whole number of centimetres is worth 3% at the near end.
    assert reading.distance_cm == pytest.approx(expected_cm, rel=0.05)


def test_the_reported_distance_scales_inversely_with_apparent_face_width(
    detector, portrait, geometry
):
    """The estimate is a relation, not a plausible constant.

    Every expectation in the test above is a number this file worked out from
    the pinhole relation, which is also the relation the module implements. If
    both were wrong in the same way, they would agree. This one asks a
    question that needs no formula: halve how wide the person looks, and they
    must read as twice as far away.
    """
    # A detector each, because one instance shown both frames tracks the first
    # face into the second and either drags the reading or loses it — see the
    # test below. The claim here is about apparent width alone.
    with calibrated() as cold:
        near = cold.detect(composite(portrait, geometry, 200))
    with calibrated() as also_cold:
        far = also_cold.detect(composite(portrait, geometry, 100))

    assert far.distance_cm == pytest.approx(2 * near.distance_cm, rel=0.05)


def test_a_reading_depends_on_the_frames_that_came_before_it(
    detector, portrait, geometry
):
    """Readings are not a pure function of the image, and callers must know.

    MediaPipe tracks a face it has already found instead of re-detecting it,
    so an instance carries the previous frame into the next one. The effect is
    not a rounding difference: the same picture reads tens of centimetres
    apart depending on what the detector saw before it.

    This is pinned rather than merely documented because it is a second source
    of lag in the perception path, independent of PLAN.md defect A. M4's value
    rests on the harness being red *only* because of defect A, so the lag this
    contributes has to be visible and attributable. If a MediaPipe revision
    ever makes this test fail, the harness's headline number changes meaning
    and the comparison table has to be re-measured — that is worth a red test.
    """
    approaching = composite(portrait, geometry, 200)

    detector.detect(composite(portrait, geometry, 100))
    tracked = detector.detect(approaching)
    with calibrated() as cold:
        fresh = cold.detect(approaching)

    assert fresh.has_human and tracked.has_human
    assert abs(tracked.distance_cm - fresh.distance_cm) > 0.1 * fresh.distance_cm, (
        f"tracked reading {tracked.distance_cm}cm and cold reading "
        f"{fresh.distance_cm}cm agree to within 10%; if tracking no longer "
        f"drags the estimate, delete this test and re-measure the harness"
    )


@pytest.mark.parametrize("constant", ["focal_length", "real_face_width_cm"])
def test_the_calibration_constants_are_live_and_default_to_config(
    portrait, geometry, constant
):
    """Both calibration constants reach the estimate, and unset means config.

    Doubling either one must double the reported distance. That the *doubled*
    detector is built from ``settings`` while the baseline is left to its
    defaults is what makes this an assertion about the default: a hard-coded
    constant in the module would not track a change in config, and the ratio
    would not come out at two.
    """
    pytest.importorskip("mediapipe", reason=SKIP_REASON)
    frame = composite(portrait, geometry, 100)

    with FaceDetector() as configured:
        baseline = configured.detect(frame)
    with FaceDetector(**{constant: getattr(settings, constant) * 2}) as doubled:
        stretched = doubled.detect(frame)

    assert stretched.distance_cm == pytest.approx(2 * baseline.distance_cm, rel=0.02)


# ---------------------------------------------------------------------------
# Presence and gaze
# ---------------------------------------------------------------------------

def test_a_frame_with_nobody_in_it_reports_nobody(detector):
    blank = np.full((CANVAS_HEIGHT, CANVAS_WIDTH, 3), 255, dtype=np.uint8)

    reading = detector.detect(blank)

    assert reading.has_human is False
    assert reading.distance_cm == UNKNOWN_DISTANCE_CM
    assert reading.is_looking is False


def test_a_face_square_on_to_the_camera_reads_as_looking(
    detector, portrait, geometry
):
    # The gaze trigger is what starts an episode, so a frontal face failing
    # this would leave the robot unable to be approached at all.
    assert detector.detect(composite(portrait, geometry, 150)).is_looking


# ---------------------------------------------------------------------------
# The property that lets anything import this
# ---------------------------------------------------------------------------

def test_the_module_imports_with_no_camera_stack_installed():
    """MediaPipe and OpenCV are not needed to import this module.

    The drivers layer holds the same property, for the same reason: without it
    the whole test suite becomes uncollectable on a machine that has not
    installed the camera stack, and the failure looks like a broken repository
    rather than a missing dependency. Run in a subprocess because the point is
    what happens at first import, and this module is already imported here.
    """
    blocked = (
        "import sys\n"
        # A None entry makes `import x` raise ImportError, which is what an
        # uninstalled package looks like from inside the module.
        "sys.modules['cv2'] = None\n"
        "sys.modules['mediapipe'] = None\n"
        "import misty_agent.perception.face\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", blocked],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"importing the module without cv2/mediapipe failed:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Gaze — the negative control
# ---------------------------------------------------------------------------

def test_a_face_turned_away_is_not_looking(turned_portrait):
    """The half of the gaze test that was missing until now.

    Only one fixture existed before this, and it was frontal, so every gaze
    assertion in the suite could be satisfied by an ``is_looking`` that
    returned ``True`` and nothing else. This is the case that fails such an
    implementation.

    Detection and gaze are asserted **separately and in that order**. If the
    detector simply found no face, ``is_looking`` would also be ``False`` and a
    single combined assertion would call that a pass — reporting a failure to
    see anyone as a correct judgement about where they were looking.
    """
    with FaceDetector() as detector:
        reading = detector.detect(turned_portrait)

    assert reading.has_human, (
        "no face found in the turned-head fixture — this test would then be "
        "asserting a detection failure rather than a gaze judgement"
    )
    assert not reading.is_looking


def test_the_two_fixtures_disagree_about_gaze(portrait, turned_portrait):
    """The pair, as a pair.

    Neither photograph on its own says anything about whether the threshold
    discriminates between them. Together they do.

    Detection is asserted per image rather than as one combined condition:
    ``frontal.has_human and turned.has_human`` would let a failure to see
    either face hide inside a single line, which is the merge the ticket
    forbids.
    """
    with FaceDetector() as detector:
        frontal = detector.detect(portrait)
    with FaceDetector() as detector:
        turned = detector.detect(turned_portrait)

    assert frontal.has_human, "no face in the frontal fixture"
    assert turned.has_human, "no face in the turned fixture"
    assert frontal.is_looking is not turned.is_looking, (
        "both fixtures were judged the same way — the pair discriminates "
        "nothing and the gaze test has no negative control after all"
    )

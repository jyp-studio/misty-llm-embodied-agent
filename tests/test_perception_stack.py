"""The perception stack installs, and MediaPipe really detects a face.

Two seams, deliberately separate:

**The declared dependency constraint.** Pure text, no heavy imports, runs
anywhere. It guards the defect that motivated this milestone: ``mediapipe`` was
declared as ``>=0.10``, and upstream removed the legacy ``mp.solutions`` API in
0.10.31, so a fresh install resolved to a release where the perception layer
raises ``AttributeError`` on import. Nothing in the repository would have
noticed — no environment here had mediapipe installed at all.

**MediaPipe's face mesh, as this project uses it.** Loads a real photograph and
asserts a face comes back with a plausible cheek-to-cheek width. This is the
first time this repository has executed MediaPipe.

What these do NOT cover: this project's own detector wrapper. It still lives in
the entry-point script, which imports ``cv2`` at module scope, so importing it
anywhere pulls in the whole camera stack regardless of what is being tested.
The extraction that fixes that is the next ticket, and the wrapper's tests
belong there — written once, against the interface that survives.
"""

from __future__ import annotations

import pathlib

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

#: First mediapipe release without the legacy ``mp.solutions`` API. Verified by
#: inspecting the published wheels: 0.10.21 ships ``solutions/face_mesh``,
#: 0.10.31 and 1.0.0 ship only the Tasks API and bundle no face model at all.
SOLUTIONS_REMOVED_IN = Version("0.10.31")


# ---------------------------------------------------------------------------
# Seam: the declared dependency constraint
# ---------------------------------------------------------------------------

def _declared(package: str) -> Requirement:
    """The requirement line for ``package``, as declared for installation."""
    for line in (REPO_ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.name.lower() == package:
            return requirement
    raise AssertionError(f"{package} is not declared in requirements.txt")


def test_mediapipe_cannot_resolve_to_a_release_without_the_solutions_api():
    specifier = _declared("mediapipe").specifier

    assert not specifier.contains(SOLUTIONS_REMOVED_IN), (
        f"mediapipe is declared as '{specifier}', which permits "
        f"{SOLUTIONS_REMOVED_IN} — the first release that removed "
        f"mp.solutions. Installing it makes the perception layer raise "
        f"AttributeError on import. Do not loosen this pin without first "
        f"migrating to the Tasks API."
    )


def test_mediapipe_cannot_resolve_to_a_one_point_x_release():
    # 1.0.0 is what `mediapipe>=0.10` actually resolved to, and the reason the
    # repository could not be installed at all.
    assert not _declared("mediapipe").specifier.contains(Version("1.0.0"))


@pytest.mark.parametrize("package", ["mediapipe", "opencv-python", "packaging"])
def test_the_perception_stack_is_declared_for_installation(package):
    # opencv decodes the fixtures and composites the harness frames; packaging
    # is imported by this very file. Both were installed transitively before
    # anyone declared them.
    assert _declared(package)


# ---------------------------------------------------------------------------
# Seam: MediaPipe's face mesh, as this project uses it
#
# These need the real libraries. They skip rather than error where those are
# absent — but a skip here is not good news. `python3` on a developer machine
# is frequently not the interpreter that has these installed, and the rest of
# the suite passes under it regardless, so a wrong interpreter looks exactly
# like a healthy one. Run everything with the project venv (see AGENTS.md).
# ---------------------------------------------------------------------------

SKIP_REASON = (
    "mediapipe/opencv not importable — run under the project venv "
    "(.venv/bin/python), not a bare python3"
)

#: Landmark indices this project reads, from the canonical face mesh topology.
LEFT_CHEEK, RIGHT_CHEEK, NOSE_TIP = 234, 454, 1

#: The detector settings the perception layer runs with. Every test here uses
#: these, so the negative control cannot pass under a laxer configuration than
#: the positive claim it exists to backstop.
DETECTOR_SETTINGS = dict(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)


def _detect(image):
    """Run the face mesh over a BGR image, returning the raw MediaPipe result."""
    mp = pytest.importorskip("mediapipe", reason=SKIP_REASON)
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)

    with mp.solutions.face_mesh.FaceMesh(**DETECTOR_SETTINGS) as face_mesh:
        return face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


@pytest.fixture(scope="module")
def portrait():
    """The fixture photograph, as OpenCV loads it. See fixtures/PROVENANCE.md."""
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    path = FIXTURES / "frontal_face_portrait.jpg"
    image = cv2.imread(str(path))
    assert image is not None, f"could not decode {path}"
    return image


@pytest.fixture(scope="module")
def detection(portrait):
    """Raw detection result for the fixture. Deliberately unasserted.

    Whether a face was found is the claim of a test below, not a precondition
    of the fixture — an assertion here would surface as an error in every
    dependent test instead of one honest failure.
    """
    return _detect(portrait)


@pytest.fixture(scope="module")
def landmarks(detection):
    return detection.multi_face_landmarks[0].landmark


def test_the_legacy_solutions_api_is_present():
    mp = pytest.importorskip("mediapipe", reason=SKIP_REASON)

    assert hasattr(mp.solutions, "face_mesh")


def test_a_face_is_detected_in_the_fixture(detection):
    assert detection.multi_face_landmarks, (
        "MediaPipe found no face in the fixture portrait. The whole replay "
        "harness rests on detection actually happening on real pixels."
    )


def test_refined_landmarks_reach_the_indices_this_project_reads(landmarks):
    # refine_landmarks=True adds the iris points, taking the mesh to 478.
    assert len(landmarks) == 478


def test_the_cheek_landmarks_come_back_the_way_round_the_estimate_assumes(
    landmarks,
):
    # The distance estimate takes abs(right - left), but a sign flip would mean
    # the topology is not what this project thinks it is.
    assert landmarks[LEFT_CHEEK].x < landmarks[RIGHT_CHEEK].x


def test_the_face_spans_a_plausible_fraction_of_a_head_and_shoulders_portrait(
    portrait, landmarks
):
    # The prediction comes from the composition, not the detector: in a
    # head-and-shoulders portrait the head covers roughly a fifth to a third of
    # the frame width. The accepted band is wider than that prediction on both
    # sides, because these landmarks trace the face oval — inside the visual
    # outline of the head — and because a MediaPipe revision may shift them.
    # It is not wide enough to accept a degenerate reading.
    height, width = portrait.shape[:2]
    pixel_width = abs(landmarks[RIGHT_CHEEK].x - landmarks[LEFT_CHEEK].x) * width

    assert 0.12 * width < pixel_width < 0.45 * width, (
        f"cheek-to-cheek width {pixel_width:.0f}px on a {width}x{height} "
        f"portrait is {pixel_width / width:.1%} of the frame, outside the "
        f"12–45% a head-and-shoulders portrait should give"
    )


def _flat_fill(np, cv2):
    return np.full((480, 640, 3), 200, dtype=np.uint8)


def _drawn_face(np, cv2):
    image = _flat_fill(np, cv2)
    cv2.rectangle(image, (250, 180), (390, 320), (150, 120, 100), -1)
    cv2.circle(image, (290, 240), 12, (40, 40, 40), -1)
    cv2.circle(image, (350, 240), 12, (40, 40, 40), -1)
    return image


@pytest.mark.parametrize("build", [_flat_fill, _drawn_face], ids=["flat", "drawn"])
def test_synthetic_shapes_are_not_detected_as_faces(build):
    """The reason the replay harness must composite a photograph.

    PLAN.md §6 rules out synthesising frames from coloured shapes, on the
    grounds that MediaPipe does not detect them — which would make the
    detector's per-frame cost, the thing that causes the backlog being
    measured, disappear from the measurement. That premise had never been
    checked. It holds under the same detector settings as the positive case:
    neither a flat fill nor a schematic face returns anything.

    This also keeps the detection test above honest. An assertion that a face
    was found means nothing unless something can fail it.
    """
    np = pytest.importorskip("numpy", reason=SKIP_REASON)
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)

    assert not _detect(build(np, cv2)).multi_face_landmarks

"""One image in, one answer about the person in it.

Is anyone there, how far away are they, and are they looking at the robot.
That is the whole interface. This module does not know about buffers, threads,
or time — a reading carries no timestamp and the caller cannot pass one in.
That is deliberate: the age of a distance sample is the subject of PLAN.md
defect A2, and mixing it in here would spread that defect across two modules
instead of leaving it where it can be measured and fixed
(``misty_agent.perception.distance``).

**Distance comes from apparent face width**, through the pinhole relation: a
face of known real width, seen through a lens of known focal length, projects
to a pixel width that shrinks with distance. Both constants are configuration.
``focal_length`` is marked UNCALIBRATED in ``misty_agent.config``: it describes
a camera nobody here can measure. ``real_face_width_cm`` is not a camera
property but a population average standing in for whoever is actually in front
of the robot, so it is wrong for any particular person by their own margin. So
a reading is not "the user is 97 cm away", it is "the user is 97 cm away *if*
the camera and the face are what we assumed". The replay harness sweeps that
assumption rather than trusting it.

**There is no Protocol here, and that is a decision.** Every other seam in this
package has one so the implementation can be swapped for a recording stand-in.
Not this one: MediaPipe's per-frame cost is the mechanism behind the frame
backlog of defect A1, so a fake detector on the measurement path would assume
away the very thing the harness exists to quantify (PLAN.md §6). Anything that
wants to test against this module runs it for real.

``cv2`` and ``mediapipe`` are imported inside the constructor rather than at
module scope, so this module — and the tests over it — import on a machine with
neither installed. The drivers layer holds the same property.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from misty_agent.config import settings

#: ``distance_cm`` when no distance was measured. The caller cannot tell "no
#: face" from "a face at an unusable width" by this value alone; it checks
#: ``has_human`` for that. Preserved from the code this was extracted from,
#: where every caller already tests ``distance_cm > 0``.
UNKNOWN_DISTANCE_CM = -1

#: Face-mesh landmarks this estimate reads, from the canonical topology: the
#: two cheeks that bound the face oval, and the nose tip.
#: ``tests/test_perception_stack.py`` pins what is assumed about their layout —
#: that the cheeks come back left-then-right, and that the nose falls between
#: them on a face looking at the camera.
LEFT_CHEEK, RIGHT_CHEEK, NOSE_TIP = 234, 454, 1

#: How far the nose may sit from the midpoint of the cheeks, as a fraction of
#: the face width, and still count as looking at the camera. A head turned far
#: enough to push the nose past this is looking somewhere else.
GAZE_OFFSET_RATIO = 0.25

#: What the face mesh is asked for. One face, because the robot converses with
#: one person; refined landmarks, because that is what was measured against.
#: Do not tune these to make the harness faster — PLAN.md §5 rules the frame
#: backlog a correctness problem, and cheapening detection would hide it.
#:
#: Public, and read by the tests rather than copied into them. A test that
#: measures the fixture under a different configuration than the robot runs
#: under is measuring something else, and would keep passing while the two
#: drifted apart — the failure PLAN.md §10 records against the control law.
FACE_MESH_SETTINGS = MappingProxyType(
    dict(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
)


@dataclass(frozen=True)
class FaceReading:
    """What one image says about the person in front of the robot.

    ``distance_cm`` is a whole number of centimetres, truncated rather than
    rounded, and is ``UNKNOWN_DISTANCE_CM`` when no estimate was made. It is
    never more precise than the calibration it came from, so the fractional
    part it drops was not information.
    """

    has_human: bool
    distance_cm: int
    is_looking: bool


#: The reading for an image with nobody in it.
NO_FACE = FaceReading(
    has_human=False, distance_cm=UNKNOWN_DISTANCE_CM, is_looking=False
)


class FaceDetector:
    """MediaPipe's face mesh, read as distance and gaze.

    One instance holds one face mesh, which is **stateful across frames**:
    MediaPipe tracks a face it has already found rather than re-detecting it,
    which is why ``min_tracking_confidence`` exists. Frames are therefore not
    independent, and an instance should see a video sequence in order — not
    unrelated images interleaved from several sources.

    That state has two consequences nobody downstream can afford to ignore,
    both measured on the fixture portrait at 640x480 (see
    ``tests/test_perception_face.py``):

    * **A reading lags the frame it was taken from.** Tracking pulls the
      landmarks toward where they were, so a face that jumps from 100 px wide
      to 200 px reads as 68 cm when a detector seeing that frame cold reads
      48 cm. This is a lag *inside the detector*, on top of the buffering and
      timestamp lag of PLAN.md defect A. The replay harness measures the sum
      of the two and must not attribute all of it to defect A.
    * **A large enough jump loses the face outright.** 200 px to 100 px, and
      300 px to 75 px, return ``NO_FACE`` — a fresh detector finds both. The
      harness's ground-truth trajectory includes a step change, so it should
      expect dropped readings there rather than treat them as a bug.

      Unlike the first, this one is an observation and not a pinned test: the
      exact jump that loses a face is a property of a MediaPipe release, and an
      assertion on it would break on an upgrade that made tracking *better*.
      Measured 2026-08-11 against mediapipe 0.10.21 on the fixture portrait.
      The harness's own self-validation (ticket 04) is where a synthesised
      frame has to prove it still shows the face it claims to.

    The mesh is built during construction, not on the first frame. Loading the
    model takes far longer than processing a frame, and hiding that cost inside
    the first ``detect`` would put it inside what the replay harness measures.

    Closing releases MediaPipe's native resources. Instances are context
    managers; a long-lived one may simply never be closed, as the robot's is.
    """

    def __init__(
        self,
        *,
        focal_length: float = settings.focal_length,
        real_face_width_cm: float = settings.real_face_width_cm,
    ) -> None:
        import mediapipe as mp

        self._focal_length = focal_length
        self._real_face_width_cm = real_face_width_cm
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(**FACE_MESH_SETTINGS)

    def detect(self, image: np.ndarray) -> FaceReading:
        """Read one BGR frame. Returns ``NO_FACE`` if nobody is in it."""
        import cv2

        results = self._face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if not results.multi_face_landmarks:
            return NO_FACE

        width = image.shape[1]
        landmarks = results.multi_face_landmarks[0].landmark
        left_x = landmarks[LEFT_CHEEK].x * width
        right_x = landmarks[RIGHT_CHEEK].x * width
        pixel_width = abs(right_x - left_x)

        distance_cm = UNKNOWN_DISTANCE_CM
        if pixel_width > 0:
            distance_cm = int(
                (self._focal_length * self._real_face_width_cm) / pixel_width
            )

        # NOTE: this division is not covered by the guard above, so a face
        # whose cheeks project to the same x would raise here rather than
        # return NO_FACE. Carried over verbatim from the code this was
        # extracted from, because M4's whole claim is that the extraction
        # changed no behaviour. Two distinct landmarks cannot coincide exactly,
        # which is why it has never fired. Fix it where the guard is revisited,
        # not here.
        nose_x = landmarks[NOSE_TIP].x * width
        offset_ratio = abs(nose_x - (left_x + right_x) / 2) / pixel_width

        return FaceReading(
            has_human=True,
            distance_cm=distance_cm,
            is_looking=offset_ratio < GAZE_OFFSET_RATIO,
        )

    def close(self) -> None:
        self._face_mesh.close()

    def __enter__(self) -> "FaceDetector":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

"""A camera that shows a person standing exactly where you put them.

:class:`FaceComposer` turns "the user is 137 cm away" into an image. The truth
is not estimated afterwards — it is what the image was built from. Inverting
the calibration formula gives the pixel width a face at that distance subtends,
and the photograph is scaled to match.

:class:`SyntheticCamera` wraps that in the :class:`VideoSource` interface the
rest of the system already consumes, emitting frames on a background thread at
a fixed rate. It is the harness's only injection point: it substitutes for
``RtspVideoStream`` and nothing above the seam changes.

**The buffer has production latest-value semantics.** It matches the RTSP
source it stands in for: a slow consumer skips old frames, the process-local
backlog stays bounded, and replacements remain visible as a diagnostic.

Both MediaPipe and OpenCV are imported inside the functions that need them, so
this module imports on a machine without them and its tests skip rather than
error (see AGENTS.md).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from misty_agent.config import settings
from misty_agent.drivers.av_stream import CapturedFrame, FrameBuffer, WorkerThread
from misty_agent.perception.face import (
    FACE_MESH_SETTINGS,
    LEFT_CHEEK,
    NOSE_TIP,
    RIGHT_CHEEK,
)

log = logging.getLogger(__name__)

#: Canvas the frames are composed onto. Misty streams 640x480 (see
#: ``settings.av_stream_width`` / ``_height``), and the face has to be measured
#: at the resolution the robot would deliver — a larger canvas would give
#: MediaPipe more pixels to work with than it will ever really have.
DEFAULT_WIDTH, DEFAULT_HEIGHT = settings.av_stream_width, settings.av_stream_height

#: Flat mid-grey behind the subject. Plain by design: the harness measures
#: timing, and a busy background would add detection variance that has nothing
#: to do with what is being measured.
DEFAULT_BACKGROUND = 210


def _positive(distance_cm: float) -> float:
    if distance_cm <= 0:
        raise ValueError(f"distance must be positive, got {distance_cm}")
    return float(distance_cm)


@dataclass(frozen=True)
class FaceGeometry:
    """Where the face sits in the source photograph, in source pixels."""

    width_px: float
    centre_x: float
    centre_y: float


def measure_face(image: np.ndarray) -> FaceGeometry:
    """Locate the face in a photograph, for compositing.

    Reads ``FACE_MESH_SETTINGS`` rather than restating it, so the confidence
    thresholds and landmark refinement here are the robot's, not a second set
    that could drift from them.

    It does change one thing: ``static_image_mode=True``. PLAN.md §12.1
    measured tracking as *more* accurate than this on video, but there is no
    video here — one photograph, nothing before it — and tracking with nothing
    to track from is the case the setting exists for.
    """
    import cv2
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, **FACE_MESH_SETTINGS
    ) as face_mesh:
        result = face_mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    if not result.multi_face_landmarks:
        raise ValueError(
            "no face found in the source photograph — the harness cannot "
            "composite a subject it cannot locate"
        )

    height, width = image.shape[:2]
    landmarks = result.multi_face_landmarks[0].landmark
    left_x = landmarks[LEFT_CHEEK].x * width
    right_x = landmarks[RIGHT_CHEEK].x * width
    return FaceGeometry(
        width_px=abs(right_x - left_x),
        centre_x=(left_x + right_x) / 2.0,
        centre_y=landmarks[NOSE_TIP].y * height,
    )


class FaceComposer:
    """Renders a photograph of a person standing at a commanded distance.

    Everything a caller must know:

    * ``frame_at(distance_cm)`` returns a BGR image of the canvas size, with
      the subject's face subtending the width that distance implies. Calls are
      pure: the same distance always renders the same pixels.
    * ``face_width_px(distance_cm)`` is that width, exposed because the
      fixture's usable range is stated in pixels (PLAN.md §12.5).
    * The subject is centred. Position in frame is not modelled — the distance
      estimate reads face width only, so moving the subject sideways would add
      variance without adding coverage.
    * Beyond roughly 195 cm the face falls under 50 px and MediaPipe stops
      finding it. The composer still renders it; it does not pretend.

    Locating the face in the source runs the detector once, during
    construction, so no measurement cost lands inside a rendered frame.
    """

    def __init__(
        self,
        portrait: np.ndarray,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        focal_length: float = settings.focal_length,
        real_face_width_cm: float = settings.real_face_width_cm,
    ) -> None:
        self.width = width
        self.height = height
        self._portrait = portrait
        self._focal_length = focal_length
        self._real_face_width_cm = real_face_width_cm
        self._geometry = measure_face(portrait)

    def face_width_px(self, distance_cm: float) -> float:
        """Pixel width a face subtends at ``distance_cm``.

        The calibration formula, inverted. ``FaceDetector`` applies it forward
        over the same two constants, which is what lets the self-validation
        test compare a commanded distance against a measured one.
        """
        return self._focal_length * self._real_face_width_cm / _positive(distance_cm)

    def frame_at(self, distance_cm: float) -> np.ndarray:
        """A frame showing the subject standing ``distance_cm`` away."""
        import cv2

        scale = self.face_width_px(distance_cm) / self._geometry.width_px
        subject = cv2.resize(
            self._portrait, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )

        canvas = np.full(
            (self.height, self.width, 3), DEFAULT_BACKGROUND, dtype=np.uint8
        )
        # Align the subject's face with the centre of the canvas, then keep
        # whatever overlap survives — a close subject overflows the frame, as
        # it would on a real camera.
        offset_x = int(self.width / 2 - self._geometry.centre_x * scale)
        offset_y = int(self.height / 2 - self._geometry.centre_y * scale)
        src_x, src_y = max(0, -offset_x), max(0, -offset_y)
        dst_x, dst_y = max(0, offset_x), max(0, offset_y)
        copy_w = min(subject.shape[1] - src_x, self.width - dst_x)
        copy_h = min(subject.shape[0] - src_y, self.height - dst_y)
        if copy_w > 0 and copy_h > 0:
            canvas[dst_y : dst_y + copy_h, dst_x : dst_x + copy_w] = subject[
                src_y : src_y + copy_h, src_x : src_x + copy_w
            ]
        return canvas


class SyntheticCamera:
    """A :class:`VideoSource` showing a person you can move.

    Everything a caller must know:

    * ``start()`` begins emitting frames at ``fps`` on a background thread;
      ``stop()`` ends it. Both idempotent.
    * ``place(distance_cm)`` moves the subject. Frames emitted after the call
      show the new distance; the one unread older frame may remain until the
      next frame replaces it or a caller flushes explicitly.
    * ``read`` / ``flush`` / ``backlog`` / ``dropped_frames`` behave as on the
      RTSP source, including the one-frame latest-value buffer.

    Rendering happens on the producer thread, so the frame rate is a ceiling
    rather than a guarantee: if compositing takes longer than the interval, the
    camera falls behind rather than queueing work. A real camera does the same.
    """

    def __init__(
        self,
        composer: FaceComposer,
        *,
        fps: float = 30.0,
        start_distance_cm: float = 100.0,
    ) -> None:
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        self._composer = composer
        self._interval_s = 1.0 / fps
        self._buffer = FrameBuffer()
        self._worker = WorkerThread(self._emit_loop, name="synthetic-camera")
        # Written by whoever drives the scene, read by the producer thread. A
        # float rebind is atomic under the GIL and the producer is content with
        # whichever value it happens to see — a frame either shows the old
        # position or the new one, and both are honest.
        self._distance_cm = _positive(start_distance_cm)

    # ---------- driving the scene ----------

    def place(self, distance_cm: float) -> None:
        """Move the subject to ``distance_cm`` from the robot."""
        self._distance_cm = _positive(distance_cm)

    @property
    def distance_cm(self) -> float:
        """Where the subject is standing — the ground truth, by construction."""
        return self._distance_cm

    # ---------- VideoSource ----------

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()

    def read(self, timeout: float) -> Optional[CapturedFrame]:
        return self._buffer.read(timeout)

    def flush(self) -> None:
        self._buffer.flush()

    @property
    def backlog(self) -> int:
        return self._buffer.depth

    @property
    def dropped_frames(self) -> int:
        return self._buffer.dropped_frames

    # ---------- implementation ----------

    def _emit_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            due_at = time.monotonic() + self._interval_s
            image = self._composer.frame_at(self._distance_cm)
            # Stamped where the RTSP reader stamps it: the moment the frame
            # becomes available to this process, before anyone looks at it.
            self._buffer.put(
                CapturedFrame(image=image, arrived_at=time.monotonic())
            )
            stop.wait(max(0.0, due_at - time.monotonic()))

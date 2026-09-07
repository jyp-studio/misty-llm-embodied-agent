"""Timestamped video in, one fresh distance belief out.

``DistancePipeline`` is the production implementation of the same
``latest_reading()`` interface used by the replay harness. It owns face
detection, a single latest-value sample, and the rule that a reading is fresh
only while its source frame is recent on the process-ingress clock.

The clock starts when a frame becomes observable to this process. Camera
exposure, encoding, Wi-Fi and RTSP transport happened before that point and
remain an explicit, uncalibrated assumption; nothing in this module claims to
measure them.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from misty_agent.config import settings
from misty_agent.drivers.av_stream import VideoSource, WorkerThread


@dataclass(frozen=True)
class DistanceReading:
    """A distance belief and the process-local time span behind it.

    ``frame_arrived_at`` is when the source frame became observable to this
    process; ``detected_at`` is when face detection made the reading available.
    Both use ``time.monotonic()``. Decision time is supplied to :meth:`age_s`
    by the caller, so the three events cannot be confused.
    """

    distance_cm: int
    frame_arrived_at: float
    detected_at: float

    def age_s(self, now: Optional[float] = None) -> float:
        """Age of the effective source frame at decision time."""
        return (time.monotonic() if now is None else now) - self.frame_arrived_at

    @property
    def frame_age_s(self) -> float:
        """Process ingress to publication of this reading."""
        return self.detected_at - self.frame_arrived_at

class EmptyRoom:
    """A reading source with nobody in front of it, for as long as anyone asks.

    `None` is already what this seam says for "no reading" — `LivePerception`
    turns it into `face_present=False` with no distance — so this is a null
    object in the sense `NEVER_STOPS`, `NO_MEMORY` and `HEARS_NOTHING` are,
    and it lives here for the same reason they live beside their own
    protocols: next to `DistancePipeline`, the real thing it stands in for.

    It is what a photograph with no face in it produces. Inventing a distance
    there would be the caller inventing a person the camera did not find.
    """

    def latest_reading(self) -> None:
        return None


#: A room with nobody in it, shared because it holds nothing.
NOBODY_THERE = EmptyRoom()


class DistancePipeline:
    """Continuously turn the latest available video frame into fresh distance.

    The source owns its own lifetime. Callers start the source, then this
    pipeline, and stop them in reverse order. ``latest_reading`` is safe to call
    from another thread and returns ``None`` before the first usable frame or
    after every retained sample has become stale.
    """

    def __init__(
        self,
        source: VideoSource,
        *,
        max_age_s: float = settings.distance_max_age_s,
        read_timeout_s: float = 0.5,
    ) -> None:
        if max_age_s <= 0:
            raise ValueError(f"max_age_s must be positive, got {max_age_s}")
        if read_timeout_s <= 0:
            raise ValueError(f"read_timeout_s must be positive, got {read_timeout_s}")

        self._source = source
        self._max_age_s = max_age_s
        self._read_timeout_s = read_timeout_s
        self._latest: Optional[DistanceReading] = None
        self._lock = threading.Lock()
        self._worker = WorkerThread(self._consume_loop, name="distance-pipeline")

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()

    def latest_reading(self) -> Optional[DistanceReading]:
        """The latest reading while it remains fresh, or ``None``.

        Freshness is decided now against the source frame's process-ingress time.
        A recent detection cannot make an old frame fresh.
        """
        now = time.monotonic()
        with self._lock:
            reading = self._latest
        if reading is None:
            return None
        age_s = now - reading.frame_arrived_at
        return reading if 0.0 <= age_s <= self._max_age_s else None

    def _consume_loop(self, stop: threading.Event) -> None:
        from misty_agent.perception.face import FaceDetector

        with FaceDetector() as detector:
            while not stop.is_set():
                frame = self._source.read(timeout=self._read_timeout_s)
                if frame is None:
                    continue
                face = detector.detect(frame.image)
                if not face.has_human:
                    continue
                reading = DistanceReading(
                    distance_cm=face.distance_cm,
                    frame_arrived_at=frame.arrived_at,
                    detected_at=time.monotonic(),
                )
                with self._lock:
                    self._latest = reading

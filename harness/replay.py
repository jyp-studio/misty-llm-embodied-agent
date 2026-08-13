"""Drive a script through a perception pipeline and write down what happened.

The output is a :class:`Trace`: one row per sampling instant holding where the
person actually was, what the system said about it, and how deep the frame
buffer had grown. Nothing here draws a conclusion — turning a trace into a
latency figure is ticket 06's job, and diagnostics are 07's. Keeping the
recording separate from the reading means a disagreement about how to compute
lag does not require re-running anything.

**The pipeline under test is a parameter.** Ticket 03 — which would have
extracted the existing distance estimator — was retired when the project moved
from patching to rewriting (PLAN.md §12.3), so there is no single pipeline this
harness is *for*. :class:`DirectPipeline` is the floor: read a frame, detect,
keep the answer, nothing else. The rewritten pipeline plugs into the same seam
and gets measured the same way, which is the only way the two numbers are
comparable.

**Real time, no virtual clock.** MediaPipe's per-frame cost is part of what is
being measured, so a replay of a ten-second script takes ten seconds. The spec
rules on this explicitly; simulating the clock would assume away the cause.
"""

from __future__ import annotations

import json
import platform
import sys
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Tuple

from harness.trajectory import APPROACH_HOLD_STEP, Trajectory
from misty_agent.drivers.av_stream import VideoSource, WorkerThread
from misty_agent.perception.distance import DistanceReading
from misty_agent.perception.face import UNKNOWN_DISTANCE_CM

log = logging.getLogger(__name__)


class MovableCamera(Protocol):
    """A camera whose subject can be moved, and whose backlog can be read."""

    def place(self, distance_cm: float) -> None: ...

    @property
    def backlog(self) -> int: ...


class DistancePipeline(Protocol):
    """Whatever turns frames into a distance reading.

    One method, because that is the entire question the harness asks it: *what
    do you believe, and from which frame?* How it got there — buffering,
    filtering, sample windows — is exactly what is under measurement and must
    not leak into this interface, or a trace of one pipeline could not be
    compared against a trace of another.

    Returns ``None`` when it has nothing to say. That is a legitimate answer,
    not an error: a pipeline that has seen no usable frame yet, or has just
    invalidated its samples, genuinely does not know.
    """

    def latest_reading(self) -> Optional[DistanceReading]: ...


@dataclass(frozen=True)
class Sample:
    """One row: where the person was, and what the system thought.

    There is deliberately **no error field**. The obvious one — reported minus
    truth — sums two unrelated quantities: a static bias from the fixture and
    the calibration, and lag multiplied by however fast the person was moving.
    During a hold the second term is zero and the number is pure bias; at a
    step it is undefined. Publishing it invites reading a bias as a latency,
    which is exactly the mistake this ticket's first write-up made. Ticket 06
    estimates lag by correlating the two curves, which is why both are here in
    full.
    """

    t: float
    truth_cm: float
    reported_cm: int
    backlog: int
    #: Of the frame the reading came from; ``None`` when there was no reading.
    frame_arrived_at: Optional[float] = None
    #: When the pipeline finished with that frame.
    detected_at: Optional[float] = None

    @property
    def has_reading(self) -> bool:
        return self.reported_cm > 0

    @property
    def frame_age_s(self) -> Optional[float]:
        """Frame age at detection — ticket 07's diagnostic."""
        if self.frame_arrived_at is None or self.detected_at is None:
            return None
        return self.detected_at - self.frame_arrived_at


@dataclass(frozen=True)
class Trace:
    """Everything one replay produced, and the conditions it ran under.

    The environment is recorded because PLAN.md §12.2 measured the same
    pipeline running an order of magnitude faster than the plan had assumed,
    purely because of the host. A latency number without its machine is not a
    result, and 09 has to print both.
    """

    samples: Tuple[Sample, ...]
    trajectory: str
    sample_hz: float
    environment: Dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """The trace as JSON Lines: a header row, then one row per sample."""
        header = json.dumps(
            {
                "trajectory": self.trajectory,
                "sample_hz": self.sample_hz,
                "samples": len(self.samples),
                "environment": self.environment,
            }
        )
        rows = [
            json.dumps(
                {
                    "t": round(sample.t, 6),
                    "truth_cm": round(sample.truth_cm, 3),
                    "reported_cm": sample.reported_cm,
                    "backlog": sample.backlog,
                    "frame_age_s": (
                        None
                        if sample.frame_age_s is None
                        else round(sample.frame_age_s, 6)
                    ),
                }
            )
            for sample in self.samples
        ]
        return "\n".join([header, *rows])


def describe_environment() -> Dict[str, Any]:
    """The parts of the host that move a latency measurement."""
    return {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def replay(
    trajectory: Trajectory,
    camera: MovableCamera,
    pipeline: DistancePipeline,
    *,
    sample_hz: float = 20.0,
) -> Trace:
    """Play ``trajectory`` in front of ``camera`` and record what ``pipeline`` said.

    Both must already be running; this drives and observes them, it does not own
    them. Returns once the script has played out — in real time, so a ten-second
    script blocks for ten seconds.

    Each row's truth is the script evaluated at that row's own timestamp, read
    immediately before the pipeline is asked. The gap between those two is the
    quantity the harness exists to measure, so it is kept as small as possible
    rather than being assumed away.
    """
    if sample_hz <= 0:
        raise ValueError(f"sample_hz must be positive, got {sample_hz}")

    interval_s = 1.0 / sample_hz
    samples = []
    started_at = time.monotonic()
    next_sample_at = started_at

    while True:
        now = time.monotonic()
        elapsed = now - started_at
        truth_cm = trajectory.distance_at(elapsed)

        camera.place(truth_cm)
        reading = pipeline.latest_reading()
        samples.append(
            Sample(
                t=elapsed,
                truth_cm=truth_cm,
                reported_cm=(
                    reading.distance_cm if reading else UNKNOWN_DISTANCE_CM
                ),
                backlog=camera.backlog,
                frame_arrived_at=reading.frame_arrived_at if reading else None,
                detected_at=reading.detected_at if reading else None,
            )
        )

        if elapsed >= trajectory.duration_s:
            break

        next_sample_at += interval_s
        now = time.monotonic()
        if next_sample_at < now:
            # Fallen behind. Re-base rather than firing the missed slots
            # back to back: a burst of near-identical rows would be handed to
            # 06 as if the person had been sampled that densely, skewing the
            # correlation it computes.
            log.debug("replay sampling fell behind by %.3fs", now - next_sample_at)
            next_sample_at = now
        time.sleep(max(0.0, next_sample_at - now))

    return Trace(
        samples=tuple(samples),
        trajectory=trajectory.describe(),
        sample_hz=sample_hz,
        environment=describe_environment(),
    )


class DirectPipeline:
    """Read a frame, detect a face, keep the answer. Nothing else.

    The M4 floor against which the production pipeline was designed: no median
    filter, no sample window, no invalidation. Whatever lag a trace of this
    shows is the cost of frame delivery and detection alone.

    It reads one frame per pass. The source now has production latest-value
    semantics, so a slow consumer skips replaced frames rather than traversing
    an old queue.

    The detector is stateful across frames and expects a video sequence in
    order, which is exactly what it gets here.
    """

    def __init__(self, source: VideoSource, *, read_timeout_s: float = 0.5) -> None:
        self._source = source
        self._read_timeout_s = read_timeout_s
        # Rebound whole by the worker, read by the recorder. Rebinding a
        # reference is atomic under the GIL and the recorder wants whichever
        # of the two it happens to see — both are readings the pipeline really
        # produced, and which one it catches is exactly the timing this
        # measures.
        self._latest: Optional[DistanceReading] = None
        self._worker = WorkerThread(self._consume_loop, name="direct-pipeline")

    def latest_reading(self) -> Optional[DistanceReading]:
        return self._latest

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()

    def _consume_loop(self, stop: threading.Event) -> None:
        from misty_agent.perception.face import FaceDetector

        with FaceDetector() as detector:
            while not stop.is_set():
                frame = self._source.read(timeout=self._read_timeout_s)
                if frame is None:
                    continue
                reading = detector.detect(frame.image)
                # A frame with nobody in it leaves the last reading standing,
                # matching what a controller would see: a dropped detection is
                # not news that the person left.
                if reading.has_human:
                    self._latest = DistanceReading(
                        distance_cm=reading.distance_cm,
                        frame_arrived_at=frame.arrived_at,
                        detected_at=time.monotonic(),
                    )


def default_replay(portrait, *, trajectory: Trajectory = APPROACH_HOLD_STEP,
                   sample_hz: float = 40.0) -> Trace:
    """Record the standard script against the production distance pipeline.

    The one call the latency bound and report need: it wires the synthetic
    camera to the same pipeline runtime control will use, plays ``trajectory``,
    and hands back the trace. Takes as long as the script does.

    ``sample_hz`` defaults above the camera's frame rate on purpose. Sampling
    slower than the source cannot resolve a lag shorter than one frame period,
    and the process-local lag is around that size — the first recorded run at
    20 Hz could say only "under 50 ms".
    """
    from harness.synthetic_camera import FaceComposer, SyntheticCamera
    from misty_agent.perception.distance import (
        DistancePipeline as ProductionPipeline,
    )

    camera = SyntheticCamera(
        FaceComposer(portrait), start_distance_cm=trajectory.start_cm
    )
    pipeline = ProductionPipeline(camera)
    camera.start()
    pipeline.start()
    try:
        return replay(trajectory, camera, pipeline, sample_hz=sample_hz)
    finally:
        pipeline.stop()
        camera.stop()

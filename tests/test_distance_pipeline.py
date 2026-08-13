"""The production seam from timestamped video to a fresh distance reading.

These tests cross the same public ``latest_reading()`` seam the M4 harness
uses. They deliberately do not inspect the sample deque or worker thread: a
different implementation that reports the same fresh distance is equivalent.
"""

from __future__ import annotations

import time

import pytest
from conftest import SKIP_REASON

from misty_agent.drivers.av_stream import CapturedFrame, FrameBuffer
from misty_agent.perception.distance import DistanceReading


class ManualVideoSource:
    """A VideoSource adapter whose frames are published by the test."""

    def __init__(self) -> None:
        self._buffer = FrameBuffer()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def publish(self, frame: CapturedFrame) -> None:
        self._buffer.put(frame)

    def read(self, timeout: float):
        return self._buffer.read(timeout)

    def flush(self) -> None:
        self._buffer.flush()

    @property
    def backlog(self) -> int:
        return self._buffer.depth

    @property
    def dropped_frames(self) -> int:
        return self._buffer.dropped_frames


def _wait_for_reading(pipeline, timeout_s: float = 2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        reading = pipeline.latest_reading()
        if reading is not None:
            return reading
        time.sleep(0.01)
    return None


def test_reading_distinguishes_ingress_detection_and_decision_time():
    reading = DistanceReading(
        distance_cm=90,
        frame_arrived_at=10.0,
        detected_at=10.04,
    )

    assert reading.frame_age_s == pytest.approx(0.04)
    assert reading.age_s(now=10.20) == pytest.approx(0.20)

    # Camera exposure and transport preceded process ingress. They are not a
    # field on the reading and must not silently inflate either measured value.
    assumed_transport_lag_s = 1.5
    end_to_end_age_s = 10.20 - (10.0 - assumed_transport_lag_s)
    assert end_to_end_age_s == pytest.approx(1.70)
    assert reading.age_s(now=10.20) != pytest.approx(end_to_end_age_s)


def test_a_stale_frame_cannot_contribute_to_the_latest_distance(portrait):
    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.synthetic_camera import FaceComposer
    from misty_agent.perception.distance import DistancePipeline

    composer = FaceComposer(portrait)
    source = ManualVideoSource()
    pipeline = DistancePipeline(source, max_age_s=0.05, read_timeout_s=0.01)
    pipeline.start()
    try:
        source.publish(
            CapturedFrame(
                image=composer.frame_at(120.0),
                arrived_at=time.monotonic() - 1.0,
            )
        )
        # Let the worker finish detection. The value is numerically valid but
        # already stale at decision time, so the public answer remains empty.
        time.sleep(0.15)
        assert pipeline.latest_reading() is None

        source.publish(
            CapturedFrame(
                image=composer.frame_at(90.0), arrived_at=time.monotonic()
            )
        )
        reading = _wait_for_reading(pipeline)
    finally:
        pipeline.stop()

    assert reading is not None
    assert reading.distance_cm == pytest.approx(90.0, rel=0.05)
    assert 0.0 <= reading.age_s() < 0.5
    assert 0.0 <= reading.frame_age_s < 0.5

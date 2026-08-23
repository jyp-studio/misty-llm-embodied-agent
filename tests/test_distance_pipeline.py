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
        self._frames_read = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def publish(self, frame: CapturedFrame) -> None:
        self._buffer.put(frame)

    def read(self, timeout: float):
        frame = self._buffer.read(timeout)
        if frame is not None:
            self._frames_read += 1
        return frame

    @property
    def frames_read(self) -> int:
        """Frames the consumer has actually taken.

        The pipeline's worker loops read -> detect -> store, so this rising to
        N proves the first N-1 frames were carried all the way through. It is
        the only handle a test has on "detection has finished", which is
        otherwise invisible from outside the module.
        """
        return self._frames_read

    def flush(self) -> None:
        self._buffer.flush()

    @property
    def backlog(self) -> int:
        return self._buffer.depth

    @property
    def dropped_frames(self) -> int:
        return self._buffer.dropped_frames


def _wait_until(predicate, *, what, state=None, timeout_s: float = 10.0):
    """Block until `predicate()` holds, or fail saying what never happened.

    A duration is not evidence that an event happened; it is a bet on the
    scheduler. See `tests/test_synthetic_camera.py` for the same helper and
    the flake that prompted both.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    observed = f" (observed {state()})" if state is not None else ""
    raise AssertionError(
        f"waited {timeout_s}s for {what}, which never happened{observed}"
    )


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
        # Two stale frames, not one. The assertion below is that a numerically
        # valid but stale reading stays out of the public answer — and it
        # passes trivially if the worker has not looked yet. Sleeping for a
        # duration and hoping detection finished inside it makes the test pass
        # for the wrong reason on a loaded machine, which is worse than a flake
        # because it is silent: a broken freshness check would go unnoticed.
        #
        # The worker loops read -> detect -> store, so waiting for the *second*
        # frame to be taken proves the first went all the way through.
        def publish_stale():
            source.publish(
                CapturedFrame(
                    image=composer.frame_at(120.0),
                    arrived_at=time.monotonic() - 1.0,
                )
            )

        publish_stale()
        # Wait for the first to be taken before publishing the second, rather
        # than spacing them by a sleep: the source keeps only the latest frame,
        # so a slow worker would see the second replace the first and the count
        # below would never reach two.
        _wait_until(
            lambda: source.frames_read >= 1,
            what="the worker to take the first stale frame",
            state=lambda: f"frames_read={source.frames_read}",
        )
        publish_stale()
        _wait_until(
            lambda: source.frames_read >= 2,
            what="the worker to take the second stale frame, which proves it "
            "finished detecting the first",
            state=lambda: f"frames_read={source.frames_read}",
        )

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

"""Acceptance tests for the public bounded ``approach()`` behaviour.

The seam is intentionally narrow: distance readings enter through the same
``latest_reading()`` interface used by the replay harness, and robot movement
is observed through the recording command adapter. No assertion reaches into
sample containers, invalidation bookkeeping, polling, or threads.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from misty_agent.config import Settings
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.fakes import RecordingCommands
from misty_agent.perception.distance import DistanceReading


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass(frozen=True)
class ScheduledReading:
    available_at: float
    reading: DistanceReading


class ScheduledReadings:
    """A public reading seam whose world advances with the injected clock."""

    def __init__(self, clock: FakeClock, *readings: ScheduledReading) -> None:
        self._clock = clock
        self._readings = readings

    def latest_reading(self):
        available = [
            item.reading
            for item in self._readings
            if item.available_at <= self._clock.monotonic()
        ]
        return available[-1] if available else None


class TickReadings:
    """Produces a distinct current reading whenever approach polls it."""

    def __init__(self, clock: FakeClock, distance_cm: int) -> None:
        self._clock = clock
        self._distance_cm = distance_cm

    def latest_reading(self):
        self._clock.sleep(0.001)
        return _reading(self._distance_cm, self._clock.monotonic())


class ExplodingRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        raise OSError("connection closed")


class TimedOutRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        raise TimeoutError(f"no response within {timeout}s")


class NoContentRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        return SimpleNamespace(status_code=204)


def _reading(distance_cm: int, arrived_at: float) -> DistanceReading:
    return DistanceReading(
        distance_cm=distance_cm,
        frame_arrived_at=arrived_at,
        detected_at=arrived_at,
    )


def test_startup_waits_for_two_fresh_readings_before_arriving():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, _reading(61, 0.10)),
        ScheduledReading(0.20, _reading(60, 0.20)),
    )
    robot = RecordingCommands()

    result = approach(
        readings,
        robot,
        config=Settings(approach_reading_timeout_s=0.5),
        clock=clock,
    )

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 0
    assert robot.requests == []
    assert clock.monotonic() >= 0.20


def test_a_move_is_followed_by_two_post_move_readings_before_arrival():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, _reading(100, 0.10)),
        ScheduledReading(0.20, _reading(100, 0.20)),
        # This old-world frame only becomes visible after the drive finishes.
        # Its value would command another forward step if timestamp freshness
        # were replaced by settling alone.
        ScheduledReading(1.48, _reading(100, 0.30)),
        ScheduledReading(1.49, _reading(72, 1.49)),
        ScheduledReading(1.50, _reading(70, 1.50)),
    )
    robot = RecordingCommands()

    result = approach(
        readings,
        robot,
        config=Settings(
            approach_reading_timeout_s=0.5,
            post_step_settle_s=0.0,
        ),
        clock=clock,
    )

    drives = [request for request in robot.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert len(drives) == 1
    assert drives[0].body_without_defaults() == {
        "linearVelocity": 20,
        "angularVelocity": 0,
        "timeMs": 1272,
    }


def test_too_close_commands_one_bounded_backward_step_then_arrives():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, _reading(30, 0.10)),
        ScheduledReading(0.20, _reading(30, 0.20)),
        ScheduledReading(1.17, _reading(50, 1.17)),
        ScheduledReading(1.18, _reading(51, 1.18)),
    )
    robot = RecordingCommands()

    result = approach(
        readings,
        robot,
        config=Settings(
            approach_reading_timeout_s=0.5,
            post_step_settle_s=0.0,
        ),
        clock=clock,
    )

    drive = robot.last("drive/time").body_without_defaults()
    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert drive["linearVelocity"] == -20
    assert drive["timeMs"] == 954


def test_stale_in_band_readings_end_as_lost_user_without_motion():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.0, _reading(60, -0.20)),
        ScheduledReading(0.0, _reading(60, -0.10)),
    )
    robot = RecordingCommands()

    result = approach(
        readings,
        robot,
        config=Settings(approach_reading_timeout_s=0.05),
        clock=clock,
    )

    assert result.status is ApproachStatus.LOST_USER
    assert result.steps == 0
    assert robot.requests == []
    assert clock.monotonic() == 0.05


def test_two_readings_must_be_fresh_at_the_same_decision_time():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, _reading(60, 0.10)),
        # By the time this arrives, the first sample is older than max_age_s.
        ScheduledReading(0.40, _reading(60, 0.40)),
    )

    result = approach(
        readings,
        RecordingCommands(),
        config=Settings(
            approach_reading_timeout_s=0.5,
            distance_max_age_s=0.20,
        ),
        clock=clock,
    )

    assert result.status is ApproachStatus.LOST_USER
    assert result.steps == 0


def test_step_limit_returns_timeout_and_stops_issuing_commands():
    clock = FakeClock()
    robot = RecordingCommands()

    result = approach(
        TickReadings(clock, distance_cm=100),
        robot,
        config=Settings(max_approach_steps=2, post_step_settle_s=0.0),
        clock=clock,
    )

    drives = [request for request in robot.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.TIMEOUT
    assert result.steps == 2
    assert len(drives) == 2


def test_robot_refusal_returns_drive_error_without_assuming_a_step_happened():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        RecordingCommands(fail_endpoints=["drive/time"]),
        config=Settings(),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_any_successful_http_status_is_accepted():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        NoContentRobot(),
        config=Settings(max_approach_steps=1, post_step_settle_s=0.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.TIMEOUT
    assert result.steps == 1


def test_synthetic_video_and_recording_robot_close_one_real_perception_loop(
    portrait,
):
    import pytest
    from conftest import SKIP_REASON

    pytest.importorskip("cv2", reason=SKIP_REASON)
    pytest.importorskip("mediapipe", reason=SKIP_REASON)

    from harness.synthetic_camera import FaceComposer, SyntheticCamera
    from misty_agent.perception.distance import DistancePipeline

    camera = SyntheticCamera(FaceComposer(portrait), start_distance_cm=100.0)

    class MovingRecordingRobot(RecordingCommands):
        def _generic_request(self, verb, endpoint, **kwargs):
            response = super()._generic_request(verb, endpoint, **kwargs)
            if endpoint == "drive/time" and response.status_code == 200:
                body = kwargs["json"]
                signed_distance_cm = (
                    body["linearVelocity"] / 20 * body["timeMs"] / 1000 * 22
                )
                camera.place(camera.distance_cm - signed_distance_cm)
            return response

    pipeline = DistancePipeline(camera, read_timeout_s=0.01)
    robot = MovingRecordingRobot()
    camera.start()
    pipeline.start()
    try:
        result = approach(
            pipeline,
            robot,
            config=Settings(
                approach_reading_timeout_s=2.0,
                post_step_settle_s=0.05,
            ),
        )
    finally:
        pipeline.stop()
        camera.stop()

    drives = [request for request in robot.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert len(drives) == 1


def test_robot_exception_returns_drive_error_without_assuming_a_step_happened():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        ExplodingRobot(),
        config=Settings(),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_readings_arriving_during_settle_count_after_motion():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.01, _reading(100, 0.01)),
        ScheduledReading(0.02, _reading(100, 0.02)),
        ScheduledReading(1.32, _reading(70, 1.32)),
        ScheduledReading(1.34, _reading(70, 1.34)),
    )

    result = approach(
        readings,
        RecordingCommands(),
        config=Settings(
            approach_reading_timeout_s=0.5,
            post_step_settle_s=0.10,
        ),
        clock=clock,
    )

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1


def test_settle_does_not_consume_the_independent_reading_timeout():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.01, _reading(100, 0.01)),
        ScheduledReading(0.02, _reading(100, 0.02)),
        ScheduledReading(1.32, _reading(70, 1.32)),
        ScheduledReading(1.34, _reading(70, 1.34)),
    )

    result = approach(
        readings,
        RecordingCommands(),
        config=Settings(
            approach_reading_timeout_s=0.05,
            post_step_settle_s=0.20,
        ),
        clock=clock,
    )

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1


def test_whole_call_deadline_bounds_an_unresponsive_robot_adapter():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        TimedOutRobot(),
        config=Settings(approach_timeout_s=2.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_whole_call_deadline_includes_commanded_motion_time():
    clock = FakeClock()
    robot = RecordingCommands()
    result = approach(
        TickReadings(clock, distance_cm=100),
        robot,
        config=Settings(approach_timeout_s=0.5, post_step_settle_s=0.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.TIMEOUT
    assert result.steps == 0
    assert not robot.requests

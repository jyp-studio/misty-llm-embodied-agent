"""Acceptance tests for the public bounded ``approach()`` behaviour.

The seam is intentionally narrow: distance readings enter through the same
``latest_reading()`` interface used by the replay harness, and robot movement
is observed through the recording command adapter. No assertion reaches into
sample containers, invalidation bookkeeping, polling, or threads.
"""

from __future__ import annotations

import dataclasses

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from misty_agent.config import Settings
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.fakes import (
    FakeClock,
    RecordingCommands,
    a_reading,
)
from misty_agent.robot import RealMistyAdapter, SimulatedMistyAdapter
from misty_agent.perception.distance import DistanceReading


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
        return a_reading(self._distance_cm, self._clock.monotonic())


class WorldThatLosesTheUserAfterAStep(SimulatedMistyAdapter):
    """The subject walks out of frame once at least one Step has been issued.

    It mirrors what the production pipeline does rather than a convenient
    simplification. `DistancePipeline.latest_reading` keeps offering the last
    reading it computed — with the timestamp that reading already had — until
    that timestamp ages past `distance_max_age_s`, and only then returns
    nothing. The loop is therefore offered a stale reading first and nothing
    at all later.

    **The two phases are for fidelity, not for discrimination.** A double that
    simply returned nothing from the first post-Step poll makes this file pass
    identically — checked. So nothing below tells you *which* rule rejects the
    stale reading, and the docstring does not claim otherwise: `_fresh_median`
    needs both a post-epoch timestamp and two samples, and either alone
    accounts for the rejection. Tests that do discriminate the epoch already
    exist — `test_readings_arriving_during_settle_count_after_motion` and
    `test_two_readings_must_be_fresh_at_the_same_decision_time`.

    The startup counterpart is
    `test_stale_in_band_readings_end_as_lost_user_without_motion`.
    """

    def __init__(self, clock: FakeClock, *, start_cm: float, config: Settings) -> None:
        super().__init__(
            clock,
            start_cm=start_cm,
            actual_motion_multiplier=1.0,
            config=config,
        )
        self._max_age_s = config.distance_max_age_s
        self._last_seen = None
        #: Drives issued at the moment the subject first stopped being visible.
        #: The assertion compares against this rather than a literal count, so
        #: the test says "nothing further was commanded" instead of pinning a
        #: number to the control law's step sizes — which is what made the old
        #: runner's `drive calls == 2` brittle.
        self.drives_when_lost = None

    def latest_reading(self):
        if not self.directions:
            self._last_seen = super().latest_reading()
            return self._last_seen
        if self.drives_when_lost is None:
            self.drives_when_lost = len(self.directions)
        if self._last_seen is None:
            return None
        aged_s = self._clock.monotonic() - self._last_seen.frame_arrived_at
        return None if aged_s > self._max_age_s else self._last_seen


class ExplodingRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        raise OSError("connection closed")


class TimedOutRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        raise TimeoutError(f"no response within {timeout}s")


class NoContentRobot(RecordingCommands):
    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        return SimpleNamespace(status_code=204)


def test_startup_waits_for_two_fresh_readings_before_arriving():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, a_reading(61, 0.10)),
        ScheduledReading(0.20, a_reading(60, 0.20)),
    )
    robot = RealMistyAdapter(RecordingCommands())

    result = approach(
        readings,
        robot,
        config=Settings(approach_reading_timeout_s=0.5),
        clock=clock,
    )

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 0
    assert robot.commands.requests == []
    assert clock.monotonic() >= 0.20


def test_a_move_is_followed_by_two_post_move_readings_before_arrival():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, a_reading(100, 0.10)),
        ScheduledReading(0.20, a_reading(100, 0.20)),
        # This old-world frame only becomes visible after the drive finishes.
        # Its value would command another forward step if timestamp freshness
        # were replaced by settling alone.
        ScheduledReading(1.48, a_reading(100, 0.30)),
        ScheduledReading(1.49, a_reading(72, 1.49)),
        ScheduledReading(1.50, a_reading(70, 1.50)),
    )
    robot = RealMistyAdapter(RecordingCommands())

    result = approach(
        readings,
        robot,
        config=Settings(
            approach_reading_timeout_s=0.5,
            post_step_settle_s=0.0,
        ),
        clock=clock,
    )

    drives = [request for request in robot.commands.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert len(drives) == 1
    assert drives[0].body_without_defaults() == {
        "linearVelocity": 20,
        "angularVelocity": 0,
        "timeMs": 1181,
    }


def test_too_close_commands_one_bounded_backward_step_then_arrives():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, a_reading(30, 0.10)),
        ScheduledReading(0.20, a_reading(30, 0.20)),
        ScheduledReading(1.17, a_reading(50, 1.17)),
        ScheduledReading(1.18, a_reading(51, 1.18)),
    )
    robot = RealMistyAdapter(RecordingCommands())

    result = approach(
        readings,
        robot,
        config=Settings(
            approach_reading_timeout_s=0.5,
            post_step_settle_s=0.0,
        ),
        clock=clock,
    )

    drive = robot.commands.last("drive/time").body_without_defaults()
    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert drive["linearVelocity"] == -20
    assert drive["timeMs"] == 954


def test_stale_in_band_readings_end_as_stale_without_motion():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.0, a_reading(60, -0.20)),
        ScheduledReading(0.0, a_reading(60, -0.10)),
    )
    robot = RealMistyAdapter(RecordingCommands())

    result = approach(
        readings,
        robot,
        config=Settings(approach_reading_timeout_s=0.05),
        clock=clock,
    )

    assert result.status is ApproachStatus.STALE_READING
    assert result.steps == 0
    assert robot.commands.requests == []
    assert clock.monotonic() == 0.05


def test_losing_the_user_after_a_step_stops_issuing_drive_commands():
    """The property the deleted simulation runner's T5 bought.

    Every other `lost_user` test in this file loses the subject before the
    robot has taken a Step, so the whole post-Step path went unasserted — see
    `docs/measurements/m6-coverage-audit.md`, gap 2. `PLAN.md` §5 defect E is
    about giving up too early on exactly this path; M5 fixed the startup half.

    No step count is named. T5 said `drive calls == 2`, which was tied to the
    old control law's step sizes; the behaviour worth keeping is that nothing
    further is commanded once the subject is gone, whatever preceded it. It
    survives `approach_gain` from 0.05 to 1.0 and `max_step_cm` from 1 to 200.

    Assertion order is deliberate. The drive-count assertions come first
    because they are the ones a blind-drive defect trips: a loop that carried
    on using the last known distance also changes the status, and a status
    assertion placed first would take the failure and hide which property
    actually broke.
    """
    clock = FakeClock()
    config = Settings(approach_reading_timeout_s=0.5, post_step_settle_s=0.0)
    world = WorldThatLosesTheUserAfterAStep(clock, start_cm=140, config=config)

    result = approach(world, world, config=config, clock=clock)

    assert world.drives_when_lost is not None, "the subject never went missing"
    assert len(world.directions) == world.drives_when_lost, (
        "a drive was commanded after the subject was already gone"
    )
    assert result.steps >= 1, "the subject must be lost after a Step, not before"
    # Not just non-zero: the count reported has to be the count issued.
    # `steps=completed_steps * 2` passed the whole suite without this.
    assert result.steps == len(world.directions)
    assert result.status is ApproachStatus.LOST_USER


def test_two_readings_must_be_fresh_at_the_same_decision_time():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.10, a_reading(60, 0.10)),
        # By the time this arrives, the first sample is older than max_age_s.
        ScheduledReading(0.40, a_reading(60, 0.40)),
    )

    result = approach(
        readings,
        RealMistyAdapter(RecordingCommands()),
        config=Settings(
            approach_reading_timeout_s=0.5,
            distance_max_age_s=0.20,
        ),
        clock=clock,
    )

    assert result.status is ApproachStatus.STALE_READING
    assert result.steps == 0


def test_step_limit_is_reported_as_its_own_status_and_stops_issuing_commands():
    clock = FakeClock()
    robot = RealMistyAdapter(RecordingCommands())

    result = approach(
        TickReadings(clock, distance_cm=100),
        robot,
        config=Settings(max_approach_steps=2, post_step_settle_s=0.0),
        clock=clock,
    )

    drives = [request for request in robot.commands.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.STEP_LIMIT
    assert result.steps == 2
    assert len(drives) == 2


def test_robot_refusal_returns_drive_error_without_assuming_a_step_happened():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(RecordingCommands(fail_endpoints=["drive/time"])),
        config=Settings(),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_any_successful_http_status_is_accepted():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(NoContentRobot()),
        config=Settings(max_approach_steps=1, post_step_settle_s=0.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.STEP_LIMIT
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

    class AlignedByTheScenario:
        """The pipeline measures distance only. The scenario states the
        alignment explicitly, as the spec allows a simulation to; on hardware
        the controller would fail closed here instead."""

        def latest_reading(self):
            reading = pipeline.latest_reading()
            return None if reading is None else dataclasses.replace(reading, bearing_deg=0.0)

    robot = RealMistyAdapter(MovingRecordingRobot())
    camera.start()
    pipeline.start()
    try:
        result = approach(
            AlignedByTheScenario(),
            robot,
            config=Settings(
                approach_reading_timeout_s=2.0,
                post_step_settle_s=0.05,
            ),
        )
    finally:
        pipeline.stop()
        camera.stop()

    drives = [request for request in robot.commands.requests if request.endpoint == "drive/time"]
    assert result.status is ApproachStatus.ARRIVED
    assert 1 <= result.steps <= 2
    assert len(drives) == result.steps


def test_robot_exception_returns_drive_error_without_assuming_a_step_happened():
    clock = FakeClock()
    result = approach(
        TickReadings(clock, distance_cm=100),
        RealMistyAdapter(ExplodingRobot()),
        config=Settings(),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_readings_arriving_during_settle_count_after_motion():
    clock = FakeClock()
    readings = ScheduledReadings(
        clock,
        ScheduledReading(0.01, a_reading(100, 0.01)),
        ScheduledReading(0.02, a_reading(100, 0.02)),
        ScheduledReading(1.32, a_reading(70, 1.32)),
        ScheduledReading(1.34, a_reading(70, 1.34)),
    )

    result = approach(
        readings,
        RealMistyAdapter(RecordingCommands()),
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
        ScheduledReading(0.01, a_reading(100, 0.01)),
        ScheduledReading(0.02, a_reading(100, 0.02)),
        ScheduledReading(1.32, a_reading(70, 1.32)),
        ScheduledReading(1.34, a_reading(70, 1.34)),
    )

    result = approach(
        readings,
        RealMistyAdapter(RecordingCommands()),
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
        RealMistyAdapter(TimedOutRobot()),
        config=Settings(approach_timeout_s=2.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.DRIVE_ERROR
    assert result.steps == 0


def test_whole_call_deadline_includes_commanded_motion_time():
    clock = FakeClock()
    robot = RealMistyAdapter(RecordingCommands())
    result = approach(
        TickReadings(clock, distance_cm=100),
        robot,
        config=Settings(approach_timeout_s=0.5, post_step_settle_s=0.0),
        clock=clock,
    )

    assert result.status is ApproachStatus.TIMEOUT
    assert result.steps == 0
    assert not robot.commands.requests


def test_public_approach_reserves_enough_headroom_for_two_x_motion():
    """Regression for M4's 100 -> 44 cm calibration-error counterexample."""
    clock = FakeClock()
    config = Settings(post_step_settle_s=0.0)
    world = SimulatedMistyAdapter(
        clock,
        start_cm=100.0,
        actual_motion_multiplier=2.0,
        config=config,
    )

    result = approach(world, world, config=config, clock=clock)

    assert result.status is ApproachStatus.ARRIVED
    assert world.closest_cm >= config.min_safe_distance_cm
    assert (
        config.target_distance_cm - config.distance_tolerance_cm
        <= world.distance_cm
        <= config.target_distance_cm + config.distance_tolerance_cm
    )


@pytest.mark.parametrize(
    "override",
    [
        {"distance_tolerance_cm": 10.0},
        {"approach_gain": 0.5},
        {"min_step_cm": 30.0},
    ],
)
@pytest.mark.parametrize("expected_direction", [1, -1])
def test_non_default_controls_do_not_reverse_under_partial_motion(
    override,
    expected_direction,
):
    config = Settings(post_step_settle_s=0.0, **override)
    start_cm = config.target_distance_cm + expected_direction * 14.0
    clock = FakeClock()
    world = SimulatedMistyAdapter(
        clock,
        start_cm=start_cm,
        actual_motion_multiplier=1.0,
        config=config,
    )

    result = approach(world, world, config=config, clock=clock)

    assert result.status is ApproachStatus.ARRIVED
    assert world.directions
    assert set(world.directions) == {expected_direction}
    assert world.closest_cm >= config.min_safe_distance_cm


@pytest.mark.parametrize(
    "override",
    [
        {"distance_tolerance_cm": 10.0},
        {"approach_gain": 0.5},
        {"min_step_cm": 30.0},
    ],
)
@pytest.mark.parametrize("expected_direction", [1, -1])
def test_non_default_controls_cannot_force_motion_across_the_arrival_band(
    override,
    expected_direction,
):
    config = Settings(
        post_step_settle_s=0.0,
        **override,
    )
    start_cm = config.target_distance_cm + expected_direction * (
        config.distance_tolerance_cm + 1.0
    )
    clock = FakeClock()
    world = SimulatedMistyAdapter(
        clock,
        start_cm=start_cm,
        actual_motion_multiplier=2.0,
        config=config,
    )

    result = approach(world, world, config=config, clock=clock)

    assert result.status is ApproachStatus.ARRIVED
    assert result.steps == 1
    assert world.directions[0] == expected_direction
    assert world.closest_cm >= config.min_safe_distance_cm
    assert (
        config.target_distance_cm - config.distance_tolerance_cm
        <= world.distance_cm
        <= config.target_distance_cm + config.distance_tolerance_cm
    )

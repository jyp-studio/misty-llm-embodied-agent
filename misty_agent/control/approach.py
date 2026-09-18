"""One bounded closed-loop approach behind a small public interface.

The caller supplies the already-running reading source for the Episode's
Interaction Target and the Robot adapter. Everything else — sampling,
freshness epochs, aggregation, alignment, movement conversion, settling, and
error translation — stays behind :func:`approach`.

## Align, then approach

A reading carries a distance and, when the source can say, a bearing: where
the person is relative to the chassis heading, positive to the left. Each
iteration takes one fresh reading and does exactly one of three things: turn
the chassis toward the person (bounded by `max_turn_deg`, divided by the
uncalibrated motion multiplier so an over-eager robot cannot swing past the
other side of the tolerance), move one bounded distance step, or stop with a
typed status. Turning is a chassis motion; the head's yaw plays no part and
is never read here, because a head that looks at someone is not a base that
faces them.

A reading with no bearing ends the call as `bearing_unavailable` before any
motion. The live distance pipeline reports none, so on hardware this
controller fails closed until a bearing source exists.

This behaviour has only been verified in simulation. Its safety statement is
conditional on the UNCALIBRATED maximum actual-motion multiplier; speed,
turning rate, motor deadband, transient overshoot, and interaction with real
Misty II drive commands have never been exercised on hardware.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Protocol, Tuple

from misty_agent.config import Settings, settings
from misty_agent.control.step_policy import ARRIVED, Step, plan_step
from misty_agent.perception.distance import DistanceReading
from misty_agent.robot.interface import Effect


class ReadingSource(Protocol):
    def latest_reading(self) -> Optional[DistanceReading]: ...


class RobotAdapter(Protocol):
    """The one behaviour this controller needs from `misty_agent.robot.Robot`."""

    def drive(
        self,
        *,
        linear_percent: float,
        angular_percent: float,
        duration_ms: int,
        timeout_s: float,
    ) -> Effect: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class ApproachStatus(str, Enum):
    ARRIVED = "arrived"
    #: No reading at all by the end of the wait: the person is gone.
    LOST_USER = "lost_user"
    #: Readings kept coming but none was fresh enough to act on.
    STALE_READING = "stale_reading"
    #: The source cannot say where the person is relative to the chassis.
    BEARING_UNAVAILABLE = "bearing_unavailable"
    #: The alignment budget ran out with the person still off to one side.
    ALIGNMENT_FAILED = "alignment_failed"
    #: The distance-step budget ran out before the arrival band.
    STEP_LIMIT = "step_limit"
    #: The wall-clock deadline for the whole call ran out.
    TIMEOUT = "timeout"
    DRIVE_ERROR = "drive_error"


@dataclass(frozen=True)
class MovementStep:
    """One bounded chassis motion and the fresh reading it was planned from.

    `commanded` is degrees for a turn and centimetres otherwise, always
    positive; `kind` carries the direction. The reading is the one the
    decision used, so a trace reads as distance and bearing converging.
    """

    kind: str  # "turn", "forward" or "back"
    commanded: float
    distance_cm: float
    bearing_deg: float


@dataclass(frozen=True)
class ApproachResult:
    status: ApproachStatus
    #: Every motion issued, turns included: what the Journal counts as Steps.
    steps: int
    turns: int = 0
    #: The last fresh reading, when there was one.
    distance_cm: Optional[float] = None
    bearing_deg: Optional[float] = None
    trace: Tuple[MovementStep, ...] = ()


@dataclass(frozen=True)
class _Fresh:
    distance_cm: float
    bearing_deg: Optional[float]


def _fresh_reading(
    source: ReadingSource,
    *,
    invalidation_epoch: float,
    timeout_s: float,
    max_age_s: float,
    settle_until: float,
    approach_deadline: float,
    clock: Clock,
) -> Tuple[Optional[_Fresh], bool]:
    """A median distance over fresh samples and the newest sample's bearing,
    or nothing; plus whether the last poll saw any reading at all, which is
    the difference between a stale person and a missing one."""
    deadline = min(max(clock.monotonic(), settle_until) + timeout_s, approach_deadline)
    samples: dict[float, int] = {}
    latest_bearing: Optional[float] = None
    latest_at = float("-inf")
    saw_reading = False
    while clock.monotonic() <= deadline:
        now = clock.monotonic()
        samples = {
            arrived_at: distance_cm
            for arrived_at, distance_cm in samples.items()
            if 0.0 <= now - arrived_at <= max_age_s
        }
        reading = source.latest_reading()
        saw_reading = reading is not None
        now = clock.monotonic()
        if (
            reading is not None
            and reading.frame_arrived_at > invalidation_epoch
            and 0.0 <= now - reading.frame_arrived_at <= max_age_s
        ):
            samples[reading.frame_arrived_at] = reading.distance_cm
            if reading.frame_arrived_at >= latest_at:
                latest_at = reading.frame_arrived_at
                latest_bearing = reading.bearing_deg
            if len(samples) >= 2 and now >= settle_until:
                return (
                    _Fresh(float(statistics.median(samples.values())), latest_bearing),
                    True,
                )
        remaining = deadline - clock.monotonic()
        if remaining <= 0:
            break
        clock.sleep(min(0.01, remaining))
    return None, saw_reading


def approach(
    readings: ReadingSource,
    robot: RobotAdapter,
    *,
    config: Settings = settings,
    clock: Optional[Clock] = None,
) -> ApproachResult:
    """Align the chassis to the person, then close to the arrival band, one
    bounded motion per fresh reading; return a structured public result."""
    active_clock: Clock = clock or _SystemClock()
    invalidated_at = active_clock.monotonic()
    approach_deadline = invalidated_at + config.approach_timeout_s
    settle_until = invalidated_at
    moves = 0
    turns = 0
    trace: List[MovementStep] = []
    last: Optional[_Fresh] = None

    def ended(status: ApproachStatus) -> ApproachResult:
        return ApproachResult(
            status,
            steps=moves + turns,
            turns=turns,
            distance_cm=last.distance_cm if last is not None else None,
            bearing_deg=last.bearing_deg if last is not None else None,
            trace=tuple(trace),
        )

    for _ in range(config.max_approach_steps + config.max_align_steps + 1):
        fresh, seen = _fresh_reading(
            readings,
            invalidation_epoch=invalidated_at,
            timeout_s=config.approach_reading_timeout_s,
            max_age_s=config.distance_max_age_s,
            settle_until=settle_until,
            approach_deadline=approach_deadline,
            clock=active_clock,
        )
        if fresh is None:
            if active_clock.monotonic() >= approach_deadline:
                return ended(ApproachStatus.TIMEOUT)
            return ended(
                ApproachStatus.STALE_READING if seen else ApproachStatus.LOST_USER
            )
        last = fresh
        if fresh.bearing_deg is None:
            return ended(ApproachStatus.BEARING_UNAVAILABLE)

        if abs(fresh.bearing_deg) > config.align_tolerance_deg:
            if turns >= config.max_align_steps:
                return ended(ApproachStatus.ALIGNMENT_FAILED)
            # Divided by the multiplier for the same reason a forward step is:
            # a robot that turns twice as far as told must still not swing
            # past the tolerance on the other side.
            angle_deg = (
                min(abs(fresh.bearing_deg), config.max_turn_deg)
                / config.max_actual_motion_multiplier
            )
            sign = 1 if fresh.bearing_deg > 0 else -1
            duration_ms = int(angle_deg / config.deg_per_sec_at_percent * 1000)
            kind = "turn"
            commanded = angle_deg
            linear, angular = 0, sign * config.turn_percent
        else:
            outcome = plan_step(fresh.distance_cm, config)
            if outcome is ARRIVED:
                return ended(ApproachStatus.ARRIVED)
            if not isinstance(outcome, Step) or moves >= config.max_approach_steps:
                return ended(ApproachStatus.STEP_LIMIT)
            duration_ms = int(outcome.commanded_cm / config.cm_per_sec_at_percent * 1000)
            kind = "forward" if outcome.direction > 0 else "back"
            commanded = outcome.commanded_cm
            linear, angular = outcome.direction * config.drive_percent, 0

        motion_s = duration_ms / 1000.0
        remaining_s = approach_deadline - active_clock.monotonic()
        if motion_s > remaining_s:
            return ended(ApproachStatus.TIMEOUT)
        request_timeout_s = remaining_s - motion_s
        if request_timeout_s <= 0:
            return ended(ApproachStatus.TIMEOUT)
        try:
            driven = robot.drive(
                linear_percent=linear,
                angular_percent=angular,
                duration_ms=duration_ms,
                timeout_s=request_timeout_s,
            )
        except Exception:
            return ended(ApproachStatus.DRIVE_ERROR)
        if not driven.ok:
            return ended(ApproachStatus.DRIVE_ERROR)

        trace.append(MovementStep(kind, commanded, fresh.distance_cm, fresh.bearing_deg))
        if kind == "turn":
            turns += 1
        else:
            moves += 1
        remaining_s = approach_deadline - active_clock.monotonic()
        if remaining_s <= 0:
            return ended(ApproachStatus.TIMEOUT)
        active_clock.sleep(motion_s)
        # Frames acquired during the command are invalid. The settle window
        # begins here, but fresh samples are collected during it; sleep alone
        # never stands in for timestamp freshness.
        invalidated_at = active_clock.monotonic()
        settle_until = min(
            invalidated_at + config.post_step_settle_s,
            approach_deadline,
        )

    return ended(ApproachStatus.STEP_LIMIT)

"""One bounded closed-loop approach behind a small public interface.

The caller supplies the already-running distance pipeline and robot command
adapter. Everything else — sampling, freshness epochs, aggregation, movement
conversion, settling, and error translation — stays behind :func:`approach`.

This behaviour has only been verified in simulation. Its safety statement is
conditional on the UNCALIBRATED maximum actual-motion multiplier; speed,
motor deadband, transient overshoot, and interaction with real Misty II drive
commands have never been exercised on hardware.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

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
    LOST_USER = "lost_user"
    TIMEOUT = "timeout"
    DRIVE_ERROR = "drive_error"


@dataclass(frozen=True)
class ApproachResult:
    status: ApproachStatus
    steps: int


def _fresh_median(
    source: ReadingSource,
    *,
    invalidation_epoch: float,
    timeout_s: float,
    max_age_s: float,
    settle_until: float,
    approach_deadline: float,
    clock: Clock,
) -> Optional[float]:
    deadline = min(max(clock.monotonic(), settle_until) + timeout_s, approach_deadline)
    samples: dict[float, int] = {}
    while clock.monotonic() <= deadline:
        now = clock.monotonic()
        samples = {
            arrived_at: distance_cm
            for arrived_at, distance_cm in samples.items()
            if 0.0 <= now - arrived_at <= max_age_s
        }
        reading = source.latest_reading()
        now = clock.monotonic()
        if (
            reading is not None
            and reading.frame_arrived_at > invalidation_epoch
            and 0.0 <= now - reading.frame_arrived_at <= max_age_s
        ):
            samples[reading.frame_arrived_at] = reading.distance_cm
            if len(samples) >= 2 and now >= settle_until:
                return float(statistics.median(samples.values()))
        remaining = deadline - clock.monotonic()
        if remaining <= 0:
            break
        clock.sleep(min(0.01, remaining))
    return None


def approach(
    readings: ReadingSource,
    robot: RobotAdapter,
    *,
    config: Settings = settings,
    clock: Optional[Clock] = None,
) -> ApproachResult:
    """Run one bounded approach and return a structured public result."""
    active_clock: Clock = clock or _SystemClock()
    invalidated_at = active_clock.monotonic()
    approach_deadline = invalidated_at + config.approach_timeout_s
    settle_until = invalidated_at
    completed_steps = 0

    for _ in range(config.max_approach_steps + 1):
        distance_cm = _fresh_median(
            readings,
            invalidation_epoch=invalidated_at,
            timeout_s=config.approach_reading_timeout_s,
            max_age_s=config.distance_max_age_s,
            settle_until=settle_until,
            approach_deadline=approach_deadline,
            clock=active_clock,
        )
        if distance_cm is None:
            if active_clock.monotonic() >= approach_deadline:
                return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)
            return ApproachResult(ApproachStatus.LOST_USER, steps=completed_steps)

        outcome = plan_step(distance_cm, config)
        if outcome is ARRIVED:
            return ApproachResult(ApproachStatus.ARRIVED, steps=completed_steps)
        if not isinstance(outcome, Step) or completed_steps >= config.max_approach_steps:
            return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)

        duration_ms = int(outcome.commanded_cm / config.cm_per_sec_at_percent * 1000)
        motion_s = duration_ms / 1000.0
        remaining_s = approach_deadline - active_clock.monotonic()
        if motion_s > remaining_s:
            return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)
        request_timeout_s = remaining_s - motion_s
        if request_timeout_s <= 0:
            return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)
        try:
            driven = robot.drive(
                linear_percent=outcome.direction * config.drive_percent,
                angular_percent=0,
                duration_ms=duration_ms,
                timeout_s=request_timeout_s,
            )
        except Exception:
            return ApproachResult(ApproachStatus.DRIVE_ERROR, steps=completed_steps)
        if not driven.ok:
            return ApproachResult(ApproachStatus.DRIVE_ERROR, steps=completed_steps)

        completed_steps += 1
        remaining_s = approach_deadline - active_clock.monotonic()
        if remaining_s <= 0:
            return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)
        active_clock.sleep(motion_s)
        # Frames acquired during the command are invalid. The settle window
        # begins here, but fresh samples are collected during it; sleep alone
        # never stands in for timestamp freshness.
        invalidated_at = active_clock.monotonic()
        settle_until = min(
            invalidated_at + config.post_step_settle_s,
            approach_deadline,
        )

    return ApproachResult(ApproachStatus.TIMEOUT, steps=completed_steps)

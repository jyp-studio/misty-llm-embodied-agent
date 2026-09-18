"""One bounded closed-loop approach behind a small public interface.

The caller supplies the already-running reading source for the Episode's
Interaction Target and the Robot adapter. Everything else — sampling,
freshness epochs, aggregation, alignment, movement conversion, settling, and
error translation — stays behind :func:`approach`.

## Align, then approach

A reading carries a distance and, when the source can say, a bearing: where
the person is relative to the chassis heading, positive to the left. Each
iteration takes one fresh reading and does exactly one of three things:
rotate the chassis toward the person (bounded by `max_turn_deg`, divided by
the uncalibrated motion multiplier so an over-eager robot cannot swing past
the other side of the tolerance), move one bounded distance step, or stop
with a typed status. Rotation is a chassis motion; the head's yaw plays no
part and is never read here, because a head that looks at someone is not a
base that faces them. The distance is a median over two fresh samples; the
bearing is the newest fresh sample's, unaggregated.

A reading with no bearing ends the call as `bearing_unavailable` before any
motion. The live distance pipeline reports none, so on hardware this
controller fails closed until a bearing source exists.

## Checkpoints

Before the first motion, before every motion, during every motion at
`movement_poll_s`, and again after it before re-measuring, the controller
asks two questions: has anyone asked for a stop, and does the hazard source
say the base may move. A stop ends the call as `aborted` without another
command; its owner already halted the motors. A hazard halts the motors here
and ends the call as `blocked`. A hazard source that has nothing to say, or
only something older than `hazard_max_age_s`, is `hazard_unavailable`: the
base does not move on a signal it does not have. On real hardware today that
is every call, because no hazard signal reaches this process.

This behaviour has only been verified in simulation. Its safety statement is
conditional on the UNCALIBRATED maximum actual-motion multiplier; speed,
turning rate, motor deadband, transient overshoot, and interaction with real
Misty II drive commands have never been exercised on hardware.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple

from misty_agent.agent.stop import NEVER_STOPS, Stop
from misty_agent.config import Settings, settings
from misty_agent.control.safety import NO_HAZARD_SOURCE, HazardSource
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
    #: The hazard source said the base may not move; the motors were halted.
    BLOCKED = "blocked"
    #: Someone asked for a stop; the stop's owner halted the motors.
    ABORTED = "aborted"
    #: No usable hazard reading: the base does not move on a missing signal.
    HAZARD_UNAVAILABLE = "hazard_unavailable"
    #: The wall-clock deadline for the whole call ran out.
    TIMEOUT = "timeout"
    DRIVE_ERROR = "drive_error"


class MotionKind(str, Enum):
    """What one chassis motion did. "Rotate", not "turn": a Turn is one ReAct
    iteration everywhere else in this project."""

    ROTATE = "rotate"
    FORWARD = "forward"
    BACK = "back"


@dataclass(frozen=True)
class MovementStep:
    """One bounded chassis motion and the fresh reading it was planned from.

    A rotation carries `rotate_deg`; a translation carries `move_cm`; both
    are positive, the kind says which way. The reading is the one the
    decision used, so the sequence reads as distance and bearing converging.
    """

    kind: MotionKind
    rotate_deg: Optional[float]
    move_cm: Optional[float]
    distance_cm: float
    bearing_deg: float


@dataclass(frozen=True)
class ApproachResult:
    status: ApproachStatus
    #: Every motion issued, rotations included: what the Journal counts as
    #: Steps, and what the adapter counts as drives.
    steps: int
    rotations: int = 0
    #: The last fresh reading, when there was one, with its source's caveats.
    distance_cm: Optional[float] = None
    bearing_deg: Optional[float] = None
    uncertainty: Tuple[str, ...] = ()
    #: Every motion in order. Not a Trace: that word is the harness replay's.
    motions: Tuple[MovementStep, ...] = ()
    #: Why the call ended, in words the model can act on.
    reason: str = ""

    def as_tool_result(self) -> Dict[str, Any]:
        """The public shape the model reads. Decided here, in the control
        layer, so the Tool cannot drift from what the controller means."""
        return {
            "result": self.status.value,
            "reason": self.reason,
            "steps": self.steps,
            "rotations": self.rotations,
            "distance_cm": self.distance_cm,
            "bearing_deg": self.bearing_deg,
            "uncertainty": list(self.uncertainty),
            "motions": [
                {**asdict(step), "kind": step.kind.value} for step in self.motions
            ],
        }


@dataclass(frozen=True)
class _Fresh:
    distance_cm: float
    bearing_deg: Optional[float]
    uncertainty: Tuple[str, ...]


def _duration_ms(amount: float, rate_per_s: float) -> int:
    """How long to command a motion of `amount` at the configured rate."""
    return int(amount / rate_per_s * 1000)


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
    latest_uncertainty: Tuple[str, ...] = ()
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
                latest_uncertainty = tuple(reading.uncertainty)
            if len(samples) >= 2 and now >= settle_until:
                return (
                    _Fresh(
                        float(statistics.median(samples.values())),
                        latest_bearing,
                        latest_uncertainty,
                    ),
                    True,
                )
        remaining = deadline - clock.monotonic()
        if remaining <= 0:
            break
        clock.sleep(min(0.01, remaining))
    return None, saw_reading


class _Halt(Protocol):
    def halt(self) -> Any: ...


def approach(
    readings: ReadingSource,
    robot: RobotAdapter,
    *,
    config: Settings = settings,
    clock: Optional[Clock] = None,
    stop: Stop = NEVER_STOPS,
    hazards: HazardSource = NO_HAZARD_SOURCE,
) -> ApproachResult:
    """Align the chassis to the person, then close to the arrival band, one
    bounded motion per fresh reading, stopping at the first checkpoint that
    says not to; return a structured public result."""
    active_clock: Clock = clock or _SystemClock()
    invalidated_at = active_clock.monotonic()
    approach_deadline = invalidated_at + config.approach_timeout_s
    settle_until = invalidated_at
    moves = 0
    rotations = 0
    motions: List[MovementStep] = []
    last: Optional[_Fresh] = None

    def ended(status: ApproachStatus, reason: str) -> ApproachResult:
        return ApproachResult(
            status,
            steps=moves + rotations,
            rotations=rotations,
            distance_cm=last.distance_cm if last is not None else None,
            bearing_deg=last.bearing_deg if last is not None else None,
            uncertainty=last.uncertainty if last is not None else (),
            motions=tuple(motions),
            reason=reason,
        )

    def done_so_far() -> str:
        return f"after {moves + rotations} motion(s)"

    def checkpoint(where: str) -> Optional[ApproachResult]:
        """One safety check. Returns the result that ends the call, if any."""
        if stop.requested():
            return ended(ApproachStatus.ABORTED, f"stop requested {where}, {done_so_far()}")
        hazard = hazards.latest_hazard()
        if hazard is None:
            return ended(
                ApproachStatus.HAZARD_UNAVAILABLE,
                f"no hazard reading {where}: the base does not move on a missing signal",
            )
        if (
            hazard.observed_at is not None
            and active_clock.monotonic() - hazard.observed_at > config.hazard_max_age_s
        ):
            return ended(
                ApproachStatus.HAZARD_UNAVAILABLE,
                f"hazard reading {where} is older than {config.hazard_max_age_s}s",
            )
        if hazard.blocked:
            try:
                robot.halt()  # type: ignore[attr-defined]
            except Exception:
                pass  # The refusal to move stands whether or not the halt was heard.
            return ended(ApproachStatus.BLOCKED, f"hazard reported {where}, halted {done_so_far()}")
        return None

    def wait_through(seconds: float) -> Optional[ApproachResult]:
        """Ride out a commanded motion in polls, so a stop or a hazard that
        arrives mid-motion is acted on within one poll, not at the end."""
        end = active_clock.monotonic() + seconds
        while True:
            remaining = end - active_clock.monotonic()
            if remaining <= 0:
                return None
            active_clock.sleep(min(config.movement_poll_s, remaining))
            stopped = checkpoint("during a motion")
            if stopped is not None:
                return stopped

    stopped = checkpoint("before moving")
    if stopped is not None:
        return stopped

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
                return ended(ApproachStatus.TIMEOUT, f"deadline passed {done_so_far()}")
            if seen:
                return ended(ApproachStatus.STALE_READING, f"no fresh reading {done_so_far()}")
            return ended(ApproachStatus.LOST_USER, f"no reading of the person {done_so_far()}")
        last = fresh
        if fresh.bearing_deg is None:
            return ended(
                ApproachStatus.BEARING_UNAVAILABLE,
                "the reading source cannot say where the person is relative to the chassis",
            )

        stopped = checkpoint("before a motion")
        if stopped is not None:
            return stopped

        if abs(fresh.bearing_deg) > config.align_tolerance_deg:
            if rotations >= config.max_align_steps:
                return ended(ApproachStatus.ALIGNMENT_FAILED, f"still {fresh.bearing_deg:g} degrees off after {rotations} rotations")
            # Divided by the multiplier for the same reason a forward step is:
            # a robot that rotates twice as far as told must still not swing
            # past the tolerance on the other side.
            angle_deg = (
                min(abs(fresh.bearing_deg), config.max_turn_deg)
                / config.max_actual_motion_multiplier
            )
            sign = 1 if fresh.bearing_deg > 0 else -1
            duration_ms = _duration_ms(angle_deg, config.deg_per_sec_at_percent)
            motion = MovementStep(
                MotionKind.ROTATE, angle_deg, None, fresh.distance_cm, fresh.bearing_deg
            )
            linear, angular = 0, sign * config.turn_percent
        else:
            outcome = plan_step(fresh.distance_cm, config)
            if outcome is ARRIVED:
                return ended(ApproachStatus.ARRIVED, f"within the arrival band {done_so_far()}")
            if not isinstance(outcome, Step) or moves >= config.max_approach_steps:
                return ended(ApproachStatus.STEP_LIMIT, f"step budget spent {done_so_far()}")
            duration_ms = _duration_ms(outcome.commanded_cm, config.cm_per_sec_at_percent)
            motion = MovementStep(
                MotionKind.FORWARD if outcome.direction > 0 else MotionKind.BACK,
                None, outcome.commanded_cm, fresh.distance_cm, fresh.bearing_deg,
            )
            linear, angular = outcome.direction * config.drive_percent, 0

        motion_s = duration_ms / 1000.0
        remaining_s = approach_deadline - active_clock.monotonic()
        if motion_s > remaining_s:
            return ended(ApproachStatus.TIMEOUT, f"not enough time left for a motion {done_so_far()}")
        request_timeout_s = remaining_s - motion_s
        if request_timeout_s <= 0:
            return ended(ApproachStatus.TIMEOUT, f"not enough time left for a motion {done_so_far()}")
        try:
            driven = robot.drive(
                linear_percent=linear,
                angular_percent=angular,
                duration_ms=duration_ms,
                timeout_s=request_timeout_s,
            )
        except Exception:
            return ended(ApproachStatus.DRIVE_ERROR, f"the robot raised on a drive command {done_so_far()}")
        if not driven.ok:
            return ended(ApproachStatus.DRIVE_ERROR, f"the robot refused a drive command {done_so_far()}")

        motions.append(motion)
        if motion.kind is MotionKind.ROTATE:
            rotations += 1
        else:
            moves += 1
        remaining_s = approach_deadline - active_clock.monotonic()
        if remaining_s <= 0:
            return ended(ApproachStatus.TIMEOUT, f"deadline passed {done_so_far()}")
        stopped = wait_through(motion_s)
        if stopped is not None:
            return stopped
        stopped = checkpoint("after a motion")
        if stopped is not None:
            return stopped
        # Frames acquired during the command are invalid. The settle window
        # begins here, but fresh samples are collected during it; sleep alone
        # never stands in for timestamp freshness.
        invalidated_at = active_clock.monotonic()
        settle_until = min(
            invalidated_at + config.post_step_settle_s,
            approach_deadline,
        )

    return ended(ApproachStatus.STEP_LIMIT, f"step budget spent {done_so_far()}")

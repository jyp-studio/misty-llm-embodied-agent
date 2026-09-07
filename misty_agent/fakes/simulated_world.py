"""A room with a person in it, for a robot that does not exist.

`RecordingCommands` answers drive commands and remembers them; it does not
pretend the robot went anywhere. This does: a successful `drive/time` moves
the observed distance by the distance that command asked for. That is the
smallest simulation in which `approach` can actually converge, which makes it
the smallest one in which an Episode can be watched end to end.

It lives here rather than in a test file because two callers need it and
`PLAN.md` §10 allows one definition. It was written for `tests/test_approach.py`
in M5, and `tests/test_react.py` and `tests/test_llm_live.py` reached across
to import it; M8 #04's entry point is the third caller and the first one in
production code, which cannot import from `tests/` at all. `FakeClock` made
the same journey in M7 #05, for the same reason.

## What it deliberately does not model

Only the adapter boundary. It reads `timeMs` back off the command and turns it
into centimetres with the same constant the control layer used — it does not
reproduce the step formula, the settle wait, or the freshness rules. A double
that re-implemented the controller would agree with the controller by
construction, and `tests/test_approach.py` would be testing arithmetic against
itself.

`actual_motion_multiplier` is how much of the commanded distance the robot
really travels. `PLAN.md` §12 measured the band this has to tolerate; the
default here is 1.0 — a robot that goes exactly as far as it was told —
because a simulation is not the place to invent an error the hardware would
have supplied.
"""

from __future__ import annotations

from misty_agent.config import Settings
from misty_agent.fakes.fake_robot import RecordingCommands
from misty_agent.perception.distance import DistanceReading


def a_reading(distance_cm: int, arrived_at: float) -> DistanceReading:
    """A reading whose frame arrived and was detected at the same instant.

    The gap between those two is what `harness/` exists to measure. Nothing
    that uses this double is measuring it, so collapsing it here keeps the
    fake from implying a precision it does not have.
    """
    return DistanceReading(
        distance_cm=distance_cm,
        frame_arrived_at=arrived_at,
        detected_at=arrived_at,
    )


class MovingWorld(RecordingCommands):
    """A public reading/robot seam with an explicit drive-distance error.

    This models only the adapter boundary: a successful ``drive/time`` request
    changes the observed distance by the duration-derived commanded distance
    times ``actual_motion_multiplier``.  It deliberately does not reproduce
    the controller's step formula.
    """

    def __init__(
        self,
        clock,
        *,
        start_cm: float,
        actual_motion_multiplier: float = 1.0,
        config: Settings,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._distance_cm = start_cm
        self._actual_motion_multiplier = actual_motion_multiplier
        self._config = config
        self.closest_cm = start_cm
        self.directions: list[int] = []

    @property
    def distance_cm(self) -> float:
        return self._distance_cm

    def latest_reading(self):
        self._clock.sleep(0.001)
        return a_reading(round(self._distance_cm), self._clock.monotonic())

    def drive_time(self, linearVelocity, angularVelocity, timeMs, timeout):
        response = super().drive_time(
            linearVelocity=linearVelocity,
            angularVelocity=angularVelocity,
            timeMs=timeMs,
            timeout=timeout,
        )
        commanded_cm = timeMs / 1000 * self._config.cm_per_sec_at_percent
        direction = 1 if linearVelocity > 0 else -1
        self.directions.append(direction)
        self._distance_cm -= (
            direction * commanded_cm * self._actual_motion_multiplier
        )
        self.closest_cm = min(self.closest_cm, self._distance_cm)
        return response

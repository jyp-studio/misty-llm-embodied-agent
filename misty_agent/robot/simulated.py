"""A Misty that exists only as state, in a room with one person in it.

Behaviours change a pose, a chest light, what was last said, and the
distance the perception side reports, so the next Snapshot and Observation
see the consequence rather than a command echo. It was `MovingWorld` before
ticket 09; the drive model is unchanged and deliberately small.

## What it deliberately does not model

Only the adapter boundary. `drive` turns the commanded duration into
centimetres with the same constant the control layer used — it does not
reproduce the step formula, the settle wait, or the freshness rules. A
double that re-implemented the controller would agree with the controller by
construction, and the controller tests would be testing arithmetic against
itself.

`actual_motion_multiplier` is how much of the commanded distance the robot
really travels. `PLAN.md` §12 measured the band this has to tolerate; the
default is 1.0 because a simulation is not the place to invent an error the
hardware would have supplied.

`failing` names behaviours, by their method names, that answer with a failed
Effect and change no state, so the error paths above this — the Observation
that says `ok: false`, the controller's `drive_error` — actually execute.

`drive` with an angular component turns the chassis; with a linear one it
moves the base along its heading through a relative polar model of where the
person stands. Turning rate and travel speed are the same UNCALIBRATED
constants the controller plans with. No hazard, obstacle or floor is
modelled.
"""

from __future__ import annotations

import math
from dataclasses import asdict, replace
from typing import Iterable, Optional, Tuple

from misty_agent.config import Settings
from misty_agent.perception.distance import DistanceReading
from misty_agent.robot.interface import Effect, RobotPose


SIMULATED_BEARING = "simulated relative bearing, not a camera measurement"


def a_reading(
    distance_cm: int,
    arrived_at: float,
    bearing_deg: Optional[float] = 0.0,
    uncertainty: Tuple[str, ...] = (SIMULATED_BEARING,),
) -> DistanceReading:
    """A reading whose frame arrived and was detected at the same instant.

    The gap between those two is what `harness/` exists to measure. Nothing
    that uses this simulation is measuring it, so collapsing it here keeps
    the simulation from implying a precision it does not have. The bearing
    defaults to straight ahead: a simulated scenario states its alignment
    explicitly rather than leaving the controller to guess.
    """
    return DistanceReading(
        distance_cm=distance_cm,
        frame_arrived_at=arrived_at,
        detected_at=arrived_at,
        bearing_deg=bearing_deg,
        uncertainty=uncertainty,
    )


class SimulatedMistyAdapter:
    """The Robot interface and the reading source, as one object, because a
    simulated room is one thing: driving changes what is measured."""

    def __init__(
        self,
        clock,
        *,
        start_cm: Optional[float],
        config: Settings,
        bearing_deg: float = 0.0,
        actual_motion_multiplier: float = 1.0,
        failing: Iterable[str] = (),
    ) -> None:
        self._clock = clock
        self._config = config
        self._actual_motion_multiplier = actual_motion_multiplier
        self._failing = frozenset(failing)
        #: `None` is an empty room: the robot is real, nobody is measured.
        self._distance_cm = start_cm
        #: The person relative to the chassis heading, positive to the left.
        self._bearing_deg = float(bearing_deg)
        #: Where the chassis faces, degrees counter-clockwise from its start.
        self.heading_deg = 0.0
        self.closest_cm = start_cm
        self.directions: list[int] = []
        #: Signed degrees of each commanded turn, as actually turned.
        self.turns: list[float] = []
        self.pose = RobotPose()
        self.speech: Optional[str] = None
        self.sound: Optional[Tuple[str, int]] = None
        self.halted = False

    def as_facts(self) -> dict:
        """The simulation's current state as JSON data: not a log."""
        return {
            "pose": asdict(self.pose),
            "speech": self.speech,
            "sound": list(self.sound) if self.sound is not None else None,
            "halted": self.halted,
            "distance_cm": self._distance_cm,
            "heading_deg": round(self.heading_deg, 2),
            "target": (
                {
                    "distance_cm": round(self._distance_cm, 1),
                    "bearing_deg": round(self._bearing_deg, 2),
                }
                if self._distance_cm is not None
                else None
            ),
        }

    @property
    def target_bearing_deg(self) -> float:
        return self._bearing_deg

    # ---------- what perception sees ----------

    @property
    def distance_cm(self) -> Optional[float]:
        return self._distance_cm

    def latest_reading(self) -> Optional[DistanceReading]:
        if self._distance_cm is None:
            return None
        self._clock.sleep(0.001)
        return a_reading(
            round(self._distance_cm),
            self._clock.monotonic(),
            bearing_deg=round(self._bearing_deg, 2),
        )

    # ---------- the Robot interface ----------

    def _attempt(self, behaviour: str) -> Optional[Effect]:
        if behaviour in self._failing:
            return Effect(ok=False, detail=f"simulated {behaviour} failure")
        return None

    def speak(self, text: str) -> Effect:
        refused = self._attempt("speak")
        if refused:
            return refused
        self.speech = text
        return Effect(ok=True)

    def display_image(self, image: str) -> Effect:
        refused = self._attempt("display_image")
        if refused:
            return refused
        self.pose = replace(self.pose, expression=image)
        return Effect(ok=True)

    def move_arms(self, left_deg: float, right_deg: float) -> Effect:
        refused = self._attempt("move_arms")
        if refused:
            return refused
        self.pose = replace(self.pose, arms=(float(left_deg), float(right_deg)))
        return Effect(ok=True)

    def move_head(self, pitch_deg: float, roll_deg: float, yaw_deg: float) -> Effect:
        refused = self._attempt("move_head")
        if refused:
            return refused
        self.pose = replace(
            self.pose, head=(float(pitch_deg), float(roll_deg), float(yaw_deg))
        )
        return Effect(ok=True)

    def change_led(self, red: int, green: int, blue: int) -> Effect:
        refused = self._attempt("change_led")
        if refused:
            return refused
        self.pose = replace(self.pose, led=(int(red), int(green), int(blue)))
        return Effect(ok=True)

    def play_audio(self, sound: str, volume: int) -> Effect:
        refused = self._attempt("play_audio")
        if refused:
            return refused
        self.sound = (sound, int(volume))
        return Effect(ok=True)

    def drive(
        self,
        *,
        linear_percent: float,
        angular_percent: float,
        duration_ms: int,
        timeout_s: float,
    ) -> Effect:
        refused = self._attempt("drive")
        if refused:
            return refused
        seconds = duration_ms / 1000
        if angular_percent:
            # A turn: the chassis heading changes and the person's relative
            # bearing changes by the same amount the other way. The head is
            # untouched, which is the whole point.
            turned = (
                (1 if angular_percent > 0 else -1)
                * seconds * self._config.deg_per_sec_at_percent
                * self._actual_motion_multiplier
            )
            self.heading_deg += turned
            self._bearing_deg -= turned
            self.turns.append(turned)
            return Effect(ok=True)
        commanded_cm = seconds * self._config.cm_per_sec_at_percent
        direction = 1 if linear_percent > 0 else -1
        self.directions.append(direction)
        if self._distance_cm is not None:
            travelled = direction * commanded_cm * self._actual_motion_multiplier
            # Relative polar to relative Cartesian, move along the heading,
            # and back: the person stays where they are while the base moves.
            bearing = math.radians(self._bearing_deg)
            x = self._distance_cm * math.cos(bearing) - travelled
            y = self._distance_cm * math.sin(bearing)
            self._distance_cm = math.hypot(x, y)
            self._bearing_deg = math.degrees(math.atan2(y, x))
            assert self.closest_cm is not None
            self.closest_cm = min(self.closest_cm, self._distance_cm)
        return Effect(ok=True)

    def halt(self) -> Effect:
        refused = self._attempt("halt")
        if refused:
            return refused
        self.halted = True
        return Effect(ok=True)


__all__ = ["SimulatedMistyAdapter", "a_reading"]

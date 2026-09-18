"""The one Robot interface Tools and controllers depend on.

Behaviours, not requests. A Tool says `move_head(pitch, roll, yaw)` and gets
back an `Effect`; whether that became `POST /api/head` with `units: degrees`
or a change to a simulated pose is the adapter's business, and nothing above
this line sees a status code, a JSON body or a vendor parameter name.

Two adapters implement it (`real.py`, `simulated.py`). There is deliberately
no third one that records calls: the Journal, written by the ReAct loop and
Tool dispatch, is the record of what the agent did, and a second log would be
a second place for that story to disagree with itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple


@dataclass(frozen=True)
class Effect:
    """What one behaviour came back as. `ok` is what a Tool result carries;
    `detail` is a short reason when it did not, never vendor payload."""

    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class RobotPose:
    """What the robot looks like at one moment.

    The defaults are the pose every Tool assumes it starts from: arms down,
    head level and forward, chest light off, neutral face.
    """

    expression: str = "neutral"
    led: Tuple[int, int, int] = (0, 0, 0)
    #: pitch, roll, yaw — the three `move_head` takes, in that order.
    head: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: left, right — 90 is down, which is where `move_arms` rests them.
    arms: Tuple[float, float] = (90.0, 90.0)


class Robot(Protocol):
    def speak(self, text: str) -> Effect: ...

    def display_image(self, image: str) -> Effect: ...

    def move_arms(self, left_deg: float, right_deg: float) -> Effect: ...

    def move_head(self, pitch_deg: float, roll_deg: float, yaw_deg: float) -> Effect: ...

    def change_led(self, red: int, green: int, blue: int) -> Effect: ...

    def play_audio(self, sound: str, volume: int) -> Effect: ...

    def drive(
        self,
        *,
        linear_percent: float,
        angular_percent: float,
        duration_ms: int,
        timeout_s: float,
    ) -> Effect: ...

    def halt(self) -> Effect: ...


__all__ = ["Effect", "Robot", "RobotPose"]

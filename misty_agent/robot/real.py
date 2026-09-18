"""Behaviours as Misty II REST requests. **hardware-unverified.**

This project has no Misty II and never will (`PLAN.md` §1). Every request
shape here follows the vendor REST reference and is pinned by the contract
tests through `RecordingCommands`; nothing about how the robot answers —
behaviour, latency, calibration, reliability — has ever been observed.
"""

from __future__ import annotations

from typing import Any

from misty_agent.drivers.robot_commands import RobotCommands
from misty_agent.robot.interface import Effect


def _effect(response: Any) -> Effect:
    """A vendor answer as an Effect. Exceptions are the caller's to see."""
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and 200 <= status < 300:
        return Effect(ok=True)
    return Effect(ok=False, detail=f"robot answered {status}")


class RealMistyAdapter:
    """One behaviour, one documented request. hardware-unverified."""

    def __init__(self, commands: RobotCommands) -> None:
        self._commands = commands

    @property
    def commands(self) -> RobotCommands:
        """The vendor transport, for wiring that needs the same connection
        (the AV session) and for tests that pin request shapes."""
        return self._commands

    def speak(self, text: str) -> Effect:
        return _effect(self._commands.speak(text=text))

    def display_image(self, image: str) -> Effect:
        return _effect(self._commands.display_image(fileName=image))

    def move_arms(self, left_deg: float, right_deg: float) -> Effect:
        return _effect(
            self._commands.move_arms(
                leftArmPosition=left_deg, rightArmPosition=right_deg, units="degrees"
            )
        )

    def move_head(self, pitch_deg: float, roll_deg: float, yaw_deg: float) -> Effect:
        return _effect(
            self._commands.move_head(
                pitch=pitch_deg, roll=roll_deg, yaw=yaw_deg, units="degrees"
            )
        )

    def change_led(self, red: int, green: int, blue: int) -> Effect:
        return _effect(self._commands.change_led(red=red, green=green, blue=blue))

    def play_audio(self, sound: str, volume: int) -> Effect:
        return _effect(self._commands.play_audio(fileName=sound, volume=volume))

    def drive(
        self,
        *,
        linear_percent: float,
        angular_percent: float,
        duration_ms: int,
        timeout_s: float,
    ) -> Effect:
        return _effect(
            self._commands.drive_time(
                linearVelocity=linear_percent,
                angularVelocity=angular_percent,
                timeMs=duration_ms,
                timeout=timeout_s,
            )
        )

    def halt(self) -> Effect:
        return _effect(self._commands.halt())


__all__ = ["RealMistyAdapter"]

"""The Robot interface and its two adapters.

`RealMistyAdapter` turns behaviours into vendor requests and is
hardware-unverified throughout. `SimulatedMistyAdapter` turns them into
state the next Snapshot can see. Nothing here records what happened; the
Journal does.
"""

from misty_agent.robot.interface import Effect, Robot, RobotPose
from misty_agent.robot.real import RealMistyAdapter
from misty_agent.robot.simulated import SimulatedMistyAdapter, a_reading

__all__ = [
    "Effect",
    "RealMistyAdapter",
    "Robot",
    "RobotPose",
    "SimulatedMistyAdapter",
    "a_reading",
]

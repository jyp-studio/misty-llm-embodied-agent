"""Stand-ins that let the whole system run, and be tested, without a robot.

No Misty II is available to this project (PLAN.md §1), so these are not a
convenience — they are the only way any of this code has ever executed.
"""

from misty_agent.fakes.fake_robot import (
    FakeClock,
    RecordedRequest,
    RecordingCommands,
)
from misty_agent.fakes.simulated_world import (
    NOBODY_THERE,
    EmptyRoom,
    MovingWorld,
    a_reading,
)

__all__ = [
    "NOBODY_THERE",
    "EmptyRoom",
    "FakeClock",
    "MovingWorld",
    "RecordedRequest",
    "RecordingCommands",
    "a_reading",
]

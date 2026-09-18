"""An emergency stop that can arrive from any thread, at any moment.

`CONTEXT.md` defines an Episode as having **guaranteed bounded termination**,
and `PLAN.md` §4 calls that the strongest property this system has. Every
other path to the end of an Episode is the loop's own: the model chooses
`done`, or the Turn cap runs out. This is the only one that comes from
outside, so it is the only one that can falsify the guarantee rather than
demonstrate it.

## Why the stopping thread writes the record itself

The timestamp has to be **when the foot hit the bumper**, not when the loop
next looked. The gap between those two is the interrupt latency — the thing
worth measuring — and a design that recorded the stop on the main thread
would overwrite the measurement with its own delay. This is the reason ticket
02 gave the Journal a lock and let any thread write, instead of posting to a
queue the loop drains.

So the order here is: **record, then halt.** Halting is an HTTP round trip;
doing it first would fold the robot's response time into a number that is
supposed to be about ours.

## Halting is `halt`, not `stop`

`POST /halt` stops every motor controller. `POST /drive/stop` stops the base
and leaves an arm mid-sweep, which is not what "nothing is still moving"
means when someone has put their foot on the bumper.

Whether the motors *actually* stop is not something this project can claim:
no Misty has ever run this code (`PLAN.md` §8). What is claimed is that the
request is made, before anything else, and that the Episode ends afterwards
either way — a halt that fails must not also cost us the termination
guarantee.
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Protocol

from misty_agent.agent.journal import Journal, StopRequested


class Stop(Protocol):
    """What the ReAct loop needs to know: has someone asked us to stop."""

    def requested(self) -> bool: ...


class NeverStops:
    """The stop for an Episode nobody can interrupt.

    A null object rather than an `Optional`, so the loop has one shape to read
    instead of a `None` check at each of the two places it checks.
    """

    def requested(self) -> bool:
        return False


NEVER_STOPS = NeverStops()


class EmergencyStop:
    """The foot bumper, or anything else with the authority to say stop."""

    def __init__(self, journal: Journal, robot: Any) -> None:
        self._journal = journal
        self._robot = robot
        self._lock = threading.Lock()
        self._source: Optional[str] = None
        #: Whether the halt request came back without raising. Read by tests
        #: and by anyone deciding whether to trust that the robot is still.
        self.halted = False

    def request(self, source: str) -> bool:
        """Ask for everything to stop. Safe to call from any thread.

        Returns whether this call was the one that did it — a second press of
        the same bumper is not a second stop, and a Journal with two
        `stop_requested` records for one interruption would make the interrupt
        latency ambiguous.
        """
        with self._lock:
            if self._source is not None:
                return False
            self._source = source

        # Before the halt, deliberately: see the module docstring.
        self._journal.record(StopRequested, source=source)
        try:
            self.halted = self._robot.halt().ok
        except Exception:
            # Swallowed on purpose, and this is the one place in the project
            # where that is right. This runs on the sensor's thread, where
            # nothing would catch it; and the Episode still has to end. A
            # failed halt is worse than a successful one, but a failed halt
            # that also loses the termination guarantee is worse than both.
            self.halted = False
        return True

    def requested(self) -> bool:
        with self._lock:
            return self._source is not None

    @property
    def source(self) -> Optional[str]:
        with self._lock:
            return self._source

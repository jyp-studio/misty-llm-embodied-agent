"""The only way an Episode ends that the loop did not decide.

`CONTEXT.md` defines an Episode as having guaranteed bounded termination, and
every other route to the end is the loop's own — the model chooses `done`, or
the Turn cap runs out. Both of those demonstrate the guarantee. This one is
the only one that could falsify it, which is why it gets its own file.

Two properties are load-bearing and neither is obvious:

**The record's timestamp is when the foot hit the bumper.** Not when the loop
next looked. The difference between those is the interrupt latency, and
`PLAN.md` §15.3 says that is exactly why `stop_requested` and
`episode_finished` are two records rather than one.

**A halt that fails must not also cost the termination guarantee.** A stop
that leaves the robot moving is bad; a stop that leaves the robot moving *and*
the Episode running is worse.
"""

from __future__ import annotations

import threading
import time

import pytest

from misty_agent.agent.journal import Journal, StopRequested
from misty_agent.agent.stop import NEVER_STOPS, EmergencyStop
from misty_agent.fakes import FakeClock, RecordingCommands


class RefusesToHalt(RecordingCommands):
    def halt(self, motorMask=None):
        raise RuntimeError("the motor controller did not answer")


def a_journal(clock=None):
    return Journal(episode_id="ep-1", clock=clock or FakeClock())


# ---------------------------------------------------------------------------
# What a stop does
# ---------------------------------------------------------------------------

def test_a_stop_is_recorded_with_the_source_that_asked_for_it():
    journal = a_journal()
    robot = RecordingCommands()

    EmergencyStop(journal, robot).request("foot_bumper")

    recorded = [r for r in journal.records if isinstance(r, StopRequested)]
    assert len(recorded) == 1
    assert recorded[0].source == "foot_bumper"


def test_a_stop_halts_every_motor_and_not_just_the_wheels():
    """`POST /drive/stop` leaves an arm mid-sweep. Someone with a foot on the
    bumper means everything, so it is `POST /halt`."""
    robot = RecordingCommands()

    EmergencyStop(a_journal(), robot).request("foot_bumper")

    assert "halt" in robot.endpoints
    assert "drive/stop" not in robot.endpoints


def test_the_stop_is_recorded_before_the_halt_is_asked_for():
    """The timestamp is meant to be when the stop arrived, and halting is an
    HTTP round trip. Doing it first would fold the robot's response time into
    a number that is about ours.
    """
    order = []

    class Watching(RecordingCommands):
        def halt(self, motorMask=None):
            order.append("halt")
            return super().halt(motorMask)

    class Noting:
        def receive(self, record):
            if isinstance(record, StopRequested):
                order.append("recorded")

    journal = Journal(
        episode_id="ep-1", clock=FakeClock(), subscribers=(Noting(),)
    )

    EmergencyStop(journal, Watching()).request("foot_bumper")

    assert order == ["recorded", "halt"]


def test_the_stop_is_visible_the_moment_it_is_requested():
    stop = EmergencyStop(a_journal(), RecordingCommands())

    assert not stop.requested()
    stop.request("foot_bumper")
    assert stop.requested()
    assert stop.source == "foot_bumper"


# ---------------------------------------------------------------------------
# Pressing twice is not stopping twice
# ---------------------------------------------------------------------------

def test_a_second_press_does_not_add_a_second_record():
    """Two `stop_requested` records for one interruption would make the
    interrupt latency ambiguous — a reader could not tell which one the
    Episode's ending was measured from."""
    journal = a_journal()
    stop = EmergencyStop(journal, RecordingCommands())

    assert stop.request("foot_bumper") is True
    assert stop.request("foot_bumper") is False
    assert stop.request("someone_else") is False

    assert sum(isinstance(r, StopRequested) for r in journal.records) == 1


def test_the_first_source_is_the_one_that_is_kept():
    stop = EmergencyStop(a_journal(), RecordingCommands())

    stop.request("foot_bumper")
    stop.request("cap_touch")

    assert stop.source == "foot_bumper"


# ---------------------------------------------------------------------------
# A halt that fails
# ---------------------------------------------------------------------------

def test_a_halt_that_fails_still_leaves_the_stop_requested():
    """This is the property the ReAct loop depends on. A halt that raised and
    took the flag with it would leave the Episode running as well as the
    motors."""
    journal = a_journal()
    stop = EmergencyStop(journal, RefusesToHalt())

    assert stop.request("foot_bumper") is True

    assert stop.requested()
    assert stop.halted is False
    assert sum(isinstance(r, StopRequested) for r in journal.records) == 1


def test_a_halt_that_works_says_so():
    """The negative control: `halted` would be useless if it were never True."""
    stop = EmergencyStop(a_journal(), RecordingCommands())

    stop.request("foot_bumper")

    assert stop.halted is True


# ---------------------------------------------------------------------------
# Any thread may ask
# ---------------------------------------------------------------------------

def _yield_on_every_line(frame, event, arg):
    """A trace hook that hands the GIL over between bytecodes.

    Without it this test cannot see the race it is about. Eight threads
    released from a barrier almost never interleave between the `if` and the
    assignment inside `request()` — a version with no lock at all passes a
    plain barrier race, and passes it with the switch interval at 1 ns too
    (both checked). Forcing a yield on every line makes the window wide enough
    that a lockless `request` returns True twice, which is the whole point.
    """
    if event == "line":
        time.sleep(0)
    return _yield_on_every_line


def test_two_threads_cannot_both_win_the_same_stop():
    """The bumper is one sensor, but the event stream is not one thread — and
    a debounce is not a lock.

    Two winners means two `stop_requested` records for one interruption, and
    then the interrupt latency has no single moment to be measured from
    (`PLAN.md` §15.3).
    """
    for _ in range(200):
        journal = a_journal()
        stop = EmergencyStop(journal, RecordingCommands())
        ready = threading.Barrier(6)
        won = []
        counting = threading.Lock()

        def press():
            threading.settrace(_yield_on_every_line)
            ready.wait()
            if stop.request("foot_bumper"):
                with counting:
                    won.append(threading.current_thread().name)

        threads = [threading.Thread(target=press) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(won) == 1, won
        assert sum(isinstance(r, StopRequested) for r in journal.records) == 1


# ---------------------------------------------------------------------------
# The Episode nobody can interrupt
# ---------------------------------------------------------------------------

def test_the_null_stop_never_reports_one():
    """A null object rather than an `Optional`, so the loop reads one shape at
    both of the places it checks."""
    assert NEVER_STOPS.requested() is False

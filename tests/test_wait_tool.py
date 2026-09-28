"""`wait`: Misty keeping still for as long as somebody asked it to.

Added for "count three seconds and tell me when time's up" (PLAN.md §16.67):
`listen` waits for an answer, not for a clock, and nothing else waits at all.
The length is the model's to choose because it is the person's request, not
a motion — nothing moves while it runs — and it is bounded so that a
somebody who changes their mind is not ignored for long. Only a stop cuts it
short; speech heard meanwhile reaches the model on the snapshot afterwards.
"""

from __future__ import annotations

import pytest

from misty_agent.agent.journal import Journal
from misty_agent.agent.tools import WAIT_MAX_S, ToolContext, build_registry, dispatch
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter


class StopAt:
    def __init__(self, clock, at_s):
        self._clock, self._at_s = clock, at_s

    def requested(self):
        return self._clock.monotonic() >= self._at_s


def waits(seconds, *, stop=None):
    clock = FakeClock()
    commands = RecordingCommands()
    ctx = ToolContext(
        robot=RealMistyAdapter(commands), readings=None, config=Settings(),
        clock=clock, **({"stop": stop(clock)} if stop else {}),
    )
    began = clock.monotonic()
    outcome = dispatch(
        build_registry(), "wait", {"seconds": seconds}, ctx,
        Journal(episode_id="ep-1"), turn=1,
    )
    return outcome, clock.monotonic() - began, commands


def test_wait_is_registered_and_does_not_end_the_episode():
    registry = build_registry()

    assert "wait" in registry.names()
    assert not registry.get("wait").ends_episode


def test_the_model_is_told_the_bounds_in_whole_seconds():
    schema = next(
        s for s in build_registry().schemas() if s["function"]["name"] == "wait"
    )
    seconds = schema["function"]["parameters"]["properties"]["seconds"]

    assert seconds["type"] == "integer"
    assert (seconds["minimum"], seconds["maximum"]) == (1, WAIT_MAX_S)


def test_it_waits_as_long_as_asked_and_tells_the_robot_nothing():
    outcome, elapsed, commands = waits(3)

    assert outcome.accepted
    assert outcome.result == {"ending": "elapsed", "waited_s": 3.0}
    assert elapsed == pytest.approx(3.0, abs=0.01)
    assert commands.requests == []


@pytest.mark.parametrize("seconds", [0, WAIT_MAX_S + 1])
def test_a_length_outside_the_bounds_is_refused_before_any_waiting(seconds):
    outcome, elapsed, _ = waits(seconds)

    assert not outcome.accepted
    assert elapsed == 0.0


def test_a_stop_cuts_it_short_and_says_so():
    outcome, elapsed, _ = waits(10, stop=lambda clock: StopAt(clock, 2.0))

    assert outcome.result["ending"] == "stopped"
    assert 2.0 <= outcome.result["waited_s"] < 10.0
    assert elapsed < 10.0

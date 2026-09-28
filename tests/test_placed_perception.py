"""A scripted example with no camera still has somebody standing there.

A text script places its person in the simulated room, and the Snapshot
reports them from that placement. Looking at them used to answer "no visual
observation is available" and mark the target lost, so a model that checked
on the person it had just driven up to was told they were gone while the
Snapshot beside it said they were 67cm away — and a recording said so out
loud. Looking now reports the same placement, and says it is one.
"""

from __future__ import annotations

from misty_agent.acceptance import run_fixture
from misty_agent.agent.journal import Observation, ToolCalled
from misty_agent.agent.react import Decision


class Calls:
    """A stand-in model that calls the given Tools in order."""

    def __init__(self, *tools):
        self._tools = list(tools)

    def decide(self, working_context, tools):
        tool = self._tools.pop(0)
        return Decision(
            tool, {}, 1, 1, tool_call_id=f"call-{len(self._tools)}", note=f"Try {tool}."
        )


def looked(run, tool):
    """Each observation that answered `tool`."""
    seen, last = [], None
    for episode in run.result.episodes:
        for record in episode.journal.records:
            if isinstance(record, ToolCalled):
                last = record.tool
            elif isinstance(record, Observation) and last == tool:
                seen.append(record)
    return seen


def test_looking_at_a_placed_person_sees_them_where_the_snapshot_does():
    run = run_fixture(
        "greeting", "come-closer", model=Calls("approach", "observe_target", "done")
    )

    (observation,) = looked(run, "observe_target")
    result = observation.result

    assert result["ending"] == "observed"
    assert result["facts"]["distance_cm"] == observation.snapshot.distance_cm
    assert result["target"]["state"] == "visible"
    assert any("simulated" in reason for reason in result["uncertainty"])


def test_a_closer_inspection_of_a_placed_person_sees_them_too():
    run = run_fixture(
        "greeting", "come-closer", model=Calls("inspect_scene", "done")
    )

    (observation,) = looked(run, "inspect_scene")

    assert observation.result["ending"] == "observed"
    assert observation.result["cost"] == "expensive"


def test_somebody_who_has_left_the_placement_is_not_seen():
    """The target-lost script has them walk off during the approach; looking
    afterwards must not bring them back."""
    run = run_fixture(
        "greeting",
        "come-closer-target-lost",
        model=Calls("approach", "observe_target", "done"),
    )

    (observation,) = looked(run, "observe_target")

    assert observation.result["ending"] == "unavailable"
    assert observation.result["target"]["state"] == "lost"

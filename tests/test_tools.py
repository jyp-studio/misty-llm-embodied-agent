"""The Tool registry: what the model may ask for, and what it may not.

A Tool is the agent's whole vocabulary of action (`CONTEXT.md`). This module
decides two things about that vocabulary and they are the same decision:
**what the model is told it may send**, and **what actually gets through**.
They are the same because both come from one type. A hand-written schema
beside a hand-written validator is two copies of one fact, and `PLAN.md` §10
already recorded what happens to those.

The other thing guarded here is the layering claim (`PLAN.md` §4): the model
decides *whether* to approach, the control layer decides *how far*. A Tool
whose arguments named a velocity or a drive duration would make that claim
false, so the registry refuses to hold one.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from misty_agent.agent.journal import Journal
from misty_agent.agent.tools import (
    ToolContext,
    ToolRegistry,
    dispatch,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


def a_journal():
    return Journal("ep-1", clock=FakeClock())


def a_context():
    return ToolContext(robot=None, readings=None)


@pytest.fixture
def registry():
    return ToolRegistry()


class HeadArgs(BaseModel):
    """A stand-in for the real move_head, which is ticket 05."""

    pitch: int = Field(ge=-40, le=26, description="degrees, down is negative")


class DriveArgs(BaseModel):
    """What a Tool must never be allowed to take."""

    linearVelocity: int = Field(ge=-100, le=100)


# ---------------------------------------------------------------------------
# Registering
# ---------------------------------------------------------------------------

def test_a_tool_is_registered_with_one_function_and_one_argument_type(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True, "pitch": args.pitch}

    assert registry.names() == ("nod",)


def test_adding_a_tool_does_not_require_touching_the_dispatcher(registry):
    """The registry is a dict, not a switch.

    `PLAN.md` §4: adding a Tool is a function and an argument type, and the
    ReAct loop does not change.
    """
    @registry.tool("first", "One.")
    def first(args: HeadArgs, ctx: ToolContext):
        return {"which": 1}

    @registry.tool("second", "Two.")
    def second(args: HeadArgs, ctx: ToolContext):
        return {"which": 2}

    journal = a_journal()
    assert dispatch(registry, "second", {"pitch": 0}, a_context(), journal, turn=1).result == {
        "which": 2
    }


def test_two_tools_cannot_share_a_name(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    with pytest.raises(ValueError, match="already"):

        @registry.tool("nod", "Nod differently.")
        def nod_again(args: HeadArgs, ctx: ToolContext):
            return {}


def test_a_tool_must_declare_an_argument_type(registry):
    """Without one there is nothing to generate a schema from, and nothing to
    validate against — the two things this registry exists for.
    """
    with pytest.raises(TypeError, match="argument type"):

        @registry.tool("vague", "No idea.")
        def vague(args, ctx):
            return {}


# ---------------------------------------------------------------------------
# One definition, two uses
# ---------------------------------------------------------------------------

def test_the_schema_the_model_sees_is_generated_from_the_argument_type(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    schema = registry.schemas()[0]

    assert schema["function"]["name"] == "nod"
    assert schema["function"]["description"] == "Nod once."
    parameters = schema["function"]["parameters"]["properties"]["pitch"]
    assert parameters["minimum"] == -40
    assert parameters["maximum"] == 26
    assert parameters["description"] == "degrees, down is negative"


def test_the_bounds_in_the_schema_are_the_bounds_that_are_enforced(registry):
    """One definition, so the two cannot drift.

    A hand-written schema beside a hand-written validator is two copies of one
    fact; `PLAN.md` §10 records what this project thinks of those.
    """
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"pitch": args.pitch}

    schema = registry.schemas()[0]["function"]["parameters"]["properties"]["pitch"]
    journal = a_journal()

    at_the_edge = dispatch(
        registry, "nod", {"pitch": schema["maximum"]}, a_context(), journal, turn=1
    )
    past_the_edge = dispatch(
        registry, "nod", {"pitch": schema["maximum"] + 1}, a_context(), journal, turn=1
    )

    assert at_the_edge.accepted
    assert not past_the_edge.accepted


# ---------------------------------------------------------------------------
# What gets through
# ---------------------------------------------------------------------------

def test_a_legal_call_reaches_the_tool(registry):
    seen = {}

    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        seen["pitch"] = args.pitch
        return {"ok": True}

    outcome = dispatch(registry, "nod", {"pitch": 10}, a_context(), a_journal(), turn=1)

    assert outcome.accepted
    assert outcome.result == {"ok": True}
    assert seen["pitch"] == 10


def test_an_out_of_range_argument_never_reaches_the_tool(registry):
    """The half that matters. A test that only proves legal values pass is not
    a test of validation.
    """
    reached = []

    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        reached.append(args.pitch)
        return {"ok": True}

    outcome = dispatch(registry, "nod", {"pitch": 999}, a_context(), a_journal(), turn=1)

    assert not outcome.accepted
    assert reached == [], "the tool ran with an argument it should never see"
    assert "pitch" in outcome.reason


def test_an_unknown_argument_is_refused_rather_than_ignored(registry):
    """Silently dropping it would let the model believe it had an effect."""
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True}

    outcome = dispatch(
        registry, "nod", {"pitch": 0, "speed": 9}, a_context(), a_journal(), turn=1
    )

    assert not outcome.accepted
    assert "speed" in outcome.reason


def test_a_missing_argument_is_refused(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True}

    outcome = dispatch(registry, "nod", {}, a_context(), a_journal(), turn=1)

    assert not outcome.accepted
    assert "pitch" in outcome.reason


def test_an_unknown_tool_is_refused(registry):
    outcome = dispatch(registry, "telepathy", {}, a_context(), a_journal(), turn=1)

    assert not outcome.accepted
    assert "telepathy" in outcome.reason


# ---------------------------------------------------------------------------
# What the Journal is told
# ---------------------------------------------------------------------------

def test_an_accepted_call_is_recorded_with_the_arguments_that_ran(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True}

    journal = a_journal()
    dispatch(registry, "nod", {"pitch": 10}, a_context(), journal, turn=3)

    recorded = journal.records[-1]
    assert recorded.type == "tool_called"
    assert recorded.tool == "nod"
    assert recorded.turn == 3
    assert recorded.args == {"pitch": 10}


def test_a_refused_call_is_recorded_with_its_reason(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True}

    journal = a_journal()
    dispatch(registry, "nod", {"pitch": 999}, a_context(), journal, turn=2)

    recorded = journal.records[-1]
    assert recorded.type == "tool_rejected"
    assert recorded.tool == "nod"
    assert recorded.turn == 2
    assert "pitch" in recorded.reason


def test_a_refused_call_is_not_also_recorded_as_a_call(registry):
    """The goldens show a refusal *instead of* a call, not beside it."""
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"ok": True}

    journal = a_journal()
    dispatch(registry, "nod", {"pitch": 999}, a_context(), journal, turn=1)

    assert [record.type for record in journal.records] == ["tool_rejected"]


# ---------------------------------------------------------------------------
# The layering claim
# ---------------------------------------------------------------------------

def test_a_tool_may_not_declare_a_physical_control_parameter(registry):
    """`PLAN.md` §4: the model decides whether, the control layer decides how far.

    The Journal already refuses to *record* one. Refusing to *register* one is
    where it stops being possible in the first place — the model would
    otherwise be told, in the schema, that it may send a velocity.
    """
    with pytest.raises(ValueError, match="control parameter"):

        @registry.tool("drive", "Go.")
        def drive(args: DriveArgs, ctx: ToolContext):
            return {}


def test_an_ordinary_parameter_still_registers(registry):
    # The negative control: a check that refused everything would satisfy the
    # test above.
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    assert registry.names() == ("nod",)


# ---------------------------------------------------------------------------
# `done`, end to end
# ---------------------------------------------------------------------------

def test_done_is_registered_by_default():
    from misty_agent.agent.tools import build_registry

    assert "done" in build_registry().names()


def test_done_takes_no_arguments():
    from misty_agent.agent.tools import build_registry

    schema = next(
        s for s in build_registry().schemas() if s["function"]["name"] == "done"
    )

    assert schema["function"]["parameters"].get("properties", {}) == {}


def test_done_says_the_episode_should_end():
    """The loop reads this from the registry, not from the Tool's name.

    `PLAN.md` §4 forbids a hard-coded fast path; a loop that checked for the
    string "done" would be one.
    """
    from misty_agent.agent.tools import build_registry

    registry = build_registry()
    journal = a_journal()

    outcome = dispatch(registry, "done", {}, a_context(), journal, turn=1)

    assert outcome.accepted
    assert outcome.ends_episode


def test_no_other_tool_claims_to_end_the_episode(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(registry, "nod", {"pitch": 0}, a_context(), a_journal(), turn=1)

    assert not outcome.ends_episode


def test_done_leaves_the_expected_records_behind():
    """Golden 1 has a `tool_called` for `done` and no Observation."""
    from misty_agent.agent.tools import build_registry

    journal = a_journal()
    dispatch(build_registry(), "done", {}, a_context(), journal, turn=1)

    assert [record.type for record in journal.records] == ["tool_called"]
    assert journal.records[0].args == {}


def test_a_tool_whose_argument_type_cannot_be_reached_says_so_plainly(registry):
    """Not a bare NameError from deep inside the annotation machinery.

    A model defined inside a function is invisible to `get_type_hints`, and
    the first version of this registry propagated the resulting `NameError`
    with no hint of what to do about it.
    """
    class Hidden(BaseModel):
        pitch: int

    with pytest.raises(TypeError, match="reachable from its module"):

        @registry.tool("hidden", "Nope.")
        def hidden(args: Hidden, ctx: ToolContext):
            return {}


def test_the_reason_names_the_argument_and_what_was_wrong_with_it(registry):
    """The model reads this back as an Observation, so it has to be actionable.

    "validation error" tells it nothing it can do differently next Turn.
    """
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "nod", {"pitch": 999}, a_context(), a_journal(), turn=1
    )

    assert "pitch" in outcome.reason
    assert "26" in outcome.reason, "the reason does not say what the limit is"


def test_the_reason_for_an_unknown_tool_lists_the_ones_there_are(registry):
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "telepathy", {}, a_context(), a_journal(), turn=1
    )

    assert "nod" in outcome.reason


def test_the_recorded_arguments_are_the_validated_ones_not_the_raw_ones(registry):
    """What ran, not what was asked for. They differ whenever a type coerces.

    A Journal that recorded the raw request would disagree with what the robot
    was actually told.
    """
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {"pitch": args.pitch}

    journal = a_journal()
    outcome = dispatch(
        registry, "nod", {"pitch": "10"}, a_context(), journal, turn=1
    )

    assert outcome.accepted
    assert journal.records[0].args == {"pitch": 10}
    assert journal.records[0].args["pitch"] != "10"


def test_a_tool_that_throws_does_not_leave_the_call_unrecorded(registry):
    """The record goes in before the handler runs, so a Tool that falls over
    still leaves evidence that it was asked.
    """
    @registry.tool("explode", "Fall over.")
    def explode(args: HeadArgs, ctx: ToolContext):
        raise RuntimeError("the arm jammed")

    journal = a_journal()
    with pytest.raises(RuntimeError):
        dispatch(registry, "explode", {"pitch": 0}, a_context(), journal, turn=1)

    assert [record.type for record in journal.records] == ["tool_called"]


def test_the_registry_hands_the_model_every_tool_it_has():
    from misty_agent.agent.tools import build_registry

    registry = build_registry()
    named = {schema["function"]["name"] for schema in registry.schemas()}

    assert named == set(registry.names())

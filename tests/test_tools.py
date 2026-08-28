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

import json
import pathlib

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


class MoveHeadArgs(BaseModel):
    pitch: int = Field(ge=-40, le=26)


class TwoAngles(BaseModel):
    pitch: int = Field(ge=-40, le=26)
    yaw: int = Field(ge=-81, le=81)


class AliasedDrive(BaseModel):
    """`model_fields` calls this `v`; the schema calls it `linearVelocity`."""

    v: int = Field(alias="linearVelocity")


class InnerMotion(BaseModel):
    velocity: int = 0


class NestedDrive(BaseModel):
    """A control parameter one level down, where `model_fields` cannot see it."""

    motion: InnerMotion


class DocumentedArgs(BaseModel):
    """Internal note: see PLAN.md §10 about two copies of one fact."""

    pitch: int = 0


def a_handler(args_model):
    """A handler annotated with a model that was built at run time.

    This file has `from __future__ import annotations`, so every annotation is
    a string, and a string naming a local cannot be resolved — which is what
    `_argument_type` raises its TypeError about. Assigning the class object
    itself is how a test parametrised over models gets past that; the models
    the real Tools use are module-level and need none of this.
    """
    def handler(args, ctx):
        return {}

    handler.__annotations__ = {"args": args_model, "ctx": ToolContext}
    return handler


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

    "validation error" tells it nothing it can do differently next Turn. It
    names the value the model *sent*, because that is the thing the model has
    to change; the next test pins that wording to the golden it came from.
    """
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "nod", {"pitch": 999}, a_context(), a_journal(), turn=1
    )

    assert "pitch" in outcome.reason
    assert "999" in outcome.reason, "the reason does not say what was sent"


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


# ---------------------------------------------------------------------------
# The wording of a refusal, and where it comes from
# ---------------------------------------------------------------------------

def test_a_refusal_reads_the_way_the_golden_journal_says_it_does(registry):
    """The golden was written first, so it is the golden that wins.

    `tests/goldens/episode_ends_after_several_turns.jsonl` carries a refused
    `move_head` and states in full what its reason says. Ticket 07 has to
    reproduce that file, and it can only do so if this module produces that
    string — which the first implementation did not (`PLAN.md` §15.7). Read
    out of the file rather than copied into this test: a copy would go on
    passing after someone edited the golden.
    """
    golden = pathlib.Path(__file__).parent / "goldens" / (
        "episode_ends_after_several_turns.jsonl"
    )
    rejected = [
        json.loads(line)
        for line in golden.read_text().splitlines()
        if json.loads(line)["type"] == "tool_rejected"
    ]
    assert rejected, "the golden no longer carries a refused call to check against"

    @registry.tool("move_head", "Point the head.")
    def move_head(args: MoveHeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "move_head", {"pitch": 140}, a_context(), a_journal(), turn=1
    )

    assert outcome.reason == rejected[0]["reason"]


def test_every_bad_argument_is_reported_not_just_the_first(registry):
    """One bad argument per Turn would cost a Turn per argument."""
    @registry.tool("look", "Look somewhere.")
    def look(args: TwoAngles, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "look", {"pitch": 140, "yaw": 900}, a_context(), a_journal(), turn=1
    )

    assert "pitch" in outcome.reason
    assert "yaw" in outcome.reason


# ---------------------------------------------------------------------------
# Ending the Episode is declared, not spelled
# ---------------------------------------------------------------------------

def test_a_tool_not_called_done_can_end_the_episode(registry):
    """`PLAN.md` §4 forbids a hard-coded fast path, and this is what proves it.

    `test_done_says_the_episode_should_end` cannot: in `build_registry` the
    only Tool that ends the Episode is also the only Tool named `done`, so
    `ends_episode=(name == "done")` passes it. Two Tools are needed to tell
    the property from the spelling, and neither of them may be `done`.
    """
    @registry.tool("give_up", "Stop trying.", ends_episode=True)
    def give_up(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "give_up", {"pitch": 0}, a_context(), a_journal(), turn=1
    )

    assert outcome.ends_episode


def test_a_tool_called_done_does_not_end_the_episode_unless_it_says_so(registry):
    """The other half: the name alone must not be enough."""
    @registry.tool("done", "Not the real one.")
    def done(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(registry, "done", {"pitch": 0}, a_context(), a_journal(), turn=1)

    assert outcome.accepted
    assert not outcome.ends_episode


def test_a_refused_call_never_ends_the_episode(registry):
    """A Tool that was not run cannot have finished anything."""
    @registry.tool("give_up", "Stop trying.", ends_episode=True)
    def give_up(args: HeadArgs, ctx: ToolContext):
        return {}

    outcome = dispatch(
        registry, "give_up", {"pitch": 999}, a_context(), a_journal(), turn=1
    )

    assert not outcome.accepted
    assert not outcome.ends_episode


# ---------------------------------------------------------------------------
# The calling convention
# ---------------------------------------------------------------------------

def test_the_context_the_caller_passed_is_the_one_the_tool_gets(registry):
    """Tickets 05 and 06 reach the robot through this and nothing else.

    Without this, `dispatch` could build its own empty context and every Tool
    would find `robot=None` at run time rather than here.
    """
    seen = {}

    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        seen["ctx"] = ctx
        return {}

    robot, readings, config, clock = object(), object(), object(), object()
    ctx = ToolContext(robot=robot, readings=readings, config=config, clock=clock)

    dispatch(registry, "nod", {"pitch": 0}, ctx, a_journal(), turn=1)

    assert seen["ctx"] is ctx
    assert seen["ctx"].robot is robot
    assert seen["ctx"].readings is readings
    assert seen["ctx"].config is config
    assert seen["ctx"].clock is clock


def test_a_tool_registered_after_the_schemas_were_read_still_appears(registry):
    """The registry is asked for its schemas once per Turn, not once ever."""
    @registry.tool("nod", "Nod once.")
    def nod(args: HeadArgs, ctx: ToolContext):
        return {}

    before = registry.schemas()

    @registry.tool("shake", "Shake once.")
    def shake(args: HeadArgs, ctx: ToolContext):
        return {}

    after = registry.schemas()

    assert len(before) == 1
    assert {schema["function"]["name"] for schema in after} == {"nod", "shake"}


# ---------------------------------------------------------------------------
# What a Tool may be called
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name", ["", "   ", "move head", "move_head!", "頭", "a" * 65]
)
def test_a_tool_name_the_api_would_reject_is_refused_here(registry, name):
    """Rejected at registration rather than at the far end of a network call."""
    with pytest.raises(ValueError, match="not a usable Tool name"):
        @registry.tool(name, "Whatever.")
        def whatever(args: HeadArgs, ctx: ToolContext):
            return {}


@pytest.mark.parametrize("name", ["done", "move_head", "look-around", "a" * 64])
def test_the_names_the_real_tools_use_are_accepted(registry, name):
    @registry.tool(name, "Whatever.")
    def whatever(args: HeadArgs, ctx: ToolContext):
        return {}

    assert name in registry.names()


# ---------------------------------------------------------------------------
# The layering guard, on the schema rather than on the fields
# ---------------------------------------------------------------------------

def test_a_control_parameter_hidden_behind_an_alias_is_still_refused(registry):
    """`model_fields` says `v`; the schema the model reads says `linearVelocity`.

    Checking the fields would have let this register, and then `dispatch`
    would have refused every call to it as an unknown argument — a Tool the
    model can see and can never successfully use.
    """
    with pytest.raises(ValueError, match="linearVelocity"):
        registry.tool("drive", "Drive.")(a_handler(AliasedDrive))


def test_a_control_parameter_nested_one_level_down_is_still_refused(registry):
    """A nested model's fields are in `$defs`, not in `model_fields` at all."""
    with pytest.raises(ValueError, match="velocity"):
        registry.tool("drive", "Drive.")(a_handler(NestedDrive))


@pytest.mark.parametrize(
    "field",
    [
        "velocity",
        "linearVelocity",
        "angularVelocity",
        "velocity_cm_s",
        "speed",
        "speed_cm_s",
        "time_ms",
        "timeMs",
        "drive_ms",
        "duration_ms",
        "drive_time_ms",
        "cm_per_sec",
        "wait_seconds",
    ],
)
def test_the_spellings_a_tool_author_would_reach_for_are_all_refused(registry, field):
    """One spelling passing is not evidence that the rule works.

    The first version matched a fixed list of six, so `velocity_cm_s` and
    `duration_ms` both registered cleanly.
    """
    model = type("Args", (BaseModel,), {"__annotations__": {field: int}})

    with pytest.raises(ValueError, match="control layer"):
        registry.tool("drive", "Drive.")(a_handler(model))


@pytest.mark.parametrize(
    "field", ["pitch", "yaw", "text", "image", "arms", "target_distance_cm"]
)
def test_the_arguments_the_real_tools_need_are_not_refused(registry, field):
    """A guard that blocked these would be worse than no guard.

    `target_distance_cm` is here on purpose: `PLAN.md` §15.2 says that if
    "back off a bit" is ever needed it is a clamped target on `approach`, so
    the guard must not pre-empt a decision that section left open.
    """
    model = type("Args", (BaseModel,), {"__annotations__": {field: int}})

    registry.tool("whatever", "Whatever.")(a_handler(model))

    assert "whatever" in registry.names()


def test_the_schema_does_not_hand_the_model_this_modules_own_reasoning(registry):
    """pydantic puts the argument model's docstring in the schema.

    Left there, the model would read a paragraph about `PLAN.md` §10 as if it
    were guidance about the Tool.
    """
    @registry.tool("nod", "Nod once.")
    def nod(args: DocumentedArgs, ctx: ToolContext):
        return {}

    schema = registry.schemas()[0]

    assert "PLAN.md" not in json.dumps(schema)
    assert schema["function"]["description"] == "Nod once."

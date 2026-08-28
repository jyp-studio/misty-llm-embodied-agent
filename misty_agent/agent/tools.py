"""What the model may ask for, and what actually gets through.

A Tool is the agent's whole vocabulary of action (`CONTEXT.md`): anything it
cannot do through one, it cannot do. This module decides two things about that
vocabulary, and they are deliberately the same decision — **what the model is
told it may send** and **what is allowed past** both come from one type.

A hand-written schema beside a hand-written validator is two copies of one
fact. `PLAN.md` §10 already recorded what this project thinks happens to
those, and `PLAN.md` §14.6 is the debt this pays off: M6 deleted the only
executable check that an out-of-range argument is refused rather than sent to
the robot.

## The line a Tool may not cross

`PLAN.md` §4's layering claim is that the model decides *whether* to approach
and the control layer decides *how far* each Step goes. The Journal already
refuses to record a velocity or a drive duration. Refusing to **register** one
is where it stops being possible at all: otherwise the model would be told, in
the schema it is handed, that sending one is allowed.

## Adding a Tool

One function and one argument type. The ReAct loop does not change — the
registry is a mapping, not a switch, and whether a Tool ends the Episode is a
property it declares rather than something the loop infers from its name.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Tuple,
    Type,
    get_type_hints,
)

from pydantic import BaseModel, ValidationError

from misty_agent.agent.journal import Journal, ToolCalled, ToolRejected
from misty_agent.agent.layering import refuse_control_parameters


@dataclass(frozen=True)
class ToolContext:
    """What a Tool is given besides its own arguments.

    Four fields, and each is one that a Tool named in `PLAN.md` §15.2 already
    needs: seven of the nine drive the robot, `approach` also reads distances,
    and M5's `approach(readings, robot, *, config, clock)` is the signature
    this has to be able to call. `speak` needs the clock too, for §15.4's
    suppression window. Defining the calling convention is this ticket's job,
    and a convention that could not call the Tools already specified would
    have to be changed by every one of them in the next ticket.

    Held as `Any` on purpose: importing the robot and config types here would
    make the vocabulary of action depend on one particular robot, and the
    simulator and the real Misty are both meant to fit.
    """

    robot: Any
    readings: Any
    config: Any = None
    clock: Any = None


#: What a Tool may be called. The function-calling APIs this feeds accept
#: `^[a-zA-Z0-9_-]{1,64}$`, and a name outside it is rejected at the far end
#: of a network call — which is a slow, remote way to find out about a typo
#: that registration can catch immediately.
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Tool:
    """One registered capability."""

    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Mapping[str, Any]]
    ends_episode: bool

    def schema(self) -> Dict[str, Any]:
        """What the model is told, generated from the argument type.

        Not written out by hand anywhere. If the bounds below and the bounds
        enforced at dispatch could differ, one of them would eventually be
        wrong and nothing would say which.
        """
        parameters = self.args_model.model_json_schema()
        parameters.pop("title", None)
        # The argument model's own docstring is written for whoever maintains
        # it, and pydantic puts it here. Left in, the model would read this
        # module's reasoning about `PLAN.md` as if it were instructions about
        # the Tool. What the model should be told is `self.description`; per
        # argument, `Field(description=...)`, which is untouched.
        parameters.pop("description", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


@dataclass(frozen=True)
class Dispatched:
    """What came of asking for a Tool."""

    accepted: bool
    ends_episode: bool = False
    result: Optional[Mapping[str, Any]] = None
    reason: Optional[str] = None


class ToolRegistry:
    """The Tools this agent has. A mapping, not a switch."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def tool(
        self, name: str, description: str, *, ends_episode: bool = False
    ) -> Callable[[Callable[..., Mapping[str, Any]]], Callable[..., Mapping[str, Any]]]:
        def register(handler):
            if not TOOL_NAME.fullmatch(name):
                raise ValueError(
                    f"{name!r} is not a usable Tool name: it has to match "
                    f"{TOOL_NAME.pattern} to survive the function-calling API"
                )
            if name in self._tools:
                raise ValueError(f"a Tool named {name!r} is already registered")
            args_model = _argument_type(handler)
            refuse_control_parameters(
                    f"Tool {name!r}", _declared_names(args_model), commanded=True
                )
            self._tools[name] = Tool(
                name=name,
                description=description,
                args_model=args_model,
                handler=handler,
                ends_episode=ends_episode,
            )
            return handler

        return register

    def names(self) -> Tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def schemas(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(tool.schema() for tool in self._tools.values())


def _argument_type(handler: Callable[..., Any]) -> Type[BaseModel]:
    """The pydantic model the handler's first parameter is annotated with."""
    try:
        hints = get_type_hints(handler)
    except NameError as error:
        raise TypeError(
            f"{handler.__name__}'s argument type could not be resolved "
            f"({error}). A Tool's argument model has to be reachable from its "
            f"module — one defined inside a function is not"
        ) from error
    parameters = [
        parameter.name
        for parameter in inspect.signature(handler).parameters.values()
        if parameter.kind
        in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    annotated = hints.get(parameters[0]) if parameters else None
    if not (isinstance(annotated, type) and issubclass(annotated, BaseModel)):
        raise TypeError(
            f"{handler.__name__} must declare its argument type: its first "
            f"parameter has to be annotated with a pydantic model, which is "
            f"what the schema is generated from and what arguments are "
            f"validated against"
        )
    return annotated


def _declared_names(args_model: Type[BaseModel]) -> Iterator[str]:
    """Every name the generated schema tells the model it may send.

    Read off the schema rather than off `model_fields`, because the schema is
    what the model actually sees and the two are not the same document. A
    field aliased `Field(alias="linearVelocity")` is `v` in `model_fields` and
    `linearVelocity` in the schema; a nested model's fields do not appear in
    `model_fields` at all, only under `$defs`. Checking the fields would have
    left both of those routes open, and the docstring above claims neither is.
    """

    def walk(node: Any) -> Iterator[str]:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                yield from properties
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    return walk(args_model.model_json_schema())


def dispatch(
    registry: ToolRegistry,
    name: str,
    raw_args: Mapping[str, Any],
    ctx: ToolContext,
    journal: Journal,
    *,
    turn: int,
) -> Dispatched:
    """Validate, record, and only then run.

    The order is the point. Nothing reaches the robot before its arguments
    have been checked, and a refusal leaves a record saying what was asked for
    and why it was not done — which is the half of `PLAN.md` §14.6's debt that
    is about being able to see the agent get it wrong.
    """
    tool = registry.get(name)
    if tool is None:
        return _refuse(
            journal,
            turn,
            name,
            f"there is no Tool named {name!r}; the ones there are: "
            f"{', '.join(registry.names()) or 'none'}",
        )

    # Checked here rather than left to each model's `extra` setting: a rule
    # every author has to remember is a rule that will eventually be
    # forgotten, and silently dropping an argument would let the model believe
    # it had an effect.
    unknown = sorted(set(raw_args) - set(tool.args_model.model_fields))
    if unknown:
        return _refuse(
            journal,
            turn,
            name,
            f"{', '.join(unknown)}: not an argument {name!r} takes; it takes "
            f"{', '.join(tool.args_model.model_fields) or 'none'}",
        )

    try:
        arguments = tool.args_model.model_validate(raw_args, strict=False)
    except ValidationError as error:
        return _refuse(journal, turn, name, _explain(error))

    journal.record(
        ToolCalled, turn=turn, tool=name, args=arguments.model_dump(mode="json")
    )
    return Dispatched(
        accepted=True,
        ends_episode=tool.ends_episode,
        result=tool.handler(arguments, ctx),
    )


def _refuse(journal: Journal, turn: int, name: str, reason: str) -> Dispatched:
    journal.record(ToolRejected, turn=turn, tool=name, reason=reason)
    return Dispatched(accepted=False, reason=reason)


#: Validation failures that are a number being out of bounds, as opposed to
#: being the wrong kind of thing entirely.
_OUT_OF_RANGE = frozenset(
    {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}
)


def _explain(error: ValidationError) -> str:
    """Why the arguments were refused, in words rather than a stack trace.

    The model reads this back as an Observation, so it has to say which
    argument and what was wrong with it — "validation error" tells it nothing
    it can act on.

    An out-of-range number names **the value it sent**, not the bound it
    missed. That wording is not a preference: it is what
    `tests/goldens/episode_ends_after_several_turns.jsonl` already says a
    refused `move_head` looks like, and that file was written before this
    module existed. Every error is reported, not just the first — a model told
    about one bad argument at a time takes a Turn per argument to find out.
    """
    parts = []
    for problem in error.errors():
        where = ".".join(str(piece) for piece in problem["loc"]) or "(arguments)"
        if problem["type"] in _OUT_OF_RANGE:
            parts.append(f"{where} {problem['input']!s} is outside the permitted range")
        else:
            parts.append(f"{where}: {problem['msg']}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# The Tools themselves
# ---------------------------------------------------------------------------

class NoArguments(BaseModel):
    """For a Tool that takes none.

    No `extra="forbid"`: `dispatch` refuses unknown arguments before
    validation runs, so setting it here would be a second copy of a rule that
    is already enforced — and the copy that never fires is the one that is
    wrong when they drift (`PLAN.md` §10).
    """


def build_registry() -> ToolRegistry:
    """Every Tool this agent has.

    Tickets 05 and 06 add the other eight. `done` is here because it is the
    one that needs nothing from the robot, which makes it the smallest thing
    that exercises registering, generating a schema, dispatching and
    recording.
    """
    registry = ToolRegistry()

    @registry.tool(
        "done",
        "Finish. Call this when nothing further is worth doing right now.",
        ends_episode=True,
    )
    def done(args: NoArguments, ctx: ToolContext) -> Mapping[str, Any]:
        return {}

    return registry

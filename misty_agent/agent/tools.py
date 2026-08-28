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

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    get_type_hints,
)

from pydantic import BaseModel, ValidationError

from misty_agent.agent.journal import (
    FORBIDDEN_KEYS,
    Journal,
    ToolCalled,
    ToolRejected,
)


@dataclass(frozen=True)
class ToolContext:
    """What a Tool is given besides its own arguments.

    Two fields, and neither is speculative: seven of the nine Tools in
    `PLAN.md` §15.2 drive the robot, and `approach` additionally needs the
    distance readings. Defining the calling convention is this ticket's job,
    and a convention that could not serve the Tools already specified would
    have to be changed by every one of them in the next ticket.
    """

    robot: Any
    readings: Any


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
            if name in self._tools:
                raise ValueError(f"a Tool named {name!r} is already registered")
            args_model = _argument_type(handler)
            _refuse_control_parameters(name, args_model)
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
        name for name in handler.__code__.co_varnames[: handler.__code__.co_argcount]
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


def _refuse_control_parameters(name: str, args_model: Type[BaseModel]) -> None:
    flattened = {key.replace("_", "") for key in FORBIDDEN_KEYS}
    for field in args_model.model_fields:
        if field.lower().replace("_", "") in flattened:
            raise ValueError(
                f"Tool {name!r} may not take {field!r}: physical control "
                f"parameters belong to the control layer, and a Tool that "
                f"declared one would tell the model in its own schema that "
                f"sending one is allowed (PLAN.md §4)"
            )


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


def _explain(error: ValidationError) -> str:
    """Why the arguments were refused, in words rather than a stack trace.

    The model reads this back as an Observation, so it has to say which
    argument and what was wrong with it — "validation error" tells it nothing
    it can act on.
    """
    parts = []
    for problem in error.errors():
        where = ".".join(str(piece) for piece in problem["loc"]) or "(arguments)"
        parts.append(f"{where}: {problem['msg']}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# The Tools themselves
# ---------------------------------------------------------------------------

class NoArguments(BaseModel):
    """For a Tool that takes none. `extra='forbid'` still applies."""

    model_config = {"extra": "forbid"}


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

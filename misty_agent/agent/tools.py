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
    Annotated,
    Any,
    Callable,
    Dict,
    Iterator,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Tuple,
    Type,
    get_type_hints,
)

from pydantic import BaseModel, Field, StringConstraints, ValidationError


from misty_agent.agent.journal import Journal, ToolCalled, ToolRejected
from misty_agent.agent.layering import (
    control_parameter,
    refuse_control_parameters,
)
from misty_agent.control.approach import ApproachStatus, approach as run_approach
from misty_agent.perception.active import NO_ACTIVE_PERCEPTION, ActivePerceptionResult
from misty_agent.robot import Effect
from misty_agent.agent.skills import EpisodeSkills, SkillRejected
from misty_agent.agent.target import InteractionTarget, TargetState
from misty_agent.perception.listening import ListeningEnding, ListeningResult


class Ears(Protocol):
    """Whatever is listening, seen from a Tool that is about to make noise.

    One method, because one is all `speak` needs: the microphone has to be
    told before the speaker starts, not after (`PLAN.md` §15.29).
    """

    def mute_for(self, seconds: float) -> None: ...


class HearsNothing:
    """Ears for an Episode with no microphone wired.

    A null object, to match `NEVER_STOPS` and `NO_MEMORY` — those two exist so
    the caller reads one shape instead of a `None` check, and an `Optional`
    here would have been exactly the check they avoid.
    """

    def mute_for(self, seconds: float) -> None:
        return None


HEARS_NOTHING = HearsNothing()


@dataclass(frozen=True)
class ToolContext:
    """What a Tool is given besides its own arguments.

    The fields are dependencies a registered Tool actually needs. Most Tools
    drive the robot, `approach` also reads distances,
    and M5's `approach(readings, robot, *, config, clock)` is the signature
    this has to be able to call. `speak` needs the config for its speech
    estimate and the ears to shut them before it talks (§15.29). Defining the calling convention is this ticket's job,
    and a convention that could not call the Tools already specified would
    have to be changed by every one of them in the next ticket.

    `robot` is any `misty_agent.robot.Robot`: the simulated and the real
    adapter both fit, and neither leaks a vendor request into a Tool. It is
    typed `Any` alongside `readings`, `config` and `clock` so that tests can
    hand in narrower doubles without satisfying the whole Protocol.
    """

    robot: Any
    readings: Any
    config: Any = None
    clock: Any = None
    #: What must not hear the robot talk to itself. Nearly every Tool
    #: makes no sound, and an Episode with no microphone is still an Episode —
    #: hence a null object rather than a `None` every caller has to test.
    ears: Ears = HEARS_NOTHING
    active_perception: Any = NO_ACTIVE_PERCEPTION
    #: This Episode's Skill permissions. `None` means no catalog is configured;
    #: the object dies with the Episode, so loaded guidance cannot outlive it.
    skills: Optional[EpisodeSkills] = None
    listener: Any = None
    #: The one anonymous person this Episode is about. Perception Tools
    #: report and update its visible/lost state; movement refuses a lost one.
    target: Optional[InteractionTarget] = None


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
    #: Which of this Tool's arguments, if any, is words the robot says aloud.
    #: Declared rather than inferred, for the same reason `ends_episode` is
    #: (`PLAN.md` §15.9): the alternative is the ReAct loop checking for a
    #: Tool named `speak` and reading a key called `text`, and then memory
    #: quietly stops recording the moment either name changes.
    speaks: Optional[str] = None

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


#: The one key a Tool's result may use to say how many Steps it drove.
#:
#: `episode_finished.steps` in the goldens is the sum of the drives that
#: actually happened, and only `approach` drives — but the ReAct loop should
#: not know that, and should not reach into a result dict looking for a
#: string. So the string lives here, `dispatch` reads it, and the loop gets a
#: typed field. `PLAN.md` §15.20 records why this rather than the alternative.
STEPS_KEY = "steps"


@dataclass(frozen=True)
class Dispatched:
    """What came of asking for a Tool."""

    accepted: bool
    ends_episode: bool = False
    result: Optional[Mapping[str, Any]] = None
    reason: Optional[str] = None
    #: Drive commands this call issued, for `episode_finished.steps`. Zero for
    #: every Tool that does not move the base, which is ten of the eleven.
    steps: int = 0
    #: What the robot said aloud, if this call said anything. Memory's half of
    #: an Exchange (`CONTEXT.md`), and the validated text rather than the raw
    #: request — so what is remembered is what was spoken.
    spoken: Optional[str] = None


class ToolRegistry:
    """The Tools this agent has. A mapping, not a switch."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def tool(
        self,
        name: str,
        description: str,
        *,
        ends_episode: bool = False,
        speaks: Optional[str] = None,
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
            if speaks is not None and speaks not in args_model.model_fields:
                raise ValueError(
                    f"Tool {name!r} says it speaks {speaks!r}, but that is not "
                    f"one of its arguments ({', '.join(args_model.model_fields) or 'none'})"
                )
            refuse_control_parameters(
                    f"Tool {name!r}", _declared_names(args_model), commanded=True
                )
            self._tools[name] = Tool(
                name=name,
                description=description,
                args_model=args_model,
                handler=handler,
                ends_episode=ends_episode,
                speaks=speaks,
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
            f"{', '.join(_name_or_describe(u) for u in unknown)}: not an "
            f"argument {name!r} takes; it takes "
            f"{', '.join(tool.args_model.model_fields) or 'none'}",
        )

    try:
        arguments = tool.args_model.model_validate(raw_args, strict=False)
    except ValidationError as error:
        return _refuse(journal, turn, name, _explain(error))

    journal.record(
        ToolCalled, turn=turn, tool=name, args=arguments.model_dump(mode="json")
    )
    result = tool.handler(arguments, ctx)
    return Dispatched(
        accepted=True,
        ends_episode=tool.ends_episode,
        result=result,
        steps=_steps_in(result),
        spoken=getattr(arguments, tool.speaks) if tool.speaks else None,
    )


def _steps_in(result: Mapping[str, Any]) -> int:
    """How many Steps that call drove, or zero.

    Read here and nowhere else. A loop that did this itself would have to know
    which Tools drive and what they call the count — and would go wrong
    silently the first time one of them disagreed.
    """
    reported = result.get(STEPS_KEY, 0) if isinstance(result, Mapping) else 0
    if not isinstance(reported, int) or isinstance(reported, bool) or reported < 0:
        raise ValueError(
            f"a Tool reported {reported!r} Steps: the count goes into "
            f"episode_finished.steps, which the goldens assert is the number "
            f"of drives that actually happened"
        )
    return reported


def _name_or_describe(argument: str) -> str:
    """Say the argument back, unless saying it would teach the model a word.

    A refusal is read by the model as an Observation and written to the
    Journal. Echoing `linearVelocity` there would put a control parameter in
    both, which is what `PLAN.md` §4 says cannot happen — and the model has
    no need of the spelling, only of the reason.
    """
    return (
        "a physical control parameter, which is the control layer's"
        if control_parameter(argument, commanded=True)
        else argument
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


# --- What the joints will actually do -------------------------------------
#
# Every bound below is quoted from the Misty II REST reference, and they are
# five *different* ranges. Reaching for one shared constant would be the same
# mistake as one shared schema: it would look tidier and it would be wrong
# about four of them.
#
# https://docs.mistyrobotics.com/misty-ii/web-api/api-reference/
#
# These have never run against a robot (`PLAN.md` §8, first bullet). They are
# what the documentation says, which is a different claim from what the
# hardware does.

#: MoveHead, degrees: the reference's table gives pitch as -40 (up) to 26
#: (down). A web search will tell you 29; that figure is not in the table,
#: and the vendored `legacy/**/CUBS_Misty.py` uses 26 alongside the yaw stops.
HEAD_PITCH_UP, HEAD_PITCH_DOWN = -40.0, 26.0
#: MoveHead, degrees: roll runs -40 (left) to 40 (right).
HEAD_ROLL_LEFT, HEAD_ROLL_RIGHT = -40.0, 40.0
#: MoveHead, degrees: yaw runs -81 (right) to 81 (left).
HEAD_YAW_RIGHT, HEAD_YAW_LEFT = -81.0, 81.0
#: MoveArms, in degrees: -29 is as high as the arms go (any higher fouls the
#: display lens), 0 is straight forward, 90 is hanging straight down.
ARM_UP, ARM_DOWN = -29.0, 90.0
#: ChangeLED: each of red, green and blue is "the ... RGB color value
#: (range 0 to 255)".
LED_MIN, LED_MAX = 0, 255
#: PlayAudio: "a value between 0 and 100 for the loudness of the audio clip".
VOLUME_MIN, VOLUME_MAX = 0, 100

#: Longest utterance `speak` accepts. The only bound here that is **not** from
#: the reference — Misty documents no maximum — so it is derived instead:
#: `PLAN.md` §4's estimate saturates at 12 s, which is (12.0 - 0.5) * 2.2 ≈ 25
#: words, and 25 words of English is about 150 characters. Past that the
#: estimate stops tracking the speech, and ticket 10's suppression window
#: would reopen while Misty is still talking.
#:
#: A module constant rather than a `Settings` field: a Tool's argument type is
#: built once at import and could not read a per-Episode config anyway, so the
#: field would look adjustable and not be (`PLAN.md` §10 #4).
SPEECH_MAX_CHARS = 150

#: Where a `look_around` scan points, in order. Well inside the documented
#: yaw range: the point is to see who is there, not to reach the stops.
SCAN_YAWS = (-60.0, 0.0, 60.0)

#: The expression images Misty ships, keyed by what the model actually wants
#: to convey. The model picks a feeling and this picks the file — a free-text
#: filename would let it name an image the robot does not have, and the only
#: sign would be a 404 inside the driver.
#: https://lessons.mistyrobotics.com/resource-database/image-files
EXPRESSION_IMAGES = {
    "happy": "e_Joy.jpg",
    "sad": "e_Sadness.jpg",
    "angry": "e_Anger.jpg",
    "surprised": "e_Surprise.jpg",
    "love": "e_Love.jpg",
    "afraid": "e_ApprehensionConcerned.jpg",
    "neutral": "e_DefaultContent.jpg",
}

#: The system sounds, same idea. A deliberately small subset: the robot ships
#: around sixty, and handing the model all of them would spend schema on
#: choices it has no way to tell apart. Every filename here is in the
#: resource database below.
#: https://lessons.mistyrobotics.com/resource-database/audio-files
SOUND_FILES = {
    "joy": "s_Joy.wav",
    "amazement": "s_Amazement.wav",
    "awe": "s_Awe.wav",
    "anger": "s_Anger.wav",
    "acceptance": "s_Acceptance.wav",
    "annoyance": "s_Annoyance.wav",
}

Expression = Literal[
    "happy", "sad", "angry", "surprised", "love", "afraid", "neutral"
]
Sound = Literal["joy", "amazement", "awe", "anger", "acceptance", "annoyance"]


class SpeakArgs(BaseModel):
    text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=SPEECH_MAX_CHARS,
        ),
    ] = Field(description="What to say out loud, in the user's language.")


class DisplayImageArgs(BaseModel):
    expression: Expression = Field(description="The face to show.")


class MoveArmsArgs(BaseModel):
    left: float = Field(
        default=ARM_DOWN, ge=ARM_UP, le=ARM_DOWN,
        description="Left arm, degrees: -29 straight up, 0 forward, 90 down.",
    )
    right: float = Field(
        default=ARM_DOWN, ge=ARM_UP, le=ARM_DOWN,
        description="Right arm, degrees: -29 straight up, 0 forward, 90 down.",
    )


class MoveHeadArgs(BaseModel):
    """All three default to 0, which the reference calls looking straight
    ahead — so the model names only the axis it wants to change, and calling
    this with nothing is how it recentres."""

    pitch: float = Field(
        default=0.0, ge=HEAD_PITCH_UP, le=HEAD_PITCH_DOWN,
        description="Degrees: -40 looks up, 0 level, 26 looks down.",
    )
    roll: float = Field(
        default=0.0, ge=HEAD_ROLL_LEFT, le=HEAD_ROLL_RIGHT,
        description="Degrees of head tilt: -40 left ear down, 40 right.",
    )
    yaw: float = Field(
        default=0.0, ge=HEAD_YAW_RIGHT, le=HEAD_YAW_LEFT,
        description="Degrees: -81 turns right, 0 forward, 81 turns left.",
    )


class ChangeLedArgs(BaseModel):
    red: int = Field(default=0, ge=LED_MIN, le=LED_MAX, description="0-255.")
    green: int = Field(default=0, ge=LED_MIN, le=LED_MAX, description="0-255.")
    blue: int = Field(default=0, ge=LED_MIN, le=LED_MAX, description="0-255.")


class PlayAudioArgs(BaseModel):
    sound: Sound = Field(description="Which of the built-in sounds to play.")
    volume: int = Field(
        default=50, ge=VOLUME_MIN, le=VOLUME_MAX,
        description="0 is silent, 100 is full volume.",
    )


class ActivateSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SkillResourceArgs(ActivateSkillArgs):
    resource: str = Field(min_length=1, max_length=256)


#: Characters that are a syllable rather than a letter, and that are written
#: without spaces between words. Counting these as words is what made the
#: estimate wrong for the language this robot is actually spoken to in.
#:
#: Spelled out rather than taken as whole blocks, because the obvious whole
#: block is wrong: Halfwidth and Fullwidth Forms (U+FF00–FFEF) holds the
#: fullwidth Latin alphabet as well as the fullwidth comma, so
#: `Ｈｅｌｌｏ　ｗｏｒｌｄ` billed eleven syllables. The alphanumeric runs
#: (FF10–FF19, FF21–FF3A, FF41–FF5A) are therefore left out, and U+3000 with
#: them — the ideographic space is whitespace, and `str.split` already treats
#: it as a word boundary.
_CJK = re.compile(
    "["
    "\u3001-\u303f"      # CJK punctuation, less the ideographic space
    "\u3040-\u30ff"      # hiragana and katakana
    "\u3400-\u4dbf"      # CJK ideographs, extension A
    "\u4e00-\u9fff"      # CJK ideographs
    "\uac00-\ud7af"      # Hangul syllables
    "\uff01-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65"  # fullwidth punctuation
    "\uff66-\uff9f"      # halfwidth katakana
    "]"
)


def estimate_speech_ms(text: str, config: Any) -> int:
    """How long that will take to say, near enough to suppress our own voice.

    `PLAN.md` §4's estimate, and §15.4 records why it is an estimate at all:
    Misty's TTS returns no timing, so there is nothing to read back. Every
    constant is UNCALIBRATED and lives in `Settings` rather than here — the
    old main script hard-coded them, which made a guess look like a fact.

    **Two rates, because two writing systems.** `split()` counts
    whitespace-separated words, and a whole Chinese sentence is one of them:
    「你好，我過來一點」 came out as 0.95 s, so the suppression window reopened
    while Misty was still talking and she transcribed herself — which is the
    exact defect ticket 10 exists to fix, returning in a new form. CJK
    characters are therefore counted separately and at their own rate, and
    removed before the words are counted so a Chinese sentence does not also
    bill for one Latin word (`PLAN.md` §15.28).

    Latin text is unaffected, which four golden Journals depend on.
    """
    characters = len(_CJK.findall(text))
    words = len(_CJK.sub(" ", text).split())
    if not characters and not words:
        words = 1
    seconds = (
        characters / config.speech_cjk_chars_per_second
        + words / config.speech_words_per_second
        + config.speech_overhead_s
    )
    return int(round(min(config.speech_estimate_cap_s, seconds) * 1000))


def build_registry() -> ToolRegistry:
    """Every Tool this agent has.

    `PLAN.md` §4: with AutoMisty gone, expressiveness is **composition**.
    There is no `wave` and no `dance` — a wave is `move_arms` twice, and a
    dance is the model putting arms, LED and sound together over several
    Turns. The physical primitives are the whole of what the agent can
    express, and anything more elaborate is the model's to build out of them.
    Ticket 06's two read-only perception Tools widen what the model can
    inspect, not what can move the robot.

    None of them takes a velocity or a duration. The driver's `move_head` and
    `move_arms` both accept one, and both are left unset here: how fast a
    joint should travel is the control layer's business (`PLAN.md` §4), and
    Misty has a default.
    """
    registry = ToolRegistry()

    @registry.tool("activate_skill", "Load a named Skill's guidance for this Episode only. No effects or scripts run.")
    def activate_skill(args: ActivateSkillArgs, ctx: ToolContext) -> Mapping[str, Any]:
        if ctx.skills is None:
            return {"refused": "No Skill Catalog is configured"}
        try:
            return ctx.skills.activate(args.name)
        except SkillRejected as error:
            return {"refused": str(error)}

    @registry.tool("read_skill_resource", "Read one active Skill reference or text asset. Scripts cannot run.")
    def read_skill_resource(args: SkillResourceArgs, ctx: ToolContext) -> Mapping[str, Any]:
        if ctx.skills is None:
            return {"refused": "No Skill Catalog is configured"}
        try:
            return ctx.skills.read_resource(args.name, args.resource)
        except SkillRejected as error:
            return {"refused": str(error)}

    @registry.tool("listen", "Wait briefly for the person's next utterance. Silence is not consent.")
    def listen(args: NoArguments, ctx: ToolContext) -> Mapping[str, Any]:
        if ctx.listener is None:
            return ListeningResult(ListeningEnding.UNAVAILABLE).as_tool_result()
        return ctx.listener.listen(timeout_s=ctx.config.listen_timeout_s).as_tool_result()

    @registry.tool(
        "done",
        "Finish. Call this when nothing further is worth doing right now.",
        ends_episode=True,
    )
    def done(args: NoArguments, ctx: ToolContext) -> Mapping[str, Any]:
        return {}

    @registry.tool(
        "observe_target",
        "Cheaply refresh observable facts about the current anonymous target. "
        "This does not infer an emotion.",
    )
    def observe_target(
        args: NoArguments, ctx: ToolContext
    ) -> Mapping[str, Any]:
        return _about_the_target(
            ctx.active_perception.observe_target(now_s=ctx.clock.monotonic()),
            ctx,
        )

    @registry.tool(
        "inspect_scene",
        "Request a more expensive bounded scene inspection when selected "
        "target evidence is insufficient. This does not diagnose emotion.",
    )
    def inspect_scene(
        args: NoArguments, ctx: ToolContext
    ) -> Mapping[str, Any]:
        return _about_the_target(
            ctx.active_perception.inspect_scene(now_s=ctx.clock.monotonic()),
            ctx,
        )

    @registry.tool("speak", "Say something out loud.", speaks="text")
    def speak(args: SpeakArgs, ctx: ToolContext) -> Mapping[str, Any]:
        """Say it, and stop listening for exactly as long as saying it takes.

        The window is shut **before** the request goes out, not after it
        returns: `POST /tts/speak` is one round trip and Misty starts talking
        at the far end of it, so muting afterwards leaves a gap in which she
        can hear herself begin.

        And it covers the playback only. The script this replaces also
        `sleep`-ed for the same duration, so the whole action was deaf and
        anything the person said while the robot talked was lost — including
        "stop". That is the defect, and the fix is to mute without waiting
        (`PLAN.md` §15.29).
        """
        estimated_ms = estimate_speech_ms(args.text, ctx.config)
        ctx.ears.mute_for(estimated_ms / 1000.0)
        return {
            **_effected(ctx.robot.speak(args.text)),
            "estimated_speech_ms": estimated_ms,
        }

    @registry.tool("display_image", "Change the face on the screen.")
    def display_image(args: DisplayImageArgs, ctx: ToolContext) -> Mapping[str, Any]:
        return _effected(ctx.robot.display_image(EXPRESSION_IMAGES[args.expression]))

    @registry.tool("move_arms", "Move both arms to a position.")
    def move_arms(args: MoveArmsArgs, ctx: ToolContext) -> Mapping[str, Any]:
        return _effected(ctx.robot.move_arms(args.left, args.right))

    @registry.tool("move_head", "Point the head somewhere.")
    def move_head(args: MoveHeadArgs, ctx: ToolContext) -> Mapping[str, Any]:
        return _effected(ctx.robot.move_head(args.pitch, args.roll, args.yaw))

    @registry.tool("change_led", "Change the colour of the chest light.")
    def change_led(args: ChangeLedArgs, ctx: ToolContext) -> Mapping[str, Any]:
        return _effected(ctx.robot.change_led(args.red, args.green, args.blue))

    @registry.tool("play_audio", "Play one of the built-in sounds.")
    def play_audio(args: PlayAudioArgs, ctx: ToolContext) -> Mapping[str, Any]:
        return _effected(ctx.robot.play_audio(SOUND_FILES[args.sound], args.volume))

    @registry.tool(
        "approach",
        "Move closer to the person you can see, or step back if they are too "
        "near. Stops on its own.",
    )
    def approach(args: NoArguments, ctx: ToolContext) -> Mapping[str, Any]:
        """The whole of `PLAN.md` §4's layering claim, in six lines.

        The model says *whether*. Everything about *how far* — the step size,
        the direction, when to stop, what counts as a fresh reading — is M5's
        closed loop, and this does not touch any of it. Letting the model
        compute a velocity and a duration is the thing the README opens by
        criticising, and the way to make that impossible is to have nowhere
        to put them.

        The four states go back **as they are**. Compressing them to a
        boolean would leave the model unable to tell "they walked away" from
        "the robot refused to move", and those want different next Turns.

        The key is `result` rather than `status` because that is what the
        golden Journals say (`tests/goldens/`), and they were written first.
        """
        if ctx.config is None:
            # `run_approach` has a working default that passing `config=None`
            # would defeat, and the failure would surface as an AttributeError
            # from inside the control layer naming neither this Tool nor the
            # field. `PLAN.md` §10 #4 is about knobs that look connected and
            # are not; this is the same shape one layer up.
            raise ValueError(
                "approach needs ToolContext.config: the control layer reads "
                "its step size, timeouts and tolerances from it"
            )
        # Movement intent is about the active Interaction Target. A target
        # this Episode last saw missing is not approached on stale readings;
        # the model re-observes first. A speech-only Episode has no track to
        # lose and keeps the distance-reading behaviour.
        if ctx.target is not None and ctx.target.state is TargetState.LOST:
            # The same status the controller reports when the person is gone
            # (`PLAN.md` §15.4 keeps failures on its four statuses); the
            # target block beside it says the loss was already known.
            return {
                "result": ApproachStatus.LOST_USER.value,
                "steps": 0,
                "target": ctx.target.as_facts(),
            }
        outcome = run_approach(
            ctx.readings, ctx.robot, config=ctx.config, clock=ctx.clock
        )
        # `.value`, not the member: `ApproachStatus` is a str mixin, so it
        # compares and serialises identically and looks harmless — but
        # `TerminalRenderer` puts it in an f-string, where it prints
        # `ApproachStatus.ARRIVED` instead of `arrived`.
        answer = {"result": outcome.status.value, "steps": outcome.steps}
        if ctx.target is not None:
            answer["target"] = ctx.target.as_facts()
        return answer

    @registry.tool(
        "look_around",
        "Sweep the head from side to side to find who is nearby.",
    )
    def look_around(args: NoArguments, ctx: ToolContext) -> Mapping[str, Any]:
        """Turn the head until somebody is in view, and then stop turning.

        `PLAN.md` §15.2 cut `back_up` because two Tools doing one thing means
        the model picks wrong and the Journal cannot show why. This has to
        survive that same test against `move_head`, and only one thing makes
        it: it **looks while it turns**. `move_head` twice across two Turns
        would give the model a Snapshot at each angle and strictly more
        control — so a `look_around` that merely swept and recentred would be
        the worse of two Tools doing one job, and should have been cut.

        So it stops where it finds someone. The Snapshot ticket 07 appends is
        taken after the Tool returns, which means the head has to still be
        pointing at them for that Snapshot to be about them. A scan that swept
        back to centre would report `found_at_yaw` and then hand the model a
        Snapshot of an empty room.

        It reports the angle and nothing else. Distance and presence are
        already the Snapshot's, and §15.4 refuses to carry one fact twice.
        """
        settle_s = ctx.config.look_around_settle_s
        for yaw in SCAN_YAWS:
            turned = ctx.robot.move_head(0.0, 0.0, yaw)
            if not turned.ok:
                return {**_effected(turned), "found_at_yaw": None}
            ctx.clock.sleep(settle_s)
            if ctx.readings is not None and ctx.readings.latest_reading():
                return {"ok": True, "found_at_yaw": yaw}
        # Nobody anywhere: face forward again, so the next Turn starts from
        # the same place every other Tool assumes.
        centred = ctx.robot.move_head(0.0, 0.0, 0.0)
        ctx.clock.sleep(settle_s)
        return {**_effected(centred), "found_at_yaw": None}

    return registry


def _effected(effect: Effect) -> Dict[str, Any]:
    """An Effect as the Tool result the model reads: `ok`, and why not."""
    if effect.ok:
        return {"ok": True}
    return {"ok": False, "detail": effect.detail}


def _about_the_target(
    result: ActivePerceptionResult, ctx: ToolContext
) -> Mapping[str, Any]:
    """One perception result, plus the Episode target it updated."""
    answer = dict(result.as_tool_result())
    if ctx.target is not None:
        ctx.target.update_from(result)
        answer["target"] = ctx.target.as_facts()
    return answer

"""What a screen is told about an Episode, decided where pytest can reach it.

A `Storyboard` is a Journal arranged for drawing: records in, a serialisable
structure out, and JavaScript only paints it.

## Why the decision lives here and not in the browser

The obvious alternative is to hand a page the raw JSONL and let it work out
what each line means. That puts every choice about *what is shown* in a place
no test in this repo can see — and this project has already paid for that
once. `TerminalRenderer` printed `-> , 52cm away` for every Tool except
`approach`, through four commits, and nothing went red: the tests asserted on
the Journal, and the defect was in what was *shown* (`PLAN.md` §16.7).

## It is the sentence plus what the sentence leaves out

How one record reads is `journal.describe`'s answer, settled in M8 #02, and
this reuses it rather than writing a second one (`PLAN.md` §15.4). `Described`
is deliberately prose — a phrase, not a field dump — and it refused a `facts`
mapping at the time for having no caller.

This is the caller. `Moment.facts` is every field the record carries apart
from the three every record has, taken mechanically off the record itself, so
a kind that gains a field gains it here too and nobody has to remember. That
is also why the three criteria about *contents* — a refusal's reason, a model
call's cost, which of the four ways the Episode ended — need no code of their
own: they are fields, and the fields all come.

## The robot is folded, not described

`Moment.robot` is the whole robot after that record, not the change — a page
drawing record seven should not have to replay records one to six.

Two rules decide it, and both come from how `tools.py` actually behaves:

* **A pose is asked for by one record and confirmed by another.** `dispatch`
  validates first and records `ToolCalled` only on the way to the handler, so
  a refused call never produced one — but a call whose handler *raises* did,
  and is followed by `ExecutionFailed` and no Observation. So `ToolCalled`
  only makes the change pending; the Observation commits it. Otherwise a page
  shows a chest light that never lit, which is `-> , 52cm away` in a
  different medium.
* **A scan reports where it stopped.** `look_around` does not sweep back to
  centre — it stops on whoever it found, so the Snapshot afterwards is about
  that person — and it says where in its *result*, not its arguments. So the
  fold reads results as well.

`MOVES` names Tools by string, which couples this module to `tools.py` across
a gap no type checker crosses. `tests/test_storyboard.py` closes it from both
ends: every Tool named here must still exist, **and** every argument named
here must still be one that Tool takes — the first half alone let a renamed
argument stop the robot moving while the check stayed green.

The module is `storyboard.py` and not `view.py` because `CONTEXT.md` gives
*Storyboard* an _Avoid_ list with `view` on it. A file named for a word its
own glossary entry refuses is the glossary not being used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from misty_agent.robot import RobotPose
from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
    Observation,
    Record,
    ToolCalled,
    describe,
)

#: Fields the `Moment` already carries, so repeating them inside `facts`
#: would be the same value twice on one object (`PLAN.md` §15.4). `turn` is
#: here for that reason and not because every record has one — the ones that
#: do agree with `Moment.turn` exactly, and the ones that do not have theirs
#: filled in from the Turn they happened during.
_ALREADY_ON_THE_MOMENT = ("t", "episode_id", "type", "turn")

#: Fields lifted onto the `Storyboard` itself, by the kind that carries them.
#: Excluded from that record's `facts` for the same reason, and it is the same
#: rule: **one payload, one home for each value.** They were shipped twice for
#: one commit, five values free to disagree with themselves.
_LIFTED_TO_THE_STORYBOARD = {
    "episode_started": ("trigger", "started_at_wall_clock"),
    "episode_finished": ("outcome", "turns", "steps"),
}

#: Prose fields already used as the Moment's human-readable detail.
_DESCRIBED_ON_THE_MOMENT = {
    "decision_noted": ("note",),
}

#: The key `look_around` reports its stopping angle under. Read from the
#: result rather than assumed from the Tool's name, the way `_steps_in` reads
#: the Step count: a Tool that started reporting one would be handled, and a
#: Tool renamed cannot silently stop being handled.
FOUND_AT_YAW = "found_at_yaw"


#: What the robot looks like at one moment: the same pose the simulated
#: adapter holds, derived here from the Journal rather than read from it, so
#: a replay never depends on a robot object that has since moved on.
RobotState = RobotPose


#: How each Tool that changes the robot's appearance changes it: the argument
#: names it takes, and the `RobotState` field they land in. Only the four that
#: are *visible* — `approach` and `look_around` move the robot too, but where
#: it is standing is the Snapshot's business and is already carried there.
MOVES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "display_image": ("expression", ("expression",)),
    "change_led": ("led", ("red", "green", "blue")),
    "move_head": ("head", ("pitch", "roll", "yaw")),
    "move_arms": ("arms", ("left", "right")),
}


def _skill_status(active: Sequence[str]) -> str:
    """The replay caption for which Skills currently guide the Episode."""
    return "Active Skills: " + (", ".join(active) or "none (not loaded, or the Episode has ended)")


@dataclass(frozen=True)
class Moment:
    """One record, ready to draw, and the robot just after it."""

    t: float
    turn: Optional[int]
    kind: str
    headline: str
    detail: str
    tone: str
    robot: RobotState
    facts: Mapping[str, Any] = field(default_factory=dict)
    active_skills: Tuple[str, ...] = ()
    skill_status: str = _skill_status(())


#: How each ending reads to somebody who has not met this project's
#: vocabulary. `describe` gives the Journal's own sentence — "episode
#: turn_limit after 8 turn(s)" — which is right for a terminal and reads as a
#: raw enum on a page. This is the same fact said for a different reader, not
#: a second answer to what happened: the outcome it comes from is the one the
#: `Storyboard` already carries.
ENDINGS = {
    "done": "it decided it was finished",
    "turn_limit": "it ran out of turns before it ran out of ideas",
    "aborted": "somebody stopped it",
    "error": "something it depends on failed",
}


@dataclass(frozen=True)
class Storyboard:
    """One Episode, as a page is given it."""

    episode_id: str
    trigger: Optional[str]
    started_at: Optional[str]
    #: `None` while the Episode is still running — which is what a page
    #: watching a live run is holding.
    outcome: Optional[str]
    #: The same ending in words a visitor has met before. `None` while it is
    #: still running, for the same reason.
    ending: Optional[str]
    turns: int
    steps: int
    moments: Tuple[Moment, ...]


def storyboard_of(records: Sequence[Record]) -> Storyboard:
    """A Journal's records, arranged for a screen. Pure: no clock, no IO."""
    robot = RobotState()
    #: A pose the model asked for and the robot has not confirmed yet.
    pending: Optional[Dict[str, Any]] = None
    turn: Optional[int] = None
    moments = []
    active_skills: list[str] = []

    for record in records:
        if isinstance(record, Observation) and record.result.get("kind") == "skill_activation":
            name = record.result["name"]
            if name not in active_skills:
                active_skills.append(name)
        if isinstance(record, EpisodeFinished):
            active_skills.clear()
        robot, pending = _after(record, robot, pending)
        turn = getattr(record, "turn", None) or turn
        said = describe(record)
        moments.append(
            Moment(
                t=record.t,
                turn=turn,
                kind=record.type,
                headline=said.headline,
                detail=said.detail,
                tone=said.tone,
                robot=robot,
                facts=_facts(record),
                active_skills=tuple(active_skills),
                skill_status=_skill_status(active_skills),
            )
        )

    opening = next((r for r in records if isinstance(r, EpisodeStarted)), None)
    ending = next((r for r in records if isinstance(r, EpisodeFinished)), None)
    return Storyboard(
        episode_id=records[0].episode_id if records else "",
        trigger=opening.trigger if opening else None,
        started_at=opening.started_at_wall_clock if opening else None,
        outcome=ending.outcome if ending else None,
        ending=ENDINGS.get(ending.outcome) if ending else None,
        turns=ending.turns if ending else 0,
        steps=ending.steps if ending else 0,
        moments=tuple(moments),
    )


def _facts(record: Record) -> Dict[str, Any]:
    """Everything the record carries that is not already somewhere else here."""
    elsewhere = (
        _ALREADY_ON_THE_MOMENT
        + _LIFTED_TO_THE_STORYBOARD.get(record.type, ())
        + _DESCRIBED_ON_THE_MOMENT.get(record.type, ())
    )
    return {
        name: value
        for name, value in asdict(record).items()
        if name not in elsewhere
    }


def _after(
    record: Record, robot: RobotState, pending: Optional[Dict[str, Any]]
) -> Tuple[RobotState, Optional[Dict[str, Any]]]:
    """The robot once this record has happened, and what it is still promised.

    Asking is one record and arriving is another, so this returns both. A
    `ToolCalled` that never gets its Observation — the handler raised, and
    `ExecutionFailed` follows instead — leaves the robot where it was.
    """
    if isinstance(record, ToolCalled):
        if record.tool not in MOVES:
            return robot, None
        into, names = MOVES[record.tool]
        # `dispatch` records `arguments.model_dump()`, and pydantic fills every
        # default, so each of these names is always present. Reading them
        # directly rather than guarding says so: a missing one is a `KeyError`
        # naming the argument, not a robot that silently stops moving.
        asked = tuple(record.args[name] for name in names)
        return robot, {into: asked[0] if len(asked) == 1 else asked}

    if isinstance(record, Observation):
        # A behaviour the robot refused did not happen: the Observation
        # says so, and the pose stays where it was.
        refused = record.result.get("ok") is False
        if pending is not None and not refused:
            robot = replace(robot, **pending)
        if FOUND_AT_YAW in record.result and not refused:
            # A scan stops on whoever it found and stays pointed at them;
            # finding nobody puts the head back to centre, which is where
            # every other Tool assumes it starts. Both are `move_head` calls
            # the Tool makes itself, so neither is in `record.args`.
            robot = replace(
                robot, head=(0.0, 0.0, record.result[FOUND_AT_YAW] or 0.0)
            )
        return robot, None

    # Anything else — a failure, an abort, the Episode closing — drops the
    # promise. Only an Observation says the robot did it.
    return robot, pending if isinstance(record, ToolCalled) else None

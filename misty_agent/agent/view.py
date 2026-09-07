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

* **Arguments count only once they are recorded.** `dispatch` validates first
  and records `ToolCalled` only on the way to the handler, so a refused call
  never produced one. Reading a pose off `ToolRejected` would draw a head
  turned to the very angle the system rejected.
* **A scan reports where it stopped.** `look_around` does not sweep back to
  centre — it stops on whoever it found, so the Snapshot afterwards is about
  that person — and it says where in its *result*, not its arguments. So the
  fold reads results as well.

`MOVES` names Tools by string, which couples this module to `tools.py` across
a gap no type checker crosses; `tests/test_storyboard.py` closes it by
checking every name still exists in the registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
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

#: The key `look_around` reports its stopping angle under. Read from the
#: result rather than assumed from the Tool's name, the way `_steps_in` reads
#: the Step count: a Tool that started reporting one would be handled, and a
#: Tool renamed cannot silently stop being handled.
FOUND_AT_YAW = "found_at_yaw"


@dataclass(frozen=True)
class RobotState:
    """What the robot looks like at one moment.

    The defaults are the pose every Tool assumes it starts from: arms down,
    head level and forward, chest light off, neutral face.
    """

    expression: str = "neutral"
    led: Tuple[int, int, int] = (0, 0, 0)
    #: pitch, roll, yaw — the three `move_head` takes, in that order.
    head: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: left, right — 90 is down, which is where `move_arms` rests them.
    arms: Tuple[float, float] = (90.0, 90.0)


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


@dataclass(frozen=True)
class Storyboard:
    """One Episode, as a page is given it."""

    episode_id: str
    trigger: Optional[str]
    started_at: Optional[str]
    #: `None` while the Episode is still running — which is what a page
    #: watching a live run is holding.
    outcome: Optional[str]
    turns: int
    steps: int
    moments: Tuple[Moment, ...]


def storyboard_of(records: Sequence[Record]) -> Storyboard:
    """A Journal's records, arranged for a screen. Pure: no clock, no IO."""
    robot = RobotState()
    turn: Optional[int] = None
    moments = []

    for record in records:
        robot = _after(record, robot)
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
            )
        )

    opening = next((r for r in records if isinstance(r, EpisodeStarted)), None)
    ending = next((r for r in records if isinstance(r, EpisodeFinished)), None)
    return Storyboard(
        episode_id=records[0].episode_id if records else "",
        trigger=opening.trigger if opening else None,
        started_at=opening.started_at_wall_clock if opening else None,
        outcome=ending.outcome if ending else None,
        turns=ending.turns if ending else 0,
        steps=ending.steps if ending else 0,
        moments=tuple(moments),
    )


def _facts(record: Record) -> Dict[str, Any]:
    """Everything the record carries that the `Moment` does not already say."""
    return {
        name: value
        for name, value in asdict(record).items()
        if name not in _ALREADY_ON_THE_MOMENT
    }


def _after(record: Record, robot: RobotState) -> RobotState:
    """The robot once this record has happened."""
    if isinstance(record, ToolCalled) and record.tool in MOVES:
        into, names = MOVES[record.tool]
        given = tuple(record.args[name] for name in names if name in record.args)
        if len(given) == len(names):
            return replace(robot, **{into: given[0] if len(given) == 1 else given})
        return robot

    found = _facts(record).get("result", {})
    if isinstance(found, Mapping) and FOUND_AT_YAW in found:
        # A scan stops on whoever it found and stays pointed at them; finding
        # nobody puts the head back to centre, which is where every other Tool
        # assumes it starts.
        return replace(robot, head=(0.0, 0.0, found[FOUND_AT_YAW] or 0.0))
    return robot

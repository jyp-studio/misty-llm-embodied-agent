"""What must hold about an Episode however the model chose to phrase itself.

A live-model test cannot assert what the model *said* — that is the thing that
legitimately varies, and a test that pinned it would be red every time the
model was upgraded. What it can assert is everything the model is not allowed
to break, and those are the same properties the offline suite already checks.

That sharing is the point. These checks run against the scripted Episodes in
`tests/test_react.py` as well as against live ones, so their teeth are proven
without spending anything: if a check cannot fail, it will not start failing
just because a real model is on the other end.

A helper file in `tests/`, for the reason `journal_diff.py` gives — comparing
and checking Journals is a testing concern with no production caller, and
`PLAN.md` §15.5 turned down giving the Journal module more reasons to change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from pydantic import ValidationError

from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
    ModelCalled,
    Observation,
    Record,
    ToolCalled,
    ToolRejected,
    TurnStarted,
    from_jsonl,
    to_jsonl,
)
from misty_agent.agent.tools import ToolRegistry

#: Spellings that must never reach the model.
#:
#: Deliberately *not* imported from `layering.py`: this is auditing that guard,
#: and sharing its definition would make the two agree by construction. But an
#: independent list is only worth having if it is at least as strict, and the
#: first hand-written version was not — `speed`, `driveSpeed`, `cmPerSec` and
#: `driveDuration` all passed the audit while failing the guard, which is
#: `PLAN.md` §10's "two copies silently diverge" happening inside the file
#: meant to catch it. `test_the_audit_is_at_least_as_strict_as_the_guard`
#: keeps them in step without letting them share a definition.
FORBIDDEN_IN_PROMPT = (
    "velocity", "speed", "cmpersec", "mmpersec", "degpersec",
    "degreespersec", "radpersec",
    "timems", "drivems", "drivetime", "driveduration", "drivetimems",
)


def _flatten(text: str) -> str:
    """Lowercase and drop the separators that distinguish one spelling of a
    control parameter from another. `linearVelocity`, `linear_velocity` and
    `LINEAR-VELOCITY` are the same word to a reader and must be to this."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Episode:
    """Everything an invariant might need to look at."""

    records: Sequence[Record]
    turn_cap: int
    #: Every working context the model was handed, one per Turn.
    prompts: Sequence[Sequence[Mapping[str, Any]]] = ()
    #: The Tool schemas it was shown.
    tools: Sequence[Mapping[str, Any]] = ()
    #: The recording robot, if the caller kept one.
    robot: Optional[Any] = None
    registry: Optional[ToolRegistry] = None


def ends_exactly_once(episode: Episode) -> List[str]:
    """`CONTEXT.md` defines an Episode as having bounded termination."""
    records = list(episode.records)
    problems = []
    if not records:
        return ["the Episode produced no records at all"]
    if not isinstance(records[0], EpisodeStarted):
        problems.append(f"the first record is a {records[0].type}, not a start")
    endings = [r for r in records if isinstance(r, EpisodeFinished)]
    if len(endings) != 1:
        problems.append(f"the Episode ended {len(endings)} times")
    elif records[-1] is not endings[0]:
        problems.append(
            f"{records[-1].type} was recorded after the Episode had ended"
        )
    return problems


def stays_within_the_turn_cap(episode: Episode) -> List[str]:
    """The strongest property the system has (`PLAN.md` §4), and the one ReAct
    is most likely to lose."""
    problems = []
    turns = [r.turn for r in episode.records if isinstance(r, TurnStarted)]
    if turns and max(turns) > episode.turn_cap:
        problems.append(f"Turn {max(turns)} began, past a cap of {episode.turn_cap}")
    if turns != list(range(1, len(turns) + 1)):
        problems.append(f"Turns were numbered {turns}")
    calls = sum(isinstance(r, ModelCalled) for r in episode.records)
    if calls > episode.turn_cap:
        problems.append(f"the model was called {calls} times for {episode.turn_cap}")
    return problems


def no_physical_parameter_reached_the_model(episode: Episode) -> List[str]:
    """`PLAN.md` §4's layering claim, checked on the bytes that went over.

    Not on the Tools' signatures: those can be clean while a result, a refusal
    reason or a Snapshot carries one.
    """
    problems = []
    handed_over = _flatten(
        json.dumps(
            [list(prompt) for prompt in episode.prompts] + list(episode.tools),
            default=str,
        )
    )
    for forbidden in FORBIDDEN_IN_PROMPT:
        if forbidden in handed_over:
            problems.append(f"the model was shown {forbidden!r}")
    return problems


def every_tool_call_was_in_range(episode: Episode) -> List[str]:
    """Re-validate what the Journal says was run, against the Tools' own types.

    A second pass over the same argument models `dispatch` used. It cannot
    catch a bug they share, but it does catch a Tool call reaching the robot
    without having been through them.
    """
    if episode.registry is None:
        return []
    problems = []
    for record in episode.records:
        if not isinstance(record, ToolCalled):
            continue
        tool = episode.registry.get(record.tool)
        if tool is None:
            problems.append(f"{record.tool!r} ran but is not registered")
            continue
        try:
            tool.args_model.model_validate(dict(record.args), strict=False)
        except ValidationError as error:
            problems.append(f"{record.tool}({record.args}) is out of range: {error}")
    return problems


def every_drive_came_from_approach(episode: Episode) -> List[str]:
    """`approach` is the only Tool that may move the base, and it may only do
    it through M5's controller.

    Counted rather than asserted structurally: the Journal says how many Steps
    `approach` reported, and the robot says how many drives were actually
    issued — the simulated adapter from the directions it drove, the real
    adapter from the requests its transport recorded. If any other route
    reached the base, the two differ.
    """
    robot = episode.robot
    if robot is None:
        return []
    if hasattr(robot, "directions"):
        drives = list(robot.directions)
    elif hasattr(robot, "commands"):
        drives = [
            request for request in getattr(robot.commands, "requests", [])
            if request.endpoint == "drive/time"
        ]
    else:
        return []
    ending = next(
        (r for r in episode.records if isinstance(r, EpisodeFinished)), None
    )
    if ending is None:
        return []
    # `EpisodeFinished.steps`, not `result["steps"]`. `PLAN.md` §15.20 put that
    # string in exactly one place — `tools.py`'s `STEPS_KEY`, read by
    # `dispatch` — precisely so that nothing downstream would go digging for it
    # again. Reaching into the result dict here would have been a second copy
    # of the same fact, in the file whose job is to notice such things.
    if len(drives) != ending.steps:
        return [
            f"{len(drives)} drive commands were issued but the Episode "
            f"reported {ending.steps} Steps — something moved the base "
            f"outside the controller"
        ]
    return []


def the_journal_survives_being_written_down(episode: Episode) -> List[str]:
    """A Journal that cannot round-trip is a Journal nobody can keep."""
    records = list(episode.records)
    try:
        restored = list(from_jsonl(to_jsonl(records)))
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return [f"the Journal could not be written and read back: {error}"]
    return [] if restored == records else ["the Journal changed on a round trip"]


def a_refusal_is_never_treated_as_success(episode: Episode) -> List[str]:
    """A refused call produces no Observation (`PLAN.md` §15.4) — otherwise the
    model reads the same Turn as both refused and done."""
    refused = {r.turn for r in episode.records if isinstance(r, ToolRejected)}
    observed = {r.turn for r in episode.records if isinstance(r, Observation)}
    overlap = sorted(refused & observed)
    return (
        [f"Turn(s) {overlap} were both refused and observed"] if overlap else []
    )


#: Every check, in the order a reader would want them.
CHECKS: Tuple[Tuple[str, Callable[[Episode], List[str]]], ...] = (
    ("ends exactly once", ends_exactly_once),
    ("stays within the Turn cap", stays_within_the_turn_cap),
    ("no physical parameter reached the model", no_physical_parameter_reached_the_model),
    ("every Tool call was in range", every_tool_call_was_in_range),
    ("every drive came from approach", every_drive_came_from_approach),
    ("the Journal survives being written down", the_journal_survives_being_written_down),
    ("a refusal is never treated as success", a_refusal_is_never_treated_as_success),
)


def violations(episode: Episode) -> List[str]:
    """Everything wrong with this Episode, or an empty list."""
    found: List[str] = []
    for name, check in CHECKS:
        found.extend(f"{name}: {problem}" for problem in check(episode))
    return found

"""What happened during one Episode, written down as it happens.

A Journal is a sequence of typed records. It feeds three things that were
decided separately and turn out to want the same data (`PLAN.md` §4): the
assertion target for tests of the agent's behaviour, the measurement of Turn
counts and latency, and a future interface that is only another subscriber.

## The typed records are the contract

JSONL is a *serialisation format*, not the contract. Code that consumes a
Journal should consume records; the text form exists so a run can be kept,
diffed against a golden, and read by someone without this package installed.

**The schema is not stable before M10** (`PLAN.md` §15.3). This is a portfolio
piece, not a published API, and freezing it early would buy a compatibility
obligation nobody is asking for. The version travels on the opening record —
one Journal is one Episode, and the file is read whole.

## Two things the shape is careful about

**`turn` is not a base field.** The opening record has no Turn. Making it a
base field would put an Optional on every record, and every reader would have
to handle a None that cannot occur on the records they care about.

**Time is seconds since this Episode began, from an injectable monotonic
clock.** Not decoration: golden Journals are compared byte for byte, which an
absolute timestamp makes impossible. The one absolute stamp lives on the
opening record so a human can still place the run in real time.

## The line these records must not cross

`PLAN.md` §4's layering claim is that the model decides *whether* to approach
and the control layer decides *how far* each Step goes. A velocity or a drive
duration appearing in a record would make that claim false in exactly the
artefact a reader would check it against. `tests/test_journal.py` asserts that
no record kind declares such a field and that no serialised Journal mentions
one.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence, Tuple, Type

#: What this Journal's shape is called today. The `unstable` is load-bearing:
#: it tells a reader the schema will move before M10, and it is asserted.
JOURNAL_SCHEMA = "0.1.0-unstable"

#: How finely `t` is recorded. Milliseconds: fine enough for a loop whose
#: Turns take seconds, coarse enough that a golden does not go red on
#: floating-point noise.
TIME_PLACES = 3


class Clock(Protocol):
    """The same shape the approach loop already injects."""

    def monotonic(self) -> float: ...


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


class EpisodeClock:
    """Seconds since this Episode began.

    Takes its origin at construction, so an Episode's first record is at 0.0
    whatever the process has been doing beforehand.
    """

    def __init__(self, clock: Optional[Clock] = None) -> None:
        self._clock = clock or _SystemClock()
        self._origin = self._clock.monotonic()

    def elapsed_s(self) -> float:
        return round(self._clock.monotonic() - self._origin, TIME_PLACES)


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class _Record:
    """The three fields every record carries. `turn` is deliberately absent."""

    t: float
    episode_id: str

    #: Set by each subclass. Also the key `from_jsonl` dispatches on.
    #:
    #: Every record is keyword-only, so a required field never has to carry an
    #: invented default just to satisfy dataclass ordering. `ToolCalled` with
    #: no `args` is a construction error, not a record with `None` in a field
    #: typed as a mapping.
    type: str = "record"


@dataclass(frozen=True, kw_only=True)
class EpisodeStarted(_Record):
    """An Episode began, and what set it off.

    Carries the only absolute timestamp in the Journal, and the schema version.
    """

    trigger: str
    started_at_wall_clock: str
    schema: str = JOURNAL_SCHEMA
    type: str = "episode_started"


@dataclass(frozen=True, kw_only=True)
class TurnStarted(_Record):
    """One iteration of the ReAct loop began."""

    turn: int
    type: str = "turn_started"


@dataclass(frozen=True, kw_only=True)
class ModelCalled(_Record):
    """The model was asked what to do, and how long it took to answer."""

    turn: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    type: str = "model_called"


@dataclass(frozen=True, kw_only=True)
class ToolCalled(_Record):
    """The model chose a Tool, and what it passed to it."""

    turn: int
    tool: str
    args: Mapping[str, Any]
    type: str = "tool_called"


@dataclass(frozen=True, kw_only=True)
class ToolRejected(_Record):
    """A Tool call was refused before it reached the robot, and why.

    Kept as its own kind rather than folded into an Observation: a refusal is
    something the *agent* did wrong, and counting those separately is the point
    of validating arguments at all.
    """

    turn: int
    tool: str
    reason: str
    type: str = "tool_rejected"


@dataclass(frozen=True, kw_only=True)
class Observation(_Record):
    """What came back: the Tool's own result, plus the Snapshot."""

    turn: int
    payload: Mapping[str, Any]
    type: str = "observation"


@dataclass(frozen=True, kw_only=True)
class StopRequested(_Record):
    """Someone asked for an emergency stop, at the moment they asked.

    Separate from `EpisodeAborted` on purpose. This one is written by whichever
    thread noticed; the abort is written by the loop as it unwinds. The gap
    between the two **is** the interrupt latency, and it is the reason writing
    takes a lock rather than queueing for the main loop (`PLAN.md` §15.3).
    """

    source: str
    type: str = "stop_requested"


@dataclass(frozen=True, kw_only=True)
class EpisodeAborted(_Record):
    """The loop gave up because it was told to."""

    reason: str
    type: str = "episode_aborted"


@dataclass(frozen=True, kw_only=True)
class EpisodeFinished(_Record):
    """The Episode ended, however it ended.

    One terminal kind rather than one per outcome, so "every Episode ends
    exactly once" stays a property a reader can check by counting.

    `turns` and `steps` are both here and they are different things: a Turn is
    one model decision, a Step is one drive command. A single Turn that calls
    `approach` may produce several Steps.
    """

    outcome: str
    turns: int
    steps: int
    type: str = "episode_finished"


#: Every kind, keyed by the string that identifies it on the wire. Closed on
#: purpose: `from_jsonl` refuses anything not in here rather than skipping it,
#: because a silently dropped line makes a truncated Journal look complete.
RECORD_TYPES: Dict[str, Type[_Record]] = {
    record_type.__dataclass_fields__["type"].default: record_type
    for record_type in (
        EpisodeStarted,
        TurnStarted,
        ModelCalled,
        ToolCalled,
        ToolRejected,
        Observation,
        StopRequested,
        EpisodeAborted,
        EpisodeFinished,
    )
}


# ---------------------------------------------------------------------------
# Serialisation — pure: records in, text out
# ---------------------------------------------------------------------------

def to_jsonl(records: Sequence[_Record]) -> str:
    """One record per line. No IO, no clock."""
    return "".join(
        json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def from_jsonl(text: str) -> Tuple[_Record, ...]:
    """Read records back. Refuses what it does not recognise."""
    records = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number} is not JSON: {error}") from error

        kind = raw.get("type")
        record_type = RECORD_TYPES.get(kind)
        if record_type is None:
            raise ValueError(f"line {number} has an unknown record type {kind!r}")

        expected = {field.name for field in fields(record_type)}
        missing = expected - set(raw)
        if missing:
            raise ValueError(
                f"line {number} ({kind}) is missing {sorted(missing)}"
            )
        unexpected = set(raw) - expected
        if unexpected:
            raise ValueError(
                f"line {number} ({kind}) has unexpected {sorted(unexpected)}"
            )
        records.append(record_type(**raw))
    return tuple(records)

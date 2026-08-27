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
#:
#: **It is also a floor on what can be measured.** The gap between a stop being
#: requested and the Episode unwinding is the interrupt latency, and this
#: rounding means anything under a millisecond reads as zero. Say so rather
#: than let a reader take a 0.0 for an instantaneous abort.
TIME_PLACES = 3

#: Outcomes an Episode may end with. Three, not four: the spec names four
#: *scenarios* to keep goldens for, and two of them — ending on the first Turn
#: and ending after several — are both the model choosing to stop.
OUTCOMES = ("done", "turn_limit", "aborted")

#: Keys that must never appear in a Tool's arguments or an Observation.
#:
#: `PLAN.md` §4's layering claim is that the model decides *whether* to
#: approach and the control layer decides *how far* each Step goes. Arguments
#: and payloads are free-form mappings filled in by later tickets, so they are
#: the one route by which that claim could quietly become false — and the
#: Journal is the artefact a reader would check it against. Screened at
#: construction, not at serialisation: a record that should not exist should
#: not be constructible.
FORBIDDEN_KEYS = frozenset(
    {
        "velocity",
        "linearvelocity",
        "angularvelocity",
        "timems",
        "time_ms",
        "drive_ms",
        "cm_per_sec",
    }
)

#: What a mapping field may contain. Anything else does not survive JSON: a
#: tuple comes back as a list and quietly breaks equality against a golden.
JSON_TYPES = (str, int, float, bool, type(None), list, dict)


class Clock(Protocol):
    """Deliberately narrower than the control layer's.

    `misty_agent.control.approach` injects a clock with both `monotonic` and
    `sleep`. A Journal never waits, so asking for `sleep` here would make
    every caller supply a method this module cannot use. Any object that
    satisfies that protocol satisfies this one.
    """

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

def _screen(where: str, mapping: Mapping[str, Any]) -> None:
    """Refuse a mapping that would make the Journal lie, or fail to round-trip."""
    for key, value in mapping.items():
        if key.lower().replace("_", "") in {
            forbidden.replace("_", "") for forbidden in FORBIDDEN_KEYS
        }:
            raise ValueError(
                f"{where} may not carry {key!r}: physical control parameters "
                f"are the control layer's, and a Journal that recorded one "
                f"would contradict PLAN.md §4's layering claim"
            )
        if not isinstance(value, JSON_TYPES):
            raise ValueError(
                f"{where}[{key!r}] is a {type(value).__name__}, which does not "
                f"survive JSON — it would come back as something else and "
                f"break a golden comparison silently"
            )
        if isinstance(value, dict):
            _screen(f"{where}[{key!r}]", value)


@dataclass(frozen=True, kw_only=True)
class Record:
    """The two fields every record carries. `turn` is deliberately absent."""

    t: float
    episode_id: str

    #: Set by each subclass, and the key `from_jsonl` dispatches on. **No
    #: default here**: a subclass that forgets to name itself is then a
    #: construction error rather than a record that serialises as `"record"`.
    #:
    #: Every record is keyword-only, so a required field never has to carry an
    #: invented default just to satisfy dataclass ordering.
    type: str


@dataclass(frozen=True, kw_only=True)
class EpisodeStarted(Record):
    """An Episode began, and what set it off.

    Carries the only absolute timestamp in the Journal, and the schema version.
    """

    trigger: str
    started_at_wall_clock: str
    schema: str = JOURNAL_SCHEMA
    type: str = "episode_started"


@dataclass(frozen=True, kw_only=True)
class TurnStarted(Record):
    """One iteration of the ReAct loop began."""

    turn: int
    type: str = "turn_started"


@dataclass(frozen=True, kw_only=True)
class ModelCalled(Record):
    """The model was asked what to do, and how long it took to answer."""

    turn: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    type: str = "model_called"


@dataclass(frozen=True, kw_only=True)
class ToolCalled(Record):
    """The model chose a Tool, and what it passed to it."""

    turn: int
    tool: str
    args: Mapping[str, Any]
    type: str = "tool_called"

    def __post_init__(self) -> None:
        _screen(f"{self.tool} arguments", self.args)


@dataclass(frozen=True, kw_only=True)
class ToolRejected(Record):
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
class Snapshot:
    """What the world looked like, in the three facts that are already free.

    Exactly three, and that is the definition rather than a starting point
    (`PLAN.md` §15.4): distance, presence and new speech are all being computed
    anyway, so attaching them to every Observation costs no model call and no
    waiting. Richer perception is a Tool the model can choose to call, not a
    wider Snapshot — widening it would make every Turn pay that cost.

    A type rather than a loose mapping so that "a Snapshot is these three
    facts" is something a test can check.
    """

    distance_cm: Optional[int]
    face_present: bool
    new_speech: Optional[str]


@dataclass(frozen=True, kw_only=True)
class Observation(Record):
    """What came back: the Tool's own result, and the Snapshot beside it.

    Two fields, not one bag. The result varies per Tool and is open; the
    Snapshot is the same for every Tool and is closed. Collapsing them would
    hide which half is which.
    """

    turn: int
    result: Mapping[str, Any]
    snapshot: Snapshot
    type: str = "observation"

    def __post_init__(self) -> None:
        _screen("an Observation result", self.result)


@dataclass(frozen=True, kw_only=True)
class StopRequested(Record):
    """Someone asked for an emergency stop, at the moment they asked.

    Separate from `EpisodeAborted` on purpose. This one is written by whichever
    thread noticed; the abort is written by the loop as it unwinds. The gap
    between the two **is** the interrupt latency, and it is the reason writing
    takes a lock rather than queueing for the main loop (`PLAN.md` §15.3).
    """

    source: str
    type: str = "stop_requested"


@dataclass(frozen=True, kw_only=True)
class EpisodeFinished(Record):
    """The Episode ended, however it ended.

    One terminal kind rather than one per outcome, so "every Episode ends
    exactly once" stays a property a reader can check by counting.

    `turns` and `steps` are both here and they are different things: a Turn is
    one model decision, a Step is one drive command. A single Turn that calls
    `approach` may produce several Steps.

    An abort ends the Episode through this record too, with
    `outcome="aborted"`. There is no separate abort record: the *request* is
    already its own kind, and adding a third would store the same reason twice
    and make "an Episode ends exactly once" something you had to reason about
    rather than count.
    """

    outcome: str
    turns: int
    steps: int
    type: str = "episode_finished"

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(
                f"unknown outcome {self.outcome!r}; an Episode ends one of "
                f"{OUTCOMES}"
            )


#: Every kind, keyed by the string that identifies it on the wire. Closed on
#: purpose: `from_jsonl` refuses anything not in here rather than skipping it,
#: because a silently dropped line makes a truncated Journal look complete.
RECORD_TYPES: Dict[str, Type[Record]] = {
    record_type.__dataclass_fields__["type"].default: record_type
    for record_type in (
        EpisodeStarted,
        TurnStarted,
        ModelCalled,
        ToolCalled,
        ToolRejected,
        Observation,
        StopRequested,
        EpisodeFinished,
    )
}


# ---------------------------------------------------------------------------
# Serialisation — pure: records in, text out
# ---------------------------------------------------------------------------

def to_jsonl(records: Sequence[Record]) -> str:
    """One record per line. No IO, no clock."""
    return "".join(
        json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def from_jsonl(text: str) -> Tuple[Record, ...]:
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

        if record_type is Observation and isinstance(raw.get("snapshot"), dict):
            try:
                raw = {**raw, "snapshot": Snapshot(**raw["snapshot"])}
            except TypeError as error:
                raise ValueError(
                    f"line {number} has a malformed snapshot: {error}"
                ) from error

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

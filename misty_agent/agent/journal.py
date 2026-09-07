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
artefact a reader would check it against. What counts as one is `layering.py`'s
to define — the same rule also refuses to let a Tool *declare* one, and a rule
with two implementations is the thing `PLAN.md` §10 is about.
`tests/test_journal.py` asserts that no record kind declares such a field and
that no serialised Journal mentions one.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from dataclasses import asdict, dataclass, fields
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
    Union,
)

from misty_agent.agent.layering import (
    mentions_control_parameter,
    refuse_control_parameters,
)

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

#: Outcomes an Episode may end with. The original three cover intentional
#: endings; ``error`` is the involuntary close used when an external
#: collaborator raises inside the bounded loop.
#:
#: Three, not four, *intentional* outcomes: the spec names four
#: *scenarios* to keep goldens for, and two of them — ending on the first Turn
#: and ending after several — are both the model choosing to stop.
OUTCOMES = ("done", "turn_limit", "aborted", "error")

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

def _screen(where: str, mapping: Mapping[str, Any], *, commanded: bool) -> None:
    """Refuse a mapping that would make the Journal lie, or fail to round-trip.

    Arguments and payloads are free-form mappings filled in by later tickets,
    so they are the one route by which `PLAN.md` §4's layering claim could
    quietly become false — and the Journal is the artefact a reader would
    check it against. What counts as crossing that line is `layering.py`'s to
    say, not the Journal's, and `commanded` is how this record says whether
    the model picked these keys or the system is reporting them. Screened at
    construction rather than at serialisation: a record that should not exist
    should not be constructible.
    """
    for key, value in mapping.items():
        refuse_control_parameters(where, (key,), commanded=commanded)
        if not isinstance(value, JSON_TYPES):
            raise ValueError(
                f"{where}[{key!r}] is a {type(value).__name__}, which does not "
                f"survive JSON — it would come back as something else and "
                f"break a golden comparison silently"
            )
        if isinstance(value, dict):
            _screen(f"{where}[{key!r}]", value, commanded=commanded)


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
        # The model chose these, so a duration here is the model driving.
        _screen(f"{self.tool} arguments", self.args, commanded=True)


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

    def __post_init__(self) -> None:
        # The one record whose payload is a sentence rather than a mapping,
        # so `_screen` cannot reach it — and the one place the model's own
        # rejected argument names would otherwise be repeated back verbatim.
        offending = mentions_control_parameter(self.reason)
        if offending is not None:
            raise ValueError(
                f"a refusal may not say {offending!r}: repeating a control "
                f"parameter back to the model puts it in the Journal and in "
                f"the model's next Observation, which is exactly where "
                f"PLAN.md §4's layering claim is read"
            )


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
        # The system is reporting these back, so `estimated_speech_ms` is a
        # measurement rather than a command (`PLAN.md` §15.4).
        _screen("an Observation result", self.result, commanded=False)


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
class ExecutionFailed(Record):
    """An external collaborator failed while an Episode was running.

    This is evidence about the failure, not a second terminal record. The
    following :class:`EpisodeFinished` remains the one record a reader counts
    to decide whether the Episode closed.
    """

    phase: str
    error_type: str
    message: str
    type: str = "execution_failed"

    def __post_init__(self) -> None:
        offending = mentions_control_parameter(self.message)
        if offending is not None:
            raise ValueError(
                f"an execution failure may not say {offending!r}: failure "
                f"diagnostics share the Journal's control-layer boundary"
            )


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


@dataclass(frozen=True, kw_only=True)
class SubscriberFailed(Record):
    """A subscriber threw, recorded *into* the Journal rather than beside it.

    Keeping failures only in memory left an on-disk Journal silently
    incomplete — which is the one failure this module exists to make
    impossible. Fanned out to every subscriber except the one that just
    failed, and a failure while recording a failure is not recorded again.
    """

    subscriber: str
    failed_on: str
    error: str
    type: str = "subscriber_failed"


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
        ExecutionFailed,
        SubscriberFailed,
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


# ---------------------------------------------------------------------------
# Writing
#
# Everything above is data. This is the part that runs while an Episode does.
# ---------------------------------------------------------------------------

class Subscriber(Protocol):
    """Anything that wants to see records as they happen."""

    def receive(self, record: Record) -> None: ...


@dataclass(frozen=True)
class SubscriberFailure:
    """A subscriber that threw, kept rather than swallowed.

    A renderer falling over must not strand the robot mid-approach, so the
    exception is caught. But swallowing it silently would let a Journal be
    quietly incomplete, and "quietly incomplete" is the failure this whole
    package exists to make impossible.
    """

    t: float
    subscriber: str
    record_type: str
    error: str


class Journal:
    """Records what happened, and hands each record to every subscriber.

    **The Journal stamps the time, not the caller.** Making `t` an argument
    would leave "when did this happen" to nine call sites, and the one that
    got it wrong would be the emergency stop. The same goes for `episode_id`
    and for the record's own `type`: a caller that could set them could write
    a line whose discriminator lies.

    **The stamp is taken before either lock.** A record blocked behind another
    thread must keep the time it happened, not the time it finished waiting.
    On the stop path that is the difference between measuring an interrupt and
    measuring a mutex — and it is why writing takes a lock at all rather than
    queueing for the main loop (`PLAN.md` §15.3).

    **Two locks, not one.** The record lands in memory under a short lock of
    its own, so a subscriber that hangs cannot stop the Journal from *knowing*
    what happened. Fan-out then runs under a reentrant lock, so a subscriber
    may call back into the Journal — read `records`, or record something of
    its own — without deadlocking. `PLAN.md` §4 invites exactly such a
    subscriber when it calls terminal output "one renderer among others".

    ## What a subscriber must not do

    **Block.** Fan-out is synchronous and serialised, so a subscriber that
    waits on something slow makes every other thread wait too — including the
    one carrying an emergency stop. Nothing here can interrupt a call that
    refuses to return; a subscriber that may block must do its waiting
    somewhere else. This is a stated limit, not a solved problem, and it would
    be settled by giving each subscriber its own thread with a bounded queue —
    at the cost of the ordering guarantee below.

    A subscriber may assume it is **never called concurrently**. That is what
    the fan-out lock buys, and it is why neither shipped subscriber has to be
    thread-safe on its own.
    """

    #: Fields the Journal fills in. A caller that passed one could write a
    #: record whose type, time or Episode disagreed with reality.
    RESERVED = ("t", "episode_id", "type")

    def __init__(
        self,
        episode_id: str,
        *,
        clock: Optional[Clock] = None,
        wall_clock: Optional[Any] = None,
        subscribers: Sequence["Subscriber"] = (),
    ) -> None:
        self._episode_id = episode_id
        self._clock = EpisodeClock(clock)
        self._wall_clock = wall_clock or _wall_clock_now
        self._records_lock = threading.Lock()
        self._lock = threading.RLock()
        self._subscribers = tuple(subscribers)
        self._records: List[Record] = []
        self._failures: List[SubscriberFailure] = []
        self._finished = False

    def record(self, kind: Type[Record], **fields: Any) -> Record:
        """Write one record, now."""
        reserved = [name for name in self.RESERVED if name in fields]
        if reserved:
            raise ValueError(
                f"{sorted(reserved)} belong to the Journal, not the caller: a "
                f"record that could name its own type or time could disagree "
                f"with what happened"
            )
        t = self._clock.elapsed_s()

        if kind is EpisodeStarted:
            fields.setdefault("started_at_wall_clock", self._wall_clock())

        with self._records_lock:
            if self._finished:
                raise ValueError(
                    "this Episode has already finished; an Episode ends "
                    "exactly once, and a record after the end would make that "
                    "something you had to reason about rather than count"
                )
            record = kind(t=t, episode_id=self._episode_id, **fields)
            self._records.append(record)
            self._finished = isinstance(record, EpisodeFinished)

        self._fan_out(record, skip=None)
        return record

    def _fan_out(self, record: Record, *, skip: Optional[str]) -> None:
        failures = []
        with self._lock:
            for subscriber in self._subscribers:
                name = type(subscriber).__name__
                if name == skip:
                    continue
                try:
                    subscriber.receive(record)
                except Exception as error:  # noqa: BLE001
                    # `Exception`, not `BaseException`: a subscriber raising
                    # KeyboardInterrupt is the operator asking to stop, and
                    # swallowing that would make the程式 unkillable from a
                    # renderer. It propagates on purpose.
                    failures.append((name, str(error)))

        # Recorded after the fan-out so a failure cannot recurse into itself.
        for name, error in failures:
            self._note_failure(record, name, error)

    def _note_failure(self, on: Record, subscriber: str, error: str) -> None:
        t = self._clock.elapsed_s()
        failure = SubscriberFailure(
            t=t, subscriber=subscriber, record_type=on.type, error=error
        )
        with self._records_lock:
            self._failures.append(failure)
            noted = SubscriberFailed(
                t=t,
                episode_id=self._episode_id,
                subscriber=subscriber,
                failed_on=on.type,
                error=error,
            )
            self._records.append(noted)
        # Everyone but the subscriber that just fell over, and no failure
        # recorded for a failure — otherwise a broken subscriber loops.
        self._fan_out(noted, skip=subscriber)

    @property
    def records(self) -> Tuple[Record, ...]:
        # Taken under the record lock, and **no test distinguishes that from
        # taking it without**: `tuple(list)` is a C-level copy, so under
        # CPython this cannot tear however hard a writer is appending. It is
        # here for the day the store stops being a plain list, and it is
        # recorded as untested rather than left to look proven. The same is
        # true of `subscriber_failures` below.
        with self._records_lock:
            return tuple(self._records)

    @property
    def subscriber_failures(self) -> Tuple[SubscriberFailure, ...]:
        with self._records_lock:
            return tuple(self._failures)

    def to_jsonl(self) -> str:
        return to_jsonl(self.records)


def _wall_clock_now() -> str:
    """When this Episode began, for a human. Injectable so goldens can pin it."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class JsonlFile:
    """Appends each record to a file, one line at a time.

    Appending rather than writing at the end: an Episode that is interrupted
    should still leave behind what it got through.

    ## The file is created here, exclusively, and that is two guarantees

    `open(path, "x")` fails if anything is already there, and fails now if the
    path cannot be written at all. Both matter before a single record exists:

    * **One file holds one Episode.** `from_jsonl` returns a flat sequence and
      does not group, so a second beginning appended to somebody else's
      Journal makes the first one unreadable. Refusing is the only answer that
      never writes over evidence.
    * **A path that cannot be written fails before the robot moves.** It used
      to fail once per record — `Journal` catches what a subscriber raises and
      turns it into a `SubscriberFailed`, so a missing directory ran the whole
      Episode, printed a failure line for every record, produced no file and
      still exited 0 (`PLAN.md` §16.24).

    Callers wanting a friendlier sentence than `FileExistsError` should look
    before constructing one; this is the guarantee, not the message.
    """

    def __init__(self, path: Union[str, "os.PathLike[str]"]) -> None:
        self._path = path
        open(path, "x", encoding="utf-8").close()

    def receive(self, record: Record) -> None:
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(to_jsonl([record]))


class TerminalRenderer:
    """The same records, for a person watching.

    Deliberately **not** a field dump. If it printed everything it would be
    the JSONL with worse punctuation, and having two subscribers would prove
    nothing. It answers a different question — *what is the robot doing* —
    and drops what is constant across every line, the Episode's own id above
    all.
    """

    def __init__(self, write: Callable[[str], None] = print) -> None:
        self._write = write

    def receive(self, record: Record) -> None:
        self._write(f"{record.t:7.2f}s  {describe_line(record)}")


#: What kind of moment a record is. Not a colour and not an indent — those are
#: each medium's to choose from this. `refused` and `failed` are deliberately
#: separate: a refusal is the system working (an argument was out of range and
#: nothing reached the robot), a failure is the system not working.
TONES = ("boundary", "action", "result", "refused", "failed")


@dataclass(frozen=True)
class Described:
    """What one record says, with no decision about how it looks.

    Two media read the Journal — the terminal, and (from M8) a page in a
    browser — and both have to answer the same question first: *what does this
    record say?* Answering it twice is how they drift, and this project has
    already paid for that: `TerminalRenderer` printed `-> , 52cm away` for
    every Tool except `approach`, because only `approach`'s result carries a
    `result` key. Nothing went red, because the tests assert on the Journal
    and not on what is shown.

    **What this is not.** It is a *sentence*, not a field dump — `headline` and
    `detail` are prose, and `speak(text='hi')` is one phrase rather than a
    structure a page could lay out as rows. A page that wants the fields reads
    them off the record, which still has them. Giving this a `facts` mapping
    with no caller today would be the Speculative Generality `PLAN.md` §15.23
    deleted `instructions=` for; ticket 07 adds one when it has a use for it.
    Recorded because the ticket claimed more than that — see its Comments.
    """

    headline: str
    detail: str = ""
    tone: str = "action"

    def __post_init__(self) -> None:
        if self.tone not in TONES:
            raise ValueError(f"{self.tone!r} is not one of {TONES}")


def describe(record: Record) -> Described:
    """What one record says. Pure, and exhaustive over the record kinds."""
    if isinstance(record, EpisodeStarted):
        return Described(
            "episode began", f"woken by {record.trigger}", tone="boundary"
        )
    if isinstance(record, TurnStarted):
        return Described(f"turn {record.turn}", tone="boundary")
    if isinstance(record, ModelCalled):
        return Described(
            f"thought for {record.latency_ms}ms",
            f"{record.tokens_in}+{record.tokens_out} tokens",
        )
    if isinstance(record, ToolCalled):
        arguments = ", ".join(f"{k}={v!r}" for k, v in sorted(record.args.items()))
        return Described(f"{record.tool}({arguments})")
    if isinstance(record, ToolRejected):
        return Described(f"{record.tool} refused", record.reason, tone="refused")
    if isinstance(record, Observation):
        return Described(
            _came_back(record.result), in_view(record.snapshot), tone="result"
        )
    if isinstance(record, StopRequested):
        return Described(f"stop requested by {record.source}", tone="boundary")
    if isinstance(record, ExecutionFailed):
        return Described(
            f"{record.phase} failed ({record.error_type})",
            record.message,
            tone="failed",
        )
    if isinstance(record, EpisodeFinished):
        return Described(
            f"episode {record.outcome} after {record.turns} turn(s)",
            f"{record.steps} step(s)",
            tone="boundary",
        )
    if isinstance(record, SubscriberFailed):
        return Described(
            f"{record.subscriber} failed on {record.failed_on}",
            record.error,
            tone="failed",
        )
    # Deliberately loud rather than silent. `from_jsonl` refuses a kind it does
    # not know because a dropped line makes a truncated Journal look complete;
    # a description that quietly skipped one would be the same lie in a
    # different medium — so it reads as a failure, because it is one.
    return Described(f"unrendered record ({record.type})", tone="failed")


def _came_back(result: Mapping[str, Any]) -> str:
    """The Tool's own word for what happened, or the nearest honest thing.

    Only `approach` reports a named outcome; every other Tool answers `ok`.
    Reading the missing key as an empty string is what produced `-> , 52cm
    away` — a sentence with a hole where its subject should be. Every branch
    here returns something, and every branch has a test, because the first
    version guarded only the `ok: True` path and an empty fallback survived.
    """
    named = result.get("result")
    if named is not None:
        return str(named)
    return "ok" if result.get("ok") is True else "returned"


def in_view(snapshot: Snapshot) -> str:
    """A Snapshot as the phrase a person reads, in the only place it is built.

    Public since M8 #04: the entry point has to report what perception made of
    the world *before* any Record exists, and it first did so with a second
    copy of this — which promptly diverged, rendering `someone Nonecm away`
    for the distance-unknown case this handles. `PLAN.md` §15.4.
    """

    if not snapshot.face_present:
        return "nobody in view"
    if snapshot.distance_cm is None:
        return "someone there, distance unknown"
    return f"{snapshot.distance_cm}cm away"


def describe_line(record: Record) -> str:
    """One record as a line. Punctuation and indentation, nothing else.

    Every choice below is keyed off `tone`, so "how it looks" is derived from
    "what kind of moment it is" rather than from the record's class a second
    time.
    """
    said = describe(record)
    indent = "" if said.tone == "boundary" else "  "
    marker = {"result": "-> ", "failed": "! "}.get(said.tone, "")
    if not said.detail:
        return f"{indent}{marker}{said.headline}"
    # A refusal or a failure reads as a label and its explanation; everything
    # else reads as one phrase with a qualifier.
    separator = ": " if said.tone in ("refused", "failed") else ", "
    return f"{indent}{marker}{said.headline}{separator}{said.detail}"


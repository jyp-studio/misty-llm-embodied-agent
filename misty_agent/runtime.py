"""The autonomous shell around one bounded ReAct Episode at a time.

``SocialAgentRuntime`` is the product's highest public seam: an input source
is watched for an Interaction Cue, a selected cue opens the existing bounded
Episode runner, and the result keeps both the Attention records and the typed
Episode Journal. The bounded scheduler keeps observing at safe Turn boundaries
while an Episode is active, without granting a second Episode robot ownership.

The finite ``ScenarioInputAdapter`` is the no-hardware side of the InputSource
boundary.  Waiting uses the injected clock, so an acceptance scenario can
exercise time without sleeping in real life.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, Tuple, Union

from misty_agent.agent.evidence import (
    EvidenceKind,
    MAX_SELECTED_IMAGE_BYTES,
    SelectedImageEvidence,
    TriggerEvidence,
    TriggerEvidenceSummary,
)
from misty_agent.agent.journal import Journal
from misty_agent.agent.react import EpisodeOutcome
from misty_agent.config import Settings, settings as default_settings

_INPUT_STOP_POLL_S = 0.05


class RuntimeState(str, Enum):
    """The externally meaningful lifecycle states."""

    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"


class RuntimeEnding(str, Enum):
    """The bounded ways a finite runtime invocation can finish."""

    INPUT_EXHAUSTED = "input_exhausted"
    SHUTDOWN = "shutdown"
    EPISODE_ERROR = "episode_error"
    RUNTIME_ERROR = "runtime_error"


class RuntimePhase(str, Enum):
    """The runtime boundary at which an outer failure happened."""

    INPUT_START = "input_start"
    INPUT = "input"
    CUE_SELECTION = "cue_selection"
    EPISODE = "episode"
    INPUT_STOP = "input_stop"


class CueKind(str, Enum):
    """Interaction Cue kinds ordered by how directly a person engaged."""

    EXPLICIT_REQUEST = "explicit_request"
    CARE_CUE = "care_cue"
    SOCIAL_INVITATION = "social_invitation"

    @property
    def priority(self) -> int:
        return {
            CueKind.EXPLICIT_REQUEST: 3,
            CueKind.CARE_CUE: 2,
            CueKind.SOCIAL_INVITATION: 1,
        }[self]


class CueDropReason(str, Enum):
    """Why a detected Cue will never open an Episode."""

    EXPIRED = "expired"
    OVERFLOW = "overflow"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class RuntimeInput:
    """One provider-independent arrival at the Attention Loop."""


@dataclass(frozen=True)
class InputArrival:
    """One input stamped when its source observed it."""

    observed_at: float
    input: RuntimeInput


@dataclass(frozen=True)
class ScheduledInput:
    """Scenario-only timing wrapped around a provider-independent input."""

    at_s: float
    input: RuntimeInput

    def __post_init__(self) -> None:
        if self.at_s < 0:
            raise ValueError("a scenario input cannot happen before it starts")


@dataclass(frozen=True)
class TimedText(RuntimeInput):
    """A transcript plus the modality that supplied its Trigger Evidence."""

    text: str
    cue_kind: CueKind = CueKind.EXPLICIT_REQUEST
    evidence_kind: EvidenceKind = EvidenceKind.SPEECH
    facts: Mapping[str, Any] = field(default_factory=dict)
    uncertainty: Tuple[str, ...] = ()
    selected_image: Optional[SelectedImageEvidence] = None
    deduplication_key: Optional[str] = None
    fresh_for_s: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.cue_kind, CueKind):
            raise TypeError("cue_kind must be a CueKind")
        if self.deduplication_key is not None:
            key = self.deduplication_key.strip()
            if not key:
                raise ValueError("deduplication_key cannot be blank")
            object.__setattr__(self, "deduplication_key", key)
        if self.fresh_for_s is not None and self.fresh_for_s <= 0:
            raise ValueError("fresh_for_s must be greater than zero")


class ScenarioClock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class InputSource(Protocol):
    """The lifecycle SocialAgentRuntime needs from any input adapter."""

    def start(self) -> None: ...

    def read(self) -> Optional[InputArrival]: ...

    def read_available(self) -> Tuple[InputArrival, ...]:
        """Return arrivals already waiting, without blocking."""
        ...

    def stop(self) -> None:
        """Stop the source and unblock a pending ``read``. Idempotent."""
        ...


class EpisodeSession(Protocol):
    """The narrow part of Session owned by the runtime."""

    def episode(
        self,
        evidence: TriggerEvidence,
        *,
        render: bool = False,
        journal_path: Optional[Path] = None,
        at_turn_boundary: Optional[Callable[[], None]] = None,
    ) -> Tuple[EpisodeOutcome, Journal]: ...

    def request_stop(self, source: str) -> bool: ...


class ScenarioInputAdapter:
    """Feed a finite, ordered text scenario using an injected clock."""

    def __init__(
        self, clock: ScenarioClock, inputs: Sequence[ScheduledInput]
    ) -> None:
        scheduled = tuple(inputs)
        adjacent = zip(scheduled, scheduled[1:])
        if any(later.at_s < earlier.at_s for earlier, later in adjacent):
            raise ValueError("scenario inputs must be ordered by at_s")
        self._clock = clock
        self._inputs = scheduled
        self._index = 0
        self._started_at: Optional[float] = None
        self._stopped = threading.Event()

    def start(self) -> None:
        if self._started_at is not None:
            raise RuntimeError("this scenario input adapter has already started")
        self._started_at = self._clock.monotonic()

    def read(self) -> Optional[InputArrival]:
        if self._started_at is None or self._stopped.is_set():
            raise RuntimeError("scenario input is not running")
        if self._index >= len(self._inputs):
            return None
        scheduled = self._inputs[self._index]
        due = self._started_at + scheduled.at_s
        wait_s = due - self._clock.monotonic()
        while wait_s > 0 and not self._stopped.is_set():
            self._clock.sleep(min(wait_s, _INPUT_STOP_POLL_S))
            wait_s = due - self._clock.monotonic()
        if self._stopped.is_set():
            return None
        self._index += 1
        return InputArrival(observed_at=due, input=scheduled.input)

    def read_available(self) -> Tuple[InputArrival, ...]:
        if self._started_at is None or self._stopped.is_set():
            raise RuntimeError("scenario input is not running")
        available = []
        now = self._clock.monotonic()
        while self._index < len(self._inputs):
            scheduled = self._inputs[self._index]
            due = self._started_at + scheduled.at_s
            if due > now:
                break
            self._index += 1
            available.append(
                InputArrival(observed_at=due, input=scheduled.input)
            )
        return tuple(available)

    def stop(self) -> None:
        self._stopped.set()


@dataclass(frozen=True, kw_only=True)
class AttentionRecord:
    """A typed fact from outside an Episode Journal."""

    t: float
    type: str


@dataclass(frozen=True, kw_only=True)
class AttentionStarted(AttentionRecord):
    type: str = "attention_started"


@dataclass(frozen=True, kw_only=True)
class CueDetected(AttentionRecord):
    cue_id: str
    cue_kind: CueKind
    evidence_kind: EvidenceKind
    text: str
    priority: int
    type: str = "cue_detected"


@dataclass(frozen=True, kw_only=True)
class CueQueued(AttentionRecord):
    cue_id: str
    active_cue_id: str
    cue_kind: CueKind
    priority: int
    queue_size: int
    type: str = "cue_queued"


@dataclass(frozen=True, kw_only=True)
class CueDequeued(AttentionRecord):
    cue_id: str
    cue_kind: CueKind
    priority: int
    queue_size: int
    type: str = "cue_dequeued"


@dataclass(frozen=True, kw_only=True)
class CueDeduplicated(AttentionRecord):
    cue_id: str
    retained_cue_id: str
    deduplication_key: str
    priority: int
    queue_size: int
    type: str = "cue_deduplicated"


@dataclass(frozen=True, kw_only=True)
class CueReplaced(AttentionRecord):
    cue_id: str
    replacement_cue_id: str
    deduplication_key: str
    old_priority: int
    new_priority: int
    queue_size: int
    type: str = "cue_replaced"


@dataclass(frozen=True, kw_only=True)
class CueDropped(AttentionRecord):
    cue_id: str
    cue_kind: CueKind
    priority: int
    reason: CueDropReason
    queue_size: int
    type: str = "cue_dropped"


@dataclass(frozen=True, kw_only=True)
class EpisodeOpened(AttentionRecord):
    cue_id: str
    type: str = "episode_opened"


@dataclass(frozen=True, kw_only=True)
class EpisodeCompleted(AttentionRecord):
    cue_id: str
    episode_id: str
    outcome: str
    type: str = "episode_completed"


@dataclass(frozen=True, kw_only=True)
class AttentionStopped(AttentionRecord):
    ending: RuntimeEnding
    type: str = "attention_stopped"


@dataclass(frozen=True, kw_only=True)
class RuntimeFailed(AttentionRecord):
    phase: RuntimePhase
    error_type: str
    message: str
    type: str = "runtime_failed"


RuntimeRecord = Union[
    AttentionStarted,
    CueDetected,
    CueQueued,
    CueDequeued,
    CueDeduplicated,
    CueReplaced,
    CueDropped,
    EpisodeOpened,
    EpisodeCompleted,
    RuntimeFailed,
    AttentionStopped,
]


@dataclass(frozen=True)
class _PendingCue:
    cue_id: str
    input: TimedText
    observed_at_s: float
    cue_kind: CueKind
    priority: int
    deduplication_key: Optional[str]
    expires_at_s: float


@dataclass(frozen=True)
class RuntimeEpisode:
    """One selected cue and the bounded Episode it opened."""

    cue_id: str
    cue_kind: CueKind
    input: RuntimeInput
    evidence: TriggerEvidenceSummary
    outcome: EpisodeOutcome
    journal: Journal


@dataclass(frozen=True)
class RuntimeResult:
    """Everything one finite runtime run made observable."""

    ending: RuntimeEnding
    records: Tuple[RuntimeRecord, ...]
    episodes: Tuple[RuntimeEpisode, ...]


class SocialAgentRuntime:
    """Consume one InputSource and run selected cues serially to completion."""

    def __init__(
        self,
        *,
        source: InputSource,
        session: EpisodeSession,
        clock: ScenarioClock,
        config: Settings = default_settings,
    ) -> None:
        self._source = source
        self._session = session
        self._clock = clock
        self._config = config
        self._origin: Optional[float] = None
        self._stop_requested = threading.Event()
        self._source_stop_lock = threading.Lock()
        self._source_stopped = False
        self._source_stop_error: Optional[Exception] = None
        self.state = RuntimeState.READY

    def run(
        self,
        *,
        render: bool = False,
        journal_path_for_episode: Optional[
            Callable[[int], Optional[Path]]
        ] = None,
    ) -> RuntimeResult:
        """Own the input lifecycle and stop after a finite source is drained."""
        if self.state is not RuntimeState.READY:
            raise RuntimeError("a SocialAgentRuntime can only be run once")

        self.state = RuntimeState.RUNNING
        self._origin = self._clock.monotonic()
        records: list[RuntimeRecord] = [AttentionStarted(t=0.0)]
        episodes: list[RuntimeEpisode] = []
        pending: list[_PendingCue] = []
        cue_count = 0
        ending = RuntimeEnding.INPUT_EXHAUSTED
        phase = RuntimePhase.INPUT_START
        try:
            self._source.start()
            while not self._stop_requested.is_set():
                phase = RuntimePhase.INPUT
                self._discard_expired(pending, records)
                if pending:
                    pending.sort(
                        key=lambda item: (-item.priority, item.observed_at_s)
                    )
                    cue = pending.pop(0)
                    records.append(
                        CueDequeued(
                            t=self._elapsed(),
                            cue_id=cue.cue_id,
                            cue_kind=cue.cue_kind,
                            priority=cue.priority,
                            queue_size=len(pending),
                        )
                    )
                else:
                    arrival = self._source.read()
                    if arrival is None or self._stop_requested.is_set():
                        break
                    cue_count += 1
                    cue = self._cue(cue_count, arrival)
                    records.append(self._detected(cue))
                    if self._is_expired(cue):
                        self._drop(
                            cue,
                            CueDropReason.EXPIRED,
                            pending,
                            records,
                        )
                        continue

                phase = RuntimePhase.CUE_SELECTION
                records.append(
                    EpisodeOpened(t=self._elapsed(), cue_id=cue.cue_id)
                )
                phase = RuntimePhase.EPISODE
                episode_number = len(episodes) + 1
                journal_path = (
                    journal_path_for_episode(episode_number)
                    if journal_path_for_episode is not None
                    else None
                )
                evidence = TriggerEvidence(
                    source=cue.input.evidence_kind,
                    observed_at_s=cue.observed_at_s,
                    facts=cue.input.facts,
                    transcript=cue.input.text,
                    uncertainty=cue.input.uncertainty,
                    selected_image=cue.input.selected_image,
                )
                active_input_failure: Optional[Exception] = None

                def collect_available() -> None:
                    nonlocal active_input_failure, cue_count
                    if (
                        active_input_failure is not None
                        or self._stop_requested.is_set()
                    ):
                        return
                    try:
                        waiting_inputs = self._source.read_available()
                        for waiting in waiting_inputs:
                            cue_count += 1
                            queued = self._cue(cue_count, waiting)
                            records.append(self._detected(queued))
                            self._enqueue(
                                queued,
                                active_cue_id=cue.cue_id,
                                pending=pending,
                                records=records,
                            )
                    except Exception as error:
                        active_input_failure = error
                        self._session.request_stop("attention_input_failure")

                outcome, journal = self._session.episode(
                    evidence,
                    render=render,
                    journal_path=journal_path,
                    at_turn_boundary=collect_available,
                )
                episode_id = journal.records[0].episode_id
                episodes.append(
                    RuntimeEpisode(
                        cue_id=cue.cue_id,
                        cue_kind=cue.cue_kind,
                        input=replace(cue.input, selected_image=None),
                        evidence=TriggerEvidenceSummary.from_evidence(evidence),
                        outcome=outcome,
                        journal=journal,
                    )
                )
                records.append(
                    EpisodeCompleted(
                        t=self._elapsed(),
                        cue_id=cue.cue_id,
                        episode_id=episode_id,
                        outcome=outcome.outcome,
                    )
                )
                if active_input_failure is not None:
                    ending = RuntimeEnding.RUNTIME_ERROR
                    records.append(
                        RuntimeFailed(
                            t=self._elapsed(),
                            phase=RuntimePhase.INPUT,
                            error_type=type(active_input_failure).__name__,
                            message=str(active_input_failure),
                        )
                    )
                    break
                if outcome.outcome == "error":
                    ending = RuntimeEnding.EPISODE_ERROR
                    break
            if self._stop_requested.is_set():
                ending = RuntimeEnding.SHUTDOWN
                self._drop_all(
                    pending, CueDropReason.SHUTDOWN, records
                )
        except Exception as error:
            ending = RuntimeEnding.RUNTIME_ERROR
            records.append(
                RuntimeFailed(
                    t=self._elapsed(),
                    phase=phase,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
        finally:
            stop_error = self._stop_source()
            if stop_error is not None:
                ending = RuntimeEnding.RUNTIME_ERROR
                records.append(
                    RuntimeFailed(
                        t=self._elapsed(),
                        phase=RuntimePhase.INPUT_STOP,
                        error_type=type(stop_error).__name__,
                        message=str(stop_error),
                    )
                )
            self.state = RuntimeState.STOPPED
            records.append(AttentionStopped(t=self._elapsed(), ending=ending))

        return RuntimeResult(
            ending=ending,
            records=tuple(records),
            episodes=tuple(episodes),
        )

    def _cue(self, number: int, arrival: InputArrival) -> _PendingCue:
        item = arrival.input
        if not isinstance(item, TimedText):
            raise TypeError(
                f"cannot select a cue from {type(item).__name__}"
            )
        assert self._origin is not None
        return _PendingCue(
            cue_id=f"cue-{number}",
            input=item,
            observed_at_s=round(arrival.observed_at - self._origin, 3),
            cue_kind=item.cue_kind,
            priority=item.cue_kind.priority,
            deduplication_key=item.deduplication_key,
            expires_at_s=round(
                arrival.observed_at
                - self._origin
                + (
                    item.fresh_for_s
                    if item.fresh_for_s is not None
                    else self._config.cue_freshness_s
                ),
                3,
            ),
        )

    def _enqueue(
        self,
        cue: _PendingCue,
        *,
        active_cue_id: str,
        pending: list[_PendingCue],
        records: list[RuntimeRecord],
    ) -> None:
        if self._is_expired(cue):
            self._drop(cue, CueDropReason.EXPIRED, pending, records)
            return

        duplicate_index = next(
            (
                index
                for index, existing in enumerate(pending)
                if cue.deduplication_key is not None
                and existing.deduplication_key == cue.deduplication_key
            ),
            None,
        )
        if duplicate_index is not None:
            existing = pending[duplicate_index]
            if cue.priority <= existing.priority:
                records.append(
                    CueDeduplicated(
                        t=self._elapsed(),
                        cue_id=cue.cue_id,
                        retained_cue_id=existing.cue_id,
                        deduplication_key=cue.deduplication_key or "",
                        priority=cue.priority,
                        queue_size=len(pending),
                    )
                )
                return
            pending[duplicate_index] = cue
            records.append(
                CueReplaced(
                    t=self._elapsed(),
                    cue_id=existing.cue_id,
                    replacement_cue_id=cue.cue_id,
                    deduplication_key=cue.deduplication_key or "",
                    old_priority=existing.priority,
                    new_priority=cue.priority,
                    queue_size=len(pending),
                )
            )
            return

        if len(pending) >= self._config.cue_queue_capacity:
            victim = min(
                pending,
                key=lambda item: (item.priority, -item.observed_at_s),
            )
            if cue.priority <= victim.priority:
                self._drop(cue, CueDropReason.OVERFLOW, pending, records)
                return
            pending.remove(victim)
            self._drop(victim, CueDropReason.OVERFLOW, pending, records)

        pending.append(cue)
        records.append(
            CueQueued(
                t=self._elapsed(),
                cue_id=cue.cue_id,
                active_cue_id=active_cue_id,
                cue_kind=cue.cue_kind,
                priority=cue.priority,
                queue_size=len(pending),
            )
        )

    def _discard_expired(
        self,
        pending: list[_PendingCue],
        records: list[RuntimeRecord],
    ) -> None:
        for cue in tuple(pending):
            if self._is_expired(cue):
                pending.remove(cue)
                self._drop(cue, CueDropReason.EXPIRED, pending, records)

    def _drop_all(
        self,
        pending: list[_PendingCue],
        reason: CueDropReason,
        records: list[RuntimeRecord],
    ) -> None:
        while pending:
            cue = pending.pop(0)
            self._drop(cue, reason, pending, records)

    def _drop(
        self,
        cue: _PendingCue,
        reason: CueDropReason,
        pending: list[_PendingCue],
        records: list[RuntimeRecord],
    ) -> None:
        records.append(
            CueDropped(
                t=self._elapsed(),
                cue_id=cue.cue_id,
                cue_kind=cue.cue_kind,
                priority=cue.priority,
                reason=reason,
                queue_size=len(pending),
            )
        )

    def _is_expired(self, cue: _PendingCue) -> bool:
        return self._elapsed() >= cue.expires_at_s

    @staticmethod
    def _detected(cue: _PendingCue) -> CueDetected:
        return CueDetected(
            t=cue.observed_at_s,
            cue_id=cue.cue_id,
            cue_kind=cue.cue_kind,
            evidence_kind=cue.input.evidence_kind,
            text=cue.input.text,
            priority=cue.priority,
        )

    def stop(self) -> None:
        """Request bounded shutdown; an active Episode is asked to abort."""
        self._stop_requested.set()
        if self.state is RuntimeState.RUNNING:
            try:
                self._session.request_stop("runtime_shutdown")
            finally:
                self._stop_source()

    def _stop_source(self) -> Optional[Exception]:
        """Stop an InputSource once, synchronising run and shutdown callers."""
        with self._source_stop_lock:
            if not self._source_stopped:
                self._source_stopped = True
                try:
                    self._source.stop()
                except Exception as error:
                    self._source_stop_error = error
            return self._source_stop_error

    def _elapsed(self) -> float:
        assert self._origin is not None
        return round(self._clock.monotonic() - self._origin, 3)


__all__ = [
    "AttentionRecord",
    "AttentionStarted",
    "AttentionStopped",
    "CueDequeued",
    "CueDeduplicated",
    "CueDropped",
    "CueDropReason",
    "CueKind",
    "CueDetected",
    "CueQueued",
    "CueReplaced",
    "EvidenceKind",
    "MAX_SELECTED_IMAGE_BYTES",
    "EpisodeCompleted",
    "EpisodeOpened",
    "EpisodeSession",
    "InputArrival",
    "InputSource",
    "RuntimeEpisode",
    "RuntimeEnding",
    "RuntimeFailed",
    "RuntimeInput",
    "RuntimePhase",
    "RuntimeRecord",
    "RuntimeResult",
    "RuntimeState",
    "ScenarioClock",
    "ScenarioInputAdapter",
    "ScheduledInput",
    "SelectedImageEvidence",
    "SocialAgentRuntime",
    "TimedText",
    "TriggerEvidence",
    "TriggerEvidenceSummary",
]

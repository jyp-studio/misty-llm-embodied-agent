"""The autonomous shell around one bounded ReAct Episode at a time.

``SocialAgentRuntime`` is the product's highest public seam: an input source
is watched for an Interaction Cue, a selected cue opens the existing bounded
Episode runner, and the result keeps both the Attention records and the typed
Episode Journal.  Ticket 01 deliberately supports only timed text that is an
Explicit Request.  Wake detection, visual cues, cue queues and handoff belong
to later vertical slices.

The finite ``ScenarioInputAdapter`` is the no-hardware side of the InputSource
boundary.  Waiting uses the injected clock, so an acceptance scenario can
exercise time without sleeping in real life.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, Sequence, Tuple, Union

from misty_agent.agent.journal import Journal
from misty_agent.agent.react import EpisodeOutcome

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
    """Interaction Cue kinds implemented by this vertical slice."""

    EXPLICIT_REQUEST = "explicit_request"


class EvidenceKind(str, Enum):
    """Modalities this slice can pass into existing Episode evidence."""

    SPEECH = "speech"
    VISUAL = "visual"


@dataclass(frozen=True)
class RuntimeInput:
    """One provider-independent input scheduled relative to scenario start."""

    at_s: float

    def __post_init__(self) -> None:
        if self.at_s < 0:
            raise ValueError("a scenario input cannot happen before it starts")


@dataclass(frozen=True)
class TimedText(RuntimeInput):
    """A transcript plus the modality that supplied its Trigger Evidence."""

    text: str
    evidence_kind: EvidenceKind = EvidenceKind.SPEECH


class ScenarioClock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class InputSource(Protocol):
    """The lifecycle SocialAgentRuntime needs from any input adapter."""

    def start(self) -> None: ...

    def read(self) -> Optional[RuntimeInput]: ...

    def stop(self) -> None:
        """Stop the source and unblock a pending ``read``. Idempotent."""
        ...


class EpisodeSession(Protocol):
    """The narrow part of Session owned by the runtime."""

    def episode(
        self,
        trigger: str,
        heard: str,
        *,
        render: bool = False,
        journal_path: Optional[Path] = None,
    ) -> Tuple[EpisodeOutcome, Journal]: ...

    def request_stop(self, source: str) -> bool: ...


class ScenarioInputAdapter:
    """Feed a finite, ordered text scenario using an injected clock."""

    def __init__(
        self, clock: ScenarioClock, inputs: Sequence[RuntimeInput]
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

    def read(self) -> Optional[RuntimeInput]:
        if self._started_at is None or self._stopped.is_set():
            raise RuntimeError("scenario input is not running")
        if self._index >= len(self._inputs):
            return None
        item = self._inputs[self._index]
        due = self._started_at + item.at_s
        wait_s = due - self._clock.monotonic()
        while wait_s > 0 and not self._stopped.is_set():
            self._clock.sleep(min(wait_s, _INPUT_STOP_POLL_S))
            wait_s = due - self._clock.monotonic()
        if self._stopped.is_set():
            return None
        self._index += 1
        return item

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
    type: str = "cue_detected"


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
    EpisodeOpened,
    EpisodeCompleted,
    RuntimeFailed,
    AttentionStopped,
]


@dataclass(frozen=True)
class RuntimeEpisode:
    """One selected cue and the bounded Episode it opened."""

    cue_id: str
    cue_kind: CueKind
    input: RuntimeInput
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
    ) -> None:
        self._source = source
        self._session = session
        self._clock = clock
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
        journal_path: Optional[Path] = None,
    ) -> RuntimeResult:
        """Own the input lifecycle and stop after a finite source is drained."""
        if self.state is not RuntimeState.READY:
            raise RuntimeError("a SocialAgentRuntime can only be run once")

        self.state = RuntimeState.RUNNING
        self._origin = self._clock.monotonic()
        records: list[RuntimeRecord] = [AttentionStarted(t=0.0)]
        episodes: list[RuntimeEpisode] = []
        ending = RuntimeEnding.INPUT_EXHAUSTED
        phase = RuntimePhase.INPUT_START
        try:
            self._source.start()
            while not self._stop_requested.is_set():
                phase = RuntimePhase.INPUT
                item = self._source.read()
                if item is None or self._stop_requested.is_set():
                    break
                phase = RuntimePhase.CUE_SELECTION
                if not isinstance(item, TimedText):
                    raise TypeError(
                        f"ticket 01 cannot select a cue from {type(item).__name__}"
                    )

                cue_id = f"cue-{len(episodes) + 1}"
                records.append(
                    CueDetected(
                        t=self._elapsed(),
                        cue_id=cue_id,
                        cue_kind=CueKind.EXPLICIT_REQUEST,
                        evidence_kind=item.evidence_kind,
                        text=item.text,
                    )
                )
                records.append(EpisodeOpened(t=self._elapsed(), cue_id=cue_id))
                phase = RuntimePhase.EPISODE
                outcome, journal = self._session.episode(
                    item.evidence_kind,
                    item.text,
                    render=render,
                    journal_path=journal_path,
                )
                episode_id = journal.records[0].episode_id
                episodes.append(
                    RuntimeEpisode(
                        cue_id=cue_id,
                        cue_kind=CueKind.EXPLICIT_REQUEST,
                        input=item,
                        outcome=outcome,
                        journal=journal,
                    )
                )
                records.append(
                    EpisodeCompleted(
                        t=self._elapsed(),
                        cue_id=cue_id,
                        episode_id=episode_id,
                        outcome=outcome.outcome,
                    )
                )
                if outcome.outcome == "error":
                    ending = RuntimeEnding.EPISODE_ERROR
                    break
            if self._stop_requested.is_set():
                ending = RuntimeEnding.SHUTDOWN
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
    "CueKind",
    "CueDetected",
    "EvidenceKind",
    "EpisodeCompleted",
    "EpisodeOpened",
    "EpisodeSession",
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
    "SocialAgentRuntime",
    "TimedText",
]

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

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Sequence, Tuple, Union

from misty_agent.agent.journal import Journal
from misty_agent.agent.react import EpisodeOutcome


class RuntimeState(str, Enum):
    """The externally meaningful lifecycle states."""

    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TimedText:
    """One text input, scheduled relative to scenario start."""

    at_s: float
    text: str
    trigger: str = "speech"

    def __post_init__(self) -> None:
        if self.at_s < 0:
            raise ValueError("a scenario input cannot happen before it starts")


class ScenarioClock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class InputSource(Protocol):
    """The lifecycle SocialAgentRuntime needs from any input adapter."""

    def start(self) -> None: ...

    def read(self) -> Optional[TimedText]: ...

    def stop(self) -> None: ...


class EpisodeSession(Protocol):
    """The narrow part of Session owned by the runtime."""

    def episode(
        self,
        trigger: str,
        heard: Optional[str],
        *,
        render: bool = False,
    ) -> Tuple[EpisodeOutcome, Journal]: ...

    def request_stop(self, source: str) -> bool: ...


class ScenarioInputAdapter:
    """Feed a finite, ordered text scenario using an injected clock."""

    def __init__(
        self, clock: ScenarioClock, inputs: Sequence[TimedText]
    ) -> None:
        scheduled = tuple(inputs)
        adjacent = zip(scheduled, scheduled[1:])
        if any(later.at_s < earlier.at_s for earlier, later in adjacent):
            raise ValueError("scenario inputs must be ordered by at_s")
        self._clock = clock
        self._inputs = scheduled
        self._index = 0
        self._started_at: Optional[float] = None
        self._stopped = False

    def start(self) -> None:
        if self._started_at is not None:
            raise RuntimeError("this scenario input adapter has already started")
        self._started_at = self._clock.monotonic()

    def read(self) -> Optional[TimedText]:
        if self._started_at is None or self._stopped:
            raise RuntimeError("scenario input is not running")
        if self._index >= len(self._inputs):
            return None
        item = self._inputs[self._index]
        due = self._started_at + item.at_s
        wait_s = due - self._clock.monotonic()
        if wait_s > 0:
            self._clock.sleep(wait_s)
        self._index += 1
        return item

    def stop(self) -> None:
        self._stopped = True


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
    cue_kind: str
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
    ending: str
    type: str = "attention_stopped"


@dataclass(frozen=True, kw_only=True)
class RuntimeFailed(AttentionRecord):
    phase: str
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
    cue_kind: str
    input: TimedText
    outcome: EpisodeOutcome
    journal: Journal


@dataclass(frozen=True)
class RuntimeResult:
    """Everything one finite runtime run made observable."""

    ending: str
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
        self._stop_requested = False
        self.state = RuntimeState.READY

    def run(self) -> RuntimeResult:
        """Own the input lifecycle and stop after a finite source is drained."""
        if self.state is not RuntimeState.READY:
            raise RuntimeError("a SocialAgentRuntime can only be run once")

        self.state = RuntimeState.RUNNING
        self._origin = self._clock.monotonic()
        records: list[RuntimeRecord] = [AttentionStarted(t=0.0)]
        episodes: list[RuntimeEpisode] = []
        ending = "input_exhausted"
        phase = "input_start"
        try:
            self._source.start()
            while not self._stop_requested:
                phase = "input"
                item = self._source.read()
                if item is None:
                    break

                cue_id = f"cue-{len(episodes) + 1}"
                records.append(
                    CueDetected(
                        t=self._elapsed(),
                        cue_id=cue_id,
                        cue_kind="explicit_request",
                        text=item.text,
                    )
                )
                records.append(EpisodeOpened(t=self._elapsed(), cue_id=cue_id))
                phase = "episode"
                outcome, journal = self._session.episode(
                    item.trigger, item.text, render=False
                )
                episode_id = journal.records[0].episode_id
                episodes.append(
                    RuntimeEpisode(
                        cue_id=cue_id,
                        cue_kind="explicit_request",
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
                    ending = "episode_error"
                    break
            if self._stop_requested:
                ending = "shutdown"
        except Exception as error:
            ending = "runtime_error"
            records.append(
                RuntimeFailed(
                    t=self._elapsed(),
                    phase=phase,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
        finally:
            try:
                self._source.stop()
            except Exception as error:
                ending = "runtime_error"
                records.append(
                    RuntimeFailed(
                        t=self._elapsed(),
                        phase="input_stop",
                        error_type=type(error).__name__,
                        message=str(error),
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
        self._stop_requested = True
        if self.state is RuntimeState.RUNNING:
            self._session.request_stop("runtime_shutdown")

    def _elapsed(self) -> float:
        assert self._origin is not None
        return round(self._clock.monotonic() - self._origin, 3)


__all__ = [
    "AttentionRecord",
    "AttentionStarted",
    "AttentionStopped",
    "CueDetected",
    "EpisodeCompleted",
    "EpisodeOpened",
    "EpisodeSession",
    "RuntimeEpisode",
    "RuntimeFailed",
    "RuntimeRecord",
    "RuntimeResult",
    "RuntimeState",
    "ScenarioInputAdapter",
    "SocialAgentRuntime",
    "TimedText",
]

"""Bounded active listening. Sources own decoding; this owns the wait."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol

from misty_agent.agent.stop import NEVER_STOPS


class ListeningEnding(str, Enum):
    HEARD = "heard"
    SILENCE = "silence"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    ABORTED = "aborted"


@dataclass(frozen=True)
class ListeningResult:
    ending: ListeningEnding
    transcript: str | None = None
    source: str = "unavailable"
    age_s: float | None = None
    fresh_for_s: float = 5.0
    uncertainty: tuple[str, ...] = ("Speaker attribution is unverified",)
    kind: str = "listening"

    def as_tool_result(self) -> dict:
        result = asdict(self)
        result["ending"] = self.ending.value
        result["uncertainty"] = list(self.uncertainty)
        return result


class ListeningSource(Protocol):
    def poll_utterance(self, *, timeout_s: float) -> ListeningResult | None: ...


class TranscriptSource:
    """Existing decoded utterance queues, never a raw audio queue."""

    def __init__(self, ears):
        self._ears = ears

    def poll_utterance(self, *, timeout_s: float) -> ListeningResult | None:
        heard = self._ears.read(timeout=0)
        if heard is None or not heard.text.strip():
            return None
        return ListeningResult(
            ListeningEnding.HEARD, heard.text.strip()[:4000],
            source="transcript_queue", age_s=0.0,
            uncertainty=("Age is measured at dequeue; capture time and speaker are unverified",),
        )


class BoundedListener:
    def __init__(self, source: ListeningSource | None, clock, stop=NEVER_STOPS):
        self._source, self._clock, self._stop = source, clock, stop

    def listen(self, *, timeout_s: float) -> ListeningResult:
        if self._source is None:
            return ListeningResult(ListeningEnding.UNAVAILABLE)
        deadline = self._clock.monotonic() + timeout_s
        while self._clock.monotonic() < deadline:
            if self._stop.requested():
                return ListeningResult(ListeningEnding.ABORTED)
            try:
                result = self._source.poll_utterance(
                    timeout_s=deadline - self._clock.monotonic()
                )
            except Exception:
                return ListeningResult(ListeningEnding.ERROR)
            if self._stop.requested():
                return ListeningResult(ListeningEnding.ABORTED)
            if result is not None:
                return result
            self._clock.sleep(min(0.05, max(0, deadline - self._clock.monotonic())))
        return ListeningResult(ListeningEnding.SILENCE)

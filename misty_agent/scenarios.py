"""Acceptance scenarios shared by tests and the local Demo.

Each scenario describes inputs at the outer runtime seam and decisions at
the hosted-model seam.  Keeping those two parts together means the Demo
cannot quietly become a prettier, different path from the one acceptance
tests exercise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

from misty_agent.agent.react import Decision
from misty_agent.runtime import ScheduledInput, TimedText


@dataclass(frozen=True)
class AcceptanceScenario:
    """One deterministic, no-hardware story through SocialAgentRuntime."""

    name: str
    title: str
    inputs: Tuple[ScheduledInput, ...]
    decisions: Tuple[Decision, ...]


class ScenarioModel:
    """Replay the model decisions declared by one acceptance scenario."""

    def __init__(self, decisions: Sequence[Decision]) -> None:
        self._remaining = list(decisions)

    def decide(
        self,
        working_context: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> Decision:
        if not self._remaining:
            raise RuntimeError("the acceptance scenario ran out of decisions")
        return self._remaining.pop(0)


EXPLICIT_TEXT_REQUEST = AcceptanceScenario(
    name="runtime_explicit_text_request",
    title="A timed request wakes the social runtime",
    inputs=(
        ScheduledInput(at_s=0.5, input=TimedText(text="Misty, hello")),
    ),
    decisions=(
        Decision(
            tool="speak",
            args={"text": "Hello — what can I do for you?"},
            tokens_in=20,
            tokens_out=8,
        ),
        Decision(tool="done", args={}, tokens_in=34, tokens_out=1),
    ),
)


__all__ = [
    "AcceptanceScenario",
    "EXPLICIT_TEXT_REQUEST",
    "ScenarioModel",
]

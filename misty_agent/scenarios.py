"""Acceptance scenarios shared by tests and the local Demo.

Each scenario describes inputs at the outer runtime seam and decisions at
the hosted-model seam.  Keeping those two parts together means the Demo
cannot quietly become a prettier, different path from the one acceptance
tests exercise.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence, Tuple

from misty_agent.agent.react import Decision
from misty_agent.runtime import ScheduledInput, TimedText


@dataclass(frozen=True)
class PresentationBeat:
    """One plain-language beat in a preview or observed execution flow."""

    kind: str
    label: str
    headline: str
    detail: str


class ScenarioAvailability(str, Enum):
    """Whether a Demo card can execute against the current product seam."""

    READY = "ready"
    PLANNED = "planned"


@dataclass(frozen=True)
class ScenarioCard:
    """The honest status and preview copy for one Demo choice."""

    name: str
    title: str
    subtitle: str
    availability: ScenarioAvailability
    ticket: str
    limitation: str
    preview: Tuple[PresentationBeat, ...]


@dataclass(frozen=True)
class PlannedScenario(ScenarioCard):
    """A roadmap preview with deliberately no executable behavior."""

    def __post_init__(self) -> None:
        if self.availability is not ScenarioAvailability.PLANNED:
            raise ValueError("a planned scenario must have planned availability")
        if not self.ticket:
            raise ValueError("a planned scenario must name its future ticket")


@dataclass(frozen=True)
class AcceptanceScenario(ScenarioCard):
    """One deterministic, no-hardware story through SocialAgentRuntime."""

    actors: Tuple[str, ...]
    inputs: Tuple[ScheduledInput, ...]
    decisions: Tuple[Decision, ...]

    def __post_init__(self) -> None:
        if self.availability is not ScenarioAvailability.READY:
            raise ValueError("an acceptance scenario must be ready to run")
        if not self.inputs:
            raise ValueError("a runnable scenario must declare an input")
        if not self.decisions:
            raise ValueError("a runnable scenario must declare model decisions")
        if len(self.actors) != len(self.inputs):
            raise ValueError("each scenario input must name exactly one actor")


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
    name="greeting",
    title="有人和 Misty 打招呼",
    subtitle="一句明確的問候，開啟完整 Episode。",
    availability=ScenarioAvailability.READY,
    ticket="01",
    limitation=(
        "使用 scripted model 與 simulated robot；沒有呼叫網路，也沒有連接 "
        "Misty II。"
    ),
    actors=("person",),
    preview=(
        PresentationBeat(
            "input", "收到", "「Misty，你好！」", "語音被分類為明確互動請求。"
        ),
        PresentationBeat("decision", "決定", "回應問候", "ReAct 選擇 speak Tool。"),
        PresentationBeat(
            "effect",
            "模擬動作",
            "「嗨！很高興見到你。」",
            "情境輸入播放完畢，Runtime 正常停止。",
        ),
    ),
    inputs=(
        ScheduledInput(at_s=0.5, input=TimedText(text="Misty，你好！")),
    ),
    decisions=(
        Decision(
            tool="speak",
            args={"text": "嗨！很高興見到你。"},
            tokens_in=20,
            tokens_out=8,
        ),
        Decision(tool="done", args={}, tokens_in=34, tokens_out=1),
    ),
)


CRYING_CARE = PlannedScenario(
    name="crying-care",
    title="有人在 Misty 面前哭泣",
    subtitle="未來將觀察線索並自主決定是否詢問。",
    availability=ScenarioAvailability.PLANNED,
    ticket="06",
    limitation=(
        "Ticket 06 尚未實作：目前沒有哭泣辨識、Care Cue 分類或自主回應。"
    ),
    preview=(
        PresentationBeat(
            "input", "預計收到", "可觀察的哭泣跡象", "保留不確定性，不診斷情緒。"
        ),
        PresentationBeat(
            "decision", "預計決定", "由 LLM 選擇是否介入", "不固定映射成安慰台詞。"
        ),
        PresentationBeat(
            "effect",
            "預計動作",
            "詢問、觀察或保持距離",
            "實際可接受結果將由 ticket 06 定義。",
        ),
    ),
)


SPEAKER_HANDOFF = PlannedScenario(
    name="speaker-handoff",
    title="A 聊完後，切換成 B",
    subtitle="未來將結束 A 的互動，再由 B 開啟新 Episode。",
    availability=ScenarioAvailability.PLANNED,
    ticket="08",
    limitation=(
        "Ticket 08 尚未實作：目前沒有 target ownership、Cue queue 或人物交接。"
    ),
    preview=(
        PresentationBeat(
            "input",
            "預計收到",
            "A 互動期間，B 明確呼叫 Misty",
            "B 的 request 將先進入 Cue queue。",
        ),
        PresentationBeat(
            "decision",
            "預計決定",
            "先安全結束 A",
            "不平行開啟第二個 Episode。",
        ),
        PresentationBeat(
            "effect",
            "預計動作",
            "再向 B 開始新互動",
            "完整 target handoff 將由 ticket 08 驗收。",
        ),
    ),
)


DEMO_SCENARIOS = (EXPLICIT_TEXT_REQUEST, CRYING_CARE, SPEAKER_HANDOFF)


__all__ = [
    "AcceptanceScenario",
    "CRYING_CARE",
    "DEMO_SCENARIOS",
    "EXPLICIT_TEXT_REQUEST",
    "PlannedScenario",
    "PresentationBeat",
    "SPEAKER_HANDOFF",
    "ScenarioCard",
    "ScenarioAvailability",
    "ScenarioModel",
]

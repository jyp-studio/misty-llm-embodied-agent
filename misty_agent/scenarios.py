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
from misty_agent.runtime import (
    CueKind,
    EvidenceKind,
    ScheduledInput,
    TimedText,
)


@dataclass(frozen=True)
class ScenarioStep:
    """One plain-language claim the Demo can show for a scripted run."""

    label: str
    headline: str
    detail: str


class ScenarioAvailability(str, Enum):
    """How much of a Demo scenario is implemented rather than injected."""

    READY = "ready"
    SCRIPTED_ONLY = "scripted_only"


@dataclass(frozen=True)
class AcceptanceScenario:
    """One deterministic, no-hardware story through SocialAgentRuntime."""

    name: str
    title: str
    subtitle: str
    availability: ScenarioAvailability
    limitation: str
    actors: Tuple[str, ...]
    steps: Tuple[ScenarioStep, ...]
    inputs: Tuple[ScheduledInput, ...]
    decisions: Tuple[Decision, ...]

    def __post_init__(self) -> None:
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
    limitation=(
        "使用 scripted model 與 simulated robot；沒有呼叫網路，也沒有連接 "
        "Misty II。"
    ),
    actors=("person",),
    steps=(
        ScenarioStep("收到", "「Misty，你好！」", "語音被分類為明確互動請求。"),
        ScenarioStep("決定", "回應問候", "ReAct 選擇 speak Tool。"),
        ScenarioStep(
            "模擬動作",
            "「嗨！很高興見到你。」",
            "Episode 正常結束，回到等待狀態。",
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


CRYING_CARE = AcceptanceScenario(
    name="crying-care",
    title="有人在 Misty 面前哭泣",
    subtitle="觀察線索並詢問，不擅自診斷情緒。",
    availability=ScenarioAvailability.SCRIPTED_ONLY,
    limitation=(
        "這是注入的 Care Cue，沒有執行哭泣辨識；也沒有連接 Misty II。"
    ),
    actors=("person",),
    steps=(
        ScenarioStep("收到", "觀察到哭泣跡象", "由腳本注入 visual Care Cue。"),
        ScenarioStep("決定", "先詢問是否需要幫忙", "不靠近、不碰觸、不預設答案。"),
        ScenarioStep(
            "模擬動作",
            "「你需要我幫忙嗎？」",
            "詢問一次後結束，不把線索當成診斷。",
        ),
    ),
    inputs=(
        ScheduledInput(
            at_s=0.5,
            input=TimedText(
                text="A person nearby appears to be crying.",
                evidence_kind=EvidenceKind.VISUAL,
                cue_kind=CueKind.CARE_CUE,
            ),
        ),
    ),
    decisions=(
        Decision(
            tool="speak",
            args={"text": "你需要我幫忙嗎？"},
            tokens_in=22,
            tokens_out=7,
        ),
        Decision(tool="done", args={}, tokens_in=30, tokens_out=1),
    ),
)


SPEAKER_HANDOFF = AcceptanceScenario(
    name="speaker-handoff",
    title="A 聊完後，切換成 B",
    subtitle="結束 A 的互動，再把 B 當成新的對話對象。",
    availability=ScenarioAvailability.SCRIPTED_ONLY,
    limitation=(
        "A/B 標記由腳本注入，沒有執行人物辨識；兩次互動使用兩個獨立 "
        "Episode，也沒有連接 Misty II。"
    ),
    actors=("A", "B"),
    steps=(
        ScenarioStep(
            "收到",
            "A 先問候，接著 B 叫 Misty",
            "腳本依序送入兩個 Explicit Request。",
        ),
        ScenarioStep(
            "決定",
            "先結束 A，再回應 B",
            "A 與 B 各自擁有一個 bounded Episode。",
        ),
        ScenarioStep(
            "模擬動作",
            "向 B 開始新的對話",
            "A 的 Episode Journal 不會混入 B 的內容。",
        ),
    ),
    inputs=(
        ScheduledInput(at_s=0.2, input=TimedText(text="A: Misty，你今天好嗎？")),
        ScheduledInput(at_s=0.6, input=TimedText(text="B: Misty，也跟我打聲招呼。")),
    ),
    decisions=(
        Decision(
            tool="speak",
            args={"text": "A，你好！我今天很好。"},
            tokens_in=24,
            tokens_out=8,
        ),
        Decision(tool="done", args={}, tokens_in=31, tokens_out=1),
        Decision(
            tool="speak",
            args={"text": "B，你好！很高興也認識你。"},
            tokens_in=23,
            tokens_out=9,
        ),
        Decision(tool="done", args={}, tokens_in=32, tokens_out=1),
    ),
)


DEMO_SCENARIOS = (EXPLICIT_TEXT_REQUEST, CRYING_CARE, SPEAKER_HANDOFF)


__all__ = [
    "AcceptanceScenario",
    "CRYING_CARE",
    "DEMO_SCENARIOS",
    "EXPLICIT_TEXT_REQUEST",
    "SPEAKER_HANDOFF",
    "ScenarioAvailability",
    "ScenarioStep",
    "ScenarioModel",
]

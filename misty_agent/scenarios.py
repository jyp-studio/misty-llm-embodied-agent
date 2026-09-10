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

from misty_agent.agent.evidence import EvidenceKind
from misty_agent.agent.react import Decision
from misty_agent.runtime import CueKind, ScheduledInput, TimedText


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
        if not self.actors:
            raise ValueError("a runnable scenario must name its expected episodes")


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
    subtitle="問候進行中仍接收新線索，依優先級安全排隊。",
    availability=ScenarioAvailability.READY,
    ticket="03",
    limitation=(
        "輸入時間與 Cue 類型均為預先定義，只驗證 scheduler；另使用 "
        "scripted model 與 simulated robot，沒有連接 Misty II。"
    ),
    actors=("person", "person", "person", "person"),
    preview=(
        PresentationBeat(
            "input", "收到", "「Misty，你好！」", "語音被分類為明確互動請求。"
        ),
        PresentationBeat(
            "decision",
            "決定",
            "先找出說話方向，再回應",
            "期間的新 cue 只排隊，不搶走 Misty。",
        ),
        PresentationBeat(
            "effect",
            "模擬動作",
            "「嗨！很高興見到你。」",
            "所有 fresh cue 依優先級處理，過期或超量 cue 有明確原因。",
        ),
    ),
    inputs=(
        ScheduledInput(
            at_s=0.5,
            input=TimedText(
                text="Misty，你好！",
                facts={
                    "addressed_robot": True,
                    "cue_kind": "explicit_request",
                },
                uncertainty=("說話者身分未經驗證",),
            ),
        ),
        ScheduledInput(
            at_s=0.6,
            input=TimedText(
                text="揮手",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="same-signal",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=0.7,
            input=TimedText(
                text="再次揮手",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="same-signal",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=0.8,
            input=TimedText(
                text="Misty，我還有一個問題。",
                cue_kind=CueKind.EXPLICIT_REQUEST,
                deduplication_key="same-signal",
                facts={"addressed_robot": True},
            ),
        ),
        ScheduledInput(
            at_s=0.9,
            input=TimedText(
                text="短暫揮手",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="brief-wave",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=1.0,
            input=TimedText(
                text="聲音突然變小",
                cue_kind=CueKind.CARE_CUE,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="care-one",
                facts={"voice_volume_changed": True},
                uncertainty=("原因未知",),
            ),
        ),
        ScheduledInput(
            at_s=1.05,
            input=TimedText(
                text="低頭且沉默",
                cue_kind=CueKind.CARE_CUE,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="care-two",
                facts={"head_lowered": True},
                uncertainty=("不代表特定情緒",),
            ),
        ),
        ScheduledInput(
            at_s=1.09,
            input=TimedText(
                text="已結束的短暫手勢",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                fresh_for_s=0.01,
                facts={"gesture_ended": True},
            ),
        ),
    ),
    decisions=(
        Decision(
            tool="look_around",
            args={},
            tokens_in=18,
            tokens_out=4,
            tool_call_id="call-greeting-look",
            note="先確認問候來自哪個方向。",
        ),
        Decision(
            tool="speak",
            args={"text": "嗨！很高興見到你。"},
            tokens_in=20,
            tokens_out=8,
            tool_call_id="call-greeting-speak",
            note="回應對 Misty 的明確問候。",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=34,
            tokens_out=1,
            tool_call_id="call-greeting-done",
            note="問候已完成，結束這次互動。",
        ),
        Decision(
            tool="speak",
            args={"text": "我在，請說。"},
            tokens_in=18,
            tokens_out=5,
            tool_call_id="call-followup-speak",
            note="先處理等待中的明確請求。",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=24,
            tokens_out=1,
            tool_call_id="call-followup-done",
            note="這個請求已回應。",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=12,
            tokens_out=1,
            tool_call_id="call-care-one-done",
            note="線索不明確，不主動打擾。",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=12,
            tokens_out=1,
            tool_call_id="call-care-two-done",
            note="保留不確定性並結束觀察。",
        ),
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

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
from misty_agent.visual_fixtures import (
    CARE_VISUAL_FIXTURES,
    VISUAL_FIXTURES,
    VisualFixture,
)


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
class AudioFixture:
    """One checked-in synthetic recording offered by the Demo."""

    key: str
    label: str
    asset: str
    transcript: str


@dataclass(frozen=True)
class VisualScenarioScript:
    """Model/Snapshot collaborators for one shared visual fixture."""

    fixture_key: str
    decisions: Tuple[Decision, ...]
    heard_after_first_tool: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fixture_key or not self.decisions:
            raise ValueError("a visual scenario script needs a fixture and decisions")


@dataclass(frozen=True)
class PlannedScenario(ScenarioCard):
    """A roadmap preview with deliberately no executable behavior."""

    def __post_init__(self) -> None:
        if self.availability is not ScenarioAvailability.PLANNED:
            raise ValueError("a planned scenario must have planned availability")
        if not self.ticket:
            raise ValueError("a planned scenario must name its future ticket")


@dataclass(frozen=True)
class TimedSpeech:
    at_s: float
    text: str


class ScenarioSpeech:
    """Finite, timed utterances shared by acceptance tests and the Demo."""

    def __init__(self, clock, utterances: Sequence[TimedSpeech]):
        self._clock = clock
        self._utterances = list(utterances)
        self._start = clock.monotonic()

    def mute_for(self, seconds: float) -> None:
        pass  # Scripted external speech, not acoustic echo or TTS simulation.

    def read(self, timeout: float):
        if self._utterances and self._clock.monotonic() - self._start >= self._utterances[0].at_s:
            return self._utterances.pop(0)
        return None


@dataclass(frozen=True)
class Placement:
    """Where the simulated person stands relative to the chassis at the start."""

    distance_cm: float
    bearing_deg: float = 0.0


@dataclass(frozen=True)
class TextScenarioScript:
    key: str
    label: str
    inputs: Tuple[ScheduledInput, ...]
    decisions: Tuple[Decision, ...]
    speech: Tuple[TimedSpeech, ...] = ()
    placement: Optional[Placement] = None


@dataclass(frozen=True)
class AcceptanceScenario(ScenarioCard):
    """One deterministic, no-hardware story through SocialAgentRuntime."""

    actors: Tuple[str, ...]
    inputs: Tuple[ScheduledInput, ...]
    decisions: Tuple[Decision, ...]
    audio_fixtures: Tuple[AudioFixture, ...] = ()
    visual_fixtures: Tuple[VisualFixture, ...] = ()
    visual_decisions: Tuple[Decision, ...] = ()
    visual_scripts: Tuple[VisualScenarioScript, ...] = ()
    text_scripts: Tuple[TextScenarioScript, ...] = ()

    def __post_init__(self) -> None:
        if self.availability is not ScenarioAvailability.READY:
            raise ValueError("an acceptance scenario must be ready to run")
        if not self.inputs and not self.visual_fixtures and not self.text_scripts:
            raise ValueError("a runnable scenario must declare an input")
        if not self.decisions and not self.visual_scripts and not self.text_scripts:
            raise ValueError("a runnable scenario must declare model decisions")
        text_keys = [script.key for script in self.text_scripts]
        if len(text_keys) != len(set(text_keys)):
            raise ValueError("text scenario scripts need distinct keys")
        if not self.actors:
            raise ValueError("a runnable scenario must name its expected episodes")
        fixture_keys = {fixture.key for fixture in self.visual_fixtures}
        script_keys = [script.fixture_key for script in self.visual_scripts]
        if len(script_keys) != len(set(script_keys)):
            raise ValueError("a visual fixture can have only one scenario script")
        if not set(script_keys) <= fixture_keys:
            raise ValueError("every visual script must name a scenario fixture")

    def visual_script_for(self, fixture_key: str) -> VisualScenarioScript:
        found = next(
            (
                script
                for script in self.visual_scripts
                if script.fixture_key == fixture_key
            ),
            None,
        )
        if found is not None:
            return found
        if self.visual_decisions:
            return VisualScenarioScript(fixture_key, self.visual_decisions)
        raise KeyError(fixture_key)


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


SCRIPTED_ATTRIBUTION = (
    "speaker attribution is scripted: the runtime has no sound-source "
    "direction and no face identity, only anonymous track references"
)


def _said_by(at_s: float, text: str, who: str, **fields) -> ScheduledInput:
    return ScheduledInput(at_s, TimedText(
        text=text, facts={"track_reference": who},
        uncertainty=(SCRIPTED_ATTRIBUTION,), **fields,
    ))


COME_CLOSER = TextScenarioScript(
    key="come-closer",
    label="過來陪我 · 先轉向、再靠近",
    inputs=(_said_by(0.0, "Misty，過來陪我一下", "person-a"),),
    decisions=(
        Decision("speak", {"text": "好，我過去。"}, 20, 4,
                 note="使用者明確邀請；底盤會先對準再靠近。"),
        Decision("approach", {}, 22, 1,
                 note="只表達接近目前 Interaction Target 的意圖；速度與步幅由 controller 決定。"),
        Decision("speak", {"text": "我到了，這個距離可以嗎？"}, 26, 8,
                 note="到達社交距離後確認對方的感受。"),
        Decision("done", {}, 24, 1, note="陪伴已開始，結束 Episode。"),
    ),
    placement=Placement(distance_cm=150.0, bearing_deg=25.0),
)


EXPLICIT_TEXT_REQUEST = AcceptanceScenario(
    name="greeting",
    title="有人和 Misty 打招呼",
    subtitle="選擇錄音或視覺時間線，查看本機 gate 如何決定是否互動。",
    availability=ScenarioAvailability.READY,
    ticket="05",
    limitation=(
        "錄音與視覺 gate 都由目前程式分析 synthetic fixtures；ASR 與 model "
        "使用腳本，robot 為模擬。這不是實機或真實房間的辨識結果。"
    ),
    actors=("person", "person", "person", "person"),
    preview=(
        PresentationBeat(
            "input",
            "選擇 fixture",
            "喚醒錄音或視覺時間線",
            "兩條路徑都先通過本機 gate。",
        ),
        PresentationBeat(
            "decision",
            "本機判斷",
            "只保留 bounded Trigger Evidence",
            "空房與路過者不會呼叫 model。",
        ),
        PresentationBeat(
            "effect",
            "Episode",
            "Misty 做出模擬回應",
            "Runtime、決策與 ending 都由這次執行產生。",
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
    audio_fixtures=(
        AudioFixture(
            key="hey-normal",
            label="Hey Misty · 一般語速",
            asset="hey_misty_normal.wav",
            transcript="Misty，你好！",
        ),
        AudioFixture(
            key="hi-slow",
            label="Hi Misty · 慢速",
            asset="hi_misty_slow.wav",
            transcript="Misty，你好！",
        ),
        AudioFixture(
            key="hey-fast",
            label="Hey Misty · 快速",
            asset="hey_misty_fast.wav",
            transcript="Misty，你好！",
        ),
        AudioFixture(
            key="hey-pause",
            label="Hey … Misty · 含停頓",
            asset="hey_misty_pause.wav",
            transcript="Misty，你好！",
        ),
    ),
    visual_fixtures=VISUAL_FIXTURES,
    visual_decisions=(
        Decision(
            tool="look_around",
            args={},
            tokens_in=18,
            tokens_out=4,
            tool_call_id="call-visual-look",
            note="確認匿名互動邀請仍在畫面中，不靠近對方。",
        ),
        Decision(
            tool="speak",
            args={"text": "嗨，需要我嗎？"},
            tokens_in=20,
            tokens_out=8,
            tool_call_id="call-visual-speak",
            note="以簡短問句回應可能的互動邀請。",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=34,
            tokens_out=1,
            tool_call_id="call-visual-done",
            note="已做低風險回應，結束這次互動。",
        ),
    ),
    text_scripts=(COME_CLOSER,),
)


CALMING_SUPPORT = TextScenarioScript(
    key="calming-support",
    label="請協助我冷靜 · Skill、聆聽與表達",
    inputs=(ScheduledInput(0, TimedText(text="請協助我冷靜")),),
    decisions=(
        Decision("activate_skill", {"name": "supportive-interaction"}, 20, 4,
                 note="先載入支持性互動指引，不診斷或強迫靠近。"),
        Decision("read_skill_resource", {"name": "supportive-interaction", "resource": "references/conversation.md"}, 22, 4,
                 note="需要時才讀取後續對話參考。"),
        Decision("speak", {"text": "我在這裡。你希望安靜陪著，還是想說說話？"}, 30, 8,
                 note="詢問對方希望的陪伴方式。"),
        Decision("listen", {}, 32, 3, note="等待對方回答，不把沉默當作同意。"),
        Decision("move_head", {"roll": 8}, 34, 3, note="以輕微歪頭表達留意，底盤不移動。"),
        Decision("speak", {"text": "好，我會尊重你的空間。"}, 36, 6,
                 note="回應對方希望安靜陪伴的話，停止追問。"),
        Decision("done", {}, 40, 1, note="已回應需求，主動結束並釋放技能脈絡。"),
    ),
    speech=(TimedSpeech(1.0, "安靜陪我就好"),),
)


CRYING_CARE = AcceptanceScenario(
    name="crying-care",
    title="有人在 Misty 面前哭泣",
    subtitle="觀察不確定線索，或在明確求助時載入支持性互動 Skill。",
    availability=ScenarioAvailability.READY,
    ticket="07",
    limitation=(
        "只以 synthetic detector signals 驗證 temporal Care Cue；模型決策、"
        "後續聽到的話與 robot 都是腳本／模擬，未使用真實相機或 Misty II。"
    ),
    preview=(
        PresentationBeat(
            "input", "選擇 fixture", "持續可觀察的臉部／姿勢線索", "保留不確定性，不診斷情緒。"
        ),
        PresentationBeat(
            "decision", "腳本模型決定", "選擇重新觀察、詢問或結束", "不由 gate 固定映射回應。"
        ),
        PresentationBeat(
            "effect",
            "模擬動作",
            "詢問、觀察或保持距離",
            "Journal 會顯示實際 Tool、Observation 與 ending。",
        ),
    ),
    actors=("person",),
    inputs=(),
    decisions=(),
    text_scripts=(CALMING_SUPPORT,),
    visual_fixtures=CARE_VISUAL_FIXTURES,
    visual_scripts=(
        VisualScenarioScript(
            "care-sustained-signals",
            (
                Decision(
                    tool="observe_target",
                    args={},
                    tokens_in=20,
                    tokens_out=4,
                    tool_call_id="call-care-observe",
                    note="先重新觀察可見線索，不把它當成情緒診斷。",
                ),
                Decision(
                    tool="speak",
                    args={"text": "嗨，你希望我留在這裡嗎？"},
                    tokens_in=28,
                    tokens_out=8,
                    tool_call_id="call-care-ask",
                    note="以可拒絕的問題詢問，不靠近對方。",
                ),
                Decision(
                    tool="done",
                    args={},
                    tokens_in=32,
                    tokens_out=1,
                    tool_call_id="call-care-done",
                    note="已低風險詢問，保持距離並結束。",
                ),
            ),
        ),
        VisualScenarioScript(
            "care-expression-words-conflict",
            (
                Decision(
                    tool="inspect_scene",
                    args={},
                    tokens_in=22,
                    tokens_out=4,
                    tool_call_id="call-conflict-inspect",
                    note="先檢查場景；抬高的嘴角本身不能證明感受。",
                ),
                Decision(
                    tool="speak",
                    args={
                        "text": "謝謝你告訴我你很難過。表情線索可能不準；你希望我陪著嗎？"
                    },
                    tokens_in=34,
                    tokens_out=15,
                    tool_call_id="call-conflict-ask",
                    note="尊重本人明確說出的感受，並澄清是否需要陪伴。",
                ),
                Decision(
                    tool="done",
                    args={},
                    tokens_in=38,
                    tokens_out=1,
                    tool_call_id="call-conflict-done",
                    note="已詢問且未強迫靠近，結束。",
                ),
            ),
            heard_after_first_tool=("我其實很難過",),
        ),
    ),
)


#: The actor name single-person cards use; the Demo reads it as "someone".
DEFAULT_ACTOR = "person"

A_THEN_B = TextScenarioScript(
    key="a-then-b",
    label="A 互動中 B 呼叫 · 排隊、收尾、交接",
    inputs=(
        _said_by(0.0, "Hi Misty，我是 A", "person-a"),
        _said_by(0.5, "Hey Misty，換我", "person-b"),
    ),
    decisions=(
        Decision("speak", {"text": "你好 A，今天想聊什麼？"}, 20, 6,
                 note="回應 A；A 是本次 Episode 唯一的 Interaction Target。"),
        Decision("listen", {}, 22, 3, note="等待 A 回答。"),
        Decision("speak", {"text": "B 在等我，我們先聊到這裡，再見。"}, 30, 8,
                 note="收到交接通知：向 A 說明並收尾，不平行處理 B。"),
        Decision("done", {}, 24, 1, note="A 的 Episode 結束，釋放 target。"),
        Decision("speak", {"text": "你好 B，換你了，有什麼想說的？"}, 20, 8,
                 note="B 的新 Episode 從新的 Trigger Evidence 與新 target 開始。"),
        Decision("done", {}, 22, 1, note="B 的互動完成。"),
    ),
    speech=(TimedSpeech(0.6, "今天天氣不錯"),),
)


B_EXPIRES = TextScenarioScript(
    key="b-expires",
    label="B 呼叫後離開 · 過期 cue 不開 Episode",
    inputs=(
        _said_by(0.0, "Hi Misty，我是 A", "person-a"),
        _said_by(0.5, "Hey Misty，換我", "person-b", fresh_for_s=0.3),
    ),
    decisions=(
        Decision("speak", {"text": "你好 A，今天想聊什麼？"}, 20, 6,
                 note="回應 A；A 是本次 Episode 唯一的 Interaction Target。"),
        Decision("listen", {}, 22, 3, note="等待 A 回答。"),
        Decision("listen", {}, 22, 3,
                 note="收到交接通知；先聽 A 說完，不中斷。"),
        Decision("speak", {"text": "剛才有人叫我，不過我們先聊完。"}, 26, 8,
                 note="B 的 cue 已過期；不依舊資料強行交接。"),
        Decision("done", {}, 24, 1, note="A 的 Episode 結束。"),
    ),
    speech=(TimedSpeech(0.6, "今天天氣不錯"),),
)


SPEAKER_HANDOFF = AcceptanceScenario(
    name="speaker-handoff",
    title="A 聊完後，切換成 B",
    subtitle="A 互動中 B 明確呼叫：B 先排隊，A 在 Turn boundary 收尾後，B 才取得新 Episode。",
    availability=ScenarioAvailability.READY,
    ticket="08",
    limitation=(
        "兩位 actors 的發言歸屬由腳本指定；系統沒有聲源方向或人臉身分，只用"
        "匿名 track reference。model 決策與後續話語為腳本，robot 為模擬。"
    ),
    actors=("A", "B"),
    preview=(
        PresentationBeat(
            "input",
            "收到",
            "A 互動期間，B 明確呼叫 Misty",
            "B 的 request 先進入 Cue queue，不平行開 Episode，也不丟棄。",
        ),
        PresentationBeat(
            "decision",
            "決定",
            "在 Turn boundary 告知 model，讓 A 得到收尾",
            "只有 bumper／e-stop 才能立即中止，不必等交接。",
        ),
        PresentationBeat(
            "effect",
            "動作",
            "B 取得新 Episode 與新 target",
            "上一個 Interaction Target 不被繼承；過期的 B 不會被強行處理。",
        ),
    ),
    inputs=(),
    decisions=(),
    text_scripts=(A_THEN_B, B_EXPIRES),
)


DEMO_SCENARIOS = (EXPLICIT_TEXT_REQUEST, CRYING_CARE, SPEAKER_HANDOFF)


__all__ = [
    "AcceptanceScenario",
    "AudioFixture",
    "CRYING_CARE",
    "DEMO_SCENARIOS",
    "EXPLICIT_TEXT_REQUEST",
    "PlannedScenario",
    "PresentationBeat",
    "SPEAKER_HANDOFF",
    "A_THEN_B",
    "COME_CLOSER",
    "Placement",
    "B_EXPIRES",
    "SCRIPTED_ATTRIBUTION",
    "DEFAULT_ACTOR",
    "ScenarioCard",
    "ScenarioAvailability",
    "ScenarioModel",
    "VisualFixture",
    "VisualScenarioScript",
]

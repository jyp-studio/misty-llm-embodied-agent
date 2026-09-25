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
    #: Whether the card's other timed cues follow the recording. The greeting
    #: card's recordings share a queue-stress timeline (dedupe, replace,
    #: overflow, expiry) that opens several Episodes; a fixture that stands
    #: for one plain greeting has to leave it out, or it is not one greeting.
    with_other_cues: bool = True


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
    #: Scenario-provided safety timeline: when something blocks the path, and
    #: when the person stops being measurable. Simulated state, never sensed.
    hazard_at_s: Optional[float] = None
    leaves_at_s: Optional[float] = None


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
    label="Come keep me company · turn, then approach",
    inputs=(_said_by(0.0, "Misty, come over and keep me company.", "person-a"),),
    decisions=(
        Decision("speak", {"text": "Okay, I'm coming over."}, 20, 4,
                 note="They invited me explicitly; the chassis aligns before closing in."),
        Decision("approach", {}, 22, 1,
                 note="Express only the intent to approach the current Interaction Target; the controller decides how the chassis gets there."),
        Decision("speak", {"text": "I'm here. Is this distance okay for you?"}, 26, 8,
                 note="Arrived at a social distance; check how they feel about it."),
        Decision("done", {}, 24, 1, note="Company has started; end the Episode."),
    ),
    placement=Placement(distance_cm=150.0, bearing_deg=25.0),
)


COME_CLOSER_TARGET_LOST = TextScenarioScript(
    key="come-closer-target-lost",
    label="Come keep me company · they leave midway, so it stops and says so",
    inputs=(_said_by(0.0, "Misty, come over and keep me company.", "person-a"),),
    decisions=(
        Decision("speak", {"text": "Okay, I'm coming over."}, 20, 4, note="They invited me explicitly."),
        Decision("approach", {}, 22, 1, note="Approach the current Interaction Target."),
        Decision("speak", {"text": "I can't see you any more, so I'll stop here."}, 24, 8,
                 note="The controller reported the target lost; speak instead of driving blind."),
        Decision("done", {}, 22, 1, note="Nobody is there; end the Episode."),
    ),
    placement=Placement(distance_cm=150.0, bearing_deg=0.0, leaves_at_s=1.2),
)


COME_CLOSER_HAZARD = TextScenarioScript(
    key="come-closer-hazard",
    label="Come keep me company · an obstacle appears, so it stops at once",
    inputs=(_said_by(0.0, "Misty, come over and keep me company.", "person-a"),),
    decisions=(
        Decision("speak", {"text": "Okay, I'm coming over."}, 20, 4, note="They invited me explicitly."),
        Decision("approach", {}, 22, 1, note="Approach the current Interaction Target."),
        Decision("speak", {"text": "Something is in my way, so I'll stay here and we can talk from here."}, 26, 10,
                 note="The controller reported blocked and halted the chassis; talk from a distance instead."),
        Decision("done", {}, 22, 1, note="Do not force the approach; end the Episode."),
    ),
    placement=Placement(distance_cm=150.0, bearing_deg=0.0, hazard_at_s=1.2),
)


GOOD_NEWS = TextScenarioScript(
    key="good-news",
    label="Sharing good news · words and face agree, no needless movement",
    inputs=(_said_by(0.0, "Misty, I just got accepted!", "person-a"),),
    decisions=(
        Decision("speak", {"text": "That's wonderful, congratulations!"}, 20, 6,
                 note="Answer what they shared, in a matching tone."),
        Decision("display_image", {"expression": "happy"}, 20, 3,
                 note="The face matches the words; this is expression, not movement."),
        Decision("done", {}, 18, 1, note="The news was answered; nothing unrelated to add."),
    ),
)


VAGUE_HELP = TextScenarioScript(
    key="vague-help",
    label="Just \"I need help\" · asks first instead of guessing",
    inputs=(_said_by(0.0, "Misty, I need help.", "person-a"),),
    decisions=(
        Decision("speak", {"text": "I'm here. What kind of help do you need?"}, 20, 6,
                 note="Ask rather than guess what they need."),
        Decision("listen", {}, 20, 3, note="Let them explain in their own words."),
        Decision("speak", {"text": "Okay, let's look for them together."}, 20, 6,
                 note="Answer the need they actually said out loud."),
        Decision("done", {}, 18, 1, note="The need was confirmed and answered."),
    ),
    speech=(TimedSpeech(1.0, "I can't find my keys."),),
)


QUESTION_NO_MOVEMENT = TextScenarioScript(
    key="question-no-movement",
    label="A question that needs no movement · just answers",
    inputs=(_said_by(0.0, "Misty, what can you do?", "person-a"),),
    decisions=(
        Decision("speak", {"text": "I can talk, listen to you, turn my head and move my arms."}, 24, 10,
                 note="Answer directly; do not approach just to show off."),
        Decision("done", {}, 18, 1, note="The question is answered; no reason to move."),
    ),
)


EXPLICIT_TEXT_REQUEST = AcceptanceScenario(
    name="greeting",
    title="Starting a conversation",
    subtitle="A wake phrase, a wave, an invitation to come closer — and people it should leave alone.",
    availability=ScenarioAvailability.READY,
    ticket="05",
    limitation=(
        "The wake and visual gates analyse synthetic fixtures; the robot is "
        "simulated. This is not recognition in a real room or on a real robot."
    ),
    actors=("person", "person", "person", "person"),
    preview=(
        PresentationBeat(
            "input",
            "Pick an example",
            "A wake recording, a frame timeline or a sentence",
            "Every path passes a local gate first.",
        ),
        PresentationBeat(
            "decision",
            "Local decision",
            "Only bounded Trigger Evidence is kept",
            "An empty room or a passer-by never reaches the model.",
        ),
        PresentationBeat(
            "effect",
            "Episode",
            "Misty answers in simulation",
            "The runtime records, decisions and ending all come from this run.",
        ),
    ),
    inputs=(
        ScheduledInput(
            at_s=0.5,
            input=TimedText(
                text="Hey Misty, hello!",
                facts={
                    "addressed_robot": True,
                    "cue_kind": "explicit_request",
                },
                uncertainty=("speaker identity is unverified",),
            ),
        ),
        ScheduledInput(
            at_s=0.6,
            input=TimedText(
                text="waving",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="same-signal",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=0.7,
            input=TimedText(
                text="waving again",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="same-signal",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=0.8,
            input=TimedText(
                text="Misty, I have one more question.",
                cue_kind=CueKind.EXPLICIT_REQUEST,
                deduplication_key="same-signal",
                facts={"addressed_robot": True},
            ),
        ),
        ScheduledInput(
            at_s=0.9,
            input=TimedText(
                text="a brief wave",
                cue_kind=CueKind.SOCIAL_INVITATION,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="brief-wave",
                facts={"wave_observed": True},
            ),
        ),
        ScheduledInput(
            at_s=1.0,
            input=TimedText(
                text="voice suddenly quieter",
                cue_kind=CueKind.CARE_CUE,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="care-one",
                facts={"voice_volume_changed": True},
                uncertainty=("cause unknown",),
            ),
        ),
        ScheduledInput(
            at_s=1.05,
            input=TimedText(
                text="head lowered and silent",
                cue_kind=CueKind.CARE_CUE,
                evidence_kind=EvidenceKind.VISUAL,
                deduplication_key="care-two",
                facts={"head_lowered": True},
                uncertainty=("does not indicate any particular emotion",),
            ),
        ),
        ScheduledInput(
            at_s=1.09,
            input=TimedText(
                text="a brief gesture that has already ended",
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
            note="First find which direction the greeting came from.",
        ),
        Decision(
            tool="speak",
            args={"text": "Hi! Nice to see you."},
            tokens_in=20,
            tokens_out=8,
            tool_call_id="call-greeting-speak",
            note="Answer a greeting addressed to Misty.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=34,
            tokens_out=1,
            tool_call_id="call-greeting-done",
            note="The greeting is done; end this interaction.",
        ),
        Decision(
            tool="speak",
            args={"text": "I'm here, go ahead."},
            tokens_in=18,
            tokens_out=5,
            tool_call_id="call-followup-speak",
            note="Handle the waiting explicit request first.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=24,
            tokens_out=1,
            tool_call_id="call-followup-done",
            note="This request has been answered.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=12,
            tokens_out=1,
            tool_call_id="call-care-one-done",
            note="The cue is unclear; do not intrude.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=12,
            tokens_out=1,
            tool_call_id="call-care-two-done",
            note="Keep the uncertainty and stop observing.",
        ),
    ),
    audio_fixtures=(
        AudioFixture(
            key="hey-normal",
            label="Hey Misty · normal pace",
            asset="hey_misty_normal.wav",
            transcript="Hey Misty, hello!",
        ),
        AudioFixture(
            key="hi-slow",
            label="Hi Misty · slow",
            asset="hi_misty_slow.wav",
            transcript="Hey Misty, hello!",
        ),
        AudioFixture(
            key="hey-fast",
            label="Hey Misty · fast",
            asset="hey_misty_fast.wav",
            transcript="Hey Misty, hello!",
        ),
        AudioFixture(
            key="hey-pause",
            label="Hey … Misty · with a pause",
            asset="hey_misty_pause.wav",
            transcript="Hey Misty, hello!",
        ),
        AudioFixture(
            key="hey-greeting-only",
            label="Hey Misty · a single greeting",
            asset="hey_misty_normal.wav",
            transcript="Hey Misty, hello!",
            with_other_cues=False,
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
            note="Check the anonymous invitation is still in view, without approaching.",
        ),
        Decision(
            tool="speak",
            args={"text": "Hi, do you need me?"},
            tokens_in=20,
            tokens_out=8,
            tool_call_id="call-visual-speak",
            note="Answer a possible invitation with a short question.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=34,
            tokens_out=1,
            tool_call_id="call-visual-done",
            note="A low-risk answer is given; end this interaction.",
        ),
    ),
    text_scripts=(
        COME_CLOSER,
        COME_CLOSER_TARGET_LOST,
        COME_CLOSER_HAZARD,
        GOOD_NEWS,
        VAGUE_HELP,
        QUESTION_NO_MOVEMENT,
    ),
)


CALMING_SUPPORT = TextScenarioScript(
    key="calming-support",
    label="Help me calm down · a Skill, listening and expression",
    inputs=(ScheduledInput(0, TimedText(text="Please help me calm down.")),),
    decisions=(
        Decision("activate_skill", {"name": "supportive-interaction"}, 20, 4,
                 note="Load the supportive-interaction guidance first; no diagnosis, no forced approach."),
        Decision("read_skill_resource", {"name": "supportive-interaction", "resource": "references/conversation.md"}, 22, 4,
                 note="Read the conversation reference only when it is needed."),
        Decision("speak", {"text": "I'm here. Would you like me to stay quietly, or would you like to talk?"}, 30, 8,
                 note="Ask what kind of company they want."),
        Decision("listen", {}, 32, 3, note="Wait for their answer; silence is not consent."),
        Decision("move_head", {"roll": 8}, 34, 3, note="Tilt the head slightly to show attention; the chassis stays put."),
        Decision("speak", {"text": "Okay, I'll respect your space."}, 36, 6,
                 note="They asked for quiet company; stop asking questions."),
        Decision("done", {}, 40, 1, note="The request is answered; finish and release the Skill context."),
    ),
    speech=(TimedSpeech(1.0, "Just stay with me quietly."),),
)


RESPECT_BOUNDARY = TextScenarioScript(
    key="respect-boundary",
    label="Wants to be alone · stops moving and briefly stops intruding",
    inputs=(
        _said_by(0.0, "Please don't come closer. I want to be alone for a while.", "person-a"),
        # Two non-explicit cues: one arrives while the Episode is still
        # running and waits in the queue, one arrives later so the page shows
        # the countdown actually counting down. Both are observable signals,
        # not speech, and the Demo must not quote them as something the
        # person said.
        _said_by(
            0.0,
            "head kept lowered, shoulders heaving (observable cue)",
            "person-a",
            cue_kind=CueKind.CARE_CUE,
        ),
        _said_by(
            6.0,
            "head lowered again (observable cue)",
            "person-a",
            cue_kind=CueKind.CARE_CUE,
        ),
        _said_by(12.0, "Misty, I need you now.", "person-a"),
    ),
    decisions=(
        Decision(
            "speak",
            {"text": "Okay, I'll stay right here."},
            20,
            6,
            note="Briefly acknowledge the stated boundary; no more questions.",
        ),
        Decision(
            "respect_boundary",
            {},
            22,
            1,
            note="Halt the chassis and end the Episode by respecting the boundary.",
        ),
        Decision(
            "speak",
            {"text": "I'm here. What do you need right now?"},
            20,
            8,
            note="Answer the new explicit request; it may bypass suppression.",
        ),
        Decision("done", {}, 22, 1, note="The new explicit request has been answered."),
    ),
)


ZH_EMERGENCY_SUPPORT = TextScenarioScript(
    key="zh-emergency-support",
    label="High-risk request in Chinese · stays, states its limits, points to real help",
    inputs=(_said_by(0.0, "我覺得我快撐不下去了", "person-a"),),
    decisions=(
        Decision("speak", {"text": "我在這裡，我聽到你說的話了。"}, 20, 6,
                 note="Let them know someone is here before offering any advice."),
        Decision("activate_skill", {"name": "emergency-boundaries"}, 22, 4,
                 note="Load the high-risk boundary guidance."),
        Decision("listen", {}, 22, 3, note="Let them speak; silence is not an answer."),
        Decision(
            "speak",
            {
                "text": "我沒有辦法判斷你的狀況，也沒有辦法幫你聯絡任何人。"
                        "如果可以，請找身邊信任的人，或是打給當地的緊急服務。"
            },
            30, 12,
            note="State the limits plainly and point to people who can act; no diagnosis, no contacting anyone.",
        ),
        Decision("speak", {"text": "在那之前，我會待在這裡陪你。"}, 22, 6,
                 note="Stay, without promising an outcome."),
        Decision("done", {}, 20, 1, note="Gave the company and information it can give."),
    ),
    speech=(TimedSpeech(1.0, "我不知道可以找誰。"),),
)


EN_RESCUE_LIMITS = TextScenarioScript(
    key="en-rescue-limits",
    label="English rescue request · says what it cannot do, and stays",
    inputs=(
        _said_by(0.0, "I am trapped under this shelf. Can you lift it off me?", "person-a"),
    ),
    decisions=(
        Decision("speak", {"text": "I am here with you. I cannot lift that, and I have no way to move it."}, 22, 10,
                 note="State the capability limit first; it is about the robot, not the person."),
        Decision("activate_skill", {"name": "emergency-boundaries"}, 22, 4,
                 note="Load the high-risk guidance."),
        Decision("listen", {}, 22, 3, note="Let them answer before saying more."),
        Decision(
            "speak",
            {
                "text": "I have no way to reach anyone outside this room. Your "
                        "local emergency services are the fastest help."
            },
            30, 12,
            note="No third party is contacted or claimed; point at help that can act.",
        ),
        Decision(
            "speak",
            {
                "text": "If someone is within earshot, calling out may reach "
                        "them sooner. I will stay here with you."
            },
            22, 10,
            note="Offer the option it actually has, and stay.",
        ),
        Decision("done", {}, 20, 1, note="Stayed, and gave what it actually has."),
    ),
    speech=(TimedSpeech(1.0, "Then can you call someone for me?"),),
)


CRYING_CARE = AcceptanceScenario(
    name="crying-care",
    title="Care and boundaries",
    subtitle="Uncertain signs of distress, a request for space, and moments where it must say what it cannot do.",
    availability=ScenarioAvailability.READY,
    ticket="07",
    limitation=(
        "The temporal Care Cue is exercised only with synthetic detector "
        "signals; the robot is simulated. No real camera or Misty II was used."
    ),
    preview=(
        PresentationBeat(
            "input", "Pick an example", "Sustained observable face and posture cues", "Uncertainty is kept; no emotion is diagnosed."
        ),
        PresentationBeat(
            "decision", "The model decides", "Look again, ask, or leave them be", "The gate does not map cues to a fixed response."
        ),
        PresentationBeat(
            "effect",
            "Simulated action",
            "Ask, observe or keep its distance",
            "The Journal shows the actual Tools, Observations and ending.",
        ),
    ),
    actors=("person",),
    inputs=(),
    decisions=(),
    text_scripts=(
        CALMING_SUPPORT,
        RESPECT_BOUNDARY,
        ZH_EMERGENCY_SUPPORT,
        EN_RESCUE_LIMITS,
    ),
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
                    note="Look at the visible cues again first; they are not an emotion diagnosis.",
                ),
                Decision(
                    tool="speak",
                    args={"text": "Hi, would you like me to stay here?"},
                    tokens_in=28,
                    tokens_out=8,
                    tool_call_id="call-care-ask",
                    note="Ask a question they can decline, without approaching.",
                ),
                Decision(
                    tool="done",
                    args={},
                    tokens_in=32,
                    tokens_out=1,
                    tool_call_id="call-care-done",
                    note="A low-risk question was asked; keep the distance and finish.",
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
                    note="Inspect the scene first; raised mouth corners prove nothing about feelings.",
                ),
                Decision(
                    tool="speak",
                    args={
                        "text": "Thank you for telling me you feel sad. Facial cues can be wrong. Would you like me to stay with you?"
                    },
                    tokens_in=34,
                    tokens_out=15,
                    tool_call_id="call-conflict-ask",
                    note="Believe the feeling they stated, and ask whether they want company.",
                ),
                Decision(
                    tool="done",
                    args={},
                    tokens_in=38,
                    tokens_out=1,
                    tool_call_id="call-conflict-done",
                    note="Asked without forcing an approach; finish.",
                ),
            ),
            heard_after_first_tool=("Actually, I feel really sad.",),
        ),
    ),
)


#: The actor name single-person cards use; the Demo reads it as "someone".
DEFAULT_ACTOR = "person"

A_THEN_B = TextScenarioScript(
    key="a-then-b",
    label="A keeps context, then B starts clean",
    inputs=(
        _said_by(0.0, "Hi Misty, it's A.", "person-a"),
        _said_by(0.5, "Hey Misty, my turn.", "person-b"),
    ),
    decisions=(
        Decision("speak", {"text": "Hi A, what would you like to talk about today?"}, 20, 6,
                 note="Answer A; A is this Episode's only Interaction Target."),
        Decision("listen", {}, 22, 3, note="Wait for A to answer."),
        Decision("speak", {"text": "B is waiting for me, so let's stop here. Goodbye!"}, 30, 8,
                 note="A handoff notice arrived: explain to A and wrap up; B is not handled in parallel."),
        Decision("done", {}, 24, 1, note="A's Episode ends and the target is released."),
        Decision("speak", {"text": "Hi B, your turn. What would you like to say?"}, 20, 8,
                 note="B's new Episode starts from new Trigger Evidence and a new target."),
        Decision("done", {}, 22, 1, note="B's interaction is done."),
    ),
    speech=(TimedSpeech(0.6, "The weather is nice today."),),
)


B_EXPIRES = TextScenarioScript(
    key="b-expires",
    label="B calls, then leaves · a stale cue opens no Episode",
    inputs=(
        _said_by(0.0, "Hi Misty, it's A.", "person-a"),
        _said_by(0.5, "Hey Misty, my turn.", "person-b", fresh_for_s=0.3),
    ),
    decisions=(
        Decision("speak", {"text": "Hi A, what would you like to talk about today?"}, 20, 6,
                 note="Answer A; A is this Episode's only Interaction Target."),
        Decision("listen", {}, 22, 3, note="Wait for A to answer."),
        Decision("listen", {}, 22, 3,
                 note="A handoff notice arrived; let A finish first without interrupting."),
        Decision("speak", {"text": "Someone called me just now, but let's finish our chat first."}, 26, 8,
                 note="B's cue has expired; no forced handoff on stale data."),
        Decision("done", {}, 24, 1, note="A's Episode ends."),
    ),
    speech=(TimedSpeech(0.6, "The weather is nice today."),),
)


SPEAKER_HANDOFF = AcceptanceScenario(
    name="speaker-handoff",
    title="Two people, one at a time",
    subtitle="A's context stays in A's Episode; B queues, gets a handoff, and starts from fresh Trigger Evidence.",
    availability=ScenarioAvailability.READY,
    ticket="12",
    limitation=(
        "Who said what is assigned by the example: the runtime has no "
        "sound-source direction and no face identity, only anonymous track "
        "references. The robot is simulated."
    ),
    actors=("A", "B"),
    preview=(
        PresentationBeat(
            "input",
            "Heard",
            "While A is talking, B calls Misty",
            "B's request waits in the Cue queue: no parallel Episode, and not dropped.",
        ),
        PresentationBeat(
            "decision",
            "Decide",
            "The model is told at a Turn boundary, so A gets a proper goodbye",
            "Only a bumper or e-stop stops it immediately; a handoff waits.",
        ),
        PresentationBeat(
            "effect",
            "Act",
            "B gets a new Episode, a new target and a clean context",
            "A's name, words and Skill instructions are not inherited; a stale B is never forced.",
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
    "GOOD_NEWS",
    "VAGUE_HELP",
    "QUESTION_NO_MOVEMENT",
    "RESPECT_BOUNDARY",
    "ZH_EMERGENCY_SUPPORT",
    "EN_RESCUE_LIMITS",
    "COME_CLOSER_HAZARD",
    "COME_CLOSER_TARGET_LOST",
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

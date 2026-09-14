"""Ticket 06: uncertain visual Care Cues stay evidence, not diagnoses."""

from __future__ import annotations

import json
from dataclasses import replace

from misty_agent.agent.journal import DecisionNoted, Observation, ToolCalled
from misty_agent.agent.react import Decision
from misty_agent.app import simulated_session
from misty_agent.fakes import FakeClock
from misty_agent.runtime import RuntimeEnding, SocialAgentRuntime
from misty_agent.scenarios import ScenarioModel
from misty_agent.visual_fixtures import care_visual_fixture
from misty_agent.visual_input import (
    BoundingBox,
    LocalVisualGate,
    ObservablePersonGeometry,
    VisualFixtureSource,
    VisualInputAdapter,
)


class CapturesContexts(ScenarioModel):
    def __init__(self, decisions):
        super().__init__(decisions)
        self.contexts = []

    def decide(self, working_context, tools):
        self.contexts.append(tuple(working_context))
        return super().decide(working_context, tools)


class Heard:
    def __init__(self, text: str) -> None:
        self.text = text


class ScriptedEars:
    def __init__(self, *heard: str) -> None:
        self._heard = [Heard(text) for text in heard]

    def mute_for(self, seconds: float) -> None:
        return None

    def read(self, timeout: float):
        return self._heard.pop(0) if self._heard else None


def decision(tool: str, *, args=None, note: str) -> Decision:
    return Decision(
        tool=tool,
        args=args or {},
        tokens_in=12,
        tokens_out=4,
        tool_call_id=f"care-{tool}",
        note=note,
    )


def run_care(fixture_key: str, decisions, *, heard=()):
    clock = FakeClock()
    gate = LocalVisualGate()
    model = CapturesContexts(decisions)
    source = VisualInputAdapter(
        frames=VisualFixtureSource(
            clock, care_visual_fixture(fixture_key).frames
        ),
        clock=clock,
        gate=gate,
    )
    session = simulated_session(
        None,
        model=model,
        clock=clock,
        ears=ScriptedEars(*heard),
        active_perception=gate,
    )
    result = SocialAgentRuntime(
        source=source,
        session=session,
        clock=clock,
    ).run()
    return result, model


def test_temporal_observable_signals_form_an_uncertain_care_cue():
    result, model = run_care(
        "care-sustained-signals",
        (
            decision(
                "observe_target",
                note="先重新觀察可見線索，不把它當成情緒診斷。",
            ),
            decision("done", note="線索仍不確定，保持距離並結束。"),
        ),
    )

    assert result.ending is RuntimeEnding.INPUT_EXHAUSTED
    assert len(result.episodes) == 1
    episode = result.episodes[0]
    assert episode.cue_kind.value == "care_cue"
    assert episode.evidence.source.value == "visual"
    assert episode.evidence.transcript == ""
    assert episode.evidence.uncertainty
    facts = episode.evidence.facts
    assert facts["eyes_narrowed"] is True
    assert facts["mouth_open"] is True
    assert facts["head_lowered"] is True
    forbidden = ("emotion", "diagnosis", "sad", "crying", "distress")
    serialized = json.dumps(facts).lower()
    assert not any(word in serialized for word in forbidden)

    records = episode.journal.records
    assert any(isinstance(item, DecisionNoted) for item in records)
    called = [item.tool for item in records if isinstance(item, ToolCalled)]
    assert "observe_target" in called
    assert result.episodes[0].outcome.outcome == "done"
    assert not ({"approach", "move_head", "move_arms"} & set(called))
    observed = next(item for item in records if isinstance(item, Observation))
    assert observed.result["kind"] == "target_observation"
    assert observed.result["cost"] == "cheap"
    assert observed.result["fresh_for_s"] > 0
    assert observed.result["uncertainty"]
    assert model.contexts


def test_one_expression_frame_does_not_open_an_episode():
    fixture = care_visual_fixture("care-sustained-signals")
    clock = FakeClock()
    source = VisualInputAdapter(
        frames=VisualFixtureSource(clock, fixture.frames[:1]),
        clock=clock,
    )
    model = CapturesContexts((decision("done", note="沒有互動。"),))
    result = SocialAgentRuntime(
        source=source,
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    ).run()

    assert result.episodes == ()
    assert model.contexts == []


def test_one_confident_frame_does_not_rescue_weak_temporal_evidence():
    fixture = care_visual_fixture("care-sustained-signals")
    weak_frames = tuple(
        replace(
            frame,
            detections=tuple(
                replace(
                    detected,
                    confidence=(0.92 if index == 2 else 0.2),
                )
                for detected in frame.detections
            ),
        )
        for index, frame in enumerate(fixture.frames)
    )
    clock = FakeClock()
    model = CapturesContexts((decision("done", note="沒有互動。"),))
    result = SocialAgentRuntime(
        source=VisualInputAdapter(
            frames=VisualFixtureSource(clock, weak_frames),
            clock=clock,
        ),
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    ).run()

    assert result.episodes == ()
    assert model.contexts == []


def test_same_care_cue_can_end_without_any_intervention():
    result, _ = run_care(
        "care-sustained-signals",
        (decision("done", note="不確定對方是否希望互動，先不介入。"),),
    )

    records = result.episodes[0].journal.records
    assert [item.tool for item in records if isinstance(item, ToolCalled)] == [
        "done"
    ]
    assert result.episodes[0].outcome.outcome == "done"
    assert result.episodes[0].outcome.steps == 0


def test_explicit_words_override_ambiguous_expression_geometry():
    result, model = run_care(
        "care-expression-words-conflict",
        (
            decision(
                "inspect_scene",
                note="先檢查場景；抬高的嘴角本身不能證明感受。",
            ),
            decision(
                "speak",
                args={
                    "text": "謝謝你告訴我你很難過。表情線索可能不準；你希望我陪著嗎？"
                },
                note="尊重對方明確說出的感受，並以問題澄清需要。",
            ),
            decision("done", note="已詢問且未強迫靠近，結束。"),
        ),
        heard=("我其實很難過",),
    )

    episode = result.episodes[0]
    called = [
        item for item in episode.journal.records if isinstance(item, ToolCalled)
    ]
    assert {"inspect_scene", "speak", "done"} <= {
        item.tool for item in called
    }
    inspection = next(
        item for item in episode.journal.records
        if isinstance(item, Observation) and item.result.get("kind") == "scene_inspection"
    )
    assert inspection.result["cost"] == "expensive"
    assert inspection.result["fresh_for_s"] > 0
    assert inspection.snapshot.new_speech == "我其實很難過"
    second_context = model.contexts[1]
    assert "我其實很難過" in json.dumps(second_context, ensure_ascii=False)
    spoken = called[1].args["text"]
    assert "難過" in spoken
    assert any(term in spoken for term in ("不準", "不確定", "可能"))
    assert "approach" not in [item.tool for item in called]


def test_active_perception_reports_unavailable_after_target_leaves_frame():
    fixture = care_visual_fixture("care-sustained-signals")
    gate = LocalVisualGate()
    cue = None
    for index, visual_frame in enumerate(fixture.frames):
        _, cue = gate.observe(
            observed_at=visual_frame.at_s,
            frame_index=index,
            image=visual_frame.image,
            detections=visual_frame.detections,
        )
    assert cue is not None
    target = gate.for_track(cue.track_reference)

    gate.observe(
        observed_at=0.6,
        frame_index=3,
        image=fixture.frames[-1].image,
        detections=(),
    )
    observed = target.observe_target(now_s=0.6).as_tool_result()
    inspected = target.inspect_scene(now_s=0.6).as_tool_result()

    assert observed["ending"] == "unavailable"
    assert inspected["ending"] == "unavailable"
    assert observed["age_s"] == 0.2
    assert observed["fresh"] is False
    assert observed["facts"] == {}


def test_queued_tracks_cannot_replace_the_episode_bound_target():
    fixture = care_visual_fixture("care-sustained-signals")
    gate = LocalVisualGate()
    cue = None
    for index, visual_frame in enumerate(fixture.frames):
        _, cue = gate.observe(
            observed_at=visual_frame.at_s,
            frame_index=index,
            image=visual_frame.image,
            detections=visual_frame.detections,
        )
    assert cue is not None
    target = gate.for_track(cue.track_reference)
    first = fixture.frames[-1].detections[0]
    neutral_first = replace(first, geometry=ObservablePersonGeometry())
    second = replace(
        first,
        bounds=BoundingBox(x=0.7, y=0.2, width=0.2, height=0.4),
    )
    queued_cue = None
    for index, at_s in enumerate((0.6, 0.8, 1.0), start=3):
        _, queued_cue = gate.observe(
            observed_at=at_s,
            frame_index=index,
            image=fixture.frames[-1].image,
            detections=(neutral_first, second),
        )
    assert queued_cue is not None
    assert queued_cue.track_reference != cue.track_reference

    observed = target.observe_target(now_s=1.0).as_tool_result()

    assert observed["ending"] == "observed"
    assert observed["facts"]["track_reference"] == cue.track_reference

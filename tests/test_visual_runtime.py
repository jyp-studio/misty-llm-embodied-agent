"""Ticket 05 acceptance coverage through ``SocialAgentRuntime``.

The temporal fixtures describe local detector outputs over several frames.
They test the real tracking/gating state machine without claiming that a still
image proves waving, camera accuracy, or Misty hardware behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from misty_agent.agent.react import Decision
from misty_agent.app import simulated_session
from misty_agent.fakes import FakeClock
from misty_agent.runtime import (
    RuntimeEnding,
    SocialAgentRuntime,
    VisualAttentionRecorded,
)
from misty_agent.scenarios import ScenarioModel
from misty_agent.visual_fixtures import visual_fixture
from misty_agent.visual_input import (
    BoundingBox,
    LocalVisualDetection,
    MediaPipeVisualDetector,
    NormalizedPoint,
    ScheduledVisualFrame,
    VisualFixtureSource,
    VisualInputAdapter,
)


FRAME = np.full((120, 160, 3), 245, dtype=np.uint8)


class CapturesFirstTurn(ScenarioModel):
    def __init__(self, *decisions: Decision) -> None:
        super().__init__(decisions)
        self.contexts = []

    def decide(self, working_context, tools):
        self.contexts.append(tuple(working_context))
        return super().decide(working_context, tools)


def detection(
    *,
    x: float = 0.15,
    looking: bool,
    hand_x: float | None = None,
    confidence: float = 0.92,
) -> LocalVisualDetection:
    return LocalVisualDetection(
        bounds=BoundingBox(x=x, y=0.2, width=0.2, height=0.4),
        confidence=confidence,
        looking=looking,
        hand_center=(
            NormalizedPoint(hand_x, 0.35)
            if hand_x is not None
            else None
        ),
    )


def frame(at_s: float, *detections: LocalVisualDetection):
    return ScheduledVisualFrame(
        at_s=at_s,
        image=FRAME.copy(),
        detections=tuple(detections),
    )


def run_frames(frames, *decisions):
    clock = FakeClock()
    model = CapturesFirstTurn(*decisions)
    source = VisualInputAdapter(
        frames=VisualFixtureSource(clock, tuple(frames)),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=source,
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    ).run()
    return result, model


def done():
    return Decision(
        tool="done",
        args={},
        tokens_in=8,
        tokens_out=1,
        tool_call_id="visual-done",
        note="No further interaction is needed.",
    )


def low_risk_greeting():
    return (
        Decision(
            tool="speak",
            args={"text": "嗨！"},
            tokens_in=12,
            tokens_out=3,
            tool_call_id="visual-greet",
            note="Acknowledge the possible invitation without approaching.",
        ),
        done(),
    )


def visual_records(result):
    return [
        record
        for record in result.records
        if isinstance(record, VisualAttentionRecorded)
    ]


def test_an_empty_room_never_opens_an_episode():
    result, model = run_frames(
        visual_fixture("visual-empty-room").frames,
        done(),
    )

    assert result.ending is RuntimeEnding.INPUT_EXHAUSTED
    assert result.episodes == ()
    assert model.contexts == []
    assert [record.outcome.value for record in visual_records(result)] == [
        "empty",
        "empty",
        "empty",
    ]


def test_a_passerby_who_never_looks_or_gestures_is_ignored():
    result, model = run_frames(
        visual_fixture("visual-passerby").frames,
        done(),
    )

    assert result.episodes == ()
    assert model.contexts == []
    assert all(
        record.outcome.value == "not_looking"
        for record in visual_records(result)
    )


def test_one_still_frame_cannot_claim_to_prove_a_wave():
    result, model = run_frames(
        (frame(0.0, detection(looking=True, hand_x=0.5)),),
        done(),
    )

    assert result.episodes == ()
    assert model.contexts == []


def test_sustained_gaze_and_temporal_wave_form_one_social_invitation():
    result, model = run_frames(
        visual_fixture("visual-gaze-wave").frames,
        *low_risk_greeting(),
    )

    assert len(result.episodes) == 1
    episode = result.episodes[0]
    assert episode.cue_kind.value == "social_invitation"
    assert episode.evidence.source.value == "visual"
    assert episode.evidence.transcript == ""
    assert episode.evidence.observed_at_s == 0.6
    assert episode.evidence.facts == {
        "looking": True,
        "wave_observed": True,
        "gaze_duration_s": 0.6,
        "wave_span": 0.48,
        "direction_changes": 2,
        "observed_frames": 4,
        "selected_frame_index": 3,
        "person_count": 1,
        "track_reference": "anon-1",
        "confidence": 0.92,
    }
    assert episode.evidence.selected_image_media_type == "image/jpeg"
    assert episode.input.selected_image is None
    assert [record.outcome.value for record in visual_records(result)][-1] == (
        "qualified"
    )
    first_turn = model.contexts[0]
    message = next(entry for entry in first_turn if entry["role"] == "user")
    assert [part["type"] for part in message["content"]] == ["text", "image"]
    assert sum(part["type"] == "image" for part in message["content"]) == 1
    assert "approach" not in [
        record.tool
        for record in episode.journal.records
        if hasattr(record, "tool")
    ]


def test_the_model_can_choose_no_interaction_after_the_gate_qualifies():
    result, model = run_frames(
        visual_fixture("visual-gaze-wave").frames,
        done(),
    )

    assert len(model.contexts) == 1
    assert result.episodes[0].outcome.outcome == "done"
    assert result.episodes[0].journal.records[-1].steps == 0


def test_multiple_faces_keep_stable_anonymous_tracks_when_order_changes():
    result, _ = run_frames(
        visual_fixture("visual-two-people").frames,
        done(),
    )

    assert len(result.episodes) == 1
    assert result.episodes[0].evidence.facts["track_reference"] == "anon-1"
    b_records = [
        record
        for record in visual_records(result)
        if record.track_reference == "anon-2"
    ]
    assert len(b_records) == 4
    assert all(record.outcome.value == "not_looking" for record in b_records)


def test_a_hand_motion_without_sustained_gaze_is_a_negative_control():
    frames = (
        frame(0.0, detection(looking=False, hand_x=0.1)),
        frame(0.2, detection(looking=True, hand_x=0.6)),
        frame(0.4, detection(looking=False, hand_x=0.1)),
        frame(0.6, detection(looking=True, hand_x=0.6)),
    )

    result, model = run_frames(frames, done())

    assert result.episodes == ()
    assert model.contexts == []


def test_an_old_hand_motion_does_not_later_become_a_wave():
    frames = (
        frame(0.0, detection(looking=True, hand_x=0.1)),
        frame(0.2, detection(looking=True, hand_x=0.55)),
        frame(0.4, detection(looking=True, hand_x=0.12)),
        frame(0.8, detection(looking=True)),
        frame(1.2, detection(looking=True)),
        frame(1.4, detection(looking=True, hand_x=0.58)),
    )

    result, model = run_frames(frames, done())

    assert result.episodes == ()
    assert model.contexts == []


def test_one_high_confidence_frame_does_not_rescue_a_weak_sequence():
    frames = (
        frame(0.0, detection(looking=True, hand_x=0.1, confidence=0.2)),
        frame(0.2, detection(looking=True, hand_x=0.55, confidence=0.2)),
        frame(0.4, detection(looking=True, hand_x=0.12, confidence=0.2)),
        frame(0.6, detection(looking=True, hand_x=0.58, confidence=0.92)),
    )

    result, model = run_frames(frames, done())

    assert result.episodes == ()
    assert model.contexts == []


def test_turn_boundary_visual_drain_has_a_fixed_frame_bound():
    clock = FakeClock()
    source = VisualInputAdapter(
        frames=VisualFixtureSource(
            clock,
            tuple(frame(0.0) for _ in range(20)),
        ),
        clock=clock,
        maximum_frames_per_drain=8,
    )
    source.start()

    first = source.read_available()
    second = source.read_available()

    assert len(first) == 8
    assert len(second) == 8
    assert source.exhausted is False
    source.stop()


def test_fixture_nonblocking_read_does_not_consume_a_future_frame():
    clock = FakeClock()
    source = VisualFixtureSource(clock, (frame(1.0),))
    source.start()

    assert source.read_frame(timeout=0.0) is None
    assert clock.monotonic() == 0.0
    assert source.exhausted is False
    source.stop()


def test_one_local_hand_signal_is_not_assigned_to_two_faces():
    class Produces:
        def __init__(self, **result):
            self._result = SimpleNamespace(**result)

        def process(self, image):
            return self._result

    def face_at(x):
        box = SimpleNamespace(xmin=x, ymin=0.2, width=0.2, height=0.4)
        return SimpleNamespace(
            score=(0.9,),
            location_data=SimpleNamespace(relative_bounding_box=box),
        )

    wrist = SimpleNamespace(x=0.2, y=0.35)
    detector = MediaPipeVisualDetector.__new__(MediaPipeVisualDetector)
    detector._face_detection = Produces(
        detections=(face_at(0.6), face_at(0.1))
    )
    detector._face_mesh = Produces(multi_face_landmarks=())
    detector._hands = Produces(
        multi_hand_landmarks=(SimpleNamespace(landmark=(wrist,)),)
    )

    detections = detector.detect(FRAME)

    assert detections[0].hand_center is None
    assert detections[1].hand_center == NormalizedPoint(0.2, 0.35)

"""One Episode, one anonymous Interaction Target; never a silent switch.

The visual gate keeps several candidate tracks, but only the track the
Trigger Evidence named is the Episode's target. A closer, larger or newer
face is a different anonymous track and must not be reported as the target.
"""

from __future__ import annotations

import numpy as np
import pytest

from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.agent.journal import Journal
from misty_agent.agent.target import InteractionTarget, TargetState
from misty_agent.agent.tools import ToolContext, build_registry, dispatch
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter
from misty_agent.perception.active import (
    ActivePerceptionCost,
    ActivePerceptionEnding,
    ActivePerceptionKind,
    ActivePerceptionResult,
)
from misty_agent.visual_input import (
    BoundingBox,
    LocalVisualDetection,
    LocalVisualGate,
    VisualGatePolicy,
)

FRAME = np.full((120, 160, 3), 245, dtype=np.uint8)


def face(x: float, *, width: float = 0.2, confidence: float = 0.9) -> LocalVisualDetection:
    return LocalVisualDetection(
        bounds=BoundingBox(x=x, y=0.2, width=width, height=width * 2),
        confidence=confidence,
        looking=True,
    )


def observed(*, visible: bool, reference="anon-1"):
    if visible:
        return ActivePerceptionResult(
            kind=ActivePerceptionKind.TARGET_OBSERVATION,
            cost=ActivePerceptionCost.CHEAP,
            ending=ActivePerceptionEnding.OBSERVED,
            age_s=0.0,
            fresh_for_s=2.0,
            facts={"track_reference": reference, "visible": True},
        )
    return ActivePerceptionResult(
        kind=ActivePerceptionKind.TARGET_OBSERVATION,
        cost=ActivePerceptionCost.CHEAP,
        ending=ActivePerceptionEnding.UNAVAILABLE,
        age_s=0.4,
        fresh_for_s=2.0,
        uncertainty=("not in the latest frame",),
    )


def test_a_target_is_bound_from_evidence_and_moves_between_lost_and_reacquired():
    visual = InteractionTarget.from_evidence(TriggerEvidence(
        source=EvidenceKind.VISUAL, observed_at_s=1.5,
        facts={"track_reference": "anon-1", "confidence": 0.9},
    ))
    assert visual.reference == "anon-1"
    assert visual.state is TargetState.BOUND
    assert visual.as_facts() == {"track_reference": "anon-1", "state": "bound", "bound_at": 1.5}

    assert visual.update_from(observed(visible=True)) is TargetState.VISIBLE
    assert visual.update_from(observed(visible=False)) is TargetState.LOST
    assert visual.update_from(observed(visible=True)) is TargetState.REACQUIRED
    assert visual.update_from(observed(visible=True)) is TargetState.VISIBLE
    with pytest.raises(ValueError, match="another anonymous track"):
        visual.update_from(observed(visible=True, reference="anon-2"))

    speech_only = InteractionTarget.from_evidence(TriggerEvidence(
        source=EvidenceKind.SPEECH, observed_at_s=0.0, transcript="Hi Misty",
    ))
    assert speech_only.reference is None
    assert speech_only.state is TargetState.UNOBSERVABLE
    assert speech_only.update_from(observed(visible=False)) is TargetState.UNOBSERVABLE


def test_a_closer_larger_or_newer_face_never_replaces_the_bound_track():
    """Negative control: the intruder's numbers are distinct, so reporting
    them would be caught, not mistaken for the target."""
    gate = LocalVisualGate(VisualGatePolicy(track_ttl_s=1.0))
    gate.observe(observed_at=0.0, frame_index=0, image=FRAME, detections=(face(0.15),))
    target = gate.for_track("anon-1")

    intruder = face(0.6, width=0.35, confidence=0.99)
    gate.observe(observed_at=0.2, frame_index=1, image=FRAME, detections=(face(0.16), intruder))
    seen = target.observe_target(now_s=0.2)
    assert seen.ending is ActivePerceptionEnding.OBSERVED
    assert seen.facts["track_reference"] == "anon-1"
    assert seen.facts["confidence"] == 0.9 != intruder.confidence

    gate.observe(observed_at=0.4, frame_index=2, image=FRAME, detections=(intruder,))
    lost = target.observe_target(now_s=0.4)
    assert lost.ending is ActivePerceptionEnding.UNAVAILABLE
    assert "track_reference" not in lost.facts

    gate.observe(observed_at=0.6, frame_index=3, image=FRAME, detections=(face(0.17), intruder))
    back = target.observe_target(now_s=0.6)
    assert back.ending is ActivePerceptionEnding.OBSERVED
    assert back.facts["track_reference"] == "anon-1"

    # After the anonymous track expires, a face standing in the same place is
    # a new track: the Episode's target is not reacquired by position alone.
    gate.observe(observed_at=2.0, frame_index=4, image=FRAME, detections=(intruder,))
    gate.observe(observed_at=2.2, frame_index=5, image=FRAME, detections=(face(0.15), intruder))
    stale = target.observe_target(now_s=2.2)
    assert stale.ending is ActivePerceptionEnding.UNAVAILABLE
    fresh_reference = gate.observe(
        observed_at=2.4, frame_index=6, image=FRAME, detections=(face(0.15),)
    )[0][0].track_reference
    assert fresh_reference not in {"anon-1", "anon-2"}


def test_active_perception_tools_report_and_update_the_episode_target():
    clock = FakeClock()
    gate = LocalVisualGate()
    gate.observe(observed_at=0.0, frame_index=0, image=FRAME, detections=(face(0.15),))
    target = InteractionTarget("anon-1", EvidenceKind.VISUAL, 0.0)
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()), readings=None, config=Settings(), clock=clock,
        active_perception=gate.for_track("anon-1"), target=target,
    )
    registry = build_registry()
    journal = Journal(episode_id="ep-1")

    seen = dispatch(registry, "observe_target", {}, ctx, journal, turn=1)
    assert seen.result["target"] == {"track_reference": "anon-1", "state": "visible", "bound_at": 0.0}

    gate.observe(observed_at=0.3, frame_index=1, image=FRAME, detections=())
    clock.sleep(0.3)
    gone = dispatch(registry, "inspect_scene", {}, ctx, journal, turn=2)
    assert gone.result["ending"] == "unavailable"
    assert gone.result["target"]["state"] == "lost"
    assert target.state is TargetState.LOST


def test_approach_refuses_to_move_toward_a_lost_target_but_not_an_unobservable_one():
    robot = RecordingCommands()
    lost = InteractionTarget("anon-1", EvidenceKind.VISUAL, 0.0)
    lost.update_from(observed(visible=False))
    ctx = ToolContext(robot=RealMistyAdapter(robot), readings=None, config=Settings(), clock=FakeClock(), target=lost)

    refused = dispatch(build_registry(), "approach", {}, ctx, Journal(episode_id="ep-1"), turn=1)
    assert refused.result["result"] == "lost_user"
    assert refused.result["steps"] == 0
    assert refused.result["target"]["state"] == "lost"
    assert "drive/time" not in robot.endpoints

    class NobodyThere:
        def latest_reading(self):
            return None

    unobservable = InteractionTarget(None, EvidenceKind.SPEECH, 0.0)
    ctx = ToolContext(robot=RealMistyAdapter(robot), readings=NobodyThere(), config=Settings(), clock=FakeClock(), target=unobservable)
    outcome = dispatch(build_registry(), "approach", {}, ctx, Journal(episode_id="ep-1"), turn=1)
    assert outcome.result["result"] == "lost_user"
    assert outcome.result["target"]["state"] == "unobservable"

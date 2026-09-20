"""Acceptance coverage for the autonomous runtime seam.

These tests start at ``SocialAgentRuntime``.  Calling ``Session.episode``
directly would prove the old one-shot runner again and miss the Attention
Loop that this effort exists to add.
"""

from __future__ import annotations

import base64
import json
import threading

import pytest

from misty_agent.agent.journal import (
    ToolCalled,
    DecisionNoted,
    EpisodeFinished,
    ExecutionFailed,
    StopRequested,
)
from misty_agent.agent.react import Decision
from misty_agent.app import SystemClock, simulated_session
from misty_agent.config import Settings
from misty_agent.demo import answer
from misty_agent.fakes import FakeClock
from misty_agent.runtime import (
    AnonymousTrackReference,
    CueSuppressionClearReason,
    CueDequeued,
    CueDeduplicated,
    CueDropped,
    CueDropReason,
    CueKind,
    EvidenceKind,
    MAX_SELECTED_IMAGE_BYTES,
    CueQueued,
    CueReplaced,
    InputArrival,
    RuntimeEnding,
    RuntimeState,
    ScenarioInputAdapter,
    ScheduledInput,
    SelectedImageEvidence,
    SocialAgentRuntime,
    TimedText,
    VisualAttentionNotice,
    VisualAttentionOutcome,
    VisualCue,
)
from misty_agent.scenarios import EXPLICIT_TEXT_REQUEST, ScenarioModel


def text_at(at_s, text, **input_fields):
    return ScheduledInput(
        at_s=at_s, input=TimedText(text=text, **input_fields)
    )


def test_a_timed_explicit_request_runs_from_attention_to_a_simulated_effect():
    """Ticket 01's tracer bullet crosses the new highest public seam."""
    clock = FakeClock()
    source = ScenarioInputAdapter(
        clock,
        EXPLICIT_TEXT_REQUEST.inputs[:1],
    )
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions[:3]),
        clock=clock,
    )
    runtime = SocialAgentRuntime(source=source, session=session, clock=clock)

    result = runtime.run()

    assert result.ending == "input_exhausted"
    assert runtime.state is RuntimeState.STOPPED
    assert [record.type for record in result.records] == [
        "attention_started",
        "cue_detected",
        "episode_opened",
        "episode_completed",
        "attention_stopped",
    ]
    assert result.records[1].cue_kind == "explicit_request"
    assert result.records[1].evidence_kind == "speech"
    assert result.records[1].t == EXPLICIT_TEXT_REQUEST.inputs[0].at_s
    assert len(result.episodes) == 1
    episode = result.episodes[0]
    assert episode.outcome.outcome == "done"
    assert isinstance(episode.journal.records[-1], EpisodeFinished)
    assert session.robot.speech, "the simulated Misty said nothing"


def test_trigger_evidence_reaches_the_first_turn_before_any_observation():
    """Ticket 02 begins at the runtime seam, not inside ``run_episode``."""

    class CapturesFirstTurn(ScenarioModel):
        def __init__(self):
            super().__init__(EXPLICIT_TEXT_REQUEST.decisions)
            self.contexts = []

        def decide(self, working_context, tools):
            self.contexts.append(tuple(working_context))
            return super().decide(working_context, tools)

    clock = FakeClock()
    model = CapturesFirstTurn()
    selected = SelectedImageEvidence(
        media_type="image/png",
        data_base64="c2VsZWN0ZWQtaW1hZ2U=",
    )
    source = ScenarioInputAdapter(
        clock,
        [
            ScheduledInput(
                at_s=0.25,
                input=TimedText(
                    text="Misty, can you see me?",
                    evidence_kind=EvidenceKind.VISUAL,
                    facts={"face_present": True, "is_looking": True},
                    uncertainty=("distance is a monocular estimate",),
                    selected_image=selected,
                ),
            )
        ],
    )
    session = simulated_session(None, model=model, clock=clock)

    result = SocialAgentRuntime(
        source=source, session=session, clock=clock
    ).run()

    first_turn = model.contexts[0]
    evidence_message = next(
        entry for entry in first_turn if entry["role"] == "user"
    )
    assert evidence_message["content"] == [
        {
            "type": "text",
            "text": {
                "trigger_evidence": {
                    "source": "visual",
                    "observed_at_s": 0.25,
                    "facts": {
                        "face_present": True,
                        "is_looking": True,
                    },
                    "transcript": "Misty, can you see me?",
                    "uncertainty": ["distance is a monocular estimate"],
                }
            },
        },
        {
            "type": "image",
            "media_type": "image/png",
            "data_base64": "c2VsZWN0ZWQtaW1hZ2U=",
        },
    ]
    assert not any(entry["role"] == "tool" for entry in first_turn)
    second_turn = model.contexts[1]
    observation = next(entry for entry in second_turn if entry["role"] == "tool")
    assert "snapshot" in observation["content"]
    assert "trigger_evidence" not in observation["content"]
    assert result.episodes[0].evidence.observed_at_s == 0.25
    assert result.episodes[0].input.selected_image is None
    assert (
        result.episodes[0].evidence.selected_image_media_type == "image/png"
    )
    assert "c2VsZWN0ZWQtaW1hZ2U=" not in repr(result)


def test_a_visual_cue_reaches_the_first_turn_without_inventing_a_transcript():
    class CapturesFirstTurn(ScenarioModel):
        def __init__(self):
            super().__init__(
                (Decision(tool="done", args={}, tokens_in=1, tokens_out=1),)
            )
            self.contexts = []

        def decide(self, working_context, tools):
            self.contexts.append(tuple(working_context))
            return super().decide(working_context, tools)

    clock = FakeClock()
    model = CapturesFirstTurn()
    cue = VisualCue(
        description="anonymous person looked toward Misty and waved",
        track_reference="anon-1",
        confidence=0.91,
        facts={"looking": True, "wave_observed": True},
        selected_image=SelectedImageEvidence(
            media_type="image/jpeg",
            data_base64="c2VsZWN0ZWQ=",
        ),
    )

    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock, [ScheduledInput(at_s=0.5, input=cue)]
        ),
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    ).run()

    evidence = result.episodes[0].evidence
    assert evidence.source is EvidenceKind.VISUAL
    assert evidence.transcript == ""
    assert evidence.facts["track_reference"] == "anon-1"
    content = next(
        entry["content"]
        for entry in model.contexts[0]
        if entry["role"] == "user"
    )
    assert [part["type"] for part in content] == ["text", "image"]


def test_selected_image_evidence_owns_its_encoding_and_size_boundaries():
    with pytest.raises(ValueError, match="base64"):
        SelectedImageEvidence(media_type="image/png", data_base64="not base64!")

    too_large = base64.b64encode(
        b"x" * (MAX_SELECTED_IMAGE_BYTES + 1)
    ).decode()
    with pytest.raises(ValueError, match="too large"):
        SelectedImageEvidence(media_type="image/png", data_base64=too_large)


def test_an_invalid_decision_note_still_closes_the_episode_as_an_error():
    clock = FakeClock()
    decision = Decision(
        tool="done",
        args={},
        tokens_in=1,
        tokens_out=1,
        note="Use linearVelocity to finish.",
    )
    session = simulated_session(
        None, model=ScenarioModel((decision,)), clock=clock
    )

    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, [text_at(0.0, "Hello Misty")]),
        session=session,
        clock=clock,
    ).run()

    assert result.ending is RuntimeEnding.EPISODE_ERROR
    assert len(result.episodes) == 1
    records = result.episodes[0].journal.records
    assert any(
        isinstance(record, ExecutionFailed) and record.phase == "model"
        for record in records
    )
    assert isinstance(records[-1], EpisodeFinished)
    assert records[-1].outcome == "error"


def test_trigger_evidence_reuses_the_cue_detection_timestamp(tmp_path):
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )

    def slow_journal_path(_episode_number):
        clock.sleep(9.0)
        return tmp_path / "episode.jsonl"

    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, [text_at(0.25, "Hello Misty")]),
        session=session,
        clock=clock,
    ).run(journal_path_for_episode=slow_journal_path)

    cue = result.records[1]
    assert result.episodes[0].evidence.observed_at_s == cue.t == 0.25


def test_a_public_decision_note_is_recorded_without_private_reasoning():
    clock = FakeClock()
    decisions = (
        Decision(
            tool="speak",
            args={"text": "Hello."},
            tokens_in=10,
            tokens_out=2,
            tool_call_id="call-greet",
            note="Acknowledge the person's explicit greeting.",
        ),
        Decision(
            tool="done",
            args={},
            tokens_in=14,
            tokens_out=1,
            tool_call_id="call-finish",
            note="The greeting has been answered.",
        ),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )

    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, [text_at(0.0, "Hello Misty")]),
        session=session,
        clock=clock,
    ).run()

    notes = [
        record
        for record in result.episodes[0].journal.records
        if isinstance(record, DecisionNoted)
    ]
    assert [note.note for note in notes] == [
        "Acknowledge the person's explicit greeting.",
        "The greeting has been answered.",
    ]
    assert [note.tool_call_id for note in notes] == [
        "call-greet",
        "call-finish",
    ]
    assert all(set(note.__dataclass_fields__) == {
        "t", "episode_id", "turn", "tool_call_id", "note", "type"
    } for note in notes)


def test_an_input_source_reports_age_without_sharing_the_runtime_clock():
    """Live providers report age; declarative schedules stay in the adapter."""

    class ImmediateTextInput:
        def __init__(self) -> None:
            self.remaining = [TimedText(text="Misty, hello")]

        def start(self) -> None:
            pass

        def read(self):
            if not self.remaining:
                return None
            return InputArrival(
                age_s=0.0, input=self.remaining.pop(0)
            )

        def read_available(self):
            return ()

        def stop(self) -> None:
            pass

    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )

    result = SocialAgentRuntime(
        source=ImmediateTextInput(), session=session, clock=clock
    ).run()

    assert result.episodes[0].input == TimedText(text="Misty, hello")


@pytest.mark.parametrize("age_s", [-0.1, float("inf"), float("nan")])
def test_an_input_arrival_refuses_an_invalid_age(age_s):
    with pytest.raises(ValueError, match="finite and non-negative"):
        InputArrival(age_s=age_s, input=TimedText(text="hello"))


def test_a_cue_freshness_override_must_be_finite():
    with pytest.raises(ValueError, match="fresh_for_s"):
        TimedText(text="hello", fresh_for_s=float("nan"))


@pytest.mark.parametrize("at_s", [-0.1, float("inf"), float("nan")])
def test_a_scenario_time_must_be_finite_and_non_negative(at_s):
    with pytest.raises(ValueError, match="finite and non-negative"):
        text_at(at_s, "hello")


def test_the_demo_replays_a_text_case_that_crossed_the_runtime_seam():
    """The built-in tracer is generated by the runtime, not a direct Episode."""
    reply = answer("GET", "/examples/runtime_explicit_text_request")

    assert reply.status == 200
    payload = json.loads(reply.body)
    assert payload["example"]["name"] == EXPLICIT_TEXT_REQUEST.name
    assert payload["runtime"]["records"][1]["text"] == (
        EXPLICIT_TEXT_REQUEST.inputs[0].input.text
    )
    assert [record["type"] for record in payload["runtime"]["records"]] == [
        "attention_started",
        "cue_detected",
        "episode_opened",
        "episode_completed",
        "attention_stopped",
    ]
    assert payload["runtime"]["episodes"][0]["cue_kind"] == "explicit_request"
    assert [moment["type"] for moment in payload["runtime"]["timeline"]] == [
        "attention_started",
        "cue_detected",
        "episode_opened",
        "episode_completed",
        "attention_stopped",
    ]
    assert payload["storyboard"]["outcome"] == "done"
    assert payload["storyboard"]["moments"][-1]["kind"] == "episode_finished"
    page = answer("GET", "/").body.decode()
    assert 'id="runtime"' in page
    assert "runtime.timeline" in page


def test_text_entered_in_the_demo_also_crosses_the_runtime(monkeypatch):
    """The old one-shot Episode is no longer the Demo's product boundary."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr(
        "misty_agent.demo.OpenAIModel",
        lambda: ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
    )
    body = json.dumps({"trigger": "speech", "said": "Misty, hello"}).encode()

    payload = json.loads(answer("POST", "/run", body).body)

    assert payload["runtime"]["records"][1]["type"] == "cue_detected"
    assert payload["runtime"]["episodes"][0]["cue_kind"] == "explicit_request"
    assert payload["storyboard"]["outcome"] == "done"


def test_an_input_failure_still_stops_the_runtime_with_a_bounded_result():
    """A broken adapter must not strand the Attention Loop in ``running``."""

    class BrokenInput:
        def __init__(self) -> None:
            self.stopped = False

        def start(self) -> None:
            pass

        def read(self):
            raise RuntimeError("scenario input failed")

        def stop(self) -> None:
            self.stopped = True

    clock = FakeClock()
    source = BrokenInput()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )
    runtime = SocialAgentRuntime(source=source, session=session, clock=clock)

    result = runtime.run()

    assert result.ending == "runtime_error"
    assert [record.type for record in result.records] == [
        "attention_started",
        "runtime_failed",
        "attention_stopped",
    ]
    assert source.stopped
    assert runtime.state is RuntimeState.STOPPED


def test_shutdown_aborts_the_active_episode_and_returns_a_bounded_result():
    """Runtime shutdown may interrupt an Episode but never strand one."""

    class StopsDuringDecision:
        runtime = None

        def decide(self, working_context, tools):
            self.runtime.stop()
            return Decision(
                tool="speak",
                args={"text": "this must not be spoken"},
                tokens_in=10,
                tokens_out=2,
            )

    clock = FakeClock()
    model = StopsDuringDecision()
    session = simulated_session(None, model=model, clock=clock)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock, [text_at(0.0, "Misty, hello")]
        ),
        session=session,
        clock=clock,
    )
    model.runtime = runtime

    result = runtime.run()

    assert result.ending == "shutdown"
    assert result.episodes[0].outcome.outcome == "aborted"
    stops = [
        record
        for record in result.episodes[0].journal.records
        if isinstance(record, StopRequested)
    ]
    assert [stop.source for stop in stops] == ["runtime_shutdown"]
    assert session.robot.speech is None


def test_shutdown_interrupts_a_source_that_is_waiting_for_input():
    """Shutdown cannot wait for an input source's next scheduled event."""

    class WaitingInput:
        def __init__(self) -> None:
            self.reading = threading.Event()
            self.released = threading.Event()

        def start(self) -> None:
            pass

        def read(self):
            self.reading.set()
            self.released.wait()
            return None

        def stop(self) -> None:
            self.released.set()

    clock = FakeClock()
    source = WaitingInput()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )
    runtime = SocialAgentRuntime(source=source, session=session, clock=clock)
    result = []
    runner = threading.Thread(target=lambda: result.append(runtime.run()), daemon=True)
    runner.start()
    assert source.reading.wait(timeout=1), "the source never started waiting"

    runtime.stop()
    runner.join(timeout=1)
    try:
        assert not runner.is_alive(), "shutdown left the input read blocked"
        assert result[0].ending == "shutdown"
    finally:
        source.stop()
        runner.join(timeout=1)


def test_shutdown_interrupts_scenario_adapter_before_a_future_input_is_due():
    """The concrete no-hardware adapter honours the InputSource stop contract."""
    entered_read = threading.Event()

    class SignalsRead(ScenarioInputAdapter):
        def read(self):
            entered_read.set()
            return super().read()

    clock = SystemClock()
    source = SignalsRead(
        clock,
        [text_at(60.0, "a request that must never become due")],
    )
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )
    runtime = SocialAgentRuntime(source=source, session=session, clock=clock)
    result = []
    runner = threading.Thread(target=lambda: result.append(runtime.run()), daemon=True)
    runner.start()
    assert entered_read.wait(timeout=1), "the adapter never began its timed wait"

    runtime.stop()
    runner.join(timeout=1)

    assert not runner.is_alive()
    assert result[0].ending == "shutdown"
    assert result[0].episodes == ()


def test_the_existing_turn_cap_remains_the_runtime_episode_bound():
    """The autonomous shell does not weaken the inner ReAct bound."""

    assert Settings().max_turns_per_episode == 12

    class KeepsTalking:
        def decide(self, working_context, tools):
            return Decision(
                tool="speak",
                args={"text": "still going"},
                tokens_in=10,
                tokens_out=2,
            )

    clock = FakeClock()
    session = simulated_session(None, model=KeepsTalking(), clock=clock)
    session.config = Settings(max_turns_per_episode=2)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock, [text_at(0.0, "Misty, hello")]
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    episode = result.episodes[0]
    assert episode.outcome.outcome == "turn_limit"
    assert episode.outcome.turns == 2
    assert [r.tool for r in episode.journal.records if isinstance(r, ToolCalled)] == ["speak", "speak"]


def test_an_episode_error_closes_both_episode_and_runtime():
    """Dependency failures remain typed endings at the highest seam."""

    class ModelFails:
        def decide(self, working_context, tools):
            raise RuntimeError("model connection failed")

    clock = FakeClock()
    session = simulated_session(None, model=ModelFails(), clock=clock)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock, [text_at(0.0, "Misty, hello")]
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    assert result.ending == "episode_error"
    assert result.episodes[0].outcome.outcome == "error"
    assert result.episodes[0].journal.records[-1].outcome == "error"
    assert result.records[-1].type == "attention_stopped"


def test_two_requests_never_own_the_robot_at_the_same_time():
    """A later cue opens only after the earlier Episode has completed."""

    class StopsEachEpisode:
        def decide(self, working_context, tools):
            return Decision(tool="done", args={}, tokens_in=8, tokens_out=1)

    clock = FakeClock()
    session = simulated_session(None, model=StopsEachEpisode(), clock=clock)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "first request"),
                text_at(0.1, "second request"),
            ],
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    boundaries = [
        record.type
        for record in result.records
        if record.type in {"episode_opened", "episode_completed"}
    ]
    assert boundaries == [
        "episode_opened",
        "episode_completed",
        "episode_opened",
        "episode_completed",
    ]
    assert len(result.episodes) == 2


def test_explicit_refusal_stops_movement_and_suppresses_only_non_explicit_reentry():
    """Ticket 13's highest seam: the model acknowledges a boundary, the
    controller halts, and Runtime throttles the anonymous track without
    blocking a later direct request."""
    clock = FakeClock()
    decisions = (
        Decision(
            tool="speak",
            args={"text": "好的，我會留在這裡。"},
            tokens_in=8,
            tokens_out=4,
        ),
        Decision(
            tool="respect_boundary", args={}, tokens_in=8, tokens_out=1
        ),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(
                    0.0,
                    "請不要靠近，我想一個人靜一靜",
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    0.0,
                    "same-track care cue",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    0.0,
                    "Misty，我現在需要你",
                    facts={"track_reference": "anon-1"},
                ),
            ],
        ),
        session=session,
        clock=clock,
    ).run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-3"]
    assert result.episodes[0].outcome.boundary_respected is True
    assert session.robot.halted is True
    assert session.robot.speech == "好的，我會留在這裡。"
    assert not any(
        isinstance(record, ToolCalled) and record.tool == "approach"
        for episode in result.episodes
        for record in episode.journal.records
    )
    suppression = [
        record
        for record in result.records
        if record.type
        in {
            "cue_suppression_started",
            "cue_suppressed",
            "cue_suppression_bypassed",
        }
    ]
    assert [record.type for record in suppression] == [
        "cue_suppression_started",
        "cue_suppressed",
        "cue_suppression_bypassed",
    ]
    assert suppression[0].track_reference == "anon-1"
    assert suppression[1].cue_id == "cue-2"
    assert suppression[2].cue_id == "cue-3"
    # A check that can fail: the whole field set, not one guessed name, and
    # nothing the person said anywhere in the values. A record that grew a
    # `name`, an embedding or a copy of the transcript would trip this.
    assert [set(vars(record)) for record in suppression] == [
        {"t", "type", "track_reference", "expires_at_s"},
        {"t", "type", "track_reference", "cue_id", "cue_kind", "remaining_s"},
        {"t", "type", "track_reference", "cue_id"},
    ]
    spoken = "please leave me alone"
    assert not any(
        spoken in str(value)
        for record in suppression
        for value in vars(record).values()
    )


def test_cue_suppression_repeats_until_but_not_at_the_ttl_boundary():
    """The rule is `now >= expires_at`, read off the records rather than
    from a literal instant: the Episode that starts the throttle costs a
    little clock of its own, so a hardcoded boundary would be measuring the
    Episode's cost instead of the rule."""
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(
                    tool="respect_boundary", args={}, tokens_in=8, tokens_out=1
                ),
                Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
            )
        ),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(
                    0.0,
                    "leave me alone",
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    0.2,
                    "care again",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    0.4,
                    "wave again",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    1.2,
                    "care past the boundary",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
            ],
        ),
        session=session,
        clock=clock,
        config=Settings(cue_suppression_s=1.0),
    ).run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-4"]
    assert [
        record.cue_id for record in result.records
        if record.type == "cue_suppressed"
    ] == ["cue-2", "cue-3"]
    started = next(
        record for record in result.records
        if record.type == "cue_suppression_started"
    )
    expired = next(
        record for record in result.records
        if record.type == "cue_suppression_cleared"
    )
    assert expired.reason.value == "expired"
    assert expired.t >= started.expires_at_s
    # Every cue that was throttled arrived strictly before the expiry, and
    # the one that reopened arrived at or after it. That is the `>=`.
    detected = {
        record.cue_id: record.t
        for record in result.records
        if record.type == "cue_detected"
    }
    assert all(
        detected[cue_id] < started.expires_at_s for cue_id in ("cue-2", "cue-3")
    )
    assert detected["cue-4"] >= started.expires_at_s


def test_cue_suppression_is_scoped_to_one_anonymous_track():
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(
                    tool="respect_boundary", args={}, tokens_in=8, tokens_out=1
                ),
                Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
            )
        ),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(
                    0.0,
                    "not now",
                    facts={"track_reference": "anon-1"},
                ),
                text_at(
                    0.1,
                    "different person care cue",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-2"},
                ),
                text_at(
                    0.2,
                    "same person care cue",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
            ],
        ),
        session=session,
        clock=clock,
    ).run()

    # The control: anon-2 gets its Episode while anon-1's identical cue is
    # suppressed in the same run. Without it this test would still pass with
    # suppression switched off entirely.
    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-2"]
    suppressed = [
        record for record in result.records if record.type == "cue_suppressed"
    ]
    assert [record.track_reference for record in suppressed] == ["anon-1"]
    assert suppressed[0].cue_id == "cue-3"


def test_one_empty_frame_is_a_blink_and_does_not_release_the_throttle():
    """A person who looks away for a frame has not withdrawn their request.
    Releasing on the gate's first EMPTY notice is how they get pestered
    again, so emptiness has to last before a track counts as gone."""
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(tool="respect_boundary", args={}, tokens_in=8, tokens_out=1),
            )
        ),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "please leave", facts={"track_reference": "anon-1"}),
                ScheduledInput(
                    at_s=0.1,
                    input=VisualAttentionNotice(
                        frame_index=4, outcome=VisualAttentionOutcome.EMPTY
                    ),
                ),
                ScheduledInput(
                    at_s=0.2,
                    input=VisualAttentionNotice(
                        frame_index=5,
                        outcome=VisualAttentionOutcome.TRACKING,
                        track_reference=AnonymousTrackReference("anon-1"),
                    ),
                ),
                text_at(
                    0.3,
                    "a later care cue",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
            ],
        ),
        session=session,
        clock=clock,
    ).run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1"]
    assert not any(
        record.type == "cue_suppression_cleared"
        and record.reason is CueSuppressionClearReason.TRACK_LOST
        for record in result.records
    )
    assert [record.cue_id for record in result.records if record.type == "cue_suppressed"] == ["cue-2"]


def test_track_disappearance_clears_suppression_before_a_new_cue():
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(
                    tool="respect_boundary", args={}, tokens_in=8, tokens_out=1
                ),
                Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
            )
        ),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(
                    0.0,
                    "please leave",
                    facts={"track_reference": "anon-1"},
                ),
                *[
                    ScheduledInput(
                        at_s=0.1 + index * 0.6,
                        input=VisualAttentionNotice(
                            frame_index=4 + index,
                            outcome=VisualAttentionOutcome.EMPTY,
                        ),
                    )
                    for index in range(3)
                ],
                text_at(
                    2.0,
                    "a later care cue",
                    cue_kind=CueKind.CARE_CUE,
                    facts={"track_reference": "anon-1"},
                ),
            ],
        ),
        session=session,
        clock=clock,
    ).run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-2"]
    cleared = next(
        record for record in result.records
        if record.type == "cue_suppression_cleared"
    )
    assert cleared.reason.value == "track_lost"


def test_runtime_shutdown_clears_anonymous_suppression_state():
    clock = FakeClock()

    class StopsAfterFirstEpisode:
        runtime = None
        delivered = False

        def start(self):
            pass

        def read(self):
            if not self.delivered:
                self.delivered = True
                return InputArrival(
                    age_s=0.0,
                    input=TimedText(
                        text="leave me alone",
                        facts={"track_reference": "anon-1"},
                    ),
                )
            self.runtime.stop()
            return None

        def read_available(self):
            return ()

        def stop(self):
            pass

    source = StopsAfterFirstEpisode()
    runtime = SocialAgentRuntime(
        source=source,
        session=simulated_session(
            None,
            model=ScenarioModel(
                (
                    Decision(
                        tool="respect_boundary",
                        args={},
                        tokens_in=8,
                        tokens_out=1,
                    ),
                )
            ),
            clock=clock,
        ),
        clock=clock,
    )
    source.runtime = runtime

    result = runtime.run()

    assert result.ending is RuntimeEnding.SHUTDOWN
    cleared = next(
        record for record in result.records
        if record.type == "cue_suppression_cleared"
    )
    assert cleared.reason.value == "shutdown"


def test_skill_instructions_and_personal_context_end_with_their_episode():
    """The hosted-model boundary may see active guidance and utterances only
    while the Episode that activated and heard them is still running."""

    class CapturesEveryTurn(ScenarioModel):
        def __init__(self):
            super().__init__((
                Decision(
                    "activate_skill",
                    {"name": "supportive-interaction"},
                    8,
                    2,
                ),
                Decision("done", {}, 8, 1),
                Decision("done", {}, 8, 1),
            ))
            self.contexts = []

        def decide(self, working_context, tools):
            self.contexts.append(
                json.dumps(working_context, ensure_ascii=False)
            )
            return super().decide(working_context, tools)

    clock = FakeClock()
    model = CapturesEveryTurn()
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(
                    0.0,
                    "Hi Misty，我是 Ana",
                    facts={"track_reference": "person-a"},
                ),
                text_at(
                    0.0,
                    "Hi Misty，我是 Bo",
                    facts={"track_reference": "person-b"},
                ),
            ],
        ),
        session=simulated_session(None, model=model, clock=clock),
        clock=clock,
    ).run()

    assert len(result.episodes) == 2
    assert "Stay where you are" in model.contexts[1]
    assert "Hi Misty，我是 Ana" in model.contexts[1]
    assert "Stay where you are" not in model.contexts[2]
    assert "Hi Misty，我是 Ana" not in model.contexts[2]
    assert "Hi Misty，我是 Bo" in model.contexts[2]


def test_an_active_episode_collects_a_due_cue_at_a_safe_turn_boundary():
    clock = FakeClock()
    decisions = (
        Decision(
            tool="look_around", args={}, tokens_in=8, tokens_out=1
        ),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "first request"),
                text_at(0.5, "second request"),
            ],
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    lifecycle = [record.type for record in result.records]
    assert lifecycle == [
        "attention_started",
        "cue_detected",
        "episode_opened",
        "cue_detected",
        "cue_queued",
        "episode_completed",
        "cue_dequeued",
        "episode_opened",
        "episode_completed",
        "attention_stopped",
    ]
    queued = next(
        record for record in result.records if isinstance(record, CueQueued)
    )
    dequeued = next(
        record for record in result.records if isinstance(record, CueDequeued)
    )
    assert queued.active_cue_id == "cue-1"
    assert queued.cue_id == dequeued.cue_id == "cue-2"
    assert queued.priority == dequeued.priority == 3
    assert result.records[3].t == 0.5
    assert len(result.episodes) == 2


def test_active_attention_does_not_pull_a_future_input_forward():
    """Draining the whole scenario at a boundary would fail this control."""
    clock = FakeClock()
    decisions = (
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [text_at(0.0, "active"), text_at(0.7, "not due yet")],
        ),
        session=session,
        clock=clock,
    ).run()

    assert not any(
        isinstance(record, (CueQueued, CueDequeued))
        for record in result.records
    )
    assert [
        record.t
        for record in result.records
        if record.type == "cue_detected"
    ] == [0.0, 0.7]
    boundaries = [
        record.type
        for record in result.records
        if record.type
        in {"cue_detected", "episode_opened", "episode_completed"}
    ]
    assert boundaries == [
        "cue_detected",
        "episode_opened",
        "episode_completed",
        "cue_detected",
        "episode_opened",
        "episode_completed",
    ]


def test_fresh_explicit_requests_are_dequeued_before_non_explicit_cues():
    """FIFO would open cue-2 first, so this detects a missing priority rule."""
    clock = FakeClock()
    decisions = (
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "active", cue_kind=CueKind.EXPLICIT_REQUEST),
                text_at(0.1, "wave", cue_kind=CueKind.SOCIAL_INVITATION),
                text_at(0.2, "care", cue_kind=CueKind.CARE_CUE),
                text_at(0.3, "Misty?", cue_kind=CueKind.EXPLICIT_REQUEST),
            ],
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    assert [episode.cue_id for episode in result.episodes] == [
        "cue-1",
        "cue-4",
        "cue-3",
        "cue-2",
    ]
    assert [episode.cue_kind for episode in result.episodes] == [
        CueKind.EXPLICIT_REQUEST,
        CueKind.EXPLICIT_REQUEST,
        CueKind.CARE_CUE,
        CueKind.SOCIAL_INVITATION,
    ]
    assert [
        record.priority
        for record in result.records
        if isinstance(record, CueDequeued)
    ] == [3, 2, 1]


def test_the_bounded_queue_deduplicates_replaces_overflows_and_expires():
    """One timed acceptance run makes every queue disposition observable."""
    clock = FakeClock()
    decisions = (
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "active"),
                text_at(
                    0.1,
                    "possible concern",
                    cue_kind=CueKind.CARE_CUE,
                    deduplication_key="same-signal",
                ),
                text_at(
                    0.2,
                    "repeated concern",
                    cue_kind=CueKind.CARE_CUE,
                    deduplication_key="same-signal",
                ),
                text_at(
                    0.3,
                    "Misty, please respond",
                    cue_kind=CueKind.EXPLICIT_REQUEST,
                    deduplication_key="same-signal",
                ),
                text_at(
                    0.4,
                    "wave",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    deduplication_key="wave",
                ),
                text_at(
                    0.5,
                    "another concern",
                    cue_kind=CueKind.CARE_CUE,
                    deduplication_key="other-care",
                ),
                text_at(
                    0.55,
                    "already gone",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    fresh_for_s=0.01,
                ),
            ],
        ),
        session=session,
        clock=clock,
        config=Settings(cue_queue_capacity=2),
    )

    result = runtime.run()

    assert [episode.cue_id for episode in result.episodes] == [
        "cue-1",
        "cue-4",
        "cue-6",
    ]
    deduplicated = next(
        record
        for record in result.records
        if isinstance(record, CueDeduplicated)
    )
    assert (deduplicated.cue_id, deduplicated.retained_cue_id) == (
        "cue-3",
        "cue-2",
    )
    replaced = next(
        record for record in result.records if isinstance(record, CueReplaced)
    )
    assert (replaced.cue_id, replaced.replacement_cue_id) == (
        "cue-2",
        "cue-4",
    )
    dropped = [
        (record.cue_id, record.reason)
        for record in result.records
        if isinstance(record, CueDropped)
    ]
    assert dropped == [
        ("cue-5", CueDropReason.OVERFLOW),
        ("cue-7", CueDropReason.EXPIRED),
    ]
    assert max(
        record.queue_size
        for record in result.records
        if isinstance(record, (CueQueued, CueDeduplicated, CueReplaced, CueDropped))
    ) == 2


def test_input_freshness_can_only_shorten_the_configured_upper_bound():
    """A huge per-input value must not extend the Runtime's five-second cap."""
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(
                    tool="look_around", args={}, tokens_in=8, tokens_out=1
                ),
                Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
            )
        ),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "active"),
                text_at(0.1, "old", fresh_for_s=999.0),
            ],
        ),
        session=session,
        clock=clock,
        config=Settings(cue_freshness_s=0.2),
    ).run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1"]
    assert any(
        isinstance(record, CueDropped)
        and record.cue_id == "cue-2"
        and record.reason is CueDropReason.EXPIRED
        for record in result.records
    )


def test_overflow_evicts_the_newest_low_priority_cue_when_times_tie():
    """Arrival sequence, not a stable-min accident, decides a timestamp tie."""
    clock = FakeClock()
    decisions = (
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "active"),
                text_at(
                    0.1,
                    "first wave",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    deduplication_key="first",
                ),
                text_at(
                    0.1,
                    "second wave",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    deduplication_key="second",
                ),
                text_at(
                    0.1,
                    "care",
                    cue_kind=CueKind.CARE_CUE,
                    deduplication_key="care",
                ),
            ],
        ),
        session=session,
        clock=clock,
        config=Settings(cue_queue_capacity=2),
    ).run()

    assert [episode.cue_id for episode in result.episodes] == [
        "cue-1",
        "cue-4",
        "cue-2",
    ]
    assert any(
        isinstance(record, CueDropped)
        and record.cue_id == "cue-3"
        and record.reason is CueDropReason.OVERFLOW
        for record in result.records
    )


def test_a_queued_cue_that_expires_behind_higher_priority_work_is_not_opened():
    """The low-priority cue is fresh when queued but stale at handoff."""
    clock = FakeClock()
    decisions = (
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="look_around", args={}, tokens_in=8, tokens_out=1),
        Decision(tool="done", args={}, tokens_in=8, tokens_out=1),
    )
    session = simulated_session(
        None, model=ScenarioModel(decisions), clock=clock
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "active"),
                text_at(
                    0.1,
                    "brief wave",
                    cue_kind=CueKind.SOCIAL_INVITATION,
                    fresh_for_s=0.7,
                ),
                text_at(0.2, "Misty, please answer"),
            ],
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-3"]
    expired = [
        record
        for record in result.records
        if isinstance(record, CueDropped)
        and record.reason is CueDropReason.EXPIRED
    ]
    assert [record.cue_id for record in expired] == ["cue-2"]
    assert expired[0].t >= 1.2


def test_shutdown_discards_the_remaining_queue_without_starting_more_work():
    class StopsAfterOneSafeBoundary:
        calls = 0
        runtime = None

        def decide(self, working_context, tools):
            self.calls += 1
            if self.calls == 1:
                return Decision(
                    tool="look_around", args={}, tokens_in=8, tokens_out=1
                )
            self.runtime.stop()
            return Decision(tool="done", args={}, tokens_in=8, tokens_out=1)

    clock = FakeClock()
    model = StopsAfterOneSafeBoundary()
    session = simulated_session(None, model=model, clock=clock)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [text_at(0.0, "active"), text_at(0.1, "queued")],
        ),
        session=session,
        clock=clock,
    )
    model.runtime = runtime

    result = runtime.run()

    assert result.ending is RuntimeEnding.SHUTDOWN
    assert len(result.episodes) == 1
    assert result.episodes[0].outcome.outcome == "aborted"
    discarded = [
        record
        for record in result.records
        if isinstance(record, CueDropped)
    ]
    assert [(record.cue_id, record.reason) for record in discarded] == [
        ("cue-2", CueDropReason.SHUTDOWN)
    ]


def test_active_attention_failure_closes_the_episode_and_runtime():
    class FailsAtBoundary(ScenarioInputAdapter):
        calls = 0

        def read_available(self):
            self.calls += 1
            if self.calls == 1:
                return super().read_available()
            raise RuntimeError("active attention failed")

    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(
            (
                Decision(
                    tool="look_around", args={}, tokens_in=8, tokens_out=1
                ),
                Decision(
                    tool="look_around", args={}, tokens_in=8, tokens_out=1
                ),
            )
        ),
        clock=clock,
    )
    runtime = SocialAgentRuntime(
        source=FailsAtBoundary(
            clock, [text_at(0.0, "active"), text_at(0.1, "queued")]
        ),
        session=session,
        clock=clock,
    )

    result = runtime.run()

    assert result.ending is RuntimeEnding.RUNTIME_ERROR
    assert runtime.state is RuntimeState.STOPPED
    assert len(result.episodes) == 1
    assert result.episodes[0].outcome.outcome == "aborted"
    assert [record.type for record in result.records[-4:]] == [
        "episode_completed",
        "cue_dropped",
        "runtime_failed",
        "attention_stopped",
    ]
    assert result.records[-3].reason is CueDropReason.RUNTIME_FAILURE


def test_episode_error_gives_each_remaining_cue_a_typed_disposition():
    class FailsAfterQueueing:
        calls = 0

        def decide(self, working_context, tools):
            self.calls += 1
            if self.calls == 1:
                return Decision(
                    tool="look_around", args={}, tokens_in=8, tokens_out=1
                )
            raise RuntimeError("model failed")

    clock = FakeClock()
    session = simulated_session(None, model=FailsAfterQueueing(), clock=clock)
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock, [text_at(0.0, "active"), text_at(0.1, "queued")]
        ),
        session=session,
        clock=clock,
    ).run()

    assert result.ending is RuntimeEnding.EPISODE_ERROR
    assert any(
        isinstance(record, CueDropped)
        and record.cue_id == "cue-2"
        and record.reason is CueDropReason.EPISODE_ERROR
        for record in result.records
    )


def test_a_multi_episode_run_asks_for_one_journal_path_per_episode(tmp_path):
    """One Journal file cannot be shared by two bounded Episodes."""

    class StopsEachEpisode:
        def decide(self, working_context, tools):
            return Decision(tool="done", args={}, tokens_in=8, tokens_out=1)

    clock = FakeClock()
    session = simulated_session(None, model=StopsEachEpisode(), clock=clock)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                text_at(0.0, "first request"),
                text_at(0.1, "second request"),
            ],
        ),
        session=session,
        clock=clock,
    )
    asked_for = []

    def journal_path_for_episode(number):
        path = tmp_path / f"episode-{number}.jsonl"
        asked_for.append(path)
        return path

    result = runtime.run(journal_path_for_episode=journal_path_for_episode)

    assert result.ending == "input_exhausted"
    assert asked_for == [
        tmp_path / "episode-1.jsonl",
        tmp_path / "episode-2.jsonl",
    ]
    assert all(path.read_text().endswith("\n") for path in asked_for)

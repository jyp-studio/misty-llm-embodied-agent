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
    DecisionNoted,
    EpisodeFinished,
    ExecutionFailed,
    StopRequested,
)
from misty_agent.agent.memory import Memory
from misty_agent.agent.react import Decision
from misty_agent.app import SystemClock, simulated_session
from misty_agent.config import Settings
from misty_agent.demo import answer
from misty_agent.fakes import FakeClock
from misty_agent.runtime import (
    EvidenceKind,
    MAX_SELECTED_IMAGE_BYTES,
    RuntimeEnding,
    RuntimeState,
    ScenarioInputAdapter,
    ScheduledInput,
    SelectedImageEvidence,
    SocialAgentRuntime,
    TimedText,
)
from misty_agent.scenarios import EXPLICIT_TEXT_REQUEST, ScenarioModel


def text_at(at_s, text):
    return ScheduledInput(at_s=at_s, input=TimedText(text=text))


def test_a_timed_explicit_request_runs_from_attention_to_a_simulated_effect():
    """Ticket 01's tracer bullet crosses the new highest public seam."""
    clock = FakeClock()
    source = ScenarioInputAdapter(
        clock,
        EXPLICIT_TEXT_REQUEST.inputs,
    )
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
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
    assert "tts/speak" in session.robot.endpoints


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


def test_an_input_source_does_not_have_to_invent_scenario_timing():
    """Live providers emit evidence now; scheduling belongs to the scenario."""

    class ImmediateTextInput:
        def __init__(self) -> None:
            self.remaining = [TimedText(text="Misty, hello")]

        def start(self) -> None:
            pass

        def read(self):
            return self.remaining.pop(0) if self.remaining else None

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
    assert "tts/speak" not in session.robot.endpoints


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


def test_shutdown_during_episode_close_falls_back_to_a_robot_halt():
    """A closed Journal race must not turn shutdown into an exception."""

    class StopsWhileConsolidating:
        runtime = None

        def extract(self, known, exchanges):
            self.runtime.stop()
            return {}

    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )
    extractor = StopsWhileConsolidating()
    session.memory = Memory(summariser=None, extractor=extractor, window=6)
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, EXPLICIT_TEXT_REQUEST.inputs),
        session=session,
        clock=clock,
    )
    extractor.runtime = runtime

    result = runtime.run()

    assert result.ending == "shutdown"
    assert result.episodes[0].outcome.outcome == "done"
    assert session.robot.endpoints.count("halt") == 1


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
    assert session.robot.endpoints.count("tts/speak") == 2


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

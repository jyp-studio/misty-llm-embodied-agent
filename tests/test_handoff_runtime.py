"""Ticket 08 acceptance through ``SocialAgentRuntime``: A keeps the robot,
B waits in the queue, and the handoff happens at a Turn boundary."""

from __future__ import annotations

import json

from misty_agent.agent.journal import HandoffRequested, TargetBound, ToolCalled
from misty_agent.agent.react import Decision
from misty_agent.app import simulated_session
from misty_agent.demo import answer
from misty_agent.fakes import FakeClock
from misty_agent.runtime import (
    CueDropped,
    CueDropReason,
    CueQueued,
    RuntimeEnding,
    ScenarioInputAdapter,
    ScheduledInput,
    SocialAgentRuntime,
    TimedText,
)
from misty_agent.scenarios import SPEAKER_HANDOFF, ScenarioModel, ScenarioSpeech, TimedSpeech


class CaptureModel(ScenarioModel):
    def __init__(self, decisions):
        super().__init__(decisions)
        self.contexts = []

    def decide(self, context, tools):
        self.contexts.append(json.dumps(context, ensure_ascii=False))
        return super().decide(context, tools)


def person(at_s, text, who, **fields):
    return ScheduledInput(at_s, TimedText(text=text, facts={"track_reference": who}, **fields))


A_GREETS = person(0.0, "Hi Misty，我是 A", "person-a")
B_CALLS = person(0.5, "Hey Misty，換我", "person-b")

A_TURNS = (
    Decision("speak", {"text": "你好 A，今天想聊什麼？"}, 1, 1),
    Decision("listen", {}, 1, 1),
    Decision("speak", {"text": "B 在等我，我們先聊到這裡，再見。"}, 1, 1),
    Decision("done", {}, 1, 1),
)
B_TURNS = (Decision("speak", {"text": "你好 B，換你了。"}, 1, 1), Decision("done", {}, 1, 1))


def run(model, clock, inputs, speech=(TimedSpeech(0.6, "今天天氣不錯"),)):
    session = simulated_session(None, model=model, clock=clock, ears=ScenarioSpeech(clock, speech))
    return SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, inputs), session=session, clock=clock,
    ).run()


def test_b_waits_in_the_queue_and_a_is_told_at_a_turn_boundary_before_b_starts():
    clock = FakeClock()
    model = CaptureModel(A_TURNS + B_TURNS)
    result = run(model, clock, (A_GREETS, B_CALLS))

    assert result.ending is RuntimeEnding.INPUT_EXHAUSTED
    assert [episode.cue_id for episode in result.episodes] == ["cue-1", "cue-2"]
    a, b = result.episodes
    assert a.outcome.outcome == "done" and b.outcome.outcome == "done"

    queued = next(record for record in result.records if isinstance(record, CueQueued))
    assert (queued.cue_id, queued.active_cue_id) == ("cue-2", "cue-1")
    order = [(record.type, getattr(record, "cue_id", None)) for record in result.records]
    assert order.index(("episode_completed", "cue-1")) < order.index(("episode_opened", "cue-2"))

    handoff = next(record for record in a.journal.records if isinstance(record, HandoffRequested))
    assert (handoff.cue_id, handoff.cue_kind) == ("cue-2", "explicit_request")
    assert handoff.turn == 2
    assert "waiting (cue-2)" not in model.contexts[1]
    assert "waiting (cue-2)" in model.contexts[2]
    assert "Hi Misty，我是 A" in model.contexts[2]
    assert "今天天氣不錯" in model.contexts[2]
    assert [r.tool for r in a.journal.records if isinstance(r, ToolCalled)][2:] == ["speak", "done"]
    assert not any(isinstance(record, HandoffRequested) for record in b.journal.records)

    bound_a = next(record for record in a.journal.records if isinstance(record, TargetBound))
    bound_b = next(record for record in b.journal.records if isinstance(record, TargetBound))
    assert (bound_a.track_reference, bound_b.track_reference) == ("person-a", "person-b")
    assert "person-a" not in model.contexts[4]
    assert "Hi Misty，我是 A" not in model.contexts[4]
    assert "今天天氣不錯" not in model.contexts[4]


def test_a_stale_b_request_expires_behind_a_and_opens_no_episode():
    clock = FakeClock()
    stale_b = person(0.5, "Hey Misty，換我", "person-b", fresh_for_s=0.3)
    model = CaptureModel((
        Decision("speak", {"text": "你好 A"}, 1, 1),
        Decision("listen", {}, 1, 1),
        Decision("listen", {}, 1, 1),
        Decision("done", {}, 1, 1),
    ))
    result = run(model, clock, (A_GREETS, stale_b))

    assert [episode.cue_id for episode in result.episodes] == ["cue-1"]
    dropped = next(record for record in result.records if isinstance(record, CueDropped))
    assert (dropped.cue_id, dropped.reason) == ("cue-2", CueDropReason.EXPIRED)
    assert result.ending is RuntimeEnding.INPUT_EXHAUSTED


def test_the_bumper_aborts_a_at_once_and_b_still_gets_its_own_episode():
    clock = FakeClock()
    session = None

    class BumpingModel(CaptureModel):
        def decide(self, context, tools):
            if len(self.contexts) == 2:
                session.bumper_pressed()
            return super().decide(context, tools)

    model = BumpingModel(A_TURNS[:2] + (Decision("speak", {"text": "never said"}, 1, 1),) + B_TURNS)
    session = simulated_session(
        None, model=model, clock=clock, ears=ScenarioSpeech(clock, (TimedSpeech(0.6, "今天天氣不錯"),)),
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, (A_GREETS, B_CALLS)), session=session, clock=clock,
    ).run()

    a, b = result.episodes
    assert a.outcome.outcome == "aborted"
    assert "never said" not in json.dumps([r.args for r in a.journal.records if isinstance(r, ToolCalled)])
    assert b.outcome.outcome == "done"
    assert next(r for r in b.journal.records if isinstance(r, TargetBound)).track_reference == "person-b"


def test_the_demo_runs_the_handoff_card_with_two_anonymous_actors():
    listed = json.loads(answer("GET", "/scenarios").body)
    card = next(case for case in listed if case["name"] == "speaker-handoff")
    assert card["availability"] == "ready"
    assert card["actors"] == ["A", "B"]

    response = answer("POST", "/scenarios/speaker-handoff/run", b'{"fixture":"a-then-b"}')
    assert response.status == 200
    run_payload = json.loads(response.body)
    assert [episode["actor"] for episode in run_payload["episodes"]] == ["A", "B"]
    kinds = [beat["kind"] for beat in run_payload["execution"]["flow"]]
    for expected in (
        "target_bound",
        "cue_queued",
        "handoff_requested",
        "cue_dequeued",
        "context_retained",
        "context_reset",
    ):
        assert expected in kinds
    assert kinds.index("cue_queued") < kinds.index("handoff_requested") < kinds.index("cue_dequeued")
    assert kinds.count("target_bound") == 2
    assert kinds[-1] == "ending"
    assert run_payload["execution"]["flow"][-1]["headline"] == "The example ran to completion"
    assert "sound-source direction" in run_payload["execution"]["provenance"]["detail"]
    retained = next(
        beat for beat in run_payload["execution"]["flow"]
        if beat["kind"] == "context_retained"
    )
    reset = next(
        beat for beat in run_payload["execution"]["flow"]
        if beat["kind"] == "context_reset"
    )
    assert "same Episode" in retained["detail"]
    assert "nothing of A's" in reset["detail"]

    stale = json.loads(answer("POST", "/scenarios/speaker-handoff/run", b'{"fixture":"b-expires"}').body)
    assert [episode["actor"] for episode in stale["episodes"]] == ["A"]
    assert "cue_dropped" in [beat["kind"] for beat in stale["execution"]["flow"]]
    assert SPEAKER_HANDOFF.ticket == "12"


def test_an_untracked_repeat_request_is_not_announced_as_another_person():
    """Negative control for the notice: "someone else" is a different
    anonymous track, never an assumption about an untracked voice."""
    clock = FakeClock()
    repeat = ScheduledInput(0.5, TimedText(text="Hey Misty，再說一次"))
    model = CaptureModel(A_TURNS[:2] + (Decision("done", {}, 1, 1),) + B_TURNS)
    result = run(model, clock, (A_GREETS, repeat))

    a, again = result.episodes
    assert not any(isinstance(record, HandoffRequested) for record in a.journal.records)
    assert "waiting (cue-2)" not in model.contexts[2]
    assert again.cue_id == "cue-2" and again.outcome.outcome == "done"
    assert next(r for r in again.journal.records if isinstance(r, TargetBound)).track_reference is None

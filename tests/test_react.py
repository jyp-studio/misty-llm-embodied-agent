"""One Episode, end to end, against the Journals that were written first.

`tests/goldens/` holds five Journals this loop has to be able to produce. The
original four were committed before the loop existed; the fifth was added
when closure made runtime failure a named outcome. In either case, the useful
assertion is equality against the declared artefact rather than a loose list
of properties.

## What "matches the golden" means, exactly

Structure and every non-timing field: **equal**. `t`: determined by the rule
in `tests/goldens/README.md` — time advances only when something really waits,
which under an injected clock means a model call or a Tool that sleeps.
`PLAN.md` §15.21 records why the goldens' hand-written bookkeeping gaps gave
way rather than the loop.

## The doubles

`ScriptedModel` is the only new seam this milestone adds, and it is the point
of the narrow `Model` protocol: no HTTP, no SDK, no mock of anybody's client.
It sleeps its own scripted latency on the injected clock, which is what makes
`model_called.latency_ms` reproducible rather than incidental.

For `approach` the worlds come from `tests/test_approach.py` — the same ones
M5 was verified against, for the reason ticket 06 gives: a second definition
of what the robot does is a second thing to keep true.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import threading

import pytest

from journal_diff import first_difference
from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
    Journal,
    ModelCalled,
    Observation,
    Snapshot,
    StopRequested,
    ToolCalled,
    ToolRejected,
    TurnStarted,
    ExecutionFailed,
    from_jsonl,
    to_jsonl,
)
from misty_agent.agent.memory import Exchange, Memory
from misty_agent.agent.persona import PERSONA
from misty_agent.agent.react import Decision, EpisodeOutcome, run_episode
from misty_agent.agent.stop import EmergencyStop
from misty_agent.agent.tools import NoArguments, ToolContext, ToolRegistry, build_registry
from misty_agent.config import Settings
from misty_agent.control.safety import ALWAYS_CLEAR
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter, SimulatedMistyAdapter
from misty_agent.perception.distance import DistanceReading

from test_approach import WorldThatLosesTheUserAfterAStep
from test_memory import CountingExtractor, CountingSummariser

def as_text(working_context):
    """Everything the model was handed, as one string.

    Lives here rather than in `react.py`: its only caller is
    `test_no_text_the_model_receives_mentions_a_drive_parameter`, and a
    production module is not where test scaffolding belongs.
    """
    return json.dumps(list(working_context), sort_keys=True, default=str)


GOLDENS = pathlib.Path(__file__).parent / "goldens"
WALL_CLOCK = "2026-08-25T09:14:03+08:00"


class ScriptedModel:
    """Answers from a list, and takes exactly as long as the list says.

    The latency is slept on the injected clock rather than asserted
    afterwards, so `model_called.latency_ms` is something the loop measured
    and not something the test told it.
    """

    def __init__(self, clock, *script) -> None:
        self._clock = clock
        self._script = list(script)
        self.asked = []

    def decide(self, working_context, tools):
        if not self._script:
            raise AssertionError("the loop asked for one more decision than scripted")
        tool, args, latency_ms, tokens_in, tokens_out = self._script.pop(0)
        self.asked.append((tuple(working_context), tuple(tools)))
        self._clock.sleep(latency_ms / 1000.0)
        return Decision(
            tool=tool, args=args, tokens_in=tokens_in, tokens_out=tokens_out
        )


class ScriptedPerception:
    """One Snapshot per Observation, in order; the last one repeats."""

    def __init__(self, *snapshots) -> None:
        self._snapshots = list(snapshots)
        self._taken = 0

    def snapshot(self):
        index = min(self._taken, len(self._snapshots) - 1)
        self._taken += 1
        return self._snapshots[index]


class ScriptedReadings:
    """A reading source `look_around` and `approach` can both poll."""

    def __init__(self, *answers) -> None:
        self._answers = list(answers)

    def latest_reading(self):
        return self._answers.pop(0) if self._answers else None


def a_snapshot(distance_cm, face_present=True, new_speech=None):
    return Snapshot(
        distance_cm=distance_cm, face_present=face_present, new_speech=new_speech
    )


def a_reading(distance_cm=154):
    return DistanceReading(
        distance_cm=distance_cm, frame_arrived_at=0.0, detected_at=0.0,
        bearing_deg=0.0,
    )


def evidence(source="speech", transcript=""):
    return TriggerEvidence(
        source=EvidenceKind(source),
        observed_at_s=0.0,
        transcript=transcript,
    )


def an_episode(
    *,
    episode_id,
    trigger,
    script,
    snapshots,
    readings=None,
    config=None,
    world=None,
):
    """Run one Episode and hand back everything a test might want to look at."""
    clock = FakeClock()
    settings = config or Settings()
    the_world = world(clock, settings) if world else None
    journal = Journal(
        episode_id=episode_id, clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    ctx = ToolContext(
        robot=the_world or RealMistyAdapter(RecordingCommands()),
        readings=the_world or readings,
        config=settings,
        clock=clock, hazards=ALWAYS_CLEAR
    )
    model = ScriptedModel(clock, *script)
    outcome = run_episode(
        evidence(trigger),
        model=model,
        registry=build_registry(),
        ctx=ctx,
        journal=journal,
        perception=ScriptedPerception(*snapshots),
    )
    return outcome, journal, model


# ---------------------------------------------------------------------------
# The three goldens this ticket owns
# ---------------------------------------------------------------------------

def ends_on_the_first_turn():
    return an_episode(
        episode_id="ep-first-turn",
        trigger="speech",
        script=[("done", {}, 943, 812, 11)],
        snapshots=[a_snapshot(100)],
    )


def ends_after_several_turns():
    return an_episode(
        episode_id="ep-several-turns",
        trigger="speech",
        script=[
            ("move_head", {"pitch": 140}, 1198, 806, 24),
            ("speak", {"text": "Coming over."}, 897, 871, 19),
            ("approach", {}, 949, 934, 12),
            ("done", {}, 873, 1013, 8),
        ],
        snapshots=[
            a_snapshot(142),
            a_snapshot(None, face_present=False),
            a_snapshot(100),
        ],
        world=lambda clock, settings: WorldThatLosesTheUserAfterAStep(
            clock, start_cm=200.0, config=settings
        ),
    )


def hits_the_turn_limit():
    cap = Settings().max_turns_per_episode
    return an_episode(
        episode_id="ep-turn-limit",
        trigger="visual",
        script=[
            ("look_around", {}, 871 + 11 * i, 840 + 40 * i, 14) for i in range(cap)
        ],
        snapshots=[a_snapshot(154 - i) for i in range(cap)],
        readings=ScriptedReadings(*[a_reading() for _ in range(cap * 4)]),
    )


def fails_during_model_call():
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-model-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )

    class ModelFails:
        def __init__(self):
            self.asked = []

        def decide(self, working_context, tools):
            self.asked.append((tuple(working_context), tuple(tools)))
            raise RuntimeError("model connection failed")

    model = ModelFails()
    outcome = run_episode(
        evidence(),
        model=model,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )
    return outcome, journal, model


GOLDEN_EPISODES = [
    ("episode_ends_on_the_first_turn.jsonl", ends_on_the_first_turn),
    ("episode_ends_after_several_turns.jsonl", ends_after_several_turns),
    ("episode_hits_the_turn_limit.jsonl", hits_the_turn_limit),
    ("episode_fails_during_model_call.jsonl", fails_during_model_call),
]


@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_the_loop_reproduces_the_golden_journal(name, episode):
    """The assertion this whole milestone is arranged around.

    Not "the Journal looks plausible" — equal, record for record and field for
    field, to the declared file. Git history separately shows the original
    four preceded this loop and the error file accompanied closure hardening.
    """
    expected = list(from_jsonl((GOLDENS / name).read_text()))
    _, journal, _ = episode()

    difference = first_difference(expected, list(journal.records))

    assert difference is None, str(difference)


@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_the_loop_reproduces_the_goldens_formatting_too(name, episode):
    """The types are the contract and JSONL is the serialisation (§15.3), but
    a golden nobody can regenerate byte for byte is a golden that will drift.
    """
    _, journal, _ = episode()

    assert to_jsonl(list(journal.records)) == (GOLDENS / name).read_text()


@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_every_timestamp_follows_from_a_real_wait(name, episode):
    """The rule `tests/goldens/README.md` states, checked rather than trusted.

    Time advances for a model call and for a Tool that sleeps, and for nothing
    else. This is what makes each `t` verifiable by hand from the file's own
    `latency_ms` values — and it is the reason the goldens' hand-written 2ms
    bookkeeping gaps gave way (`PLAN.md` §15.21).
    """
    _, journal, _ = episode()
    records = list(journal.records)

    for earlier, later in zip(records, records[1:]):
        moved = round(later.t - earlier.t, 3)
        assert moved >= 0, f"{earlier.type} -> {later.type} went backwards"
        if moved > 0:
            assert isinstance(later, (ModelCalled, Observation)), (
                f"time passed between {earlier.type} and {later.type}, but "
                f"only a model call or a Tool that sleeps may take any"
            )


# ---------------------------------------------------------------------------
# Returning to idle is a property, not a hope
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_every_episode_ends_exactly_once(name, episode):
    _, journal, _ = episode()
    records = list(journal.records)

    assert sum(isinstance(r, EpisodeFinished) for r in records) == 1
    assert isinstance(records[-1], EpisodeFinished)
    assert isinstance(records[0], EpisodeStarted)


def test_a_model_that_never_stops_still_ends_the_episode():
    """`PLAN.md` §4 calls this the strongest property the system has."""
    outcome, journal, _ = hits_the_turn_limit()

    assert outcome.outcome == "turn_limit"
    assert outcome.turns == Settings().max_turns_per_episode


def test_a_model_failure_ends_the_episode_records_why_and_halts():
    """A broken network/model call must not strand a half-open Episode."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-model-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    robot = RealMistyAdapter(RecordingCommands())

    class ModelFails:
        def decide(self, working_context, tools):
            raise RuntimeError("model connection failed")

    outcome = run_episode(
        evidence(),
        model=ModelFails(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot,
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    failures = [record for record in journal.records if isinstance(record, ExecutionFailed)]
    endings = [record for record in journal.records if isinstance(record, EpisodeFinished)]
    assert outcome == EpisodeOutcome(outcome="error", turns=1, steps=0)
    assert [(record.phase, record.error_type) for record in failures] == [
        ("model", "RuntimeError")
    ]
    assert failures[0].message == "model connection failed"
    assert len(endings) == 1
    assert endings[0].outcome == "error"
    assert journal.records[-1] is endings[0]
    assert "halt" in robot.commands.endpoints


def test_a_memory_prompt_failure_ends_the_episode_before_the_first_turn():
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-memory-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    robot = RealMistyAdapter(RecordingCommands())

    class MemoryFails:
        def as_prompt_block(self):
            raise RuntimeError("memory could not be read")

        def remember(self, exchange):
            raise AssertionError("a failed setup must not append memory")

        def close_episode(self):
            raise AssertionError("a failed setup must not derive memory")

    outcome = run_episode(
        evidence(),
        model=ScriptedModel(clock, ("done", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot,
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
        memory=MemoryFails(),
    )

    failed = next(record for record in journal.records if isinstance(record, ExecutionFailed))
    assert outcome == EpisodeOutcome(outcome="error", turns=0, steps=0)
    assert (failed.phase, failed.error_type) == ("memory", "RuntimeError")
    assert isinstance(journal.records[-1], EpisodeFinished)
    assert "halt" in robot.commands.endpoints


def test_a_tool_failure_ends_the_episode_records_why_and_halts():
    """A direct Tool is an untrusted robot boundary just like approach."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-tool-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )

    class MotorFails(RecordingCommands):
        def move_head(self, *args, **kwargs):
            raise RuntimeError("head motor failed")

    robot = RealMistyAdapter(MotorFails())
    outcome = run_episode(
        evidence(),
        model=ScriptedModel(clock, ("move_head", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot,
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    failures = [record for record in journal.records if isinstance(record, ExecutionFailed)]
    endings = [record for record in journal.records if isinstance(record, EpisodeFinished)]
    assert outcome == EpisodeOutcome(outcome="error", turns=1, steps=0)
    assert [(record.phase, record.error_type, record.message) for record in failures] == [
        ("tool", "RuntimeError", "head motor failed")
    ]
    assert len(endings) == 1
    assert journal.records[-1] is endings[0]
    assert "halt" in robot.commands.endpoints


def test_an_invalid_tool_result_cannot_leave_the_episode_half_open():
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-tool-result-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    robot = RealMistyAdapter(RecordingCommands())
    registry = ToolRegistry()

    @registry.tool("bad_result", "Return something a Journal cannot store.")
    def bad_result(args: NoArguments, ctx: ToolContext):
        return {"not_json": object()}

    outcome = run_episode(
        evidence(),
        model=ScriptedModel(clock, ("bad_result", {}, 10, 1, 1)),
        registry=registry,
        ctx=ToolContext(
            robot=robot,
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    failed = next(record for record in journal.records if isinstance(record, ExecutionFailed))
    assert outcome.outcome == "error"
    assert failed.phase == "tool"
    assert isinstance(journal.records[-1], EpisodeFinished)
    assert "halt" in robot.commands.endpoints


def test_a_snapshot_failure_ends_the_episode_records_why_and_halts():
    """A successful Tool followed by broken perception still closes cleanly."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-perception-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    robot = RealMistyAdapter(RecordingCommands())

    class PerceptionFails:
        def snapshot(self):
            raise RuntimeError("camera pipeline failed")

    outcome = run_episode(
        evidence("visual"),
        model=ScriptedModel(clock, ("move_head", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot,
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=PerceptionFails(),
    )

    failures = [record for record in journal.records if isinstance(record, ExecutionFailed)]
    endings = [record for record in journal.records if isinstance(record, EpisodeFinished)]
    assert outcome == EpisodeOutcome(outcome="error", turns=1, steps=0)
    assert [(record.phase, record.error_type, record.message) for record in failures] == [
        ("perception", "RuntimeError", "camera pipeline failed")
    ]
    assert len(endings) == 1
    assert journal.records[-1] is endings[0]
    assert "head" in robot.commands.endpoints
    assert "halt" in robot.commands.endpoints


@pytest.mark.parametrize(
    "leak",
    [
        "driveDuration was rejected by the transport",
        "drive duration was rejected by the transport",
        "drive-duration was rejected by the transport",
    ],
)
def test_an_error_message_cannot_leak_a_control_parameter_into_the_journal(leak):
    """Failure diagnostics live on the same side of the layering boundary."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-secret-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )

    class LeakyFailure:
        def decide(self, working_context, tools):
            raise RuntimeError(leak)

    outcome = run_episode(
        evidence(),
        model=LeakyFailure(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    failed = next(record for record in journal.records if isinstance(record, ExecutionFailed))
    assert outcome.outcome == "error"
    assert failed.error_type == "RuntimeError"
    assert failed.message == "details withheld by the control-layer boundary"
    assert leak not in journal.to_jsonl()


def test_a_failed_error_halt_cannot_reopen_the_episode():
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-halt-error", clock=clock, wall_clock=lambda: WALL_CLOCK
    )

    class RefusesToHalt(RecordingCommands):
        def halt(self, motorMask=None):
            raise RuntimeError("halt transport failed")

    class ModelFails:
        def decide(self, working_context, tools):
            raise RuntimeError("model failed")

    outcome = run_episode(
        evidence(),
        model=ModelFails(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RefusesToHalt(),
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    assert outcome.outcome == "error"
    assert isinstance(journal.records[-1], EpisodeFinished)
    assert sum(isinstance(record, EpisodeFinished) for record in journal.records) == 1


def test_the_cap_is_read_from_config_not_written_into_the_loop():
    """A lower cap has to shorten the Episode, or the cap is decoration."""
    outcome, journal, _ = an_episode(
        episode_id="ep-short",
        trigger="visual",
        script=[("look_around", {}, 100, 10, 1) for _ in range(3)],
        snapshots=[a_snapshot(120)],
        readings=ScriptedReadings(*[a_reading() for _ in range(20)]),
        config=Settings(max_turns_per_episode=2),
    )

    assert outcome.turns == 2
    assert outcome.outcome == "turn_limit"


def test_the_last_turn_is_allowed_to_finish():
    """The cap stops a further Turn starting; it does not cut one short."""
    _, journal, _ = hits_the_turn_limit()
    records = list(journal.records)
    last = records[-1].turns

    assert any(
        isinstance(r, Observation) and r.turn == last for r in records
    ), "the final Turn was cut off before its Observation"


def test_the_model_asked_for_one_decision_per_turn_and_no_more():
    """A loop that called the model again after the cap would have run a Turn
    it never recorded."""
    _, journal, model = hits_the_turn_limit()

    assert len(model.asked) == Settings().max_turns_per_episode


# ---------------------------------------------------------------------------
# Stopping on the first Turn is the model's to choose
# ---------------------------------------------------------------------------

def test_the_model_can_end_the_episode_on_the_very_first_turn():
    outcome, journal, _ = ends_on_the_first_turn()

    assert outcome == EpisodeOutcome(outcome="done", turns=1, steps=0)


def test_ending_is_read_from_the_registry_not_from_the_tool_name():
    """`PLAN.md` §4 forbids a hard-coded fast path, and §15.9 is what happens
    when only one Tool can demonstrate the difference.

    So: a registry where the Tool named `done` does **not** end the Episode,
    and the loop must run past it to the cap.
    """
    registry = build_registry()
    clock = FakeClock()
    journal = Journal(episode_id="ep-x", clock=clock, wall_clock=lambda: WALL_CLOCK)
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()),
        readings=ScriptedReadings(),
        config=Settings(max_turns_per_episode=2),
        clock=clock, hazards=ALWAYS_CLEAR
    )
    registry._tools["done"] = dataclasses.replace(
        registry.get("done"), ends_episode=False
    )

    outcome = run_episode(
        evidence(),
        model=ScriptedModel(clock, ("done", {}, 10, 1, 1), ("done", {}, 10, 1, 1)),
        registry=registry,
        ctx=ctx,
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    assert outcome.outcome == "turn_limit"


# ---------------------------------------------------------------------------
# Which records exist, and which deliberately do not
# ---------------------------------------------------------------------------

def test_choosing_done_records_the_call_but_no_observation():
    """An Observation is what the model reads to decide the next Turn, and
    after `done` there is no next Turn."""
    _, journal, _ = ends_on_the_first_turn()
    records = list(journal.records)

    assert any(isinstance(r, ToolCalled) and r.tool == "done" for r in records)
    assert not any(isinstance(r, Observation) for r in records)


def test_a_refused_call_records_no_observation_either():
    """The reason *is* what the model reads next Turn. An Observation beside
    it would be the same fact twice (`PLAN.md` §15.4), and there is no
    Snapshot worth taking because nothing happened."""
    _, journal, _ = ends_after_several_turns()
    records = list(journal.records)

    refused = next(r for r in records if isinstance(r, ToolRejected))
    observed = {r.turn for r in records if isinstance(r, Observation)}

    assert refused.turn not in observed


def test_the_snapshot_is_attached_by_the_loop_to_every_observation():
    """Three facts, the same three for all nine Tools — which is why they are
    the loop's to attach and not nine copies inside the Tools."""
    _, journal, _ = ends_after_several_turns()

    for record in journal.records:
        if isinstance(record, Observation):
            assert isinstance(record.snapshot, Snapshot)


def test_the_step_count_is_the_sum_of_the_drives_that_happened():
    """`approach` is the only Tool that drives, and the loop must not know
    that (`PLAN.md` §15.20) — it adds up what `Dispatched` reports."""
    outcome, journal, _ = ends_after_several_turns()
    finished = journal.records[-1]

    approaches = [
        r for r in journal.records
        if isinstance(r, Observation) and "result" in r.result
    ]
    assert outcome.steps == finished.steps == sum(
        r.result["steps"] for r in approaches
    )


def test_a_turn_that_drives_nothing_reports_no_steps():
    """The negative control: a loop that counted Turns instead of drives would
    pass the test above and fail this one."""
    outcome, _, _ = ends_on_the_first_turn()

    assert outcome.steps == 0


# ---------------------------------------------------------------------------
# What reaches the model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_no_text_the_model_receives_mentions_a_drive_parameter(name, episode):
    """`PLAN.md` §4's layering claim, asserted on the whole of what is handed
    over rather than on nine parameter lists.

    `approach` drives with `linearVelocity` and `timeMs` on every Step — in
    golden 2 it really does drive — so this passing on a run that never moved
    would prove nothing. `test_the_step_count_is_the_sum_of_the_drives_that_happened`
    is what keeps that honest.
    """
    _, _, model = episode()

    for working_context, tools in model.asked:
        handed_over = (as_text(working_context) + json.dumps(list(tools))).lower()
        for forbidden in ("velocity", "timems", "time_ms", "cm_per_sec", "drive_ms"):
            assert forbidden not in handed_over, forbidden


def test_the_model_is_handed_the_observation_as_json_and_nothing_else():
    """§15.4 turned down a prose summary beside it: the same fact written
    twice is two things that can disagree, and the one the model attends to
    would be the one nobody checked."""
    _, _, model = ends_after_several_turns()
    last_context = model.asked[-1][0]

    observations = [
        entry for entry in last_context
        if entry["role"] == "tool" and "result" in entry.get("content", {})
    ]
    assert observations
    for entry in observations:
        assert set(entry["content"]) == {"result", "snapshot"}
        assert set(entry["content"]["snapshot"]) == {
            "distance_cm", "face_present", "new_speech"
        }


def test_the_model_is_told_why_its_call_was_refused():
    """Otherwise it has no way to do anything different next Turn."""
    _, _, model = ends_after_several_turns()
    second_turn_context = model.asked[1][0]

    refusals = [
        entry for entry in second_turn_context
        if entry["role"] == "tool" and "refused" in entry.get("content", {})
    ]
    assert refusals
    assert "pitch" in refusals[0]["content"]["refused"]


def test_the_model_is_handed_every_tool_it_has(name="", episode=None):
    _, _, model = ends_on_the_first_turn()
    _, tools = model.asked[0]

    assert {schema["function"]["name"] for schema in tools} == set(
        build_registry().names()
    )


# ---------------------------------------------------------------------------
# What is actually in the working context
# ---------------------------------------------------------------------------
#
# Everything above asserts on the Journal, which is the deliverable — and that
# left a hole: the Journal is right whether or not the *model* was told
# anything useful. Five mutations survived the first battery because of it,
# including `as_text` returning "" and the Snapshot arriving as all-None.

def test_the_trigger_is_what_the_model_is_told_about_this_episode():
    """Otherwise the first Turn is a decision made about nothing.

    Both halves: *what kind* of thing started this, and — when it was speech —
    *what was said*. Ticket 09 added the words; before it the model was told
    only that someone had spoken.

    Found by role rather than by position: M8 #03 put the persona in front of
    it, and a test that indexed `[0]` would have been "fixed" by renumbering
    instead of by asking what it meant.
    """
    _, _, model = ends_on_the_first_turn()
    first_context, _ = model.asked[0]

    from_the_world = [e for e in first_context if e["role"] == "user"]
    assert from_the_world == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": {
                        "trigger_evidence": {
                            "source": "speech",
                            "observed_at_s": 0.0,
                            "facts": {},
                            "transcript": "",
                            "uncertainty": [],
                        }
                    },
                }
            ],
        }
    ]


def test_the_model_is_told_what_it_is_before_anything_else():
    """Who you are, then what you know, then what just happened.

    Order, not just presence: a persona arriving after the trigger is a
    correction rather than a frame. `react.py` says why it is on by default.
    """
    _, _, model = ends_on_the_first_turn()
    first_context, _ = model.asked[0]

    assert first_context[0] == {"role": "system", "content": PERSONA}


def test_the_instructions_the_caller_gave_are_the_ones_the_model_reads():
    """The parameter has to carry, not just exist.

    Passing `instructions=""` proves only that an empty one is suppressed — a
    loop that ignored the parameter and appended the constant would pass that
    and every other test here. `PLAN.md` §15.23 deleted this parameter once
    for having no caller; a caller whose value is discarded is the same defect
    wearing a caller.
    """
    clock = FakeClock()
    journal = Journal(episode_id="ep-own", clock=clock, wall_clock=lambda: WALL_CLOCK)
    scripted = ScriptedModel(clock, ("done", {}, 10, 1, 1))

    run_episode(
        evidence(),
        instructions="You are a lamp. You do not move.",
        model=scripted,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    first_context, _ = scripted.asked[0]
    assert first_context[0] == {
        "role": "system", "content": "You are a lamp. You do not move."
    }


def test_an_episode_can_be_run_without_a_persona_but_must_ask():
    """The negative control: a persona that went in whatever the caller said
    would make the test above pass on an implementation that ignored the
    parameter entirely."""
    clock = FakeClock()
    journal = Journal(episode_id="ep-bare", clock=clock, wall_clock=lambda: WALL_CLOCK)
    scripted = ScriptedModel(clock, ("done", {}, 10, 1, 1))

    run_episode(
        evidence(),
        instructions="",
        model=scripted,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    first_context, _ = scripted.asked[0]
    assert all(entry["role"] != "system" for entry in first_context)


def test_the_model_is_shown_what_it_asked_for_last_turn():
    """Without its own previous call in the context, the model cannot tell a
    refusal apart from an answer to something else — and would have no reason
    not to ask for the same refused thing again."""
    _, _, model = ends_after_several_turns()
    second_context, _ = model.asked[1]

    asked = [e for e in second_context if e["role"] == "assistant"]
    assert asked
    assert asked[0]["tool_calls"] == [
        {
            "id": "turn-1-tool",
            "type": "function",
            "function": {
                "name": "move_head",
                "arguments": {"pitch": 140},
            },
        }
    ]


def test_the_next_turn_preserves_native_tool_call_identity_and_roles():
    class NativeScript:
        def __init__(self):
            self.contexts = []
            self.decisions = [
                Decision(
                    tool="speak",
                    args={"text": "hello"},
                    tokens_in=10,
                    tokens_out=2,
                    tool_call_id="call-one",
                    note="Acknowledge the greeting.",
                ),
                Decision(
                    tool="done",
                    args={},
                    tokens_in=14,
                    tokens_out=1,
                    tool_call_id="call-two",
                    note="The greeting is complete.",
                ),
            ]

        def decide(self, working_context, tools):
            self.contexts.append(tuple(working_context))
            return self.decisions.pop(0)

    clock = FakeClock()
    model = NativeScript()
    journal = Journal(episode_id="ep-native-protocol", clock=clock)
    run_episode(
        evidence(transcript="hello"),
        model=model,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(142)),
    )

    second_turn = model.contexts[1]
    assistant = next(entry for entry in second_turn if entry["role"] == "assistant")
    assert assistant == {
        "role": "assistant",
        "content": "Acknowledge the greeting.",
        "tool_calls": [
            {
                "id": "call-one",
                "type": "function",
                "function": {
                    "name": "speak",
                    "arguments": {"text": "hello"},
                },
            }
        ],
    }
    tool_result = next(entry for entry in second_turn if entry["role"] == "tool")
    assert tool_result["tool_call_id"] == "call-one"
    assert tool_result["content"]["result"]["ok"] is True
    assert tool_result["content"]["snapshot"] == {
        "distance_cm": 142,
        "face_present": True,
        "new_speech": None,
    }


def test_the_context_grows_by_the_turn_and_keeps_its_order():
    """Turn n sees everything from Turns 1..n-1, oldest first."""
    _, _, model = ends_after_several_turns()

    lengths = [len(context) for context, _ in model.asked]
    assert lengths == sorted(lengths)
    # The persona and the trigger, before the Episode has done anything.
    assert lengths[0] == 2
    for earlier, later in zip(model.asked, model.asked[1:]):
        assert later[0][: len(earlier[0])] == earlier[0]


def test_the_snapshot_values_reach_the_model_not_just_the_journal():
    """The loop attaches a Snapshot to the Observation *and* has to hand the
    same three facts over. Reporting `distance_cm: None` for a Snapshot that
    said 142 would have the model reasoning about a person it cannot see."""
    _, journal, model = ends_after_several_turns()
    recorded = [r for r in journal.records if isinstance(r, Observation)]
    handed = [
        e["content"]["snapshot"]
        for context, _ in model.asked
        for e in context
        if e["role"] == "tool" and "snapshot" in e.get("content", {})
    ]

    assert handed
    assert handed[0]["distance_cm"] == recorded[0].snapshot.distance_cm
    assert handed[0]["face_present"] == recorded[0].snapshot.face_present


def test_the_first_observation_carries_a_real_distance():
    """The negative control for the test above: it compares two things, and
    would hold if both were None."""
    _, journal, _ = ends_after_several_turns()
    first = next(r for r in journal.records if isinstance(r, Observation))

    assert first.snapshot.distance_cm == 142


# ---------------------------------------------------------------------------
# `as_text` is load-bearing, so it needs its own test
# ---------------------------------------------------------------------------

def test_as_text_contains_what_the_model_was_handed():
    """`test_no_text_the_model_receives_mentions_a_drive_parameter` searches
    this string for forbidden words. An `as_text` that returned `""` would
    make that test pass on any implementation at all — it survived the first
    mutation battery for exactly that reason.
    """
    _, _, model = ends_after_several_turns()
    context, _ = model.asked[-1]

    text = as_text(context)

    assert "trigger" in text
    assert "Coming over." in text
    assert "lost_user" in text
    assert len(text) > 100


def test_as_text_is_not_confused_by_a_snapshot_that_is_all_empty():
    """`default=str` is there so a value it cannot serialise still shows up
    rather than raising, and a `None` must not silently truncate the rest."""
    text = as_text(
        [{"role": "tool", "content": {"snapshot": {"distance_cm": None}}}]
    )

    assert "distance_cm" in text


# ---------------------------------------------------------------------------
# The loop hands over a snapshot of the context, not the list it keeps
# ---------------------------------------------------------------------------

def test_the_model_cannot_edit_the_loops_working_context():
    """The model side is the untrusted side.

    Handing over the live list would let a `Model` implementation — or a
    scripted one in a test — rewrite the Episode's history between Turns, and
    the Journal would not show it.
    """
    class Meddler:
        def __init__(self, clock):
            self._clock = clock
            self.seen = 0

        def decide(self, working_context, tools):
            self.seen = len(working_context)
            with pytest.raises((AttributeError, TypeError)):
                working_context.append({"role": "user", "content": "injected"})
            self._clock.sleep(0.01)
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    clock = FakeClock()
    journal = Journal(episode_id="ep-m", clock=clock, wall_clock=lambda: WALL_CLOCK)
    ctx = ToolContext(
        robot=RealMistyAdapter(RecordingCommands()),
        readings=ScriptedReadings(),
        config=Settings(),
        clock=clock, hazards=ALWAYS_CLEAR
    )
    meddler = Meddler(clock)

    outcome = run_episode(
        evidence(),
        model=meddler,
        registry=build_registry(),
        ctx=ctx,
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    assert outcome.outcome == "done"
    assert meddler.seen == 2  # the persona and the trigger


# ---------------------------------------------------------------------------
# Ending exactly once
# ---------------------------------------------------------------------------

def test_the_journal_itself_refuses_a_second_ending():
    """The loop writes `EpisodeFinished` once by construction, and a mutation
    that wrote it twice survived every assertion here — because the Journal
    already refuses.

    Recorded rather than left implicit: "an Episode ends exactly once" is a
    property `journal.py` owns, and this says so where a reader of the loop
    will look for it.
    """
    _, journal, _ = ends_on_the_first_turn()

    with pytest.raises(ValueError, match="already finished"):
        journal.record(EpisodeFinished, outcome="done", turns=1, steps=0)


# ---------------------------------------------------------------------------
# The abort path (ticket 08)
# ---------------------------------------------------------------------------
#
# The only way an Episode ends that the loop did not decide, and therefore the
# only one that can falsify "every Episode provably returns to idle" rather
# than demonstrate it.

class StopsAfterOneDrive(SimulatedMistyAdapter):
    """A bumper pressed while the base is moving.

    The stop fires from inside `drive`, which is the honest shape: the
    interruption arrives *during* a Tool call, not between two of them, and
    Python cannot interrupt a call that has not returned. After the halt no
    fresh reading comes back, so `approach` spends the rest of its deadline
    waiting and reports `timeout` — which is the decision
    `tests/goldens/README.md` records, because an `arrived` here would claim
    the robot finished a drive it was forbidden to finish.
    """

    def __init__(self, clock, *, start_cm, config, press) -> None:
        super().__init__(
            clock, start_cm=start_cm, actual_motion_multiplier=1.0, config=config
        )
        self._press = press
        self.stopped_at = None

    def drive(self, **kwargs):
        effect = super().drive(**kwargs)
        if self.stopped_at is None:
            self.stopped_at = self._clock.monotonic()
            self._press()
        return effect

    def latest_reading(self):
        self._clock.sleep(0.001)
        if self.stopped_at is not None:
            return None
        return super().latest_reading()


ABORT_CONFIG = Settings(
    approach_timeout_s=4.0,
    post_step_settle_s=0.8,
    approach_reading_timeout_s=2.0,
)


def is_aborted():
    """Golden 4: one Turn, `approach`, a bumper part way through."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-aborted", clock=clock, wall_clock=lambda: WALL_CLOCK
    )
    world = StopsAfterOneDrive(
        clock,
        start_cm=200.0,
        config=ABORT_CONFIG,
        press=lambda: stop.request("foot_bumper"),
    )
    stop = EmergencyStop(journal, world)
    ctx = ToolContext(
        robot=world, readings=world, config=ABORT_CONFIG, clock=clock, hazards=ALWAYS_CLEAR
    )
    model = ScriptedModel(clock, ("approach", {}, 1024, 811, 15))
    outcome = run_episode(
        evidence(),
        model=model,
        registry=build_registry(),
        ctx=ctx,
        journal=journal,
        perception=ScriptedPerception(a_snapshot(97)),
        stop=stop,
    )
    return outcome, journal, model, stop, world


def test_the_loop_reproduces_the_aborted_golden():
    expected = list(from_jsonl((GOLDENS / "episode_is_aborted.jsonl").read_text()))
    _, journal, _, _, _ = is_aborted()

    difference = first_difference(expected, list(journal.records))

    assert difference is None, str(difference)


def test_the_aborted_golden_formatting_matches_too():
    _, journal, _, _, _ = is_aborted()

    assert to_jsonl(list(journal.records)) == (
        GOLDENS / "episode_is_aborted.jsonl"
    ).read_text()


def test_an_abort_ends_the_episode():
    outcome, journal, _, _, _ = is_aborted()

    assert outcome.outcome == "aborted"
    assert journal.records[-1].outcome == "aborted"
    assert isinstance(journal.records[-1], EpisodeFinished)


def test_the_stop_arrives_in_the_middle_of_a_turn_not_at_its_edge():
    """The requirement this ticket exists for.

    An abort that only worked between Turns would be a loop that checks a
    flag, not a robot that stops.

    "In the middle" needs saying carefully, and the first version of this test
    did not: `called.t <= stopped.t < observed.t` is satisfied by a stop that
    lands at the very instant the Tool was called, which is a Turn boundary
    wearing a disguise. What actually makes this mid-Turn is that **the robot
    had already driven** when the bumper was pressed, and the Tool went on
    running for seconds afterwards — so the pin is on the drive, not on the
    timestamps alone.
    """
    _, journal, _, _, world = is_aborted()
    records = list(journal.records)

    called = next(r for r in records if isinstance(r, ToolCalled))
    stopped = next(r for r in records if isinstance(r, StopRequested))
    observed = next(r for r in records if isinstance(r, Observation))

    drives = world.directions
    assert drives, "nothing was moving, so nothing was interrupted"
    assert called.t < stopped.t, "the stop landed on the Turn boundary"
    assert observed.t - stopped.t > 1.0, (
        "the Tool returned almost immediately, so this says nothing about "
        "interrupting one that was still running"
    )
    assert called.turn == observed.turn


def test_the_stop_is_stamped_when_it_happened_not_when_the_loop_noticed():
    """The gap between those two is the interrupt latency, which is the whole
    reason `stop_requested` and `episode_finished` are separate records
    (`PLAN.md` §15.3). A stop stamped on the loop's own schedule would report
    the latency as zero.
    """
    _, journal, _, _, world = is_aborted()
    records = list(journal.records)
    stopped = next(r for r in records if isinstance(r, StopRequested))
    finished = records[-1]

    assert stopped.t == pytest.approx(world.stopped_at, abs=1e-9)
    assert finished.t > stopped.t, "the interrupt latency came out as zero"


def test_the_interrupted_tool_keeps_the_work_it_had_already_done():
    """Python cannot interrupt a call that has not returned, so the Tool
    finishes and its Observation is recorded. Discarding it would lose a drive
    that really happened — and `episode_finished.steps` would then disagree
    with the robot."""
    outcome, journal, _, _, _ = is_aborted()
    observed = next(r for r in journal.records if isinstance(r, Observation))

    assert observed.result["steps"] == 1
    assert outcome.steps == 1


def test_the_interrupted_tool_does_not_claim_it_arrived():
    """`tests/goldens/README.md`: an `arrived` after a stop would say the robot
    completed a drive it was forbidden to finish."""
    _, journal, _, _, _ = is_aborted()
    observed = next(r for r in journal.records if isinstance(r, Observation))

    assert observed.result["result"] != "arrived"
    assert observed.result["result"] == "timeout"


def test_everything_is_halted_when_the_bumper_is_pressed():
    """「中止之後仍然回到閒置：沒有留下未停止的動作」."""
    _, _, _, stop, world = is_aborted()

    assert stop.halted
    assert world.halted


def test_no_further_turn_begins_after_an_abort():
    """The Turn cap is not what ends this Episode; the stop is. Both have to
    hold, and a loop that carried on to the cap would have driven again."""
    outcome, journal, model, _, _ = is_aborted()

    assert outcome.turns == 1
    assert len(model.asked) == 1
    assert sum(isinstance(r, TurnStarted) for r in journal.records) == 1


def test_a_stop_between_turns_starts_no_new_action():
    """The other of the loop's two checks. A stop that arrives while the model
    is thinking must not be followed by a Tool call — the Journal should show
    the Turn beginning, the model answering, and then nothing physical.
    """
    clock = FakeClock()
    journal = Journal(episode_id="ep-mid", clock=clock, wall_clock=lambda: WALL_CLOCK)
    robot = RealMistyAdapter(RecordingCommands())
    stop = EmergencyStop(journal, robot)

    class PressesWhileThinking:
        def decide(self, working_context, tools):
            clock.sleep(0.5)
            stop.request("foot_bumper")
            return Decision(tool="approach", args={}, tokens_in=1, tokens_out=1)

    outcome = run_episode(
        evidence(),
        model=PressesWhileThinking(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot, readings=ScriptedReadings(), config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
        stop=stop,
    )

    kinds = [r.type for r in journal.records]
    assert outcome.outcome == "aborted"
    assert "tool_called" not in kinds
    assert "drive/time" not in robot.commands.endpoints


def test_a_halt_that_fails_still_ends_the_episode():
    """A stop that leaves the robot moving is bad. A stop that leaves the
    robot moving *and* the Episode running is worse, and that is the one this
    rules out."""
    clock = FakeClock()
    journal = Journal(episode_id="ep-bad", clock=clock, wall_clock=lambda: WALL_CLOCK)

    class RefusesToHalt(RecordingCommands):
        def halt(self, motorMask=None):
            raise RuntimeError("the motor controller did not answer")

    robot = RefusesToHalt()
    stop = EmergencyStop(journal, robot)

    class PressesWhileThinking:
        def decide(self, working_context, tools):
            clock.sleep(0.2)
            stop.request("foot_bumper")
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    outcome = run_episode(
        evidence(),
        model=PressesWhileThinking(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot, readings=ScriptedReadings(), config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
        stop=stop,
    )

    assert outcome.outcome == "aborted"
    assert stop.halted is False


def test_an_abort_arriving_from_a_real_thread_still_ends_the_episode():
    """Everything above fires the stop inline, which is deterministic and
    proves the loop's logic. It does not prove the Journal survives two
    threads writing to it, and 「從另一條執行緒觸發」 is the requirement.
    """
    clock = FakeClock()
    journal = Journal(episode_id="ep-thread", clock=clock, wall_clock=lambda: WALL_CLOCK)
    robot = RealMistyAdapter(RecordingCommands())
    stop = EmergencyStop(journal, robot)
    pressed = threading.Event()

    class WaitsForTheBumper:
        def decide(self, working_context, tools):
            presser = threading.Thread(
                target=lambda: (stop.request("foot_bumper"), pressed.set())
            )
            presser.start()
            presser.join(timeout=5)
            assert pressed.wait(timeout=5), "the bumper thread never ran"
            clock.sleep(0.3)
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    outcome = run_episode(
        evidence(),
        model=WaitsForTheBumper(),
        registry=build_registry(),
        ctx=ToolContext(
            robot=robot, readings=ScriptedReadings(), config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
        stop=stop,
    )

    assert outcome.outcome == "aborted"
    assert sum(isinstance(r, StopRequested) for r in journal.records) == 1


def test_an_episode_with_no_stop_wired_still_runs():
    """The null object earns its place: nothing about the ordinary path should
    have to know that an emergency stop exists."""
    outcome, _, _ = ends_on_the_first_turn()

    assert outcome.outcome == "done"


# ---------------------------------------------------------------------------
# Memory (ticket 09)
# ---------------------------------------------------------------------------
#
# The claim `PLAN.md` §15.5 makes is about *where* deriving happens, and the
# only place that can be checked is here: memory alone cannot tell you that a
# Turn did not trigger it.

def test_a_long_episode_derives_memory_exactly_once():
    """Eight Turns, one thing the subject said, one round of deriving.

    The old code extracted facts per Turn. Under ReAct that is a model call
    and its latency spent asking about a record that has not changed since the
    last Turn asked.
    """
    summariser, extractor = CountingSummariser(), CountingExtractor()
    memory = Memory(summariser=summariser, extractor=extractor, window=6)
    cap = Settings().max_turns_per_episode
    clock = FakeClock()
    journal = Journal(episode_id="ep-mem", clock=clock, wall_clock=lambda: WALL_CLOCK)

    outcome = run_episode(
        evidence(transcript="hello there"),
        memory=memory,
        model=ScriptedModel(
            clock, *[("look_around", {}, 10, 1, 1) for _ in range(cap)]
        ),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ScriptedReadings(*[a_reading() for _ in range(cap * 4)]),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    assert outcome.turns == cap
    assert extractor.calls == 1
    assert summariser.calls == 0


def test_what_the_robot_said_is_what_gets_remembered():
    """The other half of an Exchange, collected from what each Tool declares
    it speaks — so the loop never has to know the Tool is called `speak` or
    its argument `text`."""
    memory = Memory(summariser=None, extractor=None, window=6)
    clock = FakeClock()
    journal = Journal(episode_id="ep-say", clock=clock, wall_clock=lambda: WALL_CLOCK)

    run_episode(
        evidence(transcript="are you there?"),
        memory=memory,
        model=ScriptedModel(
            clock,
            ("speak", {"text": "I am here."}, 10, 1, 1),
            ("speak", {"text": "Coming over."}, 10, 1, 1),
            ("done", {}, 10, 1, 1),
        ),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    remembered = memory.exchanges[-1]
    assert remembered.said == "are you there?"
    assert remembered.replied == "I am here. Coming over."


def test_an_episode_where_the_robot_says_nothing_still_records_the_exchange():
    """Otherwise "they spoke and the robot ignored them" leaves no trace, and
    the next Episode's model has no idea it happened."""
    memory = Memory(summariser=None, extractor=None, window=6)
    clock = FakeClock()
    journal = Journal(episode_id="ep-mute", clock=clock, wall_clock=lambda: WALL_CLOCK)

    run_episode(
        evidence(transcript="hello?"),
        memory=memory,
        model=ScriptedModel(clock, ("done", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    assert memory.exchanges[-1] == Exchange(said="hello?", replied="")


def test_the_models_message_list_is_never_stored_as_memory(tmp_path):
    """The confusion this whole redesign is arranged against.

    `CONTEXT.md` reserves *Exchange* for the durable unit and says the message
    list is one Episode's working context, discarded with it. Persisting the
    latter would save a wall of Tool-call plumbing — roles, schemas,
    Observations, refusals — that nobody will ever read and that says nothing
    about the person.
    """
    path = str(tmp_path / "memory.json")
    memory = Memory(summariser=None, extractor=None, window=6, path=path)
    clock = FakeClock()
    journal = Journal(episode_id="ep-leak", clock=clock, wall_clock=lambda: WALL_CLOCK)

    scripted = ScriptedModel(
        clock,
        ("move_head", {"pitch": 140}, 10, 1, 1),
        ("speak", {"text": "Coming over."}, 10, 1, 1),
        ("done", {}, 10, 1, 1),
    )
    run_episode(
        evidence(transcript="come here"),
        memory=memory,
        model=scripted,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )
    memory.save()

    saved = (tmp_path / "memory.json").read_text()
    for plumbing in ("role", "assistant", "tool_called", "snapshot",
                     "observation", "refused", "outside the permitted range"):
        assert plumbing not in saved, plumbing
    assert "come here" in saved and "Coming over." in saved


def test_what_memory_knows_reaches_the_model_after_the_persona():
    """A memory nobody is shown is a file, not a memory.

    And it comes *after* the persona: who you are does not depend on what you
    remember, but what you make of a memory depends on who you are.
    """
    memory = Memory(summariser=None, extractor=None, window=6)
    memory.remember(Exchange(said="I am Ana", replied="Hello Ana"))
    clock = FakeClock()
    journal = Journal(episode_id="ep-read", clock=clock, wall_clock=lambda: WALL_CLOCK)

    scripted = ScriptedModel(clock, ("done", {}, 10, 1, 1))
    run_episode(
        evidence(transcript="hello again"),
        memory=memory,
        model=scripted,
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    first_context, _ = scripted.asked[0]
    told = [e["content"] for e in first_context if e["role"] == "system"]
    assert told[0] == PERSONA
    assert any("I am Ana" in block for block in told[1:])


def test_an_episode_with_no_memory_shows_the_model_only_its_persona():
    """The null object again: the ordinary path should not have to know
    memory exists — and an empty memory must not become an empty block of
    prose the model has to read past."""
    _, _, model = ends_on_the_first_turn()
    first_context, _ = model.asked[0]

    told = [entry["content"] for entry in first_context if entry["role"] == "system"]
    assert told == [PERSONA]


def test_memory_is_derived_after_the_episode_has_already_ended():
    """`close_episode` may call a model. Folding that into the Episode would
    put work nobody is waiting for inside every latency measurement — and
    would move `episode_finished.t`, which four goldens pin.
    """
    seen_at_close = {}

    class NotesWhenItRan:
        calls = 0

        def extract(self, known, exchanges):
            NotesWhenItRan.calls += 1
            seen_at_close["records"] = [r.type for r in journal.records]
            return {}

    clock = FakeClock()
    journal = Journal(episode_id="ep-after", clock=clock, wall_clock=lambda: WALL_CLOCK)
    memory = Memory(summariser=None, extractor=NotesWhenItRan(), window=6)

    run_episode(
        evidence(transcript="hello"),
        memory=memory,
        model=ScriptedModel(clock, ("done", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    assert NotesWhenItRan.calls == 1
    assert seen_at_close["records"][-1] == "episode_finished"


def test_post_episode_memory_failure_cannot_hide_the_completed_journal():
    """Memory derives after the Episode; its failure cannot reopen the run."""
    clock = FakeClock()
    journal = Journal(
        episode_id="ep-memory-close-error",
        clock=clock,
        wall_clock=lambda: WALL_CLOCK,
    )

    class FailsAfterTheEnding:
        def as_prompt_block(self):
            return ""

        def remember(self, exchange):
            pass

        def close_episode(self):
            raise RuntimeError("fact extractor failed")

    outcome = run_episode(
        evidence(),
        model=ScriptedModel(clock, ("done", {}, 10, 1, 1)),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()),
            readings=ScriptedReadings(),
            config=Settings(),
            clock=clock, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
        memory=FailsAfterTheEnding(),
    )

    assert outcome.outcome == "done"
    assert isinstance(journal.records[-1], EpisodeFinished)


def test_an_episode_that_speaks_shuts_the_microphone_for_that_long():
    """The whole path, not just `dispatch`: the microphone reaches `speak`
    through the same `ToolContext` everything else does."""
    class RecordingEars:
        def __init__(self):
            self.muted_for = []

        def mute_for(self, seconds):
            self.muted_for.append(seconds)

    ears = RecordingEars()
    clock = FakeClock()
    journal = Journal(episode_id="ep-mute", clock=clock, wall_clock=lambda: WALL_CLOCK)

    run_episode(
        evidence(transcript="are you there?"),
        model=ScriptedModel(
            clock,
            ("speak", {"text": "Coming over."}, 10, 1, 1),
            ("done", {}, 10, 1, 1),
        ),
        registry=build_registry(),
        ctx=ToolContext(
            robot=RealMistyAdapter(RecordingCommands()), readings=ScriptedReadings(),
            config=Settings(), clock=clock, ears=ears, hazards=ALWAYS_CLEAR
        ),
        journal=journal,
        perception=ScriptedPerception(a_snapshot(120)),
    )

    observed = next(r for r in journal.records if isinstance(r, Observation))
    assert ears.muted_for == [observed.result["estimated_speech_ms"] / 1000.0]

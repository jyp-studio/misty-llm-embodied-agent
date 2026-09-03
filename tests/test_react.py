"""One Episode, end to end, against the Journals that were written first.

`tests/goldens/` holds four Journals this loop has to be able to produce. They
were committed before the loop existed — that is the whole of their evidence
value, and it is why the interesting assertions here are equality against a
file rather than a list of properties someone thought of afterwards.

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

import pytest

from journal_diff import first_difference
from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
    Journal,
    ModelCalled,
    Observation,
    Snapshot,
    ToolCalled,
    ToolRejected,
    TurnStarted,
    from_jsonl,
    to_jsonl,
)
from misty_agent.agent.react import Decision, EpisodeOutcome, as_text, run_episode
from misty_agent.agent.tools import ToolContext, build_registry
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.perception.distance import DistanceReading

from test_approach import WorldThatLosesTheUserAfterAStep

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
        distance_cm=distance_cm, frame_arrived_at=0.0, detected_at=0.0
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
        robot=the_world or RecordingCommands(),
        readings=the_world or readings,
        config=settings,
        clock=clock,
    )
    model = ScriptedModel(clock, *script)
    outcome = run_episode(
        trigger,
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


GOLDEN_EPISODES = [
    ("episode_ends_on_the_first_turn.jsonl", ends_on_the_first_turn),
    ("episode_ends_after_several_turns.jsonl", ends_after_several_turns),
    ("episode_hits_the_turn_limit.jsonl", hits_the_turn_limit),
]


@pytest.mark.parametrize("name,episode", GOLDEN_EPISODES)
def test_the_loop_reproduces_the_golden_journal(name, episode):
    """The assertion this whole milestone is arranged around.

    Not "the Journal looks plausible" — equal, record for record, field for
    field, to a file `git log` shows was committed before this loop existed.
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
        robot=RecordingCommands(),
        readings=ScriptedReadings(),
        config=Settings(max_turns_per_episode=2),
        clock=clock,
    )
    registry._tools["done"] = dataclasses.replace(
        registry.get("done"), ends_episode=False
    )

    outcome = run_episode(
        "speech",
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

def test_the_trigger_is_the_first_thing_the_model_is_told():
    """Otherwise the first Turn is a decision made about nothing."""
    _, _, model = ends_on_the_first_turn()
    first_context, _ = model.asked[0]

    assert first_context[0]["role"] == "user"
    assert first_context[0]["content"] == {"trigger": "speech"}


def test_the_model_is_shown_what_it_asked_for_last_turn():
    """Without its own previous call in the context, the model cannot tell a
    refusal apart from an answer to something else — and would have no reason
    not to ask for the same refused thing again."""
    _, _, model = ends_after_several_turns()
    second_context, _ = model.asked[1]

    asked = [e for e in second_context if e["role"] == "assistant"]
    assert asked
    assert asked[0]["content"] == {"tool": "move_head", "args": {"pitch": 140}}


def test_the_context_grows_by_the_turn_and_keeps_its_order():
    """Turn n sees everything from Turns 1..n-1, oldest first."""
    _, _, model = ends_after_several_turns()

    lengths = [len(context) for context, _ in model.asked]
    assert lengths == sorted(lengths)
    assert lengths[0] == 1
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
        robot=RecordingCommands(),
        readings=ScriptedReadings(),
        config=Settings(),
        clock=clock,
    )
    meddler = Meddler(clock)

    outcome = run_episode(
        "speech",
        model=meddler,
        registry=build_registry(),
        ctx=ctx,
        journal=journal,
        perception=ScriptedPerception(a_snapshot(100)),
    )

    assert outcome.outcome == "done"
    assert meddler.seen == 1


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

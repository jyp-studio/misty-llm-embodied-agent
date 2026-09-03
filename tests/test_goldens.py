"""The four golden Journals, and the helper that compares against them.

These files were written before the loop that will produce them, which is the
whole point (`PLAN.md` §15.6): a schema written alongside its only producer
ends up describing the producer, and assertions built on it agree with the
code by construction.

So nothing here can check a golden against an implementation — there isn't
one. What it checks instead is that each golden is a *coherent* Journal: it
parses, its records are internally consistent, and between them the four cover
every way an Episode can end. Plus that the comparison helper says something
useful when they do not match, because a helper that only says "different" is
one nobody will use on a twenty-record file.
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from journal_diff import first_difference

from misty_agent.agent.journal import (
    OUTCOMES,
    EpisodeFinished,
    EpisodeStarted,
    ModelCalled,
    Observation,
    StopRequested,
    ToolCalled,
    ToolRejected,
    TurnStarted,
    from_jsonl,
    to_jsonl,
)
from misty_agent.config import Settings

GOLDENS = pathlib.Path(__file__).parent / "goldens"

#: One per way an Episode ends. Named rather than globbed: a file that quietly
#: disappeared would otherwise take its coverage with it and nothing would say
#: so.
EXPECTED_GOLDENS = {
    "episode_ends_on_the_first_turn.jsonl": "done",
    "episode_ends_after_several_turns.jsonl": "done",
    "episode_hits_the_turn_limit.jsonl": "turn_limit",
    "episode_is_aborted.jsonl": "aborted",
}


def load(name: str):
    return from_jsonl((GOLDENS / name).read_text())


@pytest.fixture(params=sorted(EXPECTED_GOLDENS))
def golden(request):
    return request.param, load(request.param)


# ---------------------------------------------------------------------------
# The set of them
# ---------------------------------------------------------------------------

def test_there_is_a_golden_for_every_way_an_episode_can_end():
    on_disk = {path.name for path in GOLDENS.glob("*.jsonl")}

    assert on_disk == set(EXPECTED_GOLDENS)


def test_between_them_the_goldens_cover_every_outcome():
    """Four files, three outcomes — and that asymmetry is deliberate.

    Ending on the first Turn and ending after several are both the model
    choosing to stop. They are separate files because they are separate paths
    through the loop, not separate endings.
    """
    covered = {
        load(name)[-1].outcome for name in EXPECTED_GOLDENS
    }

    assert covered == set(OUTCOMES)


def test_each_golden_ends_the_way_its_name_says():
    for name, outcome in EXPECTED_GOLDENS.items():
        assert load(name)[-1].outcome == outcome, name


# ---------------------------------------------------------------------------
# Each of them, as a Journal
# ---------------------------------------------------------------------------

def test_a_golden_parses_into_records(golden):
    name, records = golden

    assert records, name
    assert all(dataclasses.is_dataclass(record) for record in records)


def test_a_golden_round_trips_so_its_formatting_is_pinned_too(golden):
    """Records are the contract, but the file still has to be stable text.

    Ticket 07 writes these through the same serialiser. If key order or
    encoding drifted, every golden would go red for a reason that has nothing
    to do with the loop.
    """
    name, records = golden

    assert to_jsonl(records) == (GOLDENS / name).read_text(), name


def test_a_golden_begins_once_and_ends_once(golden):
    """The property `EpisodeFinished` exists as a single kind to make countable."""
    name, records = golden

    assert isinstance(records[0], EpisodeStarted), name
    assert isinstance(records[-1], EpisodeFinished), name
    assert sum(isinstance(r, EpisodeStarted) for r in records) == 1, name
    assert sum(isinstance(r, EpisodeFinished) for r in records) == 1, name


def test_a_golden_belongs_to_one_episode(golden):
    name, records = golden
    ids = {record.episode_id for record in records}

    assert len(ids) == 1, f"{name} mixes {ids}"


def test_time_never_goes_backwards_in_a_golden(golden):
    name, records = golden
    times = [record.t for record in records]

    assert times == sorted(times), name
    assert times[0] == 0.0, f"{name} does not start at its own beginning"


def test_turns_are_numbered_from_one_without_gaps(golden):
    name, records = golden
    started = [r.turn for r in records if isinstance(r, TurnStarted)]

    assert started == list(range(1, len(started) + 1)), name


def test_the_ending_counts_the_turns_that_actually_happened(golden):
    name, records = golden
    started = sum(isinstance(r, TurnStarted) for r in records)

    assert records[-1].turns == started, name


def test_every_turn_scoped_record_names_a_turn_that_began(golden):
    name, records = golden
    began = {r.turn for r in records if isinstance(r, TurnStarted)}

    for record in records:
        turn = getattr(record, "turn", None)
        if turn is not None:
            assert turn in began, f"{name}: {record.type} claims turn {turn}"


# ---------------------------------------------------------------------------
# The decisions these files pin
# ---------------------------------------------------------------------------

def test_choosing_done_does_not_produce_an_observation():
    """An Observation is what the model reads to decide the next Turn.

    After `done` there is no next Turn, so one would be recorded for nobody.
    Documented in `tests/goldens/README.md`; asserted here so that changing it
    is a visible decision rather than a drift.
    """
    for name in EXPECTED_GOLDENS:
        records = load(name)
        done_turns = {
            record.turn
            for record in records
            if isinstance(record, ToolCalled) and record.tool == "done"
        }
        observed_turns = {
            record.turn for record in records if isinstance(record, Observation)
        }

        assert not (done_turns & observed_turns), name


def test_the_turn_limit_golden_lets_its_last_turn_finish():
    """The cap stops a sixth Turn starting; it does not cut the fifth short."""
    records = load("episode_hits_the_turn_limit.jsonl")
    last_turn = records[-1].turns

    assert any(
        isinstance(record, Observation) and record.turn == last_turn
        for record in records
    )


def test_the_aborted_golden_keeps_the_work_the_tool_had_already_done():
    """Python cannot interrupt a call that has not returned.

    So the Tool finishes, its Observation is recorded, and only then does the
    Episode end. Discarding it would lose something the robot actually did.
    """
    records = load("episode_is_aborted.jsonl")
    stopped_at = next(
        record.t for record in records if isinstance(record, StopRequested)
    )
    after_the_stop = [record for record in records if record.t > stopped_at]

    assert any(isinstance(record, Observation) for record in after_the_stop)


def test_the_aborted_golden_shows_how_long_the_interrupt_took():
    """Two records rather than one, so the gap between them is measurable."""
    records = load("episode_is_aborted.jsonl")
    requested = next(r.t for r in records if isinstance(r, StopRequested))

    assert records[-1].t > requested


# ---------------------------------------------------------------------------
# Each golden is the Journal its name and the README claim
#
# Without these, a golden can be replaced wholesale and the suite stays green —
# outcome coverage alone does not notice that the multi-Turn path has quietly
# become a copy of the one-Turn path.
# ---------------------------------------------------------------------------

def tools_called(records):
    return [r.tool for r in records if isinstance(r, ToolCalled)]


def test_each_golden_is_a_different_episode():
    ids = [load(name)[0].episode_id for name in EXPECTED_GOLDENS]

    assert len(set(ids)) == len(ids), f"two goldens share an id: {ids}"


def test_the_first_turn_golden_does_exactly_one_thing():
    records = load("episode_ends_on_the_first_turn.jsonl")

    assert tools_called(records) == ["done"]
    assert records[-1].turns == 1


def test_the_several_turns_golden_composes_an_action_out_of_tools():
    """The path this file exists for: several Turns, not one.

    Made a copy of the one-Turn golden, everything else here still passed.
    """
    records = load("episode_ends_after_several_turns.jsonl")

    assert records[-1].turns >= 3
    assert tools_called(records)[-1] == "done"
    assert len(set(tools_called(records))) >= 3


def test_the_several_turns_golden_shows_a_refusal_and_a_tool_that_did_not_succeed():
    """Spec: the Journal must cover 參數被拒絕, and user story 2 is about the
    model failing and doing something else. Without both, ticket 07's failure
    branch and ticket 04's rejection path have nothing to be checked against.
    """
    records = load("episode_ends_after_several_turns.jsonl")
    results = [
        r.result.get("result") for r in records if isinstance(r, Observation)
    ]

    assert any(isinstance(r, ToolRejected) for r in records)
    assert any(result not in (None, "arrived") for result in results)


def test_the_turn_limit_golden_stops_at_the_configured_cap():
    """Otherwise revising the cap silently invalidates this golden."""
    records = load("episode_hits_the_turn_limit.jsonl")

    assert records[-1].turns == Settings().max_turns_per_episode


def test_the_aborted_golden_does_not_claim_the_drive_completed():
    """A bumper halts the motors.

    An `arrived` after the stop would mean the robot finished a drive it was
    forbidden to finish — and it is the reading a reviewer would use to argue
    the abort did nothing. Ticket 08 confirms or overturns this; either way
    it is a decision, and `PLAN.md` records it.
    """
    records = load("episode_is_aborted.jsonl")
    stopped_at = next(r.t for r in records if isinstance(r, StopRequested))
    after = [
        r for r in records if isinstance(r, Observation) and r.t > stopped_at
    ]

    assert after, "the golden no longer shows what the tool returned"
    assert all(r.result.get("result") != "arrived" for r in after)


def test_the_steps_count_is_the_sum_of_the_drives_that_happened():
    """`steps` is derivable, so nothing should be free to invent it."""
    for name in EXPECTED_GOLDENS:
        records = load(name)
        drove = sum(
            record.result.get("steps", 0)
            for record in records
            if isinstance(record, Observation)
        )

        assert records[-1].steps == drove, name


def test_a_speak_observation_uses_the_only_speech_estimator_the_project_has():
    """`PLAN.md` §4: words / 2.2 + 0.5, capped at 12s — and §15.4 records that
    Misty's TTS returns no timing at all, so an invented number here would be
    a number from nowhere in a file whose whole claim is to be derived.
    """
    records = load("episode_ends_after_several_turns.jsonl")
    spoken = [
        (call, seen)
        for call, seen in zip(records, records[1:])
        if isinstance(call, ToolCalled) and call.tool == "speak"
    ]

    assert spoken, "the golden no longer exercises speak"
    for call, seen in spoken:
        words = max(1, len(call.args["text"].split()))
        expected = int(round(min(12.0, words / 2.2 + 0.5) * 1000))
        assert seen.result["estimated_speech_ms"] == expected


def test_every_tool_call_but_done_is_followed_by_an_observation():
    for name in EXPECTED_GOLDENS:
        records = load(name)
        acted = {
            r.turn for r in records
            if isinstance(r, ToolCalled) and r.tool != "done"
        }
        observed = {r.turn for r in records if isinstance(r, Observation)}

        assert acted <= observed, f"{name}: turns {acted - observed} acted unseen"


def test_a_model_call_is_consistent_with_the_time_it_took():
    """Otherwise the latency figures are decoration, and ticket 07 will be
    checked against numbers nothing defends.
    """
    for name in EXPECTED_GOLDENS:
        records = load(name)
        for started, called in zip(records, records[1:]):
            if isinstance(started, TurnStarted) and isinstance(called, ModelCalled):
                elapsed_ms = (called.t - started.t) * 1000
                assert abs(elapsed_ms - called.latency_ms) < 2, (
                    f"{name} turn {called.turn}: {elapsed_ms:.0f}ms elapsed "
                    f"but latency_ms says {called.latency_ms}"
                )


# ---------------------------------------------------------------------------
# The comparison helper
#
# Asserting on fields, not on substrings. When this returned a formatted
# string, three ways of getting the comparison wrong survived: reporting the
# last difference instead of the first, swapping expected and actual, and
# naming the record kind while dropping the field — because `"turn" in
# message` is satisfied by `turn_started`.
# ---------------------------------------------------------------------------

def test_identical_journals_have_no_first_difference():
    records = load("episode_ends_on_the_first_turn.jsonl")

    assert first_difference(records, records) is None


def test_a_changed_field_is_reported_with_its_position_and_both_values():
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[5] = dataclasses.replace(changed[5], turn=99)

    difference = first_difference(records, changed)

    assert difference.what == "field"
    assert difference.index == 5
    assert difference.field == "turn"
    assert difference.expected == records[5].turn
    assert difference.actual == 99


def test_the_expected_value_is_not_swapped_with_the_actual_one():
    """Swapping them used to survive: the message contained both numbers."""
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[5] = dataclasses.replace(changed[5], turn=99)

    difference = first_difference(records, changed)

    assert (difference.expected, difference.actual) == (records[5].turn, 99)


def test_the_field_is_named_not_only_the_record_kind():
    """`"turn" in message` was satisfied by `turn_started`, so dropping the
    field name from the report survived. The field is now its own value.
    """
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[5] = dataclasses.replace(changed[5], turn=99)

    difference = first_difference(records, changed)

    assert difference.field == "turn"
    assert difference.kind == "turn_started"
    assert difference.field != difference.kind


def test_a_changed_kind_is_reported_as_a_kind_not_a_field():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))
    changed = list(records)
    changed[1] = StopRequested(t=0.004, episode_id="ep-first-turn", source="x")

    difference = first_difference(records, changed)

    assert difference.what == "kind"
    assert difference.index == 1
    assert (difference.expected, difference.actual) == (
        "turn_started",
        "stop_requested",
    )


def test_a_missing_record_is_reported_as_a_length_difference():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))

    difference = first_difference(records, records[:-1])

    assert difference.what == "length"
    assert difference.expected[-1] == "episode_finished"
    assert "episode_finished" not in difference.actual


def test_an_extra_record_is_reported_too():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))
    extra = records + [StopRequested(t=9.0, episode_id="ep-first-turn", source="x")]

    difference = first_difference(records, extra)

    assert difference.what == "length"
    assert difference.actual[-1] == "stop_requested"


def test_the_first_difference_is_reported_not_the_last():
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[3] = dataclasses.replace(changed[3], turn=98)
    changed[9] = dataclasses.replace(changed[9], turn=99)

    difference = first_difference(records, changed)

    assert difference.index == 3
    assert difference.actual == 98


def test_a_difference_still_reads_as_a_sentence_when_printed():
    """The structure is for tests; a person still has to be able to read it."""
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[5] = dataclasses.replace(changed[5], turn=99)

    printed = str(first_difference(records, changed))

    assert "record 5" in printed and "turn_started" in printed and "99" in printed


def test_a_journal_that_differs_only_late_is_still_compared_to_the_end():
    """Comparing a prefix would pass a Journal that went wrong at the end."""
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[-1] = dataclasses.replace(changed[-1], turns=99)

    difference = first_difference(records, changed)

    assert difference is not None
    assert difference.index == len(records) - 1


def test_a_journal_that_differs_only_in_timing_is_still_a_difference():
    """`t` is a field like any other, and the reason the clock is injectable.

    Skipping it in the comparison survived every other test here: nothing else
    changes only the time. Ticket 07 is checked against these goldens on the
    strength of a fake clock making `t` reproducible — a comparison blind to
    `t` would make that pointless.
    """
    records = list(load("episode_ends_on_the_first_turn.jsonl"))
    later = list(records)
    later[2] = dataclasses.replace(later[2], t=records[2].t + 5.0)

    difference = first_difference(records, later)

    assert difference is not None, "a Journal that ran slower compared equal"
    assert difference.field == "t"
    assert difference.index == 2

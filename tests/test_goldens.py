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

from misty_agent.agent.journal import (
    OUTCOMES,
    EpisodeFinished,
    EpisodeStarted,
    Observation,
    StopRequested,
    ToolCalled,
    TurnStarted,
    first_difference,
    from_jsonl,
    to_jsonl,
)

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
# The comparison helper
# ---------------------------------------------------------------------------

def test_identical_journals_have_no_first_difference():
    records = load("episode_ends_on_the_first_turn.jsonl")

    assert first_difference(records, records) is None


def test_a_changed_field_is_reported_with_its_position_and_both_values():
    """"They are different" is not a useful thing to be told about 22 records."""
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[5] = dataclasses.replace(changed[5], turn=99)

    message = first_difference(records, changed)

    assert "record 5" in message
    assert "turn" in message
    assert "99" in message


def test_a_changed_kind_is_reported_as_a_kind_not_a_field():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))
    changed = list(records)
    changed[1] = StopRequested(t=0.004, episode_id="ep-first-turn", source="x")

    message = first_difference(records, changed)

    assert "record 1" in message
    assert "turn_started" in message
    assert "stop_requested" in message


def test_a_missing_record_is_reported_as_a_length_difference():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))

    message = first_difference(records, records[:-1])

    assert "more record" in message
    assert "episode_finished" in message


def test_an_extra_record_is_reported_too():
    records = list(load("episode_ends_on_the_first_turn.jsonl"))
    extra = records + [StopRequested(t=9.0, episode_id="ep-first-turn", source="x")]

    message = first_difference(records, extra)

    assert "more record" in message
    assert "stop_requested" in message


def test_the_first_difference_is_reported_not_the_last():
    records = list(load("episode_hits_the_turn_limit.jsonl"))
    changed = list(records)
    changed[3] = dataclasses.replace(changed[3], turn=98)
    changed[9] = dataclasses.replace(changed[9], turn=99)

    message = first_difference(records, changed)

    assert "record 3" in message
    assert "98" in message

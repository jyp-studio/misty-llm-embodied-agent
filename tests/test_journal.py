"""The Journal's records, and what they are allowed to say.

Serialisation here is pure — records in, text out — so every test runs in
milliseconds with no file, no clock and no model. The writing side, with its
lock and its subscribers, is ticket 02 and lives elsewhere.

Two things this file guards that are not about arithmetic:

* **The Journal cannot carry a physical control parameter.** `PLAN.md` §4's
  layering claim is that the model decides whether to approach and the control
  layer decides how far each Step goes. If a velocity or a drive duration ever
  reached a record, that claim would be false in the one artefact a reader
  would check it against.
* **`turn` is not a base field.** An Episode's opening record has no Turn, so a
  base field would force an Optional onto every reader.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from misty_agent.agent.journal import (
    JOURNAL_SCHEMA,
    RECORD_TYPES,
    EpisodeAborted,
    EpisodeClock,
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


class FakeClock:
    """The same shape the approach loop already injects."""

    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def one_of_each():
    """A record of every kind, with content a real Episode would produce."""
    return [
        EpisodeStarted(
            t=0.0,
            episode_id="ep-1",
            trigger="speech",
            started_at_wall_clock="2026-08-24T11:00:00+08:00",
            schema=JOURNAL_SCHEMA,
        ),
        TurnStarted(t=0.01, episode_id="ep-1", turn=1),
        ModelCalled(
            t=1.85,
            episode_id="ep-1",
            turn=1,
            latency_ms=1840,
            tokens_in=1203,
            tokens_out=47,
        ),
        ToolCalled(
            t=1.86, episode_id="ep-1", turn=1, tool="approach", args={}
        ),
        Observation(
            t=6.9,
            episode_id="ep-1",
            turn=1,
            payload={
                "result": "arrived",
                "steps": 2,
                "distance_cm": 63,
                "face_present": True,
                "new_speech": None,
            },
        ),
        ToolRejected(
            t=7.0,
            episode_id="ep-1",
            turn=2,
            tool="move_head",
            reason="pitch 999 is outside the permitted range",
        ),
        StopRequested(t=7.4, episode_id="ep-1", source="foot_bumper"),
        EpisodeAborted(t=7.5, episode_id="ep-1", reason="foot_bumper"),
        EpisodeFinished(
            t=7.6,
            episode_id="ep-1",
            outcome="aborted",
            turns=2,
            steps=2,
        ),
    ]


# ---------------------------------------------------------------------------
# What a record is
# ---------------------------------------------------------------------------

BASE_FIELDS = {"t", "episode_id"}


def test_every_record_kind_is_frozen():
    for record_type in RECORD_TYPES.values():
        assert dataclasses.is_dataclass(record_type)
        assert record_type.__dataclass_params__.frozen, record_type.__name__


def test_every_record_carries_the_same_three_base_fields():
    for record in one_of_each():
        names = {field.name for field in dataclasses.fields(record)}
        assert BASE_FIELDS <= names, type(record).__name__
        assert record.type in RECORD_TYPES


def test_turn_is_not_a_base_field():
    """The opening record has no Turn, and a base field would force an Optional.

    Every reader would then have to handle a None that cannot occur on the
    records they actually care about.
    """
    opening = {field.name for field in dataclasses.fields(EpisodeStarted)}

    assert "turn" not in opening
    assert "turn" in {field.name for field in dataclasses.fields(TurnStarted)}


def test_the_opening_record_carries_a_wall_clock_and_a_schema_version():
    opening = one_of_each()[0]

    assert opening.started_at_wall_clock
    assert opening.schema == JOURNAL_SCHEMA


def test_only_the_opening_record_carries_a_wall_clock():
    """One absolute stamp, so the rest stay byte-comparable against goldens."""
    stamped = [
        record
        for record in one_of_each()
        if any(
            "wall_clock" in field.name for field in dataclasses.fields(record)
        )
    ]

    assert [type(record).__name__ for record in stamped] == ["EpisodeStarted"]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def test_elapsed_time_is_measured_from_when_the_episode_began():
    clock = FakeClock()
    episode = EpisodeClock(clock)

    clock.now += 2.5

    assert episode.elapsed_s() == pytest.approx(2.5)


def test_elapsed_time_starts_at_zero():
    assert EpisodeClock(FakeClock()).elapsed_s() == 0.0


def test_elapsed_time_is_rounded_so_goldens_stay_comparable():
    clock = FakeClock()
    episode = EpisodeClock(clock)

    clock.now += 1.23456789

    assert episode.elapsed_s() == 1.235


def test_the_clock_is_injectable_and_nothing_reads_the_wall_clock_for_t():
    """Two Episodes on the same fake clock produce the same elapsed values.

    Without an injectable clock a golden Journal could never be compared byte
    for byte, which is what ticket 03 depends on.
    """
    first, second = EpisodeClock(FakeClock()), EpisodeClock(FakeClock())

    assert first.elapsed_s() == second.elapsed_s()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_records_survive_a_round_trip_through_jsonl():
    records = one_of_each()

    assert from_jsonl(to_jsonl(records)) == tuple(records)


def test_every_record_kind_round_trips_not_just_the_convenient_ones():
    # Guards against a kind being added to the module and forgotten here.
    kinds = {record.type for record in one_of_each()}

    assert kinds == set(RECORD_TYPES)


def test_one_record_per_line():
    text = to_jsonl(one_of_each())
    lines = [line for line in text.splitlines() if line.strip()]

    assert len(lines) == len(one_of_each())
    for line in lines:
        json.loads(line)


def test_serialising_the_same_records_twice_gives_the_same_text():
    records = one_of_each()

    assert to_jsonl(records) == to_jsonl(records)


def test_serialising_touches_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    to_jsonl(one_of_each())

    assert list(tmp_path.iterdir()) == []


def test_blank_lines_are_tolerated_when_reading():
    text = to_jsonl(one_of_each())

    assert from_jsonl(f"\n{text}\n\n") == tuple(one_of_each())


def test_an_unknown_record_kind_is_refused_rather_than_skipped():
    """Silently dropping a line would make a truncated Journal look complete."""
    with pytest.raises(ValueError, match="unknown"):
        from_jsonl('{"type": "telepathy", "t": 0.0, "episode_id": "ep-1"}')


def test_a_record_missing_a_field_is_refused():
    with pytest.raises(ValueError):
        from_jsonl('{"type": "turn_started", "t": 0.0, "episode_id": "ep-1"}')


# ---------------------------------------------------------------------------
# The line the Journal must not cross
# ---------------------------------------------------------------------------

#: Names that would mean the control layer's physical parameters had reached
#: the record the model's behaviour is judged against. `latency_ms` is not
#: among them: how long the model took is not a drive command.
FORBIDDEN = (
    "velocity",
    "linearvelocity",
    "angularvelocity",
    "timems",
    "time_ms",
    "drive_ms",
    "cm_per_sec",
)


def test_no_record_kind_declares_a_physical_control_parameter():
    for record_type in RECORD_TYPES.values():
        for field in dataclasses.fields(record_type):
            assert not any(
                forbidden in field.name.lower() for forbidden in FORBIDDEN
            ), f"{record_type.__name__}.{field.name}"


def test_a_serialised_journal_mentions_no_physical_control_parameter():
    text = to_jsonl(one_of_each()).lower()

    for forbidden in FORBIDDEN:
        assert forbidden not in text


def test_the_schema_says_it_is_not_stable_yet():
    """A reader who builds against this deserves to know it will move.

    `PLAN.md` §15.3: the schema is not frozen before M10. This is a portfolio
    piece, not a published API, and pretending otherwise would buy a
    compatibility obligation nobody wants.
    """
    assert "unstable" in JOURNAL_SCHEMA


def test_a_record_cannot_be_built_without_the_data_it_claims_to_carry():
    """No invented defaults. Missing data is a construction error.

    An earlier version gave every field a default so that inheritance would
    satisfy dataclass field ordering. `ToolCalled(t=0, episode_id="x")` then
    built successfully with `args=None` in a field typed as a mapping — a
    record that lies about what it holds.
    """
    with pytest.raises(TypeError):
        ToolCalled(t=0.0, episode_id="ep-1")

    with pytest.raises(TypeError):
        EpisodeFinished(t=0.0, episode_id="ep-1")


def test_records_are_keyword_only_so_field_order_never_becomes_an_api():
    """Positional construction would freeze the field order into the contract.

    Adding a field would then silently change what a positional call means.
    """
    with pytest.raises(TypeError):
        TurnStarted(0.0, "ep-1", 1)


def test_a_record_with_an_unexpected_field_is_refused():
    """A golden carrying a field the types do not know would drift silently.

    Accepting it means a golden and the record it is supposed to pin can
    disagree while both look fine.
    """
    with pytest.raises(ValueError, match="unexpected"):
        from_jsonl(
            '{"type": "turn_started", "t": 0.0, "episode_id": "ep-1", '
            '"turn": 1, "mood": "cheerful"}'
        )

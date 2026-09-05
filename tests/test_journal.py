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
    ExecutionFailed,
    JOURNAL_SCHEMA,
    OUTCOMES,
    RECORD_TYPES,
    EpisodeClock,
    EpisodeFinished,
    EpisodeStarted,
    ModelCalled,
    Observation,
    Snapshot,
    StopRequested,
    SubscriberFailed,
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
            t=1.86,
            episode_id="ep-1",
            turn=1,
            tool="speak",
            # Non-ASCII and a nested structure on purpose: goldens will carry
            # Chinese speech, and a fixture of empty dicts and plain ASCII
            # cannot tell a stable encoding from an unstable one.
            args={"text": "你好，我過來一點", "options": {"pitch": 1.0}},
        ),
        Observation(
            t=6.9,
            episode_id="ep-1",
            turn=1,
            result={"result": "arrived", "steps": 2},
            snapshot=Snapshot(
                distance_cm=63, face_present=True, new_speech=None
            ),
        ),
        ToolRejected(
            t=7.0,
            episode_id="ep-1",
            turn=2,
            tool="move_head",
            reason="pitch 999 is outside the permitted range",
        ),
        StopRequested(t=7.4, episode_id="ep-1", source="foot_bumper"),
        ExecutionFailed(
            t=7.42,
            episode_id="ep-1",
            phase="tool",
            error_type="RuntimeError",
            message="the motor controller did not answer",
        ),
        SubscriberFailed(
            t=7.45,
            episode_id="ep-1",
            subscriber="TerminalRenderer",
            failed_on="stop_requested",
            error="the renderer fell over",
        ),
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


# ---------------------------------------------------------------------------
# The gaps review found: every one of these mutations used to pass
# ---------------------------------------------------------------------------

def test_elapsed_time_keeps_moving_when_asked_more_than_once():
    """Nothing here used to call `elapsed_s` twice on one instance.

    The loop calls it once per record. A clock that cached its first answer
    would freeze every `t` in the Journal at zero and the whole file stayed
    green.
    """
    clock = FakeClock()
    episode = EpisodeClock(clock)

    first = episode.elapsed_s()
    clock.now += 3.0
    second = episode.elapsed_s()

    assert first == 0.0
    assert second == pytest.approx(3.0)


def test_every_line_ends_with_a_newline_so_journals_can_be_appended():
    """`splitlines` is blind to a missing trailing newline.

    Ticket 02 appends one record at a time. Without the final newline the next
    append fuses two records onto one line, and the file stops being JSONL.
    """
    text = to_jsonl(one_of_each())

    assert text.endswith("\n")
    assert to_jsonl(one_of_each()[:1]) + to_jsonl(one_of_each()[1:]) == text


def test_keys_are_written_in_a_stable_order():
    """Ticket 03 compares goldens byte for byte.

    Dictionary order is insertion order, and the loop builds payloads from
    whatever the model returned. Sorting is what makes two runs of the same
    Episode produce the same bytes.
    """
    scrambled = Observation(
        t=1.0,
        episode_id="ep-1",
        turn=1,
        result={"zebra": 1, "apple": 2},
        snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
    )
    ordered = Observation(
        t=1.0,
        episode_id="ep-1",
        turn=1,
        result={"apple": 2, "zebra": 1},
        snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
    )

    assert to_jsonl([scrambled]) == to_jsonl([ordered])


def test_non_ascii_is_written_as_itself_not_as_escapes():
    """Goldens will carry Chinese speech, and a reader has to be able to read them."""
    text = to_jsonl(one_of_each())

    assert "你好" in text
    assert "\\u4f60" not in text


def test_the_schema_version_is_the_default_not_something_the_caller_supplies():
    """The fixture passes `schema=` explicitly, so it was testing itself."""
    opening = EpisodeStarted(
        t=0.0,
        episode_id="ep-1",
        trigger="speech",
        started_at_wall_clock="2026-08-24T11:00:00+08:00",
    )

    assert opening.schema == JOURNAL_SCHEMA
    assert "unstable" in opening.schema


# ---------------------------------------------------------------------------
# The layering claim, guarded where it can actually be broken
# ---------------------------------------------------------------------------

def test_a_tool_call_cannot_carry_a_drive_command():
    """The realistic leak, and the one the first two guards could not see.

    `args` is a free-form mapping filled in by later tickets. Scanning declared
    field names and a fixture of empty dicts left `ToolCalled(tool="approach",
    args={"linearVelocity": 20, "timeMs": 1500})` serialising cleanly with
    every test green — while `PLAN.md` §4's central design claim is exactly
    that such a thing cannot reach the model.
    """
    for leak in ({"linearVelocity": 20}, {"timeMs": 1500}, {"time_ms": 1500}):
        with pytest.raises(ValueError, match="control parameter"):
            ToolCalled(
                t=0.0, episode_id="ep-1", turn=1, tool="approach", args=leak
            )


def test_the_leak_guard_reaches_into_nested_arguments():
    with pytest.raises(ValueError, match="control parameter"):
        ToolCalled(
            t=0.0,
            episode_id="ep-1",
            turn=1,
            tool="approach",
            args={"options": {"linearVelocity": 20}},
        )


def test_an_execution_failure_cannot_repeat_a_drive_parameter():
    with pytest.raises(ValueError, match="failure may not say"):
        ExecutionFailed(
            t=0.0,
            episode_id="ep-1",
            phase="tool",
            error_type="RuntimeError",
            message="driveDuration failed",
        )


def test_an_observation_result_cannot_carry_a_drive_command_either():
    with pytest.raises(ValueError, match="control parameter"):
        Observation(
            t=0.0,
            episode_id="ep-1",
            turn=1,
            result={"timeMs": 1500},
            snapshot=Snapshot(
                distance_cm=60, face_present=True, new_speech=None
            ),
        )


def test_a_duration_the_model_chose_is_refused_in_arguments():
    """`tool_called` is the model commanding, so a duration there is driving.

    Not covered by the three spellings above: those are refused whichever
    direction they travel, so they cannot tell whether this record screens as
    commanded or as reported. This one can — it is allowed in a result.
    """
    with pytest.raises(ValueError, match="control parameter|duration"):
        ToolCalled(
            t=0.0, episode_id="ep-1", turn=1, tool="speak", args={"wait_seconds": 3}
        )


def test_a_duration_the_system_measured_is_allowed_in_a_result():
    """The other half of the direction, and the goldens depend on it.

    `PLAN.md` §15.4's suppression window is `estimated_speech_ms`, and
    `episode_ends_after_several_turns.jsonl` carries it in an Observation. A
    guard that refused it would fail every golden.
    """
    record = Observation(
        t=0.0,
        episode_id="ep-1",
        turn=1,
        result={"estimated_speech_ms": 1409, "ok": True},
        snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
    )

    assert record.result["estimated_speech_ms"] == 1409


def test_ordinary_arguments_still_pass():
    # The negative control. A guard that rejected everything would satisfy the
    # three tests above.
    ToolCalled(
        t=0.0,
        episode_id="ep-1",
        turn=1,
        tool="move_head",
        args={"pitch": 10, "yaw": -5},
    )


# ---------------------------------------------------------------------------
# Round-trip, for real payloads
# ---------------------------------------------------------------------------

def test_a_value_that_would_not_survive_json_is_refused_at_construction():
    """A tuple comes back as a list and breaks a golden comparison silently."""
    with pytest.raises(ValueError, match="survive JSON"):
        ToolCalled(
            t=0.0,
            episode_id="ep-1",
            turn=1,
            tool="move_arms",
            args={"angles": (10, 20)},
        )


def test_nested_and_non_ascii_payloads_round_trip():
    records = one_of_each()

    assert from_jsonl(to_jsonl(records)) == tuple(records)


# ---------------------------------------------------------------------------
# Episode endings
# ---------------------------------------------------------------------------

def test_an_episode_ends_with_one_of_the_named_outcomes():
    with pytest.raises(ValueError, match="unknown outcome"):
        EpisodeFinished(
            t=1.0, episode_id="ep-1", outcome="probably_fine", turns=1, steps=0
        )


def test_the_named_outcomes_cover_the_goldens_and_involuntary_failure():
    """Four golden scenarios share three intentional outcomes; errors add one.

    Worth writing down, because "four ways an Episode ends" reads like four
    outcomes and ticket 03 names four files. Runtime failure is deliberately
    not retrofitted into a golden that predates the closure work.
    """
    assert set(OUTCOMES) == {"done", "turn_limit", "aborted", "error"}


def test_there_is_exactly_one_kind_of_terminal_record():
    """So that "an Episode ends exactly once" is something you can count.

    An earlier version also had an `EpisodeAborted`, whose only payload
    duplicated the reason already on `StopRequested` — three records for one
    ending.
    """
    terminal = [
        name for name in RECORD_TYPES if name.startswith("episode_")
    ]

    assert sorted(terminal) == ["episode_finished", "episode_started"]


def test_a_stop_request_and_the_ending_it_causes_are_separate_records():
    """The gap between them is the interrupt latency ticket 08 has to show.

    One record would make that gap unobservable; it is also why writing takes
    a lock instead of queueing for the main loop (`PLAN.md` §15.3).
    """
    requested = StopRequested(t=7.4, episode_id="ep-1", source="foot_bumper")
    finished = EpisodeFinished(
        t=7.6, episode_id="ep-1", outcome="aborted", turns=2, steps=2
    )

    assert finished.t - requested.t == pytest.approx(0.2)

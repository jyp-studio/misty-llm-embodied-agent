"""Writing a Journal: the lock, the subscribers, and when `t` is taken.

Ticket 01 made records and text. This is the part that runs while an Episode
does, so it has the concurrency to answer for.

The property this file exists to protect is the one that decided the design
(`PLAN.md` §15.3): **`t` is when the event happened, not when the writer got
round to it.** An emergency stop arrives on another thread; if its record were
stamped after waiting for the lock, the gap between the request and the
Episode unwinding would measure the lock instead of the interrupt, and ticket
08's whole claim would be about the wrong thing.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from misty_agent.agent.journal import (
    EpisodeFinished,
    EpisodeStarted,
    Journal,
    JsonlFile,
    Snapshot,
    Observation,
    StopRequested,
    TerminalRenderer,
    ToolCalled,
    TurnStarted,
    from_jsonl,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class Collector:
    """A subscriber that keeps what it was given."""

    def __init__(self) -> None:
        self.records = []

    def receive(self, record) -> None:
        self.records.append(record)


class Exploding:
    def receive(self, record) -> None:
        raise RuntimeError("the renderer fell over")


class AssumesItIsAlone:
    """A subscriber written as if it were never called concurrently.

    That assumption is precisely what the Journal's lock buys, and it is the
    only way to detect the lock from outside. Counting lines in the output
    file cannot: one small `write` is atomic to the OS and `list.append` is
    atomic under the GIL, so a Journal with no lock at all produces exactly
    the same file. The first version of this suite checked the file and
    proved nothing — removing the lock left every test green.
    """

    def __init__(self) -> None:
        self._depth = 0
        self.overlaps = 0
        self.seen = 0

    def receive(self, record) -> None:
        self._depth += 1
        if self._depth > 1:
            self.overlaps += 1
        # Wide enough that an unlocked writer will certainly overlap, short
        # enough that the suite stays fast.
        time.sleep(0.001)
        self.seen += 1
        self._depth -= 1


# ---------------------------------------------------------------------------
# Stamping
# ---------------------------------------------------------------------------

def test_the_journal_stamps_the_time_so_callers_cannot_get_it_wrong():
    clock = FakeClock()
    journal = Journal("ep-1", clock=clock)

    clock.now = 2.5
    record = journal.record(TurnStarted, turn=1)

    assert record.t == pytest.approx(2.5)
    assert record.episode_id == "ep-1"


def test_the_first_record_of_an_episode_is_at_zero():
    clock = FakeClock()
    clock.now = 987.0
    journal = Journal("ep-1", clock=clock)

    assert journal.record(TurnStarted, turn=1).t == 0.0


def test_the_time_is_taken_before_the_lock_not_after_it():
    """The property the whole design turns on.

    A writer that stamped inside the lock would give a record blocked behind
    another thread the time it *finished waiting*, not the time the event
    happened. On the emergency-stop path that is the difference between
    measuring an interrupt and measuring a mutex.
    """
    clock = FakeClock()
    journal = Journal("ep-1", clock=clock)

    holding = threading.Event()
    may_release = threading.Event()

    def hog():
        with journal._lock:  # noqa: SLF001 — the point of the test is the lock
            holding.set()
            may_release.wait(timeout=5)

    hogger = threading.Thread(target=hog)
    hogger.start()
    holding.wait(timeout=5)

    # The stop happens now, while the lock is held elsewhere.
    clock.now = 1.0
    stamped = {}

    def stop():
        stamped["record"] = journal.record(StopRequested, source="foot_bumper")

    stopper = threading.Thread(target=stop)
    stopper.start()

    # Time passes while it waits for the lock.
    clock.now = 9.0
    may_release.set()
    hogger.join(timeout=5)
    stopper.join(timeout=5)

    assert stamped["record"].t == pytest.approx(1.0), (
        "the record was stamped after waiting for the lock, so its time "
        "measures the lock rather than the event"
    )


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

def test_many_threads_writing_at_once_produce_a_readable_file(tmp_path):
    """Not "it works single-threaded". Actually contended, actually checked."""
    path = tmp_path / "episode.jsonl"
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[JsonlFile(path)])

    def write(turn: int):
        for _ in range(20):
            journal.record(TurnStarted, turn=turn)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    text = path.read_text()
    lines = [line for line in text.splitlines() if line.strip()]

    assert len(lines) == 8 * 20
    for line in lines:
        json.loads(line)  # every line whole, none interleaved
    assert len(from_jsonl(text)) == 8 * 20


def test_every_record_reaches_every_subscriber_under_contention():
    first, second = Collector(), Collector()
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[first, second])

    threads = [
        threading.Thread(target=lambda: journal.record(TurnStarted, turn=1))
        for _ in range(30)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(first.records) == 30
    assert len(second.records) == 30


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------

def test_two_subscribers_run_at_once():
    """One subscriber would make the subscription mechanism a fiction.

    `PLAN.md` §4 wants terminal output to be *one renderer among others*; that
    is only true if there is more than one.
    """
    first, second = Collector(), Collector()
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[first, second])

    journal.record(TurnStarted, turn=1)

    assert first.records == second.records
    assert len(first.records) == 1


def test_a_subscriber_that_falls_over_does_not_stop_the_episode():
    """A broken renderer must not strand the robot mid-approach."""
    survivor = Collector()
    journal = Journal(
        "ep-1", clock=FakeClock(), subscribers=[Exploding(), survivor]
    )

    journal.record(TurnStarted, turn=1)

    assert len(survivor.records) == 1


def test_a_subscriber_failure_is_observable_rather_than_swallowed():
    """Silently ignoring it would mean a Journal could be quietly incomplete."""
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[Exploding()])

    journal.record(TurnStarted, turn=1)

    assert len(journal.subscriber_failures) == 1
    failure = journal.subscriber_failures[0]
    assert "Exploding" in failure.subscriber
    assert "fell over" in failure.error


def test_the_file_subscriber_appends_rather_than_rewrites(tmp_path):
    path = tmp_path / "episode.jsonl"
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[JsonlFile(path)])

    journal.record(TurnStarted, turn=1)
    journal.record(TurnStarted, turn=2)

    assert len(from_jsonl(path.read_text())) == 2


# ---------------------------------------------------------------------------
# The terminal renderer
# ---------------------------------------------------------------------------

def a_few_records(journal):
    journal.record(
        EpisodeStarted,
        trigger="speech",
        started_at_wall_clock="2026-08-24T11:00:00+08:00",
    )
    journal.record(TurnStarted, turn=1)
    journal.record(ToolCalled, turn=1, tool="approach", args={})
    journal.record(
        Observation,
        turn=1,
        result={"result": "arrived", "steps": 2},
        snapshot=Snapshot(distance_cm=63, face_present=True, new_speech=None),
    )
    journal.record(
        EpisodeFinished, outcome="done", turns=1, steps=2
    )


def test_the_terminal_renderer_writes_something_a_person_would_read():
    lines = []
    journal = Journal(
        "ep-1", clock=FakeClock(), subscribers=[TerminalRenderer(lines.append)]
    )

    a_few_records(journal)
    text = "\n".join(lines)

    assert "approach" in text
    assert "arrived" in text


def test_the_terminal_renderer_is_not_a_field_dump():
    """If it printed every field it would be the JSONL with worse punctuation.

    The point of two subscribers is that they answer different questions.
    """
    lines = []
    journal = Journal(
        "ep-1", clock=FakeClock(), subscribers=[TerminalRenderer(lines.append)]
    )

    a_few_records(journal)
    text = "\n".join(lines)

    assert "episode_id" not in text
    assert "ep-1" not in text, "the id is the same on every line; it is noise"
    assert '"type"' not in text


def test_the_terminal_renderer_shows_how_the_episode_ended():
    lines = []
    journal = Journal(
        "ep-1", clock=FakeClock(), subscribers=[TerminalRenderer(lines.append)]
    )

    a_few_records(journal)

    assert any("done" in line for line in lines)


# ---------------------------------------------------------------------------
# What the journal holds
# ---------------------------------------------------------------------------

def test_the_journal_keeps_what_it_recorded_in_order():
    journal = Journal("ep-1", clock=FakeClock())

    a_few_records(journal)

    assert [record.type for record in journal.records] == [
        "episode_started",
        "turn_started",
        "tool_called",
        "observation",
        "episode_finished",
    ]


def test_a_journal_can_be_rendered_to_text_without_a_file_subscriber():
    journal = Journal("ep-1", clock=FakeClock())

    a_few_records(journal)

    assert len(from_jsonl(journal.to_jsonl())) == 5


def test_a_subscriber_is_never_called_by_two_threads_at_once():
    """What the lock is actually for, and the only way to see it from outside.

    A subscriber may assume it is alone — that is the contract the lock
    provides, and it is why a renderer or a file handle does not have to be
    thread-safe on its own.
    """
    alone = AssumesItIsAlone()
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[alone])

    threads = [
        threading.Thread(target=lambda: journal.record(TurnStarted, turn=1))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert alone.overlaps == 0, "two threads were inside a subscriber at once"
    assert alone.seen == 8, "an update was lost to a race"

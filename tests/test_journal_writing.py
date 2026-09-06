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
    TONES,
    Described,
    EpisodeFinished,
    EpisodeStarted,
    ExecutionFailed,
    Journal,
    JsonlFile,
    ModelCalled,
    Observation,
    Record,
    Snapshot,
    StopRequested,
    SubscriberFailed,
    TerminalRenderer,
    ToolCalled,
    ToolRejected,
    TurnStarted,
    describe,
    describe_line,
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


class BlocksUntilReleased:
    """A subscriber that hangs, so contention can be created through the seam.

    Subscribers are fanned out under the Journal's lock, so one that refuses
    to return is the only way to make another thread wait using nothing but
    the public interface.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.may_leave = threading.Event()

    def receive(self, record) -> None:
        self.entered.set()
        self.may_leave.wait(timeout=5)


def test_the_time_is_taken_when_the_event_happened_not_when_the_writer_got_to_it():
    """The property the whole design turns on.

    A writer that stamped after waiting would give a record blocked behind
    another thread the time it *finished waiting*. On the emergency-stop path
    that is the difference between measuring an interrupt and measuring a
    mutex.

    The first version of this test was a fiction: it reached into
    `journal._lock`, discarded the result of its own `wait`, and stayed green
    when the lock was renamed **or removed entirely** — because contention
    never happened and the assertion held vacuously. This one contends through
    the public seam and asserts that it managed to.
    """
    clock = FakeClock()
    blocker = BlocksUntilReleased()
    journal = Journal("ep-1", clock=clock, subscribers=[blocker])

    holder = threading.Thread(
        target=lambda: journal.record(TurnStarted, turn=1)
    )
    holder.start()
    assert blocker.entered.wait(timeout=5), "the blocker never got called"

    # The stop happens now, while the writer is stuck in a subscriber.
    clock.now = 1.0
    stamped = {}
    stopper = threading.Thread(
        target=lambda: stamped.update(
            record=journal.record(StopRequested, source="foot_bumper")
        )
    )
    stopper.start()

    stopper.join(timeout=0.3)
    assert stopper.is_alive(), (
        "no contention was created, so this test would pass with no lock at all"
    )

    # Time passes while it waits.
    clock.now = 9.0
    blocker.may_leave.set()
    holder.join(timeout=5)
    stopper.join(timeout=5)

    assert stamped["record"].t == pytest.approx(1.0), (
        "the record was stamped after waiting, so its time measures the wait "
        "rather than the event"
    )


def test_the_journal_knows_what_happened_even_while_a_subscriber_hangs():
    """The record lands in memory before the fan-out, not after.

    A subscriber that never returns must not also stop the Journal from having
    recorded the thing. Two locks rather than one is what buys this.
    """
    clock = FakeClock()
    blocker = BlocksUntilReleased()
    journal = Journal("ep-1", clock=clock, subscribers=[blocker])

    holder = threading.Thread(
        target=lambda: journal.record(TurnStarted, turn=1)
    )
    holder.start()
    assert blocker.entered.wait(timeout=5)

    assert [record.type for record in journal.records] == ["turn_started"]

    blocker.may_leave.set()
    holder.join(timeout=5)


def test_a_subscriber_may_record_something_of_its_own_without_deadlocking():
    """`PLAN.md` §4 invites this by calling terminal output one renderer among
    others — a renderer that wanted to note something of its own.

    An earlier version of this test had the subscriber merely *read*
    `journal.records`, which takes a different lock and so would not deadlock
    however the fan-out lock was declared. Reverting the reentrant lock left
    it green. Recording is the case that actually needs re-entry.
    """

    class NotesSomething:
        def __init__(self) -> None:
            self.noted = False

        def receive(self, record) -> None:
            if record.type == "turn_started" and not self.noted:
                self.noted = True
                journal.record(
                    ToolRejected, turn=1, tool="move_head", reason="just noting"
                )

    subscriber = NotesSomething()
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[subscriber])

    # A daemon, so that if this ever *does* deadlock the assertion below fails
    # and the suite still exits. A test that wedges CI is worse than one that
    # goes red.
    writer = threading.Thread(
        target=lambda: journal.record(TurnStarted, turn=1), daemon=True
    )
    writer.start()
    writer.join(timeout=3)

    assert not writer.is_alive(), "recording from inside a subscriber deadlocked"
    assert [record.type for record in journal.records] == [
        "turn_started",
        "tool_rejected",
    ]


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

    # The record it was called for, and then the notice that its neighbour
    # fell over — the survivor is how that notice reaches anywhere durable.
    assert [record.type for record in survivor.records] == [
        "turn_started",
        "subscriber_failed",
    ]


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


def test_the_terminal_renderer_explains_an_execution_failure():
    lines = []
    renderer = TerminalRenderer(lines.append)

    renderer.receive(
        ExecutionFailed(
            t=1.25,
            episode_id="ep-1",
            phase="perception",
            error_type="RuntimeError",
            message="camera pipeline failed",
        )
    )

    assert lines == [
        "   1.25s    ! perception failed (RuntimeError): camera pipeline failed"
    ]


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


# ---------------------------------------------------------------------------
# What a caller may not set
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reserved", ["t", "episode_id", "type"])
def test_a_caller_cannot_set_the_fields_the_journal_owns(reserved):
    """A record that could name its own type or time could disagree with reality.

    `journal.record(TurnStarted, turn=1, type="episode_finished")` used to be
    accepted, writing a line whose discriminator lied — caught, if at all,
    much later by `from_jsonl`.
    """
    journal = Journal("ep-1", clock=FakeClock())

    with pytest.raises(ValueError, match="belong to the Journal"):
        journal.record(TurnStarted, turn=1, **{reserved: "anything"})


def test_an_episode_that_has_finished_refuses_further_records():
    """"An Episode ends exactly once" was a claim; this makes it a rule.

    Ticket 08 has a stop arriving from another thread, and nothing otherwise
    stops it landing after the ending it caused.
    """
    journal = Journal("ep-1", clock=FakeClock())
    journal.record(EpisodeFinished, outcome="done", turns=1, steps=0)

    with pytest.raises(ValueError, match="already finished"):
        journal.record(StopRequested, source="foot_bumper")


# ---------------------------------------------------------------------------
# The wall clock
# ---------------------------------------------------------------------------

def test_the_journal_stamps_the_wall_clock_so_goldens_can_pin_it():
    """Ticket 03 compares goldens byte for byte, so this cannot be `now()`."""
    journal = Journal(
        "ep-1",
        clock=FakeClock(),
        wall_clock=lambda: "2026-08-25T09:00:00+08:00",
    )

    opening = journal.record(EpisodeStarted, trigger="speech")

    assert opening.started_at_wall_clock == "2026-08-25T09:00:00+08:00"


def test_the_wall_clock_is_only_asked_for_the_opening_record():
    asked = []
    journal = Journal(
        "ep-1",
        clock=FakeClock(),
        wall_clock=lambda: asked.append(1) or "2026-08-25T09:00:00+08:00",
    )

    journal.record(EpisodeStarted, trigger="speech")
    journal.record(TurnStarted, turn=1)

    assert len(asked) == 1


# ---------------------------------------------------------------------------
# Failures reach somewhere durable
# ---------------------------------------------------------------------------

def test_a_subscriber_failure_is_written_into_the_journal_not_only_beside_it(
    tmp_path,
):
    """Keeping failures in memory left the file silently incomplete.

    That is the exact failure this package claims to make impossible, so it
    cannot be the one it commits.
    """
    path = tmp_path / "episode.jsonl"
    journal = Journal(
        "ep-1",
        clock=FakeClock(),
        subscribers=[Exploding(), JsonlFile(path)],
    )

    journal.record(TurnStarted, turn=1)

    kinds = [record.type for record in from_jsonl(path.read_text())]
    assert kinds == ["turn_started", "subscriber_failed"]


def test_a_failure_notice_is_not_sent_back_to_the_subscriber_that_failed():
    """Otherwise a subscriber that always throws loops on its own failures."""
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[Exploding()])

    journal.record(TurnStarted, turn=1)

    assert len(journal.subscriber_failures) == 1
    assert [record.type for record in journal.records] == [
        "turn_started",
        "subscriber_failed",
    ]


# ---------------------------------------------------------------------------
# The terminal renderer, kind by kind
# ---------------------------------------------------------------------------

def render(record_kind, **fields):
    lines = []
    journal = Journal(
        "ep-1", clock=FakeClock(), subscribers=[TerminalRenderer(lines.append)]
    )
    journal.record(record_kind, **fields)
    return lines[0]


def test_the_renderer_says_something_about_a_model_call():
    line = render(ModelCalled, turn=1, latency_ms=1840, tokens_in=12, tokens_out=3)

    assert "1840" in line and "12" in line and "3" in line


def test_the_renderer_says_something_about_a_refused_tool_call():
    line = render(
        ToolRejected, turn=1, tool="move_head", reason="pitch out of range"
    )

    assert "move_head" in line and "pitch out of range" in line


def test_the_renderer_says_something_about_a_stop_request():
    assert "foot_bumper" in render(StopRequested, source="foot_bumper")


def test_the_renderer_says_something_about_a_subscriber_failure():
    lines = []
    journal = Journal(
        "ep-1",
        clock=FakeClock(),
        subscribers=[Exploding(), TerminalRenderer(lines.append)],
    )

    journal.record(TurnStarted, turn=1)

    assert any("Exploding" in line for line in lines)


def test_the_renderer_does_not_invent_a_distance_when_none_was_measured():
    """`Snapshot(distance_cm=None, face_present=True)` used to print "Nonecm"."""
    line = render(
        Observation,
        turn=1,
        result={"result": "arrived"},
        snapshot=Snapshot(
            distance_cm=None, face_present=True, new_speech=None
        ),
    )

    assert "None" not in line
    assert "unknown" in line


def test_the_renderer_is_loud_about_a_kind_it_does_not_know():
    """`from_jsonl` refuses an unknown kind because a dropped line makes a
    truncated Journal look complete. A renderer that silently skipped one
    would be the same lie in a different medium.
    """
    from misty_agent.agent import journal as module

    line = module.describe_line(
        module.Record(t=0.0, episode_id="ep-1", type="telepathy")
    )

    assert "telepathy" in line


def test_the_renderer_shows_the_time_to_a_useful_precision():
    """Whole seconds would round a Turn boundary away."""
    clock = FakeClock()
    lines = []
    journal = Journal(
        "ep-1", clock=clock, subscribers=[TerminalRenderer(lines.append)]
    )

    clock.now = 1.25
    journal.record(TurnStarted, turn=1)

    assert "1.25" in lines[0]


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def test_the_file_is_written_as_utf8_whatever_the_platform_prefers(tmp_path):
    """Goldens carry Chinese speech; a platform default would mangle them."""
    path = tmp_path / "episode.jsonl"
    journal = Journal("ep-1", clock=FakeClock(), subscribers=[JsonlFile(path)])

    journal.record(ToolCalled, turn=1, tool="speak", args={"text": "你好"})

    assert "你好" in path.read_bytes().decode("utf-8")


# ---------------------------------------------------------------------------
# What a record says, apart from how it looks
# ---------------------------------------------------------------------------
#
# Two media read the Journal now: the terminal, and (from M8) a page. Both have
# to answer "what does this record say?" first, and answering it twice is how
# they drift. `describe()` answers it once; `describe_line()` only adds
# punctuation.

#: One of every record kind. Written out rather than generated, because the
#: point is to notice a *new* kind — and a generator would invent one for
#: whatever was added without anybody looking at it.
SAMPLES = {
    "episode_started": EpisodeStarted(
        t=0.0, episode_id="ep-1", trigger="speech",
        started_at_wall_clock="2026-09-06T10:00:00+08:00",
    ),
    "turn_started": TurnStarted(t=0.1, episode_id="ep-1", turn=3),
    "model_called": ModelCalled(
        t=0.2, episode_id="ep-1", turn=3,
        latency_ms=1840, tokens_in=812, tokens_out=11,
    ),
    "tool_called": ToolCalled(
        t=0.3, episode_id="ep-1", turn=3, tool="speak",
        args={"text": "hello"},
    ),
    "tool_rejected": ToolRejected(
        t=0.4, episode_id="ep-1", turn=3, tool="move_head",
        reason="pitch 140 is outside the permitted range",
    ),
    "observation": Observation(
        t=0.5, episode_id="ep-1", turn=3, result={"ok": True},
        snapshot=Snapshot(distance_cm=142, face_present=True, new_speech=None),
    ),
    "stop_requested": StopRequested(
        t=0.6, episode_id="ep-1", source="foot_bumper"
    ),
    "execution_failed": ExecutionFailed(
        t=0.7, episode_id="ep-1", phase="perception",
        error_type="RuntimeError", message="camera pipeline failed",
    ),
    "episode_finished": EpisodeFinished(
        t=0.8, episode_id="ep-1", outcome="done", turns=3, steps=1
    ),
    "subscriber_failed": SubscriberFailed(
        t=0.9, episode_id="ep-1", subscriber="JsonlFile",
        failed_on="observation", error="disk full",
    ),
}


def test_every_record_kind_has_a_sample_here():
    """The guard that makes the rest of this section mean anything.

    Add a record kind without adding it below and every test here still
    passes — while the new kind renders as `?? unrendered`, in both media.
    """
    from misty_agent.agent.journal import RECORD_TYPES

    assert set(SAMPLES) == set(RECORD_TYPES), (
        f"no sample for: {sorted(set(RECORD_TYPES) - set(SAMPLES))}"
    )


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_every_record_kind_is_described(kind):
    said = describe(SAMPLES[kind])

    assert said.headline
    assert "unrendered" not in said.headline, f"{kind} has no description"


def test_an_unknown_kind_is_loud_rather_than_silent():
    """The negative control for the test above: a `describe` that returned a
    plausible sentence for anything would satisfy it."""
    said = describe(Record(t=0.0, episode_id="ep-1", type="telepathy"))

    assert "unrendered" in said.headline
    assert "telepathy" in said.headline


def test_the_kinds_do_not_all_say_the_same_thing():
    """A `describe` that answered "something happened" for every record would
    pass every other test in this section."""
    headlines = {describe(record).headline for record in SAMPLES.values()}

    assert len(headlines) == len(SAMPLES), f"kinds share a headline: {headlines}"


#: Exactly what each kind reads as. Written out, because a wording change
#: should be a deliberate act rather than something that happens.
#:
#: The loose version of this test — "no leading space, no leading `!`" —
#: let fifteen mutations through: swapped headline and detail, a dropped
#: trigger, a `turn` with no number, `speak()` with the spoken text gone,
#: swapped token counts, and every possible nesting mistake. A table of
#: expected lines catches all of them at once, and it is how the golden
#: Journals already work.
LINES = {
    "episode_started": "episode began, woken by speech",
    "turn_started": "turn 3",
    "model_called": "  thought for 1840ms, 812+11 tokens",
    "tool_called": "  speak(text='hello')",
    "tool_rejected": "  move_head refused: pitch 140 is outside the permitted range",
    "observation": "  -> ok, 142cm away",
    "stop_requested": "stop requested by foot_bumper",
    "execution_failed": "  ! perception failed (RuntimeError): camera pipeline failed",
    "episode_finished": "episode done after 3 turn(s), 1 step(s)",
    "subscriber_failed": "  ! JsonlFile failed on observation: disk full",
}


def test_every_kind_has_an_expected_line():
    assert set(LINES) == set(SAMPLES)


@pytest.mark.parametrize("kind", sorted(LINES))
def test_a_record_reads_exactly_this_way(kind):
    assert describe_line(SAMPLES[kind]) == LINES[kind]


def test_describing_a_record_does_not_format_it():
    """The structure is a sentence; the indentation, the markers and the
    punctuation joining its halves belong to whoever is showing it."""
    for kind, record in sorted(SAMPLES.items()):
        said = describe(record)
        assert said.headline == said.headline.strip(), kind
        assert not said.headline.startswith(("!", "->", "?")), kind
        assert not said.headline.endswith((":", ",")), kind
        assert said.detail == said.detail.strip(), kind


def test_tool_arguments_read_in_a_fixed_order():
    """Two Journals of the same Episode must read the same way.

    Argument order in a mapping is insertion order, which is whatever the
    model happened to emit. The single-argument sample above cannot see this:
    sorting one item is sorting nothing.
    """
    said = describe(
        ToolCalled(
            t=1.0, episode_id="ep-1", turn=1, tool="change_led",
            args={"red": 255, "blue": 0, "green": 128},
        )
    )

    assert said.headline == "change_led(blue=0, green=128, red=255)"


def test_the_same_arguments_read_the_same_way_however_they_arrived():
    """The negative control: the test above passes on an unsorted
    implementation whenever the model happens to emit them alphabetically."""
    forwards = describe(
        ToolCalled(
            t=1.0, episode_id="ep-1", turn=1, tool="change_led",
            args={"blue": 0, "green": 128, "red": 255},
        )
    )
    backwards = describe(
        ToolCalled(
            t=1.0, episode_id="ep-1", turn=1, tool="change_led",
            args={"red": 255, "green": 128, "blue": 0},
        )
    )

    assert forwards == backwards


def test_a_record_with_nothing_to_qualify_ends_cleanly():
    """`turn 3`, not `turn 3, `.

    Deleting the empty-detail branch left a trailing separator on every record
    that has no detail — the same shape as the hole this ticket exists to fix,
    at the other end of the line.
    """
    for kind, record in sorted(SAMPLES.items()):
        if describe(record).detail:
            continue
        line = describe_line(record)
        assert not line.endswith((", ", ": ", ",", ":")), (kind, line)


@pytest.mark.parametrize("tone", TONES)
def test_every_tone_is_used_by_some_record(tone):
    """A tone nothing produces is a distinction nobody is making."""
    produced = {describe(record).tone for record in SAMPLES.values()}
    produced.add(describe(Record(t=0.0, episode_id="ep-1", type="telepathy")).tone)

    assert tone in produced


def test_a_tone_that_is_not_a_tone_is_refused():
    """The values are a closed set, like `OUTCOMES`. An int for nesting depth
    invited a `depth=2` that nothing noticed."""
    with pytest.raises(ValueError, match="not one of"):
        Described("something", tone="interesting")


def test_a_refusal_is_not_a_failure():
    """A refusal is the system working — an argument was out of range and
    nothing reached the robot. A failure is the system not working. A page
    should be able to tell them apart without re-deriving the record's class.
    """
    assert describe(SAMPLES["tool_rejected"]).tone == "refused"
    assert describe(SAMPLES["execution_failed"]).tone == "failed"


# ---------------------------------------------------------------------------
# The hole in the sentence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,result",
    [
        ("speak", {"ok": True, "estimated_speech_ms": 1409}),
        ("change_led", {"ok": True}),
        ("move_head", {"ok": True}),
        ("look_around", {"ok": True, "found_at_yaw": -60.0}),
    ],
)
def test_a_tool_with_no_named_outcome_still_reads_as_a_sentence(tool, result):
    """The defect this whole section exists for.

    Only `approach` reports a named outcome. Reading the missing key as an
    empty string printed `-> , 52cm away` — a sentence with a hole where its
    subject should be. Nothing went red, because the tests assert on the
    Journal and not on what is shown.
    """
    line = describe_line(
        Observation(
            t=1.0, episode_id="ep-1", turn=1, result=result,
            snapshot=Snapshot(distance_cm=52, face_present=True, new_speech=None),
        )
    )

    assert ", 52cm away" in line
    assert ",  " not in line
    assert not line.strip().startswith(","), line
    assert "ok" in line


@pytest.mark.parametrize("outcome", ["arrived", "lost_user", "timeout", "drive_error"])
def test_approach_still_reads_its_own_four_states(outcome):
    """The negative control: answering "ok" for everything would fix the hole
    and lose the one Tool that has something to say."""
    line = describe_line(
        Observation(
            t=1.0, episode_id="ep-1", turn=1,
            result={"result": outcome, "steps": 1},
            snapshot=Snapshot(distance_cm=97, face_present=True, new_speech=None),
        )
    )

    assert outcome in line
    assert "97cm away" in line


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"result": "arrived", "steps": 1}, "arrived"),
        ({"ok": True}, "ok"),
        ({"ok": True, "estimated_speech_ms": 1409}, "ok"),
        ({"ok": False}, "returned"),
        ({}, "returned"),
        ({"steps": 0}, "returned"),
    ],
)
def test_every_shape_of_result_still_says_something(result, expected):
    """The headline defect, guarded on every path rather than one.

    The first version tested only `ok: True`, so replacing the fallback with
    an empty string survived — and rendered `  -> , 52cm away`, byte for byte
    the bug this ticket exists to fix. `ok: False` and a result with neither
    key are the paths that were open.
    """
    said = describe(
        Observation(
            t=1.0, episode_id="ep-1", turn=1, result=result,
            snapshot=Snapshot(distance_cm=52, face_present=True, new_speech=None),
        )
    )

    assert said.headline == expected


def test_no_result_ever_leaves_a_hole_in_the_sentence():
    """Whatever comes back, the line has a subject."""
    for result in ({"ok": True}, {"ok": False}, {}, {"steps": 3}, {"result": "x"}):
        line = describe_line(
            Observation(
                t=1.0, episode_id="ep-1", turn=1, result=result,
                snapshot=Snapshot(
                    distance_cm=52, face_present=True, new_speech=None
                ),
            )
        )
        assert ", 52cm away" in line
        assert "-> ," not in line, line
        assert not line.replace("->", "").strip().startswith(","), line


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        (Snapshot(distance_cm=142, face_present=True, new_speech=None), "142cm away"),
        (Snapshot(distance_cm=None, face_present=True, new_speech=None),
         "someone there, distance unknown"),
        (Snapshot(distance_cm=None, face_present=False, new_speech=None),
         "nobody in view"),
    ],
)
def test_what_was_in_view_is_said_three_different_ways(snapshot, expected):
    """Three states, three sentences.

    "Nobody there" and "there but I cannot measure them" are different facts
    and the model is told them differently — so a reader should be told them
    differently too. Nothing covered the absent case, so a description that
    never said "nobody in view" passed.
    """
    said = describe(
        Observation(
            t=1.0, episode_id="ep-1", turn=1, result={"ok": True},
            snapshot=snapshot,
        )
    )

    assert said.detail == expected


def test_an_ordinary_record_is_not_marked_as_a_failure():
    """The negative control for the marker: prefixing every line with `!`
    would satisfy the failure test and make the whole Journal look broken."""
    for kind, record in sorted(SAMPLES.items()):
        line = describe_line(record)
        if kind in ("execution_failed", "subscriber_failed"):
            assert "! " in line, kind
        else:
            assert "!" not in line, kind

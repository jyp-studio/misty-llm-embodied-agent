"""What survives an Episode, and what must not be mistaken for it.

`PLAN.md` §15.5 replaced the old three-tier memory rather than moving it. The
tests below are arranged around the three claims that replacement makes:

**Exchanges are the only thing that is true.** Summary and facts are derived,
and nothing is ever dropped — so a bad summary is a bad derivative, not lost
evidence. The old deque deleted what it folded.

**"The last few" costs nothing.** A slice, no model, no I/O. `PLAN.md` §14.6
lists five window checks that M6 deleted along with the old runner; here they
run in microseconds and need no fake OpenAI client, which is the point of the
redesign.

**Deriving happens once per Episode, at its edge.** Under ReAct one Episode is
many Turns but only one thing the subject said, so per-Turn extraction pays a
model call to ask about a record that has not changed. The counting doubles
below are what makes "once" checkable rather than asserted.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from misty_agent.agent.memory import (
    MEMORY_SCHEMA,
    NO_MEMORY,
    Exchange,
    Memory,
)


class CountingSummariser:
    def __init__(self, text="a summary") -> None:
        self.calls = 0
        self.seen = []
        self._text = text

    def summarise(self, existing, exchanges):
        self.calls += 1
        self.seen.append((existing, tuple(exchanges)))
        return self._text


class CountingExtractor:
    def __init__(self, facts=None) -> None:
        self.calls = 0
        self.seen = []
        self._facts = facts if facts is not None else {"name": "Ana"}

    def extract(self, known, exchanges):
        self.calls += 1
        self.seen.append((dict(known), tuple(exchanges)))
        return self._facts


class Explodes:
    def summarise(self, existing, exchanges):
        raise RuntimeError("the summariser timed out")

    def extract(self, known, exchanges):
        raise RuntimeError("the extractor timed out")


def a_memory(**kwargs):
    kwargs.setdefault("summariser", CountingSummariser())
    kwargs.setdefault("extractor", CountingExtractor())
    return Memory(**kwargs)


def some(count, offset=0):
    return [Exchange(said=f"said {i}", replied=f"replied {i}")
            for i in range(offset, offset + count)]


# ---------------------------------------------------------------------------
# Append-only is the whole design
# ---------------------------------------------------------------------------

def test_remembering_keeps_everything_in_order():
    memory = a_memory(window=2, fold_size=1)

    for exchange in some(5):
        memory.remember(exchange)

    assert [e.said for e in memory.exchanges] == [f"said {i}" for i in range(5)]


def test_folding_summarises_without_deleting():
    """The one thing the old deque got wrong.

    It dropped what it folded, so a summary that lost a detail lost it for
    good. Here folding moves a reading position; the words stay.
    """
    memory = a_memory(window=2, fold_size=1)

    for exchange in some(4):
        memory.remember(exchange)
    memory.close_episode()

    assert len(memory.exchanges) == 4
    assert memory.summary


def test_nothing_is_ever_rewritten():
    memory = a_memory(window=2, fold_size=1)
    memory.remember(Exchange(said="hello", replied="hi"))
    before = memory.exchanges

    for exchange in some(4, offset=1):
        memory.remember(exchange)
    memory.close_episode()

    assert memory.exchanges[: len(before)] == before


# ---------------------------------------------------------------------------
# The slice is a pure function
# ---------------------------------------------------------------------------

def test_recent_returns_the_last_window_and_nothing_else():
    memory = a_memory(window=3)

    for exchange in some(10):
        memory.remember(exchange)

    assert [e.said for e in memory.recent()] == ["said 7", "said 8", "said 9"]


def test_recent_is_bounded_by_the_window():
    memory = a_memory(window=4)

    for exchange in some(50):
        memory.remember(exchange)

    assert len(memory.recent()) == 4


def test_recent_asks_no_model():
    """`PLAN.md` §14.6's window checks used to need a fake OpenAI client.

    Building the memory with no summariser and no extractor at all is the
    strongest form of this: if reading the window touched either, this would
    raise rather than fail.
    """
    memory = Memory(window=3, summariser=None, extractor=None)

    for exchange in some(10):
        memory.remember(exchange)

    assert len(memory.recent()) == 3
    assert memory.as_prompt_block()


def test_remembering_asks_no_model_either():
    """The write path is on the way back to listening. A model call here would
    sit between the subject speaking and the robot being ready again."""
    summariser, extractor = CountingSummariser(), CountingExtractor()
    memory = Memory(summariser=summariser, extractor=extractor, window=1, fold_size=1)

    for exchange in some(20):
        memory.remember(exchange)

    assert summariser.calls == 0
    assert extractor.calls == 0


def test_a_narrower_window_shows_fewer():
    """The window is the only thing that sets how many are shown.

    `recent()` used to take a `count` nothing called, which is the
    Speculative Generality `PLAN.md` §15.23 deleted `instructions=` for.
    """
    wide, narrow = a_memory(window=6), a_memory(window=2)

    for exchange in some(6):
        wide.remember(exchange)
        narrow.remember(exchange)

    assert len(wide.recent()) == 6
    assert len(narrow.recent()) == 2


# ---------------------------------------------------------------------------
# Once per Episode, at its edge
# ---------------------------------------------------------------------------

def test_closing_an_episode_extracts_facts_exactly_once():
    extractor = CountingExtractor()
    memory = Memory(summariser=CountingSummariser(), extractor=extractor, window=6)

    memory.remember(Exchange(said="I am Ana", replied="Hello Ana"))
    memory.close_episode()

    assert extractor.calls == 1
    assert memory.facts["name"] == "Ana"


def test_closing_twice_is_two_boundaries_not_two_turns():
    """`close_episode` is the boundary, and it is the only one.

    Nothing inside an Episode reaches this: the ReAct loop calls `remember`
    once and `close_episode` once, however many Turns it took.
    `tests/test_react.py::test_a_long_episode_derives_memory_exactly_once`
    is the same claim asserted through the loop, which is where it matters.
    """
    summariser, extractor = CountingSummariser(), CountingExtractor()
    memory = Memory(
        summariser=summariser, extractor=extractor, window=1, fold_size=1
    )

    memory.remember(Exchange(said="hello", replied="hi"))
    memory.close_episode()

    assert extractor.calls == 1
    assert summariser.calls == 0  # one Exchange has not overflowed a window of 1


def test_two_episodes_derive_twice():
    """The negative control for the test above: a memory that never derived
    would satisfy "exactly once per Episode" by never running at all."""
    extractor = CountingExtractor()
    memory = Memory(summariser=CountingSummariser(), extractor=extractor, window=6)

    memory.remember(Exchange(said="one", replied="a"))
    memory.close_episode()
    memory.remember(Exchange(said="two", replied="b"))
    memory.close_episode()

    assert extractor.calls == 2


def test_extraction_is_only_shown_what_is_new():
    """One Episode adds one Exchange, so that is what there is to learn from.

    Handing over the whole history each time would grow the prompt without
    bound and re-ask about Exchanges every previous Episode already mined.
    """
    extractor = CountingExtractor()
    memory = Memory(summariser=None, extractor=extractor, window=6)

    for index, exchange in enumerate(some(3)):
        memory.remember(exchange)
        memory.close_episode()

    assert extractor.calls == 3
    for call, expected in zip(extractor.seen, ["said 0", "said 1", "said 2"]):
        _, exchanges = call
        assert [e.said for e in exchanges] == [expected]


def test_extraction_is_told_what_is_already_known():
    """Otherwise it re-derives the same facts and cannot revise one."""
    extractor = CountingExtractor({"name": "Ana"})
    memory = Memory(summariser=None, extractor=extractor, window=6)

    memory.remember(Exchange(said="I am Ana", replied="hello"))
    memory.close_episode()
    memory.remember(Exchange(said="my dog is Pip", replied="nice"))
    memory.close_episode()

    known_on_second_call, _ = extractor.seen[1]
    assert known_on_second_call == {"name": "Ana"}


def test_extraction_is_skipped_when_nothing_was_said():
    """A visual trigger costs one model call, not two: there is nothing
    durable to learn about someone who has not spoken."""
    extractor = CountingExtractor()
    memory = Memory(summariser=CountingSummariser(), extractor=extractor, window=6)

    memory.remember(Exchange(said="   ", replied="I see you"))
    memory.close_episode()

    assert extractor.calls == 0


def test_folding_only_happens_once_the_window_overflows():
    summariser = CountingSummariser()
    memory = Memory(summariser=summariser, extractor=None, window=4, fold_size=2)

    for exchange in some(3):
        memory.remember(exchange)
    memory.close_episode()

    assert summariser.calls == 0


def test_a_summariser_that_fails_does_not_lose_the_exchange():
    """A stale summary is a worse memory. A lost Episode is a worse robot."""
    memory = Memory(summariser=Explodes(), extractor=None, window=1, fold_size=1)

    memory.remember(Exchange(said="my dog is called Pip", replied="ok"))
    memory.remember(Exchange(said="and I like tea", replied="ok"))
    memory.close_episode()

    assert len(memory.exchanges) == 2
    assert "Pip" in memory.summary


def test_an_extractor_that_fails_does_not_take_the_episode_with_it():
    memory = Memory(summariser=None, extractor=Explodes(), window=6)

    memory.remember(Exchange(said="I am Ana", replied="hello"))
    memory.close_episode()

    assert len(memory.exchanges) == 1
    assert memory.facts == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_facts_survive_a_reload(tmp_path):
    path = str(tmp_path / "memory.json")
    memory = Memory(
        summariser=CountingSummariser(), extractor=CountingExtractor(),
        window=6, path=path,
    )
    memory.remember(Exchange(said="I am Ana", replied="Hello Ana"))
    memory.close_episode()

    reloaded = Memory(window=6, path=path)
    reloaded.load()

    assert reloaded.facts["name"] == "Ana"


def test_the_exchanges_themselves_survive_a_reload(tmp_path):
    path = str(tmp_path / "memory.json")
    memory = Memory(summariser=None, extractor=None, window=6, path=path)
    for exchange in some(3):
        memory.remember(exchange)
    memory.save()

    reloaded = Memory(window=6, path=path)
    reloaded.load()

    assert [e.said for e in reloaded.exchanges] == ["said 0", "said 1", "said 2"]
    assert reloaded.exchanges == memory.exchanges


def test_the_summary_survives_a_reload(tmp_path):
    path = str(tmp_path / "memory.json")
    memory = Memory(
        summariser=CountingSummariser("earlier, they said things"),
        extractor=None, window=1, fold_size=1, path=path,
    )
    for exchange in some(3):
        memory.remember(exchange)
    memory.close_episode()

    reloaded = Memory(window=1, fold_size=1, path=path)
    reloaded.load()

    assert reloaded.summary == "earlier, they said things"


def test_a_reload_does_not_re_fold_what_was_already_folded(tmp_path):
    """The reading position is part of the dump. Without it, a restart would
    summarise the same Exchanges again and stack the summary on itself.

    Asserted on which Exchanges the summariser is handed after the reload, not
    just on the number in the file — comparing the two `folded` values passes
    when both are zero, which is exactly what dropping the field does.
    """
    path = str(tmp_path / "memory.json")
    memory = Memory(
        summariser=CountingSummariser(), extractor=None,
        window=1, fold_size=1, path=path,
    )
    for exchange in some(3):
        memory.remember(exchange)
    memory.close_episode()

    assert memory.as_data()["folded"] == 1, "nothing was folded to begin with"

    after = CountingSummariser()
    reloaded = Memory(
        summariser=after, extractor=None, window=1, fold_size=1, path=path,
    )
    reloaded.load()
    reloaded.close_episode()

    assert reloaded.as_data()["folded"] == 2
    handed_over = after.seen[0][1]
    assert [e.said for e in handed_over] == ["said 1"], (
        "the reload summarised an Exchange that had already been folded"
    )


def test_a_missing_file_is_an_empty_memory_not_an_error(tmp_path):
    memory = Memory(window=6, path=str(tmp_path / "nothing-here.json"))

    memory.load()

    assert memory.exchanges == ()
    assert memory.facts == {}


def test_the_dump_is_one_object_a_person_can_read(tmp_path):
    path = tmp_path / "memory.json"
    memory = Memory(summariser=None, extractor=None, window=6, path=str(path))
    memory.remember(Exchange(said="hello", replied="hi"))
    memory.save()

    data = json.loads(path.read_text())

    assert data["schema"] == MEMORY_SCHEMA
    assert data["exchanges"] == [{"said": "hello", "replied": "hi"}]


def test_a_save_writes_somewhere_else_first(tmp_path):
    """Atomicity is `os.replace` over a temp file in the *same* directory.

    A rename across filesystems is not atomic, so where the temp file lands
    matters as much as that there is one.
    """
    directory = tmp_path / "nested"
    directory.mkdir()
    path = directory / "memory.json"
    memory = Memory(summariser=None, extractor=None, window=6, path=str(path))
    memory.remember(Exchange(said="hello", replied="hi"))

    seen = {}
    real = os.replace

    def watching(source, target):
        seen["source_dir"] = os.path.dirname(os.path.abspath(source))
        seen["target_existed"] = os.path.exists(target)
        return real(source, target)

    os.replace = watching
    try:
        memory.save()
    finally:
        os.replace = real

    assert seen["source_dir"] == str(directory)
    assert seen["target_existed"] is False


def test_a_save_that_fails_leaves_no_half_written_file(tmp_path):
    """The process can be interrupted by someone's foot (`stop.py`).

    Yesterday's memory is recoverable; half of today's is not.
    """
    path = tmp_path / "memory.json"
    good = Memory(summariser=None, extractor=None, window=6, path=str(path))
    good.remember(Exchange(said="keep me", replied="ok"))
    good.save()

    class Unserialisable:
        pass

    broken = Memory(summariser=None, extractor=None, window=6, path=str(path))
    broken.load()
    broken._facts["oops"] = Unserialisable()

    with pytest.raises(TypeError):
        broken.save()

    assert json.loads(path.read_text())["exchanges"] == [
        {"said": "keep me", "replied": "ok"}
    ]
    assert list(tmp_path.glob("*.tmp")) == []


def test_saving_without_a_path_is_a_no_op():
    """Memory that was never given a file is memory for this session only."""
    memory = Memory(summariser=None, extractor=None, window=6)

    memory.remember(Exchange(said="hello", replied="hi"))
    memory.save()


# ---------------------------------------------------------------------------
# What goes to the model
# ---------------------------------------------------------------------------

def test_the_prompt_block_carries_facts_summary_and_recent_exchanges():
    memory = Memory(
        summariser=CountingSummariser("they talked about dogs"),
        extractor=CountingExtractor({"name": "Ana"}),
        window=1, fold_size=1,
    )
    memory.remember(Exchange(said="I am Ana", replied="Hello Ana"))
    memory.close_episode()
    memory.remember(Exchange(said="my dog is Pip", replied="Nice"))
    memory.close_episode()

    block = memory.as_prompt_block()

    assert "Ana" in block
    assert "they talked about dogs" in block
    assert "my dog is Pip" in block


def test_an_empty_memory_says_nothing_at_all():
    """Not "(no previous interaction)" — an empty string, so the loop can
    decide whether the model is shown anything rather than being handed a
    sentence about nothing."""
    assert Memory(window=6).as_prompt_block() == ""


def test_the_null_memory_remembers_nothing_and_says_nothing():
    NO_MEMORY.remember(Exchange(said="hello", replied="hi"))
    NO_MEMORY.close_episode()

    assert NO_MEMORY.as_prompt_block() == ""


def test_the_null_memory_is_exactly_the_protocol_and_no_more():
    """It carried a `recent()` the protocol does not declare — an extra the
    loop could never call and nothing kept true."""
    from misty_agent.agent.memory import Remembers

    declared = {
        name for name in vars(Remembers)
        if not name.startswith("_") and callable(getattr(Remembers, name, None))
    }
    offered = {
        name for name in vars(type(NO_MEMORY)) if not name.startswith("_")
    }

    assert offered == declared, f"extra: {offered - declared}"


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def test_a_fold_that_folds_nothing_is_refused():
    """A summary that never grew while the record did."""
    with pytest.raises(ValueError, match="never summarise"):
        Memory(window=2, fold_size=0)


@pytest.mark.parametrize("window,fold_size", [(6, 3), (6, 1), (2, 2), (4, 3)])
def test_the_summary_never_covers_what_the_prompt_still_shows(window, fold_size):
    """`PLAN.md` §15.4 refuses to put one fact in front of the model twice,
    and this is the way it happened anyway.

    The first version folded `fold_size` at a time the moment the window
    overflowed — so **at the shipped default** (`window=6, fold_size=3`) two
    Exchanges sat in the summary while `[Recently]` was still printing them
    verbatim. Every configuration, at every length, or the guard means
    nothing.
    """
    summariser = CountingSummariser()

    class Recording:
        def __init__(self):
            self.folded = []

        def summarise(self, existing, exchanges):
            self.folded.extend(e.said for e in exchanges)
            return " ".join(self.folded)

    recording = Recording()
    memory = Memory(
        summariser=recording, extractor=None, window=window, fold_size=fold_size
    )

    for index, exchange in enumerate(some(20)):
        memory.remember(exchange)
        memory.close_episode()

        shown = {e.said for e in memory.recent()}
        overlap = set(recording.folded) & shown
        assert not overlap, (
            f"after {index + 1} Exchanges with window={window} "
            f"fold_size={fold_size}, {sorted(overlap)} is both summarised "
            f"and printed verbatim"
        )


def test_a_batch_of_several_is_folded_as_a_batch():
    """`_folded` advances by what was actually folded, not by one.

    Under the ReAct loop one Episode adds one Exchange, so `foldable` and the
    fold position advance together and a batch is nearly always a single
    Exchange — which makes `+= 1` and `+= len(batch)` indistinguishable there.
    `Memory` is not private to that loop, and a caller that records several
    before closing gets a real batch; then the two differ, and the wrong one
    re-summarises what it already summarised.
    """
    folded = []

    class Recording:
        def summarise(self, existing, exchanges):
            folded.extend(e.said for e in exchanges)
            return " ".join(folded)

    memory = Memory(summariser=Recording(), extractor=None, window=2, fold_size=3)
    for exchange in some(8):
        memory.remember(exchange)
    memory.close_episode()

    assert folded == ["said 0", "said 1", "said 2"]
    assert memory.as_data()["folded"] == 3

    memory.close_episode()
    assert folded == ["said 0", "said 1", "said 2", "said 3", "said 4", "said 5"]


def test_everything_that_leaves_the_window_is_eventually_summarised():
    """The negative control for the test above: never folding at all would
    satisfy it perfectly."""
    recording = []

    class Recording:
        def summarise(self, existing, exchanges):
            recording.extend(e.said for e in exchanges)
            return " ".join(recording)

    memory = Memory(summariser=Recording(), extractor=None, window=3, fold_size=2)
    for exchange in some(12):
        memory.remember(exchange)
        memory.close_episode()

    assert recording == [f"said {i}" for i in range(9)]


def test_nothing_here_reaches_for_a_vector_store():
    """`PLAN.md` §15.5 turned it down on size, and the way that decision stops
    being true is by someone adding an import."""
    source = (
        pathlib.Path(__file__).parent.parent
        / "misty_agent" / "agent" / "memory.py"
    ).read_text().lower()

    for forbidden in ("embedding", "faiss", "chroma", "pinecone", "numpy",
                      "sentence_transformers", "cosine"):
        assert f"import {forbidden}" not in source, forbidden


def test_the_same_thing_said_twice_is_remembered_twice():
    """Append-only is the module's entire thesis.

    A `remember` that skipped a repeat would look like a tidy-up and would
    quietly make the record a summary of itself — and someone saying "hello"
    in two separate Episodes is two interactions, not one.
    """
    memory = a_memory(window=6)
    twice = Exchange(said="hello", replied="hi")

    memory.remember(twice)
    memory.remember(twice)

    assert len(memory.exchanges) == 2


def test_the_prompt_block_puts_the_oldest_context_first():
    """Facts, then the summary, then what was just said.

    Ordering is not decoration: the model reads this top to bottom, and
    burying the last thing the person said under a paragraph of history is
    how it ends up answering the wrong question. Asserted by position, since
    a substring check passes for any arrangement.
    """
    memory = Memory(
        summariser=CountingSummariser("EARLIER"),
        extractor=CountingExtractor({"name": "Ana"}),
        window=1, fold_size=1,
    )
    memory.remember(Exchange(said="I am Ana", replied="Hello Ana"))
    memory.close_episode()
    memory.remember(Exchange(said="LATEST", replied="ok"))
    memory.close_episode()

    block = memory.as_prompt_block()

    assert block.index("Ana") < block.index("EARLIER") < block.index("LATEST")

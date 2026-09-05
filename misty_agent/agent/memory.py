"""What survives an Episode.

`PLAN.md` §15.5 replaced the old three-tier memory rather than moving it. The
old version kept three states that each changed on their own — a deque that
*dropped* its oldest entries when it overflowed, a summary string, and a facts
dict — and folding was destructive: once a Turn had been summarised, the words
were gone.

Here there is **one** thing that is true, and two that are derived from it:

* **Exchanges are append-only.** Nothing is ever dropped or rewritten. A
  summary that turns out to be wrong is a bad derivative, not lost evidence.
* **"The last few" is a slice.** A pure function over a list, no model, no
  I/O — which is why `PLAN.md` §14.6's window checks can run in microseconds
  instead of needing a fake OpenAI client.
* **Summarising and fact extraction happen once per Episode**, at its edge.
  Under ReAct one Episode is many Turns but only one thing the subject said,
  so per-Turn extraction spends a model call and its latency asking about a
  record that has not changed.

## The confusion this file exists to avoid

**The model's message list is not memory.** `CONTEXT.md` reserves *Exchange*
for the durable unit and says so explicitly: the message list is one Episode's
working context and is discarded with it. They are tempting to unify — both
are "the conversation" — and unifying them means either throwing away what
should persist or persisting a wall of Tool-call plumbing nobody will ever
read. `test_memory.py` asserts the plumbing never reaches the file.

## No vector store

§15.5 turned it down on size: an Episode is five to ten seconds and a session
is a few dozen Exchanges. Embedding calls and another dependency would cost
more than scanning a list that fits on a screen.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

#: Bumped when the on-disk shape changes. Like the Journal's, this is not a
#: stability promise before M10 (`PLAN.md` §15.3) — it is so a file written by
#: an older build is recognised as one rather than silently half-read.
MEMORY_SCHEMA = "0.1.0-unstable"


@dataclass(frozen=True)
class Exchange:
    """One thing the subject said and what the robot said back.

    `CONTEXT.md`'s definition, and the only unit memory is made of. Text only:
    frames never enter memory, which is a token-cost decision the old script
    got right and is worth keeping.
    """

    said: str
    replied: str

    def as_dict(self) -> Dict[str, str]:
        return asdict(self)


class Summariser(Protocol):
    """Folds older Exchanges into a running summary. One model call."""

    def summarise(self, existing: str, exchanges: Sequence[Exchange]) -> str: ...


class FactExtractor(Protocol):
    """Pulls durable facts about the subject out of what was just said."""

    def extract(
        self, known: Mapping[str, str], exchanges: Sequence[Exchange]
    ) -> Mapping[str, str]: ...


class Remembers(Protocol):
    """What the ReAct loop needs of memory, and nothing more."""

    def as_prompt_block(self) -> str: ...

    def remember(self, exchange: "Exchange") -> None: ...

    def close_episode(self) -> None: ...


class RemembersNothing:
    """Memory for a run that should not keep anything.

    A null object rather than an `Optional`, so the ReAct loop reads one shape
    instead of a `None` check at each end of the Episode.
    """

    def as_prompt_block(self) -> str:
        return ""

    def remember(self, exchange: Exchange) -> None:
        return None

    def close_episode(self) -> None:
        return None


NO_MEMORY = RemembersNothing()


class Memory:
    """The append-only record, and the two things derived from it."""

    def __init__(
        self,
        *,
        summariser: Optional[Summariser] = None,
        extractor: Optional[FactExtractor] = None,
        window: int = 6,
        fold_size: int = 3,
        path: Optional[str] = None,
    ) -> None:
        if fold_size < 1:
            raise ValueError(
                f"fold_size={fold_size} would never summarise anything, so "
                f"the summary would stay empty while the record grew"
            )
        self._summariser = summariser
        self._extractor = extractor
        self._window = window
        self._fold_size = fold_size
        self._path = path
        self._exchanges: List[Exchange] = []
        self._summary = ""
        self._facts: Dict[str, str] = {}
        #: How many Exchanges from the front have been folded into the
        #: summary. They are still *there* — this is a reading position, not a
        #: deletion, which is the whole difference from the old deque.
        self._folded = 0

    # ---------- writing ----------

    def remember(self, exchange: Exchange) -> None:
        """Append. No model call, no I/O, nothing derived — that is the point.

        Called once per Episode by the loop. Deriving anything here would put
        a model call on the path between the subject speaking and the robot
        being ready to listen again.
        """
        self._exchanges.append(exchange)

    def close_episode(self) -> None:
        """The one place per Episode where the model is asked anything.

        Both derivations happen here and only here. Either may fail without
        taking the Episode with it: a memory that lost the interaction because
        a summary call timed out would be worse than a memory with a stale
        summary.
        """
        self._extract()
        self._fold()
        self.save()

    # ---------- reading ----------

    def recent(self) -> Tuple[Exchange, ...]:
        """The last window of Exchanges, verbatim. A slice and nothing else.

        No `count` argument: the window is the window, and a parameter with no
        caller is the Speculative Generality `PLAN.md` §15.23 deleted
        `instructions=` for.
        """
        return tuple(self._exchanges[-self._window :])

    @property
    def exchanges(self) -> Tuple[Exchange, ...]:
        """Everything, oldest first. Never shortened."""
        return tuple(self._exchanges)

    @property
    def summary(self) -> str:
        return self._summary

    @property
    def facts(self) -> Dict[str, str]:
        return dict(self._facts)

    def as_prompt_block(self) -> str:
        """What the model is told about earlier interactions.

        Facts, then the summary of what has been folded, then the recent
        Exchanges verbatim. Nothing about Tools, Turns or Observations: those
        belong to one Episode's working context and are gone with it.
        """
        lines: List[str] = []
        if self._facts:
            lines.append("[What is known about the person]")
            lines.extend(f"- {key}: {value}" for key, value in self._facts.items())
        if self._summary:
            lines.append("")
            lines.append("[Earlier, in summary]")
            lines.append(self._summary)
        recent = self.recent()
        if recent:
            lines.append("")
            lines.append("[Recently]")
            for exchange in recent:
                lines.append(f"Them: {exchange.said}")
                lines.append(f"You: {exchange.replied}")
        return "\n".join(lines)

    # ---------- persistence ----------

    def as_data(self) -> Dict[str, Any]:
        """One dump of everything, which is all persistence has to be here."""
        return {
            "schema": MEMORY_SCHEMA,
            "facts": dict(self._facts),
            "summary": self._summary,
            "folded": self._folded,
            "exchanges": [exchange.as_dict() for exchange in self._exchanges],
        }

    def save(self, path: Optional[str] = None) -> None:
        """Write the whole thing, atomically.

        Written to a neighbouring temp file and renamed, because the process
        this runs in can be interrupted by someone's foot (`stop.py`) and a
        half-written memory file is worse than yesterday's.
        """
        target = path or self._path
        if not target:
            return
        directory = os.path.dirname(os.path.abspath(target)) or "."
        handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(self.as_data(), file, ensure_ascii=False, indent=2)
            os.replace(temporary, target)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise

    def load(self, path: Optional[str] = None) -> None:
        """Read a dump back. A missing file is an empty memory, not an error."""
        target = path or self._path
        if not target or not os.path.exists(target):
            return
        with open(target, "r", encoding="utf-8") as file:
            data = json.load(file)
        self._facts = dict(data.get("facts", {}))
        self._summary = data.get("summary", "")
        self._folded = int(data.get("folded", 0))
        self._exchanges = [
            Exchange(said=item.get("said", ""), replied=item.get("replied", ""))
            for item in data.get("exchanges", [])
        ]

    # ---------- the two derivations ----------

    def _extract(self) -> None:
        if self._extractor is None:
            return
        fresh = self._exchanges[-1:]
        if not fresh or not fresh[0].said.strip():
            # Nothing was said, so there is nothing durable to learn. The old
            # script skipped this too, and it is the difference between a
            # visual trigger costing one model call and costing two.
            return
        try:
            found = self._extractor.extract(dict(self._facts), tuple(fresh))
        except Exception:
            # Losing a fact is a worse-memory problem; losing the Episode
            # because a fact call failed is a worse-robot problem.
            return
        if isinstance(found, Mapping):
            self._facts.update(
                {str(key): str(value) for key, value in found.items()}
            )

    def _fold(self) -> None:
        """Summarise what has fallen out of the window — without deleting it.

        Only what has *actually* fallen out. The first version folded
        `fold_size` at a time as soon as the window overflowed, which at the
        default `window=6, fold_size=3` put two Exchanges in the summary while
        `[Recently]` was still printing them verbatim — the model reading the
        same thing twice, which is what `PLAN.md` §15.4 refuses. `fold_size`
        is therefore a *maximum* batch, not an exact one (`PLAN.md` §15.30).
        """
        if self._summariser is None:
            return
        # Everything before this index is outside the window `recent()` shows.
        foldable = len(self._exchanges) - self._window - self._folded
        if foldable <= 0:
            return
        batch = self._exchanges[
            self._folded : self._folded + min(self._fold_size, foldable)
        ]
        if not batch:
            return
        try:
            self._summary = self._summariser.summarise(self._summary, tuple(batch))
        except Exception:
            # Crude, and deliberately so: never lose everything.
            joined = " | ".join(f"{e.said} / {e.replied}" for e in batch)
            self._summary = (self._summary + " | " + joined).strip(" |")[-1500:]
        self._folded += len(batch)

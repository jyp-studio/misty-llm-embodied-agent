"""Each document carries one job, and none of them makes a retired claim.

Ticket 15 asks for the documentation to converge: the architecture note
describes what exists now, the ADRs hold decisions, the glossary holds
language, the handoff holds current progress, and the future work lives in
the spec under `.scratch/`. The failure this guards against is the one this
project has already had — a document left saying the system works a way it
stopped working several tickets ago, in the place a reader would check.

These are shape and claim assertions, not prose review. A document can still
be badly written and pass.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
GLOSSARY = ROOT / "CONTEXT.md"
HANDOFF = ROOT / "HANDOFF.md"
ADRS = sorted((ROOT / "docs" / "adr").glob("*.md"))

#: Every document a reader is pointed at from the README or the handoff.
PROSE = [README, ARCHITECTURE, GLOSSARY, HANDOFF, *ADRS]


def text_of(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


#: Claims that were true of an earlier design and are not true now. Each one
#: names the ticket that retired it, so a reviewer can check rather than
#: trust this list.
RETIRED = {
    # Ticket 01 replaced the one-shot runner with the Attention Loop.
    "perception-plan-act": "the loop is ReAct, not a fixed pipeline",
    "perception, plan, act": "the loop is ReAct, not a fixed pipeline",
    # Ticket 01 again: Episodes are opened by the runtime, not by a person.
    "manually triggered": "the Attention Loop opens Episodes itself",
    "one episode per run": "the runtime runs Episodes until its input ends",
    # Ticket 12 removed cross-Episode memory entirely.
    "remembers them next time": "context is discarded with the Episode",
    "across sessions": "nothing survives a run",
    # The whole effort exists because proactive interaction is in scope.
    "proactive interaction is out of scope": "it is the point of the effort",
}


#: Saying a design is *not* something is the opposite of claiming it, and
#: the ADRs do exactly that: 0001 exists to say the loop is not a fixed
#: perception-plan-action pipeline. A check that could not tell the two
#: apart would make the correct sentence the failing one.
_DENIED = re.compile(
    r"\b(?:not|never|no longer|without|rather than|instead of|stopped|avoid"
    r"|retired|used to|was once|no)\b"
)


def _sentences(text: str):
    return re.split(r"(?<=[.!?])\s+|\n\n+", text)


def asserted_claims(text: str) -> set:
    """Retired claims a document actually makes, denials excluded."""
    lowered = text.lower()
    return {
        claim
        for claim in RETIRED
        if any(
            claim in sentence and not _DENIED.search(sentence)
            for sentence in _sentences(lowered)
        )
    }


@pytest.mark.parametrize("path", PROSE, ids=lambda p: p.name)
def test_no_document_repeats_a_claim_the_code_retired(path):
    made = asserted_claims(text_of(path))

    assert made == set(), (
        f"{path.name} still claims "
        + "; ".join(f"{claim!r} ({RETIRED[claim]})" for claim in sorted(made))
    )


def test_the_retired_claim_check_can_tell_a_claim_from_a_denial():
    """Otherwise it would be green on a document that made every one of
    them, or red on the ADR that exists to rule one out."""
    for claim in RETIRED:
        assert asserted_claims(f"The system is {claim} today.") == {claim}
        assert asserted_claims(f"The system is not {claim} any more.") == set()


@pytest.mark.parametrize(
    "path", [README, ARCHITECTURE, HANDOFF], ids=lambda p: p.name
)
def test_every_document_a_reader_starts_from_says_there_is_no_robot(path):
    """The premise that shapes every technical choice, in each place someone
    might begin reading. A document that omitted it would be the one a
    reader took as evidence about hardware."""
    lowered = text_of(path).lower()

    assert "misty ii" in lowered
    assert any(
        phrase in lowered
        for phrase in ("never", "no misty ii", "hardware-unverified", "unverified")
    )


def test_the_glossary_holds_language_and_not_implementation():
    """Spec: 「glossary 只定義 ubiquitous language，不放實作細節」. A module
    path or a function name in here means the glossary has started tracking
    the code, and it will be the thing that goes stale."""
    glossary = text_of(GLOSSARY)

    for detail in ("misty_agent/", ".py", "def ", "class ", "()"):
        assert detail not in glossary, f"the glossary names {detail!r}"

    #: Its own shape: every entry is a bolded term followed by a definition.
    terms = re.findall(r"^\*\*(.+?)\*\*:$", glossary, re.MULTILINE)
    assert len(terms) >= 15, "the glossary lost its entries"
    assert len(terms) == len(set(terms)), "a term is defined twice"


def test_every_decision_record_records_one_decision():
    """An ADR is a decision and its trade-off, not a manual. These are short
    on purpose: the moment one grows instructions it has become a second
    architecture document and the two will disagree."""
    assert len(ADRS) >= 4

    for adr in ADRS:
        body = text_of(adr)
        assert body.startswith("# "), f"{adr.name} has no title"
        assert len(body.splitlines()) <= 60, f"{adr.name} reads like a manual"
        for instruction in ("pytest", "pip install", ".venv/bin"):
            assert instruction not in body, f"{adr.name} contains {instruction!r}"


def test_the_handoff_says_where_the_work_stands_and_what_is_next():
    """Its one job. If it stops naming a next ticket it has become a
    changelog, which `PLAN.md` already is."""
    handoff = text_of(HANDOFF)

    assert "## Where the work stands" in handoff
    assert "## Next ticket" in handoff

    #: Whatever it points at has to exist. Naming a ticket that was finished
    #: or never written is how a handoff sends the next reader nowhere, and
    #: after the last ticket the honest pointer is not a ticket at all.
    named = re.findall(r"issues/(\d\d)-[-a-z0-9*]*\.md", handoff)
    for number in named:
        matches = list((ROOT / ".scratch" / "social-react-runtime" / "issues").glob(f"{number}-*.md"))
        assert matches, f"the handoff points at issue {number}, which does not exist"
        assert "**Status:** resolved" not in text_of(matches[0]), (
            f"the handoff points at issue {number}, which is already resolved"
        )


def test_the_architecture_note_describes_now_and_points_future_work_elsewhere():
    """It is the current-state document. Future work lives in the spec, so a
    roadmap appearing here is the start of a second one."""
    architecture = text_of(ARCHITECTURE)

    assert ".scratch/social-react-runtime/" in architecture
    for roadmap in ("## Roadmap", "## Future work", "## Planned"):
        assert roadmap not in architecture


def test_the_readme_sends_a_reader_to_each_document_once():
    """The entry point names the others; that is how a reader finds the one
    document that answers their question instead of reading all of them."""
    readme = text_of(README)

    for pointer in ("PLAN.md", "HANDOFF.md", "docs/architecture.md"):
        assert pointer in readme, f"the README never mentions {pointer}"

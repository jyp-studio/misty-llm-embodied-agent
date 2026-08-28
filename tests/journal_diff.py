"""Where two Journals first disagree, as data rather than as a sentence.

A test helper, and it lives in the tests on purpose. `PLAN.md` §15.5 turned
down a fourth reason for the Journal module to change; comparing against a
golden is a testing concern with no production caller, so putting it there
would have been the same mistake in a smaller way.

**The difference is a value, not a string.** An earlier version returned a
formatted message, so every assertion about it could only be a substring
match — and three separate ways of getting the comparison wrong survived that:
reporting the last difference instead of the first, swapping expected and
actual, and naming the record kind while dropping the field. A test that can
only ask "does this text contain 'turn'" cannot tell `turn` the field from
`turn_started` the kind.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Optional, Sequence, Tuple

from misty_agent.agent.journal import Record


@dataclass(frozen=True)
class Difference:
    """One place two Journals disagree.

    `what` says which kind of disagreement, so a caller never has to infer it
    from which of the other fields happen to be set.
    """

    what: str  # "field" | "kind" | "length"
    index: int
    expected: Any
    actual: Any
    kind: Optional[str] = None
    field: Optional[str] = None

    def __str__(self) -> str:
        if self.what == "field":
            return (
                f"record {self.index} ({self.kind}).{self.field}: "
                f"expected {self.expected!r}, got {self.actual!r}"
            )
        if self.what == "kind":
            return (
                f"record {self.index}: expected a {self.expected}, "
                f"got a {self.actual}"
            )
        return (
            f"the journals are {self.index} record(s) long and then differ in "
            f"length: expected {self.expected}, got {self.actual}"
        )


def first_difference(
    expected: Sequence[Record], actual: Sequence[Record]
) -> Optional[Difference]:
    """The first disagreement, or ``None`` if there is none.

    "They are not the same" is not a useful thing to be told about a
    twenty-record Journal. This names the position, the record kind, the field
    and both values — enough to decide, without opening either file, whether
    the code changed or the expectation did.

    Records are compared, not bytes: `PLAN.md` §15.3 makes the types the
    contract and JSONL the serialisation. A golden's *formatting* is pinned
    separately, by round-tripping it.
    """
    for index, (want, got) in enumerate(zip(expected, actual)):
        if want == got:
            continue
        if type(want) is not type(got):
            return Difference(
                what="kind", index=index, expected=want.type, actual=got.type
            )
        for field in fields(want):
            mine, theirs = getattr(want, field.name), getattr(got, field.name)
            if mine != theirs:
                return Difference(
                    what="field",
                    index=index,
                    kind=want.type,
                    field=field.name,
                    expected=mine,
                    actual=theirs,
                )

    if len(expected) != len(actual):
        return Difference(
            what="length",
            index=min(len(expected), len(actual)),
            expected=_kinds(expected),
            actual=_kinds(actual),
        )
    return None


def _kinds(records: Sequence[Record]) -> Tuple[str, ...]:
    return tuple(record.type for record in records)

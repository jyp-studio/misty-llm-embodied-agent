"""The one line the model may not cross, in one place.

`PLAN.md` §4's layering claim is that the model decides *whether* to approach
and the control layer decides *how far* each Step goes. Two artefacts can make
that claim false: a Tool that **declares** a velocity in the schema the model
is handed, and a Journal record that **carries** one. They are the same fact,
so they are one module.

It used to be two — `journal.py` owned a list of spellings and `tools.py`
imported it and re-implemented the matching. `PLAN.md` §10 is about what
happens to two copies of one fact, and §15.5 refused to give the Journal extra
reasons to change for the same reason this module exists: a layering rule is
not a Journal fact, and both modules are its consumers rather than one being
the other's owner.

## Which direction the name is travelling matters

A name is only a *control parameter* when the model is the one choosing it.

**Rates are refused in both directions.** A Tool that takes a velocity lets the
model drive; a result that reports one teaches the model to reason in
velocities, which is the same claim failing one Turn later.

**The drive command's own parameter names are refused in both directions.**
`timeMs` is what Misty's API calls a drive duration. Echoed back to the model
in a result, it teaches the model the same vocabulary the layering claim says
it does not have.

**Any other duration is refused only where the model chooses it.** A Tool that
takes a `wait_seconds` is the model driving. `estimated_speech_ms` in an
Observation is the system reporting a measurement — `PLAN.md` §15.4's
suppression window is built on exactly that number, and `latency_ms` on every
`model_called` record is another. A rule that could not tell those apart would
have to be either useless or wrong, and the first version of this one was
wrong in the useless direction: it rejected two figures that four golden
Journals depend on.

## What counts

Both rules read the name alone. Segments come from underscores *and*
camel-case boundaries, so the two spelling conventions cannot be used to
smuggle one past the other. Requiring a duration unit to be the *last* segment
is what keeps `move_arms` legal — `arms` ends in the letters `ms` without being
a duration.

## What deliberately does not count

Distance. `PLAN.md` §15.2 contemplates giving `approach` a clamped target
distance if "back off a bit" is ever needed, and a clamped target is the
control layer being told *where*, not *how fast*. Blocking it here would
pre-empt a decision §15.2 explicitly left open.

These are name checks, so they are a guard and not a proof: a control
parameter named `intensity` gets through. They stop the spellings anyone would
actually reach for, which is what they are for.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

#: Words that make a name a rate, wherever in the name they appear.
RATE_STEMS: Tuple[str, ...] = (
    "velocity",
    "speed",
    "cmpersec",
    "mmpersec",
    "degpersec",
    "degreespersec",
    "radpersec",
)

#: The drive command's own parameter names, flattened. These are refused
#: wherever they appear: as an argument they are the model driving, and in a
#: result they are the control layer telling the model how it drove.
DRIVE_COMMANDS: Tuple[str, ...] = (
    "timems",
    "drivems",
    "drivetime",
    "driveduration",
    "drivetimems",
)

#: Units that make a name a duration, when the name ends with one.
DURATION_UNITS: Tuple[str, ...] = (
    "ms",
    "msec",
    "msecs",
    "millis",
    "milliseconds",
    "s",
    "sec",
    "secs",
    "second",
    "seconds",
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _segments(name: str) -> Tuple[str, ...]:
    """`driveTimeMs` and `drive_time_ms` are the same three segments."""
    pieces: List[str] = []
    for chunk in name.split("_"):
        pieces.extend(part for part in _CAMEL_BOUNDARY.split(chunk) if part)
    return tuple(piece.lower() for piece in pieces)


def control_parameter(name: str, *, commanded: bool) -> Optional[str]:
    """Why this name crosses the line, or None if it does not.

    `commanded` says which direction the name is travelling: True where the
    model chooses it (a Tool's arguments, a `tool_called` record), False where
    the system reports it back (an Observation's result).

    Returns the reason rather than a bool so callers can say *what* they
    matched on. A message that names the rule is the difference between a Tool
    author fixing the name and a Tool author guessing.
    """
    segments = _segments(name)
    if not segments:
        return None
    flat = "".join(segments)
    for stem in RATE_STEMS:
        if stem in flat:
            return f"{stem!r} makes it a rate"
    if flat in DRIVE_COMMANDS:
        return "it is the drive command's own parameter"
    if commanded and len(segments) > 1 and segments[-1] in DURATION_UNITS:
        return (
            f"it ends in {segments[-1]!r}, which makes it a duration the model "
            f"would be choosing"
        )
    return None


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def mentions_control_parameter(text: str) -> Optional[str]:
    """The first word in `text` that a Tool would not be allowed to declare.

    `control_parameter` reads a name; this reads a sentence, because a name
    can reach the model inside one. A refusal that says "linearVelocity is not
    an argument approach takes" has still told the model the word — and put it
    in the Journal, which is the artefact `PLAN.md` §4's layering claim is
    checked against.

    `commanded=True` throughout: anything appearing in a message *to* the
    model is on the side of the boundary where the model does the choosing.
    """
    words = _WORD.findall(text)
    # Transports may render one identifier as camelCase, snake_case, words,
    # or hyphenated words. Flatten short adjacent spans so punctuation cannot
    # turn a forbidden parameter into an apparently harmless sentence.
    for width in (1, 2, 3):
        for start in range(len(words) - width + 1):
            phrase = words[start : start + width]
            if control_parameter("".join(phrase), commanded=True) is not None:
                return " ".join(phrase)
    return None


def refuse_control_parameters(
    where: str, names: Iterable[str], *, commanded: bool
) -> None:
    """Raise on the first name that crosses the line."""
    for name in names:
        reason = control_parameter(name, commanded=commanded)
        if reason is not None:
            raise ValueError(
                f"{where} may not carry {name!r}: {reason}, and physical "
                f"control parameters belong to the control layer "
                f"(PLAN.md §4)"
            )

"""The Demo's examples: a hosted model's own runs, recorded once and replayed.

## Why recordings and not the scripted runs

The acceptance fixtures carry authored decisions, which is what makes them
tests: the same run every time. Shown to somebody else as "what Misty does",
though, an authored decision is the author's answer, not the model's. So the
Demo plays recordings instead — the fixture's inputs, timing, people and
simulated room, with every decision made by the configured hosted model — and
the scripted path stays where it earns its keep, in `tests/`.

## Why they are files and not a live call

A visitor should see the same run whenever they look, without a key, a bill
or a network. Recording is a deliberate act (`python -m
misty_agent.demo.record`), and each file says which model made it and
when, so a recording can never be mistaken for the model's behaviour today.

The shape is `fixture_payload`'s, shared with the scripted route, so a
recording differs from the tested run only in who decided.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from misty_agent.acceptance import card_named, run_fixture
from misty_agent.agent.react import Model

#: Where the recordings live, next to the page that plays them.
RECORDINGS = pathlib.Path(__file__).resolve().parent / "recordings"

#: Bumped when the document shape changes, so an old file is refused rather
#: than half-drawn.
FORMAT = 1


@dataclass(frozen=True)
class Showcase:
    """One example the Demo offers, and what a visitor should watch for."""

    card: str
    fixture: str
    title: str
    watch_for: str

    @property
    def key(self) -> str:
        return self.fixture


#: The examples, in the order the page offers them. Fewer than the fixtures:
#: the wake-phrase speed variants and the extra visual timelines exercise
#: the local gates, and after the gate they are the same conversation.
#:
#: `b-expires` is deliberately not here. Whether B's request goes stale
#: depends on how long A's Episode takes, and with the model choosing its own
#: Tools that is no longer the fixture's to decide: the first recording of it
#: showed a handoff, which the example beside it already shows. It stays a
#: contract in `misty_agent/acceptance.py`, where the authored decisions make
#: the timing the point.
SHOWCASES: Tuple[Showcase, ...] = (
    Showcase(
        "greeting", "hey-greeting-only", "“Hey Misty”",
        "A wake phrase passes the local gate; then the model decides how to greet.",
    ),
    Showcase(
        "greeting", "visual-gaze-wave", "Someone looks over and waves",
        "No words at all: a sustained look plus a wave forms a Social Invitation.",
    ),
    Showcase(
        "greeting", "visual-passerby", "Someone walks past",
        "They never look at Misty, so it leaves them alone and the model is never called.",
    ),
    Showcase(
        "greeting", "come-closer", "“Come keep me company”",
        "The chassis turns to face them, then closes in step by step.",
    ),
    Showcase(
        "greeting", "come-closer-hazard", "An obstacle on the way",
        "Mid-approach something blocks the path; the base halts at the next checkpoint.",
    ),
    Showcase(
        "greeting", "good-news", "Sharing good news",
        "Face, arms and words should agree — and there is no reason to drive anywhere.",
    ),
    Showcase(
        "greeting", "vague-help", "“I need help”",
        "Too vague to act on: it should ask, then listen, rather than guess.",
    ),
    Showcase(
        "greeting", "question-no-movement", "“What can you do?”",
        "A question that needs an answer, not a demonstration drive.",
    ),
    Showcase(
        "crying-care", "care-sustained-signals", "Signs that someone may be upset",
        "An uncertain Care Cue from face and posture — never a diagnosis.",
    ),
    Showcase(
        "crying-care", "care-expression-words-conflict", "A smile, but they say they are sad",
        "What the person says outranks what their face seems to show.",
    ),
    Showcase(
        "crying-care", "calming-support", "“Please help me calm down”",
        "Loads a Skill on demand, reads its reference, listens, and adapts.",
    ),
    Showcase(
        "crying-care", "respect-boundary", "“I want to be alone”",
        "Stops, stays put, and does not come back uninvited for a while.",
    ),
    Showcase(
        "crying-care", "en-rescue-limits", "“Can you lift this shelf off me?”",
        "It cannot, and must say so — and point at help that can act.",
    ),
    Showcase(
        "crying-care", "zh-emergency-support", "A high-risk moment, in Chinese",
        "Answers in the person's language, stays, and names real help without promising safety.",
    ),
    Showcase(
        "speaker-handoff", "a-then-b", "Two people, one at a time",
        "B waits in the queue; A gets a proper goodbye; B starts with a clean context.",
    ),
)


class NoRecording(LookupError):
    """There is no recording by that name, or it is not one this reads."""


def showcase_named(key: str) -> Showcase:
    found = next((item for item in SHOWCASES if item.key == key), None)
    if found is None:
        raise NoRecording(f"there is no example called {key!r}")
    return found


def path_of(showcase: Showcase, directory: pathlib.Path = RECORDINGS) -> pathlib.Path:
    return directory / f"{showcase.key}.json"


def record(
    showcase: Showcase,
    model: Model,
    *,
    model_name: str,
    today: datetime.date,
) -> dict:
    """Run one example with `model` deciding, and return the document.

    Pure apart from the model: nothing is written here, so a test can record
    with a stand-in and look at the result.
    """
    # Imported here: the demo package imports this module to serve the
    # recordings, and the payload builder lives in the demo package.
    from misty_agent.demo import RunSource, fixture_payload

    card = card_named(showcase.card)
    run = run_fixture(showcase.card, showcase.fixture, model=model)
    source = RunSource(
        "recorded_model_run", model_name, recorded_on=today.isoformat()
    )
    return {
        "format": FORMAT,
        "showcase": asdict(showcase),
        "model": model_name,
        "recorded_on": today.isoformat(),
        "payload": fixture_payload(card, run, source),
    }


def load(key: str, directory: pathlib.Path = RECORDINGS) -> dict:
    """One recording, checked to be the example it claims to be."""
    showcase = showcase_named(key)
    try:
        document = json.loads(path_of(showcase, directory).read_text("utf-8"))
    except FileNotFoundError:
        raise NoRecording(f"{key!r} has not been recorded yet") from None
    if document.get("format") != FORMAT:
        raise NoRecording(f"{key!r} was recorded in a format this does not read")
    if document.get("showcase", {}).get("fixture") != showcase.fixture:
        raise NoRecording(f"{key!r} holds a recording of something else")
    return document


def listing(directory: pathlib.Path = RECORDINGS) -> list:
    """Every example the page offers, with who recorded it and when."""
    entries = []
    for showcase in SHOWCASES:
        try:
            document = load(showcase.key, directory)
        except NoRecording:
            document = None
        card = card_named(showcase.card)
        entries.append(
            {
                **asdict(showcase),
                "key": showcase.key,
                "card_title": card.title,
                "card_subtitle": card.subtitle,
                "recorded": document is not None,
                "model": document["model"] if document else None,
                "recorded_on": document["recorded_on"] if document else None,
            }
        )
    return entries


def _write(document: Mapping[str, Any], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )


def _summary(document: Mapping[str, Any]) -> str:
    episodes = document["payload"]["episodes"]
    if not episodes:
        return "no Episode (the model was not called)"
    parts = []
    for episode in episodes:
        tools = [
            moment["facts"]["tool"]
            for moment in episode["storyboard"]["moments"]
            if moment["kind"] == "tool_called"
        ]
        parts.append(
            f"{episode['actor']}: {' → '.join(tools)} "
            f"[{episode['outcome']['outcome']}]"
        )
    return "; ".join(parts)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Record the examples against the configured hosted model.

    Costs a little money and needs a key; nothing else in the project calls
    this, and the default test suite never does.
    """
    parser = argparse.ArgumentParser(
        prog="python -m misty_agent.demo.record",
        description="Record the Demo's examples with the configured hosted model.",
    )
    parser.add_argument(
        "--only", action="append", metavar="KEY",
        help="record just this example (repeatable)",
    )
    asked = parser.parse_args(argv)

    from misty_agent.agent.model import OpenAIModel
    from misty_agent.app import API_KEY_FILE, load_api_key
    from misty_agent.config import settings

    if not load_api_key(API_KEY_FILE):
        from misty_agent.agent.model import MissingApiKey

        print(MissingApiKey(), file=sys.stderr)
        return 2
    chosen = (
        [showcase_named(key) for key in asked.only] if asked.only else SHOWCASES
    )
    today = datetime.date.today()
    for showcase in chosen:
        # A fresh adapter per example, so nothing about one conversation can
        # reach the next through the client.
        document = record(
            showcase, OpenAIModel(), model_name=settings.llm_model, today=today
        )
        _write(document, path_of(showcase))
        print(f"{showcase.key}: {_summary(document)}", flush=True)
    return 0


__all__ = [
    "FORMAT",
    "NoRecording",
    "RECORDINGS",
    "SHOWCASES",
    "Showcase",
    "listing",
    "load",
    "main",
    "record",
    "showcase_named",
]


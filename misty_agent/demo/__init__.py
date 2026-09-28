"""The demo, as a pure function plus a shell that owns the socket.

`answer(method, path, body)` is everything about HTTP except the socket: a
request in, a status, headers and bytes out. `serve()` is the shell — bind loopback,
open a browser, hand each request to `answer`. The shell is not tested, on the
same grounds `main()` is not: there is nothing in it to get wrong that a test
could see without opening a port.

## No web-framework dependency

`http.server`, `webbrowser`, hand-written HTML. PocketSphinx belongs to the
product's local wake path, not to page rendering; adding a web framework for
one page would still widen the surface for no product capability
(`PLAN.md` §16.4).

## The page replays a whole Journal; nothing streams

An Episode lasts a few seconds, so a page that animates a finished Journal
looks the same as one that streams a running one — and it means the built-in
examples and a real run travel exactly the same path, which removes a whole
mechanism and its seam (`PLAN.md` §16.4).

## The original examples are read from `tests/goldens/`, not copied

A copy could differ from the spec it claims to be, in the one place a visitor
is asked to take the claim seriously. The cost — this package needing a
sibling directory that an installed copy would not have — is weighed in
`PLAN.md` §16.31.

**Four of the five goldens were written before the ReAct loop existed. The fifth was
not.** It was added at M7 #13, to pin `error` once runtime failure became a
named outcome. So provenance is per example and travels *in the payload*
rather than only in the HTML — a claim printed by JavaScript is a claim no
test here can read, which is the hole `storyboard.py` exists to close. Ticket
01 adds a sixth, generated scenario; it crosses `SocialAgentRuntime` before
its Journal reaches that same replay path.
"""

from __future__ import annotations

import base64
import json
import pathlib
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Mapping, Optional, Sequence, Tuple

from misty_agent.agent.journal import (
    DecisionNoted,
    HandoffRequested,
    SkillsAvailable,
    Observation,
    TargetBound,
    ToolCalled,
    describe,
    from_jsonl,
    to_jsonl,
)
from misty_agent.acceptance import (
    ACCEPTANCE_CONTRACTS,
    SCENARIO_CONFIG,
    FixtureRun,
    UnknownFixture,
    contract_for,
    run_fixture,
)
from misty_agent.agent.model import MissingApiKey, OpenAIModel
from misty_agent.config import settings
from misty_agent.agent.storyboard import storyboard_of
from misty_agent.agent.tools import STEPS_KEY
from misty_agent.app import (
    API_KEY_FILE,
    TRIGGERS,
    SystemClock,
    decode_image,
    load_api_key,
    look_at,
    simulated_session,
)
from misty_agent.fakes import FakeClock
from misty_agent.perception.asr import (
    OpenAITranscriber,
    wav_to_pcm,
)
from misty_agent.runtime import (
    AudioAttentionRecorded,
    AttentionStarted,
    AttentionStopped,
    CueDetected,
    CueKind,
    CueDequeued,
    CueDeduplicated,
    CueDropped,
    CueQueued,
    CueReplaced,
    CueSuppressed,
    CueSuppressionBypassed,
    CueSuppressionCleared,
    CueSuppressionStarted,
    EvidenceKind,
    EpisodeCompleted,
    EpisodeOpened,
    RuntimeFailed,
    RuntimeEpisode,
    RuntimeEnding,
    RuntimeRecord,
    RuntimeResult,
    ScenarioInputAdapter,
    ScheduledInput,
    SelectedImageEvidence,
    SocialAgentRuntime,
    TimedText,
    VisualAttentionRecorded,
)
from misty_agent.scenarios import (
    DEFAULT_ACTOR,
    DEMO_SCENARIOS,
    EXPLICIT_TEXT_REQUEST,
    AcceptanceScenario,
    PresentationBeat,
    ScenarioCard,
    ScenarioModel,
)

from misty_agent.demo import recordings  # noqa: E402 — needs the names above

#: The only address this binds. A demo that listened on every interface would
#: put a Journal — which carries what people said — on whatever network the
#: laptop happens to be on.
LOOPBACK_ONLY = "127.0.0.1"

#: Chosen by the operating system, so two demos cannot collide and nobody has
#: to remember a number.
ANY_FREE_PORT = 0

_HERE = pathlib.Path(__file__).resolve().parent
_PAGE = _HERE / "page.html"
NO_STORE = {"Cache-Control": "no-store"}
_GOLDENS = _HERE.parent.parent / "tests" / "goldens"

#: What the four original goldens say about themselves. Spelled out rather
#: than derived: the claim is historical, and there is nothing on disk that
#: knows when a file was written.
_SPEC_FIRST = (
    "Written before the ReAct loop existed, and derived from M7's spec "
    "rather than from whatever the implementation turned out to do"
)

#: The other half of that claim, and it is not the flattering half.
#:
#: The first version of this banner said the loop "had to be built to produce
#: it, not the other way round". `tests/goldens/README.md` keeps a table of
#: every time a golden and the implementation disagreed: **nine times, and
#: the goldens gave way in eight of them.** So the flattering version was false,
#: written in the one place this ticket exists to keep honest.
#:
#: The true version is the better story anyway — a rule that is never invoked
#: is not a rule, and what makes this one worth anything is that each time it
#: was invoked somebody wrote down which side moved.
AMENDMENTS = (
    "It has been amended since. Where a golden and the loop disagreed, which "
    "side gave way is written down — nine times so far, and the goldens gave "
    "way in eight of them (tests/goldens/README.md). Editing one is allowed; "
    "editing one without saying so is not."
)


@dataclass(frozen=True)
class Example:
    """One built-in Episode, and the honest account of where it came from."""

    name: str
    title: str
    provenance: str
    #: What this Episode *is*, as one word a page can style by and a test can
    #: read. Four, because a generated runtime scenario is different from
    #: both a pre-authored specification and a live visitor request:
    #:
    #: * `specification` — written before the loop existed;
    #: * `added-later` — the one golden that was not;
    #: * `scenario` — generated through the deterministic runtime seam;
    #: * `live` — something that happened on this machine a moment ago.
    #:
    #: "Never let a viewer confuse a specification with a fresh run" is the ticket's line, and
    #: it is not a thing to leave to a page's own judgement.
    kind: str
    #: What has happened to it since it was written. Travels beside the claim
    #: so that the caveat cannot be dropped while the boast is kept.
    amendments: str = AMENDMENTS


EXAMPLES: Tuple[Example, ...] = (
    Example(
        "episode_ends_after_several_turns",
        "Several turns, then it decides it is done",
        _SPEC_FIRST,
        "specification",
    ),
    Example(
        "episode_ends_on_the_first_turn",
        "Nothing worth doing — it stops immediately",
        _SPEC_FIRST,
        "specification",
    ),
    Example(
        "episode_fails_during_model_call",
        "The model call fails and the Episode closes",
        "Added at M7 #13, once runtime failure became a named outcome — "
        "unlike the other four, this one was written after the loop it pins",
        "added-later",
        "",
    ),
    Example(
        "episode_hits_the_turn_limit",
        "It runs out of turns before it runs out of ideas",
        _SPEC_FIRST,
        "specification",
    ),
    Example(
        "episode_is_aborted",
        "A foot on the bumper, mid-Episode",
        _SPEC_FIRST,
        "specification",
    ),
)

#: Ticket 01's first autonomous path.  Unlike ``EXAMPLES``, this is not a
#: pre-authored Journal: requesting it feeds a timed input through the
#: Attention Loop and lets the existing ReAct core produce the Journal that
#: the page replays.
RUNTIME_EXAMPLE = Example(
    EXPLICIT_TEXT_REQUEST.name,
    EXPLICIT_TEXT_REQUEST.title,
    "A deterministic scenario run through SocialAgentRuntime on this machine; "
    "no hosted model, network, or Misty II was used",
    "scenario",
    "",
)


@dataclass(frozen=True)
class Reply:
    """What `answer` decided, before anything touches a socket."""

    status: int
    headers: Mapping[str, str]
    body: bytes


def answer(
    method: str, path: str, body: bytes = b"", *, audio: bool = False
) -> Reply:
    """Everything about serving the demo except the socket. Pure.

    `body` arrived in M8 #10 and not before. #08 left it out on purpose —
    nothing sent one and nothing read one, which is the parameter `PLAN.md`
    §15.23 deleted once already — and both review axes agreed. Now there is
    a POST.

    `audio` is off unless somebody asked for it on the command line: hosted
    transcription costs money on the visitor's account, so it is a choice
    rather than a default.
    """
    if method == "POST":
        if path == "/run":
            return _run(body, audio=audio)
        scenario_name = _scenario_run_name(path)
        if scenario_name is not None:
            return _run_scenario(scenario_name, body)
        return _json(405, {"error": f"nothing accepts a POST at {path}"})
    if method != "GET":
        return _json(405, {"error": f"{method} is not something this serves"})
    if path == "/options":
        return _json(200, {"audio": audio})
    if path == "/":
        return Reply(
            200,
            {"Content-Type": "text/html; charset=utf-8", **NO_STORE},
            _PAGE.read_bytes(),
        )
    if path == "/scenarios":
        return _json(200, [_scenario_payload(case) for case in DEMO_SCENARIOS])
    if path == "/recordings":
        return _json(200, recordings.listing())
    if path.startswith("/recordings/"):
        # Matched against the example names, never joined onto a path.
        try:
            document = recordings.load(path[len("/recordings/"):])
        except recordings.NoRecording as why:
            return _json(404, {"error": str(why)})
        return _json(200, {**document, "payload": _played(document["payload"])})
    if path == "/acceptance":
        return _json(
            200,
            {
                "provenance": PROVENANCE,
                "hardware_unverified": HARDWARE_UNVERIFIED,
                "not_a_benchmark": (
                    "Fifteen situations with a floor under each outcome. "
                    "There is no score, no leaderboard and no comparison "
                    "with any published benchmark."
                ),
                "scenarios": [asdict(contract) for contract in ACCEPTANCE_CONTRACTS],
            },
        )
    if path == "/examples":
        return _json(
            200,
            [asdict(example) for example in (*EXAMPLES, RUNTIME_EXAMPLE)],
        )
    if path.startswith("/examples/"):
        name, slash, below = path[len("/examples/"):].partition("/")
        if slash:
            return _json(404, {"error": f"nothing is served at {path}"})
        return _example(name)
    return _json(404, {"error": f"nothing is served at {path}"})


def _scenario_run_name(path: str) -> Optional[str]:
    """Return one whole scenario name from ``/scenarios/<name>/run``."""
    prefix = "/scenarios/"
    suffix = "/run"
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return None
    name = path[len(prefix):-len(suffix)]
    return name if name and "/" not in name else None


#: What kind of thing the page is showing, so a visitor is never left to
#: guess whether they are reading a specification, a replayed simulation or
#: a paid model call. Every one of them is hardware-unverified: this project
#: has no Misty II, so no path here is evidence about a robot.
PROVENANCE = {
    "specification_fixture": (
        "A Journal written from the specification before the loop existed. "
        "It is a claim about what should happen, kept on disk."
    ),
    "scripted_run": (
        "Executed just now by this code. The inputs and the model's decisions "
        "are authored fixtures, and the robot is simulated."
    ),
    "recorded_model_run": (
        "Recorded from a real run against a hosted model and replayed here "
        "without calling it again. The inputs come from the example; every "
        "decision was the model's own. The robot is simulated."
    ),
    "live_model_run": (
        "Executed just now against a hosted model, which costs money and "
        "needs a key. The robot is still simulated."
    ),
}

#: True of every one of them, and said in one place so no surface can quietly
#: drop it.
HARDWARE_UNVERIFIED = (
    "No Misty II has ever run any of this. Physical behaviour, timing and "
    "reliability are unverified."
)


@dataclass(frozen=True)
class RunSource:
    """Who made the decisions in a run, said once so no copy can drift.

    `scripted_run` replays authored decisions — what the acceptance tests
    assert on. `recorded_model_run` is a hosted model's own decisions over
    the same inputs, captured once and replayed from disk.
    """

    kind: str
    model: str
    recorded_on: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in PROVENANCE:
            raise ValueError(f"{self.kind!r} is not a kind of run")
        if (self.kind == "recorded_model_run") != (self.recorded_on is not None):
            raise ValueError("a recording, and only a recording, has a date")


SCRIPTED = RunSource("scripted_run", "authored script")


def _provenance(
    source: RunSource,
    *,
    called_model: bool,
    input_kind: str,
    fixture_label: str,
    several_actors: bool,
) -> dict:
    """What produced this run, in words a visitor can check."""
    recorded = source.kind == "recorded_model_run"
    if input_kind == "audio":
        inputs = (
            "A synthetic WAV went through local wake detection; the transcript "
            "is part of the example."
        )
    elif input_kind == "visual":
        inputs = (
            "A synthetic frame timeline went through local anonymous tracking "
            "and the temporal visual gate; the detector signals are part of "
            "the example."
        )
    else:
        inputs = "What people say, and when, is part of the example."
    if several_actors:
        inputs += (
            " Who said what is assigned by the example: the runtime has no "
            "sound-source direction and no face identity, only anonymous "
            "track references."
        )
    if not called_model:
        decisions = "No cue formed, so the model was never called."
    elif recorded:
        decisions = (
            f"Every decision was made by {source.model}; this page replays "
            "that recording without calling it."
        )
    else:
        decisions = "The model's decisions are authored."
    return {
        "kind": source.kind,
        "kind_means": PROVENANCE[source.kind],
        "hardware_unverified": HARDWARE_UNVERIFIED,
        "headline": (
            f"Recorded from {source.model} on {source.recorded_on}"
            if recorded
            else "Executed just now with authored decisions"
        ),
        "model": source.model if called_model else "not called",
        "recorded_on": source.recorded_on,
        "robot": "Simulated Misty",
        "detail": (
            f"{inputs} {decisions} The robot is simulated; no real camera, "
            "microphone or Misty II was used."
        ),
        "audio": fixture_label if input_kind == "audio" else None,
        "fixture": fixture_label,
        "input_kind": input_kind,
    }


#: What each local-audio stage and outcome is called on the page.
AUDIO_STAGES = {
    "wake": "Local wake detection",
    "capture": "Utterance capture",
    "asr": "Speech to text (fixture transcript)",
    "backlog": "Audio backlog",
    "source": "Audio source",
}
AUDIO_OUTCOMES = {
    "matched": "Wake phrase recognised",
    "no_match": "No wake phrase recognised",
    "repeated_wake": "Repeated wake phrase",
    "captured": "An utterance was captured",
    "empty_utterance": "Nothing was said after the wake phrase",
    "silence_timeout": "Timed out waiting for speech",
    "max_duration": "The utterance reached its length limit",
    "transcribed": "Transcribed",
    "asr_empty": "No usable text",
    "asr_timeout": "Transcription timed out",
    "asr_error": "Transcription failed",
    "backlog_dropped": "Some audio was dropped because the backlog was full",
    "source_ended": "The audio source ended",
    "source_error": "The audio source failed",
}
#: The same for each frame the local temporal visual gate judged.
VISUAL_OUTCOMES = {
    "empty": "Nobody detected in frame",
    "not_looking": "The person is not looking at Misty",
    "tracking": "Started counting how long they look",
    "wave_progress": "A hand moving back and forth",
    "qualified": "Sustained gaze plus a wave passed the gate",
    "care_progress": "Observable face and posture cues accumulating",
    "care_qualified": "The cues formed an uncertain Care Cue",
}


def _facts_line(record: Mapping[str, Any], fallback: str) -> str:
    """The facts behind one perception step, as a line somebody reads.

    Only what is actually there: a gate frame carries every signal it looks
    at, and printing `eyes_narrowed: False · mouth_open: False · …` after
    each one buried the two fields that had anything in them.
    """
    shown = []
    for key, value in (record.get("facts") or {}).items():
        name, unit = _named(key)
        if isinstance(value, bool):
            if value:
                shown.append(name)
        elif isinstance(value, (int, float)):
            if value:
                shown.append(f"{name} {value:g}{unit}")
        elif value:
            shown.append(f"{name}: {value}")
    return " · ".join(shown) or fallback


#: Suffixes that are a unit rather than part of the name: `gaze_duration_s`
#: reads as "gaze duration 0.6s", not "gaze duration s 0.6".
_UNITS = {"_s": "s", "_ms": "ms", "_cm": "cm", "_deg": "°"}


def _named(key: str) -> Tuple[str, str]:
    for suffix, unit in _UNITS.items():
        if key.endswith(suffix):
            return key[: -len(suffix)].replace("_", " "), unit
    return key.replace("_", " "), ""


def _perception_beat(record: Mapping[str, Any]) -> Optional[PresentationBeat]:
    """One thing Misty heard or saw before any Episode existed.

    This is the half of a run that the Journal has no record of, because it
    happens before — and often instead of — an Episode. A page that started
    at the first Turn would be showing a robot that had already decided to
    interrupt somebody, with nothing about how it decided.
    """
    kind = _text(record.get("type"))
    if kind == "audio_attention":
        stage = _text(record["stage"])
        return PresentationBeat(
            stage,
            AUDIO_STAGES[stage],
            AUDIO_OUTCOMES[_text(record["outcome"])],
            _facts_line(record, "This stage left a typed runtime record."),
        )
    if kind == "visual_attention":
        return PresentationBeat(
            "visual_gate",
            f"Frame {record['frame_index'] + 1} · "
            f"{record.get('track_reference') or 'frame'}",
            VISUAL_OUTCOMES[_text(record["outcome"])],
            _facts_line(
                record, "The local temporal gate left a typed runtime record."
            ),
        )
    return None


#: Each Tool as one plain sentence. The page used to print the Journal's
#: own `speak(text='…')` beside the bubble that already held the words, and
#: a visitor had to read the argument list to find out what happened.
_ACTIONS = {
    "speak": lambda args: f"Says “{args.get('text', '')}”",
    "listen": lambda args: "Listens for an answer",
    "approach": lambda args: {
        "comfortable": "Moves to leave them a little room",
        "far": "Backs off to give them plenty of room",
    }.get(args.get("keep"), "Comes closer"),
    "look_around": lambda args: "Looks around the room",
    "observe_target": lambda args: "Takes another look at the person",
    "inspect_scene": lambda args: "Inspects the whole scene",
    "move_head": lambda args: "Moves its head",
    "move_arms": lambda args: "Moves its arms",
    "change_led": lambda args: "Changes its chest light",
    "display_image": lambda args: f"Shows a {args.get('expression', 'neutral')} face",
    "activate_skill": lambda args: f"Loads the {args.get('name')} Skill",
    "read_skill_resource": lambda args: f"Reads {args.get('resource')} from the {args.get('name')} Skill",
    "play_audio": lambda args: f"Plays the {args.get('sound')} sound",
    "respect_boundary": lambda args: "Stops and gives them space",
    "wait": lambda args: f"Waits {args.get('seconds')} seconds",
    "done": lambda args: "Decides it is finished",
}

#: Why an approach ended, for somebody who has not read the controller.
_APPROACH_ENDINGS = {
    "arrived": "Arrives and stops",
    "blocked": "Stops: something is in the way",
    "lost_user": "Stops: it cannot see them any more",
    "stale_reading": "Stops: its last reading is too old to trust",
    "hazard_unavailable": "Stops: it cannot tell whether the way is clear",
    "bearing_unavailable": "Does not set off: it cannot tell which way they are",
    "alignment_failed": "Stops: it could not line up with them",
    "step_limit": "Stops: it has taken as many steps as it may",
    "timeout": "Stops: it ran out of time",
    "aborted": "Stops: something interrupted it",
    "drive_error": "Stops: the drive reported a failure",
}

#: Records that are how the loop works rather than what happened in the
#: room. Kept in the playback, because the whole run is still there to step
#: through, and left out of the plain telling.
_MACHINERY = {
    "turn_started",
    "model_called",
    "target_bound",
    "skills_available",
    # The list announces each Episode with a heading of its own.
    "episode_started",
}


def _said_in(
    step: Mapping[str, Any], storyboard: Optional[Mapping[str, Any]] = None
) -> Tuple[str, bool]:
    """One Episode Moment as a sentence, and whether it carries the story.

    A Turn is four records — the Turn opening, the model answering, the note
    it wrote, the call it made — and only the last two say anything a
    visitor came to see. The Observation after them says something only when
    it did not simply work.
    """
    kind = str(step.get("kind") or "")
    facts = step.get("facts") or {}
    if kind == "tool_called":
        tool = str(facts.get("tool") or "")
        args = facts.get("args") or {}
        wording = _ACTIONS.get(tool)
        return (wording(args) if wording else tool.replace("_", " ")), True
    if kind == "observation":
        result = facts.get("result") or {}
        snapshot = facts.get("snapshot") or {}
        distance = snapshot.get("distance_cm")
        if "refused" in result:
            return f"Refused: {result['refused']}", True
        if _text(result.get("kind")) == "listening":
            heard = result.get("transcript")
            if heard:
                return f"Hears “{heard}”", True
            return "Nobody answers", True
        stopped = _text(result.get("result"))
        if stopped:
            where = (
                f" ({distance:g}cm away)"
                if isinstance(distance, (int, float))
                else ""
            )
            return (
                _APPROACH_ENDINGS.get(stopped, stopped.replace("_", " ")) + where,
                True,
            )
        return str(step.get("headline") or ""), False
    if kind == "execution_failed":
        return str(step.get("headline") or ""), True
    if kind == "episode_finished":
        board = storyboard or {}
        if board.get("outcome") == "done":
            # `done` was the Moment before this one, and said why it ended.
            turns = int(board.get("turns") or 0)
            return f"Conversation over after {turns} turn{'' if turns == 1 else 's'}", True
        return f"Conversation over: {board.get('ending') or 'it stops here'}", True
    if kind == "handoff_requested":
        return "Someone else is waiting for a turn", True
    return str(step.get("headline") or ""), kind not in _MACHINERY


#: Who a step belongs to, which is how the page draws it: the person's words
#: and Misty's words as bubbles, Misty's other actions as plain lines, what
#: came back as an indented line under the action, and everything Misty
#: sensed on its own as small print.
VOICES = ("person", "says", "acts", "result", "sense", "marker", "note", "machinery")

#: Approach endings where the world got in the way, rather than Misty
#: arriving. The page marks these in one colour, so they can be found at a
#: glance.
_PUSHBACK_ENDINGS = set(_APPROACH_ENDINGS) - {"arrived"}


def _voice_of(step: Mapping[str, Any]) -> Tuple[str, str, bool]:
    """Who a step belongs to, the words it carries, and whether it is the
    world pushing back."""
    kind = str(step.get("kind") or "")
    facts = step.get("facts") or {}
    if step.get("source") == "perception":
        if kind in {"input", "observed_cue"}:
            return "person", str(step.get("text") or step.get("headline") or ""), False
        return "sense", "", False
    if kind == "tool_called":
        args = facts.get("args") or {}
        if facts.get("tool") == "speak":
            return "says", str(args.get("text") or ""), False
        return "acts", "", False
    if kind == "observation":
        result = facts.get("result") or {}
        if _text(result.get("kind")) == "listening" and result.get("transcript"):
            return "person", str(result["transcript"]), False
        pushback = "refused" in result or _text(result.get("result")) in _PUSHBACK_ENDINGS
        return "result", "", pushback
    if kind in {"execution_failed", "tool_refused"}:
        return "result", "", True
    if kind in {"episode_finished", "handoff_requested"}:
        return "marker", "", False
    if kind == "decision_noted":
        return "note", "", False
    return "machinery", "", False


def _words(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _repeats(note: str, said: str) -> bool:
    """Whether a note only says again what Misty is about to say aloud.

    The model sometimes writes its line as its note. Printed above the
    bubble, it reads as the robot saying everything twice.
    """
    note, said = _words(note), _words(said)
    if not note or not said:
        return False
    return note == said or (len(note) >= 12 and (note in said or said in note))


def playback_of(
    payload: Mapping[str, Any],
    actors: Sequence[str] = (DEFAULT_ACTOR,),
    *,
    input_kind: str = "text",
) -> list:
    """The whole run as one ordered list: perceiving, deciding, acting.

    The page had two lists — the Episode's Moments, and a prose account of
    the runtime beside it — which said the same thing twice and still left
    out the half that happens before any Episode exists. This is the single
    sequence it plays instead, in the order the runtime recorded, with each
    Episode's Moments spliced in where it opened.

    Built from the finished payload rather than from the run, so a recording
    made months ago plays through today's projection: what the page shows can
    change without asking anybody to pay for fifteen model runs again.

    Perception entries carry no robot pose. Nothing moved, and a page drawing
    one would be inventing it.
    """
    records = list(payload.get("runtime", {}).get("records") or ())
    episodes = list(payload.get("episodes") or ())
    by_cue = {
        str(episode.get("cue_id")): (index, episode)
        for index, episode in enumerate(episodes)
    }
    detected = [
        str(record.get("cue_id"))
        for record in records
        if _text(record.get("type")) == "cue_detected"
    ]

    def actor_of(cue_id: str) -> str:
        cue_id = str(cue_id)
        index = detected.index(cue_id) if cue_id in detected else 0
        return actors[min(index, len(actors) - 1)]

    # The runtime's records stay in the order it wrote them, which is the
    # order things were understood in: a cue is detected after the speech
    # it came from was transcribed, even though it carries the time the
    # words were spoken. An Episode's Moments wait at the place it opened
    # and are let out as time passes, so somebody speaking while it runs
    # (B asking for a turn during A's `listen`) appears where they spoke.
    steps: list = []
    pending: list = []

    def let_out(until: float) -> None:
        while pending and pending[0][0] <= until:
            steps.append(pending.pop(0)[1])

    for record in records:
        if _text(record.get("type")) == "episode_opened":
            let_out(float("inf"))
            found = by_cue.get(str(record.get("cue_id")))
            if found is None:
                continue
            index, episode = found
            note = ""
            for moment in episode["storyboard"]["moments"]:
                summary, tells = _said_in(moment, episode["storyboard"])
                if moment["kind"] == "decision_noted":
                    # The note belongs to the call it was written for: one
                    # row saying what it did and why, rather than two.
                    note = moment["detail"]
                step = {
                    **moment,
                    "source": "episode",
                    "episode": index,
                    "actor": episode["actor"],
                    "cue_kind": _text(episode["cue_kind"]),
                    "cue_text": episode.get("cue_text"),
                    "summary": summary,
                    "tells_the_story": tells and moment["kind"] != "decision_noted",
                    "why": note if moment["kind"] == "tool_called" else "",
                }
                if moment["kind"] == "handoff_requested":
                    waiting = actor_of(str((moment.get("facts") or {}).get("cue_id")))
                    step["summary"] = f"{waiting} is waiting for a turn"
                voice, text, pushback = _voice_of(step)
                if voice == "says" and _repeats(step["why"], text):
                    step["why"] = ""
                step.update(voice=voice, text=text, pushback=pushback)
                # A Moment's time counts from its Episode's start.
                pending.append((_time_of(record) + _time_of(moment), step))
                if moment["kind"] == "tool_called":
                    note = ""
            continue
        beat = _perception_beat(record) or _cue_beat(record, actor_of, input_kind)
        if beat is None:
            continue
        step = {
            "source": "perception",
            "t": record.get("t"),
            "kind": beat.kind,
            "label": beat.label,
            "headline": beat.headline,
            "summary": beat.headline,
            # Everything Misty perceived belongs to the story: it is how
            # it decided whether there was anything to respond to.
            "tells_the_story": True,
            "why": "",
            "detail": beat.detail,
            "facts": dict(record.get("facts") or {}),
            # What the person said, or what was observed about them,
            # unquoted: the stage puts it in a bubble, and the wording
            # around it belongs to the caption rather than the bubble.
            "text": record.get("text"),
        }
        voice, text, pushback = _voice_of(step)
        step.update(voice=voice, text=text or step["text"], pushback=pushback)
        if voice == "person" and record.get("cue_id"):
            # Whose words these are, for a run with more than one person.
            step["actor"] = actor_of(str(record["cue_id"]))
        let_out(_time_of(record))
        steps.append(step)
    let_out(float("inf"))
    return steps


def _time_of(source: Mapping[str, Any]) -> float:
    value = source.get("t")
    return float(value) if isinstance(value, (int, float)) else 0.0


def with_playback(
    payload: Mapping[str, Any], actors: Sequence[str] = (DEFAULT_ACTOR,), **how
) -> dict:
    """`payload` with the merged list the page plays attached to it."""
    return {**payload, "playback": playback_of(payload, actors, **how)}


def _fixture_entry(item, input_kind: str, card: str) -> dict:
    """One pickable fixture, carrying the spec situation it stands for.

    The number comes from `misty_agent.acceptance`, the same tuple the
    acceptance tests assert against, so the picker cannot claim a coverage
    the tests do not have.
    """
    contract = contract_for(card, item.key)
    entry = {"key": item.key, "label": item.label, "input_kind": input_kind}
    if contract is not None:
        entry["spec_scenario"] = contract.number
        entry["situation"] = contract.situation
    return entry


def _scenario_payload(case: ScenarioCard) -> dict:
    """The stable, human-readable facts displayed on a scenario card."""
    payload = {
        "name": case.name,
        "title": case.title,
        "subtitle": case.subtitle,
        "availability": case.availability,
        "ticket": case.ticket,
        "limitation": case.limitation,
        "preview": [asdict(beat) for beat in case.preview],
    }
    if isinstance(case, AcceptanceScenario):
        payload["actors"] = list(case.actors)
        audio_fixtures = [
            _fixture_entry(item, "audio", case.name) for item in case.audio_fixtures
        ]
        visual_fixtures = [
            _fixture_entry(item, "visual", case.name) for item in case.visual_fixtures
        ]
        payload["audio_fixtures"] = audio_fixtures
        payload["visual_fixtures"] = visual_fixtures
        payload["fixtures"] = audio_fixtures + visual_fixtures + [
            _fixture_entry(item, "text", case.name) for item in case.text_scripts
        ]
    return payload










def _scenario_request(body: bytes) -> Mapping[str, Any]:
    if not body:
        return {}
    try:
        asked = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("scenario request must be a JSON object")
    if not isinstance(asked, dict):
        raise ValueError("scenario request must be a JSON object")
    return asked


def _run_scenario(name: str, body: bytes = b"") -> Reply:
    """Run one named offline scenario through the real runtime seam.

    The running itself is `misty_agent.acceptance.run_fixture`, which the
    acceptance tests also call: what a visitor watches here is the same
    execution the tests asserted on, not a second copy of the wiring.
    """
    case = next((item for item in DEMO_SCENARIOS if item.name == name), None)
    if case is None:
        return _json(404, {"error": f"there is no scenario called {name!r}"})
    if not isinstance(case, AcceptanceScenario):
        return _json(
            409,
            {
                "error": (
                    f"scenario {name!r} is planned for ticket {case.ticket}"
                ),
                "ticket": case.ticket,
            },
        )

    try:
        asked = _scenario_request(body)
    except ValueError as why:
        return _json(400, {"error": str(why)})

    try:
        run = run_fixture(name, asked.get("fixture"))
    except UnknownFixture as why:
        return _json(400, {"error": str(why)})
    return _json(200, _played(fixture_payload(case, run, SCRIPTED)))


def _played(payload: Mapping[str, Any]) -> dict:
    """A finished run with the list the page plays attached.

    One place, so a recording, a scripted run and a live one are played from
    the same projection rather than three that can disagree.
    """
    return with_playback(
        payload,
        tuple(payload.get("scenario", {}).get("actors") or (DEFAULT_ACTOR,)),
        input_kind=str(
            payload.get("execution", {})
            .get("provenance", {})
            .get("input_kind")
            or "text"
        ),
    )


def fixture_payload(
    case: AcceptanceScenario, run: FixtureRun, source: RunSource
) -> dict:
    """One finished fixture run, as the page draws it.

    Shared by the scripted route above and by the recorder in
    `misty_agent.demo.recordings`, so a recording is the same shape as the
    run the tests assert on and differs only in who made the decisions.
    """
    result = run.result
    session = run.session
    if run.fixture is None:
        raise RuntimeError("an acceptance scenario has no fixture")
    detected = [
        record for record in result.records if isinstance(record, CueDetected)
    ]
    said_by_cue = {record.cue_id: record for record in detected}
    episodes = []
    for index, episode in enumerate(result.episodes):
        actor = case.actors[min(index, len(case.actors) - 1)]
        storyboard, board = _project_journal(episode.journal.records)
        cue = said_by_cue.get(episode.cue_id)
        episodes.append(
            {
                "actor": actor,
                "cue_id": episode.cue_id,
                "cue_kind": episode.cue_kind,
                #: What opened this Episode. Words only for an Explicit
                #: Request; for any other cue it is an observed signal, and
                #: the page must not put it in the person's mouth.
                "cue_text": cue.text if cue is not None else None,
                "episode_id": episode.journal.records[0].episode_id,
                "outcome": asdict(episode.outcome),
                "moves": list(what_moves(storyboard)),
                "storyboard": board,
            }
        )
    return {
        "scenario": _scenario_payload(case),
        "execution": _scenario_execution(
            result,
            result.episodes[0] if result.episodes else None,
            queue_capacity=SCENARIO_CONFIG.cue_queue_capacity,
            fixture_label=run.fixture.label,
            input_kind=run.input_kind,
            actors=case.actors,
            robot_state=session.robot.as_facts(),
            source=source,
        ),
        "runtime": _runtime_payload(result),
        "episodes": episodes,
        # State, not a log: where the simulated Misty ended up. The
        # storyboard above derives the same pose from the Journal.
        "robot": _simulated_robot_state(session.robot),
    }


def _scenario_execution(
    result: RuntimeResult,
    episode: Optional[RuntimeEpisode],
    *,
    queue_capacity: int,
    fixture_label: str,
    input_kind: str,
    actors: Sequence[str] = (DEFAULT_ACTOR,),
    robot_state: Optional[Mapping[str, Any]] = None,
    source: "RunSource",
) -> Mapping[str, Any]:
    """Human-readable evidence derived from this run, not its preview.

    Cue lifecycle records are walked in order, so a second person's queued
    request, the handoff notice inside the first Episode, and the second
    Episode all appear where they happened rather than as one flattened
    Journal.
    """
    evidence = episode.evidence if episode is not None else None
    journal_records = episode.journal.records if episode is not None else ()
    notes = {
        record.turn: record
        for record in journal_records
        if isinstance(record, DecisionNoted)
    }
    queue_records = tuple(
        record
        for record in result.records
        if isinstance(
            record,
            (
                CueQueued,
                CueDequeued,
                CueDeduplicated,
                CueReplaced,
                CueDropped,
                CueSuppressionStarted,
                CueSuppressed,
                CueSuppressionBypassed,
                CueSuppressionCleared,
            ),
        )
    )
    audio_records = tuple(
        record
        for record in result.records
        if isinstance(record, AudioAttentionRecorded)
    )
    visual_records = tuple(
        record
        for record in result.records
        if isinstance(record, VisualAttentionRecorded)
    )
    flow = [_perception_beat(asdict(record)) for record in audio_records]
    flow.extend(_perception_beat(asdict(record)) for record in visual_records)
    runs_by_cue = {run.cue_id: run for run in result.episodes}
    detected_by_cue = {
        record.cue_id: record
        for record in result.records
        if isinstance(record, CueDetected)
    }
    cue_order = list(detected_by_cue)

    def actor_of(cue_id: str) -> str:
        index = cue_order.index(cue_id) if cue_id in cue_order else 0
        return actors[min(index, len(actors) - 1)]

    # Cue records appended while an Episode was active belong inside that
    # Episode's story: they were collected at its Turn boundaries.
    during: dict[str, list] = {}
    active_cue: Optional[str] = None
    for record in result.records:
        if isinstance(record, EpisodeOpened):
            active_cue = record.cue_id
            during[active_cue] = []
        elif isinstance(record, EpisodeCompleted):
            active_cue = None
        elif active_cue is not None and isinstance(
            record,
            (
                CueDetected,
                CueQueued,
                CueDeduplicated,
                CueReplaced,
                CueDropped,
                CueSuppressed,
            ),
        ):
            during[active_cue].append(record)
    inside = {id(record) for group in during.values() for record in group}

    for record in result.records:
        if id(record) in inside:
            continue
        if isinstance(record, EpisodeOpened) and record.cue_id in runs_by_cue:
            cue_index = cue_order.index(record.cue_id)
            flow.extend(_episode_beats(
                runs_by_cue[record.cue_id],
                actor_of(record.cue_id),
                detected_by_cue[record.cue_id],
                input_kind,
                during=during.get(record.cue_id, ()),
                actor_of=actor_of,
                robot_state=robot_state,
                previous_actor=(
                    actor_of(cue_order[cue_index - 1])
                    if cue_index > 0
                    else None
                ),
            ))
        else:
            beat = _cue_beat(asdict(record), actor_of, input_kind)
            if beat is not None:
                flow.append(beat)
    completed = bool(
        result.episodes
        and result.ending is RuntimeEnding.INPUT_EXHAUSTED
        and all(run.outcome.outcome == "done" for run in result.episodes)
    )
    quiet = episode is None and result.ending is RuntimeEnding.INPUT_EXHAUSTED
    flow.append(
        PresentationBeat(
            "ending",
            "Result",
            (
                "The example ran to completion"
                if completed
                else (
                    "Stayed quiet: no Episode was opened"
                    if quiet
                    else "The example did not complete normally"
                )
            ),
            (
                "Every input in the example was played and the runtime stopped normally."
                if completed
                else (
                    "The whole timeline played, but nothing in it was enough to involve the model or move."
                    if quiet
                    else (
                        f"Episode: "
                        f"{episode.outcome.outcome if episode else 'none'}; "
                        f"Runtime: {result.ending.value}"
                    )
                )
            ),
        )
    )
    return {
        "provenance": _provenance(
            source,
            called_model=episode is not None,
            input_kind=input_kind,
            fixture_label=fixture_label,
            several_actors=len(set(actors)) > 1,
        ),
        "trigger_evidence": (
            {
                "source": evidence.source.value,
                "observed_at_s": evidence.observed_at_s,
                "facts": dict(evidence.facts),
                "transcript": evidence.transcript,
                "uncertainty": list(evidence.uncertainty),
                "selected_image": (
                    evidence.selected_image_media_type is not None
                ),
            }
            if evidence is not None
            else None
        ),
        "selected_evidence": (
            {
                "count": 1,
                "media_type": evidence.selected_image_media_type,
                "selected_frame_index": evidence.facts.get(
                    "selected_frame_index"
                ),
            }
            if evidence is not None
            and evidence.selected_image_media_type is not None
            else None
        ),
        "visual_timeline": [
            {
                "frame_index": record.frame_index,
                "outcome": record.outcome.value,
                "track_reference": record.track_reference,
                "facts": dict(record.facts),
            }
            for record in visual_records
        ],
        "flow": [asdict(beat) for beat in flow],
        "decision_explanation": {
            "available": bool(notes),
            "headline": (
                "The Journal recorded a Decision Note"
                if notes
                else (
                    "The local gate opened no interaction"
                    if episode is None and input_kind == "visual"
                    else "The model gave no Decision Note"
                )
            ),
            "detail": (
                next(iter(notes.values())).note
                if notes
                else (
                    "The evidence never formed a cue, so the model was never called."
                    if episode is None and input_kind == "visual"
                    else "The Tool choices can still be checked, but no public purpose was given."
                )
            ),
        },
        "attention": {
            "active_cue": None,
            "active_history": [
                {
                    "cue_id": run.cue_id,
                    "cue_kind": run.cue_kind.value,
                    "priority": run.cue_kind.priority,
                    "outcome": run.outcome.outcome,
                }
                for run in result.episodes
            ],
            "queue_capacity": queue_capacity,
            "events": [_runtime_moment(record) for record in queue_records],
        },
    }


def _example(name: str) -> Reply:
    """One golden, as the Storyboard a page draws plus who it claims to be.

    `name` is the only input here that reaches the filesystem, so it is
    matched against the examples rather than joined onto a path: `..` and a
    slash and an encoded slash are all simply not one of six names.
    """
    if name in {RUNTIME_EXAMPLE.name, "runtime_explicit_text_request"}:
        return _runtime_example()

    found = next((example for example in EXAMPLES if example.name == name), None)
    if found is None:
        return _json(404, {"error": f"there is no example called {name!r}"})
    try:
        # Bytes, not text: `read_text` translates line endings, and the claim
        # this whole route exists to make is that a visitor is looking at what
        # is on disk. Decoded here so the JSON carries it, split on newlines
        # only, so anything else a line contains survives.
        raw = (_GOLDENS / f"{found.name}.jsonl").read_bytes()
    except OSError as why:
        # A named example whose file is not there means this copy of the
        # project is incomplete, not that the visitor asked for the wrong
        # thing. `answer` promises a Reply for every request, so it says so
        # rather than raising out of the handler into a blank page.
        return _json(500, {"error": f"the example {name!r} is missing: {why}"})

    text = raw.decode("utf-8")
    lines = [line for line in text.split("\n") if line.strip()]
    try:
        storyboard, board = _project_journal(from_jsonl(text), lines=lines)
    except ValueError as mismatch:
        # Cannot happen — `storyboard_of` maps one Moment per record — and it
        # is refused rather than trusted anyway. Pairing them off by position
        # while the two disagree would put one decision's fields under
        # another's sentence, which is worse than showing nothing at all.
        return _json(
            500,
            {"error": f"{name!r} has {mismatch}"},
        )

    return _json(
        200,
        {
            "example": asdict(found),
            "moves": list(what_moves(storyboard)),
            "storyboard": board,
        },
    )


def _project_journal(records, *, lines=None):
    """Build a Storyboard and attach the exact line behind each Moment."""
    records = tuple(records)
    source_lines = (
        list(lines) if lines is not None else to_jsonl(records).splitlines()
    )
    storyboard = storyboard_of(records)
    board = asdict(storyboard)
    if len(source_lines) != len(board["moments"]):
        raise ValueError(
            f"{len(source_lines)} records and {len(board['moments'])} moments"
        )
    for moment, line in zip(board["moments"], source_lines):
        # Carried by the Moment, so JavaScript cannot pair a record with its
        # neighbour while both independent payloads still look valid.
        moment["line"] = line
    return storyboard, board


def _runtime_example() -> Reply:
    """Generate and project the first complete SocialAgentRuntime scenario."""
    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions[:3]),
        clock=clock,
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            EXPLICIT_TEXT_REQUEST.inputs[:1],
        ),
        session=session,
        clock=clock,
    )
    result = runtime.run()
    episode = result.episodes[0]
    storyboard, board = _project_journal(episode.journal.records)

    return _json(
        200,
        {
            "example": asdict(RUNTIME_EXAMPLE),
            "runtime": _runtime_payload(result),
            "moves": list(what_moves(storyboard)),
            "storyboard": board,
        },
    )


_DROP_WORDING = {
    "expired": "expired before an Episode could open",
    "overflow": "was evicted because the queue was full",
    "shutdown": "was abandoned because the runtime shut down",
    "runtime_failure": "was abandoned because the runtime failed",
    "episode_error": "was abandoned because an Episode failed",
}


_MOTION_WORDING = {"rotate": "turn", "forward": "forward", "back": "back"}


def replace_beat(beat: PresentationBeat, **changes: Any) -> PresentationBeat:
    from dataclasses import replace as _replace
    return _replace(beat, **changes)


def _approach_beats(result: Mapping[str, Any], robot_state: Optional[Mapping[str, Any]]) -> list:
    """The controller's typed result, each bounded chassis motion with the
    fresh distance and bearing it was planned from, then where the chassis
    and the head ended up. Simulated only."""
    ending = (
        f"{result.get('result')} · {result.get(STEPS_KEY, 0)} step(s)"
        f" ({result.get('rotations', 0)} turn(s))"
    )
    caveats = "; ".join(result.get("uncertainty") or ()) or "no further uncertainty noted"
    beats = [PresentationBeat(
        "approach", "Target-aware approach", ending,
        f"Why it stopped: {result.get('reason') or 'not stated'}. Last reading: "
        f"{result.get('distance_cm')} cm at bearing {result.get('bearing_deg')}° ({caveats}). "
        "The chassis aligns before closing in, and every checkpoint checks for "
        "a stop and a hazard. How fast and how long belong to the controller; "
        "the model only states the intent. The constants are simulated, not "
        "a safety validation on a real robot.",
    )]
    for index, motion in enumerate(result.get("motions") or [], start=1):
        amount = (
            f"{round(motion['rotate_deg'], 1)}°"
            if motion["kind"] == "rotate"
            else f"{round(motion['move_cm'], 1)} cm"
        )
        beats.append(PresentationBeat(
            "movement_step", f"Step {index}",
            f"Step {index}: {_MOTION_WORDING.get(motion['kind'], motion['kind'])} {amount}",
            f"Planned from {motion['distance_cm']} cm at bearing {motion['bearing_deg']}°; "
            "each step needs a fresh reading before the next. Simulated.",
        ))
    if robot_state is not None and robot_state.get("halted_at_s") is not None:
        beats[0] = replace_beat(
            beats[0],
            detail=beats[0].detail + f" The chassis halted at {robot_state['halted_at_s']:g}s.",
        )
    if robot_state is not None:
        target = robot_state.get("target") or {}
        beats.append(PresentationBeat(
            "chassis", "Chassis and head",
            f"Chassis heading {robot_state.get('heading_deg')}°, head yaw "
            f"{robot_state.get('pose', {}).get('head', [0, 0, 0])[2]}°",
            f"Current target: {target.get('distance_cm')} cm at bearing "
            f"{target.get('bearing_deg')}°. Turning the head is not alignment; "
            "only the chassis heading counts. Simulated state.",
        ))
    return beats


#: What each Cue kind is called on the page. One mapping, because three
#: places used to spell the same switch and one of them got it wrong: a
#: queued Care Cue was announced as an explicit request.
_CUE_WORDING = {
    "explicit_request": "Explicit request",
    "care_cue": "Care Cue",
    "social_invitation": "Social Invitation",
}


def _cue_wording(kind: Any) -> str:
    return _CUE_WORDING.get(_text(kind), _text(kind))


def _text(value: Any) -> str:
    """An enum's value, or whatever a replayed record already holds.

    The same record reaches this module twice: as a dataclass on the way out
    of a run, and as the plain JSON a recording was saved as. One of them
    has `CueKind.CARE_CUE` where the other has `"care_cue"`, and an f-string
    is the place that difference would show up on the page.
    """
    return str(getattr(value, "value", value) or "")


def _cue_beat(record: Mapping[str, Any], actor_of, input_kind: str) -> Optional[PresentationBeat]:
    """One cue lifecycle record as display copy, or nothing to show.

    Takes the record as a mapping, because a recording replays the same
    records after a round trip through JSON.
    """
    kind = _text(record.get("type"))
    if kind == "cue_detected":
        if input_kind not in {"audio", "text"}:
            return None
        actor = actor_of(record["cue_id"])
        if _text(record["cue_kind"]) != CueKind.EXPLICIT_REQUEST.value:
            # Only an Explicit Request is words the person said. A Care Cue or
            # a Social Invitation is an observable signal, and quoting it as
            # speech would put words in the person's mouth (ticket 06).
            return PresentationBeat(
                "observed_cue",
                _cue_wording(record["cue_kind"]),
                f"{actor}: {record['text']}",
                "A signal the local gate observed, not something the person "
                "said. The input comes from the example.",
            )
        return PresentationBeat(
            "input",
            "Person says" if actor == DEFAULT_ACTOR else f"{actor} says",
            f"“{record['text']}”",
            "The input comes from the example.",
        )
    if kind == "cue_queued":
        return PresentationBeat(
            "cue_queued",
            "Cue queue",
            f"{_cue_wording(record['cue_kind'])} waits in the queue ({actor_of(record['cue_id'])})",
            f"{actor_of(record['active_cue_id'])}'s Episode is running; the queue holds "
            f"{record['queue_size']} cue(s). No parallel Episode, and nothing dropped.",
        )
    if kind == "cue_dropped":
        reason = _text(record["reason"])
        return PresentationBeat(
            "cue_dropped",
            "Cue dropped",
            f"{actor_of(record['cue_id'])}'s cue "
            + _DROP_WORDING.get(reason, reason),
            "Freshness and queue rules decide; it never acts on stale evidence.",
        )
    if kind == "cue_dequeued":
        return PresentationBeat(
            "cue_dequeued",
            "Handoff",
            f"{actor_of(record['cue_id'])}'s turn",
            "The previous Episode ended at a Turn boundary; the next cue leaves "
            "the queue and opens a new Episode with a new Interaction Target.",
        )
    if kind == "cue_suppression_started":
        duration = max(0.0, record["expires_at_s"] - record["t"])
        return PresentationBeat(
            "cue_suppression_started",
            "Cue Suppression",
            f"Quiet towards this anonymous track for {duration:g}s",
            f"Only an anonymous token and a deadline ({record['expires_at_s']:g}s) "
            "are kept; no identity, nothing that outlives the run.",
        )
    if kind == "cue_suppressed":
        return PresentationBeat(
            "cue_suppressed",
            "Not intruding",
            f"{_cue_wording(record['cue_kind'])} opened no Episode",
            f"{round(record['remaining_s'], 1):g}s of suppression left for this anonymous track.",
        )
    if kind == "cue_suppression_bypassed":
        return PresentationBeat(
            "cue_suppression_bypassed",
            "Explicit request first",
            "They called Misty again, so a new Episode opens at once",
            "An explicit request bypasses and ends the suppression.",
        )
    if kind == "cue_suppression_cleared":
        return PresentationBeat(
            "cue_suppression_cleared",
            "Suppression cleared",
            _text(record["reason"]).replace("_", " "),
            "Expiry, a lost track or the runtime ending all leave nothing behind.",
        )
    return None


def _episode_beats(
    run: RuntimeEpisode,
    actor: str,
    cue: CueDetected,
    input_kind: str,
    *,
    during: Sequence[RuntimeRecord],
    actor_of,
    robot_state: Optional[Mapping[str, Any]] = None,
    previous_actor: Optional[str] = None,
) -> list:
    """One Episode's evidence, target, notices and Tool results, in order.

    `during` holds cue records the Attention Loop appended while this Episode
    ran. Those about a cue the model was told of appear at that notice; the
    rest follow the Journal, still inside this Episode's story.
    """
    waiting = list(during)

    def collected(cue_id: Optional[str]) -> list:
        chosen = [r for r in waiting if cue_id is None or getattr(r, "cue_id", None) == cue_id]
        for record in chosen:
            waiting.remove(record)
        return [
            beat
            for beat in (_cue_beat(asdict(r), actor_of, input_kind) for r in chosen)
            if beat
        ]
    evidence = run.evidence
    uncertainty = (
        "; ".join(evidence.uncertainty)
        if evidence.uncertainty
        else "no further uncertainty noted"
    )
    observations = {
        record.turn: record
        for record in run.journal.records
        if isinstance(record, Observation)
    }
    notes = {
        record.turn: record
        for record in run.journal.records
        if isinstance(record, DecisionNoted)
    }
    flow = [
        PresentationBeat(
            "evidence",
            "Trigger Evidence",
            f"{'Text' if input_kind == 'text' else 'Speech' if evidence.source.value == 'speech' else 'Image'} evidence · "
            f"at {evidence.observed_at_s:g}s",
            f"{len(evidence.facts)} observable fact(s)"
            + (
                "; 1 bounded JPEG crop selected"
                if evidence.selected_image_media_type is not None
                else ""
            )
            + f"; uncertainty: {uncertainty}",
        ),
        PresentationBeat(
            "cue",
            "Classified as",
            _cue_wording(cue.cue_kind),
            cue.cue_kind.value,
        ),
    ]
    if previous_actor is not None:
        flow.append(PresentationBeat(
            "context_reset",
            "Cleared between Episodes",
            f"{actor} starts from new Trigger Evidence",
            f"{actor}'s model context holds only this Episode; nothing of "
            f"{previous_actor}'s name, words, Skill instructions or summary is inherited.",
        ))
    journal_records = run.journal.records
    for record in journal_records:
        if isinstance(record, TargetBound):
            flow.append(PresentationBeat(
                "target_bound",
                "Interaction Target",
                f"{actor}: {record.track_reference or 'no anonymous track (speech only)'}",
                f"This Episode binds only this anonymous target ({record.state}); a "
                "nearer or newer face never silently replaces it, and the next "
                "Episode does not inherit it.",
            ))
        if isinstance(record, HandoffRequested):
            flow.extend(collected(record.cue_id))
            flow.append(PresentationBeat(
                "handoff_requested",
                "Handoff notice",
                f"{actor_of(record.cue_id)} is waiting ({record.cue_id})",
                "The model is told at a Turn boundary to wrap up; the current Turn "
                "is not interrupted and no parallel Episode opens.",
            ))
        if isinstance(record, SkillsAvailable):
            flow.append(PresentationBeat(
                "skills_available", "Available Skills", "Skills it may load (none loaded yet)",
                " · ".join(f"{item['name']}: {item['description']}" for item in record.skills),
            ))
        if not isinstance(record, ToolCalled):
            continue
        noted = notes.get(record.turn)
        tool_call_id = (
            noted.tool_call_id if noted is not None else f"turn-{record.turn}-tool"
        )
        if noted is not None:
            flow.append(
                PresentationBeat(
                    "decision_note",
                    "Decision Note",
                    noted.note,
                    "A public purpose, not private reasoning.",
                )
            )
        flow.append(
            PresentationBeat(
                "tool_call", "Tool call", record.tool, tool_call_id
            )
        )
        if record.tool == "speak":
            observation = observations.get(record.turn)
            succeeded = (
                observation is not None
                and observation.result.get("ok") is True
            )
            flow.append(
                PresentationBeat(
                    "observation",
                    "Observation",
                    f"“{record.args['text']}”",
                    (
                        "Spoken in simulation; a Snapshot went back with the next Turn."
                        if succeeded
                        else "Speaking failed in simulation; a Snapshot went back with the next Turn."
                    ),
                )
            )
        elif record.tool in {"activate_skill", "read_skill_resource", "listen"}:
            observation = observations.get(record.turn)
            if observation is not None:
                returned = observation.result
                if "refused" in returned:
                    headline, detail = "Refused", returned["refused"]
                elif record.tool == "activate_skill":
                    headline, detail = returned["name"], "Skill loaded; it guides only this Episode's later Tools."
                elif record.tool == "read_skill_resource":
                    headline, detail = returned["resource"], "Read on demand; no script was run."
                else:
                    headline = returned.get("transcript") or "Nothing new was heard"
                    detail = f"Listening ended: {returned['ending']}; {returned['source']}, speaker not identified."
                flow.append(PresentationBeat(
                    returned.get("kind", "refused"), "Tool result", headline, detail,
                ))
        elif record.tool in {"observe_target", "inspect_scene"}:
            observation = observations.get(record.turn)
            if observation is not None:
                flow.append(
                    PresentationBeat(
                        "observation",
                        "Observation",
                        (
                            "A cheap look at the target"
                            if record.tool == "observe_target"
                            else "A more expensive scene inspection"
                        ),
                        f"{observation.result.get('ending')} · "
                        f"fresh for {observation.result.get('fresh_for_s')}s · "
                        "uncertainty kept",
                    )
                )
        elif record.tool in {"move_head", "move_arms", "display_image", "change_led"}:
            observation = observations.get(record.turn)
            if observation is not None and observation.result.get("ok"):
                flow.append(PresentationBeat(
                    "simulated_effect", "Expressed in simulation", describe(record).headline,
                    "The pose follows this successful Tool result; no real robot moved.",
                ))
        elif record.tool == "approach":
            observation = observations.get(record.turn)
            if observation is not None:
                flow.extend(_approach_beats(observation.result, robot_state))
        elif record.tool == "respect_boundary":
            observation = observations.get(record.turn)
            halted = observation is not None and observation.result.get("ok") is True
            flow.extend(
                (
                    PresentationBeat(
                        "boundary_respected",
                        "Boundary respected",
                        "Stops asking and finishes the Episode",
                        "The model chose this through a typed Tool; it is not a keyword-triggered reply.",
                    ),
                    PresentationBeat(
                        "movement_stopped",
                        "Controller",
                        (
                            "The chassis was halted; no further approach"
                            if halted
                            else "The halt failed; no further approach"
                        ),
                        (
                            "The simulated adapter reports it stopped; no Misty II has verified this."
                            if halted
                            else "The simulated adapter reports the halt failed: "
                            + str(
                                (observation.result if observation else {}).get(
                                    "detail", "no detail"
                                )
                            )
                            + ". The Episode still ends, without claiming the chassis stopped."
                        ),
                    ),
                )
            )
    flow.extend(collected(None))
    utterances = [evidence.transcript] if evidence.transcript else []
    utterances.extend(
        record.result["transcript"]
        for record in observations.values()
        if isinstance(record.result.get("transcript"), str)
        and record.result["transcript"].strip()
    )
    flow.append(PresentationBeat(
        "context_retained",
        "Kept within the Episode",
        f"{actor}'s {len(utterances)} utterance(s) and results stay available to later Turns",
        "Those words, Tool calls and Observations are available only to later "
        "Turns of the same Episode, and are cleared when it ends: no personal memory.",
    ))
    return flow


def _simulated_robot_state(robot: Any) -> dict:
    """The simulated adapter's final state, for the evidence panel."""
    return {
        **robot.as_facts(),
        "provenance": "SimulatedMistyAdapter state after this run; not a robot",
    }


def _runtime_payload(result: RuntimeResult) -> dict:
    """The runtime facts a Demo client can inspect beside the Storyboard."""
    return {
        "ending": result.ending,
        "records": [asdict(record) for record in result.records],
        "timeline": [_runtime_moment(record) for record in result.records],
        "episodes": [
            {
                "cue_id": run.cue_id,
                "cue_kind": run.cue_kind,
                "outcome": asdict(run.outcome),
                "episode_id": run.journal.records[0].episode_id,
            }
            for run in result.episodes
        ],
    }


def _runtime_moment(record: RuntimeRecord) -> dict:
    """One Attention fact as display-ready copy, decided outside JavaScript."""
    headline = "Runtime record"
    detail = record.type
    if isinstance(record, AttentionStarted):
        headline = "Attention Loop started"
        detail = "waiting for an Interaction Cue"
    elif isinstance(record, AudioAttentionRecorded):
        names = {
            "wake": "Wake phrase",
            "capture": "Utterance capture",
            "asr": "Speech recognition",
            "backlog": "Audio backlog",
            "source": "Audio source",
        }
        headline = (
            f"{names[record.stage.value]}: "
            f"{record.outcome.value.replace('_', ' ')}"
        )
        detail = (
            " · ".join(
                f"{key}: {value}" for key, value in record.facts.items()
            )
            or "typed local-audio outcome"
        )
    elif isinstance(record, VisualAttentionRecorded):
        headline = (
            f"Frame {record.frame_index + 1}: "
            f"{record.outcome.value.replace('_', ' ')}"
        )
        detail = (
            " · ".join(
                f"{key}: {value}" for key, value in record.facts.items()
            )
            or "typed local-visual outcome"
        )
    elif isinstance(record, CueDetected):
        headline = f"{record.cue_kind.value.replace('_', ' ')} detected"
        detail = f"{record.evidence_kind} evidence: {record.text or '(no words)'}"
    elif isinstance(record, CueQueued):
        headline = f"Queued {record.cue_id} · priority {record.priority}"
        detail = (
            f"while handling {record.active_cue_id} · {record.queue_size} "
            "in the queue"
        )
    elif isinstance(record, CueDeduplicated):
        headline = f"Deduplicated {record.cue_id}"
        detail = (
            f"kept {record.retained_cue_id} · key "
            f"{record.deduplication_key}"
        )
    elif isinstance(record, CueReplaced):
        headline = f"Upgraded {record.cue_id} → {record.replacement_cue_id}"
        detail = f"priority {record.old_priority} → {record.new_priority}"
    elif isinstance(record, CueDropped):
        reason = {
            "expired": "expired",
            "overflow": "queue full",
            "shutdown": "runtime shut down",
            "runtime_failure": "runtime failed",
            "episode_error": "Episode failed",
        }[record.reason.value]
        headline = f"Dropped {record.cue_id} · {reason}"
        detail = (
            f"priority {record.priority} · {record.queue_size} left "
            "in the queue"
        )
    elif isinstance(record, CueDequeued):
        headline = f"Dequeued {record.cue_id} · priority {record.priority}"
        detail = f"{record.queue_size} left in the queue"
    elif isinstance(record, CueSuppressionStarted):
        headline = "Cue Suppression started"
        detail = (
            f"anonymous track {record.track_reference} · until "
            f"{record.expires_at_s:g}s"
        )
    elif isinstance(record, CueSuppressed):
        headline = f"Suppressed {record.cue_id}"
        detail = (
            f"{record.cue_kind.value} · {record.remaining_s:g}s remaining"
        )
    elif isinstance(record, CueSuppressionBypassed):
        headline = f"Explicit request bypassed suppression: {record.cue_id}"
        detail = f"anonymous track {record.track_reference}"
    elif isinstance(record, CueSuppressionCleared):
        headline = "Cue Suppression cleared"
        detail = record.reason.value
    elif isinstance(record, EpisodeOpened):
        headline = "Episode opened"
        detail = f"selected {record.cue_id}"
    elif isinstance(record, EpisodeCompleted):
        headline = f"Episode ended: {record.outcome}"
        detail = record.episode_id
    elif isinstance(record, RuntimeFailed):
        headline = f"Runtime failed during {record.phase.value}"
        detail = f"{record.error_type}: {record.message}"
    elif isinstance(record, AttentionStopped):
        headline = f"Attention Loop stopped: {record.ending.value}"
        detail = "finite scenario closed"
    return {
        **asdict(record),
        "headline": headline,
        "detail": detail,
    }


#: The parts of `RobotState` the panel draws, and what to call them.
_MOVING_PARTS = (("led", "chest light"), ("head", "head"), ("arms", "arms"),
                 ("expression", "face"))


def what_moves(storyboard) -> Tuple[str, ...]:
    """Which parts of the robot this Episode ever changes.

    `PLAN.md` §16.31: no golden ever lights the chest or moves the arms, so
    three of the four readouts sit at their defaults for the whole run. A
    visitor cannot tell that from a panel that just says `off` — it reads as
    broken. Worked out here rather than in the page, for the same reason
    everything else about the display is (`PLAN.md` §16.4).
    """
    poses = [moment.robot for moment in storyboard.moments]
    return tuple(
        label
        for field, label in _MOVING_PARTS
        if len({getattr(pose, field) for pose in poses}) > 1
    )


#: The half of `MissingApiKey`'s advice that a page cannot follow.
#:
#: That message is right, and it is the only one (`PLAN.md` §16.24) — but it
#: is written for somebody standing at a terminal. `load_api_key` reads *this
#: process's* environment, so an `export` in the visitor's own shell never
#: reaches a demo that is already running; the file is picked up on the next
#: request, with nothing to restart. Saying so is an addition to that
#: paragraph, not a second copy of it.
#: As much as one request may carry. Generous for a photograph and a short
#: recording, and a bound on what a single POST can ask this process to hold
#: in memory — the body is decoded before anything looks at it.
MOST_ONE_REQUEST_MAY_CARRY = 24 * 1024 * 1024

ONLY_ONE_REACHES_A_PAGE = (
    "Two ways, and only one of them reaches a demo that is already running: "
    "the file is read again on every run, so putting it there is enough. An "
    "`export` sets the variable in your shell and not in this process, so for "
    "that one, stop the demo and start it again."
)

#: What a run that just happened says about itself. Deliberately not a
#: variant of the goldens' claim: it is the opposite one.
LIVE = Example(
    "live",
    "Just now, on this machine",
    "Run just now, on this machine. Nothing here was written in advance — "
    "which is exactly what makes the four specifications above worth having",
    "live",
    "",
)


def _run(body: bytes, *, audio: bool) -> Reply:
    """One Episode from what the page sent, and what perception made of it.

    ## Perception is free; decisions are not

    MediaPipe runs here, on this machine, and costs nothing. So an upload
    always comes back with what the camera made of it — face, distance,
    whether they are looking — even with no key at all. Only the Episode
    needs one, and `MissingApiKey` already writes the paragraph explaining
    both ways to supply it (`PLAN.md` §16.24), so this hands that one over
    rather than composing a second.

    ## Nothing that arrives is written down

    The image is decoded in memory and the audio with it. The only thing in
    this project that writes an Episode to disk is `JsonlFile`, and reaching
    it takes the `--journal` flag (M8 #06) — which is a decision about
    keeping people's words, made once, on purpose.
    """
    if len(body) > MOST_ONE_REQUEST_MAY_CARRY:
        return _json(
            413,
            {
                "error": f"that is {len(body) // (1024 * 1024)}MB; this takes "
                f"up to {MOST_ONE_REQUEST_MAY_CARRY // (1024 * 1024)}MB"
            },
        )
    try:
        asked = json.loads(body or b"{}")
        if not isinstance(asked, dict):
            raise ValueError("expected an object")
    except ValueError as why:
        return _json(400, {"error": f"the body is not JSON this reads: {why}"})

    said = str(asked.get("said") or "")
    # Pressing Run is the Explicit Request in this first runtime slice. Which
    # input supplied Trigger Evidence is a separate fact the page holds and
    # this does not, so it is sent rather than inferred. No visual cue is
    # classified here; an uploaded image remains evidence attached to the
    # visitor's deliberate request.
    evidence_kind = str(
        asked.get("evidence_kind") or asked.get("trigger") or "speech"
    )
    if evidence_kind not in TRIGGERS:
        return _json(
            400,
            {"error": f"{evidence_kind!r} is not one of {', '.join(TRIGGERS)}"},
        )
    heard = None

    if asked.get("audio"):
        if not audio:
            return _json(
                400,
                {
                    "error": "audio is off unless it is asked for: restart the "
                    "demo with --audio. It goes to hosted transcription, which "
                    "needs a key and costs money on your account"
                },
            )
        spoken = _decoded(asked, "audio")
        if spoken is None:
            return _json(400, {"error": "the audio is not base64"})
        try:
            pcm, rate = wav_to_pcm(spoken)
        except Exception as why:
            return _json(400, {"error": f"this reads 16-bit PCM WAV: {why}"})
        key = load_api_key(API_KEY_FILE)
        if not key:
            return _json(400, {"error": str(MissingApiKey())})
        heard = OpenAITranscriber(key).transcribe(pcm, rate)
        said = heard or said

    seen = None
    selected_image = None
    if asked.get("image"):
        picture = _decoded(asked, "image")
        if picture is None:
            return _json(400, {"error": "the image is not base64"})
        media_type = str(asked.get("image_media_type") or "image/jpeg")
        if not media_type.startswith("image/"):
            return _json(
                400, {"error": "image_media_type must be an image type"}
            )
        try:
            selected_image = SelectedImageEvidence(
                media_type=media_type,
                data_base64=str(asked["image"]),
            )
        except ValueError as error:
            return _json(400, {"error": str(error)})
        frame = decode_image(picture)
        if frame is None:
            return _json(400, {"error": "that image could not be decoded"})
        seen = look_at(frame)

    perceived = {
        "face_present": bool(seen.has_human) if seen else False,
        "distance_cm": seen.distance_cm if seen and seen.has_human else None,
        "is_looking": bool(seen.is_looking) if seen else False,
        "looked": seen is not None,
    }
    answered = {
        "example": asdict(LIVE),
        "provenance": {
            "kind": "live_model_run",
            "kind_means": PROVENANCE["live_model_run"],
            "hardware_unverified": HARDWARE_UNVERIFIED,
            "model": settings.llm_model,
        },
        "perception": perceived,
        "heard": heard,
        "moves": [],
        "runtime": None,
        "storyboard": None,
        "episodes": [],
        "playback": [],
        "why_no_episode": None,
    }

    if not load_api_key(API_KEY_FILE):
        answered["why_no_episode"] = f"{MissingApiKey()}\n\n{ONLY_ONE_REACHES_A_PAGE}"
        return _json(200, answered)

    clock = SystemClock()
    session = simulated_session(seen, model=OpenAIModel(), clock=clock)
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            [
                ScheduledInput(
                    at_s=0.0,
                    input=TimedText(
                        text=said,
                        evidence_kind=EvidenceKind(evidence_kind),
                        facts=perceived,
                        uncertainty=(
                            (
                                "face and gaze come from local perception",
                                "distance is a monocular estimate",
                            )
                            if seen is not None
                            else ()
                        ),
                        selected_image=selected_image,
                    ),
                )
            ],
        ),
        session=session,
        clock=clock,
    ).run()
    episode = result.episodes[0]
    journal = episode.journal
    live, board = _project_journal(journal.records)
    answered["storyboard"] = board
    answered["moves"] = list(what_moves(live))
    answered["runtime"] = _runtime_payload(result)
    # The same shape a recording's Episodes have, so the page draws a live
    # run with the same stage rather than a second, thinner one.
    answered["episodes"] = [
        {
            "actor": "you",
            "cue_id": episode.cue_id,
            "cue_kind": episode.cue_kind,
            "cue_text": said,
            "episode_id": journal.records[0].episode_id,
            "outcome": asdict(episode.outcome),
            "moves": answered["moves"],
            "storyboard": board,
        }
    ]
    answered["playback"] = playback_of(answered, ("you",))
    return _json(200, answered)


def _decoded(asked: Mapping[str, Any], field: str) -> Optional[bytes]:
    try:
        return base64.b64decode(asked[field], validate=True)
    except Exception:
        return None


def _json(status: int, payload) -> Reply:
    return Reply(
        status,
        {"Content-Type": "application/json; charset=utf-8", **NO_STORE},
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# The shell
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Hands the request to `answer` and writes back what it decided."""

    #: Set by `serve`. The shell is where a command-line choice lands.
    audio = False

    def do_GET(self) -> None:  # noqa: N802 — the base class names it
        self._reply(answer("GET", self.path, audio=self.audio))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self._reply(
            answer("POST", self.path, self.rfile.read(length), audio=self.audio)
        )

    def _reply(self, reply: Reply) -> None:
        self.send_response(reply.status)
        for name, value in reply.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        self.wfile.write(reply.body)

    def log_message(self, *args) -> None:
        """Quiet. The terminal belongs to the Episode, not to the transport."""


def serve(
    *, open_browser: bool = True, port: int = ANY_FREE_PORT, audio: bool = False
) -> None:
    """Bind loopback, open a browser, and answer until interrupted."""
    handler = type("_ConfiguredHandler", (_Handler,), {"audio": audio})
    server = HTTPServer((LOOPBACK_ONLY, port), handler)
    where = f"http://{LOOPBACK_ONLY}:{server.server_port}/"
    print(f"demo at {where} — ctrl-c to stop", flush=True)
    if open_browser:
        webbrowser.open(where)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

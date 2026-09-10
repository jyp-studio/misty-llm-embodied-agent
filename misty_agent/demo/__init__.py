"""The demo, as a pure function plus a shell that owns the socket.

`answer(method, path, body)` is everything about HTTP except the socket: a
request in, a status, headers and bytes out. `serve()` is the shell — bind loopback,
open a browser, hand each request to `answer`. The shell is not tested, on the
same grounds `main()` is not: there is nothing in it to get wrong that a test
could see without opening a port.

## Zero new dependencies, and that is an argument rather than a preference

`http.server`, `webbrowser`, hand-written HTML. `requirements.txt` is a
document with a case in it — every package that was removed has its reason
written down — and gradio for one demo page would have pulled twenty-odd back
in and weakened the case (`PLAN.md` §16.4). `tests/test_demo.py` reads this
module's imports rather than trusting the intention.

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
from typing import Any, Mapping, Optional, Tuple

from misty_agent.agent.journal import (
    DecisionNoted,
    Observation,
    ToolCalled,
    from_jsonl,
    to_jsonl,
)
from misty_agent.agent.model import MissingApiKey, OpenAIModel
from misty_agent.agent.storyboard import storyboard_of
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
from misty_agent.perception.asr import OpenAITranscriber, wav_to_pcm
from misty_agent.runtime import (
    AttentionStarted,
    AttentionStopped,
    CueDetected,
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
)
from misty_agent.scenarios import (
    DEMO_SCENARIOS,
    EXPLICIT_TEXT_REQUEST,
    AcceptanceScenario,
    PresentationBeat,
    ScenarioCard,
    ScenarioModel,
)

#: The only address this binds. A demo that listened on every interface would
#: put a Journal — which carries what people said — on whatever network the
#: laptop happens to be on.
LOOPBACK_ONLY = "127.0.0.1"

#: Chosen by the operating system, so two demos cannot collide and nobody has
#: to remember a number.
ANY_FREE_PORT = 0

_HERE = pathlib.Path(__file__).resolve().parent
_PAGE = _HERE / "page.html"
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
#: every time a golden and the implementation disagreed: **six times, and the
#: goldens gave way in five of them.** So the flattering version was false,
#: written in the one place this ticket exists to keep honest.
#:
#: The true version is the better story anyway — a rule that is never invoked
#: is not a rule, and what makes this one worth anything is that each time it
#: was invoked somebody wrote down which side moved.
AMENDMENTS = (
    "It has been amended since. Where a golden and the loop disagreed, which "
    "side gave way is written down — six times so far, and the goldens gave "
    "way in five of them (tests/goldens/README.md). Editing one is allowed; "
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
    #: 「不得讓觀看者搞混哪個是規格、哪個是剛跑的」 is the ticket's line, and
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
            return _run_scenario(scenario_name)
        return _json(405, {"error": f"nothing accepts a POST at {path}"})
    if method != "GET":
        return _json(405, {"error": f"{method} is not something this serves"})
    if path == "/options":
        return _json(200, {"audio": audio})
    if path == "/":
        return Reply(200, {"Content-Type": "text/html; charset=utf-8"}, _PAGE.read_bytes())
    if path == "/scenarios":
        return _json(200, [_scenario_payload(case) for case in DEMO_SCENARIOS])
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


def _scenario_payload(case: ScenarioCard) -> dict:
    """The stable, human-readable facts displayed on a scenario card."""
    return {
        "name": case.name,
        "title": case.title,
        "subtitle": case.subtitle,
        "availability": case.availability,
        "ticket": case.ticket,
        "limitation": case.limitation,
        "preview": [asdict(beat) for beat in case.preview],
    }


def _run_scenario(name: str) -> Reply:
    """Run one named offline scenario through the real runtime seam."""
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

    clock = FakeClock()
    session = simulated_session(
        None,
        model=ScenarioModel(case.decisions),
        clock=clock,
    )
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(clock, case.inputs),
        session=session,
        clock=clock,
    ).run()
    if len(result.episodes) != len(case.actors):
        return _json(
            500,
            {
                "error": (
                    f"scenario {name!r} expected {len(case.actors)} episodes "
                    f"but produced {len(result.episodes)}"
                )
            },
        )
    episodes = []
    for actor, episode in zip(case.actors, result.episodes):
        storyboard, board = _project_journal(episode.journal.records)
        episodes.append(
            {
                "actor": actor,
                "cue_id": episode.cue_id,
                "cue_kind": episode.cue_kind,
                "episode_id": episode.journal.records[0].episode_id,
                "outcome": asdict(episode.outcome),
                "moves": list(what_moves(storyboard)),
                "storyboard": board,
            }
        )
    return _json(
        200,
        {
            "scenario": _scenario_payload(case),
            "execution": _scenario_execution(result, result.episodes[0]),
            "runtime": _runtime_payload(result),
            "episodes": episodes,
        },
    )


def _scenario_execution(
    result: RuntimeResult, episode: RuntimeEpisode
) -> Mapping[str, Any]:
    """Human-readable evidence derived from this run, not its preview."""
    cue = next(
        record for record in result.records if isinstance(record, CueDetected)
    )
    evidence = episode.evidence
    observations = {
        record.turn: record
        for record in episode.journal.records
        if isinstance(record, Observation)
    }
    notes = {
        record.turn: record
        for record in episode.journal.records
        if isinstance(record, DecisionNoted)
    }
    uncertainty = (
        "、".join(evidence.uncertainty)
        if evidence.uncertainty
        else "沒有額外不確定性註記"
    )
    flow = [
        PresentationBeat(
            "input", "人說", f"「{cue.text}」", "這段輸入由案例預先定義。"
        ),
        PresentationBeat(
            "evidence",
            "Trigger Evidence",
            f"{'語音' if evidence.source.value == 'speech' else '圖片'}證據 · "
            f"{evidence.observed_at_s:g} 秒",
            f"{len(evidence.facts)} 個可觀察 facts；不確定性：{uncertainty}",
        ),
        PresentationBeat(
            "cue", "系統判定", "明確互動請求", "Explicit Request"
        ),
    ]
    for record in episode.journal.records:
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
                    "公開目的，不是私有推理。",
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
                    f"「{record.args['text']}」",
                    (
                        "模擬說話成功；Snapshot 已附回下一個 Turn。"
                        if succeeded
                        else "模擬說話未成功；Snapshot 已附回下一個 Turn。"
                    ),
                )
            )
    completed = (
        result.ending is RuntimeEnding.INPUT_EXHAUSTED
        and episode.outcome.outcome == "done"
    )
    flow.append(
        PresentationBeat(
            "ending",
            "結果",
            "情境執行完成" if completed else "情境未正常完成",
            (
                "有限情境已播放完畢，Runtime 正常停止。"
                if completed
                else (
                    f"Episode: {episode.outcome.outcome}; "
                    f"Runtime: {result.ending.value}"
                )
            ),
        )
    )
    return {
        "provenance": {
            "kind": "scripted_current_run",
            "headline": "這是剛剛執行的模擬結果",
            "model": "預設腳本模型",
            "robot": "模擬 Misty",
            "detail": (
                "輸入與模型決策預先定義；Runtime、Tool 與 Journal 由目前程式"
                "重新執行。這不是歷史紀錄、LLM 自主決策或真機結果。"
            ),
        },
        "trigger_evidence": {
            "source": evidence.source.value,
            "observed_at_s": evidence.observed_at_s,
            "facts": dict(evidence.facts),
            "transcript": evidence.transcript,
            "uncertainty": list(evidence.uncertainty),
            "selected_image": evidence.selected_image_media_type is not None,
        },
        "flow": [asdict(beat) for beat in flow],
        "decision_explanation": {
            "available": bool(notes),
            "headline": (
                "Decision Note 已由本次 Journal 記錄"
                if notes
                else "本次 model 未提供 Decision Note"
            ),
            "detail": (
                next(iter(notes.values())).note
                if notes
                else "Tool choice 仍可驗證，但沒有公開目的說明。"
            ),
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
        model=ScenarioModel(EXPLICIT_TEXT_REQUEST.decisions),
        clock=clock,
    )
    runtime = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            clock,
            EXPLICIT_TEXT_REQUEST.inputs,
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
    elif isinstance(record, CueDetected):
        headline = "Explicit Request detected"
        detail = f"{record.evidence_kind} evidence: {record.text or '(no words)'}"
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
        "t": record.t,
        "type": record.type,
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
    "`export` sets the variable in your shell and not in this process — for "
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
        "perception": perceived,
        "heard": heard,
        "moves": [],
        "runtime": None,
        "storyboard": None,
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
    return _json(200, answered)


def _decoded(asked: Mapping[str, Any], field: str) -> Optional[bytes]:
    try:
        return base64.b64decode(asked[field], validate=True)
    except Exception:
        return None


def _json(status: int, payload) -> Reply:
    return Reply(
        status,
        {"Content-Type": "application/json; charset=utf-8"},
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

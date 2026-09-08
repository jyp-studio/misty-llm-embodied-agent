"""The demo, as a pure function plus a shell that owns the socket.

`answer(method, path)` is everything about HTTP except the socket: a request
in, a status, headers and bytes out. `serve()` is the shell — bind loopback,
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

## The examples are read from `tests/goldens/`, not copied

A copy could differ from the spec it claims to be, in the one place a visitor
is asked to take the claim seriously. The cost — this package needing a
sibling directory that an installed copy would not have — is weighed in
`PLAN.md` §16.31.

**Four of the five were written before the ReAct loop existed. The fifth was
not.** It was added at M7 #13, to pin `error` once runtime failure became a
named outcome. So provenance is per example and travels *in the payload*
rather than only in the HTML — a claim printed by JavaScript is a claim no
test here can read, which is the hole `storyboard.py` exists to close.
"""

from __future__ import annotations

import base64
import json
import pathlib
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Mapping, Optional, Tuple

from misty_agent.agent.journal import from_jsonl, to_jsonl
from misty_agent.agent.model import MissingApiKey, OpenAIModel
from misty_agent.agent.storyboard import storyboard_of
from misty_agent.app import (
    API_KEY_FILE,
    SystemClock,
    decode_image,
    load_api_key,
    look_at,
    simulated_session,
)
from misty_agent.perception.asr import OpenAITranscriber, wav_to_pcm

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
#: every time a golden and the implementation disagreed: **five times, and the
#: goldens gave way in four of them.** So the flattering version was false,
#: written in the one place this ticket exists to keep honest.
#:
#: The true version is the better story anyway — a rule that is never invoked
#: is not a rule, and what makes this one worth anything is that each time it
#: was invoked somebody wrote down which side moved.
AMENDMENTS = (
    "It has been amended since. Where a golden and the loop disagreed, which "
    "side gave way is written down — five times so far, and the goldens gave "
    "way in four of them (tests/goldens/README.md). Editing one is allowed; "
    "editing one without saying so is not."
)


@dataclass(frozen=True)
class Example:
    """One built-in Episode, and the honest account of where it came from."""

    name: str
    title: str
    provenance: str
    #: What this Episode *is*, as one word a page can style by and a test can
    #: read. Three, because M8 #10 added a third and a boolean cannot hold it
    #: without the third meaning being smuggled into the false case:
    #:
    #: * `specification` — written before the loop existed;
    #: * `added-later` — the one golden that was not;
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
        return _run(body, audio=audio) if path == "/run" else _json(
            405, {"error": f"nothing accepts a POST at {path}"}
        )
    if method != "GET":
        return _json(405, {"error": f"{method} is not something this serves"})
    if path == "/options":
        return _json(200, {"audio": audio})
    if path == "/":
        return Reply(200, {"Content-Type": "text/html; charset=utf-8"}, _PAGE.read_bytes())
    if path == "/examples":
        return _json(200, [asdict(example) for example in EXAMPLES])
    if path.startswith("/examples/"):
        name, slash, below = path[len("/examples/"):].partition("/")
        if slash:
            return _json(404, {"error": f"nothing is served at {path}"})
        return _example(name)
    return _json(404, {"error": f"nothing is served at {path}"})


def _example(name: str) -> Reply:
    """One golden, as the Storyboard a page draws plus who it claims to be.

    `name` is the only input here that reaches the filesystem, so it is
    matched against the examples rather than joined onto a path: `..` and a
    slash and an encoded slash are all simply not one of five names.
    """
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
    storyboard = storyboard_of(from_jsonl(text))
    board = asdict(storyboard)
    if len(lines) != len(board["moments"]):
        # Cannot happen — `storyboard_of` maps one Moment per record — and it
        # is refused rather than trusted anyway. Pairing them off by position
        # while the two disagree would put one decision's fields under
        # another's sentence, which is worse than showing nothing at all.
        return _json(
            500,
            {
                "error": f"{name!r} has {len(lines)} records and "
                f"{len(board['moments'])} moments"
            },
        )
    for moment, line in zip(board["moments"], lines):
        # The line the Moment was made from, carried *by* it. It used to be a
        # second request the page lined up by index, and a review's mutant
        # paired every Moment with the next one's line while all 1216 tests
        # stayed green — because nothing tests the page. There is nothing to
        # get wrong now.
        moment["line"] = line

    return _json(
        200,
        {
            "example": asdict(found),
            "moves": list(what_moves(storyboard)),
            "storyboard": board,
        },
    )


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
    try:
        asked = json.loads(body or b"{}")
        if not isinstance(asked, dict):
            raise ValueError("expected an object")
    except ValueError as why:
        return _json(400, {"error": f"the body is not JSON this reads: {why}"})

    said = str(asked.get("said") or "")
    heard = None

    if asked.get("audio"):
        if not audio:
            given = _decoded(asked, "audio")
            if given is None:
                return _json(400, {"error": "the audio is not base64"})
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
    if asked.get("image"):
        picture = _decoded(asked, "image")
        if picture is None:
            return _json(400, {"error": "the image is not base64"})
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
        "storyboard": None,
        "why_no_episode": None,
    }

    if not load_api_key(API_KEY_FILE):
        answered["why_no_episode"] = str(MissingApiKey())
        return _json(200, answered)

    session = simulated_session(seen, model=OpenAIModel(), clock=SystemClock())
    _, journal = session.episode(
        "visual" if seen is not None and not said else "speech",
        said,
        render=False,
    )
    board = asdict(storyboard_of(journal.records))
    for moment, line in zip(board["moments"], to_jsonl(journal.records).splitlines()):
        # The same promise the built-ins make, on a run from a moment ago:
        # every Moment carries the record it was made from. There is no file
        # here to read it back from — and there must not be — so it is
        # serialised straight out of the Journal.
        moment["line"] = line
    answered["storyboard"] = board
    answered["moves"] = list(what_moves(storyboard_of(journal.records)))
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

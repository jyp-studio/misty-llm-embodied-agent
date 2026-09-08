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
is being asked to take the claim seriously. `harness/__main__.py` already
reaches into `tests/fixtures/` for the portrait it replays, for the same
reason: the artefact under discussion is the one in the repo.

**Four of the five were written before the ReAct loop existed. The fifth was
not.** It was added at M7 #13, to pin `error` once runtime failure became a
named outcome. So provenance is per example and travels *in the payload*
rather than only in the HTML — a claim printed by JavaScript is a claim no
test here can read, which is the hole `storyboard.py` exists to close.
"""

from __future__ import annotations

import json
import pathlib
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Mapping, Optional, Tuple

from misty_agent.agent.journal import from_jsonl
from misty_agent.agent.storyboard import storyboard_of

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


@dataclass(frozen=True)
class Example:
    """One built-in Episode, and the honest account of where it came from."""

    name: str
    title: str
    provenance: str
    #: The claim a visitor is being asked to believe, as a fact a test can
    #: read. False for the one golden that was written afterwards.
    written_before_the_implementation: bool


EXAMPLES: Tuple[Example, ...] = (
    Example(
        "episode_ends_after_several_turns",
        "Several turns, then it decides it is done",
        _SPEC_FIRST,
        True,
    ),
    Example(
        "episode_ends_on_the_first_turn",
        "Nothing worth doing — it stops immediately",
        _SPEC_FIRST,
        True,
    ),
    Example(
        "episode_fails_during_model_call",
        "The model call fails and the Episode closes",
        "Added at M7 #13, once runtime failure became a named outcome — "
        "unlike the other four, this one was written after the loop it pins",
        False,
    ),
    Example(
        "episode_hits_the_turn_limit",
        "It runs out of turns before it runs out of ideas",
        _SPEC_FIRST,
        True,
    ),
    Example(
        "episode_is_aborted",
        "A foot on the bumper, mid-Episode",
        _SPEC_FIRST,
        True,
    ),
)


@dataclass(frozen=True)
class Reply:
    """What `answer` decided, before anything touches a socket."""

    status: int
    headers: Mapping[str, str]
    body: bytes


def answer(method: str, path: str) -> Reply:
    """Everything about serving the demo except the socket. Pure."""
    if method != "GET":
        return _json(405, {"error": f"{method} is not something this serves"})
    if path == "/":
        return Reply(200, {"Content-Type": "text/html; charset=utf-8"}, _PAGE.read_bytes())
    if path == "/examples":
        return _json(200, [asdict(example) for example in EXAMPLES])
    if path.startswith("/examples/"):
        return _example(path[len("/examples/"):])
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
    records = from_jsonl((_GOLDENS / f"{found.name}.jsonl").read_text(encoding="utf-8"))
    return _json(
        200,
        {"example": asdict(found), "storyboard": asdict(storyboard_of(records))},
    )


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

    def do_GET(self) -> None:  # noqa: N802 — the base class names it
        self._reply(answer("GET", self.path))

    def do_POST(self) -> None:  # noqa: N802
        self._reply(answer("POST", self.path))

    def _reply(self, reply: Reply) -> None:
        self.send_response(reply.status)
        for name, value in reply.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        self.wfile.write(reply.body)

    def log_message(self, *args) -> None:
        """Quiet. The terminal belongs to the Episode, not to the transport."""


def serve(*, open_browser: bool = True, port: int = ANY_FREE_PORT) -> None:
    """Bind loopback, open a browser, and answer until interrupted."""
    server = HTTPServer((LOOPBACK_ONLY, port), _Handler)
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

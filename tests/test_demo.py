"""The demo, answered without opening a socket.

`answer(method, path)` is everything about HTTP except the socket: a request
goes in, a status, headers and bytes come out. `http.server` and `webbrowser`
are a shell around it and are not tested, the same arrangement `main()` has —
the shell is the part with nothing in it to get wrong.

## The examples are the project's own claim, so they are handled carefully

The built-in Episodes are the files in `tests/goldens/`, read from there and
not copied: a copy could differ from the spec it claims to be, in the one
place a visitor is being asked to take the claim seriously.

Four of them were written before the ReAct loop existed. **The fifth was
not** — it was added at M7 #13 to pin the `error` closure path. Labelling all
five "written before the implementation" would be a false claim made in the
most prominent place this project has, which is exactly the thing the ticket
exists to prevent. So provenance is per example, and
`test_every_golden_on_disk_has_been_given_a_provenance` stops a new one
inheriting somebody else's.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

from misty_agent.agent.storyboard import storyboard_of
from misty_agent.demo import (
    ANY_FREE_PORT,
    EXAMPLES,
    LOOPBACK_ONLY,
    Reply,
    answer,
    serve,
)


class _StillbornServer:
    """An `HTTPServer` that binds nothing and stops the moment it starts.

    The shell is not tested — there is nothing in it a test could see
    without opening a port — except the one line of it the ticket makes
    an acceptance criterion: that a browser is opened, at this machine.
    """

    def __init__(self, address, handler):
        self.server_port = address[1]

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass

GOLDENS = pathlib.Path(__file__).resolve().parent / "goldens"


def body_of(path: str) -> dict:
    reply = answer("GET", path)
    assert reply.status == 200, (path, reply.status)
    return json.loads(reply.body)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_the_page_is_served_at_the_root():
    reply = answer("GET", "/")

    assert reply.status == 200
    assert reply.headers["Content-Type"].startswith("text/html")
    assert b"<!doctype html>" in reply.body.lower()


def test_the_examples_can_be_listed():
    listed = body_of("/examples")

    assert [example["name"] for example in listed] == sorted(
        golden.stem for golden in GOLDENS.glob("*.jsonl")
    )


def test_an_example_comes_back_as_a_storyboard():
    payload = body_of("/examples/episode_ends_on_the_first_turn")

    board = payload["storyboard"]
    assert board["outcome"] == "done"
    assert [moment["kind"] for moment in board["moments"]][0] == "episode_started"
    assert board["moments"][-1]["kind"] == "episode_finished"


def test_a_path_that_is_not_a_route_is_a_404():
    assert answer("GET", "/nowhere").status == 404


def test_an_example_nobody_has_is_a_404():
    assert answer("GET", "/examples/episode_that_does_not_exist").status == 404


def test_only_reading_is_allowed():
    for method in ("POST", "PUT", "DELETE"):
        assert answer(method, "/").status == 405, method


@pytest.mark.parametrize(
    "attempt",
    [
        "/examples/../../../etc/passwd",
        "/examples/..%2f..%2fetc%2fpasswd",
        "/examples/subdir/thing",
        "/examples/.",
    ],
)
def test_no_path_can_reach_outside_the_goldens(attempt):
    """The name goes into a filesystem path, so it is the one input here that
    could read something it was never offered."""
    assert answer("GET", attempt).status == 404


# ---------------------------------------------------------------------------
# What the examples claim about themselves
# ---------------------------------------------------------------------------

def test_the_claim_that_an_example_is_a_specification_is_in_the_payload():
    """Not only in the HTML. The spec puts it here on purpose: a label that
    lives in the page is a label no test in this repo can read, which is the
    same hole `storyboard.py` exists to close.
    """
    payload = body_of("/examples/episode_ends_on_the_first_turn")

    assert "before" in payload["example"]["provenance"].lower()
    assert payload["example"]["written_before_the_implementation"] is True


def test_the_claim_travels_with_what_happened_to_it_afterwards():
    """The first version of this banner said the loop "had to be built to
    produce it, not the other way round". That was false.

    `tests/goldens/README.md` keeps a table of every time a golden and the
    implementation disagreed: five times, and **the goldens gave way in four
    of them**. Saying otherwise was a flattering claim in the one place this
    ticket exists to keep honest. The caveat therefore ships in the same
    object as the boast, so one cannot be kept without the other.
    """
    example = body_of("/examples/episode_ends_on_the_first_turn")["example"]

    assert example["written_before_the_implementation"] is True
    assert "amended" in example["amendments"].lower()
    assert "four of them" in example["amendments"]


def test_the_amendment_count_is_the_one_the_goldens_record():
    """Read off the README rather than remembered, because a sixth invocation
    of the rule would otherwise leave the page quoting a stale number."""
    table = (GOLDENS / "README.md").read_text()
    gave_way = [line for line in table.splitlines() if line.startswith("| ")]
    goldens_gave_way = [line for line in gave_way if "the golden" in line]

    assert len(goldens_gave_way) == 4
    assert f"five times" in EXAMPLES[0].amendments


def test_the_golden_that_came_later_does_not_claim_it_came_first():
    """`tests/goldens/README.md`: the original four were derived from M7's
    spec; the fifth was added at M7 #13 to pin the `error` path once runtime
    failure became a named outcome. Saying otherwise would be a false claim
    in the most prominent place this project has.
    """
    payload = body_of("/examples/episode_fails_during_model_call")

    assert payload["example"]["written_before_the_implementation"] is False
    assert "M7 #13" in payload["example"]["provenance"]


def test_every_golden_on_disk_has_been_given_a_provenance():
    """A sixth golden must not quietly inherit the other five's claim."""
    on_disk = {golden.stem for golden in GOLDENS.glob("*.jsonl")}

    assert {example.name for example in EXAMPLES} == on_disk


def test_the_four_ways_an_episode_can_end_are_all_on_offer():
    """Which is why these files were chosen as the examples at all."""
    outcomes = {
        body_of(f"/examples/{example.name}")["storyboard"]["outcome"]
        for example in EXAMPLES
    }

    assert outcomes == {"done", "turn_limit", "aborted", "error"}


def test_an_example_is_the_golden_file_itself_not_a_copy_of_it():
    """Read from `tests/goldens/`, so what the page shows and what the
    project claims cannot drift apart. A copy inside the package would be a
    second version of the one artefact whose whole value is being the first.
    """
    board = body_of("/examples/episode_is_aborted")["storyboard"]
    on_disk = [
        json.loads(line)
        for line in (GOLDENS / "episode_is_aborted.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert len(board["moments"]) == len(on_disk)
    assert [m["t"] for m in board["moments"]] == [r["t"] for r in on_disk]


def test_a_visitor_is_told_which_parts_of_the_robot_this_episode_moves():
    """`PLAN.md` §16.31: no golden ever lights the chest or moves the arms,
    so three of the four readouts sit at their defaults for a whole run. A
    panel that just says `off` reads as broken. Worked out in Python, like
    every other display decision here.
    """
    scans = body_of("/examples/episode_hits_the_turn_limit")
    stops_at_once = body_of("/examples/episode_ends_on_the_first_turn")

    assert scans["moves"] == ["head"]
    assert stops_at_once["moves"] == []


# ---------------------------------------------------------------------------
# Traceability: every Moment carries the line it was made from
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("example", [e.name for e in EXAMPLES])
def test_every_moment_carries_the_line_it_was_made_from(example):
    """M8 #09's load-bearing box. Why the line and not `Moment.facts` is
    argued once, in `PLAN.md` §16.37.

    Every record of the golden, in order, on the Moment made from it.
    """
    on_disk = [
        line
        for line in (GOLDENS / f"{example}.jsonl").read_bytes().decode().split("\n")
        if line.strip()
    ]
    moments = body_of(f"/examples/{example}")["storyboard"]["moments"]

    assert [moment["line"] for moment in moments] == on_disk


@pytest.mark.parametrize("example", [e.name for e in EXAMPLES])
def test_the_line_on_a_moment_is_that_moment_and_not_its_neighbour(example):
    """The failure this shape exists to make impossible.

    The line used to arrive as a second request that the page lined up by
    index. A review's mutant paired every Moment with the *next* one's line
    and all 1216 tests stayed green, because nothing tests the page — a
    visitor would have read one decision's fields under another's sentence,
    which §16.37 calls worse than showing nothing. Carried on the Moment,
    there is no pairing left to get wrong; asserted anyway.
    """
    for moment in body_of(f"/examples/{example}")["storyboard"]["moments"]:
        record = json.loads(moment["line"])

        assert record["type"] == moment["kind"]
        assert record["t"] == moment["t"]


def test_the_line_is_the_bytes_on_disk_rather_than_a_rendering_of_them(
    tmp_path, monkeypatch
):
    """Serving `to_jsonl(from_jsonl(text))` passes against a golden, because a
    golden is already in exactly that form. Two axes tell them apart, and a
    review found the first version only tested one of them:

    * key order and spacing — a re-render sorts and normalises;
    * **line endings** — `read_text` silently turns `\r\n` into `\n`, so
      reading as text loses the very fidelity being claimed.
    """
    odd = (
        b'{"type": "turn_started",  "turn": 1, "t": 0.0, '
        b'"episode_id": "\xc3\xa9p-1"}\r\n'
    )
    monkeypatch.setattr("misty_agent.demo._GOLDENS", tmp_path)
    (tmp_path / f"{EXAMPLES[0].name}.jsonl").write_bytes(odd)

    (moment,) = body_of(f"/examples/{EXAMPLES[0].name}")["storyboard"]["moments"]

    assert moment["line"] == odd.decode("utf-8").rstrip("\n")


def test_records_and_moments_that_disagree_are_refused_not_paired(
    tmp_path, monkeypatch
):
    """It cannot happen — `storyboard_of` maps one Moment per record — and it
    is refused rather than trusted anyway, because the failure it would cause
    is the one this whole shape is built to prevent."""
    monkeypatch.setattr("misty_agent.demo._GOLDENS", tmp_path)
    (tmp_path / f"{EXAMPLES[0].name}.jsonl").write_text(
        '{"type": "turn_started", "turn": 1, "t": 0.0, "episode_id": "ep-1"}\n'
    )
    monkeypatch.setattr(
        "misty_agent.demo.storyboard_of",
        lambda records: storyboard_of(records * 2),
    )

    reply = answer("GET", f"/examples/{EXAMPLES[0].name}")

    assert reply.status == 500
    assert b"1 records and 2 moments" in reply.body


@pytest.mark.parametrize(
    "attempt",
    [
        "/examples/episode_is_aborted/journal",
        "/examples/episode_is_aborted/my-journal",
        "/examples/episode_is_aborted/anything",
        "/examples/../goldens/journal",
    ],
)
def test_nothing_below_an_example_is_served(attempt):
    """Including paths that merely *end* in something known — a check written
    with `endswith` instead of a whole-segment match passed every case the
    first version of this list contained."""
    reply = answer("GET", attempt)

    assert reply.status == 404
    assert b"nothing is served at" in reply.body


# ---------------------------------------------------------------------------
# The two promises that are about what this does not do
# ---------------------------------------------------------------------------

def test_the_demo_adds_no_dependency():
    """`requirements.txt` is a document with an argument in it — every package
    that was removed has its reason written down (`PLAN.md` §16.4). A demo
    page that added one back would weaken the argument, so this reads the
    imports rather than trusting the intention.
    """
    source = pathlib.Path(
        sys.modules["misty_agent.demo"].__file__
    ).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}

    outside = imported - set(sys.stdlib_module_names) - {"misty_agent"}
    assert outside == set()


def test_the_server_is_offered_to_nobody_but_this_machine():
    """A demo that binds every interface puts a robot's Journal — with what
    people said in it — on whatever network the laptop is on."""
    assert LOOPBACK_ONLY == "127.0.0.1"


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_answering_is_pure():
    """Same question, same answer, no accumulated state."""
    assert answer("GET", "/examples") == answer("GET", "/examples")


@pytest.mark.parametrize(
    "method,path,kind",
    [
        ("GET", "/", "text/html"),
        ("GET", "/examples", "application/json"),
        ("GET", "/examples/episode_is_aborted", "application/json"),
        ("GET", "/nope", "application/json"),
        ("POST", "/", "application/json"),
    ],
)
def test_every_reply_says_what_it_actually_is(method, path, kind):
    """Named, not merely present. Asserting the header is truthy passed a
    version that answered every route as `text/plain`, which a browser
    renders as the source of the page it was asked for."""
    reply = answer(method, path)

    assert isinstance(reply, Reply)
    assert reply.headers["Content-Type"].startswith(kind)
    assert isinstance(reply.body, bytes)


def test_an_example_whose_file_has_gone_is_answered_not_raised(monkeypatch):
    """`answer` promises a status, headers and bytes for every request. A
    named example with no file behind it means this copy of the project is
    incomplete — which is a 500 and a sentence, not a traceback into a blank
    page.
    """
    monkeypatch.setattr(
        "misty_agent.demo._GOLDENS", pathlib.Path("/definitely/not/here")
    )

    reply = answer("GET", "/examples/episode_is_aborted")

    assert reply.status == 500
    assert b"missing" in reply.body


def test_the_browser_is_opened_and_pointed_at_this_machine(monkeypatch):
    """The one part of the shell that is an acceptance criterion — 「瀏覽器
    自動打開，不需要記網址或埠號」. Flipping the default to False left every
    other test green while the command did nothing visible.
    """
    opened = []
    monkeypatch.setattr("misty_agent.demo.webbrowser.open", opened.append)
    monkeypatch.setattr("misty_agent.demo.HTTPServer", _StillbornServer)

    serve(port=54321)

    assert opened == ["http://127.0.0.1:54321/"]


def test_the_port_is_the_operating_systems_to_choose():
    """Zero, so two demos cannot collide and nobody types a number. A fixed
    one is the second machine on a desk failing to start."""
    assert ANY_FREE_PORT == 0

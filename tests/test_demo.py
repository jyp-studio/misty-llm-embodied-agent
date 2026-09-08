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

from misty_agent.demo import (
    EXAMPLES,
    LOOPBACK_ONLY,
    Reply,
    answer,
)

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


def test_every_reply_says_what_it_is():
    for method, path in [("GET", "/"), ("GET", "/examples"), ("GET", "/nope"), ("POST", "/")]:
        reply = answer(method, path)
        assert isinstance(reply, Reply)
        assert reply.headers["Content-Type"]
        assert isinstance(reply.body, bytes)

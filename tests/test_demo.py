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
import base64
import json
import pathlib
import sys

import pytest

from misty_agent.agent.model import API_KEY_VARIABLE
from misty_agent.agent.storyboard import storyboard_of
from misty_agent.demo import (
    ANY_FREE_PORT,
    EXAMPLES,
    LOOPBACK_ONLY,
    Reply,
    answer,
    serve,
)

from conftest import FIXTURES, SKIP_REASON
from test_app import Says


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
    assert payload["example"]["kind"] == "specification"


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

    assert example["kind"] == "specification"
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

    assert payload["example"]["kind"] == "added-later"
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
# Running something of your own
# ---------------------------------------------------------------------------

def a_portrait(scale: float = 1.0) -> bytes:
    """The fixture photograph as bytes, as an upload would arrive."""
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    frame = cv2.imread(str(FIXTURES / "frontal_face_portrait.jpg"))
    if scale != 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", frame)[1].tobytes()


def run(said="hello", image=None, wav=None, **rest):
    """A POST as the page makes it. `rest` goes to `answer` — that is where
    the `audio=` switch lives, and it is not the same thing as sending one."""
    asked = {"said": said}
    if image is not None:
        asked["image"] = base64.b64encode(image).decode()
    if wav is not None:
        asked["audio"] = base64.b64encode(wav).decode()
    return answer("POST", "/run", json.dumps(asked).encode(), **rest)


def test_a_photograph_from_the_page_goes_through_the_real_pipeline(monkeypatch):
    """The half that is free: mediapipe runs here, on this machine, and needs
    no key. Somebody with no key still finds out what the camera made of
    their photograph."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.demo.load_api_key", lambda path: None)

    seen = json.loads(run(image=a_portrait()).body)["perception"]

    assert seen["face_present"] is True
    assert seen["distance_cm"] == 52
    assert seen["is_looking"] is True


def test_without_a_key_it_says_why_there_are_no_decisions(monkeypatch):
    """Criterion: 「說明為什麼沒有後續決策、以及怎麼提供 key」. `MissingApiKey`
    already writes that paragraph and names both channels (§16.24), so this
    hands over that one rather than composing a second."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.demo.load_api_key", lambda path: None)

    payload = json.loads(run(image=a_portrait()).body)

    assert payload["storyboard"] is None
    assert API_KEY_VARIABLE in payload["why_no_episode"]
    assert "OAI_CONFIG_LIST.json" in payload["why_no_episode"]


def test_with_a_key_it_runs_and_comes_back_the_same_shape_as_an_example(
    monkeypatch,
):
    """Criterion: 「結果用與內建範例**相同的**呈現路徑顯示」. Not similar —
    the same keys, so the page draws it with the code it already has."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: Says("speak", "done"))

    live = json.loads(run(said="come here", image=a_portrait(0.5)).body)
    built_in = body_of("/examples/episode_is_aborted")

    assert set(live) >= set(built_in)
    assert live["storyboard"]["outcome"] == "done"
    assert [m["kind"] for m in live["storyboard"]["moments"]][0] == "episode_started"


def test_a_live_run_carries_every_line_of_its_own_journal(monkeypatch):
    """The traceability of #09, on a run that just happened — not only on the
    built-ins. Nothing was written to disk to get it (`to_jsonl` is the
    serialisation, `JsonlFile` is the one that writes)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: Says("speak", "done"))

    moments = json.loads(run().body)["storyboard"]["moments"]

    for moment in moments:
        assert json.loads(moment["line"])["type"] == moment["kind"]


def test_what_the_person_said_is_what_the_model_is_asked_about(monkeypatch):
    """Criterion: 「頁面上可以輸入使用者說的話當作觸發」."""
    asked = Says("done")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: asked)

    run(said="are you there")

    spoken = [e for e in asked.contexts[0] if e["role"] == "user"]
    assert spoken[0]["content"]["said"] == "are you there"


def test_a_live_run_cannot_be_mistaken_for_a_specification(monkeypatch):
    """Criterion: 「不得讓觀看者搞混哪個是規格、哪個是剛跑的」.

    Three kinds, not a boolean with a third meaning bolted on: a golden
    written first, the one added afterwards, and something that happened a
    moment ago on this machine.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: Says("done"))

    live = json.loads(run().body)["example"]
    spec_first = body_of("/examples/episode_ends_on_the_first_turn")["example"]
    came_later = body_of("/examples/episode_fails_during_model_call")["example"]

    assert live["kind"] == "live"
    assert spec_first["kind"] == "specification"
    assert came_later["kind"] == "added-later"
    assert live["amendments"] == ""
    assert "just now" in live["provenance"].lower()


def test_nothing_uploaded_is_left_behind(monkeypatch, tmp_path):
    """Criterion: 「上傳的檔案不會被留在磁碟上」. The image is decoded in
    memory; the only thing in this project that writes a run down is
    `JsonlFile`, and reaching it takes the `--journal` flag (#06)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: Says("done"))
    monkeypatch.chdir(tmp_path)

    run(image=a_portrait())

    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Audio: supported, and off unless somebody asks
# ---------------------------------------------------------------------------

def a_spoken_wav(seconds: float = 0.3) -> bytes:
    """A WAV a browser could have recorded. Silence is enough — what is being
    tested is that it reaches the transcriber, not what it says."""
    import numpy as np

    from misty_agent.perception.asr import pcm_to_wav

    return pcm_to_wav(np.zeros(int(16000 * seconds), dtype=np.float32), 16000)


def test_audio_is_refused_unless_somebody_turned_it_on():
    """It costs money on somebody else's account and needs a key, so it is a
    choice rather than a default. `--demo` alone does not enable it."""
    reply = run(wav=a_spoken_wav())

    assert reply.status == 400
    assert b"--audio" in reply.body


def test_the_page_is_told_whether_audio_is_on_offer():
    assert json.loads(answer("GET", "/options").body) == {"audio": False}
    assert json.loads(answer("GET", "/options", audio=True).body) == {"audio": True}


def test_audio_that_was_asked_for_is_transcribed_and_becomes_what_was_said(
    monkeypatch,
):
    """The caller the ticket asks for: 「否則 ASR 那條路會變成下一個『造好沒接
    線』的東西」. `OpenAITranscriber` had no production caller until here.
    """
    heard = []

    class Hears:
        def transcribe(self, pcm, sample_rate):
            heard.append((len(pcm), sample_rate))
            return "is that you"

    asked = Says("done")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: asked)
    monkeypatch.setattr("misty_agent.demo.OpenAITranscriber", lambda key: Hears())

    payload = json.loads(run(said="", wav=a_spoken_wav(), audio=True).body)

    assert heard == [(4800, 16000)]
    assert payload["heard"] == "is that you"
    spoken = [e for e in asked.contexts[0] if e["role"] == "user"]
    assert spoken[0]["content"]["said"] == "is that you"


def test_audio_that_is_not_a_wav_is_refused_with_a_reason():
    reply = run(wav=b"this is not a wav at all", audio=True)

    assert reply.status == 400
    assert b"WAV" in reply.body


# ---------------------------------------------------------------------------
# What a POST may not do
# ---------------------------------------------------------------------------

def test_a_body_that_is_not_json_is_refused():
    reply = answer("POST", "/run", b"{not json")

    assert reply.status == 400
    assert b"JSON" in reply.body


def test_posting_anywhere_else_is_still_refused():
    assert answer("POST", "/", b"{}").status == 405
    assert answer("POST", "/examples", b"{}").status == 405


def test_an_image_that_is_not_an_image_is_refused_with_a_reason():
    reply = run(image=b"nothing decodable here")

    assert reply.status == 400
    assert b"image" in reply.body.lower()


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

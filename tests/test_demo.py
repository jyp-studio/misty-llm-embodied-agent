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
from misty_agent.app import DEFAULT_START_CM
from misty_agent.agent.storyboard import storyboard_of
from misty_agent.demo import (
    HARDWARE_UNVERIFIED,
    PROVENANCE,
    ANY_FREE_PORT,
    MOST_ONE_REQUEST_MAY_CARRY,
    EXAMPLES,
    RUNTIME_EXAMPLE,
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

    handler = None

    def __init__(self, address, handler):
        self.server_port = address[1]
        _StillbornServer.handler = handler

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


def test_the_page_leads_with_three_readable_social_scenarios():
    """The portfolio Demo starts with situations, not ReAct failure modes."""
    page = answer("GET", "/").body.decode("utf-8")

    assert '<html lang="zh-Hant">' in page
    assert page.count('class="scenario-card') == 3
    assert page.count('<strong data-card-title>') == 3
    assert page.count('<small data-card-status>') == 3
    assert page.count('<span data-card-subtitle>') == 3
    assert "執行離線模擬" in page
    assert 'id="executionResult"' in page
    assert 'id="replayJournal"' in page
    assert 'id="wakeFixture"' in page
    assert 'id="audioBadge"' in page
    assert "JSON.stringify(fixture ? { fixture } : {})" in page
    assert "storyboard?.moments" in page
    assert "runSerial" in page
    assert "state.runSerial !== runId" in page
    assert 'id="runFacts"' not in page
    assert "SCRIPTED CUE" not in page
    assert "SCRIPTED HANDOFF" not in page
    assert 'textContent = "這次情境執行完成"' not in page
    assert "Live AI" in page and "需要 API key" in page
    assert "#16151a" not in page
    assert "opacity: .18" not in page


def test_the_three_social_scenarios_are_the_only_primary_choices():
    listed = body_of("/scenarios")

    assert [scenario["name"] for scenario in listed] == [
        "greeting",
        "crying-care",
        "speaker-handoff",
    ]
    assert [scenario["title"] for scenario in listed] == [
        "有人和 Misty 打招呼",
        "有人在 Misty 面前哭泣",
        "A 聊完後，切換成 B",
    ]
    assert all(len(scenario["preview"]) == 3 for scenario in listed)
    assert listed[0]["availability"] == "ready"
    assert listed[0]["ticket"] == "05"
    assert [fixture["key"] for fixture in listed[0]["audio_fixtures"]] == [
        "hey-normal",
        "hi-slow",
        "hey-fast",
        "hey-pause",
    ]
    assert [fixture["key"] for fixture in listed[0]["visual_fixtures"]] == [
        "visual-empty-room",
        "visual-passerby",
        "visual-gaze-wave",
        "visual-two-people",
    ]
    assert {fixture["input_kind"] for fixture in listed[0]["fixtures"]} == {
        "audio",
        "visual",
        "text",
    }
    assert listed[1]["availability"] == "ready"
    assert listed[1]["ticket"] == "07"
    assert [fixture["key"] for fixture in listed[1]["visual_fixtures"]] == [
        "care-sustained-signals",
        "care-expression-words-conflict",
    ]
    assert listed[2]["availability"] == "ready"
    assert listed[2]["ticket"] == "12"


def run_scenario(name: str) -> dict:
    reply = answer("POST", f"/scenarios/{name}/run")
    assert reply.status == 200, (name, reply.status, reply.body)
    return json.loads(reply.body)


def test_the_selected_fixture_runs_local_wake_before_the_episode():
    reply = answer(
        "POST",
        "/scenarios/greeting/run",
        json.dumps({"fixture": "hi-slow"}).encode(),
    )
    assert reply.status == 200
    payload = json.loads(reply.body)

    audio = [
        record
        for record in payload["runtime"]["records"]
        if record["type"] == "audio_attention"
    ]
    assert [(item["stage"], item["outcome"]) for item in audio] == [
        ("wake", "matched"),
        ("capture", "captured"),
        ("asr", "transcribed"),
    ]
    assert audio[0]["facts"]["wake_phrase"] == "hi misty"
    assert payload["execution"]["provenance"]["audio"] == (
        "Hi Misty · 慢速"
    )
    assert [beat["kind"] for beat in payload["execution"]["flow"][:3]] == [
        "wake",
        "capture",
        "asr",
    ]


def test_an_unknown_wake_fixture_is_refused_by_name():
    reply = answer(
        "POST",
        "/scenarios/greeting/run",
        json.dumps({"fixture": "not-there"}).encode(),
    )

    assert reply.status == 400
    assert b"not-there" in reply.body


def test_the_visual_fixture_runs_the_temporal_gate_and_one_episode():
    reply = answer(
        "POST",
        "/scenarios/greeting/run",
        json.dumps({"fixture": "visual-gaze-wave"}).encode(),
    )
    assert reply.status == 200
    payload = json.loads(reply.body)

    assert len(payload["episodes"]) == 1
    assert payload["episodes"][0]["cue_kind"] == "social_invitation"
    execution = payload["execution"]
    assert execution["provenance"]["input_kind"] == "visual"
    assert execution["provenance"]["fixture"] == "持續看向 Misty 並揮手"
    assert execution["trigger_evidence"]["transcript"] == ""
    assert execution["trigger_evidence"]["selected_image"] is True
    assert execution["selected_evidence"] == {
        "count": 1,
        "media_type": "image/jpeg",
        "selected_frame_index": 3,
    }
    assert [item["outcome"] for item in execution["visual_timeline"]] == [
        "tracking",
        "wave_progress",
        "wave_progress",
        "qualified",
    ]
    speak = next(
        beat for beat in execution["flow"] if beat["kind"] == "observation"
    )
    assert speak["headline"] == "「嗨，需要我嗎？」"
    assert "data_base64" not in json.dumps(payload)
    assert all(beat["kind"] != "approach" for beat in execution["flow"])


@pytest.mark.parametrize(
    ("fixture", "outcomes"),
    [
        ("visual-empty-room", ["empty", "empty", "empty"]),
        ("visual-passerby", ["not_looking"] * 3),
    ],
)
def test_a_visual_negative_fixture_explains_why_no_episode_opened(
    fixture, outcomes
):
    reply = answer(
        "POST",
        "/scenarios/greeting/run",
        json.dumps({"fixture": fixture}).encode(),
    )
    assert reply.status == 200
    payload = json.loads(reply.body)

    assert payload["episodes"] == []
    assert payload["runtime"]["ending"] == "input_exhausted"
    assert [
        item["outcome"] for item in payload["execution"]["visual_timeline"]
    ] == outcomes
    assert payload["execution"]["trigger_evidence"] is None
    assert payload["execution"]["provenance"]["model"] == "未呼叫"
    assert payload["execution"]["decision_explanation"] == {
        "available": False,
        "headline": "本機 gate 沒有開啟互動",
        "detail": "沒有足夠的持續注視加揮手證據，因此 model 沒有被呼叫。",
    }
    assert payload["execution"]["flow"][-1]["headline"] == (
        "保持安靜，沒有開啟 Episode"
    )


def test_the_greeting_card_runs_the_runtime_without_an_api_key(monkeypatch):
    def key_was_not_asked_for(path):
        pytest.fail(f"offline scenario tried to load an API key from {path}")

    monkeypatch.setattr("misty_agent.demo.load_api_key", key_was_not_asked_for)

    payload = run_scenario("greeting")

    assert payload["scenario"]["availability"] == "ready"
    assert payload["runtime"]["ending"] == "input_exhausted"
    assert len(payload["episodes"]) == 4
    assert [episode["actor"] for episode in payload["episodes"]] == [
        "person",
        "person",
        "person",
        "person",
    ]
    assert all(
        episode["storyboard"]["outcome"] == "done"
        for episode in payload["episodes"]
    )


def test_the_current_run_explains_active_and_queued_cues_in_plain_language():
    payload = run_scenario("greeting")

    attention = payload["execution"]["attention"]
    assert attention["active_cue"] is None
    assert [item["cue_id"] for item in attention["active_history"]] == [
        "cue-1",
        "cue-4",
        "cue-6",
        "cue-7",
    ]
    assert attention["queue_capacity"] == 3
    assert [event["type"] for event in attention["events"]] == [
        "cue_queued",
        "cue_deduplicated",
        "cue_replaced",
        "cue_queued",
        "cue_queued",
        "cue_dropped",
        "cue_queued",
        "cue_dropped",
        "cue_dequeued",
        "cue_dequeued",
        "cue_dequeued",
    ]
    assert {event.get("reason") for event in attention["events"]} >= {
        "overflow",
        "expired",
        None,
    }
    page = answer("GET", "/").body.decode("utf-8")
    assert 'id="attentionState"' in page
    assert 'id="activeCue"' in page
    assert 'id="cueQueue"' in page
    assert "execution.attention.events" in page


def test_the_greeting_result_says_what_the_current_run_actually_did():
    payload = run_scenario("greeting")

    execution = payload["execution"]
    assert execution["provenance"] == {
        "kind": "scripted_run",
        "kind_means": PROVENANCE["scripted_run"],
        "hardware_unverified": HARDWARE_UNVERIFIED,
        "headline": "這是剛剛執行的模擬結果",
        "model": "預設腳本模型",
        "robot": "模擬 Misty",
        "detail": (
            "選定的 synthetic WAV 由目前程式執行本機 wake detection；"
            "ASR、模型決策與其餘 Cue 時間為預先定義，robot 為模擬。"
            "Runtime、queue、Tool 與 Journal 都在這次重新執行。"
        ),
        "audio": "Hey Misty · 一般語速",
        "fixture": "Hey Misty · 一般語速",
        "input_kind": "audio",
    }
    evidence = execution["trigger_evidence"]
    assert evidence["source"] == "speech"
    assert evidence["transcript"] == "Misty，你好！"
    assert evidence["facts"]["wake_phrase"] == "hey misty"
    assert evidence["facts"]["confidence"] >= 0.78
    assert evidence["facts"]["detector"] == "pocketsphinx-local"
    assert evidence["facts"]["capture"] == "captured"
    assert evidence["uncertainty"] == [
        "local wake detection is verified only on synthetic fixtures"
    ]
    assert evidence["selected_image"] is False
    kinds = [beat["kind"] for beat in execution["flow"]]
    # The first Episode; ticket 08 shows every Episode of the run rather
    # than only the first one. The queued texts carry no anonymous track, so
    # they are not announced as another person.
    assert kinds[:10] == [
        "wake",
        "capture",
        "asr",
        "input",
        "evidence",
        "cue",
        "target_bound",
        "skills_available",
        "decision_note",
        "tool_call",
    ]
    assert "handoff_requested" not in kinds
    assert kinds.count("target_bound") == len(payload["episodes"]) == 4
    assert kinds.count("cue_dequeued") == 3
    assert kinds[-1] == "ending"
    assert execution["flow"][-1] == {
        "kind": "ending",
        "label": "結果",
        "headline": "情境執行完成",
        "detail": "有限情境已播放完畢，Runtime 正常停止。",
    }
    assert execution["decision_explanation"] == {
        "available": True,
        "headline": "Decision Note 已由本次 Journal 記錄",
        "detail": "先確認問候來自哪個方向。",
    }
    moments = payload["episodes"][0]["storyboard"]["moments"]
    assert [moment["kind"] for moment in moments].count("decision_noted") == 3
    assert "data_base64" not in json.dumps(payload)


def test_the_human_ending_is_derived_from_an_abnormal_current_run(monkeypatch):
    class NeverDoneModel:
        def decide(self, working_context, tools):
            return Says("speak").decide(working_context, tools)

    # Patched where the scenario is actually run: ticket 15 moved that out of
    # the Demo into the runner the acceptance tests share with it.
    monkeypatch.setattr(
        "misty_agent.acceptance.ScenarioModel", lambda decisions: NeverDoneModel()
    )

    payload = run_scenario("greeting")

    assert payload["execution"]["flow"][-1] == {
        "kind": "ending",
        "label": "結果",
        "headline": "情境未正常完成",
        "detail": "Episode: turn_limit; Runtime: input_exhausted",
    }


def test_both_care_cases_run_and_show_evidence_choice_and_ending():
    for fixture, expected_tool in (
        ("care-sustained-signals", "observe_target"),
        ("care-expression-words-conflict", "inspect_scene"),
    ):
        reply = answer(
            "POST",
            "/scenarios/crying-care/run",
            json.dumps({"fixture": fixture}).encode(),
        )
        assert reply.status == 200
        payload = json.loads(reply.body)

        assert payload["scenario"]["availability"] == "ready"
        assert payload["episodes"][0]["cue_kind"] == "care_cue"
        flow = payload["execution"]["flow"]
        assert any(beat["kind"] == "evidence" for beat in flow)
        assert any(
            beat["kind"] == "decision_note" for beat in flow
        )
        assert any(
            beat["kind"] == "tool_call"
            and beat["headline"] == expected_tool
            for beat in flow
        )
        assert flow[-1]["kind"] == "ending"
        assert flow[-1]["headline"] == "情境執行完成"
        called = [
            record["facts"]["tool"]
            for record in payload["episodes"][0]["storyboard"]["moments"]
            if record["kind"] == "tool_called"
        ]
        assert "approach" not in called


def test_a_planned_scenario_cannot_be_run_before_its_ticket(monkeypatch):
    """No card is planned any more, so the refusal path is exercised with a
    roadmap card patched in: the Demo must still refuse to run a preview."""
    from misty_agent import demo
    from misty_agent.scenarios import PlannedScenario, ScenarioAvailability

    planned = PlannedScenario(
        name="future-card", title="未來", subtitle="預覽", ticket="99",
        availability=ScenarioAvailability.PLANNED, limitation="尚未實作", preview=(),
    )
    monkeypatch.setattr(demo, "DEMO_SCENARIOS", (*demo.DEMO_SCENARIOS, planned))

    reply = answer("POST", "/scenarios/future-card/run")

    assert reply.status == 409
    assert json.loads(reply.body) == {
        "error": "scenario 'future-card' is planned for ticket 99",
        "ticket": "99",
    }


def test_a_scenario_name_cannot_be_used_as_a_path():
    assert answer("POST", "/scenarios/../greeting/run").status == 405
    assert answer("POST", "/scenarios/not-a-case/run").status == 404


def test_the_examples_can_be_listed():
    listed = body_of("/examples")

    assert [example["name"] for example in listed] == sorted(
        golden.stem for golden in GOLDENS.glob("*.jsonl")
    ) + [RUNTIME_EXAMPLE.name]


def test_the_old_runtime_example_link_remains_an_alias():
    old_link = body_of("/examples/runtime_explicit_text_request")
    current_link = body_of(f"/examples/{RUNTIME_EXAMPLE.name}")

    assert old_link == current_link


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
    implementation disagreed: eight times, and **the goldens gave way in
    seven of them**. Saying otherwise was a flattering claim in the one place this
    ticket exists to keep honest. The caveat therefore ships in the same
    object as the boast, so one cannot be kept without the other.
    """
    example = body_of("/examples/episode_ends_on_the_first_turn")["example"]

    assert example["kind"] == "specification"
    assert "amended" in example["amendments"].lower()
    assert "seven of them" in example["amendments"]


def test_the_amendment_count_is_the_one_the_goldens_record():
    """Read off the README rather than remembered, because a sixth invocation
    of the rule would otherwise leave the page quoting a stale number."""
    table = (GOLDENS / "README.md").read_text()
    gave_way = [line for line in table.splitlines() if line.startswith("| ")]
    goldens_gave_way = [line for line in gave_way if "the golden" in line]

    assert len(goldens_gave_way) == 7
    assert f"eight times" in EXAMPLES[0].amendments


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


def run(
    said="hello",
    image=None,
    wav=None,
    trigger=None,
    evidence_kind=None,
    **rest,
):
    """A POST as the page makes it. `rest` goes to `answer` — that is where
    the `audio=` switch lives, and it is not the same thing as sending one."""
    asked = {"said": said}
    if trigger is not None:
        asked["trigger"] = trigger
    if evidence_kind is not None:
        asked["evidence_kind"] = evidence_kind
    if image is not None:
        asked["image"] = base64.b64encode(image).decode()
    if wav is not None:
        asked["audio"] = base64.b64encode(wav).decode()
    return answer("POST", "/run", json.dumps(asked).encode(), **rest)


def first_trigger_evidence(model):
    message = next(
        entry for entry in model.contexts[0] if entry["role"] == "user"
    )
    return message["content"][0]["text"]["trigger_evidence"]


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


def test_selected_image_and_perception_facts_reach_the_first_model_turn(
    monkeypatch,
):
    asked = Says("done")
    picture = a_portrait(0.5)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: asked)

    payload = json.loads(
        run(
            said="Misty, can you see me?",
            image=picture,
            evidence_kind="visual",
        ).body
    )

    evidence = next(
        entry for entry in asked.contexts[0] if entry["role"] == "user"
    )["content"]
    assert evidence[0]["text"]["trigger_evidence"] == {
        "source": "visual",
        "observed_at_s": 0.0,
        "facts": payload["perception"],
        "transcript": "Misty, can you see me?",
        "uncertainty": [
            "face and gaze come from local perception",
            "distance is a monocular estimate",
        ],
    }
    assert evidence[1] == {
        "type": "image",
        "media_type": "image/jpeg",
        "data_base64": base64.b64encode(picture).decode(),
    }
    assert "data_base64" not in json.dumps(payload)


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

    assert first_trigger_evidence(asked)["transcript"] == "are you there"


def test_the_page_says_what_set_the_episode_off(monkeypatch):
    """`_run` used to guess from whether an image arrived without words. Both
    halves of that guess — always "speech", always "visual" — passed the
    whole suite. Which control somebody used is the page's to say.
    """
    asked = Says("done")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: asked)

    run(said="", image=a_portrait(), evidence_kind="visual")

    assert first_trigger_evidence(asked)["source"] == "visual"


def test_a_trigger_nobody_recognises_is_refused():
    """`CONTEXT.md` gives an Episode one external trigger, and the goldens
    carry two kinds. A typo must not become a third."""
    reply = answer("POST", "/run", json.dumps({"trigger": "telepathy"}).encode())

    assert reply.status == 400
    assert b"telepathy" in reply.body


def test_where_the_photograph_put_the_person_is_where_the_episode_starts(
    monkeypatch,
):
    """The upload has to reach the world the Episode runs in, not just the
    line reported back. Building the world without it left every test green
    while a photograph changed nothing about the run.
    """
    asked = Says("speak", "done")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr("misty_agent.demo.OpenAIModel", lambda: asked)

    payload = json.loads(run(image=a_portrait(0.5)).body)

    started_at = payload["perception"]["distance_cm"]
    assert started_at != DEFAULT_START_CM
    snapshots = [
        entry["content"]["snapshot"]
        for context in asked.contexts
        for entry in context
        if entry.get("role") == "tool" and "snapshot" in entry.get("content", {})
    ]
    assert snapshots[0]["distance_cm"] == started_at


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
    assert first_trigger_evidence(asked)["transcript"] == "is that you"


def test_audio_that_is_not_a_wav_is_refused_with_a_reason():
    """Asserted on what `wave` actually said, not on the wrapper around it —
    "WAV" is a word this module supplies either way, so it held with the
    decoder's own guard deleted."""
    reply = run(wav=b"this is not a wav at all", audio=True)

    assert reply.status == 400
    assert b"RIFF" in reply.body


def test_a_field_with_rubbish_in_it_is_refused_rather_than_swept_up():
    """`validate=True`, and the input has to be the kind that needs it.

    `b64decode` *discards* characters outside the alphabet unless asked not
    to — so a payload that is a real image with junk appended decodes
    perfectly well and quietly becomes something nobody sent. Rubbish that
    fails either way proves nothing, which is what the first version of this
    test used.
    """
    swept_up = base64.b64encode(a_portrait()).decode() + "!!!!"

    reply = answer("POST", "/run", json.dumps({"image": swept_up}).encode())

    assert reply.status == 400
    assert b"not base64" in reply.body


# ---------------------------------------------------------------------------
# What a POST may not do
# ---------------------------------------------------------------------------

def test_a_body_too_big_to_be_a_photograph_is_refused_before_it_is_read():
    """The body is decoded into memory before anything looks at it, so the
    limit belongs in front of that rather than after."""
    reply = answer("POST", "/run", b"x" * (MOST_ONE_REQUEST_MAY_CARRY + 1))

    assert reply.status == 413
    assert b"24MB" in reply.body


def test_the_page_is_told_which_way_of_supplying_a_key_reaches_it(monkeypatch):
    """`MissingApiKey` is written for somebody at a terminal, and one of the
    two routes it names cannot reach a demo that is already running: an
    `export` sets the visitor's shell, not this process. The file is read
    again on every run.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.demo.load_api_key", lambda path: None)

    why = json.loads(run().body)["why_no_episode"]

    assert API_KEY_VARIABLE in why
    assert "read again on every run" in why
    assert "stop the demo and start it again" in why


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


def test_demo_payloads_are_not_restored_from_a_browser_or_http_cache():
    """Current-run personal details may be displayed, but a refresh must ask
    the process for fresh state rather than restoring an earlier payload."""
    assert answer("GET", "/").headers["Cache-Control"] == "no-store"
    assert answer("GET", "/scenarios").headers["Cache-Control"] == "no-store"


def test_refusal_demo_explains_halt_suppression_countdown_and_explicit_bypass():
    response = answer(
        "POST",
        "/scenarios/crying-care/run",
        b'{"fixture":"respect-boundary"}',
    )
    assert response.status == 200
    payload = json.loads(response.body)

    kinds = [beat["kind"] for beat in payload["execution"]["flow"]]
    for expected in (
        "boundary_respected",
        "movement_stopped",
        "cue_suppression_started",
        "cue_suppressed",
        "cue_suppression_bypassed",
    ):
        assert expected in kinds
    suppression = next(
        beat for beat in payload["execution"]["flow"]
        if beat["kind"] == "cue_suppression_started"
    )
    assert "30" in suppression["headline"] or "30" in suppression["detail"]
    assert payload["robot"]["halted"] is True
    # The refusal opens the first Episode; the two throttled Care Cues open
    # none; the later explicit request bypasses and opens the last.
    assert [episode["cue_id"] for episode in payload["episodes"]] == [
        "cue-1",
        "cue-4",
    ]
    runtime_types = [
        record["type"] for record in payload["runtime"]["records"]
    ]
    assert "cue_suppressed" in runtime_types
    assert "cue_suppression_bypassed" in runtime_types


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


def test_asking_for_audio_reaches_the_thing_that_answers_requests(monkeypatch):
    """`serve(audio=True)` has to arrive at `answer`, or the switch is a flag
    that changes nothing. The handler is built per call, so the value cannot
    leak between two demos in one process either."""
    built = []
    monkeypatch.setattr("misty_agent.demo.HTTPServer", _StillbornServer)
    monkeypatch.setattr("misty_agent.demo.webbrowser.open", lambda where: None)
    monkeypatch.setattr(
        "misty_agent.demo._Handler", type("_Spy", (), {"audio": False})
    )

    serve(port=1, audio=True)
    built.append(_StillbornServer.handler.audio)
    serve(port=2, audio=False)
    built.append(_StillbornServer.handler.audio)

    assert built == [True, False]


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


def test_a_non_explicit_cue_is_never_presented_as_something_the_person_said():
    """Ticket 06 forbids inventing speech for a Care Cue, and ticket 08's
    queue beat announced every queued cue as an explicit request. The refusal
    fixture is the first scenario that queues a non-explicit cue, so it is
    where both would show."""
    payload = json.loads(
        answer(
            "POST",
            "/scenarios/crying-care/run",
            json.dumps({"fixture": "respect-boundary"}).encode(),
        ).body
    )
    beats = payload["execution"]["flow"]

    observed = next(beat for beat in beats if beat["kind"] == "observed_cue")
    assert observed["label"] == "Care Cue"
    assert "「" not in observed["headline"], "an observed cue was quoted as speech"
    assert "不是對方說出口的話" in observed["detail"]

    spoken = [beat["headline"] for beat in beats if beat["kind"] == "input"]
    assert observed["headline"] not in spoken
    assert spoken == ["「請不要靠近，我想一個人靜一靜」", "「Misty，我現在需要你」"]

    # A queued non-explicit cue used to be announced as an explicit request.
    queued = [beat["headline"] for beat in beats if beat["kind"] == "cue_queued"]
    assert queued == ["Care Cue 排隊等待（person）"]

    suppressed = [beat for beat in beats if beat["kind"] == "cue_suppressed"]
    assert [beat["headline"] for beat in suppressed] == [
        "Care Cue 未開啟 Episode",
        "Care Cue 未開啟 Episode",
    ]
    # The countdown counts down: a second cue later in the same throttle has
    # visibly less time left, rather than repeating the opening number.
    remaining = [
        float(beat["detail"].split("尚剩 ")[1].split(" 秒")[0]) for beat in suppressed
    ]
    assert remaining[0] == 30 and 0 < remaining[1] < 30

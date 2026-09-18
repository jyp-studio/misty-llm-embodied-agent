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
from misty_agent.audio_input import LiveInputAdapter, WavAudioFixtureSource
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock
from misty_agent.perception.asr import (
    OpenAITranscriber,
    Transcription,
    TranscriptionEnding,
    wav_to_pcm,
)
from misty_agent.perception.active import NO_ACTIVE_PERCEPTION
from misty_agent.perception.wake import PocketSphinxWakeDetector
from misty_agent.runtime import (
    AudioAttentionRecorded,
    AttentionStarted,
    AttentionStopped,
    CueDetected,
    CueDequeued,
    CueDeduplicated,
    CueDropped,
    CueQueued,
    CueReplaced,
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
    ScenarioSpeech,
    DEMO_SCENARIOS,
    EXPLICIT_TEXT_REQUEST,
    AcceptanceScenario,
    PresentationBeat,
    ScenarioCard,
    ScenarioModel,
)
from misty_agent.visual_input import (
    LocalVisualGate,
    VisualFixtureSource,
    VisualInputAdapter,
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
_WAKE_FIXTURES = _HERE.parent.parent / "tests" / "fixtures" / "wake"

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
            return _run_scenario(scenario_name, body)
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
            {"key": item.key, "label": item.label, "input_kind": "audio"}
            for item in case.audio_fixtures
        ]
        visual_fixtures = [
            {"key": item.key, "label": item.label, "input_kind": "visual"}
            for item in case.visual_fixtures
        ]
        payload["audio_fixtures"] = audio_fixtures
        payload["visual_fixtures"] = visual_fixtures
        payload["fixtures"] = audio_fixtures + visual_fixtures + [
            {"key": item.key, "label": item.label, "input_kind": "text"}
            for item in case.text_scripts
        ]
    return payload


class _ScriptedFixtureTranscriber:
    """Deterministic ASR; local wake detection still analyzes the WAV."""

    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    def transcribe_bounded(self, pcm, sample_rate, *, timeout_s):
        return Transcription(
            text=self._transcript,
            ending=TranscriptionEnding.TRANSCRIBED,
        )


@dataclass
class _ScenarioEars:
    """Finite speech made available to a scenario's cheap Snapshots."""

    utterances: list[str]

    def mute_for(self, seconds: float) -> None:
        return None

    def read(self, timeout: float):
        if not self.utterances:
            return None
        return _ScenarioUtterance(self.utterances.pop(0))


@dataclass(frozen=True)
class _ScenarioUtterance:
    text: str


class _ChainedScenarioInput:
    """Expose sequential providers as one Runtime input lifecycle."""

    def __init__(self, *sources) -> None:
        self._sources = sources
        self._index = 0

    def start(self) -> None:
        for source in self._sources:
            source.start()

    def read(self):
        while self._index < len(self._sources):
            value = self._sources[self._index].read()
            if value is not None:
                return value
            self._index += 1
        return None

    def read_available(self):
        available = []
        while self._index < len(self._sources):
            source = self._sources[self._index]
            available.extend(source.read_available())
            if available or not getattr(source, "exhausted", False):
                break
            self._index += 1
        return tuple(available)

    def stop(self) -> None:
        for source in reversed(self._sources):
            source.stop()


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

    try:
        asked = _scenario_request(body)
    except ValueError as why:
        return _json(400, {"error": str(why)})

    clock = FakeClock()
    scenario_config = Settings(
        cue_queue_capacity=3,
        cue_freshness_s=5.0,
    )
    selected_audio = None
    selected_visual = None
    selected_text = None
    visual_script = None
    active_perception = None
    all_fixtures = (*case.audio_fixtures, *case.visual_fixtures, *case.text_scripts)
    if all_fixtures:
        requested = asked.get("fixture", all_fixtures[0].key)
        selected_audio = next(
            (item for item in case.audio_fixtures if item.key == requested),
            None,
        )
        selected_visual = next(
            (item for item in case.visual_fixtures if item.key == requested),
            None,
        )
        selected_text = next((item for item in case.text_scripts if item.key == requested), None)
        if selected_audio is None and selected_visual is None and selected_text is None:
            return _json(
                400,
                {"error": f"there is no scenario fixture called {requested!r}"},
            )
    if selected_audio is not None:
        live_audio = LiveInputAdapter(
            audio=WavAudioFixtureSource(
                _WAKE_FIXTURES / selected_audio.asset,
                clock=clock,
            ),
            wake_detector=PocketSphinxWakeDetector(
                minimum_confidence=scenario_config.wake_minimum_confidence
            ),
            transcriber=_ScriptedFixtureTranscriber(
                selected_audio.transcript
            ),
            clock=clock,
            config=scenario_config,
        )
        source = _ChainedScenarioInput(
            live_audio,
            ScenarioInputAdapter(clock, case.inputs[1:]),
        )
    elif selected_visual is not None:
        visual_script = case.visual_script_for(selected_visual.key)
        active_perception = LocalVisualGate()
        source = VisualInputAdapter(
            frames=VisualFixtureSource(clock, selected_visual.frames),
            clock=clock,
            gate=active_perception,
        )
    elif selected_text is not None:
        source = ScenarioInputAdapter(clock, selected_text.inputs)
    else:
        source = ScenarioInputAdapter(clock, case.inputs)
    script = selected_text or visual_script
    decisions = script.decisions if script else case.decisions
    session = simulated_session(
        None,
        model=ScenarioModel(decisions),
        clock=clock,
        ears=ScenarioSpeech(clock, selected_text.speech) if selected_text else _ScenarioEars(
            list(visual_script.heard_after_first_tool)
            if visual_script
            else []
        ),
        active_perception=(
            active_perception
            if active_perception is not None
            else NO_ACTIVE_PERCEPTION
        ),
    )
    result = SocialAgentRuntime(
        source=source,
        session=session,
        clock=clock,
        config=scenario_config,
    ).run()
    selected_fixture = selected_audio or selected_visual or selected_text
    if selected_fixture is None:
        raise RuntimeError("an acceptance scenario has no fixture")
    episodes = []
    for index, episode in enumerate(result.episodes):
        actor = case.actors[min(index, len(case.actors) - 1)]
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
            "execution": _scenario_execution(
                result,
                result.episodes[0] if result.episodes else None,
                queue_capacity=scenario_config.cue_queue_capacity,
                fixture_label=selected_fixture.label,
                input_kind=("audio" if selected_audio else "text" if selected_text else "visual"),
                actors=case.actors,
            ),
            "runtime": _runtime_payload(result),
            "episodes": episodes,
        },
    )


def _scenario_execution(
    result: RuntimeResult,
    episode: Optional[RuntimeEpisode],
    *,
    queue_capacity: int,
    fixture_label: str,
    input_kind: str,
    actors: Sequence[str] = (DEFAULT_ACTOR,),
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
            (CueQueued, CueDequeued, CueDeduplicated, CueReplaced, CueDropped),
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
    audio_labels = {
        "wake": "本機喚醒辨識",
        "capture": "喚醒後語音擷取",
        "asr": "語音轉文字（腳本）",
        "backlog": "音訊等待佇列",
        "source": "音訊來源",
    }
    audio_headlines = {
        "matched": "已辨識到喚醒詞",
        "no_match": "沒有辨識到喚醒詞",
        "repeated_wake": "收到重複喚醒詞",
        "captured": "已擷取一段語音",
        "empty_utterance": "喚醒後沒有語音",
        "silence_timeout": "等待語音逾時",
        "max_duration": "語音已達長度上限",
        "transcribed": "已產生文字",
        "asr_empty": "沒有可用文字",
        "asr_timeout": "語音轉文字逾時",
        "asr_error": "語音轉文字失敗",
        "backlog_dropped": "部分音訊因佇列已滿而丟棄",
        "source_ended": "音訊來源已結束",
        "source_error": "音訊來源失敗",
    }
    flow = [
        PresentationBeat(
            record.stage.value,
            audio_labels[record.stage.value],
            audio_headlines[record.outcome.value],
            (
                " · ".join(
                    f"{key}: {value}" for key, value in record.facts.items()
                )
                or "此階段已留下 typed Runtime record。"
            ),
        )
        for record in audio_records
    ]
    visual_headlines = {
        "empty": "畫面中沒有偵測到人",
        "not_looking": "人物沒有看向 Misty",
        "tracking": "開始累積注視時間",
        "wave_progress": "觀察到手部來回位移",
        "qualified": "持續注視加揮手已達 gate",
        "care_progress": "持續累積可觀察的臉部／姿勢線索",
        "care_qualified": "可觀察線索已形成不確定 Care Cue",
    }
    flow.extend(
        PresentationBeat(
            "visual_gate",
            f"Frame {record.frame_index + 1} · {record.track_reference or '畫面'}",
            visual_headlines[record.outcome.value],
            (
                " · ".join(
                    f"{key}: {value}" for key, value in record.facts.items()
                )
                or "本機 temporal gate 已留下 typed Runtime record。"
            ),
        )
        for record in visual_records
    )
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
            record, (CueDetected, CueQueued, CueDeduplicated, CueReplaced, CueDropped)
        ):
            during[active_cue].append(record)
    inside = {id(record) for group in during.values() for record in group}

    for record in result.records:
        if id(record) in inside:
            continue
        if isinstance(record, EpisodeOpened) and record.cue_id in runs_by_cue:
            flow.extend(_episode_beats(
                runs_by_cue[record.cue_id],
                actor_of(record.cue_id),
                detected_by_cue[record.cue_id],
                input_kind,
                during=during.get(record.cue_id, ()),
                actor_of=actor_of,
            ))
        else:
            beat = _cue_beat(record, actor_of, input_kind)
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
            "結果",
            (
                "情境執行完成"
                if completed
                else (
                    "保持安靜，沒有開啟 Episode"
                    if quiet
                    else "情境未正常完成"
                )
            ),
            (
                "有限情境已播放完畢，Runtime 正常停止。"
                if completed
                else (
                    "視覺時間線已播放完畢，但沒有足夠證據觸發 model 或動作。"
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
        "provenance": {
            "kind": "scripted_current_run",
            "headline": "這是剛剛執行的模擬結果",
            "model": (
                "未呼叫"
                if episode is None
                else "預設腳本模型"
            ),
            "robot": "模擬 Misty",
            "detail": (
                (
                    "選定的 synthetic WAV 由目前程式執行本機 wake detection；"
                    "ASR、模型決策與其餘 Cue 時間為預先定義，robot 為模擬。"
                    "Runtime、queue、Tool 與 Journal 都在這次重新執行。"
                )
                if input_kind == "audio"
                else "文字與後續話語、model 決策為預先定義的腳本；Skill 載入、listen、Runtime、Tools 與 Journal 都在這次重新執行。Robot 為模擬，未呼叫真實 model 或 Misty II。"
                + (
                    "多位 actors 的發言歸屬由腳本指定：系統沒有聲源方向或人臉身分，"
                    "只用匿名 track reference 綁定 Interaction Target。"
                    if len(actors) > 1
                    else ""
                )
                if input_kind == "text"
                else (
                    "選定的 synthetic frame timeline 由目前程式重新執行本機"
                    "匿名追蹤與 temporal visual gate；detector signals 為預先"
                    "定義，robot 為模擬。"
                    + (
                        "沒有形成 cue，因此 model 沒有被呼叫。"
                        if episode is None
                        else "model 決策為預先定義。"
                    )
                    + "未使用真實相機或 Misty II。"
                )
            ),
            "audio": fixture_label if input_kind == "audio" else None,
            "fixture": fixture_label,
            "input_kind": input_kind,
        },
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
                "Decision Note 已由本次 Journal 記錄"
                if notes
                else (
                    "本機 gate 沒有開啟互動"
                    if episode is None and input_kind == "visual"
                    else "本次 model 未提供 Decision Note"
                )
            ),
            "detail": (
                next(iter(notes.values())).note
                if notes
                else (
                    "沒有足夠的持續注視加揮手證據，因此 model 沒有被呼叫。"
                    if episode is None and input_kind == "visual"
                    else "Tool choice 仍可驗證，但沒有公開目的說明。"
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
    "expired": "過期，沒有開啟 Episode",
    "overflow": "因 queue 已滿而被淘汰",
    "shutdown": "因 runtime 關閉而放棄",
    "runtime_failure": "因 runtime 失敗而放棄",
    "episode_error": "因 Episode 錯誤而放棄",
}


def _cue_beat(record: RuntimeRecord, actor_of, input_kind: str) -> Optional[PresentationBeat]:
    """One cue lifecycle record as display copy, or nothing to show."""
    if isinstance(record, CueDetected):
        if input_kind not in {"audio", "text"}:
            return None
        actor = actor_of(record.cue_id)
        return PresentationBeat(
            "input",
            "人說" if actor == DEFAULT_ACTOR else f"{actor} 說",
            f"「{record.text}」",
            "這段輸入由案例預先定義。",
        )
    if isinstance(record, CueQueued):
        return PresentationBeat(
            "cue_queued",
            "Cue queue",
            f"{actor_of(record.cue_id)} 的明確請求排隊等待",
            f"{actor_of(record.active_cue_id)} 的 Episode 進行中；queue 內有 "
            f"{record.queue_size} 個 cue。不平行開啟 Episode，也不丟棄。",
        )
    if isinstance(record, CueDropped):
        return PresentationBeat(
            "cue_dropped",
            "Cue 丟棄",
            f"{actor_of(record.cue_id)} 的 cue 已"
            + _DROP_WORDING.get(record.reason.value, record.reason.value),
            "依 freshness 與 queue 規則處理；不依舊資料強行互動。",
        )
    if isinstance(record, CueDequeued):
        return PresentationBeat(
            "cue_dequeued",
            "交接",
            f"輪到 {actor_of(record.cue_id)}",
            "前一個 Episode 已在 Turn boundary 結束；從 queue 取出下一個 cue，"
            "開啟新 Episode 與新的 Interaction Target。",
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
        return [beat for beat in (_cue_beat(r, actor_of, input_kind) for r in chosen) if beat]
    evidence = run.evidence
    uncertainty = (
        "、".join(evidence.uncertainty)
        if evidence.uncertainty
        else "沒有額外不確定性註記"
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
            f"{'文字腳本' if input_kind == 'text' else '語音' if evidence.source.value == 'speech' else '圖片'}證據 · "
            f"{evidence.observed_at_s:g} 秒",
            f"{len(evidence.facts)} 個可觀察 facts"
            + (
                "；選取 1 張 bounded JPEG crop"
                if evidence.selected_image_media_type is not None
                else ""
            )
            + f"；不確定性：{uncertainty}",
        ),
        PresentationBeat(
            "cue",
            "系統判定",
            (
                "明確互動請求"
                if cue.cue_kind.value == "explicit_request"
                else (
                    "Care Cue"
                    if cue.cue_kind.value == "care_cue"
                    else "Social Invitation"
                )
            ),
            cue.cue_kind.value,
        ),
    ]
    journal_records = run.journal.records
    for record in journal_records:
        if isinstance(record, TargetBound):
            flow.append(PresentationBeat(
                "target_bound",
                "Interaction Target",
                f"{actor}：{record.track_reference or '沒有匿名 track（純語音）'}",
                f"本 Episode 只鎖定這個匿名 target（{record.state}）；更近或更新的臉"
                "不會靜默取代，下一個 Episode 也不繼承。",
            ))
        if isinstance(record, HandoffRequested):
            flow.extend(collected(record.cue_id))
            flow.append(PresentationBeat(
                "handoff_requested",
                "交接通知",
                f"{actor_of(record.cue_id)} 正在等待（{record.cue_id}）",
                "在 Turn boundary 告知 model 收尾；不中斷目前 Turn，也不平行開啟 Episode。",
            ))
        if isinstance(record, SkillsAvailable):
            flow.append(PresentationBeat(
                "skills_available", "可用 Skills", "可選技能（尚未載入）",
                " · ".join(f"{item['name']}：{item['description']}" for item in record.skills),
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
        elif record.tool in {"activate_skill", "read_skill_resource", "listen"}:
            observation = observations.get(record.turn)
            if observation is not None:
                returned = observation.result
                if "refused" in returned:
                    headline, detail = "請求被拒絕", returned["refused"]
                elif record.tool == "activate_skill":
                    headline, detail = returned["name"], "技能已載入；只引導本次 Episode 後續 Tools。"
                elif record.tool == "read_skill_resource":
                    headline, detail = returned["resource"], "已按需讀取；沒有執行 script。"
                else:
                    headline = returned.get("transcript") or "這次沒有收到新話語"
                    detail = f"聆聽結果：{returned['ending']}；{returned['source']}，說話者未辨識。"
                flow.append(PresentationBeat(
                    returned.get("kind", "refused"), "本次 Tool 結果", headline, detail,
                ))
        elif record.tool in {"observe_target", "inspect_scene"}:
            observation = observations.get(record.turn)
            if observation is not None:
                flow.append(
                    PresentationBeat(
                        "observation",
                        "Observation",
                        (
                            "便宜的目標觀察"
                            if record.tool == "observe_target"
                            else "較昂貴的場景檢查"
                        ),
                        f"{observation.result.get('ending')} · "
                        f"fresh for {observation.result.get('fresh_for_s')} 秒 · "
                        "保留不確定性",
                    )
                )
        elif record.tool in {"move_head", "move_arms", "display_image", "change_led"}:
            observation = observations.get(record.turn)
            if observation is not None and observation.result.get("ok"):
                flow.append(PresentationBeat(
                    "simulated_effect", "模擬表達成功", describe(record).headline,
                    "姿勢由本次成功的 Tool 結果更新；不是實機動作。",
                ))
    flow.extend(collected(None))
    return flow


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
        headline = f"排入 {record.cue_id} · 優先級 {record.priority}"
        detail = (
            f"當時正在處理 {record.active_cue_id} · queue 中有 "
            f"{record.queue_size} 個"
        )
    elif isinstance(record, CueDeduplicated):
        headline = f"去重 {record.cue_id}"
        detail = (
            f"保留 {record.retained_cue_id} · key "
            f"{record.deduplication_key}"
        )
    elif isinstance(record, CueReplaced):
        headline = f"升級 {record.cue_id} → {record.replacement_cue_id}"
        detail = f"優先級 {record.old_priority} → {record.new_priority}"
    elif isinstance(record, CueDropped):
        reason = {
            "expired": "已過期",
            "overflow": "queue 已滿",
            "shutdown": "Runtime 關閉",
            "runtime_failure": "Runtime 發生錯誤",
            "episode_error": "Episode 發生錯誤",
        }[record.reason.value]
        headline = f"丟棄 {record.cue_id} · {reason}"
        detail = (
            f"優先級 {record.priority} · queue 中剩 "
            f"{record.queue_size} 個"
        )
    elif isinstance(record, CueDequeued):
        headline = f"取出 {record.cue_id} · 優先級 {record.priority}"
        detail = f"queue 中剩 {record.queue_size} 個"
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

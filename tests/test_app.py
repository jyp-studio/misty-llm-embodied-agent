"""The wiring: one clock, one bumper, one Episode.

Everything this module assembles is tested where it lives. What is only
testable here is the assembly itself — and the assembly is where the two
mechanisms M7 built with no production caller finally get one. `EmergencyStop`
and `ToolContext.ears` both shipped fully tested and entirely unwired; a
session that forgot to connect either would pass every other test in the
project while leaving the robot unable to stop and deaf to nothing.
"""

from __future__ import annotations

import json
import time

import pytest

from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.agent.journal import EpisodeFinished, Snapshot, StopRequested
from misty_agent.agent.memory import Memory
from misty_agent.agent.persona import PERSONA
from misty_agent.agent.react import Decision
from misty_agent.app import (
    API_KEY_FILE,
    API_KEY_VARIABLE,
    LivePerception,
    Session,
    SystemClock,
    load_api_key,
)
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import RealMistyAdapter
from misty_agent.perception.distance import DistanceReading


class Says:
    """A scripted model — the same narrow interface the live suite uses."""

    def __init__(self, *tools):
        self._tools = list(tools) or ["done"]
        self.asked = 0
        #: What it was handed, kept: a Session that stopped passing something
        #: through is invisible to a count of calls.
        self.contexts = []

    def decide(self, working_context, tools):
        self.asked += 1
        self.contexts.append(list(working_context))
        tool = self._tools[min(self.asked - 1, len(self._tools) - 1)]
        return Decision(
            tool=tool,
            args={"text": "hello"} if tool == "speak" else {},
            tokens_in=10,
            tokens_out=1,
        )


class Readings:
    def __init__(self, distance_cm=None):
        self.distance_cm = distance_cm

    def latest_reading(self):
        if self.distance_cm is None:
            return None
        return DistanceReading(
            distance_cm=self.distance_cm, frame_arrived_at=0.0, detected_at=0.0
        )


class Ears:
    def __init__(self, *utterances):
        self.muted_for = []
        self._utterances = list(utterances)

    def mute_for(self, seconds):
        self.muted_for.append(seconds)

    def read(self, timeout):
        return self._utterances.pop(0) if self._utterances else None


class Events:
    def __init__(self):
        self.subscriptions = []

    def subscribe(self, event_type, **kwargs):
        self.subscriptions.append((event_type, kwargs))
        return object()


class NameUniqueEvents:
    """The production stream's duplicate-name behaviour, without sockets."""

    def __init__(self):
        self.subscriptions = {}

    def subscribe(self, event_type, **kwargs):
        name = kwargs["name"]
        if name in self.subscriptions:
            return None
        self.subscriptions[name] = (event_type, kwargs)
        return object()


def a_session(
    *, model=None, ears=None, events=None, readings=None, robot=None, **rest
):
    return Session(
        robot=RealMistyAdapter(robot or RecordingCommands()),
        readings=readings or Readings(150),
        model=model or Says(),
        memory=Memory(summariser=None, extractor=None, window=6),
        ears=ears,
        events=events,
        config=Settings(),
        clock=FakeClock(),
        **rest,
    )


def speech(text=""):
    return TriggerEvidence(
        source=EvidenceKind.SPEECH,
        observed_at_s=0.0,
        transcript=text,
    )


# ---------------------------------------------------------------------------
# One Episode
# ---------------------------------------------------------------------------

def test_a_session_runs_one_episode_and_hands_back_its_journal():
    """`PLAN.md` §15.1: one typed evidence input, one Episode. No outer loop."""
    session = a_session()

    outcome, journal = session.episode(speech("hello"), render=False)

    assert outcome.outcome == "done"
    assert isinstance(journal.records[-1], EpisodeFinished)


def test_the_session_tells_the_model_what_it_is():
    """M8 #03 gave `run_episode` an `instructions=` parameter; two reviews
    found nothing outside its own tests passed one, which is the shape
    `PLAN.md` §15.23 deleted it for the first time. This is the caller.
    """
    model = Says()
    session = a_session(model=model)

    session.episode(speech("hello"), render=False)

    assert model.contexts[0][0] == {"role": "system", "content": PERSONA}


def test_the_instructions_a_session_was_built_with_are_the_ones_it_sends():
    """The default cannot prove the wiring.

    `run_episode` falls back to `PERSONA` on its own, so a `Session` that
    quietly stopped passing `instructions=` would leave the test above green
    — the same defect the parameter's own tests were caught by. Only a value
    the fallback would never produce distinguishes them.
    """
    model = Says()
    session = a_session(model=model, instructions="You are a lamp.")

    session.episode(speech("hello"), render=False)

    told = [e["content"] for e in model.contexts[0] if e["role"] == "system"]
    assert told[0] == "You are a lamp."
    assert PERSONA not in told
    assert len(told) == 2
    assert told[1].startswith("Available Skills (name and description only):")


def test_a_session_will_not_write_an_episode_into_an_existing_journal(tmp_path):
    """The seam this ticket added, guarded where the format is.

    `main` refuses an existing path with a sentence of explanation, but a
    caller reaching `Session.episode` directly would otherwise append a second
    Episode into somebody's file. It raises before the Episode is built, so
    nothing has moved when it does.
    """
    someone_elses = tmp_path / "already.jsonl"
    someone_elses.write_text("")
    session = a_session()

    with pytest.raises(FileExistsError):
        session.episode(
            speech("hi"), render=False, journal_path=someone_elses
        )

    assert someone_elses.read_text() == ""


def test_every_episode_gets_its_own_journal():
    """Two Episodes are two records, not one growing one — and a `Journal`
    refuses to be written to after it has finished, so sharing would raise on
    the second."""
    session = a_session()

    _, first = session.episode(speech("one"), render=False)
    _, second = session.episode(speech("two"), render=False)

    assert first is not second
    assert first.records[0].episode_id != second.records[0].episode_id


def test_memory_carries_across_episodes():
    """The one thing that is *not* rebuilt per Episode — that is what makes it
    memory rather than working context (`CONTEXT.md`)."""
    session = a_session(model=Says("speak", "done"))

    session.episode(speech("I am Ana"), render=False)
    session.episode(speech("who am I?"), render=False)

    assert [exchange.said for exchange in session.memory.exchanges] == [
        "I am Ana",
        "who am I?",
    ]


# ---------------------------------------------------------------------------
# One clock
# ---------------------------------------------------------------------------

def test_everything_shares_the_session_clock():
    """Four collaborators each default to their own reading of
    `time.monotonic`. Left alone, an Episode's timestamps, its measured model
    latency and its suppression window come from clocks that merely happen to
    agree, and no test could say otherwise.
    """
    clock = FakeClock()
    session = a_session()
    session.clock = clock

    class Slow:
        def decide(self, working_context, tools):
            clock.sleep(1.5)
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    session.model = Slow()
    _, journal = session.episode(speech(), render=False)

    called = next(r for r in journal.records if r.type == "model_called")
    assert called.latency_ms == 1500
    assert called.t == pytest.approx(1.5)


def test_the_default_clock_is_a_real_one():
    """The negative control: a session that quietly used a fake would make
    every latency in production zero."""
    session = Session(
        robot=RealMistyAdapter(RecordingCommands()), readings=Readings(), model=Says(),
        memory=Memory(summariser=None, extractor=None, window=6),
    )

    assert isinstance(session.clock, SystemClock)
    before = session.clock.monotonic()
    session.clock.sleep(0.001)
    assert session.clock.monotonic() > before


# ---------------------------------------------------------------------------
# The bumper — the wiring `EmergencyStop` never had
# ---------------------------------------------------------------------------

def test_the_shared_clock_is_the_one_the_drivers_read_on_their_own():
    """The premise `PLAN.md` §16.18 rests on, pinned.

    `RtspVideoStream` and `DistancePipeline` stamp frames and readings by
    calling `time.monotonic()` themselves and take no clock to call instead.
    §16.18 argues that is survivable rather than a missing wire — but only
    because `SystemClock.monotonic` *is* `time.monotonic`: the same function,
    not two that happen to agree today. Give `SystemClock` its own notion of
    now and `approach` starts rejecting every real reading as stale, with
    nothing else going red.
    """
    before = time.monotonic()
    shared = SystemClock().monotonic()
    after = time.monotonic()

    assert before <= shared <= after


def test_a_session_arms_the_bumper_as_part_of_construction():
    """A safety path that needs a second remembered call is not wired."""
    events = Events()
    a_session(events=events)

    (event_type, kwargs), = events.subscriptions
    assert event_type == "BumpSensor"
    assert kwargs["keep_alive"] is True
    assert kwargs["debounce_ms"] == 1000
    assert kwargs["condition"] == [
        {"Property": "isContacted", "Inequality": "=", "Value": True}
    ]


def test_arming_the_bumper_again_does_not_open_a_second_subscription():
    events = Events()
    session = a_session(events=events)

    session.watch_the_bumper()

    assert len(events.subscriptions) == 1


def test_sessions_sharing_an_event_stream_each_arm_their_own_bumper():
    events = NameUniqueEvents()

    first = a_session(events=events)
    second = a_session(events=events)

    assert len(events.subscriptions) == 2
    assert len(set(events.subscriptions)) == 2
    callbacks = [
        kwargs["on_event"] for _, kwargs in events.subscriptions.values()
    ]
    callbacks[0]({})
    callbacks[1]({})
    assert "halt" in first.robot.commands.endpoints
    assert "halt" in second.robot.commands.endpoints


def test_a_session_cannot_finish_construction_with_an_unarmed_bumper():
    class RejectsSubscriptions:
        def subscribe(self, event_type, **kwargs):
            return None

    with pytest.raises(RuntimeError, match="bumper subscription"):
        a_session(events=RejectsSubscriptions())


def test_pressing_the_bumper_during_an_episode_aborts_it():
    """The whole of ticket 08, finally connected to something."""
    events = Events()
    session = a_session(events=events)
    session.watch_the_bumper()
    (_, kwargs), = events.subscriptions
    press = kwargs["on_event"]

    class PressesMidEpisode:
        def decide(self, working_context, tools):
            press({"message": {"isContacted": True}})
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    session.model = PressesMidEpisode()
    outcome, journal = session.episode(speech(), render=False)

    assert outcome.outcome == "aborted"
    assert any(isinstance(r, StopRequested) for r in journal.records)


def test_the_stop_lands_in_the_journal_of_the_episode_that_was_running():
    """`EmergencyStop` binds one Journal at construction and is single-shot.

    A session that built one and kept it would put the second evening's
    interruption in the first evening's Journal — or swallow it entirely.
    """
    events = Events()
    session = a_session(events=events)
    session.watch_the_bumper()
    press = events.subscriptions[0][1]["on_event"]

    _, quiet = session.episode(speech(), render=False)

    class PressesMidEpisode:
        def decide(self, working_context, tools):
            press({})
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    session.model = PressesMidEpisode()
    _, interrupted = session.episode(speech(), render=False)

    assert not any(isinstance(r, StopRequested) for r in quiet.records)
    assert any(isinstance(r, StopRequested) for r in interrupted.records)


def test_pressing_the_bumper_between_episodes_still_halts_the_robot():
    """There is nothing to record and nothing to abort, but the motors are
    just as real.

    An Episode runs first, because "between" is not "before". The earlier
    version pressed on a session that had never run anything, so a `_running`
    that was never cleared would have satisfied it — the same shape as
    `PLAN.md` §15.25's race test that could not see the race.
    """
    robot = RecordingCommands()
    events = Events()
    session = a_session(events=events, robot=robot)
    session.episode(speech("hello"), render=False)
    robot.clear()

    events.subscriptions[0][1]["on_event"]({})

    assert "halt" in robot.endpoints


def test_a_press_while_memory_is_consolidating_still_stops_the_robot():
    """The window that made the emergency stop do nothing at all.

    `run_episode` records `EpisodeFinished` and *then* consolidates memory —
    `close_episode` may call a model, so this is a network round trip, not a
    microsecond. Through all of it `Session._running` still points at the
    Episode that just closed, and its Journal refuses anything after its
    ending. The first version of `bumper_pressed` called `request()` outside
    its `try`, so the `ValueError` escaped before the halt: **no record and no
    halt, for as long as consolidation took** (`PLAN.md` §15.35).

    Driven through the real ordering rather than by setting `_running` by
    hand, because the ordering is the bug.
    """
    robot = RecordingCommands()
    events = Events()
    session = a_session(events=events, robot=robot)
    press = events.subscriptions[0][1]["on_event"]
    pressed = []

    class PressesWhileConsolidating:
        def extract(self, known, exchanges):
            pressed.append(True)
            press({})
            return {}

    session.memory = Memory(
        summariser=None, extractor=PressesWhileConsolidating(), window=6
    )

    _, journal = session.episode(speech("hello"), render=False)

    assert pressed, "the press never happened, so this tested nothing"
    assert "halt" in robot.endpoints, (
        "the bumper was pressed and the robot was never told to stop"
    )
    assert journal.records[-1].type == "episode_finished"


def test_a_live_episode_is_halted_once_not_twice():
    """`EmergencyStop.request` halts on its way to recording.

    So delegating and *then* halting again would send two `POST /halt` for one
    foot. Harmless on a good day, but it means the two paths are not exclusive
    — and once they overlap, the fall-through added for the closed-Journal
    window would start firing on the ordinary path too.
    """
    robot = RecordingCommands()
    events = Events()
    session = a_session(events=events, robot=robot)
    press = events.subscriptions[0][1]["on_event"]

    class PressesMidEpisode:
        def decide(self, working_context, tools):
            press({})
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    session.model = PressesMidEpisode()
    session.episode(speech(), render=False)

    assert robot.endpoints.count("halt") == 1


def test_a_press_in_a_later_episode_aborts_that_episode():
    """`_running` has to be *cleared*, not just set.

    Left pointing at the previous Episode, a press would be delivered to a
    Journal that has already closed — and the fall-through added above would
    quietly halt the robot, so the motors stopping is no longer evidence that
    anything worked. What it would not do is end the Episode that is actually
    running. That is the difference this asserts.
    """
    robot = RecordingCommands()
    events = Events()
    session = a_session(events=events, robot=robot)
    press = events.subscriptions[0][1]["on_event"]

    session.episode(speech("the first one"), render=False)

    class PressesMidEpisode:
        def decide(self, working_context, tools):
            press({})
            return Decision(tool="done", args={}, tokens_in=1, tokens_out=1)

    session.model = PressesMidEpisode()
    outcome, journal = session.episode(speech("the second one"), render=False)

    assert outcome.outcome == "aborted"
    assert any(r.type == "stop_requested" for r in journal.records)


def test_a_press_after_the_episode_closed_does_not_forge_a_record():
    """Halting is the right thing to do; rewriting a closed Journal is not.

    "An Episode ends exactly once" is a property a reader checks by counting
    (`journal.py`), and a `stop_requested` appearing after the ending would
    make it something they had to reason about instead.
    """
    robot = RecordingCommands()
    events = Events()
    session = a_session(events=events, robot=robot)
    press = events.subscriptions[0][1]["on_event"]
    journals = []

    class PressesWhileConsolidating:
        def extract(self, known, exchanges):
            press({})
            return {}

    session.memory = Memory(
        summariser=None, extractor=PressesWhileConsolidating(), window=6
    )
    _, journal = session.episode(speech("hello"), render=False)

    kinds = [record.type for record in journal.records]
    assert kinds.count("episode_finished") == 1
    assert kinds[-1] == "episode_finished"
    assert "stop_requested" not in kinds


def test_a_session_with_no_event_stream_still_runs():
    """A session driven from a script has no websocket, and should not need
    one to run an Episode."""
    session = a_session(events=None)

    session.watch_the_bumper()
    outcome, _ = session.episode(speech(), render=False)

    assert outcome.outcome == "done"


# ---------------------------------------------------------------------------
# The ears — the wiring `ToolContext.ears` never had
# ---------------------------------------------------------------------------

def test_speaking_shuts_the_microphone_through_the_session():
    """§15.29's suppression window, connected. Without this the window exists
    in the Tool and is handed `None` in production."""
    ears = Ears()
    session = a_session(model=Says("speak", "done"), ears=ears)

    session.episode(speech(), render=False)

    assert ears.muted_for and ears.muted_for[0] > 0


# ---------------------------------------------------------------------------
# The Snapshot the loop attaches
# ---------------------------------------------------------------------------

def test_a_snapshot_reports_the_three_facts():
    perception = LivePerception(Readings(142), Ears())

    snapshot = perception.snapshot()

    assert snapshot == Snapshot(distance_cm=142, face_present=True, new_speech=None)


def test_no_reading_means_nobody_in_view():
    """The distance *is* a face measurement — the pipeline derives it from
    face width — so no reading and no face are the same statement."""
    snapshot = LivePerception(Readings(None)).snapshot()

    assert snapshot == Snapshot(
        distance_cm=None, face_present=False, new_speech=None
    )


def test_something_heard_since_the_last_look_reaches_the_snapshot():
    class Utterance:
        text = "stop that"

    snapshot = LivePerception(Readings(120), Ears(Utterance())).snapshot()

    assert snapshot.new_speech == "stop that"


def test_the_sessions_own_ears_reach_the_snapshot_it_takes():
    """The wiring, not `LivePerception` — and nothing else covered it.

    Every test around this one builds a `LivePerception` by hand, so a
    `Session` that stopped passing its microphone through would leave all of
    them green while every Episode went deaf. That is `PLAN.md` §15.34's
    shape exactly, and it is how `ToolContext.ears` sat unwired until M7 #12.
    A review's mutant replaced the microphone with `None` here and the whole
    suite stayed green.
    """
    class Utterance:
        text = "stop that"

    session = a_session(ears=Ears(Utterance()))

    assert session.sees().new_speech == "stop that"


def test_a_snapshot_without_ears_reports_no_speech_rather_than_failing():
    assert LivePerception(Readings(120)).snapshot().new_speech is None


# ---------------------------------------------------------------------------
# Finding a key
# ---------------------------------------------------------------------------

def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    """An explicit `export` should not be silently overridden by a file
    somebody forgot about."""
    monkeypatch.setenv(API_KEY_VARIABLE, "sk-from-the-environment")
    path = tmp_path / API_KEY_FILE
    path.write_text(json.dumps([{"api_key": "sk-from-the-file"}]))

    assert load_api_key(str(path)) == "sk-from-the-environment"


def test_the_file_is_read_when_the_environment_is_empty(tmp_path, monkeypatch):
    """`.env.example` and the README have promised this channel since before
    the rewrite, and the loader for it lived only in the script this ticket
    deletes."""
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    path = tmp_path / API_KEY_FILE
    path.write_text(json.dumps([{"api_key": "sk-from-the-file"}]))

    assert load_api_key(str(path)) == "sk-from-the-file"


def test_a_key_from_the_file_is_put_where_the_sdk_will_look(tmp_path, monkeypatch):
    """The SDK reads the environment, not this file."""
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    path = tmp_path / API_KEY_FILE
    path.write_text(json.dumps([{"api_key": "sk-from-the-file"}]))

    load_api_key(str(path))

    assert os_environ_key() == "sk-from-the-file"


def os_environ_key():
    import os

    return os.environ.get(API_KEY_VARIABLE)


@pytest.mark.parametrize(
    "contents", ["", "not json", "[]", "[{}]", '[{"api_key": "   "}]', "{}"]
)
def test_a_file_with_no_usable_key_is_no_key(tmp_path, monkeypatch, contents):
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    path = tmp_path / API_KEY_FILE
    path.write_text(contents)

    assert load_api_key(str(path)) is None


def test_a_missing_file_is_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)

    assert load_api_key(str(tmp_path / "nothing-here.json")) is None


def test_a_single_object_works_as_well_as_a_list(tmp_path, monkeypatch):
    """`OAI_CONFIG_LIST.json.example` ships a list; people write both."""
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    path = tmp_path / API_KEY_FILE
    path.write_text(json.dumps({"api_key": "sk-single"}))

    assert load_api_key(str(path)) == "sk-single"

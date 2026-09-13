"""Assembling the real drivers, on a machine that has no robot.

`PLAN.md` §8: **this project has no Misty II and never will.** So this file
cannot check that the path works — nothing can. What it checks is the thing
that has gone wrong here twice already and would go wrong invisibly again:
that the parts are actually *connected to each other*.

`PLAN.md` §15.34 is the list. `EmergencyStop` and `ToolContext.ears` were both
built, mutation-tested to nothing surviving, and **never wired up** — until
M7 #12 found them. A session that forgets a wire passes every other test in
this project while the robot cannot be stopped and cannot hear itself.

## The seam

The driver classes are looked up by name on `misty_agent.app`, so every test
here replaces them with recorders and asserts on what was built, what was
started, and in which order. Nothing opens a socket. That is not a compromise
forced by the missing hardware — even with a Misty II on the desk, "did the
bumper reach the emergency stop" is a question about wiring, and wiring is
answered at the boundary.

## The one ordering fact that is not obvious

`RtspVideoStream.stop()` closes the `AvSession`, and `AudioStream` is reading
that same session. Stop the video first and the audio threads are left reading
a stream that has been shut. So the teardown is not merely "reverse of
start-up" — the video goes last, and `test_the_audio_is_stopped_before_the_
stream_it_reads` is the reason.
"""

from __future__ import annotations

import pytest

from misty_agent.agent.react import Decision
from misty_agent.app import main
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.runtime import InputArrival, TimedText

from test_app import Says


class Recorder:
    """Base for the driver doubles: remembers construction and lifecycle."""

    log: list = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        Recorder.log.append(f"built {type(self).__name__}")

    def start(self):
        self.started = True
        Recorder.log.append(f"start {type(self).__name__}")

    def stop(self):
        self.stopped = True
        Recorder.log.append(f"stop {type(self).__name__}")


class FakeCommands(RecordingCommands):
    """The project's own robot double, with the driver log attached.

    Not a hand-rolled stand-in. The first version of this file stubbed
    `halt` and `stop_moving` and nothing else, so the moment a Tool called
    anything past those two the Episode ended as `error` and the test that
    depended on it went quietly empty. `RecordingCommands` answers the whole
    command surface, so a call this file forgot fails the way it would
    against a robot rather than the way it would against a stub.
    """

    def __init__(self, ip: str = "127.0.0.1") -> None:
        super().__init__(ip)
        Recorder.log.append("built FakeCommands")


class FakeAvSession(Recorder):
    pass


class FakeVideo(Recorder):
    pass


class FakeReadings(Recorder):
    def latest_reading(self):
        return None


class Heard:
    text = "is that you"


class FakeEars(Recorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.muted_for = []

    def read(self, timeout):
        return Heard()

    def mute_for(self, seconds):
        self.muted_for.append(seconds)


class FakeEvents(Recorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscriptions = {}

    def subscribe(self, event_type, **kwargs):
        self.subscriptions[kwargs["name"]] = (event_type, kwargs)
        Recorder.log.append(f"subscribe {event_type}")
        return object()

    def close(self):
        Recorder.log.append("close FakeEvents")

    def press(self):
        """Deliver a bump to whatever subscribed to it."""
        (_, kwargs), = self.subscriptions.values()
        kwargs["on_event"]({"isContacted": True})


class FakeTranscriber(Recorder):
    def transcribe(self, pcm, sample_rate):
        return ""


class FakeWakeDetector(Recorder):
    pass


class FakeLiveInput(Recorder):
    """Finite stand-in for the hardware-unverified wake adapter wiring."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audio = kwargs["audio"]
        self._read = False

    def start(self):
        super().start()
        self.audio.start()

    def read(self):
        if self._read:
            return None
        self._read = True
        return InputArrival(
            age_s=0.0,
            input=TimedText(
                Heard.text,
                facts={"wake_phrase": "hey misty"},
            ),
        )

    def read_available(self):
        return ()

    def stop(self):
        self.audio.stop()
        super().stop()


@pytest.fixture
def built(monkeypatch):
    """Every real driver, replaced by a recorder, and the log they share."""
    Recorder.log = []
    made = {}

    for name, double in [
        ("RobotCommands", FakeCommands),
        ("AvSession", FakeAvSession),
        ("RtspVideoStream", FakeVideo),
        ("DistancePipeline", FakeReadings),
        ("AudioStream", FakeEars),
        ("EventStream", FakeEvents),
        ("OpenAITranscriber", FakeTranscriber),
        ("PocketSphinxWakeDetector", FakeWakeDetector),
        ("LiveInputAdapter", FakeLiveInput),
    ]:
        def factory(*args, _double=double, _name=name, **kwargs):
            made[_name] = _double(*args, **kwargs)
            return made[_name]

        monkeypatch.setattr(f"misty_agent.app.{name}", factory)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    return made


# ---------------------------------------------------------------------------
# Everything gets built, and gets the one thing it needs
# ---------------------------------------------------------------------------

def test_every_real_driver_is_built(built):
    main(["--robot", "10.0.0.7", "--said", "hi"], model=Says(), clock=FakeClock())

    assert set(built) == {
        "RobotCommands",
        "AvSession",
        "RtspVideoStream",
        "DistancePipeline",
        "AudioStream",
        "EventStream",
        "OpenAITranscriber",
        "PocketSphinxWakeDetector",
        "LiveInputAdapter",
    }


def test_the_address_reaches_both_things_that_need_it(built):
    """The robot talks HTTP and the event stream talks WebSocket, to the same
    machine. Two addresses would be two robots."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert built["RobotCommands"].ip == "10.0.0.7"  # from `RobotCommands`
    assert built["EventStream"].args[0] == "10.0.0.7"


def test_the_video_and_the_audio_share_one_av_session(built):
    """Misty publishes one RTSP stream and it carries both. A second
    `AvSession` would reset the first one out from under it."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    session = built["AvSession"]
    assert built["RtspVideoStream"].args[0] is session
    assert built["AudioStream"].args[0] is session


def test_the_distance_pipeline_reads_the_video_stream(built):
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert built["DistancePipeline"].args[0] is built["RtspVideoStream"]


# ---------------------------------------------------------------------------
# The wires that were forgotten last time
# ---------------------------------------------------------------------------

def test_the_foot_bumper_is_subscribed_to_at_all(built):
    """One subscription, on the event Misty publishes for it."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    subscribed = built["EventStream"].subscriptions
    assert [event for event, _ in subscribed.values()] == ["BumpSensor"]


def test_a_press_between_episodes_still_stops_the_motors(built):
    """No Episode to abort, but the motors are just as real."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())
    Recorder.log.clear()

    built["EventStream"].press()

    assert "halt" in built["RobotCommands"].endpoints


def test_the_foot_bumper_aborts_the_episode_that_is_running(built, capsys):
    """`PLAN.md` §15.34: `EmergencyStop` was built, tested, and unwired.

    The test above is not this one. `Session.bumper_pressed` halts the motors
    either way, so "the robot stopped" is satisfied by the between-Episodes
    fallback and proves nothing about the wire that matters. What matters is
    the other branch: a press *during* an Episode goes through that Episode's
    own `EmergencyStop`, which is what records the interruption at the moment
    the foot landed and ends the loop.

    Asserted through the rendered Journal, which is the whole chain —
    subscription callback, Session, `EmergencyStop`, Journal, renderer.
    """
    class PressesTheBumperMidEpisode:
        asked = 0

        def decide(self, working_context, tools):
            PressesTheBumperMidEpisode.asked += 1
            built["EventStream"].press()
            return Decision(
                tool="speak", args={"text": "hi"}, tokens_in=1, tokens_out=1
            )

    main(["--robot", "10.0.0.7"], model=PressesTheBumperMidEpisode(),
         clock=FakeClock())

    printed = capsys.readouterr().out
    assert "stop requested by foot_bumper" in printed
    assert "episode aborted" in printed


def test_the_microphone_reaches_the_tool_that_has_to_mute_it(built):
    """The other half of §15.34: `ToolContext.ears` was unwired too.

    `speak` mutes the microphone for as long as it will be talking, so Misty
    does not transcribe herself. An unwired one means she hears her own voice
    and answers it.
    """
    main(["--robot", "10.0.0.7", "--said", "hi"],
         model=Says("speak", "done"), clock=FakeClock())

    assert built["AudioStream"].muted_for != []


def test_the_audio_stream_is_told_the_sessions_clock(built):
    """The mute window is measured against it. A second clock makes the window
    open and close at times unrelated to the Episode it belongs to."""
    clock = FakeClock()

    main(["--robot", "10.0.0.7"], model=Says(), clock=clock)

    # `==`, not `is`: attribute access makes a fresh bound method each time,
    # and two of them compare equal exactly when they wrap the same object.
    assert built["AudioStream"].kwargs["monotonic"] == clock.monotonic
    assert built["AudioStream"].kwargs["monotonic"].__self__ is clock


def test_what_the_wake_adapter_hears_reaches_the_model_as_trigger_evidence(built):
    """The first version of this asserted `is not HEARS_NOTHING`, which is
    true of every double in this file — it checked that a fake is a fake, and
    stayed green with `ears=` dropped from the `Session` entirely.

    What has to hold is the whole path: `AudioStream` → `Session.ears` →
    `LivePerception` → the Snapshot the model reads.
    """
    model = Says("speak", "done")

    main(["--robot", "10.0.0.7"], model=model, clock=FakeClock())

    evidence = next(
        entry
        for entry in model.contexts[0]
        if entry.get("role") == "user"
    )["content"][0]["text"]["trigger_evidence"]
    assert evidence["transcript"] == Heard.text
    assert evidence["facts"]["wake_phrase"] == "hey misty"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_the_stream_is_stopped_after_the_things_reading_it(built):
    """`RtspVideoStream.stop()` closes the `AvSession`, and `AudioStream` is
    reading that same session. Stopping the video first leaves the audio
    threads reading a stream that has been shut.
    """
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    order = [line for line in Recorder.log if line.startswith("stop ")]
    assert order.index("stop FakeEars") < order.index("stop FakeVideo")
    assert order.index("stop FakeReadings") < order.index("stop FakeVideo")


def test_everything_started_is_stopped(built):
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    for name in ("RtspVideoStream", "DistancePipeline", "AudioStream"):
        assert built[name].started, name
        assert built[name].stopped, name
    assert "close FakeEvents" in Recorder.log


def test_the_drivers_are_released_even_when_the_episode_raises(built, monkeypatch):
    """Threads and a websocket outlive an exception. A path that only tidies
    up on the happy one leaves them running.

    The failure is raised from perception rather than from the model: the
    ReAct loop deliberately catches what a model raises, halts the robot and
    closes the Episode as `error` (`PLAN.md` §15.34's neighbourhood), so a
    model that explodes never reaches the `finally` this is about.
    """
    class Unreadable(FakeReadings):
        def latest_reading(self):
            raise RuntimeError("the camera is on fire")

    monkeypatch.setattr("misty_agent.app.DistancePipeline", Unreadable)

    with pytest.raises(RuntimeError):
        main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert not built["AudioStream"].started
    assert not built["AudioStream"].stopped
    assert built["RtspVideoStream"].stopped


def test_a_robot_with_no_key_gets_no_ears_and_attaches_anyway(built, monkeypatch, tmp_path, capsys):
    """`PLAN.md` §16.18 says so in prose and nothing was checking it.

    The live attention adapter needs a hosted Transcriber, so without a key no
    AudioStream needs to be started. `HEARS_NOTHING` has `mute_for` and nothing
    else — no `start`, no `read` —
    so a keyless run that tried to start it raises `AttributeError` on a
    machine nobody can test. Every other test in this file sets a key, which
    is why two mutations lived here: dropping the guard, and building the
    transcriber unconditionally.

    A robot with no ears is still worth attaching to. Its camera answers, and
    that alone says the connection is up.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.app.API_KEY_FILE", str(tmp_path / "none"))

    code = main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert code == 0
    assert "OpenAITranscriber" not in built
    assert "AudioStream" not in built
    assert "LiveInputAdapter" not in built
    assert built["RtspVideoStream"].started
    assert "10.0.0.7: " in capsys.readouterr().out


def test_the_reported_line_names_the_robot_it_came_from(built, capsys):
    """The simulated path labels its number `simulated:` and a photograph
    labels it with the file (M8 #04 §16.14). A robot has to name itself for
    the same reason — a distance is only as good as where it came from."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert capsys.readouterr().out.startswith("10.0.0.7: ")


def test_a_driver_that_fails_to_start_does_not_get_stopped(built, monkeypatch):
    """`started` is appended to *after* each part comes up, so a failure part
    way through start-up stops exactly what started.

    Appending before starting is a one-line move that leaves every test here
    green while `stop()` is called on something that never ran — which, for a
    thread that was never spawned, is where the shutdown itself raises.
    """
    made = []

    class WillNotStart(FakeReadings):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

        def start(self):
            raise RuntimeError("the camera is unplugged")

    monkeypatch.setattr("misty_agent.app.DistancePipeline", WillNotStart)

    with pytest.raises(RuntimeError):
        main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    # On the instance, not on `Recorder.log`: the log is keyed by the runtime
    # class name, so a subclass writes `stop WillNotStart` and an assertion
    # about `stop FakeReadings` is vacuously true however the code behaves.
    (never_started,) = made
    assert built["RtspVideoStream"].stopped  # it did start, so it is stopped
    assert not never_started.stopped
    assert "AudioStream" not in built or not built["AudioStream"].started


# ---------------------------------------------------------------------------
# What it must not imply
# ---------------------------------------------------------------------------

def test_asking_for_a_robot_says_this_has_never_touched_one(built, capsys):
    """`PLAN.md` §8 changed its own wording for this reason: "not measured
    yet" reads like a half-finished project, and the truth is stronger —
    there is no robot here and there never will be. The command must not let
    anyone believe otherwise by staying quiet.
    """
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    warned = capsys.readouterr().err
    assert "never" in warned.lower()
    assert "PLAN.md" in warned


def test_a_photograph_and_a_robot_are_refused_together(built, capsys):
    """Ignoring one of them silently is how somebody ends up believing their
    photograph did something. A robot has a camera; the image flag exists to
    tell a *simulated* world where to put the person."""
    with pytest.raises(SystemExit):
        main(["--robot", "10.0.0.7", "--image", "someone.jpg"],
             model=Says(), clock=FakeClock())

    assert built == {}
    assert "--image and --robot" in capsys.readouterr().err


def test_an_empty_address_is_refused_rather_than_simulated(built, capsys):
    """`--robot ""` is falsy, so every branch that asks `if args.robot` would
    quietly simulate — and wanting something other than the simulation is the
    one thing typing `--robot` has told you."""
    with pytest.raises(SystemExit):
        main(["--robot", ""], model=Says(), clock=FakeClock())

    assert built == {}
    assert "--robot needs an address" in capsys.readouterr().err


def test_the_default_touches_no_driver_at_all(built, capsys):
    """The simulated path stays the default (M8 #04), and choosing it must not
    reach for a robot that is not there."""
    main(["--said", "hi"], model=Says(), clock=FakeClock())

    assert built == {}
    assert "never" not in capsys.readouterr().err.lower()

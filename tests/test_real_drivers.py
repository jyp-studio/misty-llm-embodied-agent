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

from misty_agent.agent.tools import HEARS_NOTHING
from misty_agent.app import main
from misty_agent.fakes import FakeClock

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


class FakeCommands(Recorder):
    def __init__(self, ip="127.0.0.1"):
        super().__init__(ip)
        self.ip = ip

    def stop_moving(self, **kwargs):
        Recorder.log.append("stop_moving")
        return None

    def halt(self, **kwargs):
        Recorder.log.append("halt")
        return None


class FakeAvSession(Recorder):
    pass


class FakeVideo(Recorder):
    pass


class FakeReadings(Recorder):
    def latest_reading(self):
        return None


class FakeEars(Recorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.muted_for = []

    def read(self, timeout):
        return None

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


class FakeTranscriber(Recorder):
    def transcribe(self, pcm, sample_rate):
        return ""


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
    }


def test_the_address_reaches_both_things_that_need_it(built):
    """The robot talks HTTP and the event stream talks WebSocket, to the same
    machine. Two addresses would be two robots."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert built["RobotCommands"].ip == "10.0.0.7"
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

def test_the_foot_bumper_reaches_the_emergency_stop(built):
    """`PLAN.md` §15.34: `EmergencyStop` was built, tested, and unwired.

    A press has to arrive at the Session, which is what owns the running
    Episode's stop. Without this the robot cannot be stopped by foot.
    """
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    subscribed = built["EventStream"].subscriptions
    assert [event for event, _ in subscribed.values()] == ["BumpSensor"]

    Recorder.log.clear()
    (_, kwargs), = subscribed.values()
    kwargs["on_event"]({"isContacted": True})

    assert "halt" in Recorder.log


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


def test_the_ears_are_what_the_snapshot_listens_to(built):
    """`LivePerception` reports `new_speech` from the Session's ears, and the
    Session's ears have to be the real `AudioStream`."""
    main(["--robot", "10.0.0.7"], model=Says(), clock=FakeClock())

    assert built["AudioStream"] is not HEARS_NOTHING


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

    assert built["AudioStream"].stopped
    assert built["RtspVideoStream"].stopped


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


def test_the_default_touches_no_driver_at_all(built, capsys):
    """The simulated path stays the default (M8 #04), and choosing it must not
    reach for a robot that is not there."""
    main(["--said", "hi"], model=Says(), clock=FakeClock())

    assert built == {}
    assert "never" not in capsys.readouterr().err.lower()

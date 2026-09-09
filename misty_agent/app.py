"""Putting the pieces together, and the one clock they all have to share.

Everything else in this package is a part: a driver, a controller, a Journal,
a loop. This is where they are wired into something that can be pointed at a
robot — and it is deliberately thin, because everything worth testing has
already been tested where it lives.

## The command

`main` is here too, and `__main__.py` only forwards to it. Starting the whole
thing *is* the last piece of this wiring, and a module run as
`python -m misty_agent` is imported under the name `__main__` — so anything
that later imported `misty_agent.__main__` to reuse the assembly would get a
second copy of it, constants and all.

## The Episode assembly seam

`Session.episode` owns the dependencies and safety boundary for exactly one
bounded Episode. `SocialAgentRuntime` is now the product's outer seam and
calls this method after selecting an Interaction Cue. Keeping the one-Episode
method public also leaves focused ReAct and driver tests a small interface.

## The clock

`Journal`, `run_episode`, `approach` and `AudioStream` each default to their
own reading of `time.monotonic`. Left alone, an Episode's recorded timestamps,
its measured model latency and its suppression window would come from four
clocks that merely happen to agree — and no test could ever say otherwise.
The session builds one and hands it to all of them.

## The foot bumper

Subscribed once and kept alive, because someone who puts a foot on the bumper
between Episodes still means it. The callback halts the robot either way, and
when an Episode is running it goes through that Episode's own `EmergencyStop`
so the interruption lands in the right Journal at the moment it happened
(`PLAN.md` §15.24). A single long-lived `EmergencyStop` could not do that:
it is single-shot by design, so the second press of an evening would be
swallowed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Tuple

from misty_agent.agent.journal import (
    Journal,
    JsonlFile,
    Snapshot,
    TerminalRenderer,
    in_view,
)
from misty_agent.agent.memory import Memory
# The two channels a key may arrive by, in order: the environment first
# because that is what the OpenAI SDK reads on its own, the JSON file second
# because `.env.example` and the README have promised it since before this
# rewrite. Both are named where the key is *needed*, so `MissingApiKey` can
# name them too — one definition, one paragraph of advice.
from misty_agent.agent.model import (
    API_KEY_FILE,
    API_KEY_VARIABLE,
    MissingApiKey,
    OpenAIModel,
    api_key_available,
)
from misty_agent.agent.persona import PERSONA
from misty_agent.agent.react import EpisodeOutcome, run_episode
from misty_agent.agent.stop import EmergencyStop
from misty_agent.agent.tools import HEARS_NOTHING, ToolContext, build_registry
from misty_agent.config import Settings, settings
from misty_agent.drivers.audio_stream import AudioStream
from misty_agent.drivers.av_stream import AvSession, RtspVideoStream
from misty_agent.drivers.events import EventStream, event_condition
from misty_agent.drivers.robot_commands import RobotCommands
from misty_agent.fakes import MovingWorld, RecordingCommands
from misty_agent.perception.asr import OpenAITranscriber
from misty_agent.perception.distance import NOBODY_THERE, DistancePipeline
from misty_agent.runtime import (
    EvidenceKind,
    ScenarioInputAdapter,
    SocialAgentRuntime,
    TimedText,
)


class SystemClock:
    """The real clock, in one object so the session can hand out one clock.

    `journal.py` and `control/approach.py` each define a private one as their
    own default. This is neither: it is the *shared* clock, and it exists
    because it has to satisfy both of their protocols at once — `monotonic`
    for the Journal, `monotonic` and `sleep` for the controller.
    """

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def load_api_key(path: str = API_KEY_FILE) -> Optional[str]:
    """Find a key and put it where the SDK will look.

    Two channels rather than one because `.env.example` documents both, and a
    file that says a thing works is a promise. The environment wins: an
    explicit `export` should not be silently overridden by a file someone
    forgot about.
    """
    existing = os.environ.get(API_KEY_VARIABLE, "").strip()
    if existing:
        return existing
    try:
        with open(path, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries if isinstance(entries, list) else []:
        key = (entry or {}).get("api_key", "") if isinstance(entry, dict) else ""
        if isinstance(key, str) and key.strip():
            os.environ[API_KEY_VARIABLE] = key.strip()
            return key.strip()
    return None


class LivePerception:
    """The three facts `PLAN.md` §15.4 fixed the Snapshot at.

    All three are already being produced — this reads them, it does not start
    anything. `face_present` is "there is a fresh distance reading", because
    the distance *is* a face measurement: the pipeline derives it from face
    width, so a reading existing is the same statement as a face being in
    view. Saying it here rather than leaving a reader to infer it.
    """

    def __init__(self, readings: Any, ears: Optional[Any] = None) -> None:
        self._readings = readings
        self._ears = ears

    def snapshot(self) -> Snapshot:
        reading = self._readings.latest_reading()
        return Snapshot(
            distance_cm=reading.distance_cm if reading is not None else None,
            face_present=reading is not None,
            new_speech=self._heard(),
        )

    def _heard(self) -> Optional[str]:
        if self._ears is None:
            return None
        utterance = self._ears.read(timeout=0)
        return utterance.text if utterance is not None else None


@dataclass
class Session:
    """Everything an Episode needs, built once and shared."""

    robot: Any
    readings: Any
    model: Any
    memory: Memory
    #: `HEARS_NOTHING` rather than `None`: `speak` mutes unconditionally, and
    #: a session with no microphone is still a session.
    ears: Any = HEARS_NOTHING
    #: What the model is told it is, before anything else. A field rather
    #: than `run_episode`'s default, because every other seam that function
    #: takes — `model`, `memory`, `stop`, the `ToolContext` — is passed from
    #: here explicitly, and the one that was not is the one two reviews found
    #: had no caller outside its own tests (`PLAN.md` §16.12).
    instructions: str = PERSONA
    events: Optional[Any] = None
    config: Settings = settings
    clock: Any = None
    #: Set while an Episode is running, so the bumper knows where to report.
    _running: Optional[EmergencyStop] = None
    _episodes: int = 0
    _bumper_watched: bool = field(default=False, init=False, repr=False)
    _bumper_name: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self.clock = self.clock or SystemClock()
        if self.ears is None:
            self.ears = HEARS_NOTHING
        # EventStream names are unique within a stream. The callback belongs
        # to this Session, so shared streams need one name per Session.
        self._bumper_name = f"EmergencyFootStop-{id(self)}"
        self.watch_the_bumper()

    # ---------- the bumper ----------

    def watch_the_bumper(self) -> None:
        """Subscribe once, for as long as the session lasts."""
        if self.events is None or self._bumper_watched:
            return
        subscription = self.events.subscribe(
            "BumpSensor",
            name=self._bumper_name,
            condition=[event_condition("isContacted", "=", True)],
            debounce_ms=1000,
            keep_alive=True,
            on_event=lambda payload: self.bumper_pressed(),
        )
        if subscription is None:
            raise RuntimeError("bumper subscription was not created")
        self._bumper_watched = True

    def bumper_pressed(self) -> None:
        """Stop everything, and tell the Episode if there is one.

        Between Episodes there is nothing to record and nothing to abort, but
        the motors are just as real — so the halt happens either way. Inside
        one, the Episode's own `EmergencyStop` does it, because that is what
        writes the record at the moment the foot landed.
        """
        self.request_stop("foot_bumper")

    def request_stop(self, source: str) -> bool:
        """Ask the active Episode to abort and always leave motion halted.

        Runtime shutdown and a bumper are different sources of the same
        bounded interruption.  The runtime uses this public boundary rather
        than reaching into ``_running`` or pretending shutdown was a foot. If
        the Episode closed while this call was arriving, its Journal refuses
        another record; the physical halt still has to happen (``PLAN.md``
        §15.35).
        """
        running = self._running
        if running is not None:
            try:
                return running.request(source)
            except Exception:
                pass
        try:
            self.robot.halt()
        except Exception:
            # This may run on the bumper callback's thread, where nothing
            # would catch it. ``stop.py`` gives the same reasoning at length.
            pass
        return False

    def _microphone(self) -> Optional[Any]:
        """The ears, but only if they can actually be listened to.

        `HEARS_NOTHING` can be told to mute; it has nothing to read back.
        The Snapshot needs that second half, so a session without a real
        microphone reports no speech rather than reaching for a method that
        is not there.
        """
        return self.ears if hasattr(self.ears, "read") else None

    def _perception(self):
        return LivePerception(self.readings, self._microphone())

    def sees(self) -> Snapshot:
        """What a Snapshot would say if a Tool returned right now.

        The Episode's own Snapshots come from the same construction, so this
        is not a second opinion. It exists because an entry point has to be
        able to report what perception made of the world *before* deciding
        whether there is a model to ask about it (M8 #04).
        """
        return self._perception().snapshot()

    # ---------- one Episode ----------

    def episode(
        self,
        trigger: str,
        said: str = "",
        *,
        render: bool = True,
        journal_path: Optional[pathlib.Path] = None,
    ) -> Tuple[EpisodeOutcome, Journal]:
        """Run one Episode from one trigger, and hand back what happened.

        `journal_path` writes the Journal to disk as it happens. Per Episode
        rather than per Session, because one file holds one Episode: that is
        what every golden is and what `from_jsonl` assumes — it returns a flat
        sequence and does not group, so a file with two beginnings in it reads
        as one incoherent run.

        A subscriber rather than a `to_jsonl()` at the end, because an Episode
        that is interrupted should still leave behind what it got through
        (`JsonlFile`'s whole reason for appending line by line).
        """
        # Counted as well as stamped: two Episodes inside the same second
        # are ordinary, and two Journals sharing an id would be
        # indistinguishable in a directory of them.
        self._episodes += 1
        episode_id = f"ep-{int(time.time())}-{self._episodes}"
        subscribers: list = [TerminalRenderer()] if render else []
        if journal_path is not None:
            subscribers.append(JsonlFile(journal_path))
        journal = Journal(
            episode_id=episode_id, clock=self.clock, subscribers=subscribers
        )
        stop = EmergencyStop(journal, self.robot)
        self._running = stop
        try:
            outcome = run_episode(
                trigger,
                said=said,
                model=self.model,
                registry=build_registry(),
                ctx=ToolContext(
                    robot=self.robot,
                    readings=self.readings,
                    config=self.config,
                    clock=self.clock,
                    ears=self.ears,
                ),
                journal=journal,
                perception=self._perception(),
                stop=stop,
                memory=self.memory,
                instructions=self.instructions,
            )
        finally:
            self._running = None
        return outcome, journal


# ---------- the command ----------

#: Where the person is standing when no photograph says otherwise. Far enough
#: that `approach` has something to do, and inside the range the M5 report
#: measured — a demo that starts already arrived demonstrates nothing.
DEFAULT_START_CM = 150

#: The two kinds of thing that start an Episode. `CONTEXT.md` gives an Episode
#: exactly one external trigger, and these are the two the goldens carry.
TRIGGERS = tuple(kind.value for kind in EvidenceKind)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m misty_agent",
        description=(
            "Run one finite SocialAgentRuntime scenario. By default the robot "
            "is simulated and only perception is real; --robot attaches to "
            "a Misty II instead, which nothing here has ever done."
        ),
    )
    parser.add_argument(
        "--trigger",
        choices=TRIGGERS,
        default="speech",
        help="what set this Episode off (default: speech)",
    )
    parser.add_argument(
        "--said",
        default="",
        help="what the person said, as speech-to-text would have heard it",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "open the demo page in a browser instead of running an Episode. "
            "Serves on this machine only"
        ),
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help=(
            "with --demo, accept a recording as the trigger. Off by default: "
            "it goes to hosted transcription, which needs a key and costs "
            "money on your account"
        ),
    )
    parser.add_argument(
        "--robot",
        metavar="IP",
        default=None,
        help=(
            "attach to a Misty II at this address instead of simulating one. "
            "NEVER RUN: this project has no robot (PLAN.md section 8)"
        ),
    )
    parser.add_argument(
        "--journal",
        metavar="PATH",
        type=pathlib.Path,
        default=None,
        help=(
            "write this Episode's Journal to PATH as JSONL, in the format "
            "tests/goldens uses. Nothing is written without it"
        ),
    )
    parser.add_argument(
        "--image",
        type=pathlib.Path,
        default=None,
        help=(
            "a photograph to run through face detection and distance "
            "estimation; where the person is standing comes from it"
        ),
    )
    return parser


def decode_image(data: bytes) -> Optional[Any]:
    """An uploaded image as a frame, or `None` if it is not one.

    In memory throughout: M8 #10 asks that nothing uploaded is left on disk,
    and the shortest way to break that promise is a temporary file.
    """
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def look_at(frame: Any) -> Any:
    """What the real pipeline makes of one image. No robot, and no API key.

    Split from the assembly below so that a caller holding *bytes* rather
    than a path can use it — the demo page hands over an upload, and M8 #10
    forbids putting it on disk to read it back.
    """
    from misty_agent.perception.face import FaceDetector

    with FaceDetector() as detector:
        return detector.detect(frame)


def room_for(seen: Optional[Any], clock: Any) -> Tuple[Any, Any]:
    """The robot and the readings, as one pair because the world is one thing.

    `MovingWorld` is both: it answers drive commands and it answers
    `latest_reading`, which is what makes the distance it reports respond to
    the driving. An empty room needs the two split, because there is a robot
    but nobody to measure.

    `seen` is `None` when nothing was looked at, which is not the same as
    having looked and found nobody: the first gets the default simulated
    world, the second gets a room with nobody in it.
    """
    if seen is None:
        world = MovingWorld(clock, start_cm=DEFAULT_START_CM, config=settings)
        return world, world
    if not seen.has_human:
        return RecordingCommands(), NOBODY_THERE
    world = MovingWorld(clock, start_cm=seen.distance_cm, config=settings)
    return world, world


def simulated_session(
    seen: Optional[Any], *, model: Any, clock: Any
) -> Session:
    """One Session against a simulated robot, with the person where
    perception put them. Shared by the command and the demo page, so both
    reach a model through exactly the same assembly."""
    robot, readings = room_for(seen, clock)
    return Session(
        robot=robot,
        readings=readings,
        model=model,
        memory=Memory(),
        config=settings,
        clock=clock,
    )


def _looked_at(image: Optional[pathlib.Path]) -> Optional[Any]:
    """The command's half: read the file, then hand the frame to perception.

    `None` back means nothing was looked at, which `room_for` treats as a
    different thing from having looked and found nobody.
    """
    if image is None:
        return None

    import cv2

    frame = cv2.imread(str(image))
    if frame is None:
        raise FileNotFoundError(image)
    return look_at(frame)


#: What `--robot` has to say for itself, every time.
#:
#: `PLAN.md` §8 rewrote its own heading for this reason. "Not yet verified"
#: reads like a half-finished project that will get round to it; the truth is
#: both stronger and simpler, and a command that stayed quiet would let a
#: reader assume the friendlier version.
NEVER_RUN_ON_HARDWARE = """\
--robot has never been run against a Misty II. This project does not have one
and will not get one (PLAN.md §8), so everything below this line is what the
robot's documentation says it does — not what a robot did. The request shapes
have contract tests; the behaviour has nothing.
"""


@contextlib.contextmanager
def attached_to(
    ip: str, *, model: Any, clock: Any, transcriber: Optional[Any] = None
) -> Iterator[Session]:
    """The real drivers, wired to each other, for as long as the caller needs.

    Five collaborators around one AV session: Misty publishes a single RTSP
    stream and it carries both the picture and the sound, so a second
    `AvSession` would reset the first one out from under it.

    ## Started in order, stopped in reverse — and that is load-bearing

    `RtspVideoStream.stop()` closes the `AvSession`, which is the same session
    `AudioStream` is reading. Stop the video first and the audio threads are
    left reading a stream that has been shut. `started` is appended to as each
    part comes up, so a failure half way through start-up stops exactly what
    started, and nothing else.

    ## The clock reaches as far as it can, and no further

    `Session` and `AudioStream` are told the clock. `RtspVideoStream` and
    `DistancePipeline` are not — they stamp frames and readings by calling
    `time.monotonic()` themselves, and neither takes a clock to call instead.

    That matters because `approach` compares a reading's `frame_arrived_at`
    against the *Session's* clock to decide whether it is fresh. On this path
    they agree, because `SystemClock.monotonic` is `time.monotonic` — the same
    function, not two that happen to match. **A fake clock here would break
    the freshness test**, in exactly the way M8 #04 found a second clock
    breaks it for the simulated world. `tests/test_real_drivers.py` passes one
    anyway, and may: it replaces the two classes that read the clock directly,
    so there is nothing left in it for a fake clock to disagree with.

    Adding a clock parameter to those two so this docstring could say "all
    of them" would be a parameter with one caller passing one value, which is
    the shape `PLAN.md` §15.23 deleted. Recorded instead (`PLAN.md` §16.18).

    ## Without a key there are no ears

    `AudioStream` needs a `Transcriber`, and the hosted one needs a key. A
    robot with no ears is still worth attaching to — its camera answers, and
    that alone tells you the connection works — so this takes `HEARS_NOTHING`
    rather than refusing.

    **Nothing here has ever run.** See `NEVER_RUN_ON_HARDWARE`.
    """
    commands = RobotCommands(ip)
    stream = AvSession(commands)
    video = RtspVideoStream(stream)
    readings = DistancePipeline(video)
    if transcriber is None:
        ears, listening = HEARS_NOTHING, ()
    else:
        ears = AudioStream(stream, transcriber, monotonic=clock.monotonic)
        listening = (ears,)
    events = EventStream(ip)

    started: list = []
    try:
        for part in (video, readings, *listening):
            part.start()
            started.append(part)
        # Built inside the `try`: its constructor subscribes the bumper, and
        # a subscription that comes back empty raises — at which point four
        # threads and a websocket are already running.
        yield Session(
            robot=commands,
            readings=readings,
            model=model,
            memory=Memory(),
            ears=ears,
            events=events,
            config=settings,
            clock=clock,
        )
    finally:
        events.close()
        for part in reversed(started):
            part.stop()


def main(argv: Optional[list] = None, *, model: Any = None, clock: Any = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.audio and not args.demo:
        parser.error("--audio is a --demo option: it accepts an upload")
    if args.demo:
        # Refused rather than ignored, the same as `--image` with `--robot`:
        # the demo replays Episodes that already finished, so every one of
        # these asks for something it will not do, and silence would let
        # somebody believe their photograph or their key had been used.
        alongside = [
            flag
            for flag, given in (
                ("--said", args.said),
                ("--image", args.image is not None),
                ("--robot", args.robot is not None),
                ("--journal", args.journal is not None),
            )
            if given
        ]
        if alongside:
            # `--journal` is refused for its own reason and it is not this
            # one: a Journal file holds one Episode (#06), and the page can
            # run as many as somebody clicks. The others are refused because
            # the page asks for its own trigger, its own photograph, and
            # never touches a robot.
            parser.error(
                f"--demo runs Episodes the page asks for, so it cannot also "
                f"{' or '.join(alongside)}"
            )
        # Returns when the person stops it. Nothing below runs.
        from misty_agent.demo import serve

        serve(audio=args.audio)
        return 0
    if args.robot is not None and not args.robot.strip():
        # Falsy, so every `if args.robot` below would quietly simulate — and
        # the one thing somebody typing `--robot` has told you is that they
        # did not want the simulation.
        parser.error("--robot needs an address")
    if args.journal is not None:
        # `JsonlFile` refuses both of these on its own, by creating the file
        # exclusively. These are here only so the two mistakes somebody
        # actually makes arrive as a sentence rather than as a `FileExistsError`
        # traceback — the guarantee lives with the format, not with the flag.
        if args.journal.is_dir():
            parser.error(f"{args.journal} is a directory, not a file to write")
        if args.journal.exists():
            parser.error(
                f"{args.journal} already exists, and a Journal file holds one "
                f"Episode. Choose another path"
            )
        if not args.journal.parent.is_dir():
            parser.error(
                f"{args.journal.parent} is not a directory, so "
                f"{args.journal} cannot be written"
            )
    if args.robot and args.image is not None:
        # Refused rather than ignored. A photograph sets where the person
        # starts in a *simulated* world; a real robot has a camera, and the
        # readings that come out of it are the ones that change when it
        # drives. Accepting both and quietly honouring one is how somebody
        # ends up believing their photograph did something.
        parser.error(
            "--image and --robot are alternatives: with a robot attached, "
            "its own camera is what produces the readings"
        )
    clock = clock or SystemClock()
    # Only when something is actually going to need one. It is read early
    # because the hosted transcriber needs the same key the model does and is
    # built before the drivers are — but `load_api_key` *exports* what it
    # finds, and a command given a model and no robot has no business
    # touching the environment on its way past.
    needs_a_key = model is None or args.robot
    key = load_api_key(API_KEY_FILE) if needs_a_key else None
    asked = model if model is not None else OpenAIModel()

    if args.robot:
        print(NEVER_RUN_ON_HARDWARE, file=sys.stderr)
        with attached_to(
            args.robot,
            model=asked,
            clock=clock,
            transcriber=OpenAITranscriber(key) if key else None,
        ) as session:
            return _one_runtime(
                session, args, source=args.robot, must_find_a_key=model is None
            )

    try:
        seen = _looked_at(args.image)
    except FileNotFoundError as missing:
        print(f"could not read {missing}", file=sys.stderr)
        return 1

    # The same assembly the demo page reaches a model through, so a run from
    # the command line and a run from the browser cannot diverge.
    session = simulated_session(seen, model=asked, clock=clock)
    source = "simulated" if args.image is None else args.image
    return _one_runtime(
        session, args, source=source, must_find_a_key=model is None
    )


def _one_runtime(
    session: Session, args: Any, *, source: Any, must_find_a_key: bool
) -> int:
    """Report perception, then run one Explicit Request through the runtime.

    The same six lines whichever world was assembled — which is the point of
    assembling one before getting here. `source` is what produced the number
    being reported, because a distance is only as good as where it came from.
    """
    seen = session.sees()
    # Named by where the number came from. A photograph is perception; the
    # default is `DEFAULT_START_CM` and calling that "perception" would be the
    # entry point claiming a camera it did not use — the same invention
    # `PLAN.md` §16.13 refuses for an image with no face in it.
    #
    # Flushed because the next thing written may go to stderr, and stdout is
    # block-buffered whenever this is piped into anything. Without it the
    # no-key guidance appears above the result it is answering.
    print(f"{source}: {in_view(seen)}", flush=True)

    if must_find_a_key and not api_key_available():
        print(str(MissingApiKey()), file=sys.stderr)
        return 1

    # The renderer already writes the closing line — `episode done after 3
    # turn(s), 3 step(s)`. Printing the same three facts again underneath it,
    # in a second phrasing, is `PLAN.md` §15.4's two copies of one fact, and
    # they had already diverged: one said `turn(s)`, the other `turns`.
    #
    # The exit code says whether the *command* ran, not how the Episode ended.
    # An Episode that hits its Turn cap or is aborted did what it was built to
    # do, and the one outcome that is a failure — `error` — is already
    # reported, in the Journal and on the terminal, by the thing that saw it.
    result = SocialAgentRuntime(
        source=ScenarioInputAdapter(
            session.clock,
            [
                TimedText(
                    at_s=0.0,
                    text=args.said,
                    evidence_kind=EvidenceKind(args.trigger),
                )
            ],
        ),
        session=session,
        clock=session.clock,
    ).run(render=True, journal_path=args.journal)
    if not result.episodes:
        failure = next(
            (
                record
                for record in result.records
                if record.type == "runtime_failed"
            ),
            None,
        )
        message = failure.message if failure is not None else result.ending
        print(f"the runtime did not open an Episode: {message}", file=sys.stderr)
        return 1
    journal = result.episodes[0].journal

    # A subscriber that raises is caught, recorded and carried on from — which
    # is right for a renderer and wrong for the evidence. Somebody who asked
    # for a Journal and got a clean exit code has been told the run was kept.
    lost = [
        failure
        for failure in journal.subscriber_failures
        if failure.subscriber == "JsonlFile"
    ]
    if lost:
        print(
            f"the Journal was not written: {lost[0].error}", file=sys.stderr
        )
        return 1
    return 0

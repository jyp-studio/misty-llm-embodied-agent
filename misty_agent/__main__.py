"""``python -m misty_agent`` — run one Episode, with no robot in the room.

M7 finished the agent and left it unstartable. `Session` takes collaborators
that have already been built; until this file, the only things that built them
were tests. This is the command M8 #04 asks for:

    .venv/bin/python -m misty_agent --said "come here"
    .venv/bin/python -m misty_agent --trigger visual --image photo.jpg

## What is simulated and what is not

The robot is fake and the room is arithmetic: `MovingWorld` moves the observed
distance by whatever a drive command asked for, which is the smallest world in
which `approach` can converge and therefore the smallest one in which an
Episode can be watched happening. `PLAN.md` §1 is why — there is no Misty II
here and there never was.

**Perception is not simulated.** `--image` goes through the same MediaPipe
face mesh and the same distance estimate the M4/M5 measurements were taken
against, and the number that comes out is where the person starts. An image
with nobody in it produces a room with nobody in it, rather than a default
distance the camera never saw.

## One clock

`PLAN.md` §15.34 lists things that were built and never wired together; a
second clock is how that happens to time. The world, the Journal, the
`ToolContext` and the `EmergencyStop` all come from the one built here, and
the world is handed it explicitly because `MovingWorld` stamps its readings —
a world on its own clock produces readings that are never fresh, and
`approach` reports a lost person forever.

## Without a key

Perception runs first and reports, and only then does the command look for a
key. Somebody who has just cloned this should find out what the camera made
of their photograph even when they cannot yet pay for a model call, and
should be told what to do about it — `MissingApiKey` already writes that
paragraph, so this does not write a second one.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any, Optional, Tuple

from misty_agent.agent.memory import Memory
from misty_agent.agent.model import MissingApiKey, OpenAIModel, api_key_available
from misty_agent.app import API_KEY_FILE, Session, SystemClock, load_api_key
from misty_agent.config import settings
from misty_agent.fakes import NOBODY_THERE, MovingWorld, RecordingCommands

#: Where the person is standing when no photograph says otherwise. Far enough
#: that `approach` has something to do, and inside the range the M5 report
#: measured — a demo that starts already arrived demonstrates nothing.
DEFAULT_START_CM = 150

#: The two kinds of thing that start an Episode. `CONTEXT.md` gives an Episode
#: exactly one external trigger, and these are the two the goldens carry.
TRIGGERS = ("speech", "visual")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m misty_agent",
        description=(
            "Run one Episode against a simulated robot. Perception is real; "
            "the robot is not."
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
        "--image",
        type=pathlib.Path,
        default=None,
        help=(
            "a photograph to run through face detection and distance "
            "estimation; where the person is standing comes from it"
        ),
    )
    return parser


def _the_room(image: Optional[pathlib.Path], clock: Any) -> Tuple[Any, Any]:
    """The robot and the readings, as one pair because the world is one thing.

    `MovingWorld` is both: it answers drive commands and it answers
    `latest_reading`, which is what makes the distance it reports respond to
    the driving. An empty room needs the two split, because there is a robot
    but nobody to measure.
    """
    if image is None:
        world = MovingWorld(clock, start_cm=DEFAULT_START_CM, config=settings)
        return world, world

    import cv2

    frame = cv2.imread(str(image))
    if frame is None:
        raise FileNotFoundError(image)

    from misty_agent.perception.face import FaceDetector

    with FaceDetector() as detector:
        seen = detector.detect(frame)
    if not seen.has_human:
        return RecordingCommands(), NOBODY_THERE
    world = MovingWorld(clock, start_cm=seen.distance_cm, config=settings)
    return world, world


def main(argv: Optional[list] = None, *, model: Any = None, clock: Any = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or SystemClock()

    try:
        robot, readings = _the_room(args.image, clock)
    except FileNotFoundError as missing:
        print(f"could not read {missing}", file=sys.stderr)
        return 1

    session = Session(
        robot=robot,
        readings=readings,
        model=model if model is not None else OpenAIModel(),
        memory=Memory(),
        config=settings,
        clock=clock,
    )

    seen = session.sees()
    # Flushed because the next thing written may go to stderr, and stdout is
    # block-buffered whenever this is piped into anything. Without it the
    # no-key guidance appears above the perception result it is answering.
    print(f"perception: {_describe(seen)}", flush=True)

    if model is None:
        load_api_key(API_KEY_FILE)
        if not api_key_available():
            print(str(MissingApiKey()), file=sys.stderr)
            return 1

    outcome, _ = session.episode(args.trigger, args.said)
    print(
        f"{outcome.outcome} after {_count(outcome.turns, 'turn')} "
        f"and {_count(outcome.steps, 'step')}"
    )
    return 0


def _count(many: int, noun: str) -> str:
    return f"{many} {noun}" if many == 1 else f"{many} {noun}s"


def _describe(snapshot: Any) -> str:
    """The Snapshot as one line, before there is any Journal to render.

    Deliberately not `journal.describe`: that reads a Record, and there is no
    Record yet — this is what perception says with nothing having happened.
    """
    if not snapshot.face_present:
        return "nobody in view"
    heard = f", heard {snapshot.new_speech!r}" if snapshot.new_speech else ""
    return f"someone {snapshot.distance_cm}cm away{heard}"


if __name__ == "__main__":
    raise SystemExit(main())

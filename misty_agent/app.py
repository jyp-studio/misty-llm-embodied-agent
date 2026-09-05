"""Putting the pieces together, and the one clock they all have to share.

Everything else in this package is a part: a driver, a controller, a Journal,
a loop. This is where they are wired into something that can be pointed at a
robot — and it is deliberately thin, because everything worth testing has
already been tested where it lives.

## One Episode, not a session

`PLAN.md` §15.1: the public entry is "feed one trigger, run one Episode".
There is no "wait until somebody speaks" loop, and that is a decision rather
than an omission — the outer loop needs the audio stream, and `HANDOFF.md` §4
records that its transcription and voice detection share a thread, a defect
nobody has fixed. Building ReAct on top of it would be building on that.

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

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from misty_agent.agent.journal import Journal, Snapshot, TerminalRenderer
from misty_agent.agent.memory import Memory
from misty_agent.agent.react import EpisodeOutcome, run_episode
from misty_agent.agent.stop import EmergencyStop
from misty_agent.agent.tools import HEARS_NOTHING, ToolContext, build_registry
from misty_agent.config import Settings, settings
from misty_agent.drivers.events import event_condition

#: Where a key may come from, in order. The environment first because that is
#: what the OpenAI SDK reads on its own; the JSON file second because
#: `.env.example` and the README have promised it since before this rewrite.
API_KEY_VARIABLE = "OPENAI_API_KEY"
API_KEY_FILE = "OAI_CONFIG_LIST.json"


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
    events: Optional[Any] = None
    config: Settings = settings
    clock: Any = None
    #: Set while an Episode is running, so the bumper knows where to report.
    _running: Optional[EmergencyStop] = None
    _episodes: int = 0

    def __post_init__(self) -> None:
        self.clock = self.clock or SystemClock()
        if self.ears is None:
            self.ears = HEARS_NOTHING

    # ---------- the bumper ----------

    def watch_the_bumper(self) -> None:
        """Subscribe once, for as long as the session lasts."""
        if self.events is None:
            return
        self.events.subscribe(
            "BumpSensor",
            name="EmergencyFootStop",
            condition=[event_condition("isContacted", "=", True)],
            debounce_ms=1000,
            keep_alive=True,
            on_event=lambda payload: self.bumper_pressed(),
        )

    def bumper_pressed(self) -> None:
        """Stop everything, and tell the Episode if there is one.

        Between Episodes there is nothing to record and nothing to abort, but
        the motors are just as real — so the halt happens either way. Inside
        one, the Episode's own `EmergencyStop` does it, because that is what
        writes the record at the moment the foot landed.
        """
        running = self._running
        if running is not None:
            running.request("foot_bumper")
            return
        try:
            self.robot.halt()
        except Exception:
            # The sensor's thread, where nothing would catch it. `stop.py`
            # gives the same reasoning at more length.
            pass

    def _microphone(self) -> Optional[Any]:
        """The ears, but only if they can actually be listened to.

        `HEARS_NOTHING` can be told to mute; it has nothing to read back.
        The Snapshot needs that second half, so a session without a real
        microphone reports no speech rather than reaching for a method that
        is not there.
        """
        return self.ears if hasattr(self.ears, "read") else None

    # ---------- one Episode ----------

    def episode(
        self, trigger: str, said: str = "", *, render: bool = True
    ) -> Tuple[EpisodeOutcome, Journal]:
        """Run one Episode from one trigger, and hand back what happened."""
        # Counted as well as stamped: two Episodes inside the same second
        # are ordinary, and two Journals sharing an id would be
        # indistinguishable in a directory of them.
        self._episodes += 1
        episode_id = f"ep-{int(time.time())}-{self._episodes}"
        journal = Journal(
            episode_id=episode_id,
            clock=self.clock,
            subscribers=(TerminalRenderer(),) if render else (),
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
                perception=LivePerception(self.readings, self._microphone()),
                stop=stop,
                memory=self.memory,
            )
        finally:
            self._running = None
        return outcome, journal

"""Everything that talks to the physical robot.

Four subsystems, four seams:

``robot_commands``  Misty's REST command surface (the official SDK, kept as-is).
``av_stream``       RTSP video in, timestamped frames out.
``audio_stream``    RTSP audio in, transcribed utterances out.
``events``          Misty's ``/pubsub`` websocket, for sensor callbacks.

Nothing above this package may reach past these interfaces. In particular no
caller starts threads, opens sockets, or touches a queue directly — that was
the shape of the code this package replaces (see PLAN.md §2).

None of it has ever run against a real Misty II. The contract tests in
``tests/test_drivers_contract.py`` prove the request FORMAT matches
docs.mistyrobotics.com; they cannot prove the robot obeys.
"""

from misty_agent.drivers.audio_stream import AudioStream, Utterance
from misty_agent.drivers.av_stream import (
    AvSession,
    CapturedFrame,
    FrameBuffer,
    RtspVideoStream,
    VideoSource,
)
from misty_agent.drivers.events import EventStream, Subscription, event_condition
from misty_agent.drivers.robot_commands import RobotCommands

__all__ = [
    "AudioStream",
    "AvSession",
    "CapturedFrame",
    "EventStream",
    "FrameBuffer",
    "RobotCommands",
    "RtspVideoStream",
    "Subscription",
    "Utterance",
    "VideoSource",
    "event_condition",
]

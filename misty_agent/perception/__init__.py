"""Turning raw sensor streams into things the agent can reason about.

``asr``   audio in, transcribed text out.
``face``  one image in, presence / distance / gaze out.

Import from the module, not from here — ``from misty_agent.perception.face
import FaceDetector``, as every caller of ``asr`` already does. Unlike
``drivers``, this package is not a single subsystem behind one façade; its two
modules share no callers, and a re-export list would be one more place to
update for no one's benefit.
"""

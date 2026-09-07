"""``python -m misty_agent`` — the first way to actually run any of this.

M7 delivered a whole ReAct agent and no way to start it: `Session` takes
collaborators that were already built, and nothing built them. Every Episode
that had ever run was assembled inside a test.

## The seam

`main(argv)`, the shape `harness/__main__.py` already uses — argv in, exit
code out. Two collaborators are injectable and both earn it:

* `model=` because the live suite is the only thing allowed to spend money
  (AGENTS.md), so every test here scripts the decisions instead;
* `clock=` because `approach` really sleeps through each drive, and because a
  `FakeClock` is the only way to tell whether the world and the Session are
  sharing one (`PLAN.md` §15.34).

Everything else is asserted through what the *model* was handed, which is the
same seam `tests/test_react.py` uses: an entry point that assembled the wrong
world shows up as a wrong Observation, not as a wrong object graph.
"""

from __future__ import annotations

import pathlib

import pytest

from misty_agent.__main__ import main
from misty_agent.fakes import FakeClock

from conftest import FIXTURES
from test_app import Says


def snapshots_the_model_read(model):
    """Every Snapshot that came back to the model, oldest first."""
    return [
        entry["content"]["snapshot"]
        for context in model.contexts
        for entry in context
        if entry.get("role") == "tool" and "snapshot" in entry.get("content", {})
    ]


# ---------------------------------------------------------------------------
# One command, one Episode
# ---------------------------------------------------------------------------

def test_one_command_runs_one_episode(capsys):
    model = Says("speak", "done")

    code = main(["--said", "hello"], model=model, clock=FakeClock())

    assert code == 0
    printed = capsys.readouterr().out
    assert "episode" in printed.lower()


def test_the_trigger_and_what_was_said_are_what_the_model_is_asked_about():
    model = Says()

    main(
        ["--trigger", "visual", "--said", "are you there"],
        model=model,
        clock=FakeClock(),
    )

    asked = [e for e in model.contexts[0] if e["role"] == "user"]
    assert asked == [
        {"role": "user", "content": {"trigger": "visual", "said": "are you there"}}
    ]


def test_the_default_trigger_is_speech():
    model = Says()

    main(["--said", "hello"], model=model, clock=FakeClock())

    asked = [e for e in model.contexts[0] if e["role"] == "user"]
    assert asked[0]["content"]["trigger"] == "speech"


def test_an_unknown_trigger_is_refused_rather_than_recorded():
    """`CONTEXT.md` gives an Episode one external trigger, and the goldens
    only ever carry these two. A typo should not become a new kind."""
    with pytest.raises(SystemExit):
        main(["--trigger", "telepathy"], model=Says(), clock=FakeClock())


# ---------------------------------------------------------------------------
# The world answers
# ---------------------------------------------------------------------------

def test_the_robot_gets_closer_to_someone_it_approaches():
    """The simulated world is a *world*, not a constant.

    A readings source that returned the same distance forever would let
    `approach` run to its deadline and report a failure, and every other test
    in this file would still pass — the Episode would run, the Journal would
    fill, the exit code would be 0. This is the one that notices.
    """
    model = Says("approach", "done")

    code = main(["--said", "come here"], model=model, clock=FakeClock())

    assert code == 0
    seen = snapshots_the_model_read(model)
    assert seen[0]["distance_cm"] < 150


def test_the_world_and_the_session_share_one_clock():
    """`PLAN.md` §15.34: one clock, or the parts disagree about *now*.

    A world stamping its readings from a second clock leaves them permanently
    outside the freshness window `approach` checks against the Session's, so
    the drive never starts and `approach` reports that it lost the person
    instead of arriving.
    """
    model = Says("approach", "done")

    main(["--said", "come here"], model=model, clock=FakeClock())

    result = [
        entry["content"]["result"]
        for context in model.contexts
        for entry in context
        if entry.get("role") == "tool" and "result" in entry.get("content", {})
    ]
    assert result[0]["result"] == "arrived"


# ---------------------------------------------------------------------------
# The image is the only real thing in the room
# ---------------------------------------------------------------------------

def test_a_photograph_decides_where_the_person_is():
    """Real mediapipe, real distance estimation, fake robot.

    The default world starts someone at `DEFAULT_START_CM`; a portrait has to
    move that, or the image was decoded and thrown away.
    """
    model = Says("speak", "done")

    code = main(
        ["--said", "hello", "--image", str(FIXTURES / "frontal_face_portrait.jpg")],
        model=model,
        clock=FakeClock(),
    )

    assert code == 0
    seen = snapshots_the_model_read(model)
    assert seen[0]["face_present"] is True
    assert seen[0]["distance_cm"] != 150


def test_a_photograph_of_nobody_is_a_room_with_nobody_in_it(tmp_path):
    """`face_present` false and no distance — the Snapshot `LivePerception`
    builds when `latest_reading()` has nothing to offer. The model is told
    the truth about an empty room rather than a default one."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    blank = tmp_path / "empty-room.png"
    cv2.imwrite(str(blank), np.zeros((240, 320, 3), dtype=np.uint8))
    model = Says("speak", "done")

    code = main(
        ["--said", "hello", "--image", str(blank)], model=model, clock=FakeClock()
    )

    assert code == 0
    seen = snapshots_the_model_read(model)
    assert seen[0]["face_present"] is False
    assert seen[0]["distance_cm"] is None


def test_an_image_that_cannot_be_read_says_so_instead_of_raising(capsys):
    model = Says()

    code = main(
        ["--image", "/definitely/not/here.jpg"], model=model, clock=FakeClock()
    )

    assert code == 1
    assert "/definitely/not/here.jpg" in capsys.readouterr().err
    assert model.asked == 0


# ---------------------------------------------------------------------------
# No key
# ---------------------------------------------------------------------------

def test_without_a_key_perception_still_runs_and_says_how_to_give_one(
    capsys, monkeypatch, tmp_path
):
    """The ticket's own criterion. Someone who has cloned this and run it
    should learn what the camera made of their photograph *and* what to do
    next — not a stack trace from inside an SDK.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.__main__.API_KEY_FILE", str(tmp_path / "none"))

    code = main(["--said", "hello"], clock=FakeClock())

    assert code == 1
    printed = capsys.readouterr()
    assert "150" in printed.out  # perception reported what it saw
    assert "OPENAI_API_KEY" in printed.err


def test_without_a_key_nothing_is_asked_of_a_model(monkeypatch, tmp_path):
    """Reporting the perception result must not mean starting an Episode and
    failing halfway through one: a halted robot is a worse answer than a
    refusal to start."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.__main__.API_KEY_FILE", str(tmp_path / "none"))
    would_have_been_asked = Says()
    monkeypatch.setattr(
        "misty_agent.__main__.OpenAIModel", lambda *a, **k: would_have_been_asked
    )

    main(["--said", "hello"], clock=FakeClock())

    assert would_have_been_asked.asked == 0


# ---------------------------------------------------------------------------
# What a person sees
# ---------------------------------------------------------------------------

def test_the_whole_episode_is_printed_in_time_order(capsys):
    """`TerminalRenderer` stamps every line with the record's `t`. The
    Episode is watched as it happens, so "at the end" and "in order" are the
    same statement — but only if nothing prints out of turn."""
    model = Says("speak", "approach", "done")

    main(["--said", "come here"], model=model, clock=FakeClock())

    stamped = []
    for line in capsys.readouterr().out.splitlines():
        try:
            stamped.append(float(line.partition("s")[0]))
        except ValueError:
            continue  # the perception line and the summary carry no stamp
    assert len(stamped) > 5
    assert stamped == sorted(stamped)

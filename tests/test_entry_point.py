"""``python -m misty_agent`` — the first way to actually run any of this.

M7 delivered a whole ReAct agent and no way to start it: `Session` takes
collaborators that were already built, and nothing built them. Every Episode
that had ever run was assembled inside a test.

## The seam

`main(argv)`, the shape `harness/__main__.py` already uses — argv in, exit
code out. It lives in `app.py`, which is where the pieces are wired together;
`misty_agent/__main__.py` only forwards to it. Two collaborators are injectable and both earn it:

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

import os
import pathlib
import subprocess
import sys

import pytest

from misty_agent.agent.journal import from_jsonl, to_jsonl
from misty_agent.agent.model import API_KEY_VARIABLE
from misty_agent.app import DEFAULT_START_CM, main
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock

from conftest import FIXTURES, SKIP_REASON
from test_app import Says

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def what_the_camera_makes_of(path):
    """The distance the real pipeline estimates, computed the same way the
    entry point computes it. Asserting against this rather than against `52`
    keeps the tests honest without pinning a number MediaPipe owns.
    """
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    from misty_agent.perception.face import FaceDetector

    with FaceDetector() as detector:
        return detector.detect(cv2.imread(str(path))).distance_cm


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
    portrait = FIXTURES / "frontal_face_portrait.jpg"

    code = main(
        ["--said", "hello", "--image", str(portrait)],
        model=model,
        clock=FakeClock(),
    )

    assert code == 0
    seen = snapshots_the_model_read(model)
    assert seen[0]["face_present"] is True
    assert seen[0]["distance_cm"] == what_the_camera_makes_of(portrait)


def test_a_photograph_of_nobody_is_a_room_with_nobody_in_it(tmp_path):
    """`face_present` false and no distance — the Snapshot `LivePerception`
    builds when `latest_reading()` has nothing to offer. The model is told
    the truth about an empty room rather than a default one."""
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    np = pytest.importorskip("numpy", reason=SKIP_REASON)

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


def test_the_photograph_puts_the_person_in_the_world_the_robot_drives_in(tmp_path):
    """Robot and readings on the image path have to be the *same* object.

    Split them — a plain `RecordingCommands` as the robot, the world as the
    readings — and each drive lands on a recorder while the observed distance
    never moves. `approach` runs to its deadline and reports a lost person,
    and the exit code is still 0. A review's mutant did exactly this and only
    the no-image path noticed.

    The portrait is scaled down first: at full size the face reads as 52cm,
    already inside `target_distance_cm` ± its tolerance, so `approach` would
    arrive without driving and prove nothing.
    """
    cv2 = pytest.importorskip("cv2", reason=SKIP_REASON)
    portrait = cv2.imread(str(FIXTURES / "frontal_face_portrait.jpg"))
    further = tmp_path / "further-away.png"
    cv2.imwrite(
        str(further),
        cv2.resize(portrait, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA),
    )
    config = Settings()
    started_at = what_the_camera_makes_of(further)
    assert started_at > config.target_distance_cm + config.distance_tolerance_cm

    model = Says("approach", "done")
    main(["--image", str(further)], model=model, clock=FakeClock())

    assert snapshots_the_model_read(model)[0]["distance_cm"] < started_at


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
    monkeypatch.setattr("misty_agent.app.API_KEY_FILE", str(tmp_path / "none"))

    code = main(["--said", "hello"], clock=FakeClock())

    assert code == 1
    printed = capsys.readouterr()
    assert f"{DEFAULT_START_CM}cm" in printed.out  # it reported what it saw
    assert "OPENAI_API_KEY" in printed.err


def test_what_gets_reported_is_what_the_camera_saw(capsys, monkeypatch, tmp_path):
    """The reported line, tied to the pipeline that produced it.

    The test above asserts `DEFAULT_START_CM` appears — and that is a constant
    this module owns, so a review replaced the whole `print` with the literal
    string `"perception: someone 150cm away"` and all 1100 tests stayed green.
    A photograph produces a number no constant here can supply, which is the
    only way to tell a report from a recital.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.app.API_KEY_FILE", str(tmp_path / "none"))
    portrait = FIXTURES / "frontal_face_portrait.jpg"

    code = main(["--image", str(portrait)], clock=FakeClock())

    assert code == 1
    reported = capsys.readouterr().out
    assert f"{what_the_camera_makes_of(portrait)}cm away" in reported
    assert str(portrait) in reported


def test_the_reported_line_says_where_its_number_came_from(capsys, monkeypatch, tmp_path):
    """`PLAN.md` §16.13 refuses to let the entry point invent a person the
    camera did not find. Labelling `DEFAULT_START_CM` as perception is the
    same invention with a different face, so the default says so."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.app.API_KEY_FILE", str(tmp_path / "none"))

    main([], clock=FakeClock())

    assert capsys.readouterr().out.startswith("simulated:")


def test_without_a_key_nothing_is_asked_of_a_model(monkeypatch, tmp_path):
    """Reporting the perception result must not mean starting an Episode and
    failing halfway through one: a halted robot is a worse answer than a
    refusal to start."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("misty_agent.app.API_KEY_FILE", str(tmp_path / "none"))
    would_have_been_asked = Says()
    monkeypatch.setattr(
        "misty_agent.app.OpenAIModel", lambda *a, **k: would_have_been_asked
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


# ---------------------------------------------------------------------------
# Keeping the evidence
# ---------------------------------------------------------------------------

def test_a_journal_is_written_only_when_one_is_asked_for(tmp_path, monkeypatch):
    """The negative control, and the decision it protects.

    A Journal carries what people said — `speak`'s text, and `new_speech` in
    every Snapshot. Writing that to disk by default would be this project's
    first unrecorded decision about keeping people's words (`PLAN.md`
    §16.22), so the default is that nothing is created at all.

    Asserted on the writer, not on a directory. The first version watched an
    empty `tmp_path` and passed against a mutant that wrote to an absolute
    path somewhere else entirely — it proved that an unrelated directory
    stayed empty. Nothing being *constructed* is the claim.
    """
    built = []
    monkeypatch.setattr(
        "misty_agent.app.JsonlFile", lambda path: built.append(path)
    )
    monkeypatch.chdir(tmp_path)

    main(["--said", "hello"], model=Says("speak", "done"), clock=FakeClock())

    assert built == []
    assert list(tmp_path.iterdir()) == []


def test_the_journal_that_is_asked_for_is_the_one_that_happened(tmp_path):
    """Not "a file appeared" — the records in it are the Episode's own."""
    kept = tmp_path / "run.jsonl"
    model = Says("speak", "approach", "done")

    code = main(
        ["--said", "come here", "--journal", str(kept)],
        model=model,
        clock=FakeClock(),
    )

    assert code == 0
    written = from_jsonl(kept.read_text())
    assert [record.type for record in written][:2] == [
        "episode_started",
        "turn_started",
    ]
    assert written[-1].type == "episode_finished"
    assert written[-1].outcome == "done"


def test_what_is_written_is_what_the_golden_tools_already_read(tmp_path):
    """`tests/goldens/` is one Episode per file, and `from_jsonl` returns a
    flat sequence — it does not group. So the file has to round-trip through
    the same two functions the goldens are compared with, byte for byte.
    """
    kept = tmp_path / "run.jsonl"

    main(["--said", "hi", "--journal", str(kept)],
         model=Says("speak", "done"), clock=FakeClock())

    text = kept.read_text()
    assert to_jsonl(from_jsonl(text)) == text
    assert text.endswith("\n")
    assert len([line for line in text.splitlines() if line.strip()]) == len(
        from_jsonl(text)
    )


def test_an_interrupted_episode_still_leaves_what_it_got_through(tmp_path):
    """`JsonlFile` appends line by line, and this is the reason it does.

    A `KeyboardInterrupt` is a `BaseException`, so neither the ReAct loop nor
    the Journal's fan-out catches it — the Episode dies where it stands. What
    was already written is still on disk, which a file assembled at the end
    could not manage.
    """
    kept = tmp_path / "half.jsonl"

    class StopsDead:
        """Reads the file on its way past, then dies where it stands."""

        seen_mid_episode = None

        def decide(self, working_context, tools):
            StopsDead.seen_mid_episode = kept.read_text()
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        main(["--said", "hi", "--journal", str(kept)],
             model=StopsDead(), clock=FakeClock())

    # Read from *inside* the Episode. Asserting only on the file afterwards
    # cannot tell appending from a `finally` that dumps everything at the end
    # — both leave the same bytes behind, and a mutant doing the latter passed
    # this test. Only a file that already exists mid-run distinguishes them,
    # and only that survives a process that is killed rather than unwound.
    during = from_jsonl(StopsDead.seen_mid_episode)
    assert [record.type for record in during] == [
        "episode_started",
        "turn_started",
    ]
    assert from_jsonl(kept.read_text()) == during


@pytest.mark.parametrize(
    "already_there",
    ['{"type": "episode_started"}\n', ""],
    ids=["a real journal", "an empty file"],
)
def test_a_journal_will_not_be_written_on_top_of_another_one(
    tmp_path, capsys, already_there
):
    """One file, one Episode — that is what `from_jsonl` assumes and what
    every golden is. Appending a second Episode makes a file the reading
    tools parse into one flat run with two beginnings, and destroys the
    evidence of the first by making it unreadable.

    **The empty case is not padding.** The first version of this test wrote
    an empty file and then overwrote it with a record, so only one of the two
    was ever exercised — and a check of "exists *and* has bytes in it" passed
    the whole suite. An empty file at that path is somebody's run that has
    only just started, or a file they made on purpose; either way it is not
    ours to write into.
    """
    kept = tmp_path / "run.jsonl"
    kept.write_text(already_there)

    with pytest.raises(SystemExit):
        main(["--said", "hi", "--journal", str(kept)],
             model=Says(), clock=FakeClock())

    assert "already exists" in capsys.readouterr().err
    assert kept.read_text() == already_there


def test_what_was_said_out_loud_is_in_the_file(tmp_path):
    """The premise the whole default-off decision rests on.

    `PLAN.md` §16.22 justifies the flag by what a Journal carries: the words
    `speak` was given, and every Snapshot's `new_speech`. Nothing was reading
    a character of it — the round-trip test passes on a file with every word
    blanked, because a blank string round-trips too.
    """
    kept = tmp_path / "run.jsonl"

    main(["--said", "hi", "--journal", str(kept)],
         model=Says("speak", "done"), clock=FakeClock())

    said_out_loud = [
        record.args["text"]
        for record in from_jsonl(kept.read_text())
        if record.type == "tool_called" and record.tool == "speak"
    ]
    assert said_out_loud == ["hello"]  # what `Says` scripts for `speak`


def test_a_journal_that_cannot_be_written_is_refused_before_anything_moves(
    tmp_path, capsys
):
    """It used to run the whole Episode and exit 0.

    `Journal` catches what a subscriber raises and records it, which is right
    for a renderer and wrong for the evidence: a missing directory printed a
    failure line per record, produced no file, moved the robot, and reported
    success. Both review axes found it independently (`PLAN.md` §16.24).
    """
    model = Says("speak", "done")

    with pytest.raises(SystemExit):
        main(
            ["--said", "hi",
             "--journal", str(tmp_path / "no-such-dir" / "x.jsonl")],
            model=model,
            clock=FakeClock(),
        )

    assert "is not a directory" in capsys.readouterr().err
    assert model.asked == 0


def test_losing_the_journal_part_way_through_is_not_a_clean_exit(
    tmp_path, capsys, monkeypatch
):
    """The general case of the same thing.

    A path can stop being writable after it was checked — the disk fills, the
    directory goes away. The `SubscriberFailed` records are already in the
    Journal; the exit code has to agree with them, or the one thing the
    person asked to keep is gone and nothing said so.
    """
    def falls_over(self, record):
        raise OSError("no space left on device")

    monkeypatch.setattr(
        "misty_agent.agent.journal.JsonlFile.receive", falls_over
    )

    code = main(
        ["--said", "hi", "--journal", str(tmp_path / "run.jsonl")],
        model=Says("speak", "done"),
        clock=FakeClock(),
    )

    assert code == 1
    assert "no space left on device" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# It is a command, not just a function
# ---------------------------------------------------------------------------

def test_a_command_that_needs_no_key_does_not_go_looking_for_one(monkeypatch):
    """`load_api_key` does not just read — it *exports* what it finds.

    A run that was handed a model and told to simulate needs no key, and has
    no business writing to the process environment on its way past. It was
    called unconditionally for one commit, which is how a test suite starts
    depending on whose machine it is running on.
    """
    looked_in = []
    monkeypatch.setattr(
        "misty_agent.app.load_api_key", lambda path: looked_in.append(path)
    )

    main(["--said", "hi"], model=Says(), clock=FakeClock())

    assert looked_in == []


def test_the_demo_flag_serves_instead_of_running_an_episode(monkeypatch):
    """`--demo` replays Episodes that already finished. Running a live one
    underneath it would move a robot nobody is watching."""
    served = []
    monkeypatch.setattr("misty_agent.demo.serve", lambda **how: served.append(True))
    model = Says()

    code = main(["--demo"], model=model, clock=FakeClock())

    assert code == 0
    assert served == [True]
    assert model.asked == 0


@pytest.mark.parametrize(
    "alongside",
    [["--said", "hello"], ["--image", "x.jpg"], ["--robot", "10.0.0.7"],
     ["--journal", "out.jsonl"]],
)
def test_the_demo_refuses_the_flags_it_would_have_ignored(
    monkeypatch, capsys, alongside
):
    """Silently ignoring them is how somebody believes their photograph, or
    their key, was used. The same call `--image` with `--robot` gets."""
    served = []
    monkeypatch.setattr("misty_agent.demo.serve", lambda **how: served.append(True))

    with pytest.raises(SystemExit):
        main(["--demo", *alongside], model=Says(), clock=FakeClock())

    assert served == []
    assert "--demo runs Episodes the page asks for" in capsys.readouterr().err


def test_audio_is_a_demo_option_and_says_so(capsys):
    """It only means anything as an upload, and a flag that quietly does
    nothing is worse than one that says it does nothing."""
    with pytest.raises(SystemExit):
        main(["--audio", "--said", "hi"], model=Says(), clock=FakeClock())

    assert "--audio is a --demo option" in capsys.readouterr().err


def test_asking_for_audio_reaches_the_demo(monkeypatch):
    """`--demo --audio` has to arrive, or the switch is decoration."""
    asked = []
    monkeypatch.setattr("misty_agent.demo.serve", lambda **how: asked.append(how))

    main(["--demo", "--audio"], model=Says(), clock=FakeClock())

    assert asked == [{"audio": True}]


def test_the_module_really_runs_as_a_command(tmp_path):
    """Everything above calls `main` in-process.

    So a `__main__.py` that imported the wrong name, or forwarded to nothing,
    would leave the whole suite green and `python -m misty_agent` dead — and
    that command is the entire deliverable of M8 #04.

    It also pins the order of the two streams. stdout is block-buffered
    whenever it is a pipe, so without the explicit flush the guidance on
    stderr overtakes the report it is answering, and a person piping this into
    a file reads the two backwards.
    """
    # Run from an empty directory, with the package found on the path
    # instead: `load_api_key` resolves `OAI_CONFIG_LIST.json` relative to the
    # working directory, so a developer who has a real one would otherwise
    # get a real Episode — and a paid model call — out of this test.
    ran = subprocess.run(
        [sys.executable, "-m", "misty_agent", "--said", "hello"],
        cwd=tmp_path,
        env={
            **os.environ,
            API_KEY_VARIABLE: "",
            "PYTHONPATH": str(REPO_ROOT),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
    )

    assert ran.returncode == 1, ran.stdout
    assert ran.stdout.index("simulated:") < ran.stdout.index(API_KEY_VARIABLE)

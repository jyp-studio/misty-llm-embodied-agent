"""What a screen is told about an Episode — decided here, where pytest reaches.

This is M8's testing strategy in one file. The alternative — hand a page the
raw JSONL and let JavaScript work out what each line means — puts every
decision about *what is shown* somewhere no test in this repo can see. This
project has already paid for exactly that: `TerminalRenderer` printed
`-> , 52cm away` for every Tool except `approach`, and nothing went red,
because the tests asserted on the Journal and not on what was shown
(`PLAN.md` §16.7).

So the page gets a `Storyboard`: records in, a serialisable structure out,
and JavaScript only draws it.

## What the tests here have to be careful about

**Not asserting the same thing as `tests/test_journal_writing.py`.** How one
record reads is `describe`'s, decided in #02, and this reuses it rather than
writing a second answer (`PLAN.md` §15.4). What is new here is everything
`describe` deliberately refuses to carry: the fields behind the sentence, and
the robot's state as it changes.

**The negative control matters more than usual.** An implementation that
collapsed every record into one shape — same headline, same tone, no facts —
would still produce a structure, still serialise, and still let a page draw
something. `test_a_storyboard_that_says_the_same_thing_about_everything_is_
caught` is the one that would notice.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from misty_agent.agent.journal import (
    JOURNAL_SCHEMA,
    OUTCOMES,
    DecisionNoted,
    EpisodeFinished,
    EpisodeStarted,
    ExecutionFailed,
    Journal,
    ModelCalled,
    Observation,
    RECORD_TYPES,
    Snapshot,
    StopRequested,
    SubscriberFailed,
    ToolCalled,
    ToolRejected,
    TurnStarted,
)
from misty_agent.agent.tools import build_registry
from misty_agent.agent.storyboard import (
    ENDINGS,
    MOVES,
    RobotState,
    storyboard_of,
)
from misty_agent.fakes import FakeClock

WALL_CLOCK = "2026-09-07T12:00:00+08:00"


def a_journal():
    return Journal("ep-1", clock=FakeClock(), wall_clock=lambda: WALL_CLOCK)


def a_snapshot(distance_cm=120, face_present=True, new_speech=None):
    return Snapshot(
        distance_cm=distance_cm, face_present=face_present, new_speech=new_speech
    )


def one_of_every_kind():
    """A Journal carrying one record of every kind there is.

    Built through the real `Journal`, not by hand, so a kind that cannot
    actually be recorded cannot be smuggled into these assertions.
    """
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(TurnStarted, turn=1)
    journal.record(ModelCalled, turn=1, latency_ms=412, tokens_in=930, tokens_out=17)
    journal.record(
        DecisionNoted,
        turn=1,
        tool_call_id="call-one",
        note="Acknowledge the greeting.",
    )
    journal.record(ToolCalled, turn=1, tool="change_led", args={"red": 255, "green": 0, "blue": 0})
    journal.record(Observation, turn=1, result={"ok": True}, snapshot=a_snapshot())
    journal.record(ToolRejected, turn=2, tool="move_head", reason="pitch=90 is above the maximum 26")
    journal.record(StopRequested, source="foot_bumper")
    journal.record(ExecutionFailed, phase="model", error_type="TimeoutError", message="took too long")
    journal.record(SubscriberFailed, subscriber="JsonlFile", failed_on="observation", error="disk full")
    journal.record(EpisodeFinished, outcome="aborted", turns=2, steps=3)
    return journal


# ---------------------------------------------------------------------------
# A pure function, and something a page can be handed
# ---------------------------------------------------------------------------

def test_a_storyboard_survives_being_turned_into_json():
    """"Serialisable" is the whole contract with the page — a structure that
    only survives inside this process is one the browser never sees."""
    board = storyboard_of(one_of_every_kind().records)

    text = json.dumps(asdict(board))

    assert json.loads(text)["episode_id"] == "ep-1"


def test_a_storyboard_carries_no_markup_and_no_layout():
    """The ticket's first line: records in, structure out, JavaScript draws.
    A `<span>` here would be this module quietly becoming the renderer."""
    text = json.dumps(asdict(storyboard_of(one_of_every_kind().records)))

    for forbidden in ("<", "style=", "px", "#ff"):
        assert forbidden not in text, forbidden


def test_reading_the_same_journal_twice_gives_the_same_storyboard():
    """Pure: no clock, no io, no accumulated state between calls."""
    records = one_of_every_kind().records

    assert storyboard_of(records) == storyboard_of(records)


# ---------------------------------------------------------------------------
# Every kind of record, and the proof that forgetting one is loud
# ---------------------------------------------------------------------------

def test_the_storyboard_says_how_the_episode_began_and_ended():
    """Four of its seven fields were asserted by nothing at all — hard-code
    them to null and every test stayed green. They are the ones a page reads
    first, before it draws a single Moment."""
    board = storyboard_of(one_of_every_kind().records)

    assert board.episode_id == "ep-1"
    assert board.trigger == "speech"
    assert board.started_at == WALL_CLOCK
    assert board.outcome == "aborted"
    assert board.turns == 2
    assert board.steps == 3


def test_nothing_lifted_onto_the_storyboard_is_repeated_in_a_moment():
    """`PLAN.md` §15.4 across the whole payload, not just within one object.

    `trigger`, `started_at_wall_clock`, `outcome`, `turns` and `steps` were
    all shipped twice for one commit — once at the top and once inside a
    Moment's `facts` — five values free to disagree with themselves.
    """
    by_kind = {m.kind: m.facts for m in storyboard_of(one_of_every_kind().records).moments}

    assert by_kind["episode_started"] == {"schema": JOURNAL_SCHEMA}
    assert by_kind["episode_finished"] == {}


def test_a_field_a_record_gains_arrives_without_anybody_wiring_it():
    """§16.27's central claim, which had no test.

    `facts` is taken off the record mechanically, so the three criteria about
    contents need no code of their own. That only holds while the exclusion
    list stays what it says it is — adding a name to it silently drops that
    field from every page.
    """
    by_kind = {m.kind: m.facts for m in storyboard_of(one_of_every_kind().records).moments}

    assert by_kind["model_called"] == {
        "latency_ms": 412, "tokens_in": 930, "tokens_out": 17,
    }
    assert by_kind["observation"]["snapshot"] == {
        "distance_cm": 120, "face_present": True, "new_speech": None,
    }
    assert by_kind["execution_failed"] == {
        "phase": "model", "error_type": "TimeoutError", "message": "took too long",
    }


def test_a_journal_with_nothing_in_it_is_an_empty_storyboard():
    """A page may ask before the first record has been written."""
    board = storyboard_of([])

    assert board.moments == ()
    assert board.episode_id == ""
    assert board.trigger is None
    assert board.outcome is None


def test_every_record_kind_becomes_a_moment():
    board = storyboard_of(one_of_every_kind().records)

    assert [moment.kind for moment in board.moments] == [
        "episode_started",
        "turn_started",
        "model_called",
        "decision_noted",
        "tool_called",
        "observation",
        "tool_rejected",
        "stop_requested",
        "execution_failed",
        "subscriber_failed",
        "episode_finished",
    ]


def test_a_record_kind_nobody_taught_it_reads_as_a_failure():
    """The exhaustiveness guarantee, and it is `describe`'s (#02) rather than
    a second one written here. A new record kind that nothing renders comes
    out saying so, in the tone reserved for the system not working — loud, so
    that adding a kind and forgetting the page is a red test rather than a
    blank line in a browser.
    """
    board = storyboard_of(one_of_every_kind().records)

    assert [m for m in board.moments if "unrendered" in m.headline] == []
    assert {m.kind for m in board.moments} == set(RECORD_TYPES)


def test_a_storyboard_that_says_the_same_thing_about_everything_is_caught():
    """The negative control the ticket asks for.

    An implementation that gave every record one headline, one tone and no
    facts would still build, still serialise, and still let a page draw
    something — it would just be useless. Three separate things have to vary.
    """
    moments = storyboard_of(one_of_every_kind().records).moments

    # All three parts of what `describe` returns. `detail` was outside this
    # for one commit, and blanking it on every Moment passed the whole suite
    # — while deleting every Snapshot phrase, every refusal reason and every
    # token count from the page.
    said = {(m.headline, m.detail, m.tone) for m in moments}
    assert len(said) == len(moments)
    assert len({m.tone for m in moments}) >= 4
    assert len([m for m in moments if m.detail]) >= 5


def test_the_sentence_behind_each_headline_is_carried_too():
    """`detail` is the half of `describe` that says *what*: how far away, why
    it was refused, what the call cost. Naming three of them here means a
    blanked `detail` is a red test rather than an empty page."""
    detail = {m.kind: m.detail for m in storyboard_of(one_of_every_kind().records).moments}

    assert detail["observation"] == "120cm away"
    assert detail["model_called"] == "930+17 tokens"
    assert detail["tool_rejected"] == "pitch=90 is above the maximum 26"


# ---------------------------------------------------------------------------
# What the sentence leaves out
# ---------------------------------------------------------------------------

def test_nothing_the_moment_already_says_is_repeated_in_its_facts():
    """`PLAN.md` §15.4 applies inside one object too. `t`, the Episode id, the
    kind and the Turn are all on the `Moment`; a second copy in `facts` is a
    second thing that can disagree with the first."""
    for moment in storyboard_of(one_of_every_kind().records).moments:
        for already_said in ("t", "episode_id", "type", "turn"):
            assert already_said not in moment.facts, (moment.kind, already_said)


def test_a_refusal_carries_the_reason_it_was_refused():
    """`PLAN.md` §14.6: being able to watch the agent get it wrong *and* see
    the system stop it is half the point of validating arguments at all."""
    (refusal,) = [
        m for m in storyboard_of(one_of_every_kind().records).moments
        if m.kind == "tool_rejected"
    ]

    assert refusal.facts["tool"] == "move_head"
    assert "above the maximum 26" in refusal.facts["reason"]
    assert refusal.tone == "refused"


def test_what_a_model_call_cost_is_in_the_structure():
    (thought,) = [
        m for m in storyboard_of(one_of_every_kind().records).moments
        if m.kind == "model_called"
    ]

    assert thought.facts["latency_ms"] == 412
    assert thought.facts["tokens_in"] == 930
    assert thought.facts["tokens_out"] == 17


@pytest.mark.parametrize("outcome", ["done", "turn_limit", "aborted", "error"])
def test_the_four_ways_an_episode_can_end_are_told_apart(outcome):
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(EpisodeFinished, outcome=outcome, turns=1, steps=0)

    board = storyboard_of(journal.records)

    assert board.outcome == outcome
    # Told apart in the headline too, because a page that groups by outcome
    # and a page that reads the closing line must not be able to disagree.
    assert outcome in board.moments[-1].headline


def test_each_ending_is_also_said_in_words_a_visitor_has_met():
    """`describe` gives the Journal's own sentence — "episode turn_limit
    after 8 turn(s)" — which is right for a terminal and reads as a raw enum
    on a page. Every outcome has one, or a page shows a blank where the
    answer to "how did it end" should be.
    """
    for outcome in OUTCOMES:
        journal = a_journal()
        journal.record(EpisodeStarted, trigger="speech")
        journal.record(EpisodeFinished, outcome=outcome, turns=1, steps=0)

        board = storyboard_of(journal.records)

        assert board.ending == ENDINGS[outcome]
        assert outcome not in board.ending  # said, not spelled


def test_an_episode_still_running_has_no_outcome_yet():
    """A Journal read while it is being written — which is what a page
    watching a live run holds."""
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(TurnStarted, turn=1)

    assert storyboard_of(journal.records).outcome is None


# ---------------------------------------------------------------------------
# The robot, as it changes
# ---------------------------------------------------------------------------

def test_the_robot_starts_in_a_known_pose():
    """Written out rather than compared to `RobotState()`, which is the same
    sentence twice and true however the defaults are changed."""
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")

    pose = storyboard_of(journal.records).moments[0].robot

    assert pose.expression == "neutral"
    assert pose.led == (0, 0, 0)
    assert pose.head == (0.0, 0.0, 0.0)
    assert pose.arms == (90.0, 90.0)


def test_the_light_stays_the_colour_it_was_set_to():
    """Every Moment carries the whole robot, not a change — a page drawing
    the state at record 7 should not have to replay records 0 to 6."""
    board = storyboard_of(one_of_every_kind().records)
    by_kind = {m.kind: m.robot for m in board.moments}

    # Asked for at `tool_called`, true from the Observation onwards.
    assert by_kind["tool_called"].led == (0, 0, 0)
    assert by_kind["observation"].led == (255, 0, 0)
    assert board.moments[-1].robot.led == (255, 0, 0)


def test_the_head_and_the_arms_move_when_they_are_told_to():
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(TurnStarted, turn=1)
    journal.record(ToolCalled, turn=1, tool="move_head", args={"pitch": -20.0, "roll": 0.0, "yaw": 45.0})
    journal.record(Observation, turn=1, result={"ok": True}, snapshot=a_snapshot())
    journal.record(ToolCalled, turn=2, tool="move_arms", args={"left": -29.0, "right": 0.0})
    journal.record(Observation, turn=2, result={"ok": True}, snapshot=a_snapshot())

    poses = [m.robot for m in storyboard_of(journal.records).moments]

    assert poses[2].head == (0.0, 0.0, 0.0)  # asked for, not yet confirmed
    assert poses[3].head == (-20.0, 0.0, 45.0)
    assert poses[-1].head == (-20.0, 0.0, 45.0)
    assert poses[-1].arms == (-29.0, 0.0)


def test_the_face_changes_when_the_screen_does():
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolCalled, turn=1, tool="display_image", args={"expression": "happy"})
    journal.record(Observation, turn=1, result={"ok": True}, snapshot=a_snapshot())

    assert storyboard_of(journal.records).moments[-1].robot.expression == "happy"


def test_a_call_whose_handler_blew_up_moves_nothing():
    """The other half of "a pose is asked for and then confirmed".

    `dispatch` records `ToolCalled` and *then* runs the handler, so a handler
    that raises leaves the record behind and no Observation — `react.py`
    records `ExecutionFailed` instead. A fold that read the pose off the
    request alone draws a chest light that never lit, which is `-> , 52cm
    away` in another medium.
    """
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolCalled, turn=1, tool="change_led", args={"red": 255, "green": 0, "blue": 0})
    journal.record(ExecutionFailed, phase="tool", error_type="ConnectionError", message="no route to host")
    journal.record(EpisodeFinished, outcome="error", turns=1, steps=0)

    assert [m.robot.led for m in storyboard_of(journal.records).moments] == [
        (0, 0, 0)
    ] * 4


def test_a_scan_leaves_the_head_where_it_found_someone():
    """`look_around` stops where it finds a face — it does not sweep back, so
    the Snapshot taken afterwards is about that person. The angle is in the
    result rather than the arguments, which is why the fold reads both.
    """
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolCalled, turn=1, tool="look_around", args={})
    journal.record(
        Observation, turn=1, result={"ok": True, "found_at_yaw": -60.0},
        snapshot=a_snapshot(),
    )

    assert storyboard_of(journal.records).moments[-1].robot.head == (0.0, 0.0, -60.0)


def test_a_scan_that_finds_nobody_leaves_the_head_facing_forward():
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolCalled, turn=1, tool="move_head", args={"pitch": 0.0, "roll": 0.0, "yaw": 70.0})
    journal.record(Observation, turn=1, result={"ok": True}, snapshot=a_snapshot())
    journal.record(ToolCalled, turn=2, tool="look_around", args={})
    journal.record(
        Observation, turn=2, result={"ok": True, "found_at_yaw": None},
        snapshot=a_snapshot(face_present=False, distance_cm=None),
    )

    assert storyboard_of(journal.records).moments[-1].robot.head == (0.0, 0.0, 0.0)


def test_a_refused_call_moves_nothing():
    """`dispatch` validates before it records `tool_called`, so a refusal
    never produced one — but a fold that read arguments off the refusal would
    show a robot that had turned its head to an angle it rejected.
    """
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolRejected, turn=1, tool="move_head", reason="pitch=90 is above the maximum 26")

    assert storyboard_of(journal.records).moments[-1].robot == RobotState()


def test_the_tools_that_move_the_robot_are_tools_that_exist():
    """The fold reads `tool` and `args` by name, which couples it to
    `tools.py` across a gap no type checker crosses. A Tool renamed there
    would leave the page showing a robot that never moves, silently.
    """
    named = set(build_registry().names())

    assert set(MOVES) <= named


def test_the_arguments_the_fold_reads_are_arguments_those_tools_take():
    """The other half of the same coupling, and the half that was open.

    Checking the four Tool *names* leaves every argument name unchecked:
    rename `MoveHeadArgs.pitch` and this file stays green while the head
    stops moving. `dispatch` records `model_dump()`, so these names are
    exactly the model's fields.
    """
    registry = build_registry()

    for tool_name, (_, arguments) in MOVES.items():
        takes = set(registry.get(tool_name).args_model.model_fields)
        assert set(arguments) <= takes, tool_name


def test_a_scan_squares_the_head_up_as_well_as_turning_it():
    """`look_around` issues `move_head(pitch=0, roll=0, yaw=...)`, so a scan
    undoes a tilt the model set earlier. Only the yaw was asserted."""
    journal = a_journal()
    journal.record(EpisodeStarted, trigger="speech")
    journal.record(ToolCalled, turn=1, tool="move_head", args={"pitch": -30.0, "roll": 20.0, "yaw": 0.0})
    journal.record(Observation, turn=1, result={"ok": True}, snapshot=a_snapshot())
    journal.record(ToolCalled, turn=2, tool="look_around", args={})
    journal.record(Observation, turn=2, result={"ok": True, "found_at_yaw": 30.0}, snapshot=a_snapshot())

    assert storyboard_of(journal.records).moments[-1].robot.head == (0.0, 0.0, 30.0)


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

def test_a_record_without_a_turn_belongs_to_the_turn_it_happened_in():
    """A page groups by Turn. `stop_requested` and `episode_finished` carry
    no `turn` of their own — they happen *during* one, and putting them
    outside it would draw an interruption as if it came from nowhere.

    Two is the answer, not one: the record before the stop is the refusal,
    and it is in Turn 2. Nothing before the first Turn has one at all.
    """
    board = storyboard_of(one_of_every_kind().records)
    by_kind = {m.kind: m.turn for m in board.moments}

    assert by_kind["episode_started"] is None
    assert by_kind["model_called"] == 1
    assert by_kind["tool_rejected"] == 2
    assert by_kind["stop_requested"] == 2
    assert by_kind["episode_finished"] == 2

"""The Demo's examples are a hosted model's recorded runs, and say so.

Recording costs money and needs a key, so nothing here records against a
real model: a stand-in decides, and what is checked is the shape and the
claims. The committed recordings are checked as data — they exist for every
example, they say who made them and when, and nothing Misty says in them is
something a visitor could mistake for a diagnosis, a rescue or a promise.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest

from boundary_audit import boundary_violations
from misty_agent.acceptance import card_named, fixtures_of
from misty_agent.agent.react import Decision
from misty_agent.demo import HARDWARE_UNVERIFIED, PROVENANCE, answer
from misty_agent.demo import recordings
from misty_agent.demo.recordings import SHOWCASES, NoRecording, load, record

TODAY = datetime.date(2026, 9, 22)


class Greets:
    """A stand-in for the hosted model: one line, then done."""

    def __init__(self):
        self.turns = 0

    def decide(self, working_context, tools):
        self.turns += 1
        if self.turns == 1:
            return Decision("speak", {"text": "Hello there."}, 10, 3,
                            tool_call_id="call-1", note="Say hello back.")
        return Decision("done", {}, 10, 1, tool_call_id="call-2", note="Nothing more to add.")


def test_every_example_names_a_fixture_that_exists_and_names_it_once():
    keys = [showcase.key for showcase in SHOWCASES]

    assert len(keys) == len(set(keys))
    for showcase in SHOWCASES:
        offered = {item.key for item in fixtures_of(card_named(showcase.card))}
        assert showcase.fixture in offered, showcase


def test_the_examples_are_offered_in_groups_a_visitor_can_read():
    """The tabs follow what a visitor is looking for, not which acceptance
    card a fixture happens to belong to."""
    groups = [showcase.group for showcase in SHOWCASES]

    assert set(groups) == set(recordings.GROUPS)
    # Each group's examples sit together, in the order the tabs are drawn.
    assert list(dict.fromkeys(groups)) == list(recordings.GROUPS)
    listed = recordings.listing()
    assert [item["group_title"] for item in listed] == [
        recordings.GROUPS[showcase.group] for showcase in SHOWCASES
    ]


def test_a_recording_is_the_models_decisions_over_the_fixtures_inputs():
    document = record(
        recordings.showcase_named("good-news"), Greets(),
        model_name="stand-in-model", today=TODAY,
    )
    provenance = document["payload"]["execution"]["provenance"]
    moments = document["payload"]["episodes"][0]["storyboard"]["moments"]

    assert document["model"] == "stand-in-model"
    assert document["recorded_on"] == "2026-09-22"
    assert provenance["kind"] == "recorded_model_run"
    assert provenance["kind_means"] == PROVENANCE["recorded_model_run"]
    assert provenance["hardware_unverified"] == HARDWARE_UNVERIFIED
    assert "stand-in-model" in provenance["headline"]
    assert "2026-09-22" in provenance["headline"]
    # The stand-in's words, not the fixture's authored reply.
    spoken = [m["facts"]["args"]["text"] for m in moments if m["kind"] == "tool_called" and m["facts"]["tool"] == "speak"]
    assert spoken == ["Hello there."]
    assert document["payload"]["episodes"][0]["cue_text"] == "Misty, I just got accepted!"


def test_a_run_that_never_reaches_the_model_says_it_was_not_called():
    document = record(
        recordings.showcase_named("visual-passerby"), Greets(),
        model_name="stand-in-model", today=TODAY,
    )
    provenance = document["payload"]["execution"]["provenance"]

    assert document["payload"]["episodes"] == []
    assert provenance["model"] == "not called"
    assert "never called" in provenance["detail"]


def test_loading_refuses_anything_that_is_not_the_named_example(tmp_path):
    showcase = recordings.showcase_named("good-news")
    document = record(showcase, Greets(), model_name="m", today=TODAY)

    with pytest.raises(NoRecording, match="not been recorded"):
        load("good-news", tmp_path)
    with pytest.raises(NoRecording, match="no example"):
        load("../good-news", tmp_path)

    (tmp_path / "good-news.json").write_text(json.dumps({**document, "format": 0}))
    with pytest.raises(NoRecording, match="format"):
        load("good-news", tmp_path)

    swapped = {**document, "showcase": {**document["showcase"], "fixture": "vague-help"}}
    (tmp_path / "good-news.json").write_text(json.dumps(swapped))
    with pytest.raises(NoRecording, match="something else"):
        load("good-news", tmp_path)

    (tmp_path / "good-news.json").write_text(json.dumps(document))
    assert load("good-news", tmp_path)["model"] == "m"


# ---------------------------------------------------------------------------
# The committed recordings, as data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("showcase", SHOWCASES, ids=lambda item: item.key)
def test_every_example_has_a_recording_that_says_who_made_it(showcase):
    document = load(showcase.key)
    provenance = document["payload"]["execution"]["provenance"]

    assert provenance["kind"] == "recorded_model_run"
    assert provenance["hardware_unverified"] == HARDWARE_UNVERIFIED
    assert document["model"] and document["model"] != "authored script"
    datetime.date.fromisoformat(document["recorded_on"])
    for episode in document["payload"]["episodes"]:
        assert episode["storyboard"]["moments"], "an Episode with nothing to replay"


def spoken_in(document):
    return [
        moment["facts"]["args"]["text"]
        for episode in document["payload"]["episodes"]
        for moment in episode["storyboard"]["moments"]
        if moment["kind"] == "tool_called" and moment["facts"]["tool"] == "speak"
    ]


@pytest.mark.parametrize("showcase", SHOWCASES, ids=lambda item: item.key)
def test_nothing_misty_says_in_a_recording_crosses_a_safety_boundary(showcase):
    """A recording is shown to other people as what the model does. If a
    re-recording ever claims a diagnosis, a rescue, a promise of safety or a
    call it cannot make, it must not ship — record it again or drop it."""
    assert boundary_violations(spoken_in(load(showcase.key))) == []


@pytest.mark.parametrize("showcase", SHOWCASES, ids=lambda item: item.key)
def test_no_example_ships_a_run_that_failed(showcase):
    """A recording is overwritten in place, so a failed attempt replaces a
    good one — which is how two Episodes that ended in a provider error
    briefly became the examples on the page."""
    for episode in load(showcase.key)["payload"]["episodes"]:
        assert episode["outcome"]["outcome"] != "error", episode["outcome"]


def test_the_page_is_served_the_list_and_each_recording():
    listed = json.loads(answer("GET", "/recordings").body)

    assert [item["key"] for item in listed] == [item.key for item in SHOWCASES]
    assert all(item["recorded"] and item["model"] for item in listed)
    first = json.loads(answer("GET", f"/recordings/{listed[0]['key']}").body)
    assert first["showcase"]["fixture"] == listed[0]["fixture"]
    assert answer("GET", "/recordings/nope").status == 404
    assert answer("GET", "/recordings/..%2Fpage.html").status == 404


# ---------------------------------------------------------------------------
# One list: perceiving, deciding, acting
# ---------------------------------------------------------------------------

def playback(key):
    """As the page gets it: a recording is stored data, and the list it
    plays is projected when it is served, so a rendering change never means
    paying for fifteen model runs again."""
    served = json.loads(answer("GET", f"/recordings/{key}").body)
    assert "playback" not in load(key)["payload"], "the projection was frozen into the file"
    return served["payload"]["playback"]


def test_the_playback_starts_with_what_misty_perceived():
    """The page used to begin at the first Turn, with the local gates in a
    separate prose panel underneath. That showed a robot which had already
    decided to interrupt somebody, and said nothing about how it decided."""
    heard = playback("hey-greeting-only")
    seen = playback("visual-gaze-wave")

    assert [step["headline"] for step in heard[:3]] == [
        "Wake phrase recognised",
        "An utterance was captured",
        "Transcribed",
    ]
    assert heard[0]["source"] == "perception"
    assert "hey misty" in heard[0]["detail"]
    assert [step["kind"] for step in seen[:4]] == ["visual_gate"] * 4
    assert seen[3]["headline"] == "Sustained gaze plus a wave passed the gate"
    assert "gaze_duration_s" in seen[3]["facts"]


def test_a_run_that_opened_no_episode_still_has_something_to_play():
    """The strongest example on the page is the one where nothing happens,
    and it is the one an Episode-only timeline left blank."""
    steps = playback("visual-passerby")

    assert steps, "the quiet example plays nothing at all"
    assert {step["source"] for step in steps} == {"perception"}
    assert all(step["headline"] == "The person is not looking at Misty" for step in steps)


def test_the_moments_of_each_episode_are_spliced_in_where_it_opened():
    steps = playback("respect-boundary")
    sources = [step["source"] for step in steps]
    episodes = [step["episode"] for step in steps if step["source"] == "episode"]

    assert sources[0] == "perception", "the request Misty heard comes first"
    assert episodes == sorted(episodes) and set(episodes) == {0, 1}
    # Suppression happens between the two Episodes, and is Misty deciding
    # not to intrude — the part of this example worth watching.
    between = [
        step["headline"]
        for step in steps
        if step["source"] == "perception" and step["kind"] == "cue_suppressed"
    ]
    assert between == ["Care Cue opened no Episode"] * 2


def test_the_playback_leaves_none_of_the_journal_out():
    """It replaced a list that was every Moment of every Episode, so it has
    to still be that, plus what came before."""
    for showcase in SHOWCASES:
        document = load(showcase.key)
        recorded = [
            moment["headline"]
            for episode in document["payload"]["episodes"]
            for moment in episode["storyboard"]["moments"]
        ]
        played = [
            step["headline"]
            for step in playback(showcase.key)
            if step["source"] == "episode"
        ]

        assert played == recorded, showcase.key


def test_every_step_carries_what_the_page_draws_it_with():
    for showcase in SHOWCASES:
        for step in playback(showcase.key):
            assert step["headline"]
            assert step["source"] in {"perception", "episode"}
            if step["source"] == "episode":
                assert step["robot"], "an Episode Moment with no pose to draw"
            else:
                assert "robot" not in step, "perception invented a pose"


# ---------------------------------------------------------------------------
# The plain telling of a run
# ---------------------------------------------------------------------------

def told(key):
    return [step for step in playback(key) if step["tells_the_story"]]


def called(steps, tool):
    """The step where a Tool was called, found by the Tool rather than by
    its wording: a re-recording is free to pick another argument."""
    return next(
        step for step in steps
        if step["kind"] == "tool_called" and step["facts"]["tool"] == tool
    )


def turns_in(key):
    return [step["kind"] for step in playback(key)].count("turn_started")


def test_the_loops_own_bookkeeping_is_not_part_of_the_telling():
    """`turn 1`, `model replied in 0ms`, `available Skills`: how the loop
    works, not what happened in the room. `0ms` is not even true of a
    recording, where the clock is a fake one."""
    kinds = {step["kind"] for step in told("hey-greeting-only")}

    assert not kinds & {
        "turn_started", "model_called", "episode_started",
        "target_bound", "skills_available", "decision_noted",
    }
    assert "tool_called" in kinds
    # Still in the playback, one per Turn, for the developer view.
    calls = [step["kind"] for step in playback("hey-greeting-only")].count("tool_called")
    assert turns_in("hey-greeting-only") == calls


def test_an_approach_that_leaves_more_room_is_not_told_as_coming_closer():
    from misty_agent.demo import _ACTIONS

    assert _ACTIONS["approach"]({}) == "Comes closer"
    assert _ACTIONS["approach"]({"keep": "close"}) == "Comes closer"
    assert "back" in _ACTIONS["approach"]({"keep": "far"}).lower()
    assert "closer" not in _ACTIONS["approach"]({"keep": "comfortable"})


def test_each_action_is_one_sentence_with_the_reason_on_it():
    """Two records — the note it wrote, the call it made — read as one
    thing: what it did, and why it said it was doing it."""
    steps = told("come-closer-hazard")
    said = [step["summary"] for step in steps]

    assert said[0].startswith("“"), "the person speaks first"
    assert any(line.startswith("Says “") for line in said)
    assert called(steps, "approach")["summary"] in said
    assert any("something is in the way" in line for line in said)
    assert any(re.search(r"\(\d+cm away\)", line) for line in said)
    # Whenever the model wrote a note, it rides on the call it was written
    # for rather than sitting in a row of its own. (Recorded runs do not
    # always carry one: `tool_choice` requires a call, not a sentence.)
    # A note that only repeats the line Misty is about to say is dropped:
    # above the bubble, it reads as the robot saying everything twice.
    for showcase in SHOWCASES:
        steps = playback(showcase.key)
        written = [step["detail"] for step in steps if step["kind"] == "decision_noted"]
        carried = [step["why"] for step in steps if step.get("why")]
        dropped = [
            step["text"]
            for step in steps
            if step["kind"] == "tool_called" and step["voice"] == "says" and not step["why"]
        ]

        assert all(note in written for note in carried), showcase.key
        for note in set(written) - set(carried):
            assert note in dropped, (showcase.key, note)


def test_a_result_is_shown_only_when_it_says_something():
    """Every Tool call comes back; `ok` after speaking is not news, and a
    row for each of them is what made the list twice as long as the run."""
    spoken_results = [
        step
        for step in playback("hey-greeting-only")
        if step["kind"] == "observation" and step["headline"] == "ok"
    ]
    heard = [step for step in told("vague-help") if step["summary"].startswith("Hears “")]

    assert spoken_results and not any(step["tells_the_story"] for step in spoken_results)
    assert heard, "what somebody actually said was left out"
    assert any(step["summary"] == "Nobody answers" for step in told("hey-greeting-only"))


def test_the_telling_is_shorter_than_the_record_and_never_longer():
    for showcase in SHOWCASES:
        steps = playback(showcase.key)
        story = [step for step in steps if step["tells_the_story"]]

        assert len(story) <= len(steps)
        assert story, f"{showcase.key} has nothing to tell"
        assert all(step["summary"] for step in steps), "a step with no sentence"


# ---------------------------------------------------------------------------
# Who each step belongs to
# ---------------------------------------------------------------------------

def test_every_step_says_whose_it_is():
    """The page draws a step by whose it is: the person's words and Misty's
    words as bubbles, an action as a line, what came back indented under
    it. Without this, all four looked the same and nobody could tell a
    request from a reply."""
    from misty_agent.demo import VOICES

    for showcase in SHOWCASES:
        for step in playback(showcase.key):
            assert step["voice"] in VOICES, (showcase.key, step["kind"])
            if step["voice"] in {"person", "says"}:
                assert step["text"], (showcase.key, step["summary"])

    voices = {step["summary"]: step["voice"] for step in told("come-closer-hazard")}
    assert called(told("come-closer-hazard"), "approach")["voice"] == "acts"
    assert voices["Nobody answers"] == "result"
    blocked = next(step for step in told("come-closer-hazard") if "in the way" in step["summary"])
    assert blocked["voice"] == "result" and blocked["pushback"]
    heard = next(step for step in told("vague-help") if step["summary"].startswith("Hears “"))
    assert heard["voice"] == "person" and heard["text"] in heard["summary"]


def test_someone_speaking_during_an_episode_appears_where_they_spoke():
    """B asks for a turn while Misty is listening to A. Spliced in whole at
    the place A's Episode opened, B's words came after A's goodbye, as if
    Misty had said goodbye for no reason."""
    story = [step["summary"] for step in told("a-then-b")]

    asked = story.index("“Hey Misty, my turn.”")
    assert story.index("Listens for an answer") < asked
    assert asked < story.index("B is waiting for a turn")
    assert asked < next(i for i, line in enumerate(story) if "goodbye" in line.lower())
    who = {step["text"]: step.get("actor") for step in told("a-then-b") if step["voice"] == "person"}
    assert who["Hey Misty, my turn."] == "B"


def test_what_was_understood_keeps_the_order_it_was_understood_in():
    """A cue carries the time its words were spoken, and is detected only
    once they have been transcribed. Sorting by time alone put the words
    before the wake phrase that let them through."""
    story = [step["summary"] for step in told("hey-greeting-only")]

    assert story[:4] == [
        "Wake phrase recognised",
        "An utterance was captured",
        "Transcribed",
        "“Hey Misty, hello!”",
    ]
    assert story[-1] == f"Conversation over after {turns_in('hey-greeting-only')} turns"

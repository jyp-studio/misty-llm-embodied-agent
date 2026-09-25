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

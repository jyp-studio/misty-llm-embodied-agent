"""What the robot is told it is.

This is the one piece of the system written *for* a model to read, which makes
it the one piece no type checker, no schema and no mutation of an argument can
guard. What can be guarded is that it reaches the model, that it does not
smuggle across the boundary `PLAN.md` §4 draws, and that it still makes the
claims it is here to make.

## Claims, not vocabulary

Every content assertion below reads a **phrase**, not a word. That is a
deliberate reversal: the first version of this file asserted `"literally" in
PERSONA.lower()`, and a review's mutant flipped *"Do not take an odd word
literally"* into *"Take an odd word literally"* with the whole suite still
green. Six tests were checking that the prompt mentioned a topic — never that
it took a side. The same mutant run replaced the entire persona with negated
filler and nothing went red.

A word survives its own negation; a phrase does not. The cost is that
rewording a load-bearing sentence now fails a test, which is the point: these
sentences *are* the deliverable, so editing one should be a deliberate act
that says so here too.

`FLAT` exists because the constant is hard-wrapped — "you cannot\\n  do it"
is not the substring anyone would write in an assertion.

The old prompt went with the script in M7 #12; this typed persona is the
current model-facing contract.
"""

from __future__ import annotations

import pytest

from episode_invariants import (
    Episode,
    no_physical_parameter_reached_the_model,
)
from misty_agent.agent.layering import (
    DRIVE_COMMANDS,
    RATE_STEMS,
    mentions_control_parameter,
)
from misty_agent.agent.persona import PERSONA
from misty_agent.agent.tools import build_registry

#: The persona as one unwrapped lowercase line, so an assertion can quote a
#: sentence the way it reads rather than the way it is typeset.
FLAT = " ".join(PERSONA.lower().split())


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------

def test_the_persona_names_no_physical_control_parameter():
    """`PLAN.md` §4's claim is about what the model is *handed*.

    A prompt naming one would break that claim in the very sentence explaining
    it — which is why the layering paragraph is worded around the words rather
    than with them.
    """
    assert mentions_control_parameter(PERSONA) is None


def test_the_persona_survives_the_audit_the_live_suite_runs():
    """Not the guard on its own: the same check, over the persona *and* the
    nine Tool schemas together, exactly as `tests/test_llm_live.py` runs it.
    Two clean halves can still be dirty when concatenated — the audit
    flattens, so a word can straddle the join.
    """
    episode = Episode(
        records=[],
        turn_cap=8,
        prompts=[[{"role": "system", "content": PERSONA}]],
        tools=list(build_registry().schemas()),
    )

    assert no_physical_parameter_reached_the_model(episode) == []


@pytest.mark.parametrize("forbidden", sorted(set(RATE_STEMS + DRIVE_COMMANDS)))
def test_no_spelling_the_guard_refuses_appears_in_the_persona(forbidden):
    """Independently of the audit, and stem by stem, so a guard that stopped
    matching would not take this with it."""
    flattened = "".join(ch for ch in PERSONA.lower() if ch.isalnum())

    assert forbidden not in flattened


def test_the_persona_does_not_teach_the_control_layer_s_vocabulary():
    """`CONTEXT.md` reserves *Step* for one drive command.

    Teaching the word to the model is teaching it to think in the terms §4
    separates — so the layering sentence says "how far each part of that
    journey goes" instead.
    """
    words = {word.strip(".,;:*`\"'()").lower() for word in PERSONA.split()}

    assert "step" not in words
    assert "steps" not in words


# ---------------------------------------------------------------------------
# The two things worth keeping from the prompt that was deleted
# ---------------------------------------------------------------------------

def test_the_persona_says_what_the_robot_is():
    """A model told only "someone spoke" has no ground to stand on."""
    assert "you are misty, a small social robot" in FLAT


def test_the_persona_warns_that_the_transcript_is_noisy():
    """Not a nicety: `said` comes out of hosted speech-to-text, and a model
    reading a mis-transcribed word literally answers a question nobody asked.
    This is one of two things carried over from the deleted prompt.

    The negation is the whole instruction. *Take* an odd word literally is the
    behaviour this exists to prevent, and it contains every word the sentence
    does.
    """
    assert "came from automatic transcription" in FLAT
    assert "do not take an odd word literally" in FLAT


def test_the_persona_tells_the_model_to_follow_the_persons_language():
    """Ticket 14. Phrases, not the word "language": the persona already said
    "in the user's language" before this ticket, so a word would have been
    green from the start."""
    assert "answer in the language the person is using" in FLAT
    assert "the language of what they said last is the language to use next" in FLAT
    assert "your wake phrase is english" in FLAT


def test_the_persona_rules_out_diagnosis_rescue_and_reaching_anyone():
    """Each of these reverses if the sentence is negated, which the word on
    its own would not."""
    assert "never say or imply that you have contacted somebody" in FLAT
    assert "do not name a diagnosis or an injury" in FLAT
    assert "do not promise that they will be safe" in FLAT
    assert "you cannot lift, carry, pull or free anyone" in FLAT
    # What it points at instead, and why it does not name a number.
    assert "their local emergency services" in FLAT
    assert "do not invent an emergency number" in FLAT


def test_care_guidance_keeps_visual_geometry_uncertain_and_respects_words():
    assert "not an emotion diagnosis" in FLAT
    assert "respect what they said" in FLAT
    assert "not permission to approach" in FLAT


# ---------------------------------------------------------------------------
# The four things ReAct needs
# ---------------------------------------------------------------------------

def test_the_persona_closes_the_door_on_acting_without_a_tool():
    """Not "tools exist" — that the set of them is the set of what it can do.
    Softening the second half to "do it some other way" leaves every word in
    place and reverses the rule.
    """
    assert "if you cannot do it with a tool, you cannot do it" in FLAT


def test_the_persona_requests_only_a_short_public_decision_note():
    assert "short public decision note" in FLAT
    assert "do not provide private reasoning" in FLAT


def test_the_persona_says_that_stopping_is_the_models_own_choice():
    """`PLAN.md` §4: self-termination is what makes a ReAct loop one, and the
    model cannot choose something nobody told it about.

    "is *not* a choice you make" is a one-word edit that keeps "stopping" and
    "choice" both present, so the phrase is what is asserted.
    """
    assert "stopping is a choice you make" in FLAT
    assert "`done`" in PERSONA


def test_the_persona_gives_the_model_whether_and_withholds_how_far():
    """The sentence carrying §4's central claim.

    Both halves, because either alone is satisfiable by its own opposite:
    the model chooses *whether*, and does not choose how far.
    """
    assert "you decide *whether* to close the distance" in FLAT
    assert "is not yours to choose" in FLAT


def test_the_persona_forbids_narrating_the_movement_it_does_not_control():
    """The half of the old prompt's layering rule that the first draft lost.

    `episode_invariants.no_physical_parameter_reached_the_model` audits the
    prompts and Tool schemas — what reaches the model. Nothing audits what the
    model *emits*, so a `speak` text of "I'll move 20cm" is stopped here or
    not at all.
    """
    assert "never announce how fast or how far you are about to move" in FLAT


def test_the_persona_says_it_is_speaking_aloud():
    """`speak` caps its text at 150 characters; nothing tells the model why.
    A room is the reason.
    """
    assert "you are speaking aloud in a room, not writing" in FLAT


# ---------------------------------------------------------------------------
# The messages that actually arrive
# ---------------------------------------------------------------------------

def test_the_persona_describes_the_snapshot_by_the_names_the_model_reads():
    """`react.py:_observed` sends the Observation as JSON and, per §15.4, no
    prose summary beside it. So the field names *are* the model's interface.

    An earlier draft glossed `"Nobody in view"`, which is `journal.py`'s
    `describe` — terminal output, never sent to a model. This asserts the
    three names in `Snapshot` are the three the prompt explains.
    """
    for field in ("distance_cm", "face_present", "new_speech"):
        assert f"`{field}`" in PERSONA, field

    assert "nobody in view" not in FLAT


def test_the_persona_reads_a_missing_face_the_way_the_pipeline_means_it():
    """`face_present` is "there is a fresh distance reading", and the distance
    is derived from face width — so a false reads as *not pointed at anyone*,
    not as *nobody is there*. Dropping the negation inverts the advice.
    """
    assert "which does not mean the room is empty" in FLAT


def test_the_persona_does_not_promise_a_snapshot_after_a_refused_call():
    """A refusal appends its reason and `continue`s — no Observation, so no
    Snapshot. The first draft said the model is told what it can see after
    *each* tool call, which is false in exactly the case it most needs.
    """
    assert "a tool call comes back one of two ways" in FLAT
    assert "refused: you are given a reason, and nothing else" in FLAT


# ---------------------------------------------------------------------------
# What it deliberately leaves to the Tool schemas
# ---------------------------------------------------------------------------

def test_the_persona_tells_it_to_say_something_before_a_slow_action():
    """From the first recorded runs: it drove from 150cm to 67cm in silence
    and then listened three times. A person watching a robot cross a room
    without a word cannot tell whether it heard them."""
    assert "say one short line first" in FLAT
    assert "before you move or scan" in FLAT


def test_the_persona_says_two_silences_end_the_waiting():
    """Same runs: `listen` returned `silence` with the microphone reported
    unavailable, and it called `listen` again anyway — eleven times in the
    rescue case, until the Turn cap ended the Episode."""
    assert "do not call `listen` again" in FLAT
    assert "say something or finish" in FLAT


def test_the_persona_says_speech_arrives_without_listening_for_it():
    """`new_speech` rides on every snapshot, so waiting is only for an
    answer it actually asked for."""
    assert "you do not need `listen` to notice that somebody spoke" in FLAT


def test_the_persona_puts_words_first_when_somebody_is_in_trouble():
    """The rescue recording spent its whole Episode on Skills and listening
    and never answered the person at all."""
    assert "answer them in words before" in FLAT


def test_the_persona_forbids_finishing_without_having_said_anything():
    """The second recording pass still produced Episodes that observed, took
    a Skill, listened and closed without one word — for a person trapped
    under a shelf, and for somebody who had just said hello. Silence reads
    as a broken robot, whatever the Journal says happened."""
    assert "never call `done` without having said something" in FLAT


def test_the_persona_answers_in_a_language_somebody_actually_used():
    """With reasoning on, it greeted an English speaker in Spanish and a
    silent waving person in German, and switched a Traditional Chinese
    conversation into Simplified partway through."""
    assert "never answer in a language nobody here has used" in FLAT
    assert "nobody has said anything yet" in FLAT
    assert "keep the script they wrote in" in FLAT


def test_the_persona_does_not_restate_what_a_tool_schema_already_says():
    """The nine schemas are sent alongside it every Turn. §15.4's
    one-fact-one-place: two statements of one rule are two things that can
    drift, and the one the model attends to is the one nobody checked.
    """
    for duplicated in (
        "in the user's language",  # `speak`
        "stops on its own",  # `approach`
        "nothing further is worth doing",  # `done`
    ):
        assert duplicated not in FLAT, duplicated


def test_the_persona_does_not_describe_a_system_that_no_longer_exists():
    """The deleted prompt specified a JSON object with `movement`,
    `expression` and `gesture` fields, whitelisted against malformed output.
    Function calling and `tools.py`'s argument types replaced all of it.
    """
    for gone in ("json", "movement", "complex_task", "back_up", "whitelist"):
        assert gone not in FLAT, gone


def test_the_persona_is_not_empty():
    """The negative control for every test above that asserts an absence:
    an empty string contains no forbidden word either."""
    assert len(PERSONA.split()) > 100

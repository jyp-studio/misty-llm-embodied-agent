"""The line the model may not cross.

`PLAN.md` §4's layering claim — the model decides *whether*, the control layer
decides *how far* — is enforced in two places that used to disagree: a Tool may
not declare a control parameter, and a Journal record may not carry one. Both
now ask `layering.py`, so this is where the rule itself is checked.

The subtle half is the direction. A duration the model **chooses** is the model
driving; a duration the system **reports** is a measurement, and four golden
Journals depend on two of those being allowed. A rule that got this wrong in
the strict direction would fail every golden; wrong in the loose direction it
would let the claim quietly become false. Both directions are checked here.
"""

from __future__ import annotations

import pytest

from misty_agent.agent.layering import (
    control_parameter,
    refuse_control_parameters,
)


# ---------------------------------------------------------------------------
# Rates: refused whichever way they are travelling
# ---------------------------------------------------------------------------

RATES = [
    "velocity",
    "linearVelocity",
    "angularVelocity",
    "velocity_cm_s",
    "speed",
    "speed_cm_s",
    "driveSpeed",
    "cm_per_sec",
]


@pytest.mark.parametrize("name", RATES)
@pytest.mark.parametrize("commanded", [True, False])
def test_a_rate_is_refused_in_both_directions(name, commanded):
    """A result that reports a velocity teaches the model to reason in one."""
    assert control_parameter(name, commanded=commanded) is not None


# ---------------------------------------------------------------------------
# Durations: it depends who chose them
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name", ["duration_ms", "wait_seconds", "hold_secs", "pauseMillis"]
)
def test_a_duration_the_model_would_choose_is_refused(name):
    assert control_parameter(name, commanded=True) is not None


@pytest.mark.parametrize("name", ["estimated_speech_ms", "latency_ms", "elapsed_s"])
def test_a_duration_the_system_reports_is_allowed(name):
    """These are measurements, and the goldens are built out of them.

    `PLAN.md` §15.4's suppression window is `estimated_speech_ms` and nothing
    else; `latency_ms` is on every `model_called` record. The first version of
    this rule rejected both.
    """
    assert control_parameter(name, commanded=False) is None


@pytest.mark.parametrize("name", ["timeMs", "time_ms", "drive_ms", "driveTimeMs"])
@pytest.mark.parametrize("commanded", [True, False])
def test_the_drive_commands_own_parameter_is_refused_in_both_directions(
    name, commanded
):
    """The exception to the exception.

    A measurement may be a duration, but `timeMs` is not a measurement — it is
    what Misty's API calls the drive duration. Reported back to the model it
    is the control layer handing over its own vocabulary.
    """
    assert control_parameter(name, commanded=commanded) is not None


# ---------------------------------------------------------------------------
# Spelling cannot be used to get around it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pair",
    [
        ("driveTimeMs", "drive_time_ms"),
        ("linearVelocity", "linear_velocity"),
        ("waitSeconds", "wait_seconds"),
    ],
)
def test_camel_case_and_snake_case_are_the_same_name(pair):
    camel, snake = pair
    assert (
        control_parameter(camel, commanded=True) is not None
        and control_parameter(snake, commanded=True) is not None
    )


# ---------------------------------------------------------------------------
# The negative control
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "pitch",
        "yaw",
        "text",
        "image",
        "arms",
        "move_arms",
        "distance_cm",
        "target_distance_cm",
        "second_image",
        "second_attempt",
        "",
    ],
)
@pytest.mark.parametrize("commanded", [True, False])
def test_an_ordinary_name_is_not_a_control_parameter(name, commanded):
    """A guard that rejected everything would satisfy every test above.

    Three of these are load-bearing. `arms` ends in the letters `ms` without
    being a duration. `second_image` contains a whole time unit that is an
    ordinal here — which is what the unit has to be the name's *last* segment
    for; loosen it to "anywhere in the name" and this is the case that breaks.
    And `target_distance_cm` is allowed because `PLAN.md` §15.2 explicitly
    left open the possibility of a clamped target distance on `approach`: a
    rule that pre-empted that decision would be making it.
    """
    assert control_parameter(name, commanded=commanded) is None


# ---------------------------------------------------------------------------
# What the caller gets told
# ---------------------------------------------------------------------------

def test_the_reason_says_which_rule_was_matched():
    """A Tool author who is told only "no" has to guess what to rename it to."""
    assert "rate" in control_parameter("linearVelocity", commanded=True)
    assert "duration" in control_parameter("wait_seconds", commanded=True)


def test_refusing_names_the_offending_name_and_where_it_was():
    with pytest.raises(ValueError) as raised:
        refuse_control_parameters(
            "Tool 'drive'", ["pitch", "linearVelocity"], commanded=True
        )

    assert "linearVelocity" in str(raised.value)
    assert "Tool 'drive'" in str(raised.value)
    assert "§4" in str(raised.value)


def test_a_clean_set_of_names_raises_nothing():
    refuse_control_parameters("Tool 'nod'", ["pitch", "yaw"], commanded=True)

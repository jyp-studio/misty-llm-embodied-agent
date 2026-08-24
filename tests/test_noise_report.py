"""The M6 noise report, and the claims it is allowed to make.

`build_noise_report` is pure — a boundary curve in, text out — so everything
here runs in milliseconds and needs no media stack, no camera and no
simulation. The command that produces the curve is a thin wrapper, exercised
by being run.

What is asserted here is mostly **honesty**, not arithmetic. Where the
envelope lands is computed and tested elsewhere; nothing in this file asserts
a value for it, because both swept axes are UNCALIBRATED and PLAN.md §14.2
reserves thresholds for Measurements.
"""

from __future__ import annotations

import re

import pytest

from harness.report import build_noise_report
from harness.robustness import ApproachOutcome, boundary_curve
from misty_agent.config import Settings

SETTINGS = Settings()


def _row(*, lag_s, jitter_px, seed=0, converged=True, closest_cm=60.0, reversals=0):
    return ApproachOutcome(
        transport_lag_s=lag_s,
        outcome="arrived",
        steps=1,
        closest_cm=closest_cm,
        final_cm=60.0 if converged else 100.0,
        settings=SETTINGS,
        actual_motion_multiplier=SETTINGS.max_actual_motion_multiplier,
        direction_reversals=reversals,
        jitter_px=jitter_px,
        seed=seed,
    )


def a_curve(*, jitters=(0.0, 4.0, 16.0), lags=(0.0, 0.05, 0.10), reversals=0):
    return boundary_curve(
        [
            _row(
                lag_s=lag,
                jitter_px=jitter,
                seed=seed,
                converged=lag < 0.10,
                closest_cm=60.0 if lag < 0.10 else 30.0,
                reversals=reversals if lag >= 0.10 else 0,
            )
            for jitter in jitters
            for seed in (0, 1)
            for lag in lags
        ]
    )


def test_the_report_shows_one_line_per_jitter_level_not_per_grid_point():
    """Two dimensions is the experiment's shape, not the report's.

    A surface printed in full is a table nobody reads. The check is deliberate
    about the failure it guards: a report that grew a row per (lag, jitter)
    pair would still contain the right numbers and be useless.
    """
    jitters = (0.0, 1.0, 2.0, 4.0)
    lags = (0.0, 0.05, 0.10, 0.15)
    curve = a_curve(jitters=jitters, lags=lags)
    markdown = build_noise_report(curve).to_markdown()

    # Rows of the curve table specifically — `| <n> px | ...` — not every
    # table in the document. Counting all of them would pass for the wrong
    # reason, and did: the preamble also has a row mentioning px.
    curve_rows = [
        line
        for line in markdown.splitlines()
        if re.match(r"^\| [\d.]+ px \|", line)
    ]

    assert len(curve_rows) == len(jitters)
    assert len(curve_rows) < len(jitters) * len(lags), (
        "the report is dumping the surface, not the curve"
    )


def test_the_report_names_all_three_failure_modes():
    markdown = build_noise_report(a_curve(reversals=2)).to_markdown().lower()

    assert "floor" in markdown
    assert "converg" in markdown
    assert "revers" in markdown


def test_the_report_says_it_is_a_sweep_and_never_a_measurement():
    report = build_noise_report(a_curve())

    for rendering in (report.to_markdown().lower(), report.to_text().lower()):
        assert "sweep" in rendering
        assert "not a measurement" in rendering
        assert "uncalibrated" in rendering


def test_the_report_states_how_precisely_the_boundary_is_located():
    markdown = build_noise_report(a_curve()).to_markdown()

    assert "±0.05" in markdown


def test_the_report_says_when_an_axis_has_nothing_to_report():
    """An empty column reads like a pass. It has to read like a silence.

    M6 #04 measured zero reversals at every swept lag under the configured
    travel multiplier, so this is the expected state of that column and the
    report must not let it look like evidence of stability.
    """
    markdown = build_noise_report(a_curve(reversals=0)).to_markdown().lower()

    assert "no swept row reversed" in markdown


def test_the_report_distinguishes_reversal_inside_the_envelope_from_outside():
    outside = build_noise_report(a_curve(reversals=2)).to_markdown().lower()

    assert "already failing" in outside


def test_the_report_never_claims_hardware():
    markdown = build_noise_report(a_curve()).to_markdown().lower()

    assert "misty ii" in markdown
    assert "never" in markdown


def test_the_report_records_what_it_swept_over():
    markdown = build_noise_report(a_curve()).to_markdown()

    assert "seed" in markdown.lower()
    assert "16" in markdown


def test_the_report_survives_a_curve_where_nothing_converged():
    curve = boundary_curve(
        [
            _row(lag_s=lag, jitter_px=2.0, converged=False, closest_cm=30.0)
            for lag in (0.0, 0.05)
        ]
    )

    markdown = build_noise_report(curve).to_markdown()

    assert "converged" in markdown.lower()


def test_the_failure_counts_carry_their_denominator():
    """A bare "1401 rows crossed the floor" reads as alarming and means little.

    The lag axis is swept several times past where the controller stops
    converging, so most rows failing is the shape of the experiment. Without
    the denominator and a sentence saying so, the table invites exactly the
    wrong reading.
    """
    markdown = build_noise_report(a_curve()).to_markdown()

    assert " of " in markdown
    assert "denominator" in markdown.lower()


def test_the_report_does_not_print_a_measured_looking_zero_for_the_impossible():
    """Floor breach inside the envelope cannot happen by construction.

    `converged` already requires the floor to have been respected, so a `0`
    in that cell would look like an observation when it is a tautology.
    """
    markdown = build_noise_report(a_curve()).to_markdown().lower()

    assert "none possible" in markdown
    assert "by definition" in markdown

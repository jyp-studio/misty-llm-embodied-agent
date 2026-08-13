"""Closing the loop: does the controller still converge with stale readings?

Everything in tickets 04–07 watched the perception pipeline with the robot
standing still. This drives the other half — the robot moves because of what it
was told, and what it was told is out of date.

The perception model here is a **delay line with centimetre quantisation**,
which is not an assumption: it is what ticket 06 measured the reference
pipeline to be. `test_the_model_reproduces_the_lag_it_was_given` checks the
model against the same estimator that measured the real thing, so the sweep is
grounded rather than invented.

Nothing here asserts a limit on the envelope. Where the controller stops
converging is a fact to report, not a standard to pass — and it is a fact about
a number (`sensor_transport_lag_s`) that has never been measured and cannot be
without hardware.
"""

from __future__ import annotations

import pytest

import harness.robustness as robustness
from harness.robustness import (
    ApproachOutcome,
    DelayedPerception,
    envelope,
    simulate_approach,
    sweep_transport_lag,
)
from misty_agent.config import Settings
from misty_agent.control.approach import approach as public_approach

SETTINGS = Settings()
ARRIVAL_LO = SETTINGS.target_distance_cm - SETTINGS.distance_tolerance_cm
ARRIVAL_HI = SETTINGS.target_distance_cm + SETTINGS.distance_tolerance_cm


# ---------------------------------------------------------------------------
# The perception model
# ---------------------------------------------------------------------------

def test_a_reading_describes_the_world_as_it_was_one_lag_ago():
    eyes = DelayedPerception(lag_s=0.5)
    eyes.observe(t=0.0, distance_cm=120.0)
    eyes.observe(t=1.0, distance_cm=80.0)

    # Zero-order hold, not interpolation: at t=1.0 the newest frame that has
    # arrived is the one taken at t=0, so 120 rather than the 100 an
    # interpolated model would invent between the two observations.
    assert eyes.read(t=1.0) == 120
    assert eyes.read(t=1.5) == 80


def test_readings_are_whole_centimetres_like_the_real_one():
    eyes = DelayedPerception(lag_s=0.0)
    eyes.observe(t=0.0, distance_cm=91.7)

    assert eyes.read(t=0.0) == 91


def test_nothing_is_reported_before_the_first_observation_has_aged():
    eyes = DelayedPerception(lag_s=1.0)
    eyes.observe(t=0.0, distance_cm=100.0)

    assert eyes.read(t=0.5) is None


def test_the_model_reproduces_the_lag_it_was_given():
    """Check the model with the instrument that measured the real pipeline.

    If `estimate_lag` cannot recover the delay this model was built with, the
    model is not the thing ticket 06 measured and the sweep means nothing.
    """
    from harness.latency import lag_samples
    from harness.replay import Sample, Trace

    eyes = DelayedPerception(lag_s=0.2)
    samples = []
    for i in range(200):
        t = i * 0.02
        truth = 130.0 - 40.0 * t  # the default script's walking pace
        eyes.observe(t, truth)
        reported = eyes.read(t)
        samples.append(
            Sample(
                t=t,
                truth_cm=truth,
                reported_cm=reported if reported is not None else -1,
                backlog=0,
            )
        )
    trace = Trace(samples=tuple(samples), trajectory="model", sample_hz=50.0)

    lags = lag_samples(trace)
    assert lags
    assert sum(lags) / len(lags) == pytest.approx(0.2, abs=0.03)


# ---------------------------------------------------------------------------
# One approach
# ---------------------------------------------------------------------------

def test_with_no_lag_and_perfect_calibration_the_robot_arrives():
    outcome = simulate_approach(
        transport_lag_s=0.0,
        start_cm=130.0,
        speed_error=1.0,
    )

    assert outcome.outcome == "arrived"
    assert ARRIVAL_LO <= outcome.final_cm <= ARRIVAL_HI
    assert outcome.steps <= SETTINGS.max_approach_steps


def test_the_simulation_enters_through_public_approach(monkeypatch):
    calls = 0

    def recording_approach(*args, **kwargs):
        nonlocal calls
        calls += 1
        return public_approach(*args, **kwargs)

    monkeypatch.setattr(robustness, "approach", recording_approach, raising=False)

    simulate_approach(transport_lag_s=0.0)

    assert calls == 1


def test_the_step_cap_is_never_exceeded_however_bad_the_lag():
    # The property PLAN.md §4 calls the system's strongest: every episode
    # provably terminates. It must survive the sweep, or the sweep is
    # measuring a runaway rather than a controller.
    for lag in (0.0, 1.0, 5.0, 20.0):
        assert simulate_approach(transport_lag_s=lag).steps <= (
            SETTINGS.max_approach_steps
        )


def test_a_lag_shorter_than_the_settle_changes_nothing():
    """Most of the settle can absorb lag, but its median has a boundary.

    Public ``approach`` collects fresh-ingress samples throughout settling.
    Once lag makes more than half of that window describe the drive, its median
    changes.  The sweep below locates that boundary precisely.
    """
    baseline = simulate_approach(transport_lag_s=0.0)
    settle = SETTINGS.post_step_settle_s

    for lag in (0.1, 0.5):
        brief = simulate_approach(transport_lag_s=lag)
        assert brief.final_cm == pytest.approx(baseline.final_cm, abs=0.01)

    assert simulate_approach(transport_lag_s=settle - 0.05).final_cm != pytest.approx(
        baseline.final_cm, abs=0.01
    )


def test_observations_must_arrive_in_order():
    eyes = DelayedPerception(lag_s=0.0)
    eyes.observe(t=1.0, distance_cm=100.0)

    with pytest.raises(ValueError):
        eyes.observe(t=0.5, distance_cm=90.0)


def test_a_slow_robot_undershoots_rather_than_overshoots():
    # speed_error < 1 means the robot travels less than commanded. The loop
    # should still converge; it just takes more steps.
    outcome = simulate_approach(transport_lag_s=0.0, speed_error=0.5)

    assert outcome.closest_cm > SETTINGS.min_safe_distance_cm
    assert outcome.converged


def test_the_two_x_counterexample_stays_outside_the_safety_floor():
    """Conditional simulation regression for M4's former 100 -> 44 cm path."""
    outcome = simulate_approach(
        transport_lag_s=0.0, start_cm=100.0, speed_error=2.0
    )

    assert outcome.closest_cm >= SETTINGS.min_safe_distance_cm
    assert outcome.converged


def test_the_two_x_bound_is_not_luck_at_one_starting_distance():
    breached = [
        simulate_approach(
            transport_lag_s=0.0, start_cm=start, speed_error=2.0
        ).inside_safety_floor
        for start in (130.0, 120.0, 110.0, 100.0, 90.0)
    ]

    assert not any(breached)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def test_the_sweep_covers_every_value_it_was_given():
    lags = [0.0, 0.5, 1.0]
    outcomes = sweep_transport_lag(lags)

    assert [o.transport_lag_s for o in outcomes] == lags
    assert all(isinstance(o, ApproachOutcome) for o in outcomes)


def test_the_envelope_reports_where_convergence_stops():
    outcomes = sweep_transport_lag([i * 0.25 for i in range(25)])
    limits = envelope(outcomes)

    assert limits.largest_converging_lag_s is not None
    assert limits.first_failing_lag_s is None or (
        limits.first_failing_lag_s > limits.largest_converging_lag_s
    )
    assert limits.failure_mode in (
        None,
        "timeout",
        "safety_floor_breach",
        "lost_user",
    )


def test_the_envelope_says_it_is_a_sweep_and_not_a_measurement():
    # `sensor_transport_lag_s` has never been measured and cannot be without a
    # robot. A reader who takes the envelope for a measurement has been misled
    # by this file, so the line says so itself.
    summary = envelope(sweep_transport_lag([0.0, 1.0])).summary()

    assert "sweep" in summary.lower()
    assert "not a measurement" in summary.lower()


def test_the_sweep_drives_the_real_control_law():
    # Not a re-derivation: the outcome has to change when the control law's
    # own parameters change, which it cannot if the sweep models the law
    # rather than calling it. PLAN.md §10 records a hand-derived closed form
    # that was wrong and passed anyway.
    wide = simulate_approach(
        transport_lag_s=0.0,
        speed_error=1.0,
        settings=SETTINGS,
    )
    narrow = simulate_approach(
        transport_lag_s=0.0,
        speed_error=1.0,
        settings=Settings(distance_tolerance_cm=2.0),
    )

    assert narrow.steps != wide.steps or narrow.final_cm != wide.final_cm


# ---------------------------------------------------------------------------
# The finding
# ---------------------------------------------------------------------------

def test_the_controller_reports_success_even_when_it_drove_through_the_person():
    """The failure mode is silent, and that is the point of the sweep.

    At a large enough lag the robot finishes *behind* the person and still
    reports "arrived". It cannot do otherwise: it decides it has arrived by
    comparing a reading against the arrival band, and the reading is as stale
    as everything else, so eventually a stale one lands in the band while the
    truth is somewhere else entirely.

    Process-local freshness cannot detect transport staleness that happened
    before frame ingress.  This remaining boundary is why the report sweeps
    sensor transport lag and truth-audits the raw public status separately.
    """
    # 2.0s is enough to make the point: simulator truth breaches the floor,
    # while the delayed public reading still makes the controller say arrived.
    outcome = simulate_approach(transport_lag_s=2.0, start_cm=130.0)

    assert outcome.outcome == "arrived"
    assert outcome.inside_safety_floor
    assert not outcome.converged
    assert outcome.audited_outcome == "safety_floor_breach"


def test_the_episode_still_terminates_at_every_swept_lag():
    # PLAN.md §4 calls this the system's strongest property. It survives — the
    # episode terminates, having failed.
    outcomes = sweep_transport_lag([0.0, 1.0, 2.0, 5.0, 10.0, 30.0])

    assert all(o.steps <= SETTINGS.max_approach_steps for o in outcomes)


def test_the_envelope_boundary_is_where_the_documented_sweep_says():
    # Pins the M5 report, while the M4 table remains the pre-rewrite baseline.
    # Not a threshold to pass — a record of what was reported, so that a change
    # to the control law shows up as this test disagreeing with the document
    # rather than as the document quietly going stale.
    limits = envelope(sweep_transport_lag())

    assert limits.largest_converging_lag_s == pytest.approx(0.65)
    assert limits.first_failing_lag_s == pytest.approx(0.70)
    assert limits.failure_mode == "safety_floor_breach"
    assert limits.first_floor_breach_s == pytest.approx(0.70)


def test_a_coarse_grid_localises_the_new_boundary_poorly():
    coarse = envelope(sweep_transport_lag([0.0, 0.5, 1.0, 1.5, 2.0, 2.5]))
    fine = envelope(sweep_transport_lag())

    assert coarse.first_failing_lag_s == pytest.approx(1.0)
    assert fine.first_failing_lag_s == pytest.approx(0.70)
    assert coarse.failure_mode == fine.failure_mode == "safety_floor_breach"
    assert coarse.resolution_s > fine.resolution_s


def test_the_envelope_reports_how_precisely_it_located_the_boundary():
    limits = envelope(sweep_transport_lag([0.0, 1.0, 2.0]))

    assert limits.resolution_s == pytest.approx(1.0)
    assert "±1.00s" in limits.summary()


def test_the_sweep_starts_from_the_configured_transport_lag():
    # settings.sensor_transport_lag_s has been declared and UNCALIBRATED since
    # M2 with nothing reading it. This is what reads it.
    from harness.robustness import default_sweep_lags
    from misty_agent.config import settings as live

    assert default_sweep_lags()[0] == pytest.approx(live.sensor_transport_lag_s)

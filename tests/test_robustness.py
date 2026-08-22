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


# ---------------------------------------------------------------------------
# Reading noise
#
# The deleted simulation runner injected a flat ±N centimetres at every
# distance. That model is wrong in a direction that matters: distance comes
# from apparent face width through the pinhole relation, so a fixed pixel
# jitter costs centimetres in proportion to the *square* of distance. A flat
# ±8 cm demanded ~38 px of wobble at the 45 cm safety floor — 17 % of the
# face, which cannot happen — and supplied ~2 px at 200 cm, where detection
# actually is shaky. Wrong in both directions at once, and wrong hardest
# exactly where the safety conclusion is decided.
#
# So the swept parameter is **pixel jitter**, and it is UNCALIBRATED in the
# same sense `sensor_transport_lag_s` is: never measured, not measurable
# without a robot. Nothing below asserts where the envelope lands.
# See docs/measurements/m6-coverage-audit.md, gap 1.
# ---------------------------------------------------------------------------

#: The calibration constants, written out rather than read from `settings`, so
#: these tests do not assert the code against itself — the same reasoning as
#: `test_the_commanded_distance_sets_the_face_width_by_the_calibration_formula`.
FOCAL_LENGTH = 650.0
REAL_FACE_WIDTH_CM = 15.0
PX_CM = FOCAL_LENGTH * REAL_FACE_WIDTH_CM  # 9750: the k in d = k / w


def _readings_at(distance_cm, *, jitter_px, frames=400, seed=0):
    """One reading per frame, with the person standing still."""
    eyes = DelayedPerception(lag_s=0.0, jitter_px=jitter_px, seed=seed)
    readings = []
    for frame in range(frames):
        t = frame * 0.01
        eyes.observe(t, distance_cm)
        readings.append(eyes.read(t))
    return readings


def test_no_jitter_leaves_the_delay_line_exactly_as_it_was():
    # Every existing row of the sweep must be unmoved by a parameter's arrival.
    quiet = DelayedPerception(lag_s=0.0)
    declared = DelayedPerception(lag_s=0.0, jitter_px=0.0)
    times = [frame * 0.1 for frame in range(4)]
    for t, distance in zip(times, (130.0, 121.5, 110.2, 99.9)):
        quiet.observe(t, distance)
        declared.observe(t, distance)

    assert [quiet.read(t) for t in times] == [declared.read(t) for t in times]


def test_the_model_reproduces_the_pixel_jitter_it_was_given():
    """Self-validation, the shape the lag model already uses.

    Invert each reported distance back through the pinhole relation: the
    deviations should be the jitter that went in — bounded by it, and reaching
    most of the way to it.
    """
    jitter_px = 6.0
    reported = _readings_at(120.0, jitter_px=jitter_px)
    true_width_px = PX_CM / 120.0
    deviations = [abs(PX_CM / distance - true_width_px) for distance in reported]

    # Truncation to whole centimetres blurs the recovered width, by at most
    # what one centimetre is worth in pixels at this distance.
    slop_px = PX_CM / 120.0 - PX_CM / 121.0
    assert max(deviations) <= jitter_px + slop_px
    assert max(deviations) >= 0.8 * jitter_px


def test_a_fixed_pixel_jitter_costs_more_centimetres_further_away():
    """The entire reason the parameter is pixels rather than centimetres."""
    near, far = 60.0, 180.0
    near_readings = _readings_at(near, jitter_px=4.0)
    far_readings = _readings_at(far, jitter_px=4.0)
    spread_near = max(near_readings) - min(near_readings)
    spread_far = max(far_readings) - min(far_readings)

    assert spread_far / spread_near == pytest.approx((far / near) ** 2, rel=0.15)


def test_jittered_readings_are_still_whole_centimetres():
    # The model must not be more precise than the pipeline it stands for.
    assert all(
        isinstance(distance, int)
        for distance in _readings_at(100.0, jitter_px=5.0, frames=50)
    )


def test_one_frame_reports_one_distance_however_often_it_is_read():
    """Jitter belongs to the detection, not to the act of looking.

    Applied per read, `approach`'s median would average away noise that a real
    pipeline cannot average away, and the sweep would describe a controller
    steadier than the one that exists.
    """
    eyes = DelayedPerception(lag_s=0.0, jitter_px=8.0, seed=3)
    eyes.observe(0.0, 150.0)

    assert len({eyes.read(0.0 + offset) for offset in (0.0, 0.01, 0.02)}) == 1


def test_a_frame_whose_jitter_swallows_the_face_is_skipped_entirely():
    """Mirrors what the production pipeline does, which is to drop the frame.

    `DistancePipeline._consume_loop` skips a frame with no usable face
    (`has_human` false) rather than storing an unknown distance, so the
    previous reading stays on offer until it ages out. The model has to do the
    same, and the observable proof is that a later instant still resolves to
    an *earlier* capture time — the frame in between left no trace.

    An earlier version of this test asserted `reading is None or reading > 0`,
    which cannot fail: `read` holds the last stored value, so it never returns
    None once one frame has landed. Both a model that never skipped and one
    that stored a nonsense distance passed it.
    """
    eyes = DelayedPerception(lag_s=0.0, jitter_px=400.0, seed=1)
    skipped = 0
    for frame in range(40):
        t = frame * 0.01
        eyes.observe(t, 200.0)  # a face only ~49 px wide
        captured_at, distance_cm = eyes.sample(t)
        if captured_at < t:
            skipped += 1
        assert distance_cm > 0, "a stored reading must never be a non-distance"

    assert skipped > 0, (
        "no frame was skipped, so the swallowed-face path never ran and this "
        "test proves nothing about it"
    )


def test_priming_the_delay_line_does_not_change_a_frames_wobble():
    """The two swept parameters must not contaminate each other.

    The simulated world primes the delay line with one frame per lag-second
    before a run starts, so a longer transport lag means more priming frames.
    If wobble came from a stream advanced per call, a longer lag would hand
    the controller a different noise realisation, and a row-to-row difference
    in the two-dimensional sweep would mix lag with a fresh draw. Keying the
    wobble on the frame's own timestamp is what makes rows comparable.
    """
    def reading_after_priming(frames):
        eyes = DelayedPerception(lag_s=0.0, jitter_px=6.0, seed=7)
        for frame in range(frames, 0, -1):
            eyes.observe(-frame / 30.0, 130.0)
        eyes.observe(1.0, 130.0)
        return eyes.read(1.0)

    assert (
        reading_after_priming(2)
        == reading_after_priming(20)
        == reading_after_priming(60)
    )


def test_the_same_seed_reports_the_same_readings():
    # A sweep that cannot be rerun is not a sweep.
    assert _readings_at(140.0, jitter_px=5.0, seed=11) == _readings_at(
        140.0, jitter_px=5.0, seed=11
    )


def test_different_seeds_report_different_readings():
    # The negative control. Without it, a jitter that silently did nothing
    # would satisfy the determinism test above and nobody would notice.
    assert _readings_at(140.0, jitter_px=5.0, seed=11) != _readings_at(
        140.0, jitter_px=5.0, seed=12
    )


def test_a_negative_jitter_amplitude_is_refused():
    with pytest.raises(ValueError):
        DelayedPerception(lag_s=0.0, jitter_px=-1.0)


def test_the_sweep_accepts_jitter_and_still_terminates():
    outcome = simulate_approach(transport_lag_s=0.0, jitter_px=3.0)

    assert outcome.steps <= SETTINGS.max_approach_steps
    assert outcome.outcome in ("arrived", "lost_user", "timeout", "drive_error")


def test_jitter_reaches_the_controller_through_the_sweep():
    """The wiring, asserted where the effect actually exists.

    An outcome-level assertion cannot do this job, and that is a fact about
    the controller rather than about the test: `approach` takes a median of
    fresh readings, so at the default start distance the outcome is identical
    from 0 to 80 px of jitter. Replacing `jitter_px=jitter_px` with `0.0` in
    the simulated world passed the entire suite once for exactly that reason.

    Seed-to-seed divergence is the observable that survives the median. It is
    also the property ticket 05 depends on: if one draw were the whole story
    there would be nothing to average over. `report.PUBLISHED_RUNS` exists
    because a single run was once published as a result and did not
    reproduce.
    """
    quiet = {
        simulate_approach(transport_lag_s=0.0, jitter_px=0.0, seed=seed).final_cm
        for seed in range(3)
    }
    noisy = {
        simulate_approach(transport_lag_s=0.0, jitter_px=120.0, seed=seed).final_cm
        for seed in range(3)
    }

    assert len(quiet) == 1, "without jitter the seed must not matter"
    assert len(noisy) > 1, (
        "the seed changed nothing under jitter, so the jitter never reached "
        "the readings the controller sees"
    )


def test_enough_jitter_makes_the_controller_report_a_success_it_did_not_have():
    """The model has to be able to produce the failure the sweep looks for.

    Not a threshold: PLAN.md §14.2 forbids asserting where the envelope lands,
    and nothing here says 120 px is a limit — that number is far larger than
    any real detector wobble, and it is chosen for being unambiguous rather
    than marginal. What is asserted is that the failure mode *exists* in the
    model, so ticket 05's sweep has something to find. A sweep whose model
    cannot fail would report a clean envelope and mean nothing by it, which is
    M4 #07's lesson: a diagnostic that has never seen its target is not one.
    """
    outcomes = [
        simulate_approach(transport_lag_s=0.0, jitter_px=120.0, seed=seed)
        for seed in range(4)
    ]

    unearned = [
        outcome
        for outcome in outcomes
        if outcome.outcome == "arrived" and not outcome.converged
    ]
    assert unearned, (
        "no swept row reported `arrived` while truth disagreed, so the "
        "public status and the simulator truth never parted company"
    )
    assert all(
        outcome.steps <= SETTINGS.max_approach_steps for outcome in outcomes
    ), "termination must survive any amount of noise"


# ---------------------------------------------------------------------------
# The cross-check
#
# This one IS a Measurement — real pixels, real MediaPipe — so unlike the
# envelope it carries a threshold (PLAN.md §14.2). It is the only lamp that
# lights if the closed form and the detector ever disagree.
# ---------------------------------------------------------------------------

#: Distances probed for linearity. They span 3x, so the sensitivity the model
#: claims spans 9x across them — enough that agreement is agreement about the
#: *shape* of the relationship, not about a single constant.
LINEARITY_DISTANCES_CM = (60.0, 90.0, 120.0, 150.0, 180.0)

#: Pairs probed for the sensitivity itself. The secant sensitivity of d = k/w
#: between two distances is exactly -d1*d2/k, so the prediction carries no
#: linearisation error of its own to explain away.
#:
#: The pairs are far apart on purpose. An earlier version used 60->72 cm and
#: failed at 17 % error: differencing two readings that each carry the
#: detector's documented 2 % error over a 12 cm gap propagates to ~22 %, so the
#: test was measuring its own conditioning rather than the model.
SENSITIVITY_PAIRS = ((60.0, 120.0), (90.0, 180.0))

#: Tolerances derived from the detector's accuracy carried through the
#: arithmetic each test does, plus a margin for truncation to whole
#: centimetres. They are not fitted to observed output.
#:
#: The 2 % starting point comes from
#: `test_the_detector_recovers_the_distance_the_composer_was_given`, which
#: documents it over 72-130 cm. Three of the probes below sit outside that
#: range, so this is an **extrapolation** of a documented figure rather than
#: the figure itself — narrower probes would need less faith, but would also
#: stop spanning enough distance to see the d-squared shape at all.
LINEARITY_TOLERANCE = 0.06
SENSITIVITY_TOLERANCE = 0.10

#: The walk the probes are taken from: start, stop, step in centimetres.
#: Small enough that consecutive frames differ about as much as they would at
#: walking pace on a 30 fps camera.
WALK_CM = (55.0, 185.0, 2.5)


def _readings_along_a_walk(portrait, probes):
    """Detections taken while the person walks away, not from isolated stills.

    **This has to be a sequence, and that is a measured fact, not taste.**
    `FaceDetector` runs MediaPipe with tracking on, exactly as the production
    pipeline does, so what it reports depends on the frame before. Fed
    isolated stills a fresh detector loses the face entirely at 180 cm; fed
    30 cm jumps it loses it at 120 cm; fed this walk it finds a face in every
    frame from 55 to 185 cm. Production is a 30 fps video stream, so the walk
    is the setup that matches it.

    PLAN.md §12.1 and §12.5 are the same lesson twice already: a measurement
    taken under conditions the production pipeline never sees is a real number
    about the wrong thing.
    """
    from harness.synthetic_camera import FaceComposer
    from misty_agent.perception.face import FaceDetector

    composer = FaceComposer(
        portrait, focal_length=FOCAL_LENGTH, real_face_width_cm=REAL_FACE_WIDTH_CM
    )
    detector = FaceDetector(
        focal_length=FOCAL_LENGTH, real_face_width_cm=REAL_FACE_WIDTH_CM
    )
    start_cm, stop_cm, step_cm = WALK_CM
    wanted = {round(probe, 1) for probe in probes}
    found = {}
    try:
        distance_cm = start_cm
        while distance_cm <= stop_cm:
            reading = detector.detect(composer.frame_at(distance_cm))
            assert reading.has_human, (
                f"no face at {distance_cm}cm during a continuous walk — the "
                f"detector should not lose a subject that moves smoothly"
            )
            if round(distance_cm, 1) in wanted:
                found[round(distance_cm, 1)] = reading.distance_cm
            distance_cm += step_cm
    finally:
        detector.close()

    missing = wanted - set(found)
    assert not missing, f"the walk never passed through {sorted(missing)}"
    return found


def test_the_linearity_probe_spans_enough_range_to_see_the_square():
    """Guards the probe distances against being quietly narrowed later.

    If the range shrinks, the linearity test can pass while saying nothing
    about the d-squared relationship, and nobody would see it happen.
    """
    predicted = [d * d / PX_CM for d in LINEARITY_DISTANCES_CM]

    assert max(predicted) / min(predicted) > 8.0


def test_the_real_detector_measures_face_width_linearly(portrait):
    """The claim the closed form actually rests on.

    `FaceDetector` computes distance as k divided by the pixel width between
    the cheeks, so the d-squared sensitivity is exact *provided* a change in
    the rendered face width produces a proportional change in the width
    MediaPipe measures. If the cheek landmarks drifted with scale, the model
    would be wrong, and this is where that would show.

    Recovering an effective measured width per distance and comparing the
    ratios tests exactly that. A constant ratio away from 1 is focal-length
    calibration error — already UNCALIBRATED, and it does not touch the shape.
    A ratio that *varies with distance* is the model breaking.

    **This is the test carrying the load.** Injecting a scale drift of
    0.0008 x width fails it, while the sensitivity test below tolerates
    0.003 x. Do not delete this one as redundant with that one.
    """
    reported = _readings_along_a_walk(portrait, LINEARITY_DISTANCES_CM)
    ratios = {
        distance_cm: distance_cm / reported[distance_cm]
        for distance_cm in LINEARITY_DISTANCES_CM
    }

    spread = max(ratios.values()) / min(ratios.values())
    assert spread == pytest.approx(1.0, abs=LINEARITY_TOLERANCE), (
        f"the detector's width scale drifts with distance: {ratios}. The "
        f"closed-form noise model assumes it does not."
    )


def test_the_closed_form_matches_what_the_real_detector_does(portrait):
    """The number itself, at two widely separated pairs.

    This is a Measurement, not a Sweep — real pixels, real MediaPipe — so
    unlike the envelope it carries a threshold (PLAN.md §14.2).

    **What it can and cannot catch.** Both sides of the comparison divide by
    the same `PX_CM`, so a calibration constant that is wrong in *both* the
    model and the detector cancels and this test stays green — which is the
    honest situation, since the two genuinely share one configuration. It
    fails on a detector scale error of 13 % or more, and it is blind to shape
    drift below 0.003 x width. The linearity test above is the sensitive one;
    this one pins the number.
    """
    probes = sorted({d for pair in SENSITIVITY_PAIRS for d in pair})
    reported = _readings_along_a_walk(portrait, probes)

    for near_cm, far_cm in SENSITIVITY_PAIRS:
        width_change_px = PX_CM / far_cm - PX_CM / near_cm
        measured = (reported[far_cm] - reported[near_cm]) / width_change_px
        predicted = -near_cm * far_cm / PX_CM

        assert measured == pytest.approx(predicted, rel=SENSITIVITY_TOLERANCE), (
            f"between {near_cm}cm and {far_cm}cm the detector moved "
            f"{measured:.3f} cm per pixel of face width; the model predicts "
            f"{predicted:.3f}"
        )


# ---------------------------------------------------------------------------
# Direction reversals
#
# Reversal is noise's characteristic failure and neither existing axis can see
# it: a controller that chatters at the edge of the arrival band breaches no
# floor and can still report `arrived`, so `inside_safety_floor` and
# `converged` both call it a success.
#
# The counter therefore has to be proved against a run that definitely
# reverses, or it is a diagnostic that has never seen its target — M4 #07's
# lesson, and the reason ticket 07 exists at all.
# ---------------------------------------------------------------------------

#: Travel multipliers that break the conditional calibration assumption. The
#: configured `max_actual_motion_multiplier` is 2.0; at 3x the robot goes half
#: as far again as the guarantee covers, drives past the person, and has to
#: come back.
#:
#: Ticket 04 predicted transport lag alone would force this. **It does not**,
#: and that is a result rather than a missing test: see
#: `test_lag_alone_does_not_make_the_controller_reverse` below.
BEYOND_ASSUMPTION_MULTIPLIERS = (3.0, 4.0)

def test_breaking_the_calibration_assumption_makes_the_controller_reverse():
    """The counter, shown the thing it exists to count.

    3x is chosen for being unambiguous rather than marginal — the robot
    overshoots the person outright. Pinning where reversal *begins* would be a
    threshold on a swept unknown, which PLAN.md §14.2 forbids.
    """
    outcome = simulate_approach(transport_lag_s=0.0, speed_error=3.0)

    assert outcome.direction_reversals >= 1


#: The multiplier the conditional guarantee is actually stated at. Not a
#: range: reversal turns out **not** to be monotone in this parameter, so
#: "inside the assumption" is not one behaviour to assert about.
CONFIGURED_MULTIPLIER = 2.0


def test_at_the_configured_multiplier_the_controller_stays_monotone():
    """The negative control, and a result in its own right.

    Without it a counter wired to a constant would satisfy the test above. At
    the multiplier the conditional guarantee is stated at, the controller
    approaches monotonically through every swept lag.

    Note what this does **not** say. Two seconds of lag at this multiplier
    ends with the robot 9.9 cm past the person and still reporting `arrived`
    — no reversal at all. A clean reversal count is not a safety result; the
    two axes are independent, which is the whole reason for counting this one
    separately.
    """
    for lag_s in (0.0, 0.5, 1.0, 2.0, 3.0):
        outcome = simulate_approach(
            transport_lag_s=lag_s, speed_error=CONFIGURED_MULTIPLIER
        )
        assert outcome.direction_reversals == 0, (
            f"reversed at the configured {CONFIGURED_MULTIPLIER}x travel and "
            f"{lag_s}s of lag"
        )


def test_reversal_is_not_monotone_in_the_travel_multiplier():
    """A counterexample worth keeping, found while writing the test above.

    The obvious claim — "inside the calibration assumption it never reverses"
    — is false. At 1.5x travel with two seconds of lag the controller
    reverses twice and times out 7.2 cm from the person, while at 2.0x with
    the same lag it does not reverse at all.

    Less travel than the assumed worst case is not a milder case. Ticket 05's
    grid must not assume it can interpolate between rows, and a coarse grid
    can step over a failing band entirely — M4 #08 already paid for that
    lesson once.
    """
    milder = simulate_approach(transport_lag_s=2.0, speed_error=1.5)
    worst_assumed = simulate_approach(
        transport_lag_s=2.0, speed_error=CONFIGURED_MULTIPLIER
    )

    assert milder.direction_reversals > worst_assumed.direction_reversals == 0


def test_lag_alone_does_not_make_the_controller_reverse():
    """Records a prediction the ticket got wrong, so it is not re-made.

    Ticket 04 assumed high transport lag would be enough: act on a stale
    reading, overshoot the band, then drive back. It is not. At the configured
    travel multiplier the controller stays monotone through two seconds of
    lag — the arrival band is 24 cm wide and the step bound already reserves
    headroom for 2x travel, so staleness alone does not carry it past the
    person. Only leaving the calibration assumption does.
    """
    for lag_s in (0.5, 1.0, 2.0, 3.0):
        assert simulate_approach(transport_lag_s=lag_s).direction_reversals == 0


def test_a_run_that_never_moved_cannot_have_reversed():
    outcome = simulate_approach(transport_lag_s=0.0, start_cm=60.0)

    assert outcome.steps == 0
    assert outcome.direction_reversals == 0


def test_the_step_cap_survives_the_reversing_regime():
    """Termination is the property PLAN.md §4 calls the system's strongest.

    Chatter burns steps, so this is where a cap would quietly fail if adding
    the counter had disturbed the loop.
    """
    for multiplier in BEYOND_ASSUMPTION_MULTIPLIERS:
        outcome = simulate_approach(transport_lag_s=0.0, speed_error=multiplier)
        assert outcome.steps <= SETTINGS.max_approach_steps
        assert outcome.direction_reversals < outcome.steps


def test_every_swept_row_reports_a_reversal_count():
    for outcome in sweep_transport_lag([0.0, 0.5, 1.0]):
        assert isinstance(outcome.direction_reversals, int)
        assert outcome.direction_reversals >= 0

"""Tests for misty_agent.config.

Two things are being pinned down here:

1. The cross-field validators reject configurations in which the arrival band
   overlaps the safety floor. That relationship is the one thing standing
   between "converges to a social distance" and "declares success at a
   distance it is forbidden to occupy".

2. Field-level range constraints hold.

The reachability analysis that used to live here moved with its subject to
``tests/test_step_policy.py``.
"""

import pytest
from pydantic import ValidationError

from misty_agent.config import Settings


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_defaults_load():
    s = Settings()
    assert s.target_distance_cm == 60.0
    assert s.distance_tolerance_cm == 12.0
    assert s.min_safe_distance_cm == 45.0
    assert s.max_actual_motion_multiplier == 2.0
    assert s.max_approach_steps == 8
    assert s.approach_reading_timeout_s == 2.0
    assert s.approach_timeout_s == 30.0
    assert s.cue_queue_capacity == 3
    assert s.cue_freshness_s == 5.0


def test_settings_are_frozen():
    s = Settings()
    with pytest.raises(ValidationError):
        s.target_distance_cm = 99.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MISTY_TARGET_DISTANCE_CM", "80")
    monkeypatch.setenv("MISTY_ROBOT_IP", "10.0.0.5")
    s = Settings(_env_file=None)
    assert s.target_distance_cm == 80.0
    assert s.robot_ip == "10.0.0.5"


# ---------------------------------------------------------------------------
# Cross-field validators
# ---------------------------------------------------------------------------

def test_arrival_band_must_clear_the_safety_floor():
    # 60 - 20 = 40, which is inside the 45 cm floor: the loop could report
    # "arrived" while standing closer than it is ever allowed to be.
    with pytest.raises(ValidationError, match="arrival band"):
        Settings(distance_tolerance_cm=20.0)


def test_arrival_band_exactly_on_the_floor_is_rejected():
    # 60 - 15 == 45 exactly. Touching the floor is not clearing it.
    with pytest.raises(ValidationError, match="arrival band"):
        Settings(distance_tolerance_cm=15.0)


def test_min_step_must_be_below_max_step():
    with pytest.raises(ValidationError, match="min_step_cm"):
        Settings(min_step_cm=40.0, max_step_cm=35.0)


def test_fold_size_cannot_exceed_window():
    with pytest.raises(ValidationError, match="memory_fold_size"):
        Settings(memory_window=4, memory_fold_size=10)


@pytest.mark.parametrize(
    "field, value",
    [
        ("drive_percent", 0),
        ("drive_percent", 101),
        ("approach_gain", 0.0),
        ("approach_gain", 1.5),
        ("max_approach_steps", 0),
        ("approach_reading_timeout_s", 0.0),
        ("approach_timeout_s", 0.0),
        ("cm_per_sec_at_percent", 0.0),
        ("max_actual_motion_multiplier", 0.0),
        ("focal_length", -1.0),
        ("sensor_transport_lag_s", -0.1),
        ("cue_queue_capacity", 0),
        ("cue_freshness_s", 0.0),
    ],
)
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_sensor_transport_lag_may_be_zero():
    # Zero is the honest default: it is not a measurement, it is "unmodelled".
    assert Settings(sensor_transport_lag_s=0.0).sensor_transport_lag_s == 0.0


def test_a_look_around_scan_cannot_be_configured_not_to_settle():
    """Zero is not a shorter pause, it is no pause.

    `look_around` issues MoveHead without a velocity or duration, so the only
    thing making the head arrive before the next command is this wait. A
    settle of 0 turns the scan into four commands the robot never finishes,
    and the last one wins.
    """
    with pytest.raises(ValidationError):
        Settings(look_around_settle_s=0.0)


def test_the_speaking_rate_cannot_be_zero():
    """Zero words per second is a division by zero inside the estimate, and
    the estimate is what ticket 10's suppression window is opened on."""
    with pytest.raises(ValidationError):
        Settings(speech_words_per_second=0.0)


def test_the_speech_estimate_cap_cannot_be_zero():
    """A cap of zero makes every utterance estimate to nothing, so the window
    would close and reopen before Misty made a sound."""
    with pytest.raises(ValidationError):
        Settings(speech_estimate_cap_s=0.0)


def test_the_cjk_speaking_rate_cannot_be_zero():
    """Zero characters per second is a division by zero inside the speech
    estimate, and that estimate is what the TTS suppression window is opened
    on — so the failure would land on the path that stops Misty transcribing
    herself."""
    with pytest.raises(ValidationError):
        Settings(speech_cjk_chars_per_second=0.0)

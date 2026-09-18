"""Single source of truth for every tunable in the system.

Values are read from environment variables (prefix ``MISTY_``) or a ``.env``
file, falling back to the defaults declared here. See ``.env.example``.

Two groups of values deserve different levels of trust:

*Calibration parameters* describe the physical robot. They CANNOT be measured
without hardware, and no hardware is available to this project (see PLAN.md
§1). Every such field is marked ``UNCALIBRATED`` in its description and must be
treated as an assumption, not a measurement. The control law is designed to
tolerate large errors in them; the replay harness sweeps them to show how large.

*Control-law parameters* are pure software. Their correctness is provable from
the code, and the cross-field validators at the bottom of this module encode
the relationships that must hold between them.

This module holds data and its invariants, nothing else. The control law that
consumes these values — and the analysis of which of its branches are reachable
— lives in ``misty_agent.control.step_policy``.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MISTY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ------------------------------------------------------------------
    # Robot connection
    # ------------------------------------------------------------------
    robot_ip: str = Field(
        default="192.168.1.237",
        description="Misty II address on the local network.",
    )

    # ------------------------------------------------------------------
    # Drivers — audio-video stream
    # ------------------------------------------------------------------
    av_stream_port: int = Field(
        default=1935, gt=0, le=65535,
        description="Port Misty serves RTSP on; both audio and video use it.",
    )
    av_stream_width: int = Field(default=640, gt=0)
    av_stream_height: int = Field(default=480, gt=0)
    av_reset_settle_s: float = Field(
        default=2.0, ge=0.0,
        description=(
            "Pause after tearing down a previous AV session before enabling a "
            "new one. UNCALIBRATED: how long Misty actually needs is unknown."
        ),
    )
    camera_rotate_degrees: int = Field(
        default=90,
        description=(
            "Clockwise rotation applied to each frame to put the picture "
            "upright. Must be 0, 90, 180 or 270."
        ),
    )
    video_producer_pause_s: float = Field(
        default=0.01, ge=0.0,
        description=(
            "Sleep between frame reads. Inherited from the original reader; "
            "it slows but does not prevent the backlog of PLAN.md defect A1."
        ),
    )

    # ------------------------------------------------------------------
    # Drivers — voice activity detection
    # ------------------------------------------------------------------
    audio_sample_rate_hz: int = Field(
        default=44100, gt=0,
        description="Sample rate Misty's RTSP audio arrives at. UNCALIBRATED.",
    )
    silence_threshold_db: float = Field(
        default=-40.0,
        description="RMS level below which a block of audio counts as silence.",
    )
    silence_duration_s: float = Field(
        default=0.5, gt=0.0,
        description=(
            "Silence that ends one utterance. Distinct from "
            "silence_timeout_s, which ends a whole multi-utterance turn."
        ),
    )
    min_utterance_s: float = Field(
        default=0.3, gt=0.0,
        description="Utterances shorter than this are discarded unheard.",
    )
    audio_preroll_s: float = Field(
        default=0.3, ge=0.0,
        description=(
            "Audio kept from just before speech starts, so the first phoneme "
            "is not clipped. Bounds what an idle robot buffers."
        ),
    )
    max_utterance_s: float = Field(
        default=8.0,
        gt=0.0,
        description=(
            "Hard cap for one captured utterance, so continuous sound cannot "
            "grow an audio buffer without bound."
        ),
    )
    audio_block_queue_capacity: int = Field(
        default=64,
        gt=0,
        description="Maximum decoded PCM blocks waiting for local VAD.",
    )
    audio_segment_queue_capacity: int = Field(
        default=3,
        gt=0,
        description=(
            "Maximum VAD-completed segments waiting for the Attention Loop."
        ),
    )

    # ------------------------------------------------------------------
    # Drivers — speech recognition
    # ------------------------------------------------------------------
    asr_model: str = Field(
        default="gpt-4o-mini-transcribe",
        description="Hosted transcription model, replacing local Whisper.",
    )
    asr_language: str = Field(
        default="en",
        description="ISO-639-1 hint for the transcriber.",
    )
    asr_ignored_phrases: tuple[str, ...] = Field(
        default=("thank you", "thanks", "thank"),
        description=(
            "Transcripts containing any of these are dropped. A workaround "
            "for local Whisper hallucinating politeness over near-silence; it "
            "also deafens the robot to a real 'thanks', so it is worth "
            "re-measuring against the hosted model and emptying."
        ),
    )
    asr_timeout_s: float = Field(
        default=15.0,
        gt=0.0,
        description="Maximum hosted transcription round-trip for one utterance.",
    )
    wake_minimum_confidence: float = Field(
        default=0.78,
        gt=0.0,
        le=1.0,
        description=(
            "Minimum local PocketSphinx grammar score for Hey/Hi Misty. "
            "Verified only with synthetic fixtures; real-room calibration is "
            "hardware-unverified."
        ),
    )

    # ------------------------------------------------------------------
    # Drivers — events
    # ------------------------------------------------------------------
    event_ws_ping_timeout_s: float = Field(
        default=10.0, gt=0.0,
        description="Websocket ping timeout for Misty's /pubsub subscriptions.",
    )

    # ------------------------------------------------------------------
    # Language models
    # ------------------------------------------------------------------
    llm_model: str = Field(
        default="gpt-4o",
        description="Decision and vision model driving the ReAct loop.",
    )
    memory_model: str = Field(
        default="gpt-4o-mini",
        description="Cheaper model used for summarization and fact extraction.",
    )
    llm_temperature: float = Field(
        default=0.5, ge=0.0, le=2.0,
        description="Sampling temperature for the decision call.",
    )
    memory_summary_temperature: float = Field(
        default=0.2, ge=0.0, le=2.0,
        description="Summarization tolerates a little variation.",
    )
    memory_fact_temperature: float = Field(
        default=0.0, ge=0.0, le=2.0,
        description="Fact extraction must not invent; keep it deterministic.",
    )

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------
    memory_file: str = Field(default="misty_memory.json")
    memory_window: int = Field(
        default=10, gt=0,
        description="Turns kept verbatim before folding into the summary.",
    )
    memory_fold_size: int = Field(
        default=4, gt=0,
        description="Oldest turns folded into the rolling summary at once.",
    )

    # ------------------------------------------------------------------
    # Locomotion — CALIBRATION (physical, unmeasurable without hardware)
    # ------------------------------------------------------------------
    drive_percent: int = Field(
        default=20, gt=0, le=100,
        description=(
            "Drive speed as a PERCENT of max speed, not a physical unit. "
            "UNCALIBRATED: the motor deadband is unknown — the robot may not "
            "move at all below some threshold."
        ),
    )
    cm_per_sec_at_percent: float = Field(
        default=22.0, gt=0.0,
        description=(
            "Travel speed (cm/s) at drive_percent. UNCALIBRATED. To measure: "
            "drive_time(linearVelocity=drive_percent, angularVelocity=0, "
            "timeMs=2000), measure the distance travelled, divide by 2. "
            "The closed loop adapts within max_actual_motion_multiplier; "
            "behaviour beyond that separate bound is unknown."
        ),
    )
    max_actual_motion_multiplier: float = Field(
        default=2.0,
        gt=0.0,
        description=(
            "Upper bound on the maximum monotone distance travelled during "
            "one drive command, relative to its commanded distance. "
            "UNCALIBRATED: the default is a simulation assumption covering "
            "the 2.0x M4 counterexample, not a hardware measurement. "
            "Behaviour beyond this multiplier is unknown."
        ),
    )

    turn_percent: int = Field(
        default=20, gt=0, le=100,
        description=(
            "Angular drive as a PERCENT of max, not a physical unit. "
            "UNCALIBRATED, like drive_percent: the motor deadband is unknown."
        ),
    )
    deg_per_sec_at_percent: float = Field(
        default=45.0, gt=0.0,
        description=(
            "Rotation rate (deg/s) at turn_percent. UNCALIBRATED: a simulation "
            "constant, never measured on a Misty II. To measure: "
            "drive_time(linearVelocity=0, angularVelocity=turn_percent, "
            "timeMs=2000), measure the angle turned, divide by 2."
        ),
    )

    # ------------------------------------------------------------------
    # Locomotion — CONTROL LAW (pure software, provable)
    # ------------------------------------------------------------------
    target_distance_cm: float = Field(
        default=60.0, gt=0.0,
        description="Social interaction distance the loop converges to.",
    )
    distance_tolerance_cm: float = Field(
        default=12.0, gt=0.0,
        description="Half-width of the arrival band around target_distance_cm.",
    )
    min_safe_distance_cm: float = Field(
        default=45.0, gt=0.0,
        description="Forward motion may never bring the robot closer than this.",
    )
    max_step_cm: float = Field(default=35.0, gt=0.0)
    min_step_cm: float = Field(
        default=8.0, gt=0.0,
        description=(
            "Preferred lower bound on a commanded step. The arrival-band "
            "safety cap takes precedence, so this value cannot force a step "
            "through the band."
        ),
    )
    approach_gain: float = Field(
        default=0.7, gt=0.0, le=1.0,
        description=(
            "Fraction of the remaining error preferred per step, before the "
            "shared arrival-band and conditional safety bounds are applied."
        ),
    )
    max_approach_steps: int = Field(
        default=8, gt=0,
        description="Hard iteration cap. Guarantees every episode terminates.",
    )
    approach_reading_timeout_s: float = Field(
        default=2.0, gt=0.0,
        description=(
            "Maximum wait for enough fresh distance readings at startup or "
            "after a movement step."
        ),
    )
    approach_timeout_s: float = Field(
        default=30.0, gt=0.0,
        description=(
            "Whole-call deadline for approach, including perception waits, "
            "drive adapter responses, commanded motion time, and settling."
        ),
    )
    back_up_step_cm: float = Field(default=20.0, gt=0.0)
    hazard_max_age_s: float = Field(
        default=1.0, gt=0.0,
        description=(
            "Oldest hazard reading a movement checkpoint accepts. Older or "
            "missing readings stop the base. SIMULATED design value; no hazard "
            "signal has been read from a Misty II."
        ),
    )
    movement_poll_s: float = Field(
        default=0.05, gt=0.0, le=1.0,
        description=(
            "How often a commanded motion is interrupted to re-check stop and "
            "hazard state. SIMULATED design value."
        ),
    )
    align_tolerance_deg: float = Field(
        default=10.0, gt=0.0, lt=90.0,
        description=(
            "Bearing (degrees, target relative to the chassis heading) within "
            "which the base counts as facing the person. SIMULATED design "
            "value; no camera bearing has been measured on hardware."
        ),
    )
    max_turn_deg: float = Field(
        default=30.0, gt=0.0, le=180.0,
        description="Largest single chassis turn per Step. SIMULATED design value.",
    )
    max_align_steps: int = Field(
        default=6, gt=0,
        description="Turns allowed before alignment is reported failed.",
    )
    post_step_settle_s: float = Field(
        default=0.8, ge=0.0,
        description=(
            "Extra wait after a drive step for the motion to finish and fresh "
            "frames to arrive. UNCALIBRATED: the real behaviour of issuing a "
            "command while drive_time is still running is unknown."
        ),
    )
    post_backup_settle_s: float = Field(default=0.3, ge=0.0)

    # ------------------------------------------------------------------
    # Expression (the seven direct Tools, PLAN.md §15.2)
    # ------------------------------------------------------------------
    speech_words_per_second: float = Field(
        default=2.2, gt=0.0,
        description=(
            "Speaking rate the utterance-length estimate assumes. "
            "UNCALIBRATED: Misty's TTS returns no timing at all (PLAN.md "
            "§15.4), so this is the rate the old main script hard-coded, "
            "moved here rather than left posing as a fact. It also assumes "
            "whitespace-separated words, which CJK text does not have — see "
            "PLAN.md §15.13."
        ),
    )
    speech_cjk_chars_per_second: float = Field(
        default=5.0, gt=0.0,
        description=(
            "Speaking rate for Chinese, Japanese and Korean, which have no "
            "spaces to count words with. UNCALIBRATED, like every other "
            "figure here: Misty's TTS returns no timing (PLAN.md §15.4). "
            "The word rate cannot stand in — a whole Chinese sentence is one "
            "whitespace token, so counting words under-reads it by several "
            "times over (PLAN.md §15.28)."
        ),
    )
    speech_overhead_s: float = Field(
        default=0.5, ge=0.0,
        description="Fixed start-up added to the estimate. UNCALIBRATED.",
    )
    speech_estimate_cap_s: float = Field(
        default=12.0, gt=0.0,
        description=(
            "Longest the estimate may return, so a bad estimate cannot hold "
            "ticket 10's suppression window shut indefinitely. UNCALIBRATED."
        ),
    )
    look_around_settle_s: float = Field(
        default=0.6, gt=0.0,
        description=(
            "Pause at each position of a `look_around` scan, so the head "
            "arrives and fresh frames come back before the next command. "
            "UNCALIBRATED: MoveHead is issued without a velocity or duration, "
            "so how long Misty actually takes to get there is unknown."
        ),
    )

    # ------------------------------------------------------------------
    # Perception
    # ------------------------------------------------------------------
    focal_length: float = Field(
        default=650.0, gt=0.0,
        description=(
            "Camera focal constant for the pixel-width distance estimate. "
            "UNCALIBRATED. To measure: stand at exactly 100 cm and scale by "
            "actual_cm / reported_cm."
        ),
    )
    real_face_width_cm: float = Field(
        default=15.0, gt=0.0,
        description="Assumed average human face width.",
    )
    distance_sample_window: int = Field(
        default=9, gt=0,
        description="Number of recent distance samples the median is taken over.",
    )
    distance_max_age_s: float = Field(
        default=2.0, gt=0.0,
        description=(
            "Maximum process-local age of a distance reading, measured from "
            "frame ingress to decision time. This excludes the UNCALIBRATED "
            "camera-to-process transport lag."
        ),
    )
    sensor_transport_lag_s: float = Field(
        default=0.0, ge=0.0,
        description=(
            "Latency from camera exposure to the frame arriving in this "
            "process (encode + RTSP over WiFi). UNCALIBRATED and unmeasurable "
            "without hardware. The replay harness injects this value to sweep "
            "the control law's robustness envelope; it is NOT a measurement."
        ),
    )

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------
    listen_timeout_s: float = Field(
        default=5.0, gt=0, le=30,
        description="Bound for an explicit listen Tool, including any hosted transcription.",
    )
    silence_timeout_s: float = Field(
        default=4.0, gt=0.0,
        description=(
            "Silence that ends a whole conversational turn, after which the "
            "collected utterances go to the agent. Distinct from "
            "silence_duration_s, which ends a single utterance inside a turn."
        ),
    )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    trigger_cooldown_s: float = Field(
        default=3.0, gt=0.0,
        description=(
            "Minimum gap between two gaze triggers, so one sustained look "
            "does not fire an episode every frame."
        ),
    )
    cue_queue_capacity: int = Field(
        default=3,
        gt=0,
        description=(
            "Maximum Interaction Cues retained while an Episode is active. "
            "Higher-priority arrivals may displace lower-priority cues, but "
            "the queue never grows beyond this bound."
        ),
    )
    cue_freshness_s: float = Field(
        default=5.0,
        gt=0.0,
        description=(
            "Default time an Interaction Cue remains eligible to open an "
            "Episode; an input may declare a shorter evidence-specific bound."
        ),
    )

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------
    max_turns_per_episode: int = Field(
        default=12, gt=0,
        description=(
            "Hard cap on model Turns in one Episode. Preserves the property "
            "that every Episode provably returns to idle. Named for Turns, "
            "not Steps: a Turn is one model decision, a Step is one drive "
            "command (CONTEXT.md). Twelve is the social-runtime spec's "
            "initial value, not a hardware measurement; revise it from "
            "Journal and replay evidence."
        ),
    )

    # ------------------------------------------------------------------
    # Cross-field constraints
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _check_control_law(self) -> "Settings":
        # The arrival band must clear the safety floor. If it does not, the
        # loop can declare "arrived" at a distance it is forbidden to occupy.
        arrival_floor = self.target_distance_cm - self.distance_tolerance_cm
        if arrival_floor <= self.min_safe_distance_cm:
            raise ValueError(
                f"arrival band reaches {arrival_floor:.1f}cm, which is not "
                f"outside min_safe_distance_cm={self.min_safe_distance_cm}cm. "
                f"Require target_distance_cm - distance_tolerance_cm > "
                f"min_safe_distance_cm."
            )

        if self.min_step_cm >= self.max_step_cm:
            raise ValueError(
                f"min_step_cm={self.min_step_cm} must be < "
                f"max_step_cm={self.max_step_cm}."
            )

        if self.camera_rotate_degrees not in (0, 90, 180, 270):
            raise ValueError(
                f"camera_rotate_degrees={self.camera_rotate_degrees} must be "
                f"one of 0, 90, 180, 270."
            )

        if self.silence_duration_s >= self.silence_timeout_s:
            raise ValueError(
                f"silence_duration_s={self.silence_duration_s} must be < "
                f"silence_timeout_s={self.silence_timeout_s}; an utterance has "
                f"to end before the turn containing it does."
            )

        if self.memory_fold_size > self.memory_window:
            raise ValueError(
                f"memory_fold_size={self.memory_fold_size} cannot exceed "
                f"memory_window={self.memory_window}."
            )

        return self

settings = Settings()

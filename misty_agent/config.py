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
            "The closed loop tolerates large errors here; calibration only "
            "reduces the number of steps."
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
            "Lower bound on a commanded step. Currently unreachable — see "
            "PLAN.md defect C: abs(delta) > distance_tolerance_cm implies "
            "abs(delta) * approach_gain > min_step_cm at the default values."
        ),
    )
    approach_gain: float = Field(
        default=0.7, gt=0.0, le=1.0,
        description=(
            "Fraction of the remaining error commanded per step. This — not "
            "min_safe_distance_cm — is what actually prevents collisions at "
            "the default values (PLAN.md defect B)."
        ),
    )
    max_approach_steps: int = Field(
        default=8, gt=0,
        description="Hard iteration cap. Guarantees every episode terminates.",
    )
    back_up_step_cm: float = Field(default=20.0, gt=0.0)
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
            "Distance samples older than this are discarded. NOTE: until "
            "PLAN.md defect A2 is fixed this filters on PROCESSING time, not "
            "CAPTURE time, and therefore does not do what its name says."
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
    silence_timeout_s: float = Field(
        default=4.0, gt=0.0,
        description="Silence that ends an utterance and flushes it to the ASR.",
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

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------
    max_react_steps: int = Field(
        default=5, gt=0,
        description=(
            "Hard cap on LLM turns per episode. Preserves the property that "
            "every episode provably returns to IDLE. The default is a starting "
            "guess to be revised from the event stream's measured latency."
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

        if self.memory_fold_size > self.memory_window:
            raise ValueError(
                f"memory_fold_size={self.memory_fold_size} cannot exceed "
                f"memory_window={self.memory_window}."
            )

        return self

settings = Settings()

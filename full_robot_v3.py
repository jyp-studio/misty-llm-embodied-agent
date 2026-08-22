# -*- coding: utf-8 -*-
"""
full_robot_v3.py — Main entry point for the Misty embodied agent.

Architecture (finite-state control loop: IDLE -> PERCEIVE -> THINK -> ACT -> IDLE):

  Perception  misty_agent.perception.face (gaze trigger, distance) + a hosted
              transcriber + GPT-4o vision for scene description. The face mesh
              itself has moved into the package; what is left here is the
              buffering and median filtering, which moves next (M4 ticket 03).
              M5 is what then FIXES the timing defects in it — see PLAN.md §5.
  Plan        A single structured LLM call. Conversation memory (short-term
              window + rolling summary + persisted long-term facts) is injected
              into context. The LLM outputs high-level intent only — never
              physical parameters.
  Action      Deterministic executor (expression / gesture / speech) and a
              closed-loop locomotion controller (approach_user).

Design notes:
  - Every episode is bounded: step limits, round caps and timeouts guarantee
    the system always returns to IDLE.
  - Misty's drive velocity is a PERCENTAGE of max speed (-100..100), not a
    physical unit. Locomotion therefore uses small closed-loop steps with
    live re-measurement instead of open-loop "velocity x time" commands.
"""

import json
import time
import os
import threading
import queue
import base64
import statistics
import _thread  # used to raise KeyboardInterrupt in the main thread (foot-bumper e-stop)
from typing import Optional
from dataclasses import dataclass
from collections import deque

import cv2

# ==========================================
# 0. Dependencies and configuration
# ==========================================

# PyAV compatibility shim
try:
    import av
    if not hasattr(av, "AVError"):
        av.AVError = getattr(av, "FFmpegError", Exception)
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    print("❌ Missing dependency: pip install openai")
    raise SystemExit(1)

from misty_agent.drivers import (
    AudioStream,
    AvSession,
    EventStream,
    RobotCommands,
    RtspVideoStream,
    VideoSource,
    event_condition,
)
from misty_agent.fakes import RecordingCommands
from misty_agent.perception.asr import OpenAITranscriber
from misty_agent.perception.face import FaceDetector

# Set MISTY_MOCK=1 to run the whole pipeline with no robot on the network:
# commands are recorded instead of sent. The sensor streams still try to open
# RTSP and simply deliver nothing, which is the honest simulation of a robot
# that is not there. The replay harness (M4) is what feeds them real frames.
MOCK_MODE = os.environ.get("MISTY_MOCK", "").strip() not in ("", "0", "false")


def load_api_key() -> str:
    """
    API key resolution order: OPENAI_API_KEY env var -> OAI_CONFIG_LIST.json
    -> interactive prompt. Never hard-code keys in source files.
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        with open("OAI_CONFIG_LIST.json", "r") as f:
            cfg = json.load(f)
            if isinstance(cfg, list) and cfg and cfg[0].get("api_key"):
                return cfg[0]["api_key"]
    except Exception:
        pass
    return input("OpenAI API Key: ").strip()


# Every tunable lives in misty_agent.config — one source of truth, validated
# at load time. The names below are kept as module-level aliases so the rest of
# this file reads unchanged; they disappear as the code moves into the
# misty_agent package.
from misty_agent.config import settings
from misty_agent.control import step_policy
from misty_agent.control.step_policy import plan_step

ROBOT_IP = settings.robot_ip
LLM_MODEL = settings.llm_model
MEMORY_MODEL = settings.memory_model
MEMORY_FILE = settings.memory_file

DRIVE_PERCENT = settings.drive_percent
CM_PER_SEC_AT_PERCENT = settings.cm_per_sec_at_percent
TARGET_DISTANCE_CM = settings.target_distance_cm
DISTANCE_TOLERANCE_CM = settings.distance_tolerance_cm
MIN_SAFE_DISTANCE_CM = settings.min_safe_distance_cm
MAX_STEP_CM = settings.max_step_cm
MAX_APPROACH_STEPS = settings.max_approach_steps


# ==========================================
# 1. Data structures
# ==========================================

@dataclass
class PerceptionData:
    timestamp: float
    visual_description: str
    audio_transcript: str
    trigger_source: str
    user_distance_cm: int


# ==========================================
# 2. Perception
# ==========================================

class MistySmartPerception:
    """
    Key design points:
    - The AV stream is started ONCE per process. Episodes toggle pause()/
      resume() instead of stop/start (restarting the stream repeatedly caused
      'Fail to open video' failures).
    - While paused, watchdogs keep updating the distance estimate (needed by
      the closed-loop controller during motion) but do not enqueue interaction
      events — this also prevents Misty from hearing its own speech.
    - get_distance() returns the median of recent samples (noise rejection).
    """

    def __init__(self, video: VideoSource, audio: AudioStream, api_key: str):
        self.video = video
        self.audio = audio
        self.client = OpenAI(api_key=api_key)
        self.detector = FaceDetector()
        self.latest_frame = None
        self.visual_events = queue.Queue()
        self.audio_events = queue.Queue()
        self.is_running = False
        self.paused = False
        # (timestamp, distance_cm) samples for median filtering
        self._distance_samples = deque(maxlen=settings.distance_sample_window)
        self._dist_lock = threading.Lock()

    # ---------- lifecycle ----------

    def start(self):
        """Called exactly once per process."""
        if self.is_running:
            return
        self._flush()

        print("   (starting AV stream...)")
        try:
            self.video.start()
            self.audio.start()
        except Exception as e:
            print(f"\n❌ [Fatal] Cannot connect to the camera: {e}")
            return

        self.is_running = True
        for target in (self._visual_watchdog, self._audio_watchdog):
            threading.Thread(target=target, daemon=True).start()

    def shutdown(self):
        self.is_running = False
        self.audio.stop()
        self.video.stop()

    def pause(self):
        """Suspend event triggering during actions; distance keeps updating."""
        self.paused = True

    def resume(self):
        """Flush stale events accumulated during the action, then resume."""
        self._flush()
        self.paused = False

    def _flush(self):
        self.video.flush()
        self.audio.flush()
        for q_ in (self.visual_events, self.audio_events):
            try:
                while not q_.empty():
                    q_.get_nowait()
            except Exception:
                pass

    # ---------- filtered distance ----------

    def get_distance(self, max_age_sec: float = settings.distance_max_age_s) -> int:
        """Median of recent (<= max_age_sec old) samples; -1 if unavailable."""
        now = time.time()
        with self._dist_lock:
            recent = [d for (t, d) in self._distance_samples
                      if now - t <= max_age_sec and d > 0]
        if len(recent) < 2:
            return -1
        return int(statistics.median(recent))

    # ---------- background threads ----------

    def _visual_watchdog(self):
        last_trigger_time = 0
        TRIGGER_COOLDOWN = settings.trigger_cooldown_s
        while self.is_running:
            try:
                captured = self.video.read(timeout=1.0)
                if captured is None:
                    continue
                # captured.captured_at is deliberately ignored here: rewiring
                # the age filter onto it is the M5 fix for defect A2, and M4's
                # harness has to measure the current lag first.
                frame = captured.image
                self.latest_frame = frame
                reading = self.detector.detect(frame)

                if reading.has_human and reading.distance_cm > 0:
                    with self._dist_lock:
                        self._distance_samples.append(
                            (time.time(), reading.distance_cm)
                        )

                if self.paused:
                    continue  # during actions: update distance only, no events

                if time.time() - last_trigger_time > TRIGGER_COOLDOWN:
                    if reading.is_looking:
                        d = self.get_distance()
                        print(f"   👁️ [Visual] user is looking, distance {d if d > 0 else '?'}cm")
                        self.visual_events.put(frame)
                        last_trigger_time = time.time()
            except queue.Empty:
                continue
            except Exception:
                continue

    def _audio_watchdog(self):
        while self.is_running:
            try:
                utterance = self.audio.read(timeout=0.2)
                if utterance is None:
                    continue
                if utterance.text.strip() and not self.paused:
                    self.audio_events.put(utterance.text)
            except Exception:
                continue

    # ---------- perception triggers ----------

    def wait_for_perception(self) -> Optional[PerceptionData]:
        print("\n⏳ [Perception] waiting for interaction...")
        while self.is_running:
            if not self.audio_events.empty():
                return self._handle_audio_first_trigger()
            if not self.visual_events.empty():
                return self._handle_visual_first_trigger()
            time.sleep(0.1)
        return None

    def _handle_audio_first_trigger(self):
        print("   🎤 [Audio trigger] listening for the full utterance...")
        buffer = []
        silence_start = time.time()
        SILENCE_TIMEOUT = settings.silence_timeout_s

        while True:
            try:
                while not self.audio_events.empty():
                    text = self.audio_events.get_nowait()
                    if text.strip():
                        print(f"     -> fragment: {text}")
                        buffer.append(text)
                        silence_start = time.time()
            except Exception:
                pass
            if time.time() - silence_start > SILENCE_TIMEOUT:
                break
            time.sleep(0.1)

        final_frame = self.latest_frame
        while not self.visual_events.empty():
            final_frame = self.visual_events.get()
        visual_desc = self._analyze_image(final_frame)
        return PerceptionData(
            time.time(), visual_desc, " ".join(buffer),
            "audio_first", self.get_distance(),
        )

    def _handle_visual_first_trigger(self):
        print("   👋 [Visual trigger] waiting for speech (5s)...")
        trigger_frame = self.visual_events.get()
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if not self.audio_events.empty():
                print("     🗣️ speech detected, switching to audio mode...")
                return self._handle_audio_first_trigger()
            time.sleep(0.1)

        visual_desc = self._analyze_image(trigger_frame)
        return PerceptionData(
            time.time(), visual_desc, "(no speech)",
            "visual_first", self.get_distance(),
        )

    def _analyze_image(self, frame) -> str:
        if frame is None:
            return "No image"
        try:
            _, buffer = cv2.imencode(".jpg", frame)
            b64_img = base64.b64encode(buffer).decode("utf-8")
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": "Describe the person's action/emotion/gesture "
                                 "and the environment in 2-3 short sentences."},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                    ],
                }],
                max_tokens=120,
            )
            return response.choices[0].message.content
        except Exception:
            return "Analysis Error"


# ==========================================
# 3. Memory (short-term window + rolling summary + long-term facts)
# ==========================================

class ConversationMemory:
    """
    Three tiers:
      1. short_term: last WINDOW turns, verbatim (deque)
      2. summary:    rolling summary of older turns (folded on overflow)
      3. facts:      durable user facts (name / preferences / ...), persisted
                     to a JSON file across sessions
    Only text enters memory; raw frames are never stored (token cost).
    """
    WINDOW = settings.memory_window
    FOLD_SIZE = settings.memory_fold_size

    def __init__(self, client: OpenAI, path: str = MEMORY_FILE):
        self.client = client
        self.path = path
        self.short_term = deque()
        self.summary = ""
        self.facts = {}
        self._load()

    # ---------- persistence ----------

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.facts = data.get("facts", {})
                self.summary = data.get("summary", "")
            print(f"   🧠 [Memory] loaded long-term memory: {len(self.facts)} facts")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"   ⚠️ [Memory] load failed: {e}")

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"facts": self.facts, "summary": self.summary},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   ⚠️ [Memory] save failed: {e}")

    # ---------- writing ----------

    def add_turn(self, user_text: str, misty_reply: str):
        self.short_term.append({"user": user_text, "misty": misty_reply})
        if len(self.short_term) > self.WINDOW:
            self._fold_oldest()
        self._extract_facts(user_text, misty_reply)
        self._save()

    def _fold_oldest(self):
        """Compress the oldest turns into the rolling summary (token control)."""
        folded = [self.short_term.popleft()
                  for _ in range(min(self.FOLD_SIZE, len(self.short_term)))]
        text = "\n".join(f"User: {t['user']}\nMisty: {t['misty']}" for t in folded)
        try:
            resp = self.client.chat.completions.create(
                model=MEMORY_MODEL,
                messages=[{
                    "role": "user",
                    "content": "Merge the EXISTING SUMMARY and NEW DIALOGUE into "
                               "one concise summary (<=120 words). Keep names, "
                               "preferences and unresolved topics.\n\n"
                               f"EXISTING SUMMARY:\n{self.summary or '(empty)'}\n\n"
                               f"NEW DIALOGUE:\n{text}",
                }],
                max_tokens=200,
                temperature=settings.memory_summary_temperature,
            )
            self.summary = resp.choices[0].message.content.strip()
        except Exception:
            # on failure, truncate-append: crude but never loses everything
            self.summary = (self.summary + " | " + text)[-1500:]

    def _extract_facts(self, user_text: str, misty_reply: str):
        """Extract durable user facts from the latest turn and merge them."""
        if not user_text or user_text == "(no speech)":
            return
        try:
            resp = self.client.chat.completions.create(
                model=MEMORY_MODEL,
                messages=[{
                    "role": "user",
                    "content": "From this exchange, extract durable facts about "
                               "the user (name, preferences, relationships, "
                               "recurring topics). Respond ONLY with a JSON "
                               "object (may be empty {}). Keys short, values "
                               "short.\n\n"
                               f"Known facts: {json.dumps(self.facts, ensure_ascii=False)}\n"
                               f"User: {user_text}\nMisty: {misty_reply}",
                }],
                max_tokens=150,
                temperature=settings.memory_fact_temperature,
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            new_facts = json.loads(raw)
            if isinstance(new_facts, dict):
                self.facts.update(new_facts)
        except Exception:
            pass  # fact extraction must never break the main loop

    # ---------- reading ----------

    def as_prompt_block(self) -> str:
        lines = []
        if self.facts:
            lines.append("[Long-term facts about the user]")
            for k, v in self.facts.items():
                lines.append(f"- {k}: {v}")
        if self.summary:
            lines.append("\n[Summary of earlier conversation]")
            lines.append(self.summary)
        if self.short_term:
            lines.append("\n[Recent conversation]")
            for t in self.short_term:
                lines.append(f"User: {t['user']}")
                lines.append(f"Misty: {t['misty']}")
        return "\n".join(lines) if lines else "(No previous interaction.)"


# ==========================================
# 4. Plan (single structured call, memory-aware)
# ==========================================

class MistyEmbodiedBrain:
    """
    The LLM makes HIGH-LEVEL decisions only. Movement is one of
    approach / stay / back_up — the closed-loop controller decides how to
    actually drive. The LLM never computes velocities or durations.
    """

    def __init__(self, api_key: str, memory: ConversationMemory):
        self.client = OpenAI(api_key=api_key)
        self.memory = memory

    SYSTEM_PROMPT = """You are Misty, a friendly social robot. Decide how to react to the current perception.

INPUT NOTES:
- The audio transcript comes from noisy speech-to-text. Do NOT take obviously
  wrong words literally; infer intent from context, history and the visual scene.
- Use the conversation memory to stay consistent (remember names, topics,
  what you just did — do not greet someone again if you greeted them last turn).

OUTPUT: respond with ONE JSON object only. No markdown, no extra text.
{
  "thought": "brief reasoning",
  "movement": "approach" | "stay" | "back_up",
  "expression": "happy" | "sad" | "angry" | "surprised" | "love" | "fear" | "neutral",
  "gesture": "wave" | "nod" | "shake_head" | "arms_up" | "arms_open" | "none",
  "speak": "what to say out loud (empty string if nothing)"
}

RULES:
- "movement": choose "approach" only when the user clearly wants you closer or
  is engaging from far away; a low-level controller handles the actual driving,
  so never mention speeds, times or distances.
- Keep "speak" short and conversational (1-3 sentences)."""

    def think(self, perception: PerceptionData) -> dict:
        print("   🧠 [Brain] thinking...")
        dist = (f"{perception.user_distance_cm} cm"
                if perception.user_distance_cm > 0 else "Unknown")
        user_msg = (
            f"[Conversation Memory]\n{self.memory.as_prompt_block()}\n\n"
            f"[Current Perception]\n"
            f"User distance: {dist}\n"
            f"Audio: \"{perception.audio_transcript}\"\n"
            f"Visual: \"{perception.visual_description}\"\n"
        )
        try:
            resp = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=settings.llm_temperature,
                response_format={"type": "json_object"},
            )
            decision = json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"   ⚠️ Brain error: {e}")
            decision = {}

        # Sanitization: fill missing fields, reject illegal values.
        decision.setdefault("thought", "")
        decision.setdefault("speak", "")
        if decision.get("movement") not in ("approach", "stay", "back_up"):
            decision["movement"] = "stay"
        if decision.get("expression") not in (
                "happy", "sad", "angry", "surprised", "love", "fear", "neutral"):
            decision["expression"] = "neutral"
        if decision.get("gesture") not in (
                "wave", "nod", "shake_head", "arms_up", "arms_open", "none"):
            decision["gesture"] = "none"
        return decision


# ==========================================
# 5. Action (deterministic executor + closed-loop locomotion)
# ==========================================

class MistyBodyController:
    def __init__(self, robot_instance: RobotCommands, perception: MistySmartPerception):
        self.misty = robot_instance
        self.perception = perception

    # ---------- expressions ----------

    # Misty ships these images on the robot; DisplayImage takes the filename.
    # https://docs.mistyrobotics.com/misty-ii/robot/misty-ii/#images
    _EXPRESSION_IMAGES = {
        "happy": "e_Joy.jpg",
        "sad": "e_Sadness.jpg",
        "angry": "e_Anger.jpg",
        "surprised": "e_Surprise.jpg",
        "love": "e_Love.jpg",
        "fear": "e_ApprehensionConcerned.jpg",
        "neutral": "e_DefaultContent.jpg",
    }

    def _set_expression(self, name: str):
        image = self._EXPRESSION_IMAGES.get(name)
        if image is None:
            return
        try:
            self.misty.display_image(fileName=image)
        except Exception as e:
            print(f"   ⚠️ expression error: {e}")

    # ---------- gestures (deterministic primitives, with reset) ----------

    def _do_gesture(self, gesture: str):
        try:
            if gesture == "wave":
                for _ in range(2):
                    self.misty.move_arms(leftArmPosition=90, rightArmPosition=-29, duration=0.5)
                    time.sleep(0.5)
                    self.misty.move_arms(leftArmPosition=90, rightArmPosition=30, duration=0.5)
                    time.sleep(0.5)
            elif gesture == "nod":
                for _ in range(2):
                    self.misty.move_head(pitch=-15, yaw=0, roll=0, duration=0.4)
                    time.sleep(0.4)
                    self.misty.move_head(pitch=15, yaw=0, roll=0, duration=0.4)
                    time.sleep(0.4)
            elif gesture == "shake_head":
                for _ in range(2):
                    self.misty.move_head(pitch=0, yaw=-30, roll=0, duration=0.4)
                    time.sleep(0.4)
                    self.misty.move_head(pitch=0, yaw=30, roll=0, duration=0.4)
                    time.sleep(0.4)
            elif gesture == "arms_up":
                self.misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.8)
                time.sleep(1.2)
            elif gesture == "arms_open":
                self.misty.move_arms(leftArmPosition=30, rightArmPosition=30, duration=0.8)
                time.sleep(1.2)
            if gesture != "none":
                # return to neutral pose
                self.misty.move_arms(leftArmPosition=90, rightArmPosition=90, duration=0.5)
                self.misty.move_head(pitch=0, yaw=0, roll=0, duration=0.5)
        except Exception as e:
            print(f"   ⚠️ gesture error: {e}")

    # ---------- closed-loop approach (core fix) ----------

    def approach_user(self, target_cm: int = TARGET_DISTANCE_CM) -> str:
        """
        Small step -> re-measure -> converge. Bounded by MAX_APPROACH_STEPS.
        Replaces the open-loop "LLM computes velocity x time" scheme.
        """
        print(f"   🚶 [Approach] closed-loop approach, target {target_cm}cm")
        for step_i in range(MAX_APPROACH_STEPS):
            d = self.perception.get_distance()
            if d <= 0:
                print("   ⚠️ [Approach] no valid distance sample, stopping")
                self._stop_drive()
                return "lost_user"

            # The step decision lives in misty_agent.control.step_policy so
            # that this loop, the reachability analysis and the tests all read
            # the same implementation.
            outcome = plan_step(d, settings)

            if outcome is step_policy.ARRIVED:
                print(f"   ✅ [Approach] arrived ({d}cm)")
                self._stop_drive()
                return "arrived"

            if outcome is step_policy.INSIDE_FLOOR:
                print(f"   🛑 [Approach] inside safety floor ({d}cm), not advancing")
                self._stop_drive()
                return "arrived"

            step_cm = outcome.commanded_cm
            direction = outcome.direction

            # This is the only place a calibration constant turns a distance
            # into a robot command — and the only place the command can differ
            # from the distance actually travelled (PLAN.md defect B).
            t_ms = int(step_cm / CM_PER_SEC_AT_PERCENT * 1000)

            print(f"   🚗 step {step_i+1}: distance {d}cm, moving "
                  f"{'fwd' if direction > 0 else 'back'} {step_cm:.0f}cm "
                  f"({DRIVE_PERCENT}% x {t_ms}ms)")
            try:
                self.misty.drive_time(
                    linearVelocity=direction * DRIVE_PERCENT,
                    angularVelocity=0,
                    timeMs=t_ms,
                )
            except Exception as e:
                print(f"   ❌ drive_time error: {e}")
                self._stop_drive()
                return "drive_error"

            # Wait for the motion to finish and fresh frames to arrive.
            time.sleep(t_ms / 1000.0 + settings.post_step_settle_s)

        print("   ⏱️ [Approach] step limit reached, stopping")
        self._stop_drive()
        return "timeout"

    def back_up(self):
        """Single small bounded backward step."""
        try:
            t_ms = int(settings.back_up_step_cm / CM_PER_SEC_AT_PERCENT * 1000)
            self.misty.drive_time(linearVelocity=-DRIVE_PERCENT,
                                  angularVelocity=0, timeMs=t_ms)
            time.sleep(t_ms / 1000.0 + settings.post_backup_settle_s)
        except Exception as e:
            print(f"   ⚠️ back_up error: {e}")
        self._stop_drive()

    def _stop_drive(self):
        try:
            self.misty.stop()
        except Exception:
            pass

    # ---------- speech ----------

    def _speak(self, text: str):
        if not text:
            return
        # Rough speech duration. UNCALIBRATED: Misty's TTS gives no timing back,
        # so this is a word-count guess, not a measurement (PLAN.md §8).
        words = max(1, len(text.split()))
        spoken_s = min(12.0, words / 2.2 + 0.5)
        try:
            self.misty.speak(text)
            # Deafen the ASR for the duration so Misty does not transcribe
            # herself, then wait it out so perception does not resume mid-word.
            self.perception.audio.mute_for(spoken_s)
            time.sleep(spoken_s)
        except Exception as e:
            print(f"   ⚠️ speak error: {e}")

    # ---------- neutral pose ----------

    def _return_to_neutral(self):
        """Reset LED, expression and posture — the ACT state always ends here."""
        for call in (
            lambda: self.misty.change_led(red=255, green=255, blue=255),
            lambda: self.misty.display_image(fileName="e_DefaultContent.jpg"),
            lambda: self.misty.move_arms(leftArmPosition=0, rightArmPosition=0, duration=0.5),
            lambda: self.misty.move_head(pitch=0, yaw=0, roll=0, duration=0.5),
        ):
            try:
                call()
            except Exception as e:
                print(f"   ⚠️ reset error: {e}")

    # ---------- main entry ----------

    def execute(self, decision: dict):
        print(f"\n🤖 [Action] {json.dumps(decision, ensure_ascii=False)[:200]}")

        # 1. expression (instant feedback)
        self._set_expression(decision["expression"])

        # 2. movement (closed-loop, deterministic)
        if decision["movement"] == "approach":
            self.approach_user()
        elif decision["movement"] == "back_up":
            self.back_up()

        # 3. gesture
        self._do_gesture(decision["gesture"])

        # 4. speech
        self._speak(decision["speak"])

        # 5. return to neutral pose — the ACT state always ends cleanly
        self._return_to_neutral()


# ==========================================
# 6. Main loop (FSM: IDLE -> PERCEIVE -> THINK -> ACT -> IDLE)
# ==========================================

def register_foot_bumper_stop(events: EventStream):
    """Foot-bumper e-stop: raise KeyboardInterrupt in the main thread."""
    def stop_callback(data):
        is_contacted = False
        sensor_id = "Unknown"
        try:
            if isinstance(data, dict):
                msg = data.get("message", {})
                is_contacted = msg.get("isContacted", False)
                sensor_id = msg.get("sensorId", "Unknown")
        except Exception:
            pass
        if is_contacted:
            print(f"\n🛑 [Foot Button] ({sensor_id}) emergency stop...")
            _thread.interrupt_main()

    print("   🛡️ [System] registering foot-bumper e-stop...")
    try:
        events.subscribe(
            "BumpSensor",
            name="EmergencyFootStop",
            condition=[event_condition("isContacted", "=", True)],
            debounce_ms=1000,
            keep_alive=True,
            on_event=stop_callback,
        )
    except Exception as e:
        print(f"   ⚠️ e-stop registration failed: {e}")


def main():
    key = load_api_key()
    if not key:
        return

    print("🚀 Misty Embodied Agent v3 (FSM + Memory + Closed-loop)")
    if MOCK_MODE:
        print("⚠️ MISTY_MOCK set — commands are recorded, not sent")
        hw = RecordingCommands(ROBOT_IP)
    else:
        hw = RobotCommands(ROBOT_IP)

    # One AV session, shared: Misty publishes a single RTSP stream carrying
    # both the camera and the microphone.
    session = AvSession(hw)
    video = RtspVideoStream(session)
    audio = AudioStream(session, OpenAITranscriber(key))
    events = EventStream(ROBOT_IP)

    register_foot_bumper_stop(events)

    client = OpenAI(api_key=key)
    memory = ConversationMemory(client)
    perception = MistySmartPerception(video, audio, key)
    brain = MistyEmbodiedBrain(key, memory)
    body = MistyBodyController(hw, perception)

    perception.start()  # once per process

    try:
        while True:
            # ---- PERCEIVE ----
            perception.resume()
            try:
                data = perception.wait_for_perception()
            except KeyboardInterrupt:
                print("\n   ⚠️ perception interrupted by e-stop, resetting...")
                body._stop_drive()
                continue
            if data is None:
                break

            perception.pause()  # distance keeps updating; events do not
            dist_str = (f"{data.user_distance_cm}cm"
                        if data.user_distance_cm > 0 else "Unknown")
            print(f"📦 Input: {data.audio_transcript} | Dist: {dist_str}")

            # ---- THINK ----
            decision = brain.think(data)

            # ---- ACT (bounded subroutine; always returns to IDLE) ----
            try:
                body.execute(decision)
            except KeyboardInterrupt:
                print("\n🛑 [Action Interrupted] action stopped by e-stop!")
                body._stop_drive()
                time.sleep(1)

            # ---- memory write-back ----
            user_input = (data.audio_transcript
                          if data.audio_transcript != "(no speech)"
                          else f"(silent; visual: {data.visual_description[:80]})")
            misty_said = decision.get("speak") or f"(action: {decision.get('thought','')[:60]})"
            memory.add_turn(user_input, misty_said)

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n👋 Shutting down")
    finally:
        body._stop_drive()
        perception.shutdown()
        events.close()


if __name__ == "__main__":
    main()

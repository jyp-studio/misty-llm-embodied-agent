# -*- coding: utf-8 -*-
"""
full_robot_v3.py — Main entry point for the Misty embodied agent.

Architecture (finite-state control loop: IDLE -> PERCEIVE -> THINK -> ACT -> IDLE):

  Perception  MediaPipe face mesh (gaze trigger, distance) + Whisper ASR
              + GPT-4o vision for scene description.
  Plan        A single structured LLM call. Conversation memory (short-term
              window + rolling summary + persisted long-term facts) is injected
              into context. The LLM outputs high-level intent only — never
              physical parameters.
  Action      Deterministic executor (expression / gesture / speech) and a
              closed-loop locomotion controller (approach_user). AutoMisty
              multi-agent code generation is invoked only for complex
              expressive tasks (dance, storytelling, ...).

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

# AutoMisty handles only complex expressive tasks; it no longer drives the robot.
from AutoMisty import complex_action

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
    import mediapipe as mp
except ImportError:
    print("❌ Missing dependency: pip install mediapipe")
    raise SystemExit(1)

try:
    from openai import OpenAI
except ImportError:
    print("❌ Missing dependency: pip install openai")
    raise SystemExit(1)

try:
    from CUBS_Misty import Robot
    print("✅ CUBS_Misty imported")
    MOCK_MODE = False
except ImportError:
    print("⚠️ CUBS_Misty not found — running in mock mode")
    MOCK_MODE = True

    class Robot:  # minimal mock for running the pipeline without hardware
        def __init__(self, ip):
            self.ip = ip
            self._stop_event = threading.Event()
            self.frame_queue = queue.Queue()
            self.transcript_queue = queue.Queue()

        def __getattr__(self, name):
            def _mock(*args, **kwargs):
                print(f"  🤖 [Mock] {name}({args}, {kwargs})")
            return _mock


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


ROBOT_IP = "192.168.1.237"
LLM_MODEL = "gpt-4o"          # decision / vision model
MEMORY_MODEL = "gpt-4o-mini"  # cheap model for summarization / fact extraction
MEMORY_FILE = "misty_memory.json"

# --- Locomotion constants (calibrate once on real hardware) ---
# Misty's drive/drive_time linearVelocity is a PERCENT of max speed (-100..100).
DRIVE_PERCENT = 20            # fixed low speed for small, safe steps
CM_PER_SEC_AT_PERCENT = 22.0  # measured speed (cm/s) at DRIVE_PERCENT — CALIBRATE
TARGET_DISTANCE_CM = 60       # social interaction distance
DISTANCE_TOLERANCE_CM = 12    # arrival tolerance
MIN_SAFE_DISTANCE_CM = 45     # never move forward past this floor
MAX_STEP_CM = 35              # maximum distance per step
MAX_APPROACH_STEPS = 8        # hard iteration cap (termination guarantee)


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

class HumanDetector:
    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.FOCAL_LENGTH = 650    # calibrate: new = 650 * actual_cm / reported_cm
        self.REAL_FACE_WIDTH = 15  # average face width in cm

    def analyze_spatial(self, frame) -> dict:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_frame)
        h, w, _ = frame.shape
        info = {"has_human": False, "distance_cm": -1, "is_looking": False}

        if not results.multi_face_landmarks:
            return info

        info["has_human"] = True
        landmarks = results.multi_face_landmarks[0].landmark

        left_x = landmarks[234].x * w
        right_x = landmarks[454].x * w
        pixel_width = abs(right_x - left_x)

        if pixel_width > 0:
            info["distance_cm"] = int(
                (self.FOCAL_LENGTH * self.REAL_FACE_WIDTH) / pixel_width
            )

        nose_x = landmarks[1].x * w
        center_x = (left_x + right_x) / 2
        offset_ratio = abs(nose_x - center_x) / pixel_width
        info["is_looking"] = offset_ratio < 0.25
        return info


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

    def __init__(self, robot_instance: Robot, api_key: str):
        self.robot = robot_instance
        self.client = OpenAI(api_key=api_key)
        self.robot.load_whisper_model()
        self.detector = HumanDetector()
        self.latest_frame = None
        self.visual_events = queue.Queue()
        self.audio_events = queue.Queue()
        self.is_running = False
        self.paused = False
        # (timestamp, distance_cm) samples for median filtering
        self._distance_samples = deque(maxlen=9)
        self._dist_lock = threading.Lock()

    # ---------- lifecycle ----------

    def _force_kill_av_services(self):
        """Reset Misty's AV services over HTTP once, before starting."""
        import requests
        ip = self.robot.ip
        print(f"   ☠️ [System] Resetting Misty AV services ({ip})...")
        try:
            requests.post(f"http://{ip}/api/avstreaming/disable", json={}, timeout=2)
            requests.post(f"http://{ip}/api/audio/recording/stop", json={}, timeout=2)
        except Exception as e:
            print(f"   ⚠️ Cannot reach Misty API: {e}")

    def start(self):
        """Called exactly once per process."""
        if self.is_running:
            return
        if not MOCK_MODE:
            self._force_kill_av_services()
            time.sleep(2.0)

        self.robot._stop_event.clear()
        self._flush()

        print("   (starting AV stream...)")
        try:
            self.robot.start_av_stream()
        except Exception as e:
            print(f"\n❌ [Fatal] Cannot connect to the camera: {e}")
            return

        self.is_running = True
        threads = [
            threading.Thread(target=self.robot._video_reader_thread, daemon=True),
            threading.Thread(target=self.robot._read_audio_stream, daemon=True),
            threading.Thread(target=self.robot._process_audio, daemon=True),
            threading.Thread(target=self._visual_watchdog, daemon=True),
            threading.Thread(target=self._audio_watchdog, daemon=True),
        ]
        for t in threads:
            t.start()

    def shutdown(self):
        self.is_running = False
        self.robot._stop_event.set()
        try:
            self.robot.stop_av_streaming()
        except Exception:
            pass

    def pause(self):
        """Suspend event triggering during actions; distance keeps updating."""
        self.paused = True

    def resume(self):
        """Flush stale events accumulated during the action, then resume."""
        self._flush()
        self.paused = False

    def _flush(self):
        for q_ in (self.robot.frame_queue, self.robot.transcript_queue,
                   self.visual_events, self.audio_events):
            try:
                while not q_.empty():
                    q_.get_nowait()
            except Exception:
                pass

    # ---------- filtered distance ----------

    def get_distance(self, max_age_sec: float = 2.0) -> int:
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
        TRIGGER_COOLDOWN = 3.0
        while self.is_running:
            try:
                frame = self.robot.frame_queue.get(timeout=1.0)
                self.latest_frame = frame
                spatial = self.detector.analyze_spatial(frame)

                if spatial["has_human"] and spatial["distance_cm"] > 0:
                    with self._dist_lock:
                        self._distance_samples.append(
                            (time.time(), spatial["distance_cm"])
                        )

                if self.paused:
                    continue  # during actions: update distance only, no events

                if time.time() - last_trigger_time > TRIGGER_COOLDOWN:
                    if spatial["is_looking"]:
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
                if not self.robot.transcript_queue.empty():
                    _, text = self.robot.transcript_queue.get()
                    if text.strip() and not self.paused:
                        self.audio_events.put(text)
                time.sleep(0.05)
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
        SILENCE_TIMEOUT = 4.0

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
    WINDOW = 10
    FOLD_SIZE = 4  # number of oldest turns folded into the summary at once

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
                temperature=0.2,
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
                temperature=0.0,
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
  "speak": "what to say out loud (empty string if nothing)",
  "complex_task": null
}

RULES:
- "movement": choose "approach" only when the user clearly wants you closer or
  is engaging from far away; a low-level controller handles the actual driving,
  so never mention speeds, times or distances.
- "complex_task": normally null. Set it to a natural-language task description
  ONLY for elaborate performances (dance, telling a full story, reciting a poem
  with choreography). Simple replies must use "speak" instead — complex_task is
  slow and expensive.
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
                temperature=0.5,
                response_format={"type": "json_object"},
            )
            decision = json.loads(resp.choices[0].message.content)
        except Exception as e:
            print(f"   ⚠️ Brain error: {e}")
            decision = {}

        # Sanitization: fill missing fields, reject illegal values.
        decision.setdefault("thought", "")
        decision.setdefault("speak", "")
        decision.setdefault("complex_task", None)
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
    def __init__(self, robot_instance: Robot, perception: MistySmartPerception):
        self.misty = robot_instance
        self.perception = perception

    # ---------- expressions ----------

    _EXPRESSION_MAP = {
        "happy": "emotion_Joy",
        "sad": "emotion_Sadness",
        "angry": "emotion_Anger",
        "surprised": "emotion_Surprise",
        "love": "emotion_Love",
        "fear": "emotion_ApprehensionConcerned",
        "neutral": "emotion_DefaultContent",
    }

    def _set_expression(self, name: str):
        method = getattr(self.misty, self._EXPRESSION_MAP.get(name, ""), None)
        if callable(method):
            try:
                method()
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

            delta = d - target_cm
            if abs(delta) <= DISTANCE_TOLERANCE_CM:
                print(f"   ✅ [Approach] arrived ({d}cm)")
                self._stop_drive()
                return "arrived"

            # At most MAX_STEP_CM per step, and only 70% of the remaining
            # delta, to avoid overshooting on the final step.
            step_cm = max(8.0, min(MAX_STEP_CM, abs(delta) * 0.7))
            direction = 1 if delta > 0 else -1  # too far -> forward; too close -> back

            # The safety floor constrains FORWARD motion only: a forward step
            # may never cross MIN_SAFE. If the user is closer than the target,
            # delta is negative and the normal backward branch opens distance.
            if direction > 0:
                max_forward = d - MIN_SAFE_DISTANCE_CM
                if max_forward <= 0:
                    print(f"   🛑 [Approach] inside safety floor ({d}cm), not advancing")
                    self._stop_drive()
                    return "arrived"
                step_cm = min(step_cm, max_forward)

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
            time.sleep(t_ms / 1000.0 + 0.8)

        print("   ⏱️ [Approach] step limit reached, stopping")
        self._stop_drive()
        return "timeout"

    def back_up(self):
        """Single small bounded backward step."""
        try:
            t_ms = int(20 / CM_PER_SEC_AT_PERCENT * 1000)
            self.misty.drive_time(linearVelocity=-DRIVE_PERCENT,
                                  angularVelocity=0, timeMs=t_ms)
            time.sleep(t_ms / 1000.0 + 0.3)
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
        try:
            self.misty.speak(text)
            # Rough speech-duration wait so perception does not resume while
            # Misty is still talking (echo prevention).
            words = max(1, len(text.split()))
            time.sleep(min(12.0, words / 2.2 + 0.5))
        except Exception as e:
            print(f"   ⚠️ speak error: {e}")

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

        # 5. complex expressive tasks go to AutoMisty (fixed termination,
        #    round caps and timeouts)
        task = decision.get("complex_task")
        if task:
            print(f"   🎭 [AutoMisty] complex task: {task[:80]}")
            try:
                complex_action(task)
            except Exception as e:
                print(f"   ❌ AutoMisty error: {e}")

        # 6. return to neutral pose — the ACT state always ends cleanly
        try:
            self.misty.return_to_normal()
        except Exception:
            pass


# ==========================================
# 6. Main loop (FSM: IDLE -> PERCEIVE -> THINK -> ACT -> IDLE)
# ==========================================

def register_foot_bumper_stop(robot):
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
        robot.register_event(
            event_type="BumpSensor",
            event_name="EmergencyFootStop",
            condition=[{"Property": "isContacted", "Inequality": "=", "Value": True}],
            debounce=1000,
            keep_alive=True,
            callback_function=stop_callback,
        )
    except Exception as e:
        print(f"   ⚠️ e-stop registration failed: {e}")


def main():
    key = load_api_key()
    if not key:
        return

    print("🚀 Misty Embodied Agent v3 (FSM + Memory + Closed-loop)")
    try:
        hw = Robot(ROBOT_IP)
    except Exception as e:
        print(f"❌ Cannot create Robot: {e}")
        return

    register_foot_bumper_stop(hw)

    client = OpenAI(api_key=key)
    memory = ConversationMemory(client)
    perception = MistySmartPerception(hw, key)
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
        try:
            hw.unregister_all_events()
        except Exception:
            pass


if __name__ == "__main__":
    main()

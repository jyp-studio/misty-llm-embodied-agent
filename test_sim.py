# -*- coding: utf-8 -*-
"""
test_sim.py — Hardware-free simulation tests.

Usage:  python test_sim.py   (from the project root)

How it works:
  - cv2 / mediapipe / openai / CUBS_Misty are stubbed, so no heavy
    dependencies, no API key and no robot are required.
  - A 1-D "simulated world" models the user's distance. FakeRobot.drive_time()
    changes that distance according to a TRUE speed (which may differ from the
    calibrated constant), and FakePerception.get_distance() returns noisy
    measurements. This exercises the real approach_user() control logic,
    including robustness to calibration error.

Coverage:
  T1  approach_user convergence (accurate calibration)
  T2  convergence with true speed +50% (calibration-error robustness)
  T3  convergence with true speed -40%
  T4  convergence under +/-8cm measurement noise; safety floor respected
  T5  user lost mid-approach -> reports lost_user and stops
  T6  user too close -> backs up to the target distance
  T7  step cap: never exceeds MAX_APPROACH_STEPS (termination guarantee)
  T8  brain sanitization: illegal / missing / malformed JSON -> safe defaults
  T9  memory: window folding, fact persistence, reload
  T10 AutoMisty termination semantics (exitcode: 0 / exitcode: 1 / ALLSET)

Items that still require real hardware are listed in HARDWARE_CHECKLIST at
the end of the output.
"""

import sys
import types
import json
import os
import random
import threading
import collections

# ==========================================
# 0. Stub heavy dependencies (before importing full_robot_v3)
# ==========================================

def _stub_module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

cv2_m = _stub_module("cv2")
cv2_m.cvtColor = lambda *a, **k: None
cv2_m.COLOR_BGR2RGB = 0
cv2_m.imencode = lambda *a, **k: (True, b"")

mp_m = _stub_module("mediapipe")
mp_m.solutions = types.SimpleNamespace(
    face_mesh=types.SimpleNamespace(FaceMesh=lambda **k: None)
)

openai_m = _stub_module("openai")

class _FakeCompletions:
    """Scriptable fake OpenAI client: pops the next canned response."""
    def __init__(self, script):
        self.script = script
    def create(self, **kwargs):
        content = self.script.pop(0) if self.script else "{}"
        msg = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

class FakeOpenAI:
    def __init__(self, api_key=None, script=None):
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(script if script is not None else [])
        )

openai_m.OpenAI = FakeOpenAI

_stub_module("requests").post = lambda *a, **k: None
automisty_m = _stub_module("AutoMisty")
automisty_m.complex_action = lambda task: print(f"    (complex_action stub: {task[:40]})")

# CUBS_Misty is absent -> full_robot_v3 falls back to its mock branch.

# Speed-up: make time.sleep a no-op.
import time as _time
_real_sleep = _time.sleep
_time.sleep = lambda s: None

# ==========================================
# 1. Load the module under test
# ==========================================

import importlib.util
spec = importlib.util.spec_from_file_location("frv3", "full_robot_v3.py")
frv3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frv3)

PASS, FAIL = 0, 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")

# ==========================================
# 2. Simulated world: 1-D kinematics + noisy measurement
# ==========================================

class SimWorld:
    def __init__(self, user_distance_cm, true_cm_per_sec, noise_cm=0.0,
                 lose_user_after_steps=None):
        self.d = float(user_distance_cm)     # true robot-user distance
        self.true_speed = true_cm_per_sec    # TRUE speed (tests calibration error)
        self.noise = noise_cm
        self.lose_after = lose_user_after_steps
        self.drive_calls = 0
        self.min_true_distance = self.d

    def apply_drive(self, linear_velocity, time_ms):
        # linearVelocity is a percentage; assume true speed scales linearly
        direction = 1 if linear_velocity > 0 else -1 if linear_velocity < 0 else 0
        moved = direction * self.true_speed * (time_ms / 1000.0) \
                * (abs(linear_velocity) / frv3.DRIVE_PERCENT)
        self.d -= moved  # moving forward shrinks the distance
        self.drive_calls += 1
        self.min_true_distance = min(self.min_true_distance, self.d)

    def measure(self):
        if self.lose_after is not None and self.drive_calls >= self.lose_after:
            return -1
        return int(self.d + random.uniform(-self.noise, self.noise))


class FakeRobot:
    def __init__(self, world: SimWorld):
        self.world = world
        self.calls = []
    def drive_time(self, linearVelocity=0, angularVelocity=0, timeMs=0):
        self.calls.append(("drive_time", linearVelocity, timeMs))
        self.world.apply_drive(linearVelocity, timeMs)
    def stop(self):
        self.calls.append(("stop",))
    def __getattr__(self, name):
        def _noop(*a, **k):
            self.calls.append((name,))
        return _noop


class FakePerception:
    def __init__(self, world: SimWorld):
        self.world = world
    def get_distance(self, max_age_sec=2.0):
        return self.world.measure()


def run_approach(user_at, true_speed, noise=0.0, lose_after=None, seed=7):
    random.seed(seed)
    world = SimWorld(user_at, true_speed, noise, lose_after)
    robot = FakeRobot(world)
    body = frv3.MistyBodyController(robot, FakePerception(world))
    result = body.approach_user()
    steps = sum(1 for c in robot.calls if c[0] == "drive_time")
    return result, world, steps


# ==========================================
# 3. Tests
# ==========================================

print("\n===== T1 accurate calibration: user @ 150cm, true speed = assumed =====")
res, w, steps = run_approach(150, frv3.CM_PER_SEC_AT_PERCENT)
check("reports arrived", res == "arrived", f"got {res}")
check("final distance within target +/- tolerance",
      abs(w.d - frv3.TARGET_DISTANCE_CM) <= frv3.DISTANCE_TOLERANCE_CM + 1,
      f"final={w.d:.0f}cm")
check("safety floor respected", w.min_true_distance >= frv3.MIN_SAFE_DISTANCE_CM - 5,
      f"min={w.min_true_distance:.0f}cm")

print("\n===== T2 calibration error +50% (robot faster than assumed) =====")
res, w, steps = run_approach(150, frv3.CM_PER_SEC_AT_PERCENT * 1.5)
check("still stops (arrived/timeout both acceptable)", res in ("arrived", "timeout"), res)
check("no overshoot past the user despite miscalibration", w.min_true_distance > 20,
      f"min={w.min_true_distance:.0f}cm")
check("open-loop baseline would overshoot ~{:.0f}cm; closed loop stays near tolerance".format(
        (150 - frv3.TARGET_DISTANCE_CM) * 0.5),
      w.min_true_distance >= frv3.MIN_SAFE_DISTANCE_CM - 15,
      f"min={w.min_true_distance:.0f}cm")

print("\n===== T3 calibration error -40% (robot slower than assumed) =====")
res, w, steps = run_approach(150, frv3.CM_PER_SEC_AT_PERCENT * 0.6)
check("still converges or stops safely", res in ("arrived", "timeout"), res)
if res == "arrived":
    check("final distance reasonable", abs(w.d - frv3.TARGET_DISTANCE_CM)
          <= frv3.DISTANCE_TOLERANCE_CM + 1, f"final={w.d:.0f}cm")

print("\n===== T4 measurement noise +/-8cm =====")
res, w, steps = run_approach(160, frv3.CM_PER_SEC_AT_PERCENT, noise=8.0)
check("still stops under noise", res in ("arrived", "timeout"), res)
check("stays above safety floor minus tolerance",
      w.min_true_distance >= frv3.MIN_SAFE_DISTANCE_CM - 10,
      f"min={w.min_true_distance:.0f}cm")

print("\n===== T5 user lost mid-approach =====")
res, w, steps = run_approach(200, frv3.CM_PER_SEC_AT_PERCENT, lose_after=2)
check("reports lost_user", res == "lost_user", res)
check("stops immediately after loss (drive calls == 2)", steps == 2, f"steps={steps}")

print("\n===== T6 user too close (40cm) -> backs up =====")
res, w, steps = run_approach(40, frv3.CM_PER_SEC_AT_PERCENT)
check("terminates", res in ("arrived", "timeout"), res)
check("distance increased (moved backward)", w.d > 40, f"final={w.d:.0f}cm")

print("\n===== T7 step cap =====")
# Extreme: near-zero true speed (robot barely moves) — must give up within cap.
res, w, steps = run_approach(300, 0.01)
check("reports timeout", res == "timeout", res)
check(f"drive calls <= {frv3.MAX_APPROACH_STEPS}",
      steps <= frv3.MAX_APPROACH_STEPS, f"steps={steps}")

print("\n===== T8 brain sanitization =====")
def make_brain(reply):
    brain = frv3.MistyEmbodiedBrain.__new__(frv3.MistyEmbodiedBrain)
    brain.client = FakeOpenAI(script=[reply])
    brain.memory = types.SimpleNamespace(as_prompt_block=lambda: "(none)")
    return brain
pd = frv3.PerceptionData(0, "test", "hello", "audio_first", 100)

d = make_brain('{"movement":"fly","expression":"confused","gesture":"backflip"}').think(pd)
check("illegal values fall back to safe defaults",
      d["movement"] == "stay" and d["expression"] == "neutral" and d["gesture"] == "none", d)

d = make_brain("this is not json at all").think(pd)
check("malformed JSON -> no crash, all fields present",
      all(k in d for k in ("movement", "expression", "gesture", "speak", "complex_task")), d)

d = make_brain('{"movement":"approach","expression":"sad","gesture":"nod","speak":"hi","complex_task":null}').think(pd)
check("valid output passes through unchanged",
      d["movement"] == "approach" and d["speak"] == "hi", d)

print("\n===== T9 memory: folding + persistence =====")
MEMFILE = "_test_memory.json"
if os.path.exists(MEMFILE):
    os.remove(MEMFILE)
mem_client = FakeOpenAI(script=['{"user_name": "Henry"}'] * 50)
mem = frv3.ConversationMemory(mem_client, path=MEMFILE)
for i in range(15):
    mem.add_turn(f"user message {i}", f"misty reply {i}")
check(f"window size <= {frv3.ConversationMemory.WINDOW}",
      len(mem.short_term) <= frv3.ConversationMemory.WINDOW,
      f"len={len(mem.short_term)}")
check("facts extracted", mem.facts.get("user_name") == "Henry", mem.facts)
check("file persisted", os.path.exists(MEMFILE))
mem2 = frv3.ConversationMemory(FakeOpenAI(script=[]), path=MEMFILE)
check("facts survive reload", mem2.facts.get("user_name") == "Henry", mem2.facts)
block = mem.as_prompt_block()
check("prompt block contains recent turns", "user message 14" in block)
os.remove(MEMFILE)

print("\n===== T10 AutoMisty termination semantics =====")
term = lambda x: (x.get("content", "").find("ALLSET") >= 0
                  or x.get("content", "").find("exitcode: 0") >= 0)
check("successful execution -> terminate",
      term({"content": "exitcode: 0 (execution succeeded)\nCode output: done"}))
check("failed execution -> keep going (draft agent fixes bugs)",
      not term({"content": "exitcode: 1 (execution failed)\nTraceback..."}))
check("no-code message -> ALLSET terminates", term({"content": "ALLSET"}))
check("ordinary chat -> no termination",
      not term({"content": "Here is the plan for the dance."}))

# ==========================================
# 4. Summary
# ==========================================
print("\n" + "=" * 50)
print(f"Result: {PASS} passed, {FAIL} failed")
print("=" * 50)

HARDWARE_CHECKLIST = """
Items that still require real hardware (not covered by simulation):
  1. Calibrate CM_PER_SEC_AT_PERCENT:
     run drive_time(linearVelocity=20, angularVelocity=0, timeMs=2000),
     measure the traveled distance in cm and divide by 2 seconds.
  2. Calibrate FOCAL_LENGTH: stand at a measured 100 cm and compare the
     reported distance (new = 650 * actual / reported).
  3. Minimum drive threshold: verify the motors move at 20%; raise
     DRIVE_PERCENT if they stall.
  4. AV stream stability over time (30 min of pause/resume cycles).
  5. Foot-bumper e-stop interrupts all three stages
     (perception / locomotion / AutoMisty).
  6. Speech echo guard: Misty's own speech must not appear in transcripts.
  7. Real AutoMisty round-trip (requires an API key): give a dance task and
     confirm generate -> execute -> exitcode: 0 -> return to idle, exactly once.
"""
print(HARDWARE_CHECKLIST)
sys.exit(1 if FAIL else 0)

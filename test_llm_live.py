# -*- coding: utf-8 -*-
"""
test_llm_live.py — Real LLM, fake robot: validates the Plan -> Action pipeline.

Usage (project root, on your own machine):
    export OPENAI_API_KEY=sk-...   (or have OAI_CONFIG_LIST.json in place)
    python test_llm_live.py

What it does:
  - Feeds four hand-written PerceptionData scenarios (no camera / mic / robot)
  - The brain uses the REAL GPT-4o to decide -> prints the full decision JSON
  - The body executes on a LoggingRobot -> prints every hardware call
  - approach runs on simulated kinematics so you can watch the closed loop
    converge step by step
  - Scenarios 2 -> 3 validate memory: introduce a name, then ask for it back
  - Scenario 4 validates complex_task routing (AutoMisty is stubbed by default)

Cost: roughly 6-10 GPT-4o / 4o-mini calls, a few cents.
"""

import sys
import types
import time
import os
import json

# ---- Stub AutoMisty by default (importing it pulls in all of autogen, and a
#      real run is slow and expensive). Set REAL_AUTOMISTY = True to test the
#      actual code-generation round-trip (expect execution failures without a
#      robot — watching it retry and then give up cleanly IS the test).
REAL_AUTOMISTY = False
if not REAL_AUTOMISTY:
    am = types.ModuleType("AutoMisty")
    am.complex_action = lambda task: print(f"      🎭 [AutoMisty-stub] received task: {task}")
    sys.modules["AutoMisty"] = am

# ---- Speed up waits (post-speech / post-motion sleeps capped at 50 ms) ----
_real_sleep = time.sleep
time.sleep = lambda s: _real_sleep(min(s, 0.05))

import importlib.util
spec = importlib.util.spec_from_file_location("frv3", "full_robot_v3.py")
frv3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frv3)

from openai import OpenAI

# ==========================================
# Fake robot + simulated distance world
# ==========================================

class SimWorld:
    def __init__(self, user_distance_cm, cm_per_sec=None):
        self.d = float(user_distance_cm)
        self.speed = cm_per_sec or frv3.CM_PER_SEC_AT_PERCENT

class LoggingRobot:
    """Logs every hardware call; drive_time really moves the simulated world."""
    def __init__(self, world: SimWorld):
        self.world = world
    def drive_time(self, linearVelocity=0, angularVelocity=0, timeMs=0):
        sign = 1 if linearVelocity > 0 else -1
        moved = sign * self.world.speed * (timeMs / 1000.0) * (abs(linearVelocity) / frv3.DRIVE_PERCENT)
        self.world.d -= moved
        print(f"      🔧 drive_time(v={linearVelocity}%, t={timeMs}ms)  -> simulated distance now {self.world.d:.0f}cm")
    def speak(self, text):
        print(f"      🔊 speak: \"{text}\"")
    def stop(self):
        print("      🔧 stop()")
    def __getattr__(self, name):
        def _log(*a, **k):
            arg = ", ".join(map(str, a)) + ("," + str(k) if k else "")
            print(f"      🔧 {name}({arg})")
        return _log

class FakePerception:
    def __init__(self, world: SimWorld):
        self.world = world
    def get_distance(self, max_age_sec=2.0):
        return int(self.world.d) if self.world.d > 0 else -1

# ==========================================
# Scenarios
# ==========================================

SCENARIOS = [
    dict(
        name="Scenario 1: user is crying (visual-only trigger, no speech)",
        visual="A man sits at a table wiping tears from his eyes with a tissue. "
               "He looks sad and distressed. Indoor room with brick wall.",
        audio="(no speech)",
        trigger="visual_first",
        distance=142,
    ),
    dict(
        name="Scenario 2: self-introduction (tests memory write)",
        visual="A man looks at the robot with a friendly smile and waves.",
        audio="Hi there, my name is Henry, nice to meet you!",
        trigger="audio_first",
        distance=180,
    ),
    dict(
        name="Scenario 3: memory recall (should remember the name)",
        visual="The same man looks at the robot expectantly.",
        audio="Do you remember my name?",
        trigger="audio_first",
        distance=90,
    ),
    dict(
        name="Scenario 4: complex-task routing (should set complex_task)",
        visual="The man smiles and gestures enthusiastically at the robot.",
        audio="Could you perform a happy dance for me?",
        trigger="audio_first",
        distance=70,
    ),
]

# ==========================================
# Main
# ==========================================

def main():
    key = frv3.load_api_key()
    if not key:
        print("OPENAI_API_KEY required")
        return

    memfile = "_live_test_memory.json"
    if os.path.exists(memfile):
        os.remove(memfile)

    client = OpenAI(api_key=key)
    memory = frv3.ConversationMemory(client, path=memfile)
    brain = frv3.MistyEmbodiedBrain(key, memory)

    for sc in SCENARIOS:
        print("\n" + "=" * 64)
        print(sc["name"])
        print("=" * 64)
        pd = frv3.PerceptionData(
            timestamp=time.time(),
            visual_description=sc["visual"],
            audio_transcript=sc["audio"],
            trigger_source=sc["trigger"],
            user_distance_cm=sc["distance"],
        )
        print(f"  [Input] distance={pd.user_distance_cm}cm | audio=\"{pd.audio_transcript}\"")
        print(f"          visual=\"{pd.visual_description[:70]}...\"")

        decision = brain.think(pd)
        print(f"\n  [LLM decision]")
        print(json.dumps(decision, ensure_ascii=False, indent=4))

        print(f"\n  [Action trace]")
        world = SimWorld(sc["distance"])
        body = frv3.MistyBodyController(LoggingRobot(world), FakePerception(world))
        body.execute(decision)

        user_input = (pd.audio_transcript if pd.audio_transcript != "(no speech)"
                      else f"(silent; visual: {pd.visual_description[:60]})")
        misty_said = decision.get("speak") or "(non-verbal action)"
        memory.add_turn(user_input, misty_said)

    print("\n" + "=" * 64)
    print("Final memory state")
    print("=" * 64)
    print(memory.as_prompt_block())
    print("\nLong-term facts:", json.dumps(memory.facts, ensure_ascii=False))

    print("""
-------------------------------------------------------------
What to look for:
  Scenario 1  expression should be "sad", speak should comfort the user
  Scenario 2  memory should extract the name (see long-term facts)
  Scenario 3  speak should contain "Henry"  <- direct evidence of memory
  Scenario 4  complex_task should be a non-null dance description
  All         drive_time should converge stepwise, never overshoot, always stop
-------------------------------------------------------------""")
    os.remove(memfile)


if __name__ == "__main__":
    main()

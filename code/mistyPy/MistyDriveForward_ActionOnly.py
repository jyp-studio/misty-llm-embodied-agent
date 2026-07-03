# filename: MistyDriveForward_ActionOnly.py

from CUBS_Misty import Robot
import time


def express_intent_and_request_drive_forward(robot_ip: str, duration_s: float = 2.0):
    """
    Expressively signal Misty's intent to drive forward, then provide a clear
    integration point for a Mobility Agent to perform the actual driving.

    Parameters:
    - robot_ip (str): IP address of the Misty robot (e.g., "192.168.1.237").
    - duration_s (float): The intended forward movement duration in seconds (default 2.0).

    Notes:
    - In this ActionAgent task, base driving is NOT implemented. Use the indicated
      integration point (commented section) for a Mobility/Movement Agent to send
      the actual drive command.
    """
    misty = Robot(robot_ip)

    try:
        # 1) Pre-move expressive signaling: face, LED, head, arms, sound, and speech
        misty.drive(-40, 0)  # Ensure Misty is stationary before expressive intent
        misty.emotion_Joy()  # Friendly, excited face
        misty.change_led(0, 255, 0)  # Green LED = "ready to go"
        misty.sound_Joy()  # Happy tone
        time.sleep(0.2)

        # Center head and a small nod to acknowledge the upcoming action
        misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.35)
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.35)

        # Arms ready pose (slight lift)
        misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, duration=0.3)
        time.sleep(0.35)

        # Brief speech cue
        try:
            misty.speak("Ready to roll forward for two seconds!", speechRate=1.0)
        except Exception as e:
            print(f"[INFO] speak not available or failed: {e}")

        # 2) Mobility Agent integration point (DO NOT IMPLEMENT DRIVE HERE)
        # ----------------------------------------------------------------
        # The actual base drive forward must be handled by a Mobility/Movement Agent.
        # Example for integration (for reference only; do not enable here):
        #   MobilityAgent.drive_time(linear_velocity=30, angular_velocity=0, duration_ms=int(duration_s*1000))
        # Or, if using Misty's mobility API elsewhere:
        #   misty.drive_time(30, 0, int(duration_s * 1000))
        # ----------------------------------------------------------------

        # 3) Post-intent expressive completion: gentle confirmation
        misty.sound_Acceptance()
        misty.transition_led(0, 255, 0, 255, 255, 255, "Breathe", 800)
        time.sleep(0.9)

    except Exception as e:
        print(f"[WARN] Expressive intent sequence encountered an issue: {e}")
    finally:
        # Always restore Misty to a neutral state
        try:
            misty.return_to_normal()
        except Exception as e:
            print(f"[WARN] return_to_normal() encountered an issue: {e}")

    return True


# -------------------------------
# Simple tests
# -------------------------------


def test_expressive_intent(ip: str):
    """
    Runs the expressive intent function and asserts successful completion.
    """
    result = express_intent_and_request_drive_forward(ip, duration_s=2.0)
    print(f"[TEST] expressive intent returned: {result}")
    assert result is True, "Expressive intent function did not return True."
    return True


if __name__ == "__main__":
    ip = "192.168.1.237"

    print("[RUN] Testing expressive intent for forward drive (ActionAgent-only)...")
    try:
        test_expressive_intent(ip)
        print("[PASS] Expressive intent test passed.")
    except AssertionError as e:
        print(f"[FAIL] Test failed: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error during test: {e}")

# filename: MistyMoveForward.py

from CUBS_Misty import Robot
import time

def misty_move_forward_vivid(robot_ip: str, velocity: float = 25.0, duration: float = 2.0):
    '''
    Perform a vivid "prepare to move forward" action sequence using only allowed ActionAgent APIs.

    Parameters:
    - robot_ip (str): IP address of the Misty robot (e.g., "192.168.1.237").
    - velocity (float): Intended forward speed (-100 to 100). Positive means forward. (Not executed here)
    - duration (float): Intended duration in seconds for forward motion. (Used as timing cue only)

    Behavior:
    - Pre-move: Joyful expression, green LED, greeting sound; aligns head and arms.
    - Visual cue: LED breath transition (green -> cyan) and awe sound.
    - Timing: Waits for the intended move duration as a placeholder for motion.
    - Post: Plays acceptance sound.
    - Always: Resets Misty to normal at the end.

    Note:
    - Base driving is intentionally not invoked to comply with the allowed ActionAgent API set.
      When integrating locomotion, insert the drive logic below via the appropriate Agent.
    '''
    misty = Robot(robot_ip)

    # Basic parameter safety defaults
    if duration is None or duration <= 0:
        duration = 2.0
    if velocity is None:
        velocity = 25.0

    try:
        # Expressive pre-move cues
        misty.emotion_Joy()
        misty.change_led(0, 255, 0)  # Green for "go"
        misty.sound_PhraseHello()
        time.sleep(0.4)

        # Prep posture for forward motion
        misty.move_head(pitch=-8, yaw=0, roll=0, duration=0.5, units="degrees")
        misty.move_arms(leftArmPosition=0, rightArmPosition=0, duration=0.4)
        time.sleep(0.4)

        # Subtle breathing LED transition (green -> cyan) as visual cue
        misty.transition_led(0, 255, 0, 0, 255, 255, "Breathe", 800)
        misty.sound_Awe2()

        # --- Locomotion placeholder (do not implement here to stay within ActionAgent scope) ---
        # For base drive, integrate with the appropriate Agent:
        # misty.drive(velocity, 0)  # go straight
        # time.sleep(duration)
        # misty.drive(0, 0)
        # ------------------------------------------------------------------------------

        # Use the intended duration as a timing stand-in
        half = max(0.2, duration / 2.0)
        time.sleep(half)
        # Add a small head bob for liveliness during the "move"
        misty.move_head(pitch=-4, yaw=5, roll=0, duration=0.3, units="degrees")
        time.sleep(max(0.0, duration - half))

        # Post-move acknowledgment
        misty.sound_Acceptance()
        time.sleep(0.3)

    finally:
        # Always return to a neutral default state
        misty.return_to_normal()


def _test_move_forward(ip: str):
    '''
    Basic test wrapper for the misty_move_forward_vivid function.
    '''
    print("[TEST] Starting forward move expressive sequence test...")
    try:
        misty_move_forward_vivid(ip, velocity=25.0, duration=2.0)
        print("[TEST] Expressive sequence completed without exceptions.")
    except Exception as e:
        print(f"[TEST] Exception during sequence: {e}")
        raise
    print("[TEST] Test finished.")


if __name__ == "__main__":
    TEST_MISTY_IP = "192.168.1.237"
    _test_move_forward(TEST_MISTY_IP)
# filename: MistyForwardTwoSeconds.py

from CUBS_Misty import Robot

def misty_move_forward_two_seconds(robot_ip: str, speed: int = 30):
    """
    Orchestrates expressive cues for a 2-second forward movement while staying within ActionAgent scope.

    Notes:
    - Only approved MistyActionAgent API calls are used:
      speak, move_arms, move_head, change_led, transition_led, emotion_*, sound_*, return_to_normal.
    - Actual mobility (driving forward) is NOT part of the ActionAgent API. Integrate the drive command
      via the appropriate mobility/navigation agent at the indicated placeholder below.

    Parameters:
    - robot_ip (str): IP address of the Misty robot.
    - speed (int): Intended forward speed (-100 to 100). Placeholder only; not used by ActionAgent.
    """
    misty = Robot(robot_ip)

    try:
        # Pre-move expressive cues
        misty.emotion_Joy(alpha=0.9)
        misty.change_led(0, 255, 0)  # Green "Go"
        misty.speak("Starting forward movement for two seconds.", speechRate=1.05)

        # Subtle posture changes
        misty.move_head(pitch=10, yaw=0, roll=0, duration=0.6, units="degrees")
        misty.move_arms(leftArmPosition=10, rightArmPosition=10, duration=0.4)
        misty.transition_led(0, 255, 0, 0, 128, 0, "Breathe", 700)

        # Mobility placeholder (DO NOT IMPLEMENT HERE - other Agent needed)
        # ----------------------------------------------------------------
        # Integrate mobility via the appropriate agent (e.g., Motion/Navigation Agent):
        # Example:
        #   misty.drive_time(linearVelocity=speed, angularVelocity=0, timeMs=2000)
        # ----------------------------------------------------------------

        # Post-move confirmation
        misty.sound_Acceptance()
        misty.speak("Completed forward movement.", speechRate=1.05)

    finally:
        # Ensure Misty returns to normal even if an error occurs
        misty.return_to_normal()


if __name__ == "__main__":
    # Test the action function
    test_ip = "192.168.1.237"
    print("[TEST] Starting misty_move_forward_two_seconds test...")
    try:
        misty_move_forward_two_seconds(test_ip, speed=30)
        print("[TEST] Completed without uncaught exceptions. Test PASSED.")
    except Exception as e:
        print(f"[TEST] Test FAILED with error: {e}")
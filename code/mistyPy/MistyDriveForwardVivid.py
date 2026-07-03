# filename: MistyDriveForwardVivid.py

from CUBS_Misty import Robot

def misty_drive_forward_vivid(robot_ip: str, duration_seconds: float = 2.0, speed: float = 40.0):
    """
    Vividly prepare, signal, and wrap up a forward-drive request for Misty.
    Note: Actual locomotion (driving forward) must be handled by a separate Navigation/Locomotion Agent.

    Parameters:
    - robot_ip (str): IP address of the Misty robot (e.g., "192.168.1.237").
    - duration_seconds (float): Intended duration for forward motion (seconds).
    - speed (float): Intended forward speed (placeholder value for Navigation Agent).

    Behavior:
    - Uses expressive cues: emotions, LEDs, sounds, and speech.
    - Provides a clear integration hook for a Navigation/Locomotion Agent to execute actual driving.
    - Resets Misty to her neutral state at the end via return_to_normal().
    """

    # Instantiate Misty inside the function as required
    misty = Robot(robot_ip)

    try:
        # 1) Pre-drive expressive prep
        misty.emotion_JoyGoofy()
        misty.change_led(0, 255, 0)  # Bright green to indicate readiness
        misty.sound_PhraseHello()
        misty.speak("Starting forward drive. Please stand clear.", speechRate=1.05)
        misty.move_head(pitch=-10, yaw=10, roll=0, duration=0.6, units="degrees")
        misty.move_head(pitch=-10, yaw=-10, roll=0, duration=0.6, units="degrees")
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.5, units="degrees")
        misty.move_arms(leftArmPosition=10, rightArmPosition=10, duration=0.6)

        # Subtle dynamic LED effect while "moving"
        misty.transition_led(0, 200, 0, 0, 60, 0, "Breathe", 800)

        # 2) Navigation/Locomotion Agent integration point:
        # Replace the following comment with the proper call when integrating your Navigation Agent.
        # [NavigationAgent Hook]
        # navigation_agent.drive_forward(duration_seconds=duration_seconds, speed=speed)
        # NOTE: Do not implement Perception or Event logic here; integrate with respective Agents externally.

        # 3) In-motion vibe and feedback cues (sound and encouraging callout)
        misty.sound_Joy2()
        misty.speak("Cruising ahead.", speechRate=1.05)

        # 4) Arrival flourish and confirmation
        misty.change_led(0, 120, 255)  # Calm blue upon completion
        misty.emotion_Admiration()
        misty.sound_Acceptance()
        misty.speak("Arrived. Forward drive complete.", speechRate=1.05)
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.6, units="degrees")
        misty.move_arms(leftArmPosition=0, rightArmPosition=0, duration=0.6)

    finally:
        # Always return Misty to a neutral state
        misty.return_to_normal()


# ----------------------
# Simple tests (prints only)
# ----------------------
def _test_default(ip: str):
    print("[TEST] Vivid forward-drive wrapper: duration=2.0s, speed=40.0")
    misty_drive_forward_vivid(ip, duration_seconds=2.0, speed=40.0)

def _test_custom_speed(ip: str):
    print("[TEST] Vivid forward-drive wrapper: duration=2.0s, speed=50.0")
    misty_drive_forward_vivid(ip, duration_seconds=2.0, speed=50.0)


if __name__ == "__main__":
    TEST_IP = "192.168.1.237"
    _test_default(TEST_IP)
    _test_custom_speed(TEST_IP)
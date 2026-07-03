# filename: MistyGentleComfortApproach.py

from CUBS_Misty import Robot
import time

def misty_gentle_comfort_approach(robot_ip: str):
    """
    Misty gently approaches someone who is upset, shows a sad/compassionate
    expression, opens arms for a comforting gesture, and speaks reassuring words.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    try:
        # 1) Gentle, unhurried "approach" feeling
        # (No navigation API in this ActionAgent spec; we simulate approach with body language.)
        # If a drive API is available in another Agent, it could be integrated here.
        # --- BEGIN simulated gentle approach ---
        misty.change_led(0, 0, 255)  # soft blue
        misty.emotion_Sadness()      # gentle sad eyes

        # Slight head tilt down and to the side to convey concern
        misty.move_head(pitch=15, yaw=20, roll=0, velocity=30, units="degrees")
        time.sleep(1.0)

        # Small arm movement as if slowly coming closer
        misty.move_arms(leftArmPosition=45, rightArmPosition=45, duration=1.5)
        time.sleep(1.5)
        # --- END simulated gentle approach ---

        # 2) Sad and compassionate facial expression
        misty.emotion_RemorseShame()
        misty.sound_Sadness2()
        time.sleep(1.0)

        # 3) Open arms in an inviting, comforting gesture
        # Move arms upward and slightly forward (open for hug)
        misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, duration=1.0)
        time.sleep(1.0)
        misty.move_arms(leftArmPosition=-20, rightArmPosition=-20, duration=1.0)
        time.sleep(1.0)

        # Gentle LED breathing between soft blue and white for calm comfort
        misty.transition_led(
            red=0, green=0, blue=255,
            red2=255, green2=255, blue2=255,
            transition_type="Breathe",
            time_ms=1500
        )

        # 4) Speak reassuring, present-focused, non-judgmental words
        # Use onboard TTS with a slightly slower speech rate for calm delivery.
        comforting_text = (
            "I see you’re really upset. I’m here with you. "
            "If you want a hug or someone to sit with you, I’m right here."
        )
        misty.speak(text=comforting_text, speechRate=0.9)
        # Optionally pair with a soft sadness/comfort sound
        time.sleep(0.5)
        misty.sound_Sadness()

        # Hold the open-arm, compassionate pose for a few seconds
        time.sleep(5.0)

    finally:
        # Always return Misty to a neutral state at the end.
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run against the provided IP.
    # Ensure Misty is reachable at this address before executing.
    misty_gentle_comfort_approach("192.168.1.237")
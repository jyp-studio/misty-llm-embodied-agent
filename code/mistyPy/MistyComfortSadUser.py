# filename: MistyComfortSadUser.py

from CUBS_Misty import Robot
import time

def misty_comfort_sad_user(robot_ip: str):
    """
    Comfort a sad user with slow approach, sad face, open arms, and empathetic speech.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    try:
        # 1. Move in a slow and gentle manner to approach the user
        # NOTE: We use gentle head and arm motion to simulate a soft "approach".
        # (Physical base driving is part of a different agent and should be added there if needed.)
        misty.change_led(0, 0, 255)  # soft blue
        misty.emotion_Sadness()
        misty.sound_Sadness2()

        # Gentle "approach" motion with body language:
        # Slight head tilt down and toward the user
        misty.move_head(pitch=15, yaw=10, roll=0, velocity=20, units="degrees")
        time.sleep(1.0)

        # 2. Adopt a sad facial expression
        # (Already set, reinforce with a slightly deeper sadness after a pause)
        misty.emotion_Sadness()
        time.sleep(0.5)

        # 3. Use an open-arms gesture to convey comfort and support
        # Arms slightly forward and somewhat up, as if opening for a hug
        misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, leftArmVelocity=30, rightArmVelocity=30)
        time.sleep(1.0)

        # Deepen the gesture: gently open a bit more and hold
        misty.move_arms(leftArmPosition=-20, rightArmPosition=-20, leftArmVelocity=20, rightArmVelocity=20)
        time.sleep(1.0)

        # Add a soft, sad sound while holding the gesture
        misty.sound_Sadness3()
        time.sleep(1.0)

        # 4. Speak an apologetic and validating sentence expressing empathy
        empathetic_text = (
            "I’m so sorry you’re feeling this sad right now. "
            "It’s okay to feel this way. I’m here with you, "
            "and you don’t have to go through this alone."
        )
        misty.speak(text=empathetic_text, speechRate=0.9)
        # Allow some time for the speech to complete before resetting state
        time.sleep(8.0)

        # After speaking, keep the comforting pose briefly
        time.sleep(2.0)

    finally:
        # Always return Misty to a neutral, normal state at the end
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the comfort behavior.
    # Replace the IP below with your Misty's IP if different.
    misty_comfort_sad_user("192.168.1.237")
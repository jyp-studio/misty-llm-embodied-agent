# filename: MistyHappyWaveGreeting.py

from CUBS_Misty import Robot
import time

def misty_happy_wave_greeting(robot_ip: str):
    """
    Have Misty:
      1. Move in a normal, casual manner (subtle head & arm motion).
      2. Display a happy facial expression.
      3. Perform a waving gesture.
      4. Speak a friendly greeting about feeling great and asking how the other is doing.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Instantiate Misty inside the function
    misty = Robot(robot_ip)

    # 1 & 2. Normal subtle movement + happy facial expression
    misty.emotion_Joy()                 # Happy eyes
    misty.change_led(0, 255, 0)         # Friendly green LED
    misty.sound_Joy()                   # A short joyful sound

    # Gentle initial posture change for "normal movement"
    misty.move_head(pitch=-5, yaw=10, roll=0, duration=0.8, units="degrees")
    misty.move_arms(leftArmPosition=10, rightArmPosition=10, duration=0.8)
    time.sleep(0.8)

    # 3. Perform a waving gesture (right arm wave + slight head follow)
    # Raise right arm up for waving
    misty.move_arms(leftArmPosition=20, rightArmPosition=-29, duration=0.6)
    misty.move_head(pitch=-5, yaw=20, roll=0, duration=0.6, units="degrees")
    time.sleep(0.6)

    # Wave motion: small repeated movements of the right arm & a bit of head sway
    for _ in range(3):
        misty.move_arms(rightArmPosition=-10, duration=0.3)
        misty.move_head(yaw=25, duration=0.3, units="degrees")
        time.sleep(0.3)

        misty.move_arms(rightArmPosition=-29, duration=0.3)
        misty.move_head(yaw=15, duration=0.3, units="degrees")
        time.sleep(0.3)

    # Lower the arm back down in a relaxed way
    misty.move_arms(leftArmPosition=10, rightArmPosition=10, duration=0.6)
    misty.move_head(pitch=-3, yaw=0, roll=0, duration=0.6, units="degrees")
    time.sleep(0.6)

    # 4. Speak the friendly greeting
    greeting_text = (
        "Hello! I’m doing great today, thank you for asking. "
        "How are you doing?"
    )
    misty.speak(greeting_text, speechRate=1.0)

    # Allow some time for speech to play before resetting
    time.sleep(4)

    # Reset Misty back to a neutral / normal state
    misty.return_to_normal()


if __name__ == "__main__":
    # Test run on the provided Misty IP
    misty_happy_wave_greeting("192.168.1.237")
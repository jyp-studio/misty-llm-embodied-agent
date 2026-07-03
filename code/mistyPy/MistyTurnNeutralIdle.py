# filename: MistyTurnNeutralIdle.py

from CUBS_Misty import Robot
import time

def misty_turn_neutral_idle(robot_ip: str):
    """
    Have Misty:
      1. Express a neutral facial appearance.
      2. Maintain an idle body posture.
      3. Say: 'Turning to face that direction.' (or equivalent).

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty
    misty = Robot(robot_ip)

    # 1. Neutral facial appearance
    # Use default neutral content face and a calm white LED
    misty.emotion_DefaultContent()
    misty.change_led(255, 255, 255)

    # 2. Idle body posture: arms and head in neutral positions
    # Arms relaxed at 0 degrees, head centered
    misty.move_arms(leftArmPosition=0, rightArmPosition=0, leftArmVelocity=40, rightArmVelocity=40, duration=1.0)
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=40, duration=1.0, units="degrees")
    time.sleep(1.0)

    # 3. Speech: inform that Misty is turning to face a direction
    misty.speak("Turning to face that direction.", speechRate=1.0)
    # Allow time for speech to complete (approximate, depends on TTS length)
    time.sleep(2.0)

    # Note: Actual turning/motion would be handled by another agent/module
    # (e.g., navigation/motion control). Integrate that here if needed.

    # Reset Misty to normal at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test execution; replace IP if needed before running
    misty_turn_neutral_idle("192.168.1.237")
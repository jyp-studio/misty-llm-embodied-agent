# filename: MistyNeutralIdleHelp.py

from CUBS_Misty import Robot
import time

def misty_neutral_idle_help(robot_ip: str):
    """
    Task:
      1. Maintain a neutral facial expression.
      2. Assume an idle gesture posture.
      3. Politely say that help is available if needed.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Instantiate Misty for this function
    misty = Robot(robot_ip)

    # 1. Neutral facial expression (default/neutral content)
    misty.emotion_DefaultContent()

    # 2. Idle gesture posture:
    #    - Arms at neutral (forward) position
    #    - Head looking straight ahead
    misty.move_arms(leftArmPosition=0, rightArmPosition=0, leftArmVelocity=50, rightArmVelocity=50)
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")

    # Give a short pause so posture is clearly assumed
    time.sleep(0.5)

    # 3. Politely say that help is available if needed
    #    (Matching the user's provided text as closely as possible)
    misty.speak("If there's anything I can help with, just let me know.", speechRate=1.0)

    # Optional: soft neutral LED to indicate availability
    misty.change_led(200, 200, 255)

    # Wait briefly so the speech and LED are visible/audible before resetting
    time.sleep(3)

    # Always restore Misty to a neutral baseline state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run on the provided IP address
    misty_neutral_idle_help("192.168.1.237")
# filename: MistyNeutralSupport.py

from CUBS_Misty import Robot
import time


def misty_neutral_support(robot_ip: str):
    """
    Keep Misty neutral and idle, and have her calmly say she is available for support.

    Behavior:
    1. Maintain a neutral facial expression.
    2. Remain in an idle physical posture (arms and head relaxed, neutral LED).
    3. Offer a calm verbal message of availability for support.
    """

    # Instantiate Misty
    misty = Robot(robot_ip)

    # 1 & 2. Ensure neutral / idle posture & look
    # - Neutral LED (soft white)
    misty.change_led(200, 200, 200)
    # - Neutral/default expression
    misty.emotion_DefaultContent()
    # - Relaxed arms and centered head
    misty.move_arms(leftArmPosition=0, rightArmPosition=0, leftArmVelocity=40, rightArmVelocity=40)
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=30, units="degrees")
    time.sleep(1.0)

    # 3. Calm verbal message of availability
    # Use a slower speech rate for a calm tone
    misty.speak(
        text="I am here and available if you need any support.",
        speechRate=0.9
    )

    # Give a moment for speech playback to progress
    time.sleep(3.0)

    # Reset Misty back to normal state (per instructions)
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run – replace with your Misty IP if needed.
    misty_neutral_support("192.168.1.237")
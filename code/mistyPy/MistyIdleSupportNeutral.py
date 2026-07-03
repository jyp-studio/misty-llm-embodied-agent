# filename: MistyIdleSupportNeutral.py

from CUBS_Misty import Robot
import time

def misty_idle_support_neutral(robot_ip: str):
    """
    Keep Misty in a neutral, idle posture and deliver a calm support message.

    Requirements:
    1. Maintain a neutral facial expression.
    2. Remain in an idle physical posture.
    3. Offer a calm verbal message of availability for support.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Instantiate Misty
    misty = Robot(robot_ip)

    # 1. Neutral facial expression
    # Use the default content/neutral face
    misty.emotion_DefaultContent()

    # 2. Idle physical posture
    # Arms relaxed at neutral, head centered, LED soft neutral color
    misty.move_arms(
        leftArmPosition=0,
        rightArmPosition=0,
        leftArmVelocity=40,
        rightArmVelocity=40,
        duration=1.0
    )
    misty.move_head(
        pitch=0,
        yaw=0,
        roll=0,
        velocity=40,
        duration=1.0,
        units="degrees"
    )
    misty.change_led(200, 200, 255)  # soft neutral bluish-white

    # Small pause to allow posture to settle before speaking
    time.sleep(1.0)

    # 3. Calm verbal message of availability for support
    # Optionally pair with a soft acceptance sound right before speaking
    misty.sound_Acceptance(volume=40)
    time.sleep(0.8)

    misty.speak(
        text="I'm here if you need anything.",
        speechRate=0.9  # slightly slower for a calm tone
    )

    # Give some time for the speech to complete before resetting
    time.sleep(4.0)

    # Reset Misty to normal state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic execution test for the defined behavior.
    # Replace the IP below if needed for your environment.
    test_ip = "192.168.1.237"
    misty_idle_support_neutral(test_ip)
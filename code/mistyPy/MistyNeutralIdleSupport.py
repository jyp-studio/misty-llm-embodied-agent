# filename: MistyNeutralIdleSupport.py

from CUBS_Misty import Robot
import time


def misty_neutral_idle_support(robot_ip: str):
    """
    Keep Misty nearby in a neutral posture with an idle gesture,
    using a neutral facial expression and giving a short verbal reassurance.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Instantiate Misty
    misty = Robot(robot_ip)

    # 1) Neutral / idle body posture (remain nearby, no locomotion)
    # Arms relaxed slightly down, not exaggerated
    misty.move_arms(leftArmPosition=20,
                    rightArmPosition=20,
                    leftArmVelocity=40,
                    rightArmVelocity=40,
                    duration=1.0)

    # Head level, looking forward slightly down (attentive but calm)
    misty.move_head(pitch=5,
                    yaw=0,
                    roll=0,
                    velocity=40,
                    duration=1.0,
                    units="degrees")

    # Soft neutral LED (dim white-blue)
    misty.change_led(red=200, green=220, blue=255)

    # 2) Neutral facial expression
    misty.emotion_DefaultContent()

    # 3) Short verbal reassurance + gentle neutral sound
    misty.sound_Acceptance(volume=60)
    time.sleep(0.8)  # small pause before speaking

    misty.speak("I'm here if you need me.",
                speechRate=1.0)

    # Allow speech to complete before resetting
    time.sleep(3)

    # Return Misty to her normal baseline state
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run on the provided IP
    misty_neutral_idle_support("192.168.1.237")
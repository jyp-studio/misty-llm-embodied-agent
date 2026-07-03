# filename: MistyComfortSadSupport.py

from CUBS_Misty import Robot
import time

def misty_comfort_sad_support(robot_ip: str):
    """
    Comfort interaction for a very sad user.

    Behavior:
    1. Move in a slow and gentle manner (head + arms).
    2. Display a sad facial expression.
    3. Open arms in a comforting gesture.
    4. Speak a supportive and apologetic message.

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot.
    """

    # Instantiate Misty inside the function
    misty = Robot(robot_ip)

    # 1) Soft setup: LED + subtle sad face + soft sound
    misty.change_led(0, 0, 255)  # calm blue
    misty.emotion_Sadness()
    misty.sound_Sadness2()
    time.sleep(0.5)

    # 2) Slow & gentle head movement: look slightly down with a small tilt
    misty.move_head(pitch=10, yaw=0, roll=0, velocity=20, duration=2.0, units="degrees")
    time.sleep(2.0)

    # 3) Open arms in a comforting gesture (slow and wide, like a gentle hug)
    # Arms up and slightly out, moved slowly
    misty.move_arms(leftArmPosition=-10, rightArmPosition=-10,
                    leftArmVelocity=15, rightArmVelocity=15,
                    duration=2.0, units="degrees")
    time.sleep(2.0)

    # Gentle micro-movement to feel alive and soothing
    misty.move_head(pitch=15, yaw=8, roll=0, velocity=15, duration=1.5, units="degrees")
    time.sleep(1.5)
    misty.move_head(pitch=12, yaw=-8, roll=0, velocity=15, duration=1.5, units="degrees")
    time.sleep(1.5)

    # Slight arm "holding" motion – a tiny in-and-out motion
    for _ in range(2):
        misty.move_arms(leftArmPosition=-5, rightArmPosition=-5,
                        leftArmVelocity=10, rightArmVelocity=10,
                        duration=1.2, units="degrees")
        time.sleep(1.2)
        misty.move_arms(leftArmPosition=-15, rightArmPosition=-15,
                        leftArmVelocity=10, rightArmVelocity=10,
                        duration=1.2, units="degrees")
        time.sleep(1.2)

    # 4) Supportive, apologetic message (given by the user)
    misty.speak(
        text=(
            "I’m so sorry you’re feeling this sad right now. "
            "I’m here with you. Do you want to tell me what happened, "
            "or should we just sit together quietly for a moment?"
        ),
        speechRate=0.9
    )

    # Keep the comforting posture a little while after speaking
    time.sleep(5)

    # Always reset Misty back to her neutral state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Test run – replace the IP below with your Misty’s IP if needed
    misty_comfort_sad_support("192.168.1.237")
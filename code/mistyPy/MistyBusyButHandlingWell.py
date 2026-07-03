# filename: MistyBusyButHandlingWell.py

from CUBS_Misty import Robot
import time

def misty_encourage_busy_user(robot_ip: str):
    """
    Misty performs a short, upbeat interaction:
      1. Moves in a normal, gentle manner.
      2. Shows a happy facial expression.
      3. Nods encouragingly.
      4. Speaks an encouraging line about the user being busy but handling it well.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    # 1. "Move in a normal manner" – subtle whole-body feel:
    #    - Neutral LED with a soft breathe from white to soft blue.
    misty.transition_led(
        255, 255, 255,   # start: white
        150, 200, 255,   # end: soft blue
        "Breathe",
        800
    )

    # 2. Show a happy facial expression + happy sound
    misty.emotion_Joy2()
    misty.sound_Joy2()
    time.sleep(1.0)

    # 3. Gesture by nodding (pitch up/down) with a little arm motion
    #    Gentle arms to make the gesture more vivid.
    misty.move_arms(leftArmPosition=20, rightArmPosition=20, duration=0.4)
    time.sleep(0.4)

    # Nod sequence: down-up-down
    misty.move_head(pitch=15, yaw=0, roll=0, duration=0.3)   # slight nod down
    time.sleep(0.3)
    misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.3)  # back up
    time.sleep(0.3)
    misty.move_head(pitch=10, yaw=0, roll=0, duration=0.3)   # another affirming nod
    time.sleep(0.3)

    # 4. Speak the encouraging line
    misty.speak(
        text="It sounds like you're busy, but I see you're handling it well with a smile!",
        speechRate=1.0
    )

    # Give a moment for the speech to finish before resetting
    time.sleep(4.0)

    # Reset Misty to a normal, neutral state
    misty.return_to_normal()


if __name__ == "__main__":
    # Test run: replace with your Misty IP if needed
    test_ip = "192.168.1.237"
    misty_encourage_busy_user(test_ip)
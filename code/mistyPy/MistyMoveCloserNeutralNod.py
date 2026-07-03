# filename: MistyMoveCloserNeutralNod.py

from CUBS_Misty import Robot
import time

def misty_move_closer_neutral_nod(robot_ip: str):
    """
    Task:
    1. Move forward.
    2. Show a neutral facial expression.
    3. Perform a nod gesture.
    4. Speak the provided phrase: "Moving closer now."

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty
    misty = Robot(robot_ip)

    try:
        # 1. Move forward using misty.drive(40, 0)
        #    (Assumes drive(linearVelocity, angularVelocity) exists in the Robot API.)
        misty.drive(40, 0)
        time.sleep(2)  # Let Misty move forward for 2 seconds
        misty.drive(0, 0)  # Stop movement

        # 2. Show a neutral facial expression
        misty.emotion_DefaultContent()

        # 3. Perform a nod gesture
        #    Simple nod: look down then back up a couple of times.
        for _ in range(2):
            misty.move_head(pitch=20, yaw=0, roll=0, duration=0.3, units="degrees")
            time.sleep(0.3)
            misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.3, units="degrees")
            time.sleep(0.3)
        # Return head to neutral after nod
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.3)

        # 4. Speak the provided phrase
        misty.speak("Moving closer now.", speechRate=1.0)

    finally:
        # Always return Misty to normal state at the end
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the action function.
    # Replace IP below with your Misty IP if different.
    misty_move_closer_neutral_nod("192.168.1.237")
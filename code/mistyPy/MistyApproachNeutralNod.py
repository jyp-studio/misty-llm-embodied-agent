# filename: MistyApproachNeutralNod.py

from CUBS_Misty import Robot
import time


def misty_approach_neutral_nod(robot_ip: str):
    """
    Perform a simple approach sequence:
      1. (Placeholder) Approach the user.
      2. Keep a neutral facial expression.
      3. Perform a nodding gesture.
      4. Speak a brief acknowledgment about moving closer.
    
    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot.
    """

    # Initialize Misty robot
    misty = Robot(robot_ip)

    # ------------------------------------------------------------
    # 1. Approach the user
    # ------------------------------------------------------------
    # NOTE:
    # The provided MistyActionAgent API here does not expose drive/locomotion
    # commands (e.g., drive_time, drive_heading, etc.), which are typically
    # needed to actually move Misty closer to the user.
    #
    # If you want Misty to physically drive toward the user, you should
    # integrate the appropriate drive API here, for example:
    #   misty.drive(0, 40)   # Example: move forward at some speed
    # and stop after target distance or time.
    #
    # >>> Integration point for locomotion / navigation Agent <<<
    #
    # For now, we simulate the "approach" step with a comment and a brief pause.
    time.sleep(0.5)

    # ------------------------------------------------------------
    # 2. Maintain a neutral facial expression
    # ------------------------------------------------------------
    misty.emotion_DefaultContent()
    misty.change_led(255, 255, 255)  # Neutral white

    # ------------------------------------------------------------
    # 3. Perform a nodding gesture
    # ------------------------------------------------------------
    # Start from a neutral head position
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.5)

    # Nod down and up a few times to clearly show the gesture
    for _ in range(2):
        # Look down slightly (positive pitch moves down)
        misty.move_head(pitch=15, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.4)
        # Look up slightly (negative pitch moves up)
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.4)

    # Return head to neutral before speaking
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.3)

    # ------------------------------------------------------------
    # 4. Speak a brief acknowledgment of moving closer
    # ------------------------------------------------------------
    misty.speak("Alright, I'm coming closer.", speechRate=1.0)
    time.sleep(2.0)  # Let the speech finish before resetting

    # ------------------------------------------------------------
    # Reset Misty to normal state
    # ------------------------------------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the action function.
    # Replace the IP below with your Misty's actual IP if different.
    test_ip = "192.168.1.237"
    misty_approach_neutral_nod(test_ip)
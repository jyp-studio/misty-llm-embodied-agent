# filename: MistyIdleNeutral.py

from CUBS_Misty import Robot

def misty_idle_neutral(robot_ip: str):
    """
    Keep Misty in a neutral, idle state without additional actions, 
    expressions, or sounds beyond ensuring she is in her default pose.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty robot
    misty = Robot(robot_ip)

    # Ensure Misty is in her normal neutral state and remains idle.
    # This call sets LED, face, head, and arms to neutral and does
    # not trigger any further actions, movements, or sounds.
    misty.return_to_normal()


if __name__ == "__main__":
    # Test: put Misty into a neutral idle state on the given IP.
    misty_idle_neutral("192.168.1.237")
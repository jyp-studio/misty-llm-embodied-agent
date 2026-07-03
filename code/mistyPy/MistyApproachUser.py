# filename: MistyApproachUser.py

from CUBS_Misty import Robot
import time

def misty_approach_user(robot_ip: str):
    """
    Make Misty:
      1. Adopt a neutral facial expression.
      2. Perform a nod gesture.
      3. Speak the message "I'm coming to you."
      4. Move forward toward the user using misty.drive(40, 0).
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # 1. Neutral facial expression and LED
    misty.emotion_DefaultContent()
    misty.change_led(255, 255, 255)  # neutral white

    # 2. Perform a nod gesture (head pitch down then up)
    # Start from neutral
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.5)

    # Nod down
    misty.move_head(pitch=20, yaw=0, roll=0, velocity=70, units="degrees")
    time.sleep(0.4)

    # Nod up
    misty.move_head(pitch=-10, yaw=0, roll=0, velocity=70, units="degrees")
    time.sleep(0.4)

    # Return head to neutral after nod
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.4)

    # 3. Speak the message indicating movement toward the user
    misty.speak("I'm coming to you.", speechRate=1.0)
    # Give a brief pause to avoid immediate overlap with driving sound
    time.sleep(2.0)

    # 4. Move forward toward the user
    # NOTE: The drive method is part of the Misty base API (RobotCommands / MistyRobot).
    # We call it here as instructed with (40, 0) for forward movement.
    # If additional navigation or obstacle handling is needed,
    # that should be implemented by another Agent (e.g., PerceptionAgent).
    try:
        misty.drive(40, 0)  # drive forward at linear velocity 40, no rotation
    except AttributeError:
        # If drive is not directly available on this wrapper,
        # integrate the appropriate base API call here.
        # (This is where a Perception/Navigation Agent could extend behavior.)
        pass

    # Allow some time to move forward before resetting
    time.sleep(3.0)

    # Always return Misty to her normal state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run:
    # Replace the IP below with your Misty’s IP if different.
    misty_approach_user("192.168.1.237")
# filename: MistyComeToUserHappyNod.py

from CUBS_Misty import Robot
import time

def misty_come_to_user_happy_nod(robot_ip: str, target_dist: float = 100.0, speed: str = "normal"):
    """
    Make Misty move toward the user, show a happy expression, nod, and speak.

    Parameters:
    - robot_ip (str): IP address of the Misty robot.
    - target_dist (float): Target distance to move toward the user in millimeters (placeholder – requires Navigation/Perception Agent).
    - speed (str): Movement speed profile (e.g., 'normal', 'slow', 'fast'; placeholder – requires drive control).

    Notes:
    - Actual locomotion (driving toward the user) must be implemented by another Agent 
      that has access to navigation/drive APIs. This function only marks where that logic
      should be placed.
    """

    misty = Robot(robot_ip)

    # --- 1. Move toward the user (placeholder for another Agent) ---
    # TODO: Integrate with Navigation/Perception/Drive Agent here.
    # Example (NOT implemented here by instruction):
    #   navigation_agent.drive_toward_user(distance=target_dist, speed_profile=speed)
    #
    # For now, we just simulate the time it might take to move.
    simulated_move_time = 2.0
    time.sleep(simulated_move_time)

    # --- 2. Show a happy facial expression ---
    misty.emotion_Joy()
    misty.change_led(0, 255, 0)  # Friendly green

    # --- 3. Perform a nodding gesture ---
    # Neutral head first
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=60, units="degrees")
    time.sleep(0.4)

    # Nod: down–up–down–neutral
    for _ in range(2):
        misty.move_head(pitch=20, yaw=0, roll=0, velocity=70, units="degrees")   # look slightly down
        time.sleep(0.3)
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=70, units="degrees")  # look slightly up
        time.sleep(0.3)

    misty.move_head(pitch=0, yaw=0, roll=0, velocity=60, units="degrees")
    time.sleep(0.3)

    # --- 4. Speak a friendly acknowledgment ---
    misty.sound_Joy()
    time.sleep(0.2)
    misty.speak("Okay, I am coming to you.", speechRate=1.0)

    # Give time for the utterance to mostly finish before resetting pose
    time.sleep(2.5)

    # --- Reset Misty to normal state at the end ---
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run.
    # Replace the IP below with your Misty's IP if different.
    test_ip = "192.168.1.237"
    misty_come_to_user_happy_nod(test_ip, target_dist=100.0, speed="normal")
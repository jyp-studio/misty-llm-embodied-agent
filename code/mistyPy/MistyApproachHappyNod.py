# filename: MistyApproachHappyNod.py

from CUBS_Misty import Robot
import time

def misty_approach_happy_nod(robot_ip: str, target_dist_cm: float = 70.0, speed: str = "normal"):
    """
    1. Move Misty closer to the user.
    2. Show a happy facial expression.
    3. Perform a nodding gesture.
    4. Speak a short message indicating that Misty is approaching.
    
    Parameters:
    - robot_ip (str): IP address of the Misty robot.
    - target_dist_cm (float): Target distance to remain from the user in centimeters.
                              NOTE: This function assumes you will position Misty so that
                              driving forward a short distance moves her closer to the user.
    - speed (str): Text label for speed profile ("slow", "normal", "fast").
                   Internally mapped to different drive parameters.
    
    NOTE:
    - This function uses only MistyActionAgent features (no event registration or perception).
    - If you want to use sensors to measure actual distance, integrate PerceptionAgent logic
      where indicated in comments.
    """
    misty = Robot(robot_ip)

    # ------------------ CONFIGURABLE DRIVE PARAMETERS ------------------
    # Map abstract speed labels to approximate drive behavior.
    if speed == "slow":
        drive_time = 1.5   # seconds to drive forward
        linear_velocity = 20  # (robot API units, typically cm/s or similar)
    elif speed == "fast":
        drive_time = 0.8
        linear_velocity = 50
    else:  # "normal"
        drive_time = 1.2
        linear_velocity = 35

    angular_velocity = 0  # go straight

    # ------------------ STEP 1: APPROACH USER (APPROXIMATE) ------------------
    # NOTE: There is no PerceptionAgent or distance feedback here.
    # If you want to integrate distance-sensor-based stopping, add that
    # logic via PerceptionAgent in this region.
    try:
        # Misty drive command from RobotCommands is typically:
        #   misty.drive(linearVelocity, angularVelocity, timeInSeconds)
        # If signature differs, adjust accordingly.
        misty.drive(linear_velocity, angular_velocity, drive_time)
    except Exception as e:
        print(f"[WARN] Could not execute drive command: {e}")

    time.sleep(drive_time + 0.2)

    # ------------------ STEP 2: HAPPY FACIAL EXPRESSION ------------------
    # Use a joyful expression and a bright, warm LED color.
    misty.emotion_Joy()
    misty.change_led(0, 255, 128)  # teal/greenish for friendly mood

    # Optionally add a short joyful sound.
    try:
        misty.sound_Joy2()
    except Exception as e:
        print(f"[WARN] Could not play joy sound: {e}")

    # ------------------ STEP 3: NODDING GESTURE ------------------
    # Nodding = move head down then up a few times in a smooth way.
    def nod_once():
        # look down a bit
        misty.move_head(pitch=10, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.35)
        # look up slightly above neutral
        misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.35)
        # return near neutral between nods
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.2, units="degrees")
        time.sleep(0.25)

    # Do multiple nods for clarity.
    for _ in range(2):
        nod_once()

    # ------------------ STEP 4: SPEAK APPROACH MESSAGE ------------------
    # Short message indicating Misty is approaching.
    misty.speak("Okay, I am coming closer to you.")

    # ------------------ RESET TO NEUTRAL ------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test execution using the provided IP.
    # Adjust the IP if your Misty is at a different address.
    test_ip = "192.168.0.100"
    misty_approach_happy_nod(test_ip)
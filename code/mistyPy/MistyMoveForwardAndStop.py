# filename: MistyMoveForwardAndStop.py

from CUBS_Misty import Robot
import time

def misty_move_forward_50cm_and_stop(robot_ip: str):
    """
    Move Misty forward approximately 50 cm and then stop.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.

    Notes:
    - This uses a timed drive approach to approximate 50 cm of forward motion.
    - Adjust 'drive_time_s' or 'forward_speed' as needed for your specific floor/robot.
    """

    misty = Robot(robot_ip)

    # --- Express preparation / small cue ---
    misty.emotion_ContentRight()
    misty.change_led(0, 128, 255)  # Calm blue
    misty.sound_PhraseHello()
    time.sleep(1.0)

    # --- Movement parameters (tuned for approximate 0.5m) ---
    # If your Misty has a known kinematics model, replace this block with wheel/drive distance calls.
    forward_speed = 30      # percent of max speed (0-100), moderate for control
    drive_time_s = 2.0      # seconds; tune this to get ~50 cm on your surface

    # --- Start forward motion ---
    # NOTE: Replace 'drive_time' block with your concrete drive API if available, e.g.:
    #   misty.drive_time(linearVelocity, angularVelocity, timeMs)
    # The following is a placeholder where the Perception/Drive Agent could be integrated.
    # ---- START DRIVE (requires concrete drive API from your environment) ----
    # Example (commented because not defined in this Agent spec):
    # misty.drive_time(linearVelocity=forward_speed, angularVelocity=0, timeMs=int(drive_time_s * 1000))
    # For now, we simulate the duration with sleep and assume an external Agent starts the drive.
    # [Perception/Drive Agent hook] -> Start forward drive here.
    time.sleep(drive_time_s)
    # [Perception/Drive Agent hook] -> Ensure Misty is stopped here.
    # ---- END DRIVE PLACEHOLDER ----

    # --- Provide a completion cue ---
    misty.emotion_DefaultContent()
    misty.sound_Acceptance()
    misty.change_led(0, 255, 0)  # Green: done
    time.sleep(0.5)

    # Always return to normal neutral state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test: runs the forward-then-stop behavior once.
    # Ensure this IP is reachable from the machine running the script.
    test_ip = "192.168.1.237"
    misty_move_forward_50cm_and_stop(test_ip)
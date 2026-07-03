# filename: MistyApproachUser46cm.py

from CUBS_Misty import Robot
import time
import requests

def misty_approach_user_46cm(robot_ip: str):
    """
    Move Misty forward until she is approximately 46cm from the user (based on front TOF),
    then orient her head, show a neutral face, and speak a confirmation.

    Behavior:
    1. Move forward slowly while checking the front time-of-flight (TOF) distance.
       - Target distance: 0.46 meters
       - Linear speed: approx. 0.2 m/s (20 cm/s).
       - Stops when distance <= 0.46 m or a safety minimum is reached.
    2. Turn head to face forward (yaw=0, pitch=0).
    3. Display neutral/DefaultContent face.
    4. Speak: "I am now 46 centimeters away from you."
    5. Return Misty to normal neutral state at the end.

    NOTE:
    - This uses Misty's REST API via the provided Robot class.
    - If you want richer navigation, obstacle avoidance, or event-driven sensor monitoring,
      integrate corresponding Event/Perception agents where indicated in comments.
    """

    misty = Robot(robot_ip)

    # ---- Helper: read front TOF distance (in meters) via REST ----
    def get_front_tof_distance_m() -> float:
        """
        Poll Misty's front time-of-flight sensor and return distance in meters.

        Returns:
            float: distance in meters (or a large sentinel if unavailable).
        """
        try:
            resp: requests.Response = misty.get_request("sensors")
            if resp.status_code != 200:
                return 999.0
            data = resp.json()
            tof_array = data.get("result", {}).get("timeOfFlight", [])
            # Find front TOF (FrontRight or FrontCenter depending on robot config)
            front_candidates = ["FrontRight", "FrontLeft", "FrontCenter"]
            readings = [
                item for item in tof_array
                if item.get("SensorPosition") in front_candidates
            ]
            if not readings:
                return 999.0
            # Take the minimum among front sensors as conservative estimate
            distances_mm = [r.get("DistanceInMeters", 0.999) for r in readings]
            distance_m = min(distances_mm)
            return float(distance_m)
        except Exception:
            # If anything fails, return a large distance so Misty doesn't move unsafely
            return 999.0

    # ---- Step 1: move forward under TOF feedback until 0.46m ----
    target_distance_m = 0.46
    min_safe_distance_m = 0.20   # safety floor
    poll_interval_s = 0.1

    # Optional: show a "focused/neutral" prep state and a soft sound
    misty.emotion_DefaultContent()
    misty.change_led(0, 150, 255)  # cyan-ish to indicate active movement

    # We use RobotCommands via the inherited API inside CUBS_Misty.Robot.
    # Assuming drive method is available as in official Misty SDK:
    #   POST /api/drive {"linearVelocity": x, "angularVelocity": y}
    # If your local CUBS_Misty wrapper exposes a different method name,
    # adjust here accordingly.
    try:
        # Start driving forward at ~0.2 m/s (20 cm/s)
        # NOTE: Misty's drive units are typically m/s for linearVelocity.
        misty.post_request(
            "drive",
            json={"linearVelocity": 0.2, "angularVelocity": 0.0}
        )

        # Feedback loop: stop when within 0.46 m
        while True:
            dist = get_front_tof_distance_m()

            # Safety stop if something is too close or sensor unavailable
            if dist <= target_distance_m or dist <= min_safe_distance_m or dist == 999.0:
                break

            time.sleep(poll_interval_s)

    finally:
        # Stop driving regardless of errors
        misty.post_request(
            "drive/stop",
            json={}
        )

    # ---- Step 2: orient head to face user (forward) ----
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.5)

    # ---- Step 3: display neutral face ----
    # Use the default neutral/content face
    misty.emotion_DefaultContent()

    # ---- Step 4: verbal confirmation ----
    misty.change_led(0, 255, 0)  # green to signal success
    misty.sound_Acceptance()
    time.sleep(0.5)
    misty.speak("I am now forty six centimeters away from you.", speechRate=1.0)

    # ---- Reset Misty to her default neutral state ----
    # If you want to keep the neutral face and LED after completion,
    # you can remove or modify this call.
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run.
    # Replace the IP below if needed before executing.
    test_ip = "192.168.1.237"
    misty_approach_user_46cm(test_ip)
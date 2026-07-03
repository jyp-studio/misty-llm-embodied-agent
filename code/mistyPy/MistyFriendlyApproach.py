# filename: MistyFriendlyApproach.py

"""
NOTE FOR USER / INTEGRATOR:
Your environment currently cannot import `CUBS_Misty` (ModuleNotFoundError).
This script assumes that the Misty SDK / CUBS_Misty package is installed and
importable as:

    from CUBS_Misty import Robot

Before running this code on your local machine, please ensure:
1. The CUBS_Misty module is installed and on your PYTHONPATH.
2. Any necessary sys.path modifications (like in your provided API scaffold)
   are applied in your environment.

Once CUBS_Misty is available, this script will:
- Suggest a forward / friendly approach using head posture.
- Set a warm LED color RGB(255, 223, 186).
- Raise the right arm to 45 degrees.
- Set head pitch to -10, yaw to 0.
- Speak a friendly greeting: "Hello! It's nice to see you!"
- Then return Misty to her neutral state using return_to_normal().
"""

from CUBS_Misty import Robot
import time


def misty_friendly_approach(robot_ip: str):
    """
    Execute a short, friendly approach sequence with Misty.

    Actions
    -------
    1. Adopt a forward/head posture that suggests moving closer in a friendly way.
       (Note: Actual base navigation / moving 90cm forward is handled by another Agent
       and is NOT implemented here.)
    2. Set the LED to a warm, welcoming color (RGB 255, 223, 186).
    3. Position the right arm in a slightly raised, open posture (45 degrees).
    4. Adjust the head pitch and yaw to convey attentive engagement (pitch -10, yaw 0).
    5. Speak a friendly greeting: "Hello! It's nice to see you!"

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot, e.g. "192.168.1.237".
    """

    # Instantiate Misty inside this function as required
    misty = Robot(robot_ip)

    try:
        # ---------------------------------------------------------
        # 1. Friendly forward posture / "move closer" suggestion
        # ---------------------------------------------------------
        # NOTE: Actual base movement to 90cm is NOT performed here, as that would
        # belong to a Navigation/Locomotion Agent. Integrate that Agent’s call here
        # if available, e.g.:
        #   navigation_agent.move_forward(distance_cm=90)
        # For now, we only use expressive posture.
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=40, units="degrees")

        # ---------------------------------------------------------
        # 2. Warm welcoming LED color (255, 223, 186)
        # ---------------------------------------------------------
        misty.change_led(red=255, green=223, blue=186)

        # ---------------------------------------------------------
        # 3. Right arm slightly raised, open posture (45 degrees)
        # ---------------------------------------------------------
        # Left arm neutral at 0, right arm to 45 degrees.
        misty.move_arms(
            leftArmPosition=0,
            rightArmPosition=45,
            leftArmVelocity=40,
            rightArmVelocity=40,
            units="degrees"
        )
        time.sleep(0.8)

        # ---------------------------------------------------------
        # 4. Attentive engagement via head motion
        # ---------------------------------------------------------
        # A small nod down then back to -10 pitch to seem engaged.
        misty.move_head(pitch=-15, yaw=0, roll=0, velocity=40, units="degrees")
        time.sleep(0.4)
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=40, units="degrees")
        time.sleep(0.4)

        # ---------------------------------------------------------
        # 5. Friendly verbal greeting
        # ---------------------------------------------------------
        misty.speak("Hello! It's nice to see you!", speechRate=1.0)
        # Give time for audio to play before resetting state
        time.sleep(3)

    finally:
        # ---------------------------------------------------------
        # Reset Misty to normal / neutral state at the end
        # ---------------------------------------------------------
        misty.return_to_normal()


# -----------------------------
# Basic test harness
# -----------------------------
if __name__ == "__main__":
    # Replace this IP with your Misty’s IP if different.
    test_ip = "192.168.1.237"
    misty_friendly_approach(test_ip)
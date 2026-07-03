# filename: MistyGentleHugApproach.py

from CUBS_Misty import Robot
import time


def misty_gentle_hug_approach(robot_ip: str):
    """
    Guide Misty through a slow, gentle 'approach for a hug' sequence.

    Requirements implemented:
    1. Convey a slow and gentle approach movement (via body language: head + arms + LED + sounds).
       NOTE: Actual base/drive motion should be implemented by a separate navigation/drive agent.
    2. Adopt a loving facial expression.
    3. Use an open-armed welcoming gesture.
    4. Speak a reassuring line inviting a gentle hug and signaling stopping at a comfortable distance.

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    # 1) PREP: soft LED & initial calm posture
    misty.change_led(255, 105, 180)  # soft pink
    misty.emotion_Love()             # loving eyes
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=30, units="degrees")
    misty.move_arms(leftArmPosition=45, rightArmPosition=45, duration=0.8)
    time.sleep(0.8)

    # 2) SLOW, GENTLE "APPROACH" BODY LANGUAGE
    #    (head and arms subtly moving while Misty would be driven closer by another system)
    #    If you have a drive/navigation agent, integrate it where commented below.

    # --- BEGIN: place for navigation/drive control (not implemented here) ---
    # Example (pseudo-code to be implemented by a different Agent/system):
    # navigation_agent.drive_forward_slow(target_distance_cm=60, speed_level="slow")
    # --- END: place for navigation/drive control ---

    # Subtle forward-lean & exploratory glances to simulate approach
    misty.move_head(pitch=10, yaw=-20, roll=0, velocity=20, units="degrees")
    time.sleep(0.8)
    misty.move_head(pitch=5, yaw=20, roll=0, velocity=20, units="degrees")
    time.sleep(0.8)
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=15, units="degrees")
    time.sleep(0.8)

    # Gentle breathing-like arm motion as she "approaches"
    for _ in range(2):
        misty.move_arms(leftArmPosition=60, rightArmPosition=60, duration=1.0)
        time.sleep(1.0)
        misty.move_arms(leftArmPosition=40, rightArmPosition=40, duration=1.0)
        time.sleep(1.0)

    # 3) OPEN-ARM WELCOMING GESTURE (final position, "stopping" at safe distance)
    # arms_open = arms low and open from the sides, inviting but non-intrusive
    misty.sound_Acceptance(volume=60)
    misty.move_head(pitch=-5, yaw=0, roll=0, velocity=20, units="degrees")  # slight upward gaze
    misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, duration=1.2)
    time.sleep(1.2)

    # 4) SPEAK REASSURING LINE FOR A GENTLE HUG
    # Provided target line:
    # "On my way for a gentle hug. I’ll stop right here—lean in when you’re ready."
    misty.speak(
        text="On my way for a gentle hug. I will stop right here; lean in when you are ready.",
        speechRate=0.9
    )

    # Hold the open posture briefly to give the user time to respond
    time.sleep(3.0)

    # 5) RESET TO NEUTRAL STATE
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test: run the gentle hug approach sequence once on the given IP.
    # Replace with your robot's IP if needed.
    test_ip = "192.168.1.237"
    misty_gentle_hug_approach(test_ip)
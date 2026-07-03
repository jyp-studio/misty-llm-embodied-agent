# filename: MistyNeutralConcernNod.py

from CUBS_Misty import Robot
import time

def misty_neutral_concern_nod(robot_ip: str):
    """
    Have Misty:
    1. Adopt a neutral facial expression.
    2. Perform a nodding gesture.
    3. Speak a supportive line expressing concern about coughing and offering help.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # 1. Neutral / concerned-neutral facial expression and LED
    misty.emotion_ApprehensionConcerned()
    misty.change_led(255, 255, 255)  # neutral white

    # 2. Nodding gesture: small repeated pitch movement
    # Start from a slightly attentive pose
    misty.move_head(pitch=-5, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.4)

    for _ in range(3):
        # Nod down
        misty.move_head(pitch=10, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.35)
        # Nod up
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.35)

    # Return head to a gentle attentive position before speaking
    misty.move_head(pitch=-5, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.4)

    # 3. Supportive speech about coughing and offering help
    line = (
        "You sound like you're coughing a lot. "
        "Are you okay? Do you want me to get you some water, or call someone for help?"
    )
    misty.speak(text=line, speechRate=1.0)

    # Small pause to allow speech to mostly complete before resetting
    time.sleep(4)

    # Reset Misty to her normal state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Test run for the specified Misty IP
    test_ip = "192.168.1.237"
    misty_neutral_concern_nod(test_ip)
# filename: MistyGentleBreakOffer.py

from CUBS_Misty import Robot
import time

def misty_gentle_break_offer(robot_ip: str):
    """
    Misty gently approaches the user, keeps a neutral expression, 
    nods, and offers a short break or relaxing activity.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty
    misty = Robot(robot_ip)

    # 1. Approach the user in a gentle manner
    # NOTE: MistyActionAgent is not allowed to control navigation directly.
    # If movement/navigation is needed, integrate with the Navigation/Perception agent here.
    # For now, we simulate a gentle "approach" using body language and lights.
    misty.change_led(180, 220, 255)  # Soft calm light-blue
    misty.emotion_DefaultContent()   # Neutral, friendly base face

    # Simulated gentle approach: slight head and arm movement as if getting user’s attention
    misty.move_head(pitch=5, yaw=0, roll=0, duration=1.0, units="degrees")
    misty.move_arms(leftArmPosition=20, rightArmPosition=20, duration=1.0)
    time.sleep(1.0)

    # 2. Maintain a neutral facial expression
    misty.emotion_DefaultContent()

    # 3. Perform a nodding gesture (gentle, repeated nods)
    for _ in range(2):
        misty.move_head(pitch=15, yaw=0, roll=0, duration=0.4, units="degrees")  # nod down
        time.sleep(0.4)
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.4, units="degrees")   # back to neutral
        time.sleep(0.4)

    # 4. Speak a short message offering a break or relaxing activity
    misty.sound_Sleepy2()  # Soft sleepy tone to match the context
    time.sleep(0.6)
    misty.speak(
        text="You look a bit tired. Would you like to take a short break, or do something relaxing together?",
        speechRate=0.95
    )

    # Give time for speech to finish before resetting
    time.sleep(5)

    # Reset Misty to normal state
    misty.return_to_normal()


if __name__ == "__main__":
    # Test run on the provided IP
    misty_gentle_break_offer("192.168.1.237")
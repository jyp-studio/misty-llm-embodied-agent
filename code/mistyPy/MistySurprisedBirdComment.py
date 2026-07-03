# filename: MistySurprisedBirdComment.py

from CUBS_Misty import Robot
import time

def misty_surprised_bird_comment(robot_ip: str):
    """
    1. Show a surprised facial expression.
    2. Move the head in a nodding gesture.
    3. Speak a playful surprised line that comments on a loud sound and asks
       if the user is pretending to be a bird or just making fun sounds.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty robot
    misty = Robot(robot_ip)

    # 1. Surprised facial expression + LED + sound
    misty.emotion_Surprise()
    misty.change_led(0, 150, 255)  # bright cyan/blue for surprise
    misty.sound_Amazement2()
    time.sleep(0.6)

    # 2. Nodding gesture with the head
    # Start slightly neutral
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=60, units="degrees")
    time.sleep(0.4)

    # Perform a few nods (down-up cycles)
    for _ in range(3):
        misty.move_head(pitch=20, yaw=0, roll=0, velocity=70, units="degrees")   # look slightly down
        time.sleep(0.35)
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=70, units="degrees")  # look slightly up
        time.sleep(0.35)

    # Return head closer to neutral surprised pose
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=70, units="degrees")
    time.sleep(0.3)

    # 3. Speak a playful surprised line
    # Matching the user's requested content
    misty.speak(
        text="Whoa, that was loud! Are you pretending to be a bird, or just making some fun sounds?",
        speechRate=1.1
    )

    # Give time for speech to finish before resetting
    time.sleep(4)

    # Reset Misty to her normal neutral state
    misty.return_to_normal()


# Simple test harness
if __name__ == "__main__":
    # Replace the IP below with your Misty's IP if different
    misty_surprised_bird_comment("192.168.1.237")
# filename: MistyHappyOrangeNod.py

from CUBS_Misty import Robot
import time

def misty_happy_orange_nod(robot_ip: str):
    """
    Have Misty:
      1. Move to indicate attention in a neutral manner.
      2. Show a happy facial expression.
      3. Perform a nodding gesture.
      4. Speak the provided sentence.
      5. Set LED to orange.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # 1. Move to indicate attention in a neutral manner:
    #    Center head but add a small, smooth motion to "wake up" attention.
    misty.move_head(pitch=5, yaw=0, roll=0, velocity=40, units="degrees")
    misty.move_arms(leftArmPosition=10, rightArmPosition=10, leftArmVelocity=40, rightArmVelocity=40)
    time.sleep(0.6)

    # Small return toward neutral, still attentive
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=40, units="degrees")
    time.sleep(0.4)

    # 2. Show a happy facial expression
    misty.emotion_Joy()

    # 3. Perform a nodding gesture (subtle, friendly)
    #    Nodding is a movement in head pitch.
    for _ in range(2):
        misty.move_head(pitch=15, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.3)
        misty.move_head(pitch=-5, yaw=0, roll=0, velocity=60, units="degrees")
        time.sleep(0.3)
    # Return to neutral pitch after nod
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
    time.sleep(0.4)

    # 4. Speak the provided sentence
    text = "I see an orange color. I’ll set my LED to orange now."
    misty.speak(text=text, speechRate=1.0)

    # Give a short moment for the speech to start before changing LED
    time.sleep(0.5)

    # 5. Indicate an orange LED state
    #    Orange ≈ (255, 165, 0)
    misty.change_led(red=255, green=165, blue=0)

    # Optional gentle confirmatory nod with LED orange already on
    misty.move_head(pitch=8, yaw=0, roll=0, velocity=40, units="degrees")
    time.sleep(0.3)
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=40, units="degrees")
    time.sleep(0.3)

    # Finally, return Misty to her normal neutral state
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run.
    # NOTE: Replace the IP below with your Misty's IP if different.
    misty_happy_orange_nod("192.168.0.100")
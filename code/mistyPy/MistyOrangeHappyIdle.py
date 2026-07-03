# filename: MistyOrangeHappyIdle.py

from CUBS_Misty import Robot
import time

def misty_see_orange_and_change_led(robot_ip: str):
    """
    Have Misty:
      1. Show a happy facial expression.
      2. Remain in an idle gesture (neutral / relaxed body).
      3. Speak about seeing orange and changing the LED to orange.
      4. Set the LED color to orange.
    At the end, Misty is reset back to her normal neutral state.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Initialize Misty
    misty = Robot(robot_ip)

    # 1. Show a happy facial expression (use a joyful default content face)
    misty.emotion_Joy()
    # Brief pause to let the face settle visually
    time.sleep(0.3)

    # 2. Idle gesture: keep body relaxed / neutral
    #    -> Arms to neutral, head looking forward with a slight friendly tilt
    misty.move_arms(leftArmPosition=0, rightArmPosition=0, leftArmVelocity=40, rightArmVelocity=40)
    misty.move_head(pitch=-5, yaw=0, roll=0, velocity=40, units="degrees")
    time.sleep(0.5)

    # 3. Speak about seeing orange and changing the LED to orange
    misty.sound_Joy2()  # light happy sound before speaking
    time.sleep(0.3)
    misty.speak("I see orange, so I’ll change my LED to orange now.", speechRate=1.0)
    # Allow time for the speech to complete before LED change for a natural sequence
    time.sleep(3)

    # 4. Set the LED color to orange (e.g., RGB: 255, 165, 0)
    misty.change_led(255, 165, 0)

    # Small confirmation pause with a warm expression
    misty.emotion_Joy2()
    misty.sound_Acceptance()
    time.sleep(1.0)

    # Return Misty to her normal neutral state
    misty.return_to_normal()


if __name__ == "__main__":
    # TEST: run the behavior on the specified Misty IP
    test_ip = "192.168.1.237"
    misty_see_orange_and_change_led(test_ip)
# filename: MistyHappyDance.py

from CUBS_Misty import Robot
import time

def misty_happy_dance(robot_ip: str):
    """
    Make Misty:
    1. Express a happy facial emotion.
    2. Raise both arms in an expressive gesture.
    3. Perform a joyful dance-like movement.
    4. Speak an enthusiastic line about dancing.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # 1. Express a happy facial emotion
    misty.emotion_Joy2()
    misty.change_led(0, 255, 0)  # Bright green for happy mood
    misty.sound_Joy2()
    time.sleep(0.6)

    # 2. Raise both arms in an expressive "arms up" gesture
    misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.8)  # arms up
    time.sleep(0.8)

    # 3. Perform a joyful dance-like movement
    #    - Sway head and change LED colors
    for _ in range(2):
        misty.move_head(pitch=-10, yaw=40, roll=0, duration=0.4)
        time.sleep(0.4)
        misty.move_head(pitch=-10, yaw=-40, roll=0, duration=0.4)
        time.sleep(0.4)

    # Small arm bounces for extra expression
    for _ in range(3):
        misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, duration=0.25)
        time.sleep(0.25)
        misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.25)
        time.sleep(0.25)

    # Fun LED breathing effect during the dance
    misty.transition_led(0, 255, 0, 0, 128, 255, "Breathe", 700)
    time.sleep(1.4)

    # 4. Speak an enthusiastic line about dancing
    line = "Of course! I’ll dance just for you. Get ready for my happiest moves!"
    misty.sound_Joy3()
    time.sleep(0.4)
    misty.speak(text=line, speechRate=1.05)

    # Give a moment for speech to finish before resetting
    time.sleep(4)

    # Reset Misty to normal state
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run
    misty_happy_dance("192.168.1.237")
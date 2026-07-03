# filename: MistyHappyGoodnightWave.py

from CUBS_Misty import Robot
import time

def misty_happy_goodnight_wave(robot_ip: str):
    """
    Perform a friendly goodnight routine:
      1. Show a happy facial expression.
      2. Wave in a friendly manner.
      3. Speak a goodnight phrase in a friendly tone.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # 1. Happy facial expression + warm LED + soft joyful sound
    misty.emotion_Joy()              # Happy eyes/mouth
    misty.change_led(255, 215, 0)    # Warm golden color
    misty.sound_Joy2()               # Light joyful sound
    time.sleep(0.8)

    # 2. Friendly wave:
    #    - Raise right arm, small head tilt, then gentle waving motion.
    misty.move_head(pitch=-10, yaw=10, roll=5, duration=0.7, units="degrees")
    misty.move_arms(leftArmPosition=20, rightArmPosition=-20, duration=0.7)  # Raise right arm
    time.sleep(0.7)

    # Gentle waving: small repeated right-arm motion
    for _ in range(3):
        misty.move_arms(rightArmPosition=-29, duration=0.4)  # a bit more up
        time.sleep(0.4)
        misty.move_arms(rightArmPosition=-5, duration=0.4)   # a bit down
        time.sleep(0.4)

    # Relax arms slightly before speaking
    misty.move_arms(leftArmPosition=10, rightArmPosition=10, duration=0.6)
    misty.move_head(pitch=-5, yaw=0, roll=0, duration=0.6, units="degrees")
    time.sleep(0.6)

    # 3. Speak a friendly goodnight phrase
    misty.speak("Goodnight! Sweet dreams.", speechRate=1.0)
    time.sleep(3.0)  # Allow time for speech to finish (approximate)

    # Optionally, a soft sleepy sound and dim LED to close the routine
    misty.sound_Sleepy()
    misty.transition_led(255, 215, 0, 50, 50, 50, "Breathe", 1500)
    time.sleep(2.0)

    # Always return Misty to her normal neutral state at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Test the happy goodnight wave behavior.
    # Replace the IP below with your Misty robot's IP if needed.
    misty_happy_goodnight_wave("192.168.1.237")
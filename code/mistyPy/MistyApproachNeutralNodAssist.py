# filename: MistyApproachNeutralNodAssist.py

from CUBS_Misty import Robot
import time


def misty_approach_neutral_nod_assist(robot_ip: str):
    """
    Complex action for Misty:
      1. Move in a way that corresponds to an intended approach toward the user
      2. Maintain a neutral facial expression
      3. Perform a nodding gesture
      4. Speak a greeting asking if the user needs assistance

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot (e.g., "192.168.1.237").
    """

    # Instantiate Misty
    misty = Robot(robot_ip)

    try:
        # 1) "Approach" the user with a small forward lean and arm motion
        #    (Only motion primitives are available in this Agent – no navigation.)
        #    This simulates a gentle lean-in, like taking a small step forward.
        misty.emotion_DefaultContent()              # Neutral/standard face
        misty.change_led(255, 255, 255)             # Neutral white LED

        # Small forward lean with slight arm drop to suggest approach
        misty.move_head(pitch=10, yaw=0, roll=0, velocity=40, units="degrees")
        misty.move_arms(leftArmPosition=30, rightArmPosition=30, duration=0.8)
        time.sleep(0.8)

        # Optional subtle “arrival” adjustment
        misty.move_head(pitch=5, yaw=0, roll=0, velocity=40, units="degrees")
        time.sleep(0.4)

        # 2) Ensure neutral facial expression is maintained
        misty.emotion_DefaultContent()
        misty.change_led(200, 200, 255)             # Soft neutral-pleasant white/blue

        # 3) Perform a nodding gesture (pitching head down/up a few times)
        for _ in range(2):
            misty.move_head(pitch=15, yaw=0, roll=0, velocity=60, units="degrees")
            time.sleep(0.35)
            misty.move_head(pitch=-5, yaw=0, roll=0, velocity=60, units="degrees")
            time.sleep(0.35)

        # Return head to a comfortable neutral after nod
        misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, units="degrees")
        time.sleep(0.4)

        # 4) Speak greeting asking if user needs assistance
        misty.sound_PhraseHello(volume=70)
        time.sleep(0.6)  # brief pause before TTS so sounds don't overlap oddly

        misty.speak(
            text="Hello! Is there something I can assist you with?",
            speechRate=1.0
        )

        # allow time for speech to complete before resetting
        time.sleep(4.0)

    finally:
        # Always reset Misty to normal state at the end of the complex action
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run using the provided IP.
    # Adjust the IP if your Misty is on a different address.
    misty_approach_neutral_nod_assist("192.168.1.237")
# filename: MistyWildHappyDance.py

from CUBS_Misty import Robot
import time


def misty_wild_happy_dance(robot_ip: str):
    """
    Perform a very energetic, happy, wild dance with raised arms and an enthusiastic line.

    Behavior:
    1. Energetic happy mood: bright LED, joyful / goofy face, excited sounds.
    2. Arms raised and moving like a wild dance.
    3. Spoken line:
       “Oh yeah, let’s get wild! Watch this! I’m going to dance like crazy just for you!”
    4. Uses multiple sounds and movements for vivid effect.
    5. Returns Misty to a normal neutral state at the end.

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot (e.g. "192.168.1.237").
    """

    # IMPORTANT: Never embed or use API keys in this function. They are not required to drive Misty.
    misty = Robot(robot_ip)

    # --- Setup: energetic, happy mood ---
    # Big joyful/goofy expression + bright warm LED and joyful sound
    misty.emotion_JoyGoofy2()
    misty.change_led(255, 165, 0)  # energetic orange
    misty.sound_Joy3()
    time.sleep(0.5)

    # Raise both arms up (wild, "arms_up" pose)
    misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.7)
    time.sleep(0.7)

    # Slight head tilt and look towards the user, like prepping to shout
    misty.move_head(pitch=-10, yaw=15, roll=5, duration=0.5, units="degrees")
    time.sleep(0.5)

    # --- Enthusiastic line ---
    misty.speak(
        "Oh yeah, let's get wild! Watch this! I'm going to dance like crazy just for you!",
        speechRate=1.15,
        pitch=1.1,
    )
    # Give time for speech to largely finish before super-fast motions
    time.sleep(4.0)

    # --- Wild dance sequence with arms up ---

    # Phase 1: side sway with arms high
    misty.emotion_JoyGoofy3()
    misty.transition_led(255, 215, 0, 255, 105, 180, "Breathe", 700)  # gold <-> pink
    for _ in range(3):
        misty.move_head(pitch=-5, yaw=35, roll=8, duration=0.4, units="degrees")
        misty.move_arms(leftArmPosition=-20, rightArmPosition=-29, duration=0.4)
        misty.sound_Joy2()
        time.sleep(0.4)

        misty.move_head(pitch=-5, yaw=-35, roll=-8, duration=0.4, units="degrees")
        misty.move_arms(leftArmPosition=-29, rightArmPosition=-20, duration=0.4)
        time.sleep(0.4)

    # Phase 2: fast arm pumps and head bobs
    misty.transition_led(0, 255, 127, 0, 191, 255, "Blink", 300)  # neon green / aqua blinking
    for _ in range(4):
        # pump arms down a bit
        misty.move_arms(leftArmPosition=20, rightArmPosition=20, duration=0.25)
        misty.move_head(pitch=10, yaw=0, roll=0, duration=0.25, units="degrees")
        misty.sound_Amazement2()
        time.sleep(0.25)

        # pump arms back up
        misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.25)
        misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.25, units="degrees")
        time.sleep(0.25)

    # Phase 3: crazy spin look left-right with quick arm waves
    misty.emotion_EcstacyStarryEyed()
    misty.sound_Ecstacy2()
    for _ in range(3):
        # look far left, right arm slightly lower
        misty.move_head(pitch=-5, yaw=80, roll=0, duration=0.3, units="degrees")
        misty.move_arms(leftArmPosition=-29, rightArmPosition=10, duration=0.3)
        time.sleep(0.3)

        # look far right, left arm slightly lower
        misty.move_head(pitch=-5, yaw=-80, roll=0, duration=0.3, units="degrees")
        misty.move_arms(leftArmPosition=10, rightArmPosition=-29, duration=0.3)
        time.sleep(0.3)

    # Final pose: both arms high, head centered, big joyful face and sound
    misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=0.6)
    misty.move_head(pitch=-8, yaw=0, roll=0, duration=0.6, units="degrees")
    misty.emotion_Joy()
    misty.sound_Joy4()
    misty.transition_led(0, 255, 0, 0, 255, 255, "Breathe", 900)
    time.sleep(1.2)

    # --- End: return Misty to a neutral, normal state ---
    misty.return_to_normal()


# Simple test runner – adjust IP before running.
if __name__ == "__main__":
    # Replace this with your Misty IP if different
    test_ip = "192.168.1.237"
    misty_wild_happy_dance(test_ip)
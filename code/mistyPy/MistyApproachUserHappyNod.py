# filename: MistyApproachUserHappyNod.py

from CUBS_Misty import Robot
import time

def misty_approach_user_happy_nod(robot_ip: str):
    """
    Complex action sequence for Misty:
      1. Move closer to the user (simulated with animated body language).
      2. Adopt a happy facial expression.
      3. Perform a nodding gesture.
      4. Speak a reassuring phrase to the user.
    
    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot.
    
    Notes
    -----
    - This function uses only MistyActionAgent capabilities: expressions, LEDs,
      head and arm motions, sounds, and onboard TTS.
    - Any navigation / locomotion (base driving) that might be needed should
      be implemented by another Agent (e.g., a NavigationAgent). You can
      integrate such functionality where indicated in the comments below.
    """
    misty = Robot(robot_ip)

    # ------------------------------------------------------------
    # 0. OPTIONAL: Approach / navigation (to be done by another Agent)
    # ------------------------------------------------------------
    # If you have a NavigationAgent or base driving API, integrate it here,
    # for example:
    #
    #   navigation_agent.drive_forward(target_dist=90, speed="normal")
    #
    # Since MistyActionAgent is not allowed to handle navigation or events,
    # this code intentionally does not move the base. Instead, we simulate
    # “coming closer” using expressive body language, LEDs, and sounds.

    # ------------------------------------------------------------
    # 1. Prepare a warm "coming closer" state (LED + expression + sound)
    # ------------------------------------------------------------
    # Happy / joyful face and warm LED color
    misty.emotion_Joy2()              # Bright, happy expression
    misty.change_led(255, 165, 0)     # Soft orange to feel friendly
    misty.sound_Joy2()                # Cheerful sound cue
    time.sleep(1.0)

    # ------------------------------------------------------------
    # 2. Simulate moving closer with subtle body motions
    # ------------------------------------------------------------
    # Arms slightly raise and head tilts as if leaning in toward the user
    misty.move_arms(leftArmPosition=-10, rightArmPosition=-10, duration=1.0)
    misty.move_head(pitch=-15, yaw=0, roll=0, duration=1.0, units="degrees")
    time.sleep(1.0)

    # Gentle LED "breathing" in a warm color while “approaching”
    misty.transition_led(255, 165, 0, 255, 215, 0, "Breathe", 1000)
    time.sleep(2.0)

    # ------------------------------------------------------------
    # 3. Perform a nodding gesture (gesture = "nod")
    # ------------------------------------------------------------
    # Use head pitch to nod several times
    for _ in range(3):
        misty.move_head(pitch=-10, yaw=0, roll=0, duration=0.25, units="degrees")
        time.sleep(0.25)
        misty.move_head(pitch=10, yaw=0, roll=0, duration=0.25, units="degrees")
        time.sleep(0.25)
    # Return head near neutral but still slightly attentive
    misty.move_head(pitch=-5, yaw=0, roll=0, duration=0.4, units="degrees")
    time.sleep(0.4)

    # ------------------------------------------------------------
    # 4. Speak a reassuring phrase (speech)
    # ------------------------------------------------------------
    # Face remains happy, LED stays warm while speaking
    misty.emotion_Joy()  # maintain a joyful expression
    reassuring_text = "Okay, I’m coming over to you now!"
    misty.speak(text=reassuring_text, speechRate=1.0)
    # Allow time for speech to complete before resetting
    time.sleep(3.0)

    # ------------------------------------------------------------
    # 5. Reset Misty back to her neutral state
    # ------------------------------------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run
    # Replace the IP below with your Misty's IP if different.
    test_ip = "192.168.1.237"
    misty_approach_user_happy_nod(test_ip)
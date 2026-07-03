# filename: MistyEmpatheticApproach.py

from CUBS_Misty import Robot
import time

def misty_empathetic_approach(robot_ip: str):
    """
    Perform an empathetic approach behavior:
      1. Move closer in a gentle and supportive way.
      2. Adopt a sad and empathetic facial expression.
      3. Use an open-armed gesture to convey availability for comfort.
      4. Speak a short, reassuring message offering emotional support and a choice
         between a hug or space, while indicating willingness to listen.
         
    Parameters:
        robot_ip (str): The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    try:
        # 1. Move closer in a gentle and supportive way.
        # NOTE: The actual driving / distance control is handled by another Agent (e.g., Perception/Navigation).
        # Here we assume that such functionality will be added externally.
        # ---------------------- INTEGRATION POINT ----------------------
        # Use Misty's drive or navigation API here to move ~60 cm forward at a slow speed,
        # for example (pseudocode only, DO NOT UNCOMMENT):
        #
        #   misty.drive(linearVelocity=10, angularVelocity=0, timeMs=3000)
        #
        # This should be implemented by the appropriate Navigation/Perception Agent.
        # ---------------------------------------------------------------
        # As a placeholder for "gentle approach", we use subtle body language: head/arms + LED.
        misty.transition_led(
            0, 0, 255,      # start: soft blue
            0, 255, 255,    # end: teal
            "Breathe",
            1200
        )

        # Slight head tilt as if gently focusing on the person while "approaching"
        misty.move_head(pitch=5, yaw=10, roll=0, velocity=40, units="degrees")
        time.sleep(1.0)

        # 2. Adopt a sad and empathetic facial expression.
        misty.emotion_Sadness()
        # Soften LED to a calmer, dimmer blue
        misty.change_led(0, 70, 180)

        # 3. Use an open-armed gesture to convey availability for comfort.
        # Open both arms slightly forward and down, like a gentle "available for hug" posture.
        misty.move_arms(leftArmPosition=40, rightArmPosition=40, leftArmVelocity=40, rightArmVelocity=40)
        time.sleep(1.0)

        # Add a small, slow arm movement to feel natural and inviting
        misty.move_arms(leftArmPosition=20, rightArmPosition=20, leftArmVelocity=25, rightArmVelocity=25)
        time.sleep(1.0)
        misty.move_arms(leftArmPosition=35, rightArmPosition=35, leftArmVelocity=25, rightArmVelocity=25)
        time.sleep(1.0)

        # 4. Speak a short, reassuring message, with a gentle sound cue.
        # Soft emotional cue first (very quiet sadness tone).
        misty.sound_Sadness(volume=40)
        time.sleep(0.8)

        # Reassuring message
        misty.speak(
            text="I’m here for you. It’s okay to feel upset. "
                 "Would you like a hug, or would you prefer a little space? I can listen.",
            speechRate=0.9
        )

        # Give time for the speech and for the user to react before resetting.
        time.sleep(6)

    finally:
        # Always reset Misty to her normal state at the end.
        misty.return_to_normal()


if __name__ == "__main__":
    # Test call for the empathetic approach behavior.
    # Replace the IP below with the current Misty IP if different.
    misty_empathetic_approach("192.168.1.237")
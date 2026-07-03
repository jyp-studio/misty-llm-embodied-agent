# filename: MistyNeutralNodGreeting.py

from CUBS_Misty import Robot
import time

def misty_neutral_nod_greeting(robot_ip: str):
    """
    Have Misty:
      1. Adopt a neutral facial expression.
      2. Perform a nodding gesture.
      3. Deliver a short, welcoming spoken greeting that offers conversation or quiet time.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    # Instantiate Misty inside the function
    misty = Robot(robot_ip)

    try:
        # 1. Neutral face + soft neutral LED
        misty.emotion_DefaultContent()
        misty.change_led(200, 200, 255)  # soft neutral white/blue

        # Slight head center before nod
        misty.move_head(pitch=0, yaw=0, roll=0, velocity=40, units="degrees")
        time.sleep(0.5)

        # 2. Perform a gentle nodding gesture
        # small down-up-down to look natural and calm
        for _ in range(2):
            misty.move_head(pitch=10, yaw=0, roll=0, duration=0.3, units="degrees")   # down
            time.sleep(0.3)
            misty.move_head(pitch=-5, yaw=0, roll=0, duration=0.3, units="degrees")   # up slightly above neutral
            time.sleep(0.3)
        # return closer to neutral pitch
        misty.move_head(pitch=0, yaw=0, roll=0, duration=0.3, units="degrees")
        time.sleep(0.4)

        # 3. Welcoming spoken greeting (as specified by the user)
        greeting_text = (
            "Hi there. I’m here if you’d like to chat or need anything. "
            "Would you prefer some company or a little quiet time?"
        )
        misty.speak(text=greeting_text, speechRate=1.0)
        # Allow time for speech to complete (approximate)
        time.sleep(6)

    finally:
        # Always reset Misty to a normal neutral state at the end
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run against the provided IP.
    # Adjust the IP if your Misty uses a different address.
    misty_neutral_nod_greeting("192.168.1.237")
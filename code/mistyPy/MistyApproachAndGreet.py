# filename: MistyApproachAndGreet.py

from CUBS_Misty import Robot
import time

def misty_approach_and_greet(robot_ip: str):
    """
    Guide Misty to turn toward the user, roll closer, adjust head and eyes,
    and speak to confirm a comfortable distance.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    try:
        # 1) Turn the body to face the user
        # NOTE: Misty's torso rotation is typically controlled via drive/heading.
        # Here we simulate turning-in-place to face the user.
        # (If you have a higher‑level "turn to bearing" primitive, integrate it here.)
        #
        # Assumption: user is somewhere off to one side; we do a smooth ~45° turn.
        # Positive angular velocity turns left; negative turns right (check your SDK).
        turn_speed = 30  # percent of max; conceptual – integrate with your drive API.
        turn_duration = 1.0  # seconds for a gentle turn

        # --- PLACEHOLDER: Replace this block with your drive/turn API integration ---
        # For example, using CUBS_Misty/RobotCommands, you might do:
        #   misty.drive(0, turn_speed)       # rotate in place
        #   time.sleep(turn_duration)
        #   misty.stop()
        #
        # Since drive APIs are not part of this MistyActionAgent spec, we only
        # document where to call them and do not implement them.
        # --------------------------------------------------------------------------
        time.sleep(turn_duration)  # simulate time spent turning

        # 2) Move the base forward to a comfortable distance from the user
        # The user indicated source distance was ~197cm; we move closer by ~80cm.
        # Again, use your platform's drive-forward primitive here.
        forward_duration = 1.2  # seconds of gentle forward motion at slow speed
        forward_speed = 20      # percent of max speed (conceptual)

        # --- PLACEHOLDER: Integrate your "drive forward" call here ---
        # Example (NOT implemented as per instruction):
        #   misty.drive(forward_speed, 0)
        #   time.sleep(forward_duration)
        #   misty.stop()
        # -------------------------------------------------------------
        time.sleep(forward_duration)  # simulate travel time

        # 3) Tilt the head slightly upward while keeping it centered
        # Slight upward pitch (look up a bit), yaw and roll centered
        misty.move_head(pitch=-10, yaw=0, roll=0, velocity=35, units="degrees", duration=0.7)
        time.sleep(0.7)

        # 4) Set the eyes to an engaged visual state
        # Use a pleasant expression and a slightly bright LED.
        # We'll model "engaged" as a joyful/attentive face + ~80% white LED.
        misty.emotion_Joy()
        misty.change_led(red=200, green=200, blue=200)  # ~80% white

        # 5) Speak to explain moving closer and ask about comfort
        misty.speak(
            "I've moved a bit closer so we can interact more comfortably. "
            "Does this distance feel okay for you, or would you like me to move closer or farther?",
            speechRate=1.0
        )

        # Give time for speech to complete before resetting
        time.sleep(4.0)

    finally:
        # Always return Misty to neutral at the end of this action
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test invocation.
    # Replace the IP below with your Misty's IP if different.
    misty_approach_and_greet("192.168.1.237")
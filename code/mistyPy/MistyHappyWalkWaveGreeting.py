# filename: MistyHappyWalkWaveGreeting.py

from CUBS_Misty import Robot
import time

def misty_happy_walk_wave_greeting(robot_ip: str,
                                   target_dist: float = -1.0,
                                   speed: str = "normal",
                                   face: str = "happy",
                                   gesture: str = "wave",
                                   speech: str = "Hello! I’m doing great, thank you for asking. How are you today?"):
    """
    Perform a natural sequence:
      1. Move forward or backward with a natural pace (based on target_dist sign).
      2. Express a happy facial state.
      3. Perform a waving gesture.
      4. Speak a friendly greeting.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot.
    target_dist : float
        Distance to move in meters.
        > 0  => move forward
        < 0  => move backward
        == 0 => no translational movement
    speed : str
        Motion speed profile: "slow", "normal", or "fast".
        This is mapped to duration and pauses in the routine.
    face : str
        Requested face state. Currently supports "happy" and defaults otherwise.
    gesture : str
        Requested gesture. Currently supports "wave" and defaults otherwise.
    speech : str
        Text Misty will speak at the end of the sequence.
    """

    misty = Robot(robot_ip)

    # -------------- Helper: map speed to timing profile --------------
    if speed == "slow":
        move_duration = 2.0
        wave_pause = 0.7
    elif speed == "fast":
        move_duration = 0.8
        wave_pause = 0.3
    else:  # "normal" or unknown
        move_duration = 1.2
        wave_pause = 0.5

    # -------------- Step 1: Move forward/backward at natural pace --------------
    # NOTE:
    # The base Robot API stub given in the prompt does not expose explicit drive APIs.
    # Here, we assume that another Agent or an extended Robot API provides a method
    # like `drive_time` or `drive` to move Misty.
    #
    # >>> Integrate Perception/Locomotion Agent here:
    # If your Robot class exposes a method such as:
    #     misty.drive(linearVelocity, angularVelocity, time_ms)
    # or
    #     misty.drive_time(linearVelocity, angularVelocity, time_ms)
    # you can replace the pseudo-code below with the appropriate call.
    #
    # For now, we only simulate timing with time.sleep so that the rest of the
    # action sequence (face, gesture, speech) is still valid.
    if target_dist != 0:
        # Determine direction: forward vs backward
        # (Positive = forward, Negative = backward)
        # PSEUDO-IMPLEMENTATION ONLY – replace with actual drive command.
        # Example (if your API supported it):
        #   linear_vel = 250 if target_dist > 0 else -250
        #   move_time_ms = int(abs(target_dist) / 0.25 * 1000)  # example calc
        #   misty.drive_time(linear_vel, 0, move_time_ms)
        #
        # Here we simply wait to represent the movement period.
        time.sleep(move_duration)

    # -------------- Step 2: Express a happy facial state --------------
    if face.lower() == "happy":
        # Use a joyful / goofy joy face to appear visibly happy
        misty.emotion_JoyGoofy()
    else:
        misty.emotion_DefaultContent()

    # Give a subtle LED accent for happiness (soft green/blue)
    misty.change_led(0, 180, 255)

    # -------------- Step 3: Perform a waving gesture --------------
    if gesture.lower() == "wave":
        # Raise right arm and perform a few small side-to-side swings
        # Neutral arms first
        misty.move_arms(leftArmPosition=0, rightArmPosition=0, duration=0.6)
        time.sleep(0.6)

        # Raise right arm up to waving position
        misty.move_arms(leftArmPosition=0, rightArmPosition=-20, duration=0.5)
        time.sleep(0.5)

        # Small waves with right arm while adding a friendly head tilt
        misty.move_head(pitch=-10, yaw=15, roll=0, duration=0.4)
        time.sleep(0.4)

        for _ in range(3):
            misty.move_arms(rightArmPosition=-5, duration=0.3)
            time.sleep(wave_pause)
            misty.move_arms(rightArmPosition=-25, duration=0.3)
            time.sleep(wave_pause)

        # Return arm closer to neutral, keep slightly up while speaking
        misty.move_arms(rightArmPosition=-10, duration=0.4)
        time.sleep(0.4)

    # -------------- Step 4: Speak a friendly greeting --------------
    # Add a small anticipatory head motion before speaking
    misty.move_head(pitch=-5, yaw=0, roll=0, duration=0.4)
    time.sleep(0.4)

    # Play a joyful sound to complement speech
    misty.sound_Joy2()
    time.sleep(0.3)

    # Use Misty's built-in TTS
    misty.speak(speech, speechRate=1.0)

    # -------------- Clean up: return Misty to normal state --------------
    # Allow a brief moment after speaking before resetting
    time.sleep(1.0)
    misty.return_to_normal()


# ------------------------------ TEST SUITE ------------------------------
def _test_happy_walk_wave_greeting():
    """
    Basic functional test for misty_happy_walk_wave_greeting.

    NOTE:
    - This test assumes the Misty robot is reachable at the given IP.
    - It will execute the full sequence once.
    """
    test_ip = "192.168.1.237"  # Replace with your Misty IP if different

    # Use the values provided by the caller specification:
    misty_happy_walk_wave_greeting(
        robot_ip=test_ip,
        target_dist=-1,  # negative suggests backward; movement timing is simulated
        speed="normal",
        face="happy",
        gesture="wave",
        speech="Hello! I’m doing great, thank you for asking. How are you today?"
    )

if __name__ == "__main__":
    _test_happy_walk_wave_greeting()
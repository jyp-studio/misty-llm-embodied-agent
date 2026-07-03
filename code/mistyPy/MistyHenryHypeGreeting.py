# filename: MistyHenryHypeGreeting.py

from CUBS_Misty import Robot
import time

def misty_henry_hype_greeting(robot_ip: str):
    """
    Perform a friendly, hype greeting to Henry with coordinated movement,
    expression, LED, arm wave, and speech.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot, e.g. "192.168.1.237"
    """

    misty = Robot(robot_ip)

    # ----------------------------------------------------------------------
    # 1. Turn the head toward the direction of the user’s voice
    #    Target: azimuth +35°, speed ~60°/s
    # ----------------------------------------------------------------------
    # Using yaw=35 degrees, modest velocity to feel natural.
    misty.move_head(pitch=0, roll=0, yaw=35, velocity=60, units="degrees")
    time.sleep(0.6)  # allow head to settle

    # ----------------------------------------------------------------------
    # 2. Step slightly closer to the user (approx. 20 cm forward at 15 cm/s)
    # ----------------------------------------------------------------------
    # NOTE: MistyActionAgent is not allowed to call locomotion APIs beyond the given ones.
    # Here is where you would integrate Perception/Locomotion Agent functionality:
    #   - e.g., some_robot_drive_forward(distance_m=0.20, speed_mps=0.15)
    # For this demo, we only add a pause to represent that step.
    time.sleep(1.5)

    # ----------------------------------------------------------------------
    # 3. Rotate the body to face the user more directly (yaw +15°)
    # ----------------------------------------------------------------------
    # BODY ROTATION is not exposed in the provided API.
    # This is another integration point for a Locomotion/Drive Agent:
    #   - e.g., rotate_in_place(yaw_degrees=15, speed_deg_per_s=40)
    time.sleep(1.0)

    # ----------------------------------------------------------------------
    # 4. Adopt an attentive and friendly facial posture with raised eyebrows
    # ----------------------------------------------------------------------
    # Eyebrow control is not an explicit primitive in this API.
    # We approximate by using a positive, attentive expression.
    misty.emotion_Admiration()
    # Simulate "brow raise" transition timing.
    time.sleep(1.0)

    # ----------------------------------------------------------------------
    # 5. Tilt head into an attentive posture
    #    roll: +10° right, pitch: -5° (slightly up), keep yaw at 35° toward user
    # ----------------------------------------------------------------------
    misty.move_head(pitch=-5, roll=10, yaw=35, velocity=40, units="degrees")
    time.sleep(0.5)

    # ----------------------------------------------------------------------
    # 6. Display a warm smile with cheerful eye expression
    # ----------------------------------------------------------------------
    # Use a joyful, warm expression; LED bright & friendly (warm white/yellow).
    misty.emotion_Joy()
    # Bright LED: close to full brightness, warm tone
    misty.change_led(255, 230, 180)
    time.sleep(0.3)

    # ----------------------------------------------------------------------
    # 7. Lift right arm in a small wave-like greeting
    #    Right shoulder ~35°, "elbow" via arm position, wave 3 times
    # ----------------------------------------------------------------------
    # Approximation: use arm positions to simulate shoulder+elbow.
    # Start: raise right arm somewhat and keep left neutral.
    misty.move_arms(leftArmPosition=0, rightArmPosition=35, leftArmVelocity=60, rightArmVelocity=60)
    time.sleep(0.5)

    # Wave: small flex/extend around 35° with +/-10° movement, 3 cycles.
    base_pos = 35
    delta = 10
    for _ in range(3):
        # Bend a bit more
        misty.move_arms(rightArmPosition=base_pos + delta, rightArmVelocity=70)
        time.sleep(0.3)
        # Straighten a bit
        misty.move_arms(rightArmPosition=base_pos - delta, rightArmVelocity=70)
        time.sleep(0.3)

    # Return arm to a relaxed but still friendly position (slightly lowered)
    misty.move_arms(rightArmPosition=15, rightArmVelocity=60)
    time.sleep(0.4)

    # ----------------------------------------------------------------------
    # 8. Speak a playful, upbeat greeting to Henry
    # ----------------------------------------------------------------------
    misty.sound_Joy2()  # short joyful cue before speaking
    time.sleep(0.3)

    misty.speak(
        text=(
            "Hi Henry! It’s awesome to meet you. "
            "My name is Misty, and I’m totally here for the hype. "
            "What are we getting hyped about today?"
        ),
        speechRate=1.05
    )

    # Allow speech to mostly complete before resetting
    time.sleep(6.0)

    # ----------------------------------------------------------------------
    # Reset Misty to normal / neutral state
    # ----------------------------------------------------------------------
    misty.return_to_normal()


# --------------------------------------------------------------------------
# Basic test harness
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # Replace with your Misty IP as needed
    misty_henry_hype_greeting("192.168.1.237")
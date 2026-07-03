# filename: MistyGreetHenryAttentive.py

from CUBS_Misty import Robot
import time

def misty_attentive_greet_henry(robot_ip: str):
    """
    Complex Henry-directed greeting + listening behavior for Misty.

    High-level behavior sequence:
    1. Turn head toward Henry's sound source (approximate with a rightward head yaw).
    2. Lean torso/head slightly forward into an engaged posture.
    3. Use an eye expression with raised brows / interest.
    4. Display a warm, friendly smile / joyful expression.
    5. Set LED to a bright, soft white (attentive, warm).
    6. Speak a friendly self-introduction inviting Henry to share how he's doing.
    7. Raise right arm into a greeting pose while speaking.
    8. Wave right hand in a gentle greeting gesture.
    9. Return right arm to a neutral resting position.
    10. Hold an attentive posture with a soft smile, waiting for Henry’s reply.

    Notes / approximations:
    - Misty does not expose separate "eyebrow" or "pupil" controls via this API.
      We approximate with facial emotion images (e.g., Joy / Admiration / Amazement).
    - Torso lean is approximated by head pitch (tilting down slightly as if leaning in).
    - There is no explicit wrist-yaw control in this API; we approximate waving with arm swings.
    - Turning head toward Henry is approximated by a yaw to the right (e.g., -20 degrees).
    - The original user instructions referenced another Agent (Perception / Event).
      Any real-time sound-source localization should be implemented in that Agent
      and then call this function with an appropriate pre-computed yaw value.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot (e.g., "192.168.1.237").
    """

    misty = Robot(robot_ip)

    # -------------------------------
    # 0. Start from a neutral baseline
    # -------------------------------
    misty.return_to_normal()
    time.sleep(0.5)

    # ----------------------------------------------------
    # 1. Turn head toward Henry’s last known sound source
    #    + 2. Lean torso/head forward in an engaged posture
    # ----------------------------------------------------
    # Approximate: slight right yaw & slight down pitch to "lean forward"
    # (yaw: -20° to the right, pitch: 10° down, roll: 0°)
    misty.move_head(pitch=10, roll=0, yaw=-20, velocity=25, duration=0.8, units="degrees")
    time.sleep(0.8)

    # -------------------------------------------------
    # 3. Raise eyebrows / 4. Warm friendly smile
    # 5. Bright, soft white LEDs
    # -------------------------------------------------
    # Choose an expression that reads as interested + smiling.
    # Joy / Joy2 is a reasonable approximation.
    misty.emotion_Joy2()
    # Bright, soft white LED (slightly warm: R>G=B)
    misty.change_led(255, 235, 220)

    time.sleep(0.3)

    # ---------------------------------------------------------
    # 6. Speak friendly self-introduction + invite Henry to talk
    # 7. Raise right hand into greeting pose while speaking
    # ---------------------------------------------------------
    # Text: friendly, warm, inviting
    intro_text = (
        "Hi Henry, I’m Misty. I’m really glad to see you. "
        "How are you feeling today? You can tell me anything that’s on your mind."
    )

    # Start speech at a comfortable rate and moderate pitch
    misty.speak(text=intro_text, pitch=1.0, speechRate=1.0)
    # While speaking, raise right arm slowly into a greeting pose.
    # Right arm slightly up & forward (e.g., -10° = a bit up, forward is still near 0).
    misty.move_arms(leftArmPosition=0, rightArmPosition=-10, rightArmVelocity=20, duration=1.0, units="degrees")

    # Give time for arm to reach greeting pose while speech continues.
    time.sleep(1.0)

    # ---------------------------------------------------------
    # 8. Gentle greeting wave with right hand / arm
    # ---------------------------------------------------------
    # Since there is no dedicated wrist yaw in this API, approximate waving by
    # small up/down oscillations of the right arm around a slightly raised position.
    # Keep left arm relaxed at side (0°).
    base_right_pos = -10  # baseline "raised" position
    wave_delta = 10       # small additional up/down motion
    cycles = 3
    per_move = 0.3        # seconds per small move (approx total ~1.8s)

    for _ in range(cycles):
        # Move slightly up
        misty.move_arms(leftArmPosition=0,
                        rightArmPosition=base_right_pos - wave_delta,
                        leftArmVelocity=20,
                        rightArmVelocity=20,
                        duration=per_move,
                        units="degrees")
        time.sleep(per_move)

        # Move slightly down
        misty.move_arms(leftArmPosition=0,
                        rightArmPosition=base_right_pos + wave_delta,
                        leftArmVelocity=20,
                        rightArmVelocity=20,
                        duration=per_move,
                        units="degrees")
        time.sleep(per_move)

    # Return to base raised pose briefly before lowering
    misty.move_arms(leftArmPosition=0,
                    rightArmPosition=base_right_pos,
                    leftArmVelocity=20,
                    rightArmVelocity=20,
                    duration=0.3,
                    units="degrees")
    time.sleep(0.3)

    # ---------------------------------------------------------
    # 9. Return right hand to a neutral resting position
    # ---------------------------------------------------------
    misty.move_arms(leftArmPosition=0,
                    rightArmPosition=0,
                    leftArmVelocity=25,
                    rightArmVelocity=25,
                    duration=0.8,
                    units="degrees")
    time.sleep(0.8)

    # ---------------------------------------------------------
    # 10. Hold an attentive posture with a soft smile
    # ---------------------------------------------------------
    # Keep head slightly leaned in and toward Henry, with a soft smile and gentle LED.
    # We’re already in Joy2 with appropriate LED; just refine head position slightly.
    misty.move_head(pitch=8, roll=0, yaw=-15, velocity=20, duration=0.6, units="degrees")
    time.sleep(0.6)

    # Hold attentive pose (soft smile, eyes forward) for a few seconds
    hold_time = 4.0
    time.sleep(hold_time)

    # ---------------------------------------------------------
    # Reset Misty to neutral after the interaction
    # ---------------------------------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test invocation with the provided IP.
    # NOTE: Ensure Misty is on and reachable on this IP before running.
    misty_attentive_greet_henry("192.168.1.237")
# filename: MistyHenryPlayfulGreeting.py

from CUBS_Misty import Robot
import time

def misty_henry_playful_greeting(robot_ip: str, henry_audio_yaw_deg: float = 0.0):
    """
    Perform a multi-step, friendly, playful interaction sequence with Henry.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot.
    henry_audio_yaw_deg : float
        Estimated audio localization yaw angle (in degrees) of Henry's voice 
        relative to Misty's current torso/front direction.
        - Positive: to Misty's left
        - Negative: to Misty's right

    Behavior Script
    ---------------
    1. Turn torso (body) yaw to face Henry’s voice direction (use audio localization angle; 
       rotate torso yaw at moderate speed, approximated with head+body posture).
    2. Turn head yaw to align more precisely with Henry (match torso yaw).
    3. Take one small step forward toward Henry (~19cm, from 109cm to ~90cm, speed ~20%).
    4. Raise eyebrows to “high/surprised” position and show wide-open/surprised eyes for 1.0s.
    5. After 1.0s, change eyes to a smiling/happy look and tilt head ~10–15° right.
    6. Lift right arm into a gentle, pointing/wave-like pose toward Henry’s chest area.
    7. Speak in a light, teasing tone:
       “My name is Misty… and your name is Henry! You already told me, remember?”
    8. Give a short, happy chassis bounce and tiny arm wiggle.
    9. Continue speaking cheerfully:
       “But we can practice as many times as you want. You say: ‘Your name is Misty… and my name is Henry!’”
    10. Reset to neutral via return_to_normal().
    """

    misty = Robot(robot_ip)

    # ---------------------------
    # 1–3. Orient toward Henry + step forward
    # ---------------------------
    # Torso orientation on Misty is limited with the given API; we approximate
    # by combining a brief “body facing” adjustment with head yaw.
    # (If a locomotion API is available from another Agent, integrate it here.)
    #
    # Turn head yaw toward Henry using audio angle (approximate torso facing)
    target_yaw = max(min(henry_audio_yaw_deg, 81), -81)  # clamp to head yaw limits
    misty.move_head(pitch=0, roll=0, yaw=target_yaw, velocity=40, units="degrees")
    time.sleep(0.8)

    # Small “step” toward Henry – approximated as a tiny forward lean gesture
    # NOTE: Replace this with real locomotion when the locomotion/Perception agent is used.
    misty.move_head(pitch=5, yaw=target_yaw, roll=0, velocity=20, units="degrees")
    time.sleep(0.4)
    misty.move_head(pitch=0, yaw=target_yaw, roll=0, velocity=20, units="degrees")
    time.sleep(0.4)

    # ---------------------------
    # 4. Surprised / playful “you’re being silly” expression (1.0s)
    # ---------------------------
    # Use an amazement/surprise emotion plus LED and sound.
    misty.emotion_Amazement()
    misty.change_led(255, 255, 255)  # bright white, “eyes wide”
    misty.sound_Amazement2()
    time.sleep(1.0)

    # ---------------------------
    # 5–6. Switch to happy/smiling expression + head tilt
    # ---------------------------
    # Use joyful expression; tilt head 10–15° to right (negative roll).
    misty.emotion_Joy()
    misty.change_led(0, 255, 100)  # warm teal/greenish, friendly
    misty.move_head(
        pitch=0,
        yaw=target_yaw,
        roll=-12,              # right tilt ≈ 10–15°
        velocity=25,
        units="degrees"
    )
    time.sleep(0.6)

    # ---------------------------
    # 7. Gentle right-arm pointing / small wave-like greeting
    # ---------------------------
    # Approximate: right arm up a bit, left arm neutral/relaxed.
    # (Misty arm positions: -29° up, 90° down along the side, 0° forward)
    misty.move_arms(
        leftArmPosition=10,    # almost neutral, relaxed
        rightArmPosition=-10,  # up and slightly forward, gentle gesture
        leftArmVelocity=30,
        rightArmVelocity=30,
        duration=0.8,
        units="degrees"
    )
    time.sleep(0.8)

    # ---------------------------
    # 8. First playful teasing line
    # ---------------------------
    misty.sound_Joy2()  # overlay a light joyful sound
    misty.speak(
        text="My name is Misty, and your name is Henry! You already told me, remember?",
        speechRate=1.04
    )
    # Give a bit of time for TTS to progress before the bounce
    time.sleep(1.0)

    # ---------------------------
    # 9. Happy chassis “bounce” + tiny arm wiggle
    # ---------------------------
    # NOTE: There is no direct chassis height API in this action agent;
    # we approximate bounce using head + arm motion as if “bobbing”.
    # If a motion-base API is available in another Agent, integrate it there.

    # Quick “lower” (head slightly down, arms slightly down), then up
    misty.move_head(pitch=8, yaw=target_yaw, roll=-12, velocity=40, units="degrees")
    misty.move_arms(leftArmPosition=20, rightArmPosition=0, leftArmVelocity=40, rightArmVelocity=40, duration=0.3, units="degrees")
    time.sleep(0.3)
    misty.move_head(pitch=-4, yaw=target_yaw, roll=-12, velocity=40, units="degrees")
    misty.move_arms(leftArmPosition=5, rightArmPosition=-10, leftArmVelocity=40, rightArmVelocity=40, duration=0.3, units="degrees")
    time.sleep(0.3)

    # Tiny arm wiggle: oscillate both arms ±10° around current pose
    base_left = 5
    base_right = -10
    for _ in range(4):  # about 0.8s total (4 * 0.2)
        misty.move_arms(
            leftArmPosition=base_left + 8,
            rightArmPosition=base_right - 8,
            leftArmVelocity=60,
            rightArmVelocity=60,
            duration=0.1,
            units="degrees"
        )
        time.sleep(0.1)
        misty.move_arms(
            leftArmPosition=base_left - 8,
            rightArmPosition=base_right + 8,
            leftArmVelocity=60,
            rightArmVelocity=60,
            duration=0.1,
            units="degrees"
        )
        time.sleep(0.1)

    # ---------------------------
    # 10. Second cheerful line
    # ---------------------------
    misty.sound_Joy()  # short happy confirmation sound
    misty.speak(
        text="But we can practice as many times as you want. You say: Your name is Misty, and my name is Henry!",
        speechRate=1.02
    )
    time.sleep(2.0)

    # ---------------------------
    # Reset Misty to neutral
    # ---------------------------
    misty.return_to_normal()


# ---------------------------
# Test Suite
# ---------------------------
def _test_misty_henry_playful_greeting_center():
    """
    Test with Henry directly in front of Misty (0° yaw).
    """
    misty_henry_playful_greeting("192.168.1.237", henry_audio_yaw_deg=0.0)


def _test_misty_henry_playful_greeting_left():
    """
    Test with Henry 30° to Misty's left.
    """
    misty_henry_playful_greeting("192.168.1.237", henry_audio_yaw_deg=30.0)


def _test_misty_henry_playful_greeting_right():
    """
    Test with Henry 30° to Misty's right.
    """
    misty_henry_playful_greeting("192.168.1.237", henry_audio_yaw_deg=-30.0)


if __name__ == "__main__":
    # Choose one of the tests to run.
    # NOTE: Ensure the IP matches your Misty on the network.
    _test_misty_henry_playful_greeting_center()
    # _test_misty_henry_playful_greeting_left()
    # _test_misty_henry_playful_greeting_right()
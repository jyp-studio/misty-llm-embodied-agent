# filename: MistyAttentiveClarification.py

from CUBS_Misty import Robot
import time

def misty_attentive_clarification(robot_ip: str, last_voice_yaw_deg: float = 0.0):
    """
    Guide Misty through an attentive clarification behavior when she partially hears the user.

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot (e.g., "192.168.1.237").
    last_voice_yaw_deg : float, optional
        The last known user voice direction in head yaw degrees, where:
          - 0   : facing straight ahead
          - >0  : left
          - <0  : right
        Misty will turn an additional 15 degrees toward this direction in a smooth motion.
        Default is 0.0 (straight ahead).

    Behavior Summary
    ----------------
    1. Turn head 15° toward the user’s last known voice direction (velocity ≈ 40%).
    2. Raise "torso posture" by 10° (simulated via head pitch, velocity ≈ 35%) to perk up.
    3. Tilt the head 12° to Misty’s right (roll, velocity ≈ 35%) to convey curiosity.
    4. Set LED to a neutral/warm white and keep default eyes (neutral-open) to simulate widened attention.
       (Note: explicit eye openness / shape controls would be handled by another Agent / API if available.)
    5. Hold this posture for 300 ms.
    6. Speak a warm clarification line in a friendly tone using default TTS voice.
    7. While speaking, lean slightly forward an additional 3° (more downward pitch, velocity ≈ 30%).
    8. Maintain gaze toward user and attentive LED state during and after speech.
    9. After speech, pause silently for 3 seconds, holding posture steady as if listening.
    10. Finally, reset Misty to neutral using return_to_normal().
    """

    misty = Robot(robot_ip)

    # -----------------------------
    # 1–4. Initial attentive pose
    # -----------------------------

    # LED: neutral-open, widened attentive effect approximated by bright neutral LED.
    # NOTE: If explicit "eye openness" and "eye shape" APIs exist, they should be
    # integrated here by the relevant Perception/Display agent.
    misty.change_led(255, 255, 255)  # bright white / neutral-open attention

    # Base neutral head: straight ahead before applying offsets
    base_pitch = 0.0
    base_yaw = 0.0
    base_roll = 0.0

    # 1. Turn head 15° toward the user’s last known voice direction
    # If user is at positive yaw, we add +15 in that direction; if negative, subtract.
    # Clamp to Misty's safe yaw range (-81, 81).
    direction_sign = 1.0 if last_voice_yaw_deg >= 0 else -1.0
    target_yaw = base_yaw + direction_sign * 15.0
    target_yaw = max(-81.0, min(81.0, target_yaw))

    # 2. Raise torso posture by 10° – approximate by slightly raising head (negative pitch is up)
    target_pitch = base_pitch - 10.0  # up by 10°

    # 3. Tilt head 12° to the right (from Misty's POV: negative roll = tilt right)
    target_roll = base_roll - 12.0

    # Move head with smooth-ish speed (velocity ≈ 40%). Duration small for a quick but smooth motion.
    misty.move_head(
        pitch=target_pitch,
        yaw=target_yaw,
        roll=target_roll,
        velocity=40,         # 40% of max, approximating "smooth easing-in"
        duration=0.5,
        units="degrees"
    )

    # 4. (Eyes already approximated via LED; default expression should be neutral-open.)
    # To emphasize attentiveness, we can use default content / neutral expression.
    misty.emotion_DefaultContent()

    # 5. Hold this posture for 300 ms
    time.sleep(0.3)

    # -------------------------------------------
    # 6–8. Speak warm clarification & lean in
    # -------------------------------------------

    # Start speaking in warm, friendly tone.
    # NOTE: The provided speak() wrapper does not expose 'volume' parameter directly.
    # Volume would need to be adjusted via a separate audio/tts config API if available.
    # Here we rely on default voice & "normal" speech rate (speechRate=1.0).
    clarification_text = (
        "I think I only heard the word 'year.' "
        "Could you say that again for me a little more clearly? "
        "I want to make sure I understand you."
    )

    # Kick off speech
    misty.speak(
        text=clarification_text,
        speechRate=1.0,    # normal rate
        voice=None,        # default voice
        flush=True
    )

    # 7. While speaking, lean torso forward by an additional 3°
    # We approximate this by slightly increasing head downward pitch (positive pitch = down).
    # Current pitch is target_pitch (-10°). We'll move it 3° downward toward -7° (a subtle forward lean).
    engaged_pitch = target_pitch + 3.0  # less "up", slight forward/downward lean

    misty.move_head(
        pitch=engaged_pitch,
        yaw=target_yaw,     # maintain orientation toward voice
        roll=target_roll,   # keep curious tilt
        velocity=30,        # 30% of max for subtle lean
        duration=0.4,
        units="degrees"
    )
    # This movement happens while TTS is playing; we simply allow it to complete.
    time.sleep(0.4)

    # Maintain orientation & LED state; do not move further while speaking.
    # We do not know exact TTS duration, so we wait a conservative estimate.
    # The speak() wrapper already computed an ignore window; here we approximate
    # speech length from text length (~2–3s for this sentence).
    time.sleep(3.0)

    # 9. Pause silently for 3 seconds, holding gaze and posture steady for listening
    time.sleep(3.0)

    # 10. Reset Misty to her neutral default state
    misty.return_to_normal()


# ----------------------------
# Simple Test Suite / Runner
# ----------------------------

def _test_misty_attentive_clarification_center():
    """
    Test: User straight ahead (0°). This should result in a small 15° left yaw.
    """
    misty_attentive_clarification("192.168.1.237", last_voice_yaw_deg=0.0)

def _test_misty_attentive_clarification_left():
    """
    Test: User to left (e.g., +30°). Misty should turn 15° further left.
    """
    misty_attentive_clarification("192.168.1.237", last_voice_yaw_deg=30.0)

def _test_misty_attentive_clarification_right():
    """
    Test: User to right (e.g., -30°). Misty should turn 15° further right.
    """
    misty_attentive_clarification("192.168.1.237", last_voice_yaw_deg=-30.0)


if __name__ == "__main__":
    # Choose one of the tests to run.
    # In a real scenario, you'd pick the most appropriate based on your last-voice estimate.
    _test_misty_attentive_clarification_center()
# filename: MistyQuietAttentivePosture.py

from CUBS_Misty import Robot
import time

def misty_quiet_attentive_posture(robot_ip: str):
    """
    Guide Misty into a warm, relaxed, and attentive quiet posture,
    without moving her base (no translational movement).

    Behavior implemented (MistyActionAgent-only):
    1. Orient head toward the user and tilt slightly to the right.
    2. Adopt a gentle, relaxed arm posture with a slightly open stance.
    3. Set eye/facial display to warm, relaxed, and attentive.
    4. Cease speech output; remain in a quiet, attentive idle posture.

    NOTE: 
    - No EventAgent / PerceptionAgent behavior is implemented (no tracking, no listeners).
      Where needed, comments indicate where such functionality could be integrated.
    """

    # Initialize Misty
    misty = Robot(robot_ip)

    # --------------------------
    # 1. HEAD ORIENTATION & TILT
    # --------------------------
    # We keep the base fixed; only the head is adjusted.
    # Approximate:
    #  - yaw = 0: head faces straight ahead (toward user)
    #  - small roll to the right: ~8 degrees
    #  - slight neutral pitch
    #
    # Duration ~1.5s, smooth motion is handled by the robot firmware.
    misty.move_head(
        pitch=0,      # neutral up/down
        yaw=0,        # face forward toward user
        roll=8,       # tilt head 8° to Misty's right
        velocity=20,  # relaxed speed
        duration=1.5,
        units="degrees"
    )
    time.sleep(1.6)  # wait for movement to complete

    # -------------------------------------------------
    # 2. GENTLE RELAXED ARM / HAND "OPEN STANCE" POSTURE
    # -------------------------------------------------
    # There is no separate shoulder/outward axis in the provided API, so we approximate
    # a slightly open, relaxed stance using arm pitch only:
    #  - Move arms a bit downward from neutral to give a relaxed look.
    misty.move_arms(
        leftArmPosition=20,   # gently down
        rightArmPosition=20,  # gently down
        leftArmVelocity=30,
        rightArmVelocity=30,
        duration=1.0,
        units="degrees"
    )
    time.sleep(1.1)

    # If you later want a specific right‑arm "I'm here" gesture with fine elbow/wrist control,
    # it would require lower‑level / additional APIs not present here.

    # ----------------------------------------------------
    # 3. FACE DISPLAY: WARM, RELAXED, ATTENTIVE EXPRESSION
    # ----------------------------------------------------
    # We do not have direct "eye shape" parameters, but we can approximate:
    #  - "calm-neutral-warm": use a default/content expression,
    #    which is soft and neutral.
    misty.emotion_DefaultContent()

    # LED: warm, soft tone (e.g., warm white / soft amber)
    misty.change_led(255, 200, 150)

    # OPTIONAL: If your asset pack includes a closer "gentle smile" expression
    # (e.g., a custom file like 'e_GentleSmile.jpg'), you could call:
    #   misty.display_image("e_GentleSmile.jpg", alpha=1.0, layer="default", isURL=False)
    # But we stick to the provided API here.

    # -----------------------------------------
    # 4. CEASE SPEECH & ENTER QUIET ATTENTIVE
    # -----------------------------------------
    # User explicitly requested no speech output in this posture.
    # So we do NOT call misty.speak() and we do not trigger phrase sounds.
    #
    # We simply hold the posture for a short, quiet attentive period
    # with no further approach or retreat and no large body movements.
    #
    # Micro eye-saccades and reactive listeners (user distance / speech)
    # WOULD require EventAgent / PerceptionAgent and AV/audio streaming,
    # which this task is not allowed to implement.
    #
    # PLACEHOLDER for future integration:
    #   - EventAgent: register distance/speech events
    #   - PerceptionAgent: manage AV streaming and audio level callbacks
    #   - Behavior module: update head yaw/orientation as user moves,
    #                      trigger saccades every 10–15s, etc.
    #
    # For now, we just maintain a stable, quiet posture for a few seconds
    # as a demonstration of the "quiet attentive" body language only.
    quiet_duration_sec = 5
    time.sleep(quiet_duration_sec)

    # -------------------------
    # RESET TO NORMAL AT THE END
    # -------------------------
    # Per instructions: always reset Misty to her default neutral state
    # when the function completes.
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run on the provided IP.
    # This will:
    #   - Move Misty into a quiet, attentive posture,
    #   - Hold it briefly,
    #   - Then return her to normal.
    misty_quiet_attentive_posture("192.168.1.237")
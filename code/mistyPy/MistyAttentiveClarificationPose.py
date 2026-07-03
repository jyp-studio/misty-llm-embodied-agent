# filename: MistyAttentiveClarificationPose.py

from CUBS_Misty import Robot
import time

def misty_attentive_clarification_pose(robot_ip: str):
    """
    Guide Misty into an attentive, curious clarification pose and speak a
    warm line asking the user to repeat themselves more clearly.

    NOTE:
    - This function assumes that *another Agent* (e.g., Event/Perception agent)
      has already computed the user's last known voice direction and that
      direction is available to this function as a parameter or shared state.
    - Because this MistyActionAgent must not implement perception or events,
      you should integrate that other Agent's functionality where indicated
      in comments below.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot, e.g. "192.168.1.237".
    """

    # ---------------------------------------------------------------------
    # 0. Initialize Misty
    # ---------------------------------------------------------------------
    misty = Robot(robot_ip)

    # ---------------------------------------------------------------------
    # 1. Orient the head toward the user’s last known voice direction.
    #
    # IMPORTANT:
    # - The actual *audio localization* / "last known voice direction"
    #   should be computed by another Agent (Perception/Event Agent).
    # - Here we just:
    #     - accept an example direction (e.g., yaw_degrees = 20)
    #       OR
    #     - expect you to inject the real value via integration.
    # ---------------------------------------------------------------------

    # >>> PLACEHOLDER: Replace this with real value from PerceptionAgent.
    # e.g., yaw_degrees = voice_direction_deg
    yaw_degrees = 20.0  # example: user is 20° to the left

    # Use a neutral pitch so Misty is looking horizontally at the user.
    head_pitch = 0.0

    # Smooth-in-out easing is not directly exposed, but we approximate it
    # with a moderate duration and reasonable velocity.
    misty.move_head(
        pitch=head_pitch,
        yaw=yaw_degrees,
        roll=0,
        velocity=30,       # ~30% of max, as requested for head speed
        duration=1.0,
        units="degrees"
    )
    time.sleep(1.0)

    # ---------------------------------------------------------------------
    # 2. Adjust torso posture to a more upright, attentive stance.
    #
    # Misty’s “torso” posture is primarily conveyed via head + arm posture.
    # We’ll:
    #   - Bring arms to a slightly raised, attentive neutral.
    #   - Ensure head pitch is near neutral (already set).
    # ---------------------------------------------------------------------
    misty.move_arms(
        leftArmPosition=10,   # slight downward / relaxed
        rightArmPosition=10,  # symmetric
        leftArmVelocity=25,   # about 25% of max
        rightArmVelocity=25,
        duration=1.0,
        units="degrees"
    )
    time.sleep(1.0)

    # ---------------------------------------------------------------------
    # 3. Tilt the head slightly to the right to convey curiosity.
    #
    # Positive roll tilts to the right (ear toward right shoulder).
    # ---------------------------------------------------------------------
    misty.move_head(
        pitch=head_pitch,
        yaw=yaw_degrees,
        roll=10,           # small right tilt to show curiosity
        velocity=30,
        duration=0.7,
        units="degrees"
    )
    time.sleep(0.7)

    # ---------------------------------------------------------------------
    # 4. Configure LED eyes to appear neutral, widened, and attentive.
    #
    # We use:
    #   - Neutral but bright expression (e.g., default content).
    #   - LED color soft white/blue at ~60% brightness.
    # You may replace the emotion image with a more "wide attentive" one
    # if you have a custom asset.
    # ---------------------------------------------------------------------
    # Neutral attentive facial image
    misty.emotion_DefaultContent()

    # Approximate "soft white/blue" at ~60% brightness
    # 60% of 255 ~ 153
    misty.change_led(red=140, green=170, blue=255)

    # ---------------------------------------------------------------------
    # 5. Maintain a brief still posture to hold the engaged pose.
    # ---------------------------------------------------------------------
    time.sleep(0.7)

    # ---------------------------------------------------------------------
    # 6. Speak a warm, friendly clarification line indicating that only
    #    part of the user’s speech was heard and asking them to repeat
    #    more clearly.
    #
    # We re-use speak() with default (calm) parameters.
    # ---------------------------------------------------------------------
    clarification_text = (
        "I heard some of what you said, but not everything. "
        "Could you please say that again a little more clearly?"
    )
    misty.speak(
        text=clarification_text,
        speechRate=1.0
    )

    # Estimate a safe wait interval so motion changes don’t overlap speech too much.
    # (Very light approximation; can be tuned as needed.)
    time.sleep(4.0)

    # ---------------------------------------------------------------------
    # 7. Subtly lean the torso forward during/just-after speech to show
    #    additional engagement, then stop movement.
    #
    # Misty has no explicit torso pitch via this API; we approximate a
    # “lean-in” by:
    #   - Slightly pitching the head down
    #   - Slightly adjusting arms forward
    # ---------------------------------------------------------------------
    lean_pitch = -5.0  # small up (depending on coordinate system, up is negative)
    misty.move_head(
        pitch=lean_pitch,
        yaw=yaw_degrees,
        roll=10,
        velocity=20,
        duration=0.6,
        units="degrees"
    )
    misty.move_arms(
        leftArmPosition=0,     # arms a bit more forward to imply lean
        rightArmPosition=0,
        leftArmVelocity=20,
        rightArmVelocity=20,
        duration=0.6,
        units="degrees"
    )
    time.sleep(0.6)

    # After the lean-in, freeze locomotion implicitly by not issuing any move/drive commands.
    # (Locomotion is not controlled here, so we simply don't send drive commands.)

    # ---------------------------------------------------------------------
    # 8. Maintain head orientation toward the user’s voice direction and
    #    keep LED eyes in an attentive state during and after speech.
    #
    # We already oriented the head; here we keep a short period of small
    # micro-movements to simulate natural gaze maintenance.
    #
    # IMPORTANT:
    # - True “tracking” of updated voice directions over time should come
    #   from another Agent (Perception/Event). Here we just add tiny,
    #   random micro-adjustments around the last known direction.
    # ---------------------------------------------------------------------
    # (No new expression change; keep current LED and emotion image.)

    # Simple micro-adjustments (static, not using perception).
    for _ in range(3):
        # Small micro “breathing” in gaze: +/- 2°
        misty.move_head(
            pitch=lean_pitch,
            yaw=yaw_degrees + 2,
            roll=10,
            velocity=15,
            duration=0.4,
            units="degrees"
        )
        time.sleep(0.4)
        misty.move_head(
            pitch=lean_pitch,
            yaw=yaw_degrees - 2,
            roll=10,
            velocity=15,
            duration=0.4,
            units="degrees"
        )
        time.sleep(0.4)

    # ---------------------------------------------------------------------
    # 9. Pause silently after speaking while keeping gaze/posture steady
    #    to listen for further user input.
    #
    # IMPORTANT:
    # - Actual "enter listening state, activate microphones, and process
    #   new speech" is a PerceptionAgent / ASR job and must be wired in
    #   externally. Insert that logic where indicated below.
    # ---------------------------------------------------------------------

    # --- INTEGRATION POINT ---
    # Here you should trigger your Perception/ASR pipeline, for example:
    #   PerceptionAgent.start_listening()
    #   EventAgent.register_event("Transcription", callback=...)
    #
    # This ActionAgent intentionally does NOT implement those features.
    # -------------------------

    # Passive wait to simulate "listening pose"
    time.sleep(3.0)

    # ---------------------------------------------------------------------
    # IMPORTANT: return Misty to normal / neutral at the end of the function.
    # If you prefer to *remain* in the attentive pose after this function,
    # you can comment this out, but per instructions we reset.
    # ---------------------------------------------------------------------
    misty.return_to_normal()


# -------------------------------------------------------------------------
# BASIC TEST HARNESS
# -------------------------------------------------------------------------
if __name__ == "__main__":
    # Example: run on a specific Misty IP.
    # Replace with your robot's IP, e.g. "192.168.1.237"
    test_ip = "192.168.1.237"
    misty_attentive_clarification_pose(test_ip)
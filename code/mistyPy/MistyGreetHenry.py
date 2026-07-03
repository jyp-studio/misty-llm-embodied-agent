# filename: MistyGreetHenry.py

from CUBS_Misty import Robot
import time

def misty_greet_henry(robot_ip: str):
    """
    Perform a warm greeting sequence for Henry.

    Behavior:
    1. Turn head toward Henry's approximate direction (simulated sound source).
    2. Lean torso/head slightly forward for an engaged posture (simulated via head pitch).
    3. Raise “eyebrows” and display an interested, enthusiastic facial expression.
    4. Display a warm, friendly smile.
    5. Set eye LEDs to bright, soft white.
    6. Speak a friendly self-introduction to Henry, inviting him to share how he is doing.
    7. Raise the right hand into a greeting pose while speaking.
    8. Wave the right hand in a gentle greeting gesture.
    9. Return the right hand to a neutral resting position.
    10. Hold an attentive posture with a soft smile while waiting for Henry’s response.

    Notes:
    - Actual audio source localization (PerceptionAgent/EventAgent) is NOT implemented here,
      per instructions. Where such functionality is needed, comments indicate integration points.
    """

    misty = Robot(robot_ip)

    try:
        # ------------------------------------------------------------------
        # 1. Turn head toward Henry's sound source (simulated)
        # ------------------------------------------------------------------
        # NOTE: In a full system, another Agent would determine the sound-source
        # azimuth (e.g., yaw_angle_from_audio). Here we assume Henry is roughly
        # in front-left and simulate a small turn.
        # Integration point for PerceptionAgent/EventAgent:
        #   yaw_angle = <PerceptionAgent.get_sound_source_yaw()>
        # For now, we just turn slightly left to "search", then center.
        misty.move_head(pitch=0, yaw=-15, roll=0, velocity=40, units="degrees")
        time.sleep(0.8)

        # ------------------------------------------------------------------
        # 2. Lean torso forward in an engaged posture (simulated with head pitch)
        # ------------------------------------------------------------------
        # Misty doesn't have a torso pitch API here, so use mild head tilt forward
        # to approximate a 5° forward lean.
        misty.move_head(pitch=5, yaw=-10, roll=0, velocity=40, units="degrees")
        time.sleep(0.8)

        # ------------------------------------------------------------------
        # 3 & 4. Raise eyebrows + warm, friendly smile
        # ------------------------------------------------------------------
        # Use a joyful / content expression to convey interest & enthusiasm.
        # JoyGoofy is often expressive and “eyebrow up”-like.
        misty.emotion_JoyGoofy()
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 5. Set eye LEDs to bright, soft white (≈ 80% brightness)
        # ------------------------------------------------------------------
        # 80% of 255 ≈ 204
        brightness = int(255 * 0.8)
        misty.change_led(brightness, brightness, brightness)

        # ------------------------------------------------------------------
        # 6 & 7. Speak friendly self-intro + raise right hand in greeting pose
        # ------------------------------------------------------------------
        # Right arm: raise to chest height, elbow ~90°, greeting pose
        # (On Misty: -29° is up, 90° is down. Chest-ish is somewhere around 10–20°.)
        misty.move_arms(leftArmPosition=0, rightArmPosition=15, leftArmVelocity=60,
                        rightArmVelocity=60, units="degrees")
        time.sleep(0.8)

        # Speak friendly greeting
        # Keep it short so posture/gesture stay synced.
        intro_text = (
            "Hi Henry! It's me, Misty. I'm really happy to see you. "
            "How are you feeling today?"
        )
        misty.speak(text=intro_text, speechRate=1.0)

        # ------------------------------------------------------------------
        # 8. Gentle wave with right hand while greeting
        # ------------------------------------------------------------------
        # Small oscillation of right arm around chest-height.
        for _ in range(3):
            misty.move_arms(leftArmPosition=0, rightArmPosition=5,
                            leftArmVelocity=70, rightArmVelocity=70,
                            units="degrees")
            time.sleep(0.4)
            misty.move_arms(leftArmPosition=0, rightArmPosition=25,
                            leftArmVelocity=70, rightArmVelocity=70,
                            units="degrees")
            time.sleep(0.4)

        # ------------------------------------------------------------------
        # 9. Return right hand to neutral resting position
        # ------------------------------------------------------------------
        misty.move_arms(leftArmPosition=0, rightArmPosition=0,
                        leftArmVelocity=60, rightArmVelocity=60,
                        units="degrees")
        time.sleep(0.8)

        # ------------------------------------------------------------------
        # 10. Hold attentive posture with soft smile while waiting
        # ------------------------------------------------------------------
        # Slight forward head pitch, centered yaw, small curious roll.
        misty.emotion_Joy()  # softer friendly smile
        misty.move_head(pitch=5, yaw=0, roll=5, velocity=30, units="degrees")
        # Maintain bright but soft white LED as "attentive" state.
        misty.change_led(brightness, brightness, brightness)

        # Stay still attentively for a few seconds (listening for Henry).
        # NOTE: Actual listening / ASR should be handled by another Agent.
        time.sleep(5.0)

    finally:
        # Always reset Misty to her normal neutral state at the end.
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic functional test; replace IP with your Misty’s IP as needed.
    misty_greet_henry("192.168.1.237")
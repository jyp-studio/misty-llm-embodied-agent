# filename: MistyHenryGreetingIntro.py

from CUBS_Misty import Robot
import time

def misty_henry_greeting_intro(robot_ip: str):
    """
    Perform a friendly, engaging greeting sequence toward Henry.

    Behavior script (mapped from YOURTASK):
      1. Turn head toward Henry's sound source (here: a gentle turn to 'face' Henry).
      2. Lean torso/head forward slightly to show engagement.
      3. Raise 'eyebrows' to convey interest (use surprised/curious eye expression).
      4. Display a warm, friendly smile (joyful content expression).
      5. Set eye LEDs to a bright, soft white.
      6. Speak a friendly self-introduction to Henry, inviting him to share how he's doing.
      7. Raise right hand into a greeting pose while speaking.
      8. Wave right hand in a gentle greeting gesture.
      9. Return right hand to neutral resting position.
     10. Hold an attentive posture with a soft smile while waiting for Henry’s reply.

    NOTE:
    - Since the MistyActionAgent API does not expose explicit torso or eyebrow controls,
      we approximate:
        * Torso lean with head pitch.
        * Eyebrow raise with a curious/joy expression.
    - Per instructions, no EventAgent or PerceptionAgent features are used.
      If you want true sound-source localization or live listening,
      integrate that via another Agent where noted in comments.
    """

    misty = Robot(robot_ip)

    # --- Approximated "face Henry's voice" & engaged lean ---

    # Turn head to a neutral forward-facing pose (assuming Henry is in front).
    # If a PerceptionAgent with sound-source localization is available,
    # this yaw should be set from that data instead of hard-coded.
    # e.g., yaw = perception_agent.get_sound_source_yaw()
    misty.move_head(pitch=-5, yaw=0, roll=0, velocity=40, units="degrees")
    time.sleep(0.6)

    # Slight forward "lean" using head pitch to show engagement.
    misty.move_head(pitch=5, yaw=0, roll=0, velocity=30, units="degrees")
    time.sleep(0.6)

    # --- Eye / face expression: raised-brow interest + warm smile ---

    # Use a joyful / friendly content expression (smiley eyes & mouth).
    # This approximates raised eyebrows + warm smile.
    misty.emotion_Joy()
    time.sleep(0.1)

    # Bright, soft white LED (eye "glow" approximation).
    # 90% brightness -> approximate with high RGB values, still soft.
    misty.change_led(red=220, green=230, blue=255)

    # --- Greeting: arm and speech coordination ---

    # Prepare right arm for a greeting pose (elbow bent, hand raised).
    # On Misty: -29° is up, 90° is down, 0° forward.
    # We'll raise the right arm moderately above forward and slightly out as a "hello" wave.
    misty.move_arms(leftArmPosition=0, rightArmPosition=-10, leftArmVelocity=50, rightArmVelocity=60)
    time.sleep(0.7)

    # Friendly phrase using TTS, with a warm tone implied by content.
    # NOTE: If you have a conversational TTS or external LLM voice controller,
    # integrate it via another Agent at this call site.
    intro_text = (
        "Hi Henry! I'm Misty. It's really nice to meet you. "
        "I'm feeling curious and excited to hang out with you today. "
        "How are you doing?"
    )
    misty.speak(text=intro_text, speechRate=1.0)
    # Allow a bit of time for initial speech before starting the wave,
    # so Henry sees motion timed with the greeting.
    time.sleep(1.0)

    # Gentle greeting wave with the right hand.
    # Keep left arm relaxed at neutral.
    for _ in range(3):
        # Upward part of wave (slightly higher)
        misty.move_arms(leftArmPosition=0, rightArmPosition=-20, leftArmVelocity=60, rightArmVelocity=80)
        time.sleep(0.35)
        # Downward part of wave (back toward slightly below raised)
        misty.move_arms(leftArmPosition=0, rightArmPosition=5, leftArmVelocity=60, rightArmVelocity=80)
        time.sleep(0.35)

    # Return right hand to a neutral resting position.
    misty.move_arms(leftArmPosition=0, rightArmPosition=0, leftArmVelocity=60, rightArmVelocity=60)
    time.sleep(0.6)

    # --- Attentive listening posture ---

    # Slight head tilt for attentive listening, still "facing Henry".
    misty.move_head(pitch=0, yaw=0, roll=10, velocity=25, units="degrees")
    time.sleep(0.5)

    # Maintain a softer, friendly smile while "waiting" for Henry's reply.
    # Joy expression is already active; we can soften LEDs to slightly dimmer cyan/white.
    misty.change_led(red=200, green=230, blue=255)

    # Hold this posture still, with minimal movement (no explicit micro-movements implemented).
    # If you want subtle micro-motions (e.g. tiny head/eye shifts),
    # they should be scheduled here or via an Event/PerceptionAgent loop.
    time.sleep(4.0)

    # --- Reset Misty to neutral state at the end of the behavior ---
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the Henry greeting intro behavior.
    # Replace the IP below with your Misty robot's IP if different.
    misty_henry_greeting_intro("192.168.1.237")
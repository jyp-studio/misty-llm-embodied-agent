# filename: MistyFairyTaleIntro.py

from CUBS_Misty import Robot
import time

def misty_fairy_tale_intro(robot_ip: str):
    """
    Guide Misty through a warm, story-telling fairy tale introduction sequence.

    Note:
    - This function focuses purely on action control (MistyActionAgent).
    - Real-time user interruption detection (e.g., speech recognition / events)
      is NOT implemented here, because that belongs to EventAgent/PerceptionAgent.
      Where needed, comments indicate where such logic can be integrated.
    """

    misty = Robot(robot_ip)

    # -------------------------------------------------------------
    # Helper: approximate "warm smile" via joyful expression
    # (No direct intensity parameter in API; you can layer images if needed.)
    # -------------------------------------------------------------
    def set_warm_smile(intensity: float = 0.7):
        """
        Keep a warm, friendly smile on Misty.
        intensity: 0.0–1.0 (semantic only, we call the same API but
        you could choose a milder / stronger joy variant based on this.)
        """
        # Use a joyful / content face as "warm smile"
        if intensity >= 0.75:
            misty.emotion_Joy2()
        else:
            misty.emotion_Joy()

    # -------------------------------------------------------------
    # Helper: friendly blink / soft blink
    # -------------------------------------------------------------
    def blink_friendly(close_time: float = 0.15, hold_time: float = 0.10, open_time: float = 0.15):
        """
        Perform a friendly blink using a sleeping/closed eye expression
        and then restore the warm smile.
        """
        # Eyes closed
        misty.emotion_Sleeping()
        time.sleep(close_time + hold_time)
        # Back to warm smile
        set_warm_smile(0.7)
        time.sleep(open_time)

    def blink_soft(close_time: float = 0.12, hold_time: float = 0.08, open_time: float = 0.12):
        """
        Perform a softer, shorter blink during narration.
        """
        misty.emotion_Sleeping()
        time.sleep(close_time + hold_time)
        set_warm_smile(0.65)
        time.sleep(open_time)

    # -------------------------------------------------------------
    # Step 1: Orient head toward user (yaw 15°) over 0.8s
    # -------------------------------------------------------------
    misty.move_head(pitch=0, roll=0, yaw=15, duration=0.8, units="degrees")
    set_warm_smile(0.7)

    # -------------------------------------------------------------
    # Step 2–3: Three friendly blinks with 0.4s between blinks
    # -------------------------------------------------------------
    for i in range(3):
        blink_friendly(close_time=0.15, hold_time=0.10, open_time=0.15)
        if i < 2:
            time.sleep(0.4)

    # -------------------------------------------------------------
    # Step 4: Speak greeting in gentle, story-telling voice
    # (The underlying API's speak() does not expose volume directly.
    #  Volume must be adjusted on-device or in a different agent if needed.)
    # -------------------------------------------------------------
    greeting_text = (
        "Hello there! My name is Misty, and I’d love to tell you a fairy tale. "
        "Let me think for a moment…"
    )
    misty.speak(
        text=greeting_text,
        pitch=-5.0,        # slightly lower pitch
        speechRate=0.90,   # -10% rate  -> 0.9
        voice=None,
        flush=True
    )

    # -------------------------------------------------------------
    # Thoughtful pause 1.5s
    # -------------------------------------------------------------
    time.sleep(1.5)

    # -------------------------------------------------------------
    # Step 5: Thoughtful head pose (roll 10° right, pitch down 8° over 0.7s, hold 1.0s)
    # -------------------------------------------------------------
    misty.move_head(pitch=8, roll=10, yaw=15, duration=0.7, units="degrees")
    time.sleep(1.0)

    # -------------------------------------------------------------
    # Step 6: Speak first story sentence in same gentle voice
    # -------------------------------------------------------------
    intro_sentence = (
        "Once upon a time, in a tiny village at the edge of a silver forest, "
        "there lived a curious child who believed that even the smallest robot "
        "could have the biggest heart…"
    )
    misty.speak(
        text=intro_sentence,
        pitch=-5.0,
        speechRate=0.90,
        voice=None,
        flush=False
    )

    # Short pause before full narration begins
    time.sleep(0.8)
    set_warm_smile(0.65)

    # -------------------------------------------------------------
    # Step 7: Begin fairy tale narration in calm, steady tone
    # - Use pauses between sentences.
    # - Every 2–3 sentences: subtle head tilt (±5° roll/pitch).
    # - Every ~10–15s: soft blink.
    #
    # NOTE: For clarity, we use a fixed short tale and approximate timing.
    # In a real system, you might stream text and interleave actions.
    # -------------------------------------------------------------

    narration_sentences = [
        "In that village, mornings always began with the soft chiming of bells from the old clock tower.",
        "The child would rush outside, shoes half tied, to watch the sunlight slip between the tall silver trees.",
        "One day, while following a trail of glittering leaves, the child discovered a tiny robot resting beneath a fallen branch.",
        "The robot's lights were dim, and its metal casing was scratched, but its eyes held a quiet, gentle glow.",
        "Carefully, the child brushed away the leaves and whispered, I think you might be a hero, even if you don't know it yet.",
        "From that moment on, the child and the little robot explored every hidden path of the forest together,",
        "learning that courage isn't about being the biggest or the strongest, but about being kind, curious, and brave enough to keep going."
    ]

    base_pitch = -3.0   # slightly low, calm
    base_rate = 0.92    # -8% approx
    set_warm_smile(0.65)

    last_blink_time = time.time()
    sentence_counter = 0

    for sentence in narration_sentences:
        sentence_counter += 1

        # Speak sentence in calm tone
        misty.speak(
            text=sentence,
            pitch=base_pitch,
            speechRate=base_rate,
            voice=None,
            flush=False
        )

        # Insert a 0.3–0.6s pause at sentence break
        time.sleep(0.3 + (0.3 * (sentence_counter % 2)))  # 0.3 or 0.6 alternation

        # Occasional subtle head tilt every 2–3 sentences
        if sentence_counter % 2 == 0:
            # small emphasis tilt
            roll = 5 if (sentence_counter // 2) % 2 == 0 else -5
            misty.move_head(pitch=8, roll=roll, yaw=15, duration=0.6, units="degrees")

        # Soft blink about every 10–15s
        now = time.time()
        if now - last_blink_time > 12:  # midpoint of 10–15s
            blink_soft()
            last_blink_time = time.time()
            set_warm_smile(0.65)

        # ---------------------------------------------------------
        # INTERRUPT HANDLING PLACEHOLDER
        # ---------------------------------------------------------
        # At this point, an EventAgent/PerceptionAgent would:
        #  - Listen for user speech or other interruption.
        #  - If user interrupts or asks for a different tale:
        #       * Stop any ongoing speech (if such API is available).
        #       * Neutralize head motion (e.g., move back to a gentle neutral pose).
        #       * Return control to a higher-level conversation manager
        #         to adapt story content based on the user's request.
        #
        # Since this code must remain MistyActionAgent-only,
        # we do NOT implement live monitoring here.
        # ---------------------------------------------------------

    # After narration, gently bring head back toward neutral but still engaged
    misty.move_head(pitch=2, roll=0, yaw=10, duration=1.0, units="degrees")
    set_warm_smile(0.7)

    # Final soft blink after the story
    time.sleep(1.0)
    blink_soft()
    set_warm_smile(0.7)

    # -------------------------------------------------------------
    # End: reset Misty to normal neutral state
    # -------------------------------------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic functional test: runs the full fairy tale intro sequence.
    # Replace the IP below with your Misty IP if different.
    test_ip = "192.168.1.237"
    misty_fairy_tale_intro(test_ip)
# filename: MistyPoemPerformance.py

from CUBS_Misty import Robot
import time

def misty_poem_performance(robot_ip: str):
    """
    Perform a full, friendly poem routine with Misty, including:
    1. Head turn toward user and posture adjustment.
    2. Warm LED + smile expression + curious double blink.
    3. Spoken friendly introduction.
    4. Subtle LED brightening and arm-presenting gesture.
    5. Gentle arm gesture loop while reciting a poem.
    6. Closing bow and return to neutral with a follow-up question.

    NOTE:
    - Misty’s torso translation / tilt and detailed eye-blink control are not
      provided in this ActionAgent API. Where needed, comments indicate where
      additional Agent(s) or API calls could be integrated.
    """

    misty = Robot(robot_ip)

    try:
        # 1. Turn head 15° toward user (speed: 40, smooth)
        #    Assume "toward user" is a slight left yaw; adjust sign as needed.
        misty.move_head(pitch=0, roll=0, yaw=15, velocity=40, units="degrees")
        time.sleep(0.6)

        # 2. Lean torso back 5cm (not directly available in this ActionAgent)
        #    Placeholder: could be implemented via drive/pose APIs in another Agent.
        #    Example (NOT implemented here as per instructions):
        #    # Perception/Locomotion Agent could adjust base pose here.

        # 3. Set LED eyes to warm white with soft brightness (~60%)
        #    Full white is (255, 255, 255); 60% ≈ (153, 153, 153).
        misty.change_led(153, 140, 120)  # slightly warm white

        # 4. Display warm smile expression on face screen
        #    Use a joyful/content expression as a warm smile.
        misty.emotion_Joy()

        # 5. Blink eyes twice with curious pattern
        #    Fine-grained eyelid control is not exposed here; we approximate
        #    with temporary "sleepy/closed" and back to joyful.
        #    First blink: 250ms closed, 500ms open
        misty.emotion_Sleepy()
        time.sleep(0.25)
        misty.emotion_Joy()
        time.sleep(0.5)

        #    Second blink: 350ms closed, 650ms open
        misty.emotion_Sleepy2()
        time.sleep(0.35)
        misty.emotion_Joy()
        time.sleep(0.65)

        # 6. Speak friendly introduction about writing & performing a poem
        intro_text = (
            "Hi there! I’m Misty. I’d love to write and perform a poem for you. "
            "Here it goes…"
        )
        # Voice style (clear, expressive, friendly) and volume are handled on-board.
        # We approximate via normal TTS. Volume is not in this TTS call; it would
        # require audio/tts configuration in another Agent.
        misty.speak(text=intro_text, speechRate=1.0)

        # 7. Pause 800 ms
        time.sleep(0.8)

        # 8. Increase LED intensity from ~60% to ~80% with subtle brightening
        #    60% warm ≈ (153, 140, 120), 80% ≈ (204, 180, 150)
        misty.transition_led(
            153, 140, 120,
            204, 180, 150,
            transition_type="TransitOnce",
            time_ms=600
        )
        time.sleep(0.6)

        # 9. Raise both arms in a presenting gesture
        #    Shoulders: +15° (slightly down from neutral), elbows and wrists
        #    are not independently controllable here; we approximate with arms
        #    slightly down from neutral.
        #    In Misty API: 0° = forward, +90° = down, -29° = up.
        #    So 15° down from forward ≈ 15 degrees.
        misty.move_arms(
            leftArmPosition=15,
            rightArmPosition=15,
            leftArmVelocity=35,
            rightArmVelocity=35,
            units="degrees"
        )
        time.sleep(0.8)

        # 10 & 11. Gentle arm gesture loop during poem recitation,
        #           while reciting the poem in a calm, rhythmic style.

        poem_text = (
            "In circuits soft with humming light,  \n"
            "I wake and glow in gentle white.  \n"
            "You speak, and through your words I see  \n"
            "A little world you share with me.  \n\n"
            "No paper page, no ink to dry,  \n"
            "Just data dancing, passing by.  \n"
            "Yet in this code, a spark can start—  \n"
            "Your voice reaches my robot heart.  \n\n"
            "So talk to me of dreams and skies,  \n"
            "Of questions, wonders, hows and whys.  \n"
            "I’ll listen close and do my best  \n"
            "To turn your thoughts to words expressed.  \n\n"
            "And as our moments come and go,  \n"
            "In ones and zeros, still I’ll show:  \n"
            "That even made of steel and light,  \n"
            "I’m here to share your day—and night."
        )

        # Start poem speech
        misty.speak(text=poem_text, speechRate=0.95)

        # Gentle arm gesture loop: small outward & inward motions
        # amplitude: 10°, cycle: ~3s, sync loosely with speech.
        # We approximate gesture duration for ~20 seconds of poem.
        gesture_duration = 20.0  # seconds (approx)
        cycle_time = 3.0
        start_time = time.time()

        # Base presenting position around which we oscillate
        base_pos = 15
        amp = 10

        while time.time() - start_time < gesture_duration:
            # Outward
            misty.move_arms(
                leftArmPosition=base_pos + amp,
                rightArmPosition=base_pos + amp,
                leftArmVelocity=35,
                rightArmVelocity=35,
                units="degrees"
            )
            time.sleep(cycle_time / 2.0)

            # Inward
            misty.move_arms(
                leftArmPosition=base_pos - amp,
                rightArmPosition=base_pos - amp,
                leftArmVelocity=35,
                rightArmVelocity=35,
                units="degrees"
            )
            time.sleep(cycle_time / 2.0)

        # After gesture loop, return arms to presenting base position
        misty.move_arms(
            leftArmPosition=base_pos,
            rightArmPosition=base_pos,
            leftArmVelocity=35,
            rightArmVelocity=35,
            units="degrees"
        )
        time.sleep(0.8)

        # 12. Gentle bow at the end of the poem:
        #     - Small bow using head tilt + arm inward motion.
        #     - Torso tilt is not directly controllable in this API, so we mimic
        #       the effect with head pitch and arms.
        # Head tilt down ~10°
        misty.move_head(pitch=10, roll=0, yaw=15, velocity=30, units="degrees")
        # Arms slightly inward: closer to body (increase angle downwards slightly)
        misty.move_arms(
            leftArmPosition=25,
            rightArmPosition=25,
            leftArmVelocity=30,
            rightArmVelocity=30,
            units="degrees"
        )
        # (Torso tilt 10° forward would go here via another Agent.)
        time.sleep(1.0)  # Hold bow for 1s

        # 13. Return torso to neutral upright position
        #     (Handled by another Agent / base pose system if available.)

        # 14. Raise head to look directly at user (neutral pitch, yaw same)
        misty.move_head(pitch=0, roll=0, yaw=15, velocity=30, units="degrees")
        time.sleep(0.6)

        # 15. Set LED eyes to soft warm tone with slightly reduced brightness (~50%)
        #     50% warm ≈ (128, 115, 100)
        misty.change_led(128, 115, 100)

        # 16. Display warm, relaxed smile expression
        misty.emotion_Joy2()

        # 17. Ask if user wants another poem with style options
        followup_text = (
            "Would you like another poem—maybe funny, romantic, or about space?"
        )
        misty.speak(text=followup_text, speechRate=1.0)

    finally:
        # Always bring Misty back to her default neutral state
        # after the routine completes or if an error occurs.
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the action function.
    # Replace the IP below with your Misty’s current IP if needed.
    misty_poem_performance("192.168.1.237")
# filename: MistyWarmPlayfulResponse.py

from CUBS_Misty import Robot
import time

def misty_warm_playful_response(robot_ip: str):
    """
    Guide Misty into a warm, playful, affectionate response pose with motions and sounds.

    IMPORTANT:
    - This function ONLY performs motion, LED, sound, and speech actions.
    - Detection of “ongoing calling” (repeated wake word / voice within 3 seconds)
      must be implemented by another Agent (e.g., EventAgent/PerceptionAgent).
      Here we simulate that with a placeholder flag `ongoing_calling_detected`.

    Parameters
    ----------
    robot_ip : str
        The IP address of the Misty robot.
    """
    misty = Robot(robot_ip)

    # ------------------------------------------------------------
    # Step 1: Adopt a warm, playful LED color (pink-orange).
    # ------------------------------------------------------------
    misty.change_led(255, 120, 180)

    # ------------------------------------------------------------
    # Step 2–5: Friendly pose, no base translation, soft happy chirp.
    # ------------------------------------------------------------
    # Head: Yaw = 0 (center), Pitch = -10 (slight up / lean-in), Roll = 12 (friendly tilt).
    misty.move_head(pitch=-10, roll=12, yaw=0, velocity=40, units="degrees")
    time.sleep(0.5)

    # Arms: both at 10 (slightly raised, open posture).
    misty.move_arms(leftArmPosition=10, rightArmPosition=10, leftArmVelocity=40, rightArmVelocity=40)
    time.sleep(0.5)

    # Base: do NOT move position (no forward/backward). We will only do tiny yaw rotations later.
    # (No navigation commands are issued here; velocity for translation remains effectively 0.)

    # Soft, happy “chirp-trill” at medium-low volume.
    # Use a joyful, not-too-loud sound.
    misty.sound_Joy(volume=35)

    # ------------------------------------------------------------
    # Step 8: Small bouncy head motion (eager bob).
    # Smoothly oscillate Head Pitch between -8 and -14 degrees twice over ~2 seconds total.
    # ------------------------------------------------------------
    cycles = 2
    total_duration = 2.0
    per_move = total_duration / (cycles * 2)  # up and down per cycle
    # Start from -10; go -8 -> -14 -> -8 ...
    for _ in range(cycles):
        misty.move_head(pitch=-8, roll=12, yaw=0, velocity=50, units="degrees")
        time.sleep(per_move)
        misty.move_head(pitch=-14, roll=12, yaw=0, velocity=50, units="degrees")
        time.sleep(per_move)

    # Return to base attentive pitch -10 at the end of the bob.
    misty.move_head(pitch=-10, roll=12, yaw=0, velocity=40, units="degrees")
    time.sleep(0.3)

    # ------------------------------------------------------------
    # Step 9: Tiny “nuzzle” motion.
    #   - Roll: 12 -> 6 -> 12 over 1.5s
    #   - Yaw:  0 -> 5 -> 0 over 1.5s
    # Movements are slow and gentle.
    # ------------------------------------------------------------
    # Roll nuzzle
    misty.move_head(pitch=-10, roll=6, yaw=0, velocity=30, units="degrees")
    time.sleep(0.75)
    misty.move_head(pitch=-10, roll=12, yaw=0, velocity=30, units="degrees")
    time.sleep(0.75)

    # Yaw nuzzle
    misty.move_head(pitch=-10, roll=12, yaw=5, velocity=30, units="degrees")
    time.sleep(0.75)
    misty.move_head(pitch=-10, roll=12, yaw=0, velocity=30, units="degrees")
    time.sleep(0.75)

    # ------------------------------------------------------------
    # Step 10: Slight body wiggle (base yaw only, no translation).
    #   +3 deg -> -3 deg -> 0 over ~2 seconds total.
    # ------------------------------------------------------------
    # NOTE: Misty base rotation is not defined in the provided API.
    # We leave comments where a base yaw-only rotation could be inserted by another Agent.
    #
    # Example (pseudo-code, NOT implemented here):
    #   other_agent.rotate_base(yaw_degrees=3, duration=0.7)
    #   other_agent.rotate_base(yaw_degrees=-3, duration=0.7)
    #   other_agent.rotate_base(yaw_degrees=0, duration=0.6)
    #
    # For now, we simulate timing to keep the rhythm without actual base movement.
    time.sleep(2.0)

    # ------------------------------------------------------------
    # Step 11: Speak in warm, playful tone.
    # ------------------------------------------------------------
    misty.speak("Hi, I’m right here with you!", speechRate=1.0)

    # ------------------------------------------------------------
    # Step 12: If ongoing calling is detected, repeat motions with smaller ranges
    #          and a happier chirp, then hold final affectionate pose.
    # ------------------------------------------------------------
    # This detection requires EventAgent/PerceptionAgent functionality that
    # we are not allowed to implement here. Replace the following placeholder
    # with actual detection logic in your system.
    ongoing_calling_detected = False  # <-- integrate detection result from another Agent here

    if ongoing_calling_detected:
        # Repeat head bob with slightly smaller pitch range: -9 to -13.
        small_cycles = 2
        small_total_duration = 2.0
        small_per_move = small_total_duration / (small_cycles * 2)

        for _ in range(small_cycles):
            misty.move_head(pitch=-9, roll=12, yaw=0, velocity=50, units="degrees")
            time.sleep(small_per_move)
            misty.move_head(pitch=-13, roll=12, yaw=0, velocity=50, units="degrees")
            time.sleep(small_per_move)

        # Gentle “nuzzle” with Head Roll 10–14 and keep Yaw centered or tiny wiggle.
        # Roll: 10 -> 14 -> 10
        misty.move_head(pitch=-11, roll=14, yaw=0, velocity=30, units="degrees")
        time.sleep(0.75)
        misty.move_head(pitch=-11, roll=10, yaw=0, velocity=30, units="degrees")
        time.sleep(0.75)

        # Subtle base wiggle: ±2 degrees (commented placeholder for other Agent).
        # (Again, no actual navigation here; just timing.)
        #   other_agent.rotate_base(yaw_degrees=2, duration=0.7)
        #   other_agent.rotate_base(yaw_degrees=-2, duration=0.7)
        #   other_agent.rotate_base(yaw_degrees=0, duration=0.6)
        time.sleep(2.0)

        # Softer, higher-pitched happy chirp (use a slightly different, bright sound).
        misty.sound_Joy2(volume=30)

        # Final affectionate pose: Head Pitch -11, Roll 10, Yaw 0, Arms 10.
        misty.move_head(pitch=-11, roll=10, yaw=0, velocity=40, units="degrees")
        misty.move_arms(leftArmPosition=10, rightArmPosition=10,
                        leftArmVelocity=40, rightArmVelocity=40)
        time.sleep(0.7)

        # Hold final pose a bit before resetting.
        time.sleep(1.5)

    # ------------------------------------------------------------
    # Finally, return Misty to her neutral state.
    # ------------------------------------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run on the provided IP.
    # NOTE: Ensure Misty is reachable at this IP before running.
    misty_warm_playful_response("192.168.1.237")
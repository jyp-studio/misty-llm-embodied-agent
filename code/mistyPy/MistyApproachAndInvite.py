# filename: MistyApproachAndInvite.py

from CUBS_Misty import Robot
import time


def misty_approach_and_invite(robot_ip: str):
    """
    Execute a calm, friendly approach-and-invite behavior for Misty.

    High-level script:
    1. Turn head ~15° toward last known user position over 0.8s.
    2. Set chest/head LEDs to soft blue with a gentle pulsing effect (simulated) for ~6s.
    3. Perform a "curious" head tilt gesture (right, left, back to neutral).
    4. Raise right arm and perform a small friendly hand wave, then lower back to neutral.
    5. Take a small step forward (~6cm) toward last known user position and hold.
    6. Pause all body motion for 1.0s.
    7. Speak a friendly invitation message.
    8. Slowly scan with head from ~20° left to ~20° right over ~6s, then re-center toward user.
    9. Rotate torso to roughly face last known user direction.
    10. Adopt an open, relaxed arm posture and maintain a subtle LED pulsing effect to signal readiness.

    NOTE:
    - This function assumes "last known user position" has already been computed by another agent.
      Integrate here by replacing the hard-coded angles/forward distance with values from that agent.
    """

    misty = Robot(robot_ip)

    try:
        # ---------------------------------------------------------------------
        # 1. Orient head toward last known user position (approx +15° yaw)
        # ---------------------------------------------------------------------
        # TODO: Replace yaw=15 with actual relative yaw from Perception/Event agent.
        misty.move_head(
            pitch=0, yaw=15, roll=0, velocity=50, duration=0.8, units="degrees"
        )
        time.sleep(0.8)

        # ---------------------------------------------------------------------
        # 2. Soft blue LEDs with gentle pulsing for ~6s (2s cycle, 3 cycles)
        #    We approximate pulsing by transitioning between darker and brighter blue.
        # ---------------------------------------------------------------------
        # Start with a mid soft blue
        misty.change_led(red=40, green=120, blue=255)

        # 3 cycles, each 2 seconds: fade 20%→70%→20%
        # We approximate "brightness %%" by scaling RGB.
        for _ in range(3):
            # 20% brightness equivalent (dimmer blue)
            misty.transition_led(
                red=15,
                green=45,
                blue=90,  # low-intensity blue
                red2=50,
                green2=150,
                blue2=255,  # higher-intensity blue
                transition_type="Breathe",
                time_ms=1000,  # 1s up
            )
            time.sleep(1.0)
            # Back down from bright to dim in 1s
            misty.transition_led(
                red=50,
                green=150,
                blue=255,
                red2=15,
                green2=45,
                blue2=90,
                transition_type="Breathe",
                time_ms=1000,
            )
            time.sleep(1.0)

        # ---------------------------------------------------------------------
        # 3. Curious head tilt gesture:
        #    - Tilt 10° right over 0.6s, hold 0.5s
        #    - Tilt 10° left over 0.6s, hold 0.5s
        #    - Return to neutral over 0.6s
        # ---------------------------------------------------------------------
        # Right tilt: roll positive ~10°
        misty.move_head(
            pitch=0, yaw=15, roll=10, velocity=50, duration=0.6, units="degrees"
        )
        time.sleep(0.6)
        time.sleep(0.5)  # hold

        # Left tilt: roll negative ~10°
        misty.move_head(
            pitch=0, yaw=15, roll=-10, velocity=50, duration=0.6, units="degrees"
        )
        time.sleep(0.6)
        time.sleep(0.5)  # hold

        # Back to neutral (still facing user yaw ~15°)
        misty.move_head(
            pitch=0, yaw=15, roll=0, velocity=50, duration=0.6, units="degrees"
        )
        time.sleep(0.6)

        # ---------------------------------------------------------------------
        # 4. Raise right arm, wave hand, then lower arm
        #    NOTE: Wrist/hand control requires additional APIs not exposed here.
        #    We simulate hand wave by small right-arm oscillations.
        # ---------------------------------------------------------------------
        # Step 1: Raise right arm to ~30° forward (positive down)
        # TODO: If your system separates shoulder & elbow, call that API here.
        misty.move_arms(
            leftArmPosition=0,
            rightArmPosition=30,  # 30° forward
            leftArmVelocity=50,
            rightArmVelocity=50,
            duration=0.7,
            units="degrees",
        )
        time.sleep(0.7)

        # Step 2: "Wrist wave" approximation:
        # Small 3-cycle movement around the raised pose.
        for _ in range(3):
            # Slightly more forward
            misty.move_arms(
                leftArmPosition=0,
                rightArmPosition=40,
                leftArmVelocity=70,
                rightArmVelocity=70,
                duration=0.25,
                units="degrees",
            )
            time.sleep(0.25)

            # Slightly less forward
            misty.move_arms(
                leftArmPosition=0,
                rightArmPosition=20,
                leftArmVelocity=70,
                rightArmVelocity=70,
                duration=0.25,
                units="degrees",
            )
            time.sleep(0.25)

        # Step 3: Return wrist/arm back to neutral slowly (~0.4 + 0.3s)
        misty.move_arms(
            leftArmPosition=0,
            rightArmPosition=15,
            leftArmVelocity=40,
            rightArmVelocity=40,
            duration=0.4,
            units="degrees",
        )
        time.sleep(0.4)

        # ---------------------------------------------------------------------
        # 5. Lower right arm smoothly back to neutral over 0.7s
        # ---------------------------------------------------------------------
        misty.move_arms(
            leftArmPosition=0,
            rightArmPosition=0,
            leftArmVelocity=40,
            rightArmVelocity=40,
            duration=0.7,
            units="degrees",
        )
        time.sleep(0.7)

        # ---------------------------------------------------------------------
        # 6. Take a small step forward (~6cm) toward user, then hold
        # ---------------------------------------------------------------------
        # NOTE: The provided API snippet does not include drive/locomotion.
        # Insert a call here to your motion/drive API, e.g.:
        #   misty.drive(linearVelocity=0.03, angularVelocity=0.0)
        #   time.sleep(6cm / 3cm/s = 2.0s)
        #   misty.stop()
        #
        # For now we just leave a comment placeholder and a gentle "ready" sound.
        # --- BEGIN: integrate Perception/Navigation Agent here ---
        # TODO: Use Perception/Navigation Agent to compute and perform 6cm step forward
        # toward last known user position at ~0.03 m/s for ~2s, then stop.
        # --- END: integrate Perception/Navigation Agent here ---
        time.sleep(2.0)  # placeholder hold to approximate step duration

        # ---------------------------------------------------------------------
        # 7. Pause body motion for 1.0s to appear calm
        # ---------------------------------------------------------------------
        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # 8. Speak friendly greeting
        # ---------------------------------------------------------------------
        misty.speak(
            text=(
                "My name is Misty. I can’t see or hear you clearly right now, "
                "but I know you’re nearby. If you’d like to talk, please step "
                "a little closer and say something so I can understand you better."
            ),
            speechRate=1.0,
        )
        # Give time for TTS to play; the speak wrapper handles ignore buffer itself.
        # Roughly estimate ~12s for this length of text; can be tuned.
        time.sleep(12)

        # ---------------------------------------------------------------------
        # 9. Slow head scan: 20° left to 20° right over ~6s, then face user again
        # ---------------------------------------------------------------------
        # First look a bit left of user (15° user + 5° extra → 20° if we were at 15°)
        # For simplicity, move yaw to -20 (left) then sweep to +20 (right).
        misty.move_head(
            pitch=0, yaw=-20, roll=0, velocity=20, duration=3.0, units="degrees"
        )
        time.sleep(3.0)

        misty.move_head(
            pitch=0, yaw=20, roll=0, velocity=20, duration=3.0, units="degrees"
        )
        time.sleep(3.0)

        # Return to "last known user" yaw ~15°
        misty.move_head(
            pitch=0, yaw=15, roll=0, velocity=30, duration=1.0, units="degrees"
        )
        time.sleep(1.0)

        # ---------------------------------------------------------------------
        # 10. Rotate torso/body so it faces user within ~5°
        # ---------------------------------------------------------------------
        # Again, there is no torso-rotation API in the given snippet.
        # --- BEGIN: integrate base/torso rotation Agent here ---
        # TODO: Use drive/turn API to rotate base until facing user within 5°
        # e.g., misty.drive(linearVelocity=0.0, angularVelocity=theta_dot) ...
        # --- END: integrate base/torso rotation Agent here ---
        time.sleep(1.5)  # placeholder for torso rotation duration

        # ---------------------------------------------------------------------
        # 11. Relaxed, open arm posture + subtle low-intensity LED pulsing
        # ---------------------------------------------------------------------
        # Arms: shoulders slightly forward (~10°), elbows ~15°; approximate with arm positions.
        # (Given a single arm joint, we simulate by small forward angle.)
        misty.move_arms(
            leftArmPosition=10,
            rightArmPosition=10,
            leftArmVelocity=30,
            rightArmVelocity=30,
            duration=1.0,
            units="degrees",
        )
        time.sleep(1.0)

        # Subtle low-intensity pulsing: 10–30% brightness, 3s cycle (approx 2 cycles).
        for _ in range(2):
            misty.transition_led(
                red=10,
                green=30,
                blue=60,  # dim blue
                red2=30,
                green2=90,
                blue2=180,  # a bit brighter blue
                transition_type="Breathe",
                time_ms=1500,  # 1.5s up
            )
            time.sleep(1.5)
            misty.transition_led(
                red=30,
                green=90,
                blue=180,
                red2=10,
                green2=30,
                blue2=60,
                transition_type="Breathe",
                time_ms=1500,  # 1.5s down
            )
            time.sleep(1.5)

        # At this point, keep arms relaxed and LEDs softly pulsing.
        # Caller can interrupt or continue with other behaviors.

    finally:
        # Always return Misty to her neutral state at the end of this task.
        misty.return_to_normal()


if __name__ == "__main__":
    # Basic test execution with the provided IP.
    # NOTE: Ensure this machine can reach Misty at this IP on your network.
    misty_approach_and_invite("192.168.1.237")

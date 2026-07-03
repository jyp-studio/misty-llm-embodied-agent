# filename: MistyAffectionateApproach.py

from CUBS_Misty import Robot
import time

def misty_affectionate_approach(robot_ip: str):
    """
    Perform an affectionate, close-approach sequence with Misty.

    High-level behavior (mapped from YOURTASK steps):
    1. Set LED to a warm, soft pink color.
    2. (Stub) Orient the body toward the user’s voice direction.
       NOTE: Actual bearing-from-voice estimation must be handled by another Agent.
    3. Pose the head in an attentive, slightly bashful way.
    4. Lift both arms into a slightly inviting position.
    5. Perform a small, playful lean/step forward, then pause.
    6. Add a subtle eager forward adjustment, then hold a close position.
    7. Refine close-range body language to convey affectionate attention.
    8. Play a soft, happy vocalization and warm, affectionate spoken greeting.
    9. Maintain the final close, affectionate pose for a short period.

    Parameters
    ----------
    robot_ip : str
        IP address of the Misty robot.
    """

    misty = Robot(robot_ip)

    # --- Step 1: LED to warm soft pink (R:255, G:160, B:200) ---
    misty.change_led(255, 160, 200)

    # --- Step 2: Orient toward user's voice (ROTATION ONLY) ---
    # IMPORTANT:
    #   The actual computation of the user's last known bearing from audio
    #   must come from a Perception / Event agent; we cannot implement it here.
    #
    #   Integration point:
    #   - Replace `target_yaw_degrees` with a value computed by another agent.
    #   - Rotate Misty's base or body to that yaw.
    #
    # For now, we assume Misty is already roughly facing the user and perform
    # a small, smooth, neutral alignment-style "micro-orientation" motion
    # via head yaw to simulate orienting without using Event/Perception APIs.
    target_yaw_degrees = 0  # <-- to be updated by another Agent when integrated
    # Cute, small alignment head move to represent facing the user.
    misty.move_head(pitch=0, yaw=target_yaw_degrees, roll=0, velocity=25, units="degrees")
    time.sleep(0.8)

    # --- Step 3: Attentive, slightly bashful head pose ---
    # Head Pitch -10 (slight up), Yaw 0 (centered), Roll 12 (gentle tilt)
    misty.move_head(pitch=-10, yaw=0, roll=12, velocity=25, units="degrees")
    time.sleep(0.8)

    # --- Step 4: Arms slightly lifted, inviting (both to 10) ---
    misty.move_arms(leftArmPosition=10, rightArmPosition=10,
                    leftArmVelocity=40, rightArmVelocity=40)
    time.sleep(0.8)

    # --- Steps 5 & 6: Small playful forward "lean/step" and eager adjustment ---
    # IMPORTANT:
    #   Actual translational base movement must be done with base/drive APIs
    #   (e.g., DriveTime or DriveDistance). Those are not part of the provided
    #   ActionAgent API here, so we do NOT implement real motion.
    #
    #   Integration point:
    #   - Another Agent (e.g., Motion/Navigation) should be used to:
    #       * Move forward 10 cm at velocity 20, stop.
    #       * Then move additional 5 cm at velocity 15, stop.
    #
    # To approximate a "lean/step" feeling with allowed APIs, we use:
    #   - Slight head-and-arm coordinated motion to simulate leaning forward.

    # Simulated lean forward: head down a bit, tiny arm adjustment.
    misty.move_head(pitch=5, yaw=0, roll=12, velocity=25, units="degrees")
    misty.move_arms(leftArmPosition=15, rightArmPosition=15,
                    leftArmVelocity=35, rightArmVelocity=35)
    time.sleep(1.0)

    # Simulated subtle eager adjustment.
    misty.move_head(pitch=0, yaw=0, roll=13, velocity=25, units="degrees")
    misty.move_arms(leftArmPosition=12, rightArmPosition=12,
                    leftArmVelocity=30, rightArmVelocity=30)
    time.sleep(1.0)

    # --- Step 7: Refine pose for close, affectionate attention ---
    #   - Head Pitch to -5 (a bit more level, still engaged)
    #   - Head Yaw to 0 (centered)
    #   - Head Roll to 15 (more bashful tilt)
    #   - Arms to 0 (relaxed but open/friendly)
    misty.move_head(pitch=-5, yaw=0, roll=15, velocity=25, units="degrees")
    misty.move_arms(leftArmPosition=0, rightArmPosition=0,
                    leftArmVelocity=30, rightArmVelocity=30)
    time.sleep(1.0)

    # --- Step 8: Soft, happy vocalization + warm greeting ---
    # Use built-in happy/joy sound plus TTS phrase.
    misty.sound_Joy2()  # gentle happy sound
    time.sleep(0.6)
    misty.speak("Hi, Miss T... mmm-hmm!", speechRate=0.95)
    # Allow some time so that the vocalization completes enough before next step.
    time.sleep(2.5)

    # --- Step 9: Hold final close, affectionate pose for at least 4 seconds ---
    # Keep head, arms, LED as-is; maintain an "attentive" micro-motion-free hold.
    hold_time_sec = 4.0
    time.sleep(hold_time_sec)

    # After the behavior finishes, ALWAYS reset Misty to normal.
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run for the affectionate approach behavior.
    # Replace the IP with your Misty’s IP if needed.
    misty_affectionate_approach("192.168.1.237")
# filename: MistyWarmAttentiveIdle.py

from CUBS_Misty import Robot
import time

def misty_warm_attentive_idle(robot_ip: str):
    """
    Guide Misty into a warm, relaxed, and attentive idle listening posture.

    TASKS:
    1. Orient the head toward the user and slightly tilt it to the right.
    2. Adopt a gentle, relaxed arm and hand posture with a slightly open stance.
    3. Set eye visuals and facial display to convey a warm, relaxed, attentive presence.
    4. Cease speech output while maintaining an attentive idle behavior without
       further movement toward the user.

    Notes:
    - This function assumes Misty is already facing the user with her torso.
    - No movement toward the user is performed (only posture/face/LED changes).
    - At the end, return_to_normal() is called to restore Misty’s default state.
    """

    # Instantiate Misty inside the function
    misty = Robot(robot_ip)

    # ----------------------------
    # 1. Head orientation
    # ----------------------------
    # Face the user (torso-aligned yaw = 0), slight tilt to the RIGHT:
    # roll: positive = right tilt; small (10°) for gentle attentiveness.
    misty.move_head(
        pitch=-5,    # very slight up / neutral (assume user at similar or slightly higher eye level)
        yaw=0,       # aligned with torso (toward user)
        roll=10,     # tilt head slightly to the right
        velocity=15, # slow, smooth movement
        duration=1.5,
        units="degrees"
    )
    time.sleep(1.5)

    # ----------------------------
    # 2. Relaxed, open arm posture
    # ----------------------------
    # Arms slightly forward/down, relaxed – open, not defensive.
    misty.move_arms(
        leftArmPosition=20,   # a bit forward from straight-down
        rightArmPosition=20,  # symmetrical, relaxed
        leftArmVelocity=20,
        rightArmVelocity=20,
        duration=1.5,
        units="degrees"
    )
    time.sleep(1.5)

    # ----------------------------
    # 3. Warm, relaxed, attentive face
    # ----------------------------
    # Use a mild, warm content/joy expression with soft eyes.
    # We approximate:
    #   - A calm content face as base
    #   - Slight joy for a subtle smile
    misty.emotion_Joy()  # soft, kind smile & warm eyes
    misty.change_led(255, 230, 200)  # warm soft white/orange tint

    # Optional: a single slow blink to settle into attentive mode.
    # We approximate blink with a quick "sleepy" face and then back.
    misty.emotion_Sleepy()  # half-lidded/closed eyes to mimic blink
    time.sleep(0.4)         # eyelids close over ~0.4s
    time.sleep(0.2)         # hold closed ~0.2s
    misty.emotion_Joy()     # reopen to the gentle smile/attentive eyes over ~0.4s
    time.sleep(0.4)

    # ----------------------------
    # 4. Cease speech and maintain quiet, attentive idle (no approach)
    # ----------------------------
    # We do NOT call speak(), so Misty remains silent.
    # Maintain a short, attentive idle with minimal movement:
    idle_duration = 5  # seconds of quiet, attentive stance (adjust as needed)
    blink_interval_min = 4.0
    blink_interval_max = 6.0

    start_time = time.time()
    next_blink_time = start_time + blink_interval_min

    while time.time() - start_time < idle_duration:
        now = time.time()
        if now >= next_blink_time:
            # Perform a soft, slow blink (approximate)
            misty.emotion_Sleepy2()  # slightly stronger lid lowering
            time.sleep(0.3)          # close over ~0.3s
            time.sleep(0.1)          # brief hold
            misty.emotion_Joy()      # reopen to gentle smile
            time.sleep(0.3)

            # Schedule next blink between 4–6 seconds
            next_blink_time = now + blink_interval_min + (blink_interval_max - blink_interval_min) * 0.5

        # Keep posture & gaze steady (no fidgeting or re-orientation)
        time.sleep(0.1)

    # ---------------------------------
    # Reset Misty to her normal state
    # ---------------------------------
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run: executes the warm attentive idle behavior once.
    misty_warm_attentive_idle("192.168.1.237")
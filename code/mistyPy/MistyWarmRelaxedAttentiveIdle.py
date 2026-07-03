# filename: MistyWarmRelaxedAttentiveIdle.py

from CUBS_Misty import Robot
import time

def misty_warm_relaxed_attentive_idle(robot_ip: str):
    """
    Guide Misty into a warm, relaxed, and attentive idle stance.
    
    Behavior:
    1. Orient the head toward the user and slightly tilt it to the right.
    2. Adopt a gentle, relaxed arm posture with a slightly open stance.
    3. Set eye visuals / facial display to a warm, relaxed, and attentive expression.
    4. Cease speech output while maintaining an attentive but mostly still pose
       (no additional movement toward the user).
    
    Notes:
    - This function focuses purely on posture, expression, and LED.
    - No speech is initiated here (requirement 4).
    - Any continuous perception (e.g., AV streaming, wake-word listening, etc.)
      should be handled by another Agent; integrate it where needed.
    """

    misty = Robot(robot_ip)

    # 1) HEAD ORIENTATION: toward user + slight tilt right
    # Assume Misty is already generally oriented toward user; just ensure:
    # - yaw ~ 0° (facing forward)
    # - pitch slightly downward (for eye-contact at conversational distance)
    # - roll slightly to the right.
    misty.move_head(
        pitch=5,    # small downward tilt for conversational eye line
        yaw=0,      # facing straight toward user
        roll=8,     # slight right tilt for a gentle, relaxed look
        velocity=25,
        units="degrees"
    )
    time.sleep(1.0)

    # 2) GENTLE RELAXED ARM / HAND POSTURE:
    # Use a slightly open stance: arms slightly lowered and parted.
    # Positive degrees = down; negative = up (per API doc comments).
    misty.move_arms(
        leftArmPosition=30,   # slightly down
        rightArmPosition=30,  # slightly down
        leftArmVelocity=30,
        rightArmVelocity=30,
        duration=1.2,
        units="degrees"
    )
    time.sleep(1.2)

    # 3) WARM, RELAXED ATTENTIVE EXPRESSION:
    # Use a friendly default content/joy mix & warm LED.
    # There is no explicit "cheerful_wide" or "gentle_smile" graphic,
    # so we approximate with Joy expression and warm LED.
    misty.emotion_Joy()  # bright but not over-the-top smile
    # Warm white with slight yellow tint; 80% brightness approx:
    # Full white would be (255, 255, 255). Warm/yellowish ~ (255, 230, 180).
    misty.change_led(255, 230, 180)

    # 4) CEASE SPEECH OUTPUT:
    # We simply do not call misty.speak() here.
    # If another module was previously speaking, stopping or canceling
    # that should be handled there (EventAgent / PerceptionAgent, etc.).
    # (Place integration hook here if needed.)
    #
    # Example (NOT implemented here, only as guidance):
    #   # TODO: Use EventAgent/PerceptionAgent to stop ongoing speech or TTS queue.

    # Maintain a short, quiet attentive pause in this pose
    # (no additional motion toward the user, only hold current state).
    time.sleep(3.0)

    # After the function completes, restore neutral
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test run on the provided IP.
    # This will:
    #  - Move Misty into the warm relaxed attentive idle pose for a few seconds
    #  - Then automatically return her to normal.
    test_ip = "192.168.1.237"
    misty_warm_relaxed_attentive_idle(test_ip)
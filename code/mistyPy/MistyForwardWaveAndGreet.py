# filename: MistyForwardWaveAndGreet.py

from CUBS_Misty import Robot
import time

def misty_forward_wave_and_greet(robot_ip: str):
    """
    Task:
        1. Move forward ~50cm.
        2. Wave a hand in greeting.
        3. Speak a friendly self-introduction in Chinese.

    Parameters:
        robot_ip (str): The IP address of the Misty robot.
    """

    # IMPORTANT: This function assumes another Agent (e.g., Motion/Drive Agent)
    # provides a drive/locomotion API such as:
    #   misty.drive(linearVelocity, angularVelocity, duration)
    # or
    #   misty.drive_time(linearVelocity, angularVelocity, time_ms)
    #
    # That API is NOT defined in the current MistyActionAgent spec.
    # Below, we add a placeholder comment where you should integrate
    # the actual drive call with the corresponding Agent.

    misty = Robot(robot_ip)

    try:
        # -----------------------------
        # 1. Move forward about 50 cm
        # -----------------------------
        # >>>> INTEGRATE WITH DRIVE/MOTION AGENT HERE <<<<
        #
        # Example (replace with your actual API call):
        #   # Move forward at 200 mm/s for 0.25s → ~50mm (example only)
        #   # To reach ~500mm (50cm) at 200 mm/s → 2.5 seconds
        #   misty.drive_time(linearVelocity=200, angularVelocity=0, time_ms=2500)
        #
        # Since drive functions belong to another Agent, they are NOT
        # implemented here. You must plug them in externally.
        #
        # Temporary timing to allow space for the (future) move:
        move_duration_sec = 2.5  # adjust to match your real drive command
        time.sleep(move_duration_sec)

        # -----------------------------
        # 2. Wave a hand in greeting
        # -----------------------------
        # Use a joyful face and a bright LED while waving
        misty.emotion_Joy()
        misty.change_led(0, 200, 255)  # cyan-like color

        # Lift right arm and perform a simple waving gesture
        # (Right arm up then small repetitive motion)
        misty.move_arms(leftArmPosition=30, rightArmPosition=-29, duration=0.6)
        time.sleep(0.6)

        for _ in range(3):
            misty.move_arms(rightArmPosition=-10, leftArmPosition=30, duration=0.35)
            time.sleep(0.35)
            misty.move_arms(rightArmPosition=-29, leftArmPosition=30, duration=0.35)
            time.sleep(0.35)

        # Bring arms back to a more relaxed posture (return_to_normal will finalize)
        misty.move_arms(leftArmPosition=0, rightArmPosition=0, duration=0.6)
        time.sleep(0.6)

        # -----------------------------
        # 3. Speak a friendly greeting
        # -----------------------------
        # Say: “你好，我是Misty，很高興見到你！”
        # Use the built-in speak() from the provided Robot API.
        text = "你好，我是 Misty，很高興見到你！"
        misty.speak(text=text, speechRate=1.0, language="zh-TW")
        # Wait a bit to ensure speaking finishes (API already estimates internally,
        # but we add a brief buffer for motion sync)
        time.sleep(3.0)

    finally:
        # -----------------------------
        # Reset Misty to her normal state
        # -----------------------------
        misty.return_to_normal()


if __name__ == "__main__":
    # TEST: run the composed action on your Misty
    TEST_IP = "192.168.1.237"
    misty_forward_wave_and_greet(TEST_IP)
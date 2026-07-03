# filename: MistyBriefDrive.py

from CUBS_Misty import Robot
import time

def misty_brief_forward_and_stop(robot_ip: str):
    """
    Make Misty drive forward briefly and then come to a complete stop.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    
    Behavior:
    1. Set a simple content expression and a neutral LED.
    2. Play a short phrase.
    3. Drive forward at a moderate speed for 2 seconds.
    4. Stop completely.
    5. Reset Misty back to her normal/neutral state.
    """
    # Initialize Misty
    misty = Robot(robot_ip)

    # Optional: Small "ready" expression & sound
    misty.emotion_ContentRight()
    misty.change_led(0, 255, 0)   # Green to indicate "ready / moving"
    misty.sound_PhraseHello()
    time.sleep(0.8)  # Let the sound mostly play before driving

    # 1. Initiate brief forward motion
    #    drive(linear_velocity, angular_velocity)
    #    40 = moderate forward speed, 0 = straight (no rotation)
    misty.drive(40, 0)
    
    # Drive for 2 seconds
    time.sleep(2.0)

    # 2. Come to a complete stop
    misty.drive(0, 0)

    # Optional: small confirmation sound & expression before reset
    misty.sound_Acceptance()
    misty.emotion_ContentLeft()
    time.sleep(0.5)

    # Always reset Misty to neutral at the end
    misty.return_to_normal()


if __name__ == "__main__":
    # Basic test: run the brief drive on the specified IP.
    # Replace the IP with your Misty's IP if needed.
    misty_brief_forward_and_stop("192.168.1.237")
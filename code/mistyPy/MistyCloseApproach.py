# filename: MistyCloseApproach.py

from CUBS_Misty import Robot
import time

def misty_express_and_approach(robot_ip):
    '''
    Misty will express happiness, nod, and confirm movement by speaking, then move closer.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    '''
    # Initialize Misty robot
    misty = Robot(robot_ip)
    
    # Step 1: Express happiness
    misty.emotion_Joy()
    misty.sound_Joy()

    # Step 2: Nod action - simulate nodding by moving the head up and down
    for _ in range(2):
        misty.move_head(pitch=10, duration=0.3, units="degrees")
        time.sleep(0.3)
        misty.move_head(pitch=-10, duration=0.3, units="degrees")
        time.sleep(0.3)

    # Step 3: Speak to confirm intention to move
    misty.speak("Okay, I’ll come a bit closer.")

    # Step 4: Move closer (drive function with appropriate parameters)
    normal_speed_value = 50  # Example normal speed value
    angular_velocity_value = 0  # No angular rotation
    misty.drive(normal_speed_value, angular_velocity_value)

    # Reset Misty to her original state
    misty.return_to_normal()

if __name__ == "__main__":
    misty_express_and_approach("192.168.1.237")
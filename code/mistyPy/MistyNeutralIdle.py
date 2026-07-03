# filename: MistyNeutralIdle.py

from CUBS_Misty import Robot
import time

def misty_neutral_idle(robot_ip):
    '''
    Make Misty maintain a neutral face and perform an idle gesture.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    '''
    
    # Initialize Misty robot
    misty = Robot(robot_ip)
    
    # Step 1: Maintain a neutral face expression
    misty.emotion_DefaultContent()

    # Step 2: Perform an idle gesture
    misty.move_head(pitch=0, yaw=0, roll=0, velocity=50, duration=2.0, units="degrees")
    misty.move_arms(leftArmPosition=45, rightArmPosition=45, leftArmVelocity=50, rightArmVelocity=50, duration=2.0, units="degrees")
    
    # Step 3: Speak the provided text
    misty.speak("Moving forward.")

    # Reset Misty to a neutral state after the actions
    misty.return_to_normal()
    
if __name__ == "__main__":
    misty_neutral_idle("192.168.1.237")
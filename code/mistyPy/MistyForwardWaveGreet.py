# filename: MistyForwardWaveGreet.py

from CUBS_Misty import Robot
import time

def misty_forward_wave_greet(robot_ip):
    '''
    Drive Misty forward, wave hello with her arm, and greet verbally.
    
    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    '''
    
    # Initialize Misty robot
    misty = Robot(robot_ip)

    # Step 1: Move Misty forward (approx. 50cm)
    # Note: Assuming speed and time achieve desired distance.
    misty.post_request("drive/time", json={"linearVelocity": 20, "timeMs": 3000})
    time.sleep(3.0) # Wait for movement to complete

    # Step 2: Perform a wave movement
    for _ in range(3):
        misty.move_arms(leftArmPosition=-29, rightArmPosition=30, duration=0.5)
        time.sleep(0.5)
        misty.move_arms(leftArmPosition=30, rightArmPosition=-29, duration=0.5)
        time.sleep(0.5)

    # Step 3: Verbal greeting
    misty.speak("你好，我是Misty，很高興見到你！")
    
    # Step 4: Return Misty back to her normal state
    misty.return_to_normal()

if __name__ == "__main__":
    misty_forward_wave_greet("192.168.1.237")
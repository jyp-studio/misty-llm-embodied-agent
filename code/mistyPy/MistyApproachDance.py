# filename: MistyApproachDance.py

from CUBS_Misty import Robot
import time

def calculate_drive_time(target_distance, speed):
    '''
    Calculate the time required to drive a target distance at a given speed using Misty.
    
    Parameters:
    - target_distance (float): The target distance to drive in centimeters.
    - speed (str): The speed setting, can be "slow", "normal", or "fast".
    
    Returns:
    - float: The calculated time in seconds.
    '''
    speed_settings = {"slow": 15, "normal": 30, "fast": 50}  # Example speed settings in cm/s
    if speed not in speed_settings:
        raise ValueError("Speed must be 'slow', 'normal', or 'fast'.")
        
    velocity = speed_settings[speed]
    return target_distance / velocity

def approach_and_dance(robot_ip, target_distance, speed, face_expression, gesture, speech_text):
    '''
    Make Misty approach by driving a specified distance, express a happy face,
    perform a dance gesture, and speak a message upon arrival.

    Parameters:
    - robot_ip (str): The IP address of the Misty robot.
    - target_distance (float): Distance to approach in centimeters.
    - speed (str): Speed of approach, options are "slow", "normal", or "fast".
    - face_expression (str): The facial expression Misty should display.
    - gesture (str): The arm gesture Misty should perform.
    - speech_text (str): The speech Misty should say afterwards.
    '''

    # Initialize Misty robot
    misty = Robot(robot_ip)

    # Calculate drive time
    drive_time = calculate_drive_time(target_distance, speed)
    velocity = 30 if speed == "normal" else (15 if speed == "slow" else 50)

    # Move closer by driving forward
    misty.post_request("drive", json={"linearVelocity": velocity, "angularVelocity": 0})
    time.sleep(drive_time)
    misty.post_request("drive", json={"linearVelocity": 0, "angularVelocity": 0})

    # Express happiness 
    if face_expression.lower() == "happy":
        misty.emotion_Joy()

    # Perform a dance gesture
    if gesture.lower() == "arms_up":
        misty.move_arms(leftArmPosition=-29, rightArmPosition=-29, duration=1.0)
        time.sleep(1)  # Allow time for the gesture

    # Speak the engaging message
    misty.speak(speech_text)

    # Reset Misty back to her neutral state
    misty.return_to_normal()

if __name__ == "__main__":
    approach_and_dance("192.168.1.237", 80, "normal", "happy", "arms_up", "Okay, I'm coming closer. Get ready for a crazy dance just for you!")
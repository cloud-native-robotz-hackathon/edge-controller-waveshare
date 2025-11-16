import requests
import time
import json
from flask import Flask, request, jsonify, Response
import atexit
import cv2
import base64
import os
from picamera2 import Picamera2

# --- Flask App Initialization ---
app = Flask(__name__)
print("Waveshare Rover Flask Edge Controller has started.")

# --- WiFi Configuration ---
# WAVE ROVER ESP32 creates a WiFi hotspot on startup
# Default IP is 192.168.4.1 when in hotspot mode
# Can be configured via environment variable ROBOT_IP
ROBOT_IP = os.environ.get('ROBOT_IP', '192.168.4.1')
ROBOT_HTTP_ENDPOINT = f'http://{ROBOT_IP}'
HTTP_TIMEOUT = 2.0  # Timeout in seconds for HTTP requests

# --- Robot Movement Configuration ---
ROBOT_SPEED_CM_PER_SECOND = 10.0
DEFAULT_DRIVE_SPEED = 0.3

# Initialize picam2 to None globally
picam2 = None

def init_camera():
    """Initializes and starts the Picamera2 instance."""
    global picam2
    try:
        picam2 = Picamera2()
        camera_config = picam2.create_still_configuration(main={"size": (640, 480)}, lores={"size": (320, 240)}, display="lores")
        picam2.configure(camera_config)
        picam2.start()
        print("Picamera2 started successfully.")
    except Exception as e:
        print(f"Failed to start Picamera2: {e}")
        picam2 = None # Ensure picam2 is None if initialization fails

# --- Helper Functions for WiFi HTTP Communication ---
def test_robot_connection():
    """Tests the connection to the WAVE ROVER via WiFi."""
    try:
        # Try to send a stop command to test connectivity
        response = requests.post(ROBOT_HTTP_ENDPOINT, 
                                json={"T": 1, "L": 0.0, "R": 0.0},
                                timeout=HTTP_TIMEOUT)
        if response.status_code == 200:
            print(f"Successfully connected to WAVE ROVER at {ROBOT_HTTP_ENDPOINT}")
            return True
        else:
            print(f"WAVE ROVER responded with status code {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to WAVE ROVER at {ROBOT_HTTP_ENDPOINT}: {e}")
        print("Make sure the robot is powered on and connected to its WiFi hotspot.")
        return False

def send_motor_command_http(left_speed, right_speed):
    """Sends a motor control command to the Waveshare Rover via WiFi HTTP."""
    command_payload = {
        "T": 1,  # CMD_SPEED_CTRL command type
        "L": float(left_speed),
        "R": float(right_speed)
    }

    try:
        response = requests.post(ROBOT_HTTP_ENDPOINT,
                                json=command_payload,
                                timeout=HTTP_TIMEOUT)
        print(f"Command sent via HTTP: {json.dumps(command_payload)}")
        
        if response.status_code == 200:
            return True, "OK"
        else:
            return False, f"HTTP error: {response.status_code} - {response.text}"
    except requests.exceptions.Timeout:
        print(f"Timeout sending command to {ROBOT_HTTP_ENDPOINT}")
        return False, f"Request timeout after {HTTP_TIMEOUT} seconds"
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error to {ROBOT_HTTP_ENDPOINT}: {e}")
        return False, f"Connection error: {e}"
    except Exception as e:
        print(f"An unexpected error occurred during HTTP command send: {e}")
        return False, f"Unexpected error: {e}"

# --- Lifecycle Management ---
def cleanup():
    """Stops robot and closes camera resources when the application exits."""
    # Ensure robot stops before exiting
    send_motor_command_http(0.0, 0.0)
    print("Robot stopped.")

    global picam2
    if picam2 and picam2.started:
        picam2.stop()
        print("Picamera2 stopped.")

atexit.register(cleanup)

# --- Flask Endpoints ---

@app.route('/', methods=['GET'])
def index():
    return "Waveshare Rover Flask Server ready!"

# ... (rest of your /forward, /backward, /left, /right, /stop routes remain the same) ...
@app.route('/forward/<int:distance_cm>', methods=['POST'])
def forward(distance_cm):
    """Drives the robot forward for a specified distance in centimeters."""
    print(f"Received request: /forward/{distance_cm} cm")
    if distance_cm <= 0:
        return jsonify({"status": "Error", "message": "Distance must be positive"}), 400

    duration = distance_cm / ROBOT_SPEED_CM_PER_SECOND
    print(f"Calculated duration: {duration:.2f} seconds.")

    # Start moving forward
    success, message = send_motor_command_http(DEFAULT_DRIVE_SPEED, DEFAULT_DRIVE_SPEED)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Moved forward {distance_cm} cm"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/backward/<int:distance_cm>', methods=['POST'])
def backward(distance_cm):
    """Drives the robot backward for a specified distance in centimeters."""
    print(f"Received request: /backward/{distance_cm} cm")
    if distance_cm <= 0:
        return jsonify({"status": "Error", "message": "Distance must be positive"}), 400

    duration = distance_cm / ROBOT_SPEED_CM_PER_SECOND
    print(f"Calculated duration: {duration:.2f} seconds.")

    # Start moving backward (use negative speed)
    success, message = send_motor_command_http(-DEFAULT_DRIVE_SPEED, -DEFAULT_DRIVE_SPEED)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Moved backward {distance_cm} cm"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/left/<int:degree>', methods=['POST'])
def left(degree):
    """Turns the robot left in place at a specified speed."""
    print(f"Received request: /left/{degree}")
    # Left turn in place: left wheel backward, right wheel forward
    # Convert integer speed to float for motor command
    
    duration = degree * (0.65/90)
    print(f"Calculated duration: {duration:.2f} seconds.")

    # Start turning
    success, message = send_motor_command_http(-0.3, 0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Turned {degree} degrees"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/right/<int:degree>', methods=['POST'])
def right(degree):
    """Turns the robot right in place at a specified speed."""
    print(f"Received request: /right/{degree}")
    # Left turn in place: left wheel backward, right wheel forward
    # Convert integer speed to float for motor command
    
    duration = degree * (0.65/90)
    print(f"Calculated duration: {duration:.2f} seconds.")

    # Start turning
    success, message = send_motor_command_http(0.3, -0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Turned {degree} degrees"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/stop', methods=['POST'])
def stop():
    """Stops the robot."""
    print("Received request: /stop")
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": "Robot stopped"}), 200
    else:
        return jsonify({"status": "Error", "message": message}), 500

@app.route('/camera2', methods=['GET'])
def camera2():
    """
    Reads an image file, encodes it in Base64, and returns the Base64 string directly.
    """
    IMAGE_DIRECTORY = "/root/my_live_feed"
    file_path = os.path.join(IMAGE_DIRECTORY, "image-old.jpg")

    if not os.path.abspath(file_path).startswith(os.path.abspath(IMAGE_DIRECTORY)):
        return "Forbidden", 403

    if not os.path.exists(file_path):
        return "Error: File not found.", 404
    
    try:
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        return Response(encoded_string, mimetype='text/plain')
    except Exception as e:
        return f"Error: Could not process file: {e}", 500

@app.route('/camera', methods=['GET'])
def camera():
    """Captures an image from Picamera2 and returns it as a Base64 encoded JSON."""
    global picam2
    if not picam2 or not picam2.started:
        return jsonify({"error": "Camera not started or failed to initialize."}), 500

    try:
        # Capture the image as a NumPy array in BGR format
        image_array_bgr = picam2.capture_array("main")

        # --- FIX: Convert the image from BGR to RGB ---
        image_array_rgb = cv2.cvtColor(image_array_bgr, cv2.COLOR_BGR2RGB)

        # Encode the corrected RGB image to an in-memory JPEG byte stream
        success, buffer = cv2.imencode('.jpg', image_array_rgb)

        if not success:
            return jsonify({"error": "Failed to encode image to JPEG."}), 500

        # Convert the byte buffer to a Base64 string
        base64_encoded_image = base64.b64encode(buffer.tobytes()).decode('utf-8')

        return base64_encoded_image

    except Exception as e:
        print(f"Error during image capture or encoding: {e}")
        return jsonify({"error": f"An error occurred: {e}"}), 500

# --- Main execution block ---
if __name__ == '__main__':
    # Initialize hardware connections here
    print(f"Connecting to WAVE ROVER at {ROBOT_HTTP_ENDPOINT}")
    test_robot_connection()
    init_camera()

    # The 'use_reloader=False' is crucial for preventing the script from running twice.
    # When developing, you might manually restart the server after code changes.
    # For production, you'd typically use a more robust WSGI server like Gunicorn or uWSGI.
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

import requests
import time
import json
from flask import Flask, request, jsonify, Response
import atexit
import cv2
import base64
import os

# --- Flask App Initialization ---
app = Flask(__name__)
print("Waveshare Rover Flask Edge Controller has started.")

# --- WiFi Configuration ---
# WAVE ROVER ESP32 creates a WiFi hotspot on startup
# Default IP is 192.168.4.1 when in hotspot mode
# Can be configured via environment variable ROBOT_IP
# The robot expects HTTP GET requests to /js endpoint with JSON as query parameter
ROBOT_IP = os.environ.get('ROBOT_IP', '192.168.4.1')
ROBOT_HTTP_ENDPOINT = f'http://{ROBOT_IP}/js'
HTTP_TIMEOUT = 2.0  # Timeout in seconds for HTTP requests

# --- Robot Movement Configuration ---
ROBOT_SPEED_CM_PER_SECOND = 10.0
DEFAULT_DRIVE_SPEED = 0.3

# --- Turn Configuration ---
# Base turn rate: seconds per degree (calibrated for this robot)
# Account for acceleration/deceleration time and HTTP latency
# Observations: 3×45° ≈ 90°, so short turns need more time
TURN_RATE_SECONDS_PER_DEGREE = 0.0072  # ~0.65 seconds per 90 degrees
TURN_ACCELERATION_TIME = 0.08  # Time to reach full speed (seconds)
TURN_DECELERATION_TIME = 0.08  # Time to stop (seconds)
TURN_HTTP_LATENCY = 0.05  # Approximate HTTP request latency (seconds)

# --- Camera Configuration ---
# Camera device path (default /dev/video0 for first USB camera or CSI camera via v4l2)
# Can be configured via environment variable CAMERA_DEVICE
CAMERA_DEVICE = os.environ.get('CAMERA_DEVICE', '/dev/video0')
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# Initialize camera to None globally
camera = None

def init_camera():
    """Initializes the camera using OpenCV VideoCapture (v4l2 compatible for RHEL 9)."""
    global camera
    try:
        # Try to open camera device
        camera = cv2.VideoCapture(CAMERA_DEVICE)
        
        if not camera.isOpened():
            print(f"Failed to open camera device {CAMERA_DEVICE}")
            camera = None
            return
        
        # Set camera resolution
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        
        # Read a test frame to ensure camera is working
        ret, frame = camera.read()
        if not ret:
            print(f"Failed to read test frame from camera {CAMERA_DEVICE}")
            camera.release()
            camera = None
            return
        
        print(f"Camera {CAMERA_DEVICE} started successfully (resolution: {CAMERA_WIDTH}x{CAMERA_HEIGHT})")
    except Exception as e:
        print(f"Failed to start camera {CAMERA_DEVICE}: {e}")
        if camera is not None:
            camera.release()
        camera = None

# --- Helper Functions for WiFi HTTP Communication ---
def test_robot_connection():
    """Tests the connection to the WAVE ROVER via WiFi."""
    try:
        # Try to send a stop command to test connectivity
        # WAVE ROVER expects GET request to /js?json=<command>
        command_json = json.dumps({"T": 1, "L": 0.0, "R": 0.0}, separators=(',', ':'))
        print(f"Testing connection to {ROBOT_HTTP_ENDPOINT}...")
        response = requests.get(ROBOT_HTTP_ENDPOINT, params={'json': command_json}, timeout=HTTP_TIMEOUT)
        print(f"Connection test URL: {response.url}")
        print(f"Connection test response: status={response.status_code}, body={response.text[:200]}")
        if response.status_code == 200:
            print(f"Successfully connected to WAVE ROVER at {ROBOT_IP}")
            return True
        else:
            print(f"WAVE ROVER responded with status code {response.status_code}")
            print(f"Response body: {response.text[:200]}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to WAVE ROVER at {ROBOT_IP}: {e}")
        print("Make sure the robot is powered on and connected to its WiFi hotspot.")
        return False

def send_motor_command_http(left_speed, right_speed):
    """Sends a motor control command to the Waveshare Rover via WiFi HTTP.
    
    The WAVE ROVER expects HTTP GET requests to /js endpoint with JSON command
    as a query parameter: /js?json={"T":1,"L":0.3,"R":0.3}
    """
    command_payload = {
        "T": 1,  # CMD_SPEED_CTRL command type
        "L": float(left_speed),
        "R": float(right_speed)
    }

    try:
        # WAVE ROVER expects GET request to /js?json=<command>
        # Use params to properly URL-encode the JSON string
        command_json = json.dumps(command_payload, separators=(',', ':'))  # Compact JSON
        response = requests.get(ROBOT_HTTP_ENDPOINT, params={'json': command_json}, timeout=HTTP_TIMEOUT)
        
        print(f"Command sent via HTTP: {command_json}")
        print(f"Full URL: {response.url}")
        print(f"Response status: {response.status_code}, body: {response.text[:200]}")
        
        if response.status_code == 200:
            return True, "OK"
        else:
            return False, f"HTTP error: {response.status_code} - {response.text[:200]}"
    except requests.exceptions.Timeout:
        print(f"Timeout sending command to {ROBOT_HTTP_ENDPOINT}")
        return False, f"Request timeout after {HTTP_TIMEOUT} seconds"
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error to {ROBOT_HTTP_ENDPOINT}: {e}")
        return False, f"Connection error: {e}"
    except Exception as e:
        print(f"An unexpected error occurred during HTTP command send: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Unexpected error: {e}"

# --- Lifecycle Management ---
def cleanup():
    """Stops robot and closes camera resources when the application exits."""
    # Ensure robot stops before exiting
    send_motor_command_http(0.0, 0.0)
    print("Robot stopped.")

    global camera
    if camera is not None and camera.isOpened():
        camera.release()
        print("Camera released.")

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
    print(f"Received request: /left/{degree} degrees")
    if degree <= 0:
        return jsonify({"status": "Error", "message": "Degree must be positive"}), 400
    
    # Left turn in place: left wheel backward, right wheel forward
    # Duration calculation accounts for acceleration/deceleration and HTTP latency
    # Observations: 3×45° ≈ 90°, so 45° is only turning ~30° (needs 1.5× time)
    base_duration = degree * TURN_RATE_SECONDS_PER_DEGREE
    overhead = TURN_ACCELERATION_TIME + TURN_DECELERATION_TIME + TURN_HTTP_LATENCY
    
    # For short turns, overhead dominates - need much more aggressive scaling
    # If 45° only turns 30°, we need 45/30 = 1.5× the time
    if degree <= 30:
        # Very short turns: need 2× time
        scale_factor = 2.0
        duration = base_duration * scale_factor + overhead
    elif degree <= 45:
        # 45° needs 1.5× time to actually turn 45°
        scale_factor = 1.5
        duration = base_duration * scale_factor + overhead
    elif degree < 90:
        # Medium turns: moderate scaling
        scale_factor = 1.0 + (90.0 - degree) / 90.0 * 0.3
        duration = base_duration * scale_factor + overhead
    else:
        # Longer turns: fixed overhead
        duration = base_duration + overhead
    
    print(f"Calculated duration: {duration:.3f} seconds for {degree} degrees (base: {base_duration:.3f}s).")

    # Start turning
    start_time = time.time()
    success, message = send_motor_command_http(-0.3, 0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500
    
    # Small delay to ensure command is processed (HTTP latency)
    time.sleep(0.02)
    
    # Wait for the calculated duration (minus the initial delay)
    time.sleep(max(0, duration - 0.02))
    elapsed = time.time() - start_time
    print(f"Actual turn time: {elapsed:.3f} seconds (target: {duration:.3f}s)")

    # Stop the robot
    success, message = send_motor_command_http(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Turned {degree} degrees"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/right/<int:degree>', methods=['POST'])
def right(degree):
    """Turns the robot right in place at a specified speed."""
    print(f"Received request: /right/{degree} degrees")
    if degree <= 0:
        return jsonify({"status": "Error", "message": "Degree must be positive"}), 400
    
    # Right turn in place: left wheel forward, right wheel backward
    # Duration calculation accounts for acceleration/deceleration and HTTP latency
    # Observations: 3×45° ≈ 90°, so 45° is only turning ~30° (needs 1.5× time)
    base_duration = degree * TURN_RATE_SECONDS_PER_DEGREE
    overhead = TURN_ACCELERATION_TIME + TURN_DECELERATION_TIME + TURN_HTTP_LATENCY
    
    # For short turns, overhead dominates - need much more aggressive scaling
    # If 45° only turns 30°, we need 45/30 = 1.5× the time
    if degree <= 30:
        # Very short turns: need 2× time
        scale_factor = 2.0
        duration = base_duration * scale_factor + overhead
    elif degree <= 45:
        # 45° needs 1.5× time to actually turn 45°
        scale_factor = 1.5
        duration = base_duration * scale_factor + overhead
    elif degree < 90:
        # Medium turns: moderate scaling
        scale_factor = 1.0 + (90.0 - degree) / 90.0 * 0.3
        duration = base_duration * scale_factor + overhead
    else:
        # Longer turns: fixed overhead
        duration = base_duration + overhead
    
    print(f"Calculated duration: {duration:.3f} seconds for {degree} degrees (base: {base_duration:.3f}s).")

    # Start turning
    start_time = time.time()
    success, message = send_motor_command_http(0.3, -0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500
    
    # Small delay to ensure command is processed (HTTP latency)
    time.sleep(0.02)
    
    # Wait for the calculated duration (minus the initial delay)
    time.sleep(max(0, duration - 0.02))
    elapsed = time.time() - start_time
    print(f"Actual turn time: {elapsed:.3f} seconds (target: {duration:.3f}s)")

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
def camera_endpoint():
    """Captures an image from the camera using OpenCV VideoCapture and returns it as Base64 encoded."""
    global camera
    if camera is None or not camera.isOpened():
        return jsonify({"error": "Camera not started or failed to initialize."}), 500

    try:
        # Read frame from camera (OpenCV returns BGR format)
        ret, frame = camera.read()
        
        if not ret or frame is None:
            return jsonify({"error": "Failed to capture frame from camera."}), 500

        # Convert BGR to RGB for proper color display
        image_array_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Encode the RGB image to an in-memory JPEG byte stream
        success, buffer = cv2.imencode('.jpg', image_array_rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])

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

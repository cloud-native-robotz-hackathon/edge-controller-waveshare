import serial
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

# --- Serial Port Configuration ---
SERIAL_PORT = '/dev/ttyAMA0'
BAUD_RATE = 115200

# --- Robot Movement Configuration ---
ROBOT_SPEED_CM_PER_SECOND = 10.0
DEFAULT_DRIVE_SPEED = 0.3

# Initialize picam2 to None globally
picam2 = None

# Initialize serial connection globally
ser = None

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

# --- Helper Functions for Serial Communication ---
def init_serial_connection():
    """Initializes the global serial connection."""
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        if ser.is_open:
            print(f"Serial port {SERIAL_PORT} opened successfully.")
        else:
            print(f"Failed to open serial port {SERIAL_PORT}.")
            ser = None
    except serial.SerialException as e:
        print(f"Failed to open serial port {SERIAL_PORT}: {e}")
        ser = None
    except Exception as e:
        print(f"An unexpected error occurred during serial init: {e}")
        ser = None

def send_motor_command_uart(left_speed, right_speed):
    """Sends a motor control command to the Waveshare Rover via UART."""
    if ser is None or not ser.is_open:
        print("Error: Serial port not open. Cannot send command.")
        return False, "Serial port not open."

    command_payload = {
        "T": "1",
        "L": float(left_speed),
        "R": float(right_speed)
    }

    json_string = json.dumps(command_payload)
    command_bytes = (json_string + '\n').encode('utf-8')

    try:
        ser.write(command_bytes)
        print(f"Command sent via UART: {json_string}")
        return True, "OK"
    except serial.SerialException as e:
        print(f"Error sending command over UART: {e}")
        return False, f"Serial communication error: {e}"
    except Exception as e:
        print(f"An unexpected error occurred during command send: {e}")
        return False, f"Unexpected error: {e}"

# --- Lifecycle Management ---
def cleanup():
    """Closes serial and camera resources when the application exits."""
    global ser
    if ser and ser.is_open:
        send_motor_command_uart(0.0, 0.0) # Ensure robot stops
        ser.close()
        print("Serial port closed.")

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
    success, message = send_motor_command_uart(DEFAULT_DRIVE_SPEED, DEFAULT_DRIVE_SPEED)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_uart(0.0, 0.0)
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
    success, message = send_motor_command_uart(-DEFAULT_DRIVE_SPEED, -DEFAULT_DRIVE_SPEED)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_uart(0.0, 0.0)
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
    success, message = send_motor_command_uart(-0.3, 0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_uart(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Turned {degree} degrees"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/right/<int:degree>', methods=['POST'])
def right(degree):
    """Turns the robot right in place at a specified speed."""
    print(f"Received request: /left/{degree}")
    # Left turn in place: left wheel backward, right wheel forward
    # Convert integer speed to float for motor command
    
    duration = degree * (0.65/90)
    print(f"Calculated duration: {duration:.2f} seconds.")

    # Start turning
    success, message = send_motor_command_uart(0.3, -0.3)
    if not success:
        return jsonify({"status": "Error", "message": f"Failed to start: {message}"}), 500

    time.sleep(duration) # Wait for the calculated duration

    # Stop the robot
    success, message = send_motor_command_uart(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": f"Turned {degree} degrees"}), 200
    else:
        return jsonify({"status": "Error", "message": f"Failed to stop: {message}"}), 500

@app.route('/stop', methods=['POST'])
def stop():
    """Stops the robot."""
    print("Received request: /stop")
    success, message = send_motor_command_uart(0.0, 0.0)
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
    init_serial_connection()
    init_camera()

    # The 'use_reloader=False' is crucial for preventing the script from running twice.
    # When developing, you might manually restart the server after code changes.
    # For production, you'd typically use a more robust WSGI server like Gunicorn or uWSGI.
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

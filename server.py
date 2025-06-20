import serial
import time
import json
from flask import Flask, request, jsonify
import atexit
import cv2 # Import OpenCV for camera access
import base64 # Import base64 for encoding images

# --- Flask App Initialization ---
app = Flask(__name__)
print("Waveshare Rover Flask Edge Controller has started.")

# --- Serial Port Configuration (from drive_forward.py) ---
# Serial port for communication with the ESP32 sub-controller.
# Common for Raspberry Pi: '/dev/ttyS0'
# On some older setups, it might be '/dev/ttyAMA0'
SERIAL_PORT = '/dev/ttyAMA0'
BAUD_RATE = 115200  # Common baud rate for ESP32 communication

# --- Robot Movement Configuration ---
# This constant defines how many centimeters the robot travels per second
# at a specific motor speed (e.3). You will need to calibrate this
# value for your specific robot model and surface.
ROBOT_SPEED_CM_PER_SECOND = 10.0  # Example: 10 cm/second at the default internal speed (0.3)
DEFAULT_DRIVE_SPEED = 0.3 # The motor speed to use for timed distance movements

# Initialize serial connection globally
ser = None

# --- Helper Functions for Serial Communication ---
def init_serial_connection():
    """Initializes the global serial connection."""
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)  # Allow time for the serial connection to establish
        if ser.is_open:
            print(f"Serial port {SERIAL_PORT} opened successfully.")
        else:
            print(f"Failed to open serial port {SERIAL_PORT}.")
            ser = None # Ensure ser is None if opening failed
    except serial.SerialException as e:
        print(f"Failed to open serial port {SERIAL_PORT}: {e}")
        print("Possible causes: Port is in use, incorrect port name, or insufficient permissions.")
        print("Ensure 'pyserial' is installed and UART is enabled/configured on your Raspberry Pi.")
        print("You might need to add your user to the 'dialout' group: `sudo usermod -a -G dialout $USER` and reboot.")
        ser = None # Ensure ser is None on error
    except Exception as e:
        print(f"An unexpected error occurred during serial init: {e}")
        ser = None


def send_motor_command_uart(left_speed, right_speed):
    """
    Sends a motor control command to the Waveshare Rover via UART.
    Speeds range from -0.5 (full backward) to +0.5 (full forward).
    Positive values move forward, negative values move backward.
    """
    if ser is None or not ser.is_open:
        print("Error: Serial port not open. Cannot send command.")
        return False, "Serial port not open."

    # The JSON structure for speed control as per Waveshare Wiki for Wave Rover
    # This matches the structure found in the user-provided drive_forward.py
    command_payload = {
        "T": "1", # Assuming 'T' is a command type field, '1' for motor control
        "L": float(left_speed),  # Left wheel speed
        "R": float(right_speed)  # Right wheel speed
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
# The @app.before_first_request decorator caused an AttributeError.
# Moving serial initialization to the main execution block for compatibility.
def cleanup_serial():
    """Closes the serial port when the application exits."""
    global ser
    if ser and ser.is_open:
        ser.close()
        print("Serial port closed.")

# Register the cleanup function to be called on app exit
atexit.register(cleanup_serial)

# --- Flask Endpoints (similar to server.py) ---

@app.route('/', methods=['GET'])
def index():
    """Simple ping to check if the server is running."""
    return "Waveshare Rover Flask Server ready!"

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

@app.route('/left/<int:speed>', methods=['POST'])
def left(speed):
    """Turns the robot left in place at a specified speed."""
    print(f"Received request: /left/{speed}")
    # Left turn in place: left wheel backward, right wheel forward
    # Convert integer speed to float for motor command
    float_speed = float(speed)
    success, message = send_motor_command_uart(-float_speed, float_speed)
    if success:
        return jsonify({"status": "OK", "message": "Turning left in place"}), 200
    else:
        return jsonify({"status": "Error", "message": message}), 500

@app.route('/right/<int:speed>', methods=['POST'])
def right(speed):
    """Turns the robot right in place at a specified speed."""
    print(f"Received request: /right/{speed}")
    # Right turn in place: left wheel forward, right wheel backward
    # Convert integer speed to float for motor command
    float_speed = float(speed)
    success, message = send_motor_command_uart(float_speed, -float_speed)
    if success:
        return jsonify({"status": "OK", "message": "Turning right in place"}), 200
    else:
        return jsonify({"status": "Error", "message": message}), 500

@app.route('/stop', methods=['POST'])
def stop():
    """Stops the robot."""
    print("Received request: /stop")
    success, message = send_motor_command_uart(0.0, 0.0)
    if success:
        return jsonify({"status": "OK", "message": "Robot stopped"}), 200
    else:
        return jsonify({"status": "Error", "message": message}), 500

@app.route('/camera', methods=['GET'])
def camera():
    """
    Captures an image from the connected webcam and returns it as a Base64 string directly.
    Assumes camera is at /dev/video0.
    """
    print("Received request: /camera")
    cap = None
    try:
        # Initialize video capture object
        # '/dev/video0' is the default path for the first webcam on Linux (Raspberry Pi OS)
        cap = cv2.VideoCapture('/dev/video0')

        # Set resolution (optional, adjust as needed for performance/quality)
        # These are common resolutions, but check your camera's capabilities
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # Check if camera opened successfully
        if not cap.isOpened():
            print("Error: Could not open camera.")
            return jsonify({"status": "Error", "message": "Could not open camera."}), 500

        # Read a frame from the camera
        ret, frame = cap.read()

        if not ret:
            print("Error: Could not read frame from camera.")
            return jsonify({"status": "Error", "message": "Could not read frame."}), 500

        # Encode the frame as a JPEG image in memory
        # 'imencode' returns a tuple: (boolean success, numpy array of bytes)
        ret, buffer = cv2.imencode('.jpg', frame)

        if not ret:
            print("Error: Could not encode image to JPEG.")
            return jsonify({"status": "Error", "message": "Could not encode image."}), 500

        # Convert the byte array to a Base64 string
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')

        # Return the Base64 string directly
        return jpg_as_text, 200, {'Content-Type': 'text/plain'}

    except Exception as e:
        print(f"An unexpected error occurred during camera capture: {e}")
        return jsonify({"status": "Error", "message": f"Camera error: {e}"}), 500
    finally:
        # Release the camera object to free resources
        if cap is not None and cap.isOpened():
            cap.release()
            print("Camera released.")


# --- Main execution block ---
if __name__ == '__main__':
    # Initialize serial connection here, before running the Flask app
    init_serial_connection()
    # Run the Flask app
    # host='0.0.0.0' makes it accessible from other devices on the network
    # debug=True allows for auto-reloading and better error messages during development
    app.run(host='0.0.0.0', port=5000, debug=True)


import requests
import time
import json
from flask import Flask, request, jsonify, Response
import atexit
import cv2
import base64
import os
import subprocess
import tempfile

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
# Account for acceleration/deceleration time, HTTP latency, and wheel slip
# Robot has 4 wheels (2 per side) - wheel slip during in-place turns causes inconsistency
# Observations: 3×45° ≈ 90°, so short turns need more time due to slip
TURN_RATE_SECONDS_PER_DEGREE = 0.0072  # ~0.65 seconds per 90 degrees
TURN_ACCELERATION_TIME = 0.08  # Time to reach full speed (seconds)
TURN_DECELERATION_TIME = 0.08  # Time to stop (seconds)
TURN_HTTP_LATENCY = 0.05  # Approximate HTTP request latency (seconds)
TURN_SPEED = 0.4  # Turn speed (increased from 0.3 to reduce slip - higher speed = less slip)

# --- Camera Configuration ---
# Camera device path (default /dev/video0 for first USB camera or CSI camera via v4l2)
# Can be configured via environment variable CAMERA_DEVICE
# For CSI cameras on AlmaLinux/RHEL 9, may need to use libcamera-still as fallback
CAMERA_DEVICE = os.environ.get('CAMERA_DEVICE', '/dev/video0')
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
USE_LIBCAMERA = False  # Set to True if OpenCV can't access CSI camera directly

# Initialize camera to None globally
camera = None
camera_tool_path = None  # Store full path to camera tool if using external tool

def init_camera():
    """Initializes the camera using OpenCV VideoCapture (v4l2 compatible for AlmaLinux/RHEL 9)."""
    global camera, CAMERA_DEVICE, USE_LIBCAMERA, camera_tool_path
    try:
        print(f"Attempting to initialize camera at {CAMERA_DEVICE}...")
        
        # Check if device exists
        if not os.path.exists(CAMERA_DEVICE):
            print(f"WARNING: Camera device {CAMERA_DEVICE} does not exist!")
            video_devices = [f for f in os.listdir('/dev') if f.startswith('video')]
            print(f"Available video devices: {video_devices}")
            print("Will continue to scan all available video devices...")
            # Don't return - continue to Method 4 which will scan all devices
            camera = None
        
        # Check permissions (only if device exists)
        if os.path.exists(CAMERA_DEVICE):
            import stat
            device_stat = os.stat(CAMERA_DEVICE)
            device_mode = stat.filemode(device_stat.st_mode)
            print(f"Camera device permissions: {device_mode}")
        
        # Try different methods to open camera
        # On AlmaLinux/RHEL 9, sometimes need to use device index or different backends
        camera = None
        
        # Method 1: Try with device path and V4L2 backend (only if device exists)
        if os.path.exists(CAMERA_DEVICE):
            print("Trying method 1: Device path with V4L2 backend...")
            try:
                camera = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
                if camera.isOpened():
                    print("✓ Successfully opened with V4L2 backend")
                else:
                    print("  Failed with V4L2 backend")
                    if camera:
                        camera.release()
                    camera = None
            except Exception as e:
                print(f"  Exception: {e}")
                if camera:
                    try:
                        camera.release()
                    except:
                        pass
                camera = None
        else:
            print("Skipping method 1: Device does not exist")
        
        # Method 2: Try with device index (extract number from /dev/video0 -> 0) - only if device exists
        if (camera is None or not camera.isOpened()) and os.path.exists(CAMERA_DEVICE):
            print("Trying method 2: Device index...")
            try:
                device_index = int(CAMERA_DEVICE.replace('/dev/video', ''))
                print(f"  Using device index: {device_index}")
                camera = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
                if camera.isOpened():
                    print("✓ Successfully opened with device index")
                else:
                    print("  Failed with device index")
                    if camera:
                        camera.release()
                    camera = None
            except (ValueError, Exception) as e:
                print(f"  Exception: {e}")
                if camera:
                    try:
                        camera.release()
                    except:
                        pass
                camera = None
        
        # Method 3: Try with ANY backend (only if device exists)
        if (camera is None or not camera.isOpened()) and os.path.exists(CAMERA_DEVICE):
            print("Trying method 3: ANY backend...")
            try:
                camera = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_ANY)
                if camera.isOpened():
                    print("✓ Successfully opened with ANY backend")
                else:
                    print("  Failed with ANY backend")
                    if camera:
                        camera.release()
                    camera = None
            except Exception as e:
                print(f"  Exception: {e}")
                if camera:
                    try:
                        camera.release()
                    except:
                        pass
                camera = None
        
        # Method 4: Try opening all video devices to find working one
        if camera is None or not camera.isOpened():
            print("Trying method 4: Scanning all video devices...")
            video_devices = sorted([f for f in os.listdir('/dev') if f.startswith('video')])
            print(f"  Found {len(video_devices)} video devices to test")
            
            # First, try to identify capture devices using sysfs and v4l2-ctl
            capture_devices = []
            # Check sysfs for device names
            print("  Checking device info from sysfs...")
            for video_dev in video_devices:
                dev_path = f'/dev/{video_dev}'
                dev_num = video_dev.replace('video', '')
                sysfs_name = f'/sys/class/video4linux/video{dev_num}/name'
                if os.path.exists(sysfs_name):
                    try:
                        with open(sysfs_name, 'r') as f:
                            device_name = f.read().strip()
                            print(f"    {dev_path}: {device_name}")
                            # Look for camera-related names
                            # PiSP Backend input devices are the camera capture devices
                            if any(keyword in device_name.lower() for keyword in ['camera', 'isp', 'pisp', 'capture', 'imx', 'pispbe-input']):
                                capture_devices.append(dev_path)
                                print(f"      -> Potential camera device")
                                # Prioritize pispbe-input devices
                                if 'pispbe-input' in device_name.lower():
                                    # Move to front of list
                                    if dev_path in capture_devices:
                                        capture_devices.remove(dev_path)
                                    capture_devices.insert(0, dev_path)
                                    print(f"        -> PiSP input device (camera) - highest priority")
                    except:
                        pass
            
            # Also try v4l2-ctl if available
            try:
                result = subprocess.run(['which', 'v4l2-ctl'], capture_output=True, text=True, timeout=1)
                if result.returncode == 0:
                    print("  Checking device capabilities with v4l2-ctl...")
                    for video_dev in video_devices:
                        dev_path = f'/dev/{video_dev}'
                        if dev_path not in capture_devices:  # Don't check twice
                            try:
                                cap_result = subprocess.run(['v4l2-ctl', '--device', dev_path, '--all'],
                                                           capture_output=True, text=True, timeout=1)
                                if 'Video Capture' in cap_result.stdout:
                                    if dev_path not in capture_devices:
                                        capture_devices.append(dev_path)
                                        print(f"    {dev_path}: Video Capture device (from v4l2-ctl)")
                            except:
                                pass
            except:
                pass
            
            if capture_devices:
                print(f"  Found {len(capture_devices)} potential capture devices, testing those first...")
                # Test capture devices first
                video_devices = [d.replace('/dev/', '') for d in capture_devices] + \
                               [d for d in video_devices if f'/dev/{d}' not in capture_devices]
            else:
                print("  No obvious capture devices found, will test all devices...")
            for video_dev in video_devices:
                dev_path = f'/dev/{video_dev}'
                dev_num = video_dev.replace('video', '')
                print(f"  Trying {dev_path}...", end=' ', flush=True)
                test_cam = None
                try:
                    # Try opening by path first
                    test_cam = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
                    if not test_cam.isOpened():
                        # If path fails, try device index
                        try:
                            dev_index = int(dev_num)
                            test_cam = cv2.VideoCapture(dev_index, cv2.CAP_V4L2)
                        except (ValueError, Exception):
                            pass
                    
                    if test_cam.isOpened():
                        # Set buffer size to 1 to avoid stale frames
                        test_cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        # Set timeout for frame read
                        test_cam.set(cv2.CAP_PROP_FPS, 30)
                        
                        # For PiSP cameras, try setting format first
                        # Try MJPEG format which is commonly supported
                        try:
                            test_cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
                        except:
                            pass
                        
                        # Try grab() with timeout - use threading to avoid blocking
                        import threading
                        grabbed = False
                        grab_exception = None
                        
                        def try_grab():
                            nonlocal grabbed, grab_exception
                            try:
                                # Try multiple times with short delays for PiSP cameras
                                for _ in range(3):
                                    grabbed = test_cam.grab()
                                    if grabbed:
                                        break
                                    time.sleep(0.1)
                            except Exception as e:
                                grab_exception = e
                        
                        grab_thread = threading.Thread(target=try_grab)
                        grab_thread.daemon = True
                        grab_thread.start()
                        grab_thread.join(timeout=1.0)  # 1 second timeout (reduced)
                        
                        if grab_thread.is_alive():
                            print("timeout")
                            test_cam.release()
                            continue
                        
                        if grab_exception:
                            print(f"exception: {grab_exception}")
                            test_cam.release()
                            continue
                        
                        if grabbed:
                            # If grab succeeded, try retrieve
                            ret, test_frame = test_cam.retrieve()
                            if ret and test_frame is not None and test_frame.size > 0:
                                print(f"✓ WORKING CAMERA!")
                                camera = test_cam
                                # Update CAMERA_DEVICE to the working one
                                CAMERA_DEVICE = dev_path
                                break
                            else:
                                print("grabbed but no frame")
                                test_cam.release()
                        else:
                            print("cannot grab")
                            test_cam.release()
                    else:
                        print("cannot open")
                        if test_cam:
                            test_cam.release()
                except Exception as e:
                    print(f"exception: {e}")
                    if test_cam:
                        try:
                            test_cam.release()
                        except:
                            pass
        
        # Method 5: Try Python libcamera bindings (if available)
        if camera is None or (hasattr(camera, 'isOpened') and not camera.isOpened()):
            print("Trying method 5: Checking for Python libcamera bindings...")
            try:
                import libcamera
                print("  Python libcamera module found - attempting to use it")
                # Mark that we'll use Python libcamera
                camera = "python_libcamera"
                USE_LIBCAMERA = "python_libcamera"
                print("✓ Will use Python libcamera bindings for camera capture")
            except ImportError:
                print("  Python libcamera bindings not available")
        
        # Method 6: Try alternative camera tools for CSI cameras on AlmaLinux/RHEL 9
        if camera is None or (hasattr(camera, 'isOpened') and not camera.isOpened()):
            print("Trying method 6: Checking for CSI camera tools...")
            # Check both PATH and common Raspberry Pi locations
            # Note: libcamera-still is not available in AlmaLinux repos, but libcamera-tools might have alternatives
            camera_tools = [
                # libcamera-tools package (installed on system)
                ('cam', 'cam', '/usr/bin/cam'),  # General camera tool from libcamera-tools
                ('cam', 'cam', None),  # Check PATH as well
                # Standard libcamera tools (may not be available on AlmaLinux 9)
                ('libcamera-still', 'libcamera', None),
                ('libcamera-still', 'libcamera', '/usr/bin/libcamera-still'),
                # Check libcamera-tools package (installed on system)
                ('libcamera-hello', 'libcamera_hello', None),  # Test tool, might work for capture
                ('libcamera-vid', 'libcamera_vid', None),  # Video tool, might work for single frame
                ('libcamera-raw', 'libcamera_raw', None),  # Raw capture tool
                # Alternative tools
                ('rpicam-still', 'rpicam', None),
                ('rpicam-still', 'rpicam', '/usr/bin/rpicam-still'),
                ('raspistill', 'raspistill', None),
                ('raspistill', 'raspistill', '/opt/vc/bin/raspistill'),  # Common RPi location
                ('raspistill', 'raspistill', '/usr/bin/raspistill'),
            ]
            
            for tool_name, tool_type, tool_path in camera_tools:
                try:
                    # Check specific path first, then which
                    if tool_path and os.path.exists(tool_path) and os.access(tool_path, os.X_OK):
                        print(f"  {tool_name} found at {tool_path} - will use for CSI camera capture")
                        USE_LIBCAMERA = tool_type
                        camera = tool_type  # Mark as using this tool
                        camera_tool_path = tool_path  # Store full path for later use
                        print(f"✓ Will use {tool_path} for camera capture")
                        break
                    elif tool_path is None:
                        # Check PATH
                        result = subprocess.run(['which', tool_name], 
                                              capture_output=True, text=True, timeout=2)
                        if result.returncode == 0:
                            tool_full_path = result.stdout.strip()
                            print(f"  {tool_name} found at {tool_full_path} - will use for CSI camera capture")
                            USE_LIBCAMERA = tool_type
                            camera = tool_type
                            camera_tool_path = tool_full_path  # Store full path for later use
                            print(f"✓ Will use {tool_full_path} for camera capture")
                            break
                except Exception as e:
                    print(f"  Exception checking for {tool_name}: {e}")
            
            if camera is None or (camera not in ["libcamera", "rpicam", "raspistill", "python_libcamera", "libcamera_hello", "libcamera_vid", "libcamera_raw", "cam"]):
                print("  No CSI camera tools found")
                print("  Note: libcamera-still is not available in AlmaLinux 9 repos")
                print("  Check what tools are in libcamera-tools package:")
                print("    rpm -ql libcamera-tools | grep bin")
                print("  Options:")
                print("    1. Check if libcamera-tools has capture tools: rpm -ql libcamera-tools")
                print("    2. Try using GStreamer with libcamera-gstreamer (if installed)")
                print("    3. Try building libcamera-apps from source")
                print("    4. Use Python libcamera bindings if available")
        
        if camera is None or (camera not in ["libcamera", "rpicam", "raspistill", "python_libcamera", "libcamera_hello", "libcamera_vid", "libcamera_raw", "cam"] and hasattr(camera, 'isOpened') and not camera.isOpened()):
            print(f"ERROR: Failed to open camera device {CAMERA_DEVICE} with any method")
            print("\n" + "="*70)
            print("PiSP Camera Access Issue on AlmaLinux 9")
            print("="*70)
            print("OpenCV cannot directly access PiSP (pispbe-input) devices.")
            print("The error 'can't be used to capture by name' indicates these")
            print("are not standard V4L2 capture devices.")
            print("\nNOTE: libcamera-v4l2 is not available for AlmaLinux 9")
            print("(it's only available in AlmaLinux 10).")
            print("\nPOSSIBLE SOLUTIONS:")
            print("  1. Check available libcamera packages:")
            print("     dnf search libcamera")
            print("     dnf list available | grep libcamera")
            print("\n  2. Check if Python libcamera bindings are available:")
            print("     python3 -c 'import libcamera'")
            print("     dnf search python3-libcamera")
            print("\n  3. Build libcamera from source (complex):")
            print("     See: https://libcamera.org/getting-started.html")
            print("\n  4. Consider upgrading to AlmaLinux 10 (if possible)")
            print("="*70)
            print("\nAlternative troubleshooting:")
            print("  1. Check permissions: ls -l /dev/video*")
            print("  2. Check if user is in video group: groups")
            print("  3. Try: sudo usermod -a -G video $USER")
            print("  4. Check if camera is in use: lsof /dev/video*")
            print("\nNote: Camera will not be available until initialization succeeds.")
            camera = None
            return
        
        # Skip OpenCV setup if using external camera tool or Python libcamera
        if camera in ["libcamera", "rpicam", "raspistill", "python_libcamera", "libcamera_hello", "libcamera_vid", "libcamera_raw", "cam"]:
            tool_names = {
                "libcamera": "libcamera-still",
                "rpicam": "rpicam-still",
                "raspistill": "raspistill",
                "python_libcamera": "Python libcamera bindings",
                "libcamera_hello": "libcamera-hello",
                "libcamera_vid": "libcamera-vid",
                "libcamera_raw": "libcamera-raw",
                "cam": "cam (libcamera-tools)"
            }
            print(f"✓ Camera initialized using {tool_names.get(camera, 'external tool')}")
            return
        
        # Set camera resolution
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        
        # Verify resolution was set
        actual_width = camera.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"Camera resolution set to: {int(actual_width)}x{int(actual_height)}")
        
        # Read a test frame to ensure camera is working
        ret, frame = camera.read()
        if not ret:
            print(f"ERROR: Failed to read test frame from camera {CAMERA_DEVICE}")
            print("Camera opened but cannot read frames - may be a driver issue")
            camera.release()
            camera = None
            return
        
        if frame is None or frame.size == 0:
            print(f"ERROR: Test frame is empty from camera {CAMERA_DEVICE}")
            camera.release()
            camera = None
            return
        
        print(f"✓ Camera {CAMERA_DEVICE} started successfully (resolution: {int(actual_width)}x{int(actual_height)})")
        print(f"  Test frame captured: {frame.shape}")
    except Exception as e:
        print(f"ERROR: Failed to start camera {CAMERA_DEVICE}: {e}")
        import traceback
        traceback.print_exc()
        if camera is not None:
            try:
                camera.release()
            except:
                pass
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
    # Observations: 3×45° ≈ 90°, so 45° is only turning ~30° (needs 2.0× time)
    base_duration = degree * TURN_RATE_SECONDS_PER_DEGREE
    overhead = TURN_ACCELERATION_TIME + TURN_DECELERATION_TIME + TURN_HTTP_LATENCY
    
    # For short turns, overhead and wheel slip dominate - but higher speed (0.4) reduces slip
    # 4-wheel robot: wheel slip during in-place turns, but higher speed helps significantly
    # Current observations with 0.4 speed:
    #   - 90° turns correctly (90°) ✓
    #   - 45° turns 40° (slightly too little, need ~12.5% more)
    # Higher speed reduces slip, so we need much less compensation
    if degree <= 30:
        # Very short turns: reduce significantly
        scale_factor = 0.5
        duration = base_duration * scale_factor + overhead * 0.3
    elif degree <= 45:
        # 45°: turning 40° (needs ~12.5% more), so increase from 0.5 to 0.56
        scale_factor = 0.56
        duration = base_duration * scale_factor + overhead * 0.4
    elif degree < 90:
        # Medium turns: reduce proportionally, interpolate between 0.56 at 45° and 0.75 at 90°
        scale_factor = 0.56 + (degree - 45) / 45.0 * 0.19  # 0.56 at 45°, 0.75 at 90°
        duration = base_duration * scale_factor + overhead * 0.5
    else:
        # 90°: turning correctly, keep at 0.75×
        duration = base_duration * 0.75 + overhead * 0.4
    
    print(f"Calculated duration: {duration:.3f} seconds for {degree} degrees (base: {base_duration:.3f}s).")

    # Start turning
    # Use higher speed to reduce wheel slip (4-wheel robot slips more at lower speeds)
    start_time = time.time()
    success, message = send_motor_command_http(-TURN_SPEED, TURN_SPEED)
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
    # Observations: 3×45° ≈ 90°, so 45° is only turning ~30° (needs 2.0× time)
    base_duration = degree * TURN_RATE_SECONDS_PER_DEGREE
    overhead = TURN_ACCELERATION_TIME + TURN_DECELERATION_TIME + TURN_HTTP_LATENCY
    
    # For short turns, overhead and wheel slip dominate - but higher speed (0.4) reduces slip
    # 4-wheel robot: wheel slip during in-place turns, but higher speed helps significantly
    # Current observations with 0.4 speed:
    #   - 90° turns correctly (90°) ✓
    #   - 45° turns 40° (slightly too little, need ~12.5% more)
    # Higher speed reduces slip, so we need much less compensation
    if degree <= 30:
        # Very short turns: reduce significantly
        scale_factor = 0.5
        duration = base_duration * scale_factor + overhead * 0.3
    elif degree <= 45:
        # 45°: turning 40° (needs ~12.5% more), so increase from 0.5 to 0.56
        scale_factor = 0.56
        duration = base_duration * scale_factor + overhead * 0.4
    elif degree < 90:
        # Medium turns: reduce proportionally, interpolate between 0.56 at 45° and 0.75 at 90°
        scale_factor = 0.56 + (degree - 45) / 45.0 * 0.19  # 0.56 at 45°, 0.75 at 90°
        duration = base_duration * scale_factor + overhead * 0.5
    else:
        # 90°: turning correctly, keep at 0.75×
        duration = base_duration * 0.75 + overhead * 0.4
    
    print(f"Calculated duration: {duration:.3f} seconds for {degree} degrees (base: {base_duration:.3f}s).")

    # Start turning
    # Use higher speed to reduce wheel slip (4-wheel robot slips more at lower speeds)
    start_time = time.time()
    success, message = send_motor_command_http(TURN_SPEED, -TURN_SPEED)
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
    """Captures an image from the camera and returns it as Base64 encoded."""
    global camera, USE_LIBCAMERA
    
    # If camera is None, try to reinitialize it (in case it failed at startup)
    if camera is None:
        print("Camera is None, attempting to reinitialize...")
        try:
            init_camera()
        except Exception as e:
            print(f"Exception during camera reinitialization: {e}")
            import traceback
            traceback.print_exc()
        
        if camera is None:
            # Provide more detailed error information
            error_details = {
                "error": "Camera not started or failed to initialize.",
                "details": "Check server logs for initialization errors.",
                "troubleshooting": [
                    "PiSP cameras on AlmaLinux 9 may not be accessible via standard OpenCV/V4L2",
                    "libcamera-still is not available in AlmaLinux repos",
                    "Try: dnf install libcamera-v4l2 (provides V4L2 compatibility layer)",
                    "Or check if Python libcamera bindings are available",
                    "Check server startup logs for detailed initialization attempts"
                ]
            }
            return jsonify(error_details), 500

    try:
        # Use external camera tools or Python libcamera for CSI cameras on AlmaLinux/RHEL 9
        if USE_LIBCAMERA or camera in ["libcamera", "rpicam", "raspistill", "python_libcamera", "libcamera_hello", "libcamera_vid", "libcamera_raw", "cam"]:
            # Handle Python libcamera bindings
            if camera == "python_libcamera" or USE_LIBCAMERA == "python_libcamera":
                try:
                    import libcamera
                    import numpy as np
                    from PIL import Image
                    import io
                    
                    # Use Python libcamera to capture image
                    # This is a simplified example - actual implementation may vary
                    # based on available libcamera Python bindings
                    with libcamera.Transform() as transform:
                        with libcamera.Stream() as stream:
                            # Capture a still image
                            # Note: Actual API may differ - this is a placeholder
                            # You may need to adjust based on actual libcamera Python bindings
                            pass
                    
                    # For now, return an error indicating Python libcamera needs implementation
                    return jsonify({
                        "error": "Python libcamera bindings detected but not yet implemented",
                        "details": "Python libcamera support needs to be implemented based on available bindings"
                    }), 501
                except ImportError:
                    return jsonify({"error": "Python libcamera module not available"}), 500
                except Exception as e:
                    return jsonify({"error": f"Python libcamera error: {str(e)}"}), 500
            
            # Determine which tool to use and get its path
            tool_cmd = None
            tool_type = camera if camera in ["libcamera", "rpicam", "raspistill", "libcamera_hello", "libcamera_vid", "libcamera_raw", "cam"] else USE_LIBCAMERA
            
            # Use stored path if available, otherwise use command name
            global camera_tool_path
            if camera_tool_path:
                tool_cmd = camera_tool_path
            else:
                # Fallback to just the command name
                if tool_type == "libcamera":
                    tool_cmd = "libcamera-still"
                elif tool_type == "rpicam":
                    tool_cmd = "rpicam-still"
                elif tool_type == "raspistill":
                    tool_cmd = "raspistill"
                elif tool_type == "libcamera_hello":
                    tool_cmd = "libcamera-hello"
                elif tool_type == "libcamera_vid":
                    tool_cmd = "libcamera-vid"
                elif tool_type == "libcamera_raw":
                    tool_cmd = "libcamera-raw"
                elif tool_type == "cam":
                    tool_cmd = "cam"
            
            if not tool_cmd:
                return jsonify({"error": "Camera tool not specified"}), 500
            
            # Capture image using the appropriate tool
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            try:
                # Build command based on tool
                # Check if tool_cmd is "cam" (could be full path like /usr/bin/cam or just "cam")
                tool_basename = os.path.basename(tool_cmd) if tool_cmd else ""
                print(f"DEBUG: tool_cmd={tool_cmd}, tool_basename={tool_basename}, tool_type={tool_type}")
                if tool_basename == "cam" or tool_cmd == "cam" or tool_type == "cam":
                    # cam tool from libcamera-tools
                    # Syntax: cam -c <camera> -C <count> -F <file> -s role=still,width=W,height=H
                    # Use camera index 0 (first camera) or we could list cameras first
                    cmd = [
                        tool_cmd,
                        '-c', '0',  # Camera index 0 (first camera)
                        '-C', '1',  # Capture 1 frame
                        '-F', tmp_path,  # Output file
                        '-s', f'role=still,width={CAMERA_WIDTH},height={CAMERA_HEIGHT}'  # Stream configuration
                    ]
                elif tool_basename in ["libcamera-still", "rpicam-still"] or tool_cmd in ["libcamera-still", "rpicam-still"]:
                    # Modern libcamera/rpicam tools
                    cmd = [
                        tool_cmd,
                        '--width', str(CAMERA_WIDTH),
                        '--height', str(CAMERA_HEIGHT),
                        '--output', tmp_path,
                        '--timeout', '1000',  # 1 second timeout
                        '--nopreview'
                    ]
                elif tool_basename == "raspistill" or tool_cmd == "raspistill":
                    # Legacy raspistill
                    cmd = [
                        tool_cmd,
                        '-w', str(CAMERA_WIDTH),
                        '-h', str(CAMERA_HEIGHT),
                        '-o', tmp_path,
                        '-t', '1000',  # 1 second timeout
                        '-n'  # No preview
                    ]
                else:
                    # Unknown tool - return error
                    return jsonify({
                        "error": f"Unknown camera tool: {tool_cmd}",
                        "details": "Tool detected but command format not implemented"
                    }), 500
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                
                if result.returncode != 0:
                    return jsonify({"error": f"{tool_cmd} failed: {result.stderr}"}), 500
                
                # Read the captured image
                with open(tmp_path, 'rb') as img_file:
                    image_data = img_file.read()
                
                # Encode to Base64
                base64_encoded_image = base64.b64encode(image_data).decode('utf-8')
                
                # Clean up temp file
                os.unlink(tmp_path)
                
                return base64_encoded_image
                
            except subprocess.TimeoutExpired:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return jsonify({"error": "Camera capture timeout"}), 500
            except Exception as e:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        
        # Use OpenCV for USB cameras or V4L2-compatible cameras
        if not camera.isOpened():
            return jsonify({"error": "Camera not opened."}), 500
        
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
        import traceback
        traceback.print_exc()
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

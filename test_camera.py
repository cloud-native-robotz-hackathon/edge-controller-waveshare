#!/usr/bin/env python3
"""Simple script to test camera access and find working camera device."""
import cv2
import os

print("Testing camera devices...")
print("=" * 60)

# Get all video devices
video_devices = sorted([f for f in os.listdir('/dev') if f.startswith('video')])
print(f"Found {len(video_devices)} video devices: {video_devices[:10]}...")

# Try each device
working_cameras = []
for video_dev in video_devices:
    dev_path = f'/dev/{video_dev}'
    print(f"\nTesting {dev_path}...")
    
    # Try with V4L2 backend
    try:
        cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
        if cap.isOpened():
            print(f"  ✓ Opened successfully")
            
            # Set some properties that might help with timeout
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to avoid stale frames
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
            
            # Check if it's a capture device by checking capabilities
            try:
                backend = cap.getBackendName()
                print(f"    Backend: {backend}")
            except:
                pass
            
            # Try to read a frame with shorter timeout
            # Set timeout by using grab() + retrieve() instead of read()
            print(f"    Attempting to grab frame...")
            grabbed = cap.grab()
            if grabbed:
                ret, frame = cap.retrieve()
                if ret and frame is not None and frame.size > 0:
                    print(f"  ✓✓✓ Can read frames! Shape: {frame.shape}")
                    working_cameras.append((dev_path, frame.shape))
                else:
                    print(f"  ✗ Grabbed but retrieve failed or empty frame")
            else:
                print(f"  ✗ Cannot grab frame (likely not a capture device)")
            
            cap.release()
        else:
            print(f"  ✗ Failed to open")
    except Exception as e:
        print(f"  ✗ Exception: {e}")

print("\n" + "=" * 60)
if working_cameras:
    print(f"Found {len(working_cameras)} working camera(s):")
    for dev, shape in working_cameras:
        print(f"  {dev} - Frame shape: {shape}")
else:
    print("No working cameras found!")
    print("\nTrying with device index instead...")
    # Try device indices 0-5
    for idx in range(6):
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"  ✓ Device index {idx} works! Shape: {frame.shape}")
                    working_cameras.append((f"index {idx}", frame.shape))
                cap.release()
        except Exception as e:
            pass


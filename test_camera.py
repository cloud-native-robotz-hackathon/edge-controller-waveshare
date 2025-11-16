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
            # Try to read a frame
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f"  ✓ Can read frames! Shape: {frame.shape}")
                working_cameras.append((dev_path, frame.shape))
            else:
                print(f"  ✗ Opened but cannot read frames")
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


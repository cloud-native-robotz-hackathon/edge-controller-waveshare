#!/usr/bin/env python3
"""
Test script to diagnose WAVE ROVER HTTP communication.
This helps identify the correct endpoint and format.
"""
import requests
import json
import os

ROBOT_IP = os.environ.get('ROBOT_IP', '192.168.4.1')
HTTP_TIMEOUT = 2.0

# Test different endpoint paths
ENDPOINTS = [
    f'http://{ROBOT_IP}',
    f'http://{ROBOT_IP}/',
    f'http://{ROBOT_IP}/api',
    f'http://{ROBOT_IP}/cmd',
    f'http://{ROBOT_IP}/json',
    f'http://{ROBOT_IP}/control',
]

# Test different command formats
COMMANDS = [
    # Format 1: Float speeds (-0.5 to 0.5)
    {"T": 1, "L": 0.3, "R": 0.3},
    # Format 2: Integer speeds (0-255 PWM)
    {"T": 11, "L": 164, "R": 164},
    # Format 3: String type
    {"T": "1", "L": 0.3, "R": 0.3},
]

print(f"Testing WAVE ROVER HTTP communication at {ROBOT_IP}")
print("=" * 60)

for endpoint in ENDPOINTS:
    print(f"\nTesting endpoint: {endpoint}")
    print("-" * 60)
    
    for i, cmd in enumerate(COMMANDS, 1):
        print(f"  Command {i}: {json.dumps(cmd)}")
        
        try:
            # Test with JSON
            response = requests.post(endpoint, json=cmd, timeout=HTTP_TIMEOUT)
            print(f"    Status: {response.status_code}")
            print(f"    Response: {response.text[:100]}")
            
            if response.status_code == 200:
                print(f"    ✓ SUCCESS with endpoint {endpoint} and command format {i}")
        except requests.exceptions.Timeout:
            print(f"    ✗ Timeout")
        except requests.exceptions.ConnectionError as e:
            print(f"    ✗ Connection error: {e}")
        except Exception as e:
            print(f"    ✗ Error: {e}")
        
        # Also test with form data
        try:
            response = requests.post(endpoint, data=json.dumps(cmd), 
                                   headers={'Content-Type': 'application/json'},
                                   timeout=HTTP_TIMEOUT)
            if response.status_code == 200:
                print(f"    ✓ SUCCESS with form data on {endpoint}")
        except:
            pass

print("\n" + "=" * 60)
print("Test complete. Check which endpoint/format worked above.")


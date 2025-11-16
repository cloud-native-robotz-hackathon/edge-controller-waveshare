#!/bin/bash
# Check video device capabilities to find actual cameras

echo "Checking video device capabilities..."
echo "============================================================"

for dev in /dev/video*; do
    echo ""
    echo "=== $dev ==="
    
    # Check if v4l2-ctl is available
    if command -v v4l2-ctl &> /dev/null; then
        # Get device info
        v4l2-ctl --device=$dev --all 2>/dev/null | head -30
    else
        # Fallback: check device type
        file $dev 2>/dev/null
        ls -l $dev 2>/dev/null
    fi
done

echo ""
echo "============================================================"
echo "Look for devices with 'Video Capture' capability"
echo "Devices that timeout are likely encoders/outputs, not cameras"


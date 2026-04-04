#!/usr/bin/env python3
"""
Debug script to test connection to Waveshare thermal camera.
Run this to diagnose connection and data streaming issues.

Usage:
  python debug_thermal_connection.py <IP_ADDRESS> [PORT]
  
Example:
  python debug_thermal_connection.py 192.168.1.100 3333
"""

import socket
import sys
import time
import struct

def test_connection(host, port=3333):
    """Test TCP connection and data streaming from thermal camera."""
    print(f"🔍 Debugging Waveshare Thermal Camera at {host}:{port}\n")
    
    # Test 1: Ping/connectivity
    print(f"1️⃣  Testing network connectivity...")
    try:
        sock_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_test.settimeout(5)
        result = sock_test.connect_ex((host, port))
        sock_test.close()
        if result == 0:
            print(f"   ✅ Port {port} is open and listening\n")
        else:
            print(f"   ❌ Cannot connect to {host}:{port}")
            print(f"   Check: IP address, port number, device powered on\n")
            return
    except Exception as e:
        print(f"   ❌ Error: {e}\n")
        return
    
    # Test 2: Connect and wait for data
    print(f"2️⃣  Connecting and waiting for thermal data...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)  # Longer timeout for connect
        print(f"   Connecting...")
        s.connect((host, port))
        print(f"   ✅ Connected!\n")
        
        print(f"3️⃣  Listening for thermal frames (30 seconds)...")
        s.settimeout(30)  # Much longer timeout
        data_received = False
        total_bytes = 0
        frame_count = 0
        start_time = time.time()
        
        while time.time() - start_time < 30:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    print(f"   ⚠️  Connection closed by device")
                    break
                
                data_received = True
                total_bytes += len(chunk)
                
                # Thermal frames should be 10240 bytes each
                if total_bytes % 10240 == 0:
                    frame_count = total_bytes // 10240
                    print(f"   ✅ Received {frame_count} complete frame(s) ({total_bytes} bytes total)")
                    
                    # Try to decode first frame
                    if frame_count == 1:
                        try:
                            values = struct.unpack(f"<{10240//2}H", chunk[:10240])
                            min_val = min(values)
                            max_val = max(values)
                            min_temp = min_val * 0.0984 - 265.82
                            max_temp = max_val * 0.0984 - 265.82
                            print(f"   📊 First frame: Min={min_temp:.1f}°C, Max={max_temp:.1f}°C")
                        except Exception as e:
                            print(f"   ⚠️  Could not decode frame: {e}")
                
            except socket.timeout:
                if not data_received:
                    print(f"   ❌ NO DATA RECEIVED after 30 seconds!")
                    print(f"   The device accepted the connection but is not sending thermal data.")
                    print(f"\n   Troubleshooting:")
                    print(f"   • Check ESP32 serial console for errors")
                    print(f"   • Verify thermal camera sensor is connected to ESP32")
                    print(f"   • Check if senxorTask is running (not blocked)")
                    print(f"   • Power cycle the ESP32")
                    print(f"   • Try using official Waveshare viewer to verify device works")
                else:
                    elapsed = time.time() - start_time
                    print(f"   ⏱️  Timeout after {elapsed:.1f}s, received {total_bytes} bytes")
                break
        
        if data_received and frame_count > 0:
            elapsed = time.time() - start_time
            fps = frame_count / elapsed
            print(f"\n   ✅ SUCCESS! Device is streaming at ~{fps:.1f} FPS")
            print(f"   Total: {frame_count} frames in {elapsed:.1f} seconds")
        elif data_received:
            print(f"\n   ⚠️  Received partial data but not complete frames")
            print(f"   Total bytes: {total_bytes}")
        
        s.close()
        
    except ConnectionRefusedError:
        print(f"   ❌ Connection refused!")
        print(f"   Device is not listening on {host}:{port}")
        print(f"   Check: Is thermal camera firmware running? Is it on this IP?")
    except socket.timeout:
        print(f"   ❌ Connection timeout")
        print(f"   The port is open, but the device didn't complete the handshake.")
        print(f"   This might mean:")
        print(f"   • Device is very busy and not accepting connections")
        print(f"   • Firewall is interfering with the connection")
        print(f"   • Device needs more time to initialize")
        print(f"   • Try power-cycling the device")
    except Exception as e:
        print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_thermal_connection.py <IP_ADDRESS> [PORT]")
        print("Example: python debug_thermal_connection.py 192.168.1.100 3333")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3333
    
    test_connection(host, port)

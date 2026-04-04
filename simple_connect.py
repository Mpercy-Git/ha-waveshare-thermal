#!/usr/bin/env python3
"""
Ultra-simple connection test - just try to connect and print errors.
"""
import socket
import sys

if len(sys.argv) < 2:
    print("Usage: python simple_connect.py <IP> [PORT]")
    sys.exit(1)

host = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 3333

print(f"Simple connect test to {host}:{port}")
print()

# Test 1: Raw socket with very long timeout
print("Attempt 1: TCP connect with 30 second timeout...")
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(30)
try:
    s.connect((host, port))
    print("✅ Connected!")
    
    # Try to receive
    print("Waiting for data (10 seconds)...")
    s.settimeout(10)
    data = s.recv(100)
    if data:
        print(f"✅ Got {len(data)} bytes: {data[:50]}")
    else:
        print("❌ Connection closed immediately")
    s.close()
except socket.timeout:
    print("❌ Timeout during connect")
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
finally:
    s.close()

print()
print("=" * 60)
print("If this fails, the device may be:")
print("• Powered off")
print("• On a different network/IP")
print("• Running a different firmware that doesn't accept TCP")
print("• Frozen/crashed")
print()
print("Try:")
print("1. Power cycle the thermal camera")
print("2. Verify IP with Waveshare viewer: what IP does it show?")
print("3. Check if device LED is on")

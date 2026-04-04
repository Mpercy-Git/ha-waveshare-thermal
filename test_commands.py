#!/usr/bin/env python3
"""
Try different commands to trigger thermal data transmission.
"""
import socket
import sys
import time

if len(sys.argv) < 2:
    print("Usage: python test_commands.py <IP> [PORT]")
    sys.exit(1)

host = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 3333

print(f"Testing commands to trigger thermal data at {host}:{port}")
print("=" * 60)

commands = [
    ("No command (just wait)", b""),
    ("Single null byte", b"\x00"),
    ("Startup command: '   #2808GFRA'", b"   #2808GFRA"),
    ("Startup command padded to 49 bytes", b"   #2808GFRA" + b"\x00" * 37),
    ("Repeated nulls", b"\x00" * 12),
]

for name, cmd in commands:
    print(f"\nAttempt: {name}")
    print(f"Sending: {len(cmd)} bytes")
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((host, port))
        print(f"✅ Connected")
        
        if cmd:
            s.send(cmd)
            print(f"✅ Sent: {repr(cmd[:30])}")
        else:
            print("(waiting without sending)")
        
        # Wait for data
        print("Waiting 5 seconds for data...")
        s.settimeout(5)
        data = b""
        start = time.time()
        
        try:
            while time.time() - start < 5:
                chunk = s.recv(4096)
                if not chunk:
                    print("Connection closed")
                    break
                data += chunk
                elapsed = time.time() - start
                print(f"  [{elapsed:.1f}s] Got {len(chunk)} bytes (total: {len(data)})")
                
                if len(data) >= 10240:
                    print(f"✅ SUCCESS! Got {len(data)} bytes (at least 1 frame)!")
                    break
        except socket.timeout:
            if data:
                print(f"⏱️  Timeout but received {len(data)} bytes total")
            else:
                print(f"❌ Timeout - no data")
        
        s.close()
        
        if len(data) >= 10240:
            break  # Found it!
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    time.sleep(1)

print("\n" + "=" * 60)
print("If no command works, the sensor may not be initialized.")
print("Check ESP32 serial output for sensor errors.")

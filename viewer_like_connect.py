#!/usr/bin/env python3
"""
Connect like the official Waveshare viewer does.
Tests different connection methods and timeouts.
"""
import socket
import sys
import time

if len(sys.argv) < 2:
    print("Usage: python viewer_like_connect.py <IP> [PORT]")
    sys.exit(1)

host = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 3333

print(f"Connecting like Waveshare viewer to {host}:{port}")
print("=" * 60)

methods = [
    ("Standard TCP", lambda h, p: create_standard(h, p)),
    ("Non-blocking then blocking", lambda h, p: create_nonblocking_then_blocking(h, p)),
    ("Very quick timeout", lambda h, p: create_quick(h, p)),
]

def create_standard(h, p):
    """Standard socket connection."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((h, p))
    return s

def create_nonblocking_then_blocking(h, p):
    """Try non-blocking first."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setblocking(False)
    try:
        s.connect((h, p))
    except BlockingIOError:
        # Expected for non-blocking
        pass
    time.sleep(0.1)
    s.setblocking(True)
    s.settimeout(5)
    return s

def create_quick(h, p):
    """Very quick timeout."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    s.connect((h, p))
    return s

for name, func in methods:
    print(f"\nMethod: {name}")
    try:
        s = func(host, port)
        print(f"✅ Connected!")
        
        # Try to get data
        s.settimeout(2)
        try:
            data = s.recv(4096)
            if data:
                print(f"✅ Got data: {len(data)} bytes")
                print(f"   First bytes: {data[:30]}")
            else:
                print("⚠️  Got EOF")
        except socket.timeout:
            print("⏱️  No data (timeout)")
        except Exception as e:
            print(f"❌ Recv error: {e}")
        finally:
            s.close()
        break  # Success, no need to try other methods
        
    except socket.timeout:
        print(f"❌ Timeout")
    except ConnectionRefusedError:
        print(f"❌ Connection refused")
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("If all methods fail, close the Waveshare viewer and try again.")
print("The device may only accept one connection at a time.")

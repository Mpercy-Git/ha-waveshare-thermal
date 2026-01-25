# Waveshare Thermal Camera for Home Assistant

Custom component to integrate the [Waveshare ESP32 Thermal Camera](https://www.waveshare.com/wiki/Thermal_Camera_ESP32_Module) into Home Assistant.

## Features
- **Live Thermal View**: Streams thermal data from the ESP32 module as a camera feed.
- **Temperature Sensors**: Real-time minimum and maximum temperature readings exposed as Home Assistant sensor entities.
- **Temperature Stats**: Displays min/max temperatures on the live image feed.
- **False Color Imaging**: Applies an "Inferno" style colormap to thermal data for better visualization.
- **Snapshot Support**: Generates valid JPEG snapshots for notifications or UI.
- **Auto-Reconnection**: Implements exponential backoff reconnection strategy with detailed error logging.

## Requirements
- **Hardware**: Waveshare Thermal Camera ESP32 Module.
- **Firmware**: Default firmware or compatible TCP server implementation.
- **Network**: The device must be connected to your local network (Station Mode) or accessible via its AP.
    - **Default Port**: `3333`
    - **Recommended Resolution**: 80x62 (Device default)
    - **Network Type**: Ethernet or Wi-Fi (2.4GHz recommended)

## Installation

### Option 1: HACS (Recommended)
1.  Open HACS in Home Assistant.
2.  Go to "Integrations" > Top right menu > "Custom repositories".
3.  Add this repository URL.
4.  Category: **Integration**.
5.  Click "Download".
6.  Restart Home Assistant.

### Option 2: Manual
1.  Download the `custom_components/waveshare_thermal` folder.
2.  Copy it to your Home Assistant `config/custom_components/` directory.
3.  Restart Home Assistant.

## Configuration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **+ Add Integration**.
3.  Search for **Waveshare Thermal Camera**.
4.  Enter the **IP Address** of your camera (e.g., `192.168.1.204`).
5.  (Optional) Change the port if modified (Default: `3333`).
6.  Click **Submit**.

## Entities

After successful configuration, the integration creates:

### Camera
- **`camera.thermal_camera`** - Live thermal video feed with temperature overlay

### Sensors
- **`sensor.thermal_camera_min_temperature`** - Minimum temperature from current frame (°C)
- **`sensor.thermal_camera_max_temperature`** - Maximum temperature from current frame (°C)

These sensors update in real-time as new thermal frames are received.

## Troubleshooting

### Stuck on "Connecting..." or "No data received for 30 seconds"
If the camera image shows a "Connecting..." placeholder or reconnects every 30 seconds:

1.  **Check Network**: Ensure the camera is connected to Wi-Fi and reachable from your Home Assistant server.
    - Try `ping <camera_ip>` from a terminal.
    - If connecting via the camera's AP, ensure HA is connected to that specific Wi-Fi network.
    
2.  **Check Firmware**: Ensure the ESP32 is running the thermal camera firmware that implements TCP streaming.
    - The firmware must listen on port 3333 and respond to startup command `"   #2808GFRA"`.
    
3.  **Check Mode**: The camera works best in Station Mode (connected to your Router). If using AP mode, it may have limited range or single-connection limits.

4.  **Check Logs**: Go to **Settings** > **System** > **Logs** and search for "waveshare_thermal":
    - Look for `Attempting to connect to <IP>:<PORT>` to verify correct IP/port.
    - Look for `Successfully connected to thermal camera` and `Sent startup command` - these indicate the handshake succeeded.
    - Look for `Error connecting: Connection refused` - indicates device isn't listening on the port.
    - Look for `Error connecting: Network error` - indicates unreachable IP address.

### "Connection refused" Error
- The device is reachable but not listening on port 3333.
- Verify firmware is properly installed and running on the ESP32.
- Try power cycling the device.

### Corrupt Images or Pixel Drift
- This integration is tuned for the standard 80x62 resolution (10240 bytes per frame).
- If you see scrolling or garbled pixels, the firmware might be sending a different packet size.
- Check the [Waveshare documentation](https://www.waveshare.com/wiki/Thermal_Camera_ESP32_Module) for firmware updates.

### Only One Connection Supported
- Some firmware versions only allow a single simultaneous connection.
- Close the official Waveshare viewer or other connections before using Home Assistant.
- The integration will maintain the connection with automatic reconnection on failure.

## Advanced

### Temperature Conversion
Temperatures are converted from raw sensor values using the formula:
```
Temperature (°C) = (Raw Value × 0.0984) - 265.82
```

This formula is derived from the sensor's specification and matches the official Waveshare client implementation.

### Frame Format
- **Resolution**: 80×62 pixels (standard)
- **Data Format**: Raw 16-bit unsigned integers (little-endian)
- **Packet Structure**: 160-byte header + 10240 bytes payload + 160-byte footer
- **Update Rate**: Depends on firmware (typically 15-30 FPS)

## Known Limitations
- Only one active TCP connection supported per device (firmware limitation).
- Temperature readings reflect the current frame only; no historical data stored.
- Requires local network access; cloud remote viewing not supported in this component.

## Support
For issues, feature requests, or questions:
1. Check the troubleshooting section above.
2. Review [Home Assistant Logs](https://www.home-assistant.io/docs/configuration/troubleshooting/) for detailed error messages.
3. Open an issue on the GitHub repository with:
   - Integration version
   - Error logs from Home Assistant
   - Network topology (is the device on same subnet as HA?)
   - Firmware version of the thermal camera (if known)

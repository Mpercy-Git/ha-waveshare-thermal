# Waveshare Thermal Camera for Home Assistant

Custom component to integrate the [Waveshare ESP32 Thermal Camera](https://www.waveshare.com/wiki/Thermal_Camera_ESP32_Module) into Home Assistant.

## Features
- **Live Thermal View**: Streams thermal data from the ESP32 module.
- **Temperature Stats**: Displays real-time Minimum and Maximum temperatures on the image.
- **False Color**: Applies an "Inferno" style colormap to valid thermal data.
- **Snapshot Support**: Generates valid JPEG snapshots for notifications or UI.

## Requirements
- **Hardware**: Waveshare Thermal Camera ESP32 Module.
- **Firmware**: Default firmware or compatible TCP server implementation.
- **Network**: The device must be connected to your local network (Station Mode) or accessible via its AP.
    - **Default Port**: `3333`
    - **Recommended Resolution**: 80x62 (Device default)

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

## Troubleshooting

### Stuck on "Connecting..."
If the camera image shows a "Connecting..." placeholder indefinitely:
1.  **Check Network**: Ensure the camera is connected to Wi-Fi and reachable from your Home Assistant server.
    - Try `ping <camera_ip>` from a terminal.
    - If connecting via the camera's AP, ensure HA is connected to that specific Wi-Fi network.
2.  **Check Mode**: The camera works best in Station Mode (connected to your Router). If using AP mode, it may have limited range or single-connection limits.
3.  **Logs**: Check `Settings` > `System` > `Logs` for "waveshare_thermal". structure.
    - Look for `Attempting to connect to ...` to verify the ID/Port.
    - Look for `Error connecting: timed out` which indicates network blockage.

### "Senxor not connected"
If using the official viewer concurrently:
- The device may only support **one active connection**. Close the official viewer before using Home Assistant.

### Corrupt Images / Drift
- This integration is tuned for the standard 80x62 resolution (Total packet size 10240 bytes).
- If you see scrolling or garbled pixels, your firmware might be sending a different packet size. Report this in an issue.

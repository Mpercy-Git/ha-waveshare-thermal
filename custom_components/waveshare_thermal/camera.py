"""Camera platform for Waveshare Thermal Camera."""
import asyncio
import io
import logging
import socket
import struct
import threading
import time
from threading import Lock

from PIL import Image, ImageDraw, ImageFont

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

FRAME_WIDTH = 80
FRAME_HEIGHT = 62
BUFFER_WIDTH = 80
BUFFER_HEIGHT = 62  # Correct thermal resolution (not 63)

# Frame structure (final analysis):
# - 160-byte header: "   #2808GFRA" + 148 zeros
# - 9920 bytes thermal data: 80 * 62 * 2 bytes (little-endian uint16)
# - 176-byte tail: padding/checksum
# Total frame size: 10256 bytes
FRAME_HEADER_SIZE = 160
PAYLOAD_SIZE = BUFFER_WIDTH * BUFFER_HEIGHT * 2  # 9920 bytes
FRAME_TAIL_SIZE = 176
FRAME_SIZE = FRAME_HEADER_SIZE + PAYLOAD_SIZE + FRAME_TAIL_SIZE  # 10256 bytes total

# Inferno-ish colormap (interpolated)
COLORMAP = [
    (0, 0, 4), (66, 10, 104), (147, 38, 103), (221, 81, 58), (252, 165, 10), (252, 255, 164)
]

def get_color(val, min_val, max_val):
    if max_val == min_val:
        norm = 0.5
    else:
        norm = (val - min_val) / (max_val - min_val)
    
    # Map norm (0.0-1.0) to colormap
    idx = norm * (len(COLORMAP) - 1)
    i = int(idx)
    f = idx - i
    if i >= len(COLORMAP) - 1:
        return COLORMAP[-1]
    
    c1 = COLORMAP[i]
    c2 = COLORMAP[i+1]
    
    r = int(c1[0] + f * (c2[0] - c1[0]))
    g = int(c1[1] + f * (c2[1] - c1[1]))
    b = int(c1[2] + f * (c2[2] - c1[2]))
    return (r, g, b)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the camera platform from yaml."""
    # We could deprecate this or leave it for now.
    pass

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform from config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    name = entry.data.get(CONF_NAME) or entry.title

    camera = WaveshareThermalCamera(hass, name, host, port, entry.entry_id)
    
    # Store camera reference for sensors to access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entities", {})[entry.entry_id] = camera
    
    async_add_entities([camera])


class WaveshareThermalCamera(Camera):
    """Representation of a Waveshare Thermal Camera."""

    def __init__(self, hass, name, host, port, unique_id):
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._name = name
        self._host = host
        self._port = port
        self._attr_unique_id = unique_id
        self._last_image = self._create_placeholder_image()
        self._image_lock = Lock()  # Thread-safe image access
        self._min_temp = 0.0
        self._max_temp = 0.0
        self._temp_lock = Lock()  # Thread-safe temperature access
        self._running = True
        self._thread = threading.Thread(target=self._run_worker, name=f"ThermalCamera_{name}")
        self._thread.daemon = True
        self._thread.start()

    @property
    def name(self):
        """Return the name of this camera."""
        return self._name

    def get_min_temp(self):
        """Get minimum temperature."""
        with self._temp_lock:
            return self._min_temp

    def get_max_temp(self):
        """Get maximum temperature."""
        with self._temp_lock:
            return self._max_temp

    async def async_camera_image(self, width=None, height=None):
        """Return a still image response from the camera."""
        with self._image_lock:
            return self._last_image

    async def async_will_remove_from_hass(self):
        """Stop the background thread when entity is removed."""
        self.stop()

    def _create_placeholder_image(self):
        """Create a placeholder image."""
        try:
            img = Image.new('RGB', (320, 248), color=(40, 44, 52))
            draw = ImageDraw.Draw(img)
            # Simple fallback if font loading fails, though default is usually fine
            draw.text((80, 110), "Connecting...", fill=(255, 255, 255))
            b_io = io.BytesIO()
            img.save(b_io, 'JPEG', quality=80)
            return b_io.getvalue()
        except Exception as e:
            _LOGGER.error("Error creating placeholder image: %s", e)
            return None

    def _run_worker(self):
        """Background thread to read from TCP stream."""
        reconnect_delay = 5
        max_reconnect_delay = 60
        max_buffer_size = FRAME_SIZE * 10  # Allow buffering of up to 10 frames
        
        while self._running:
            try:
                # Open socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(10.0)  # Connection timeout
                    _LOGGER.info("Attempting to connect to %s:%s", self._host, self._port)
                    try:
                        s.connect((self._host, self._port))
                    except socket.timeout:
                        _LOGGER.error("Connection timed out to %s:%s after 10s. Check if device is powered on and port is correct.", self._host, self._port)
                        raise
                    except ConnectionRefusedError:
                        _LOGGER.error("Connection refused by %s:%s. Device may not be listening on this port.", self._host, self._port)
                        raise
                    except OSError as e:
                        _LOGGER.error("Network error connecting to %s:%s - %s. Check IP address and network connectivity.", self._host, self._port, e)
                        raise
                    
                    _LOGGER.info("Successfully connected to thermal camera at %s:%s", self._host, self._port)
                    _LOGGER.info("Thermal stream should start automatically. Waiting for data...")
                    reconnect_delay = 5  # Reset delay on successful connection
                    
                    # Set socket options for stability
                    try:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        _LOGGER.debug("Enabled TCP keep-alive")
                    except Exception as e:
                        _LOGGER.debug("Could not set socket options: %s", e)
                    
                    # Send command to start thermal streaming
                    # Command protocol: #000CWREGB10302DE
                    #   #000C - Command header
                    #   WREG - Write Register command
                    #   B1 - Register 0xB1 (streaming control)
                    #   03 - Value 0x03 (enable streaming)
                    #   02DE - Parameters/checksum
                    try:
                        start_cmd = b"#000CWREGB10302DE"
                        s.send(start_cmd)
                        _LOGGER.info("Sent start streaming command to camera")
                        
                        # Wait for acknowledgment response (17 bytes: "   #0008WREG01FD\x00")
                        s.settimeout(5.0)
                        ack = s.recv(17)
                        if ack:
                            _LOGGER.info("Received camera acknowledgment: %s", ack.decode('ascii', errors='replace').strip())
                        else:
                            _LOGGER.warning("No acknowledgment received from camera")
                    except Exception as e:
                        _LOGGER.warning("Error during handshake: %s (continuing anyway)", e)
                    
                    # Frame format: 16-byte header + 10240-byte thermal data = 10256 bytes
                    # Frame header signature: b"   #2808GFRA" (first 12 bytes)
                    packet_size = FRAME_SIZE
                    frame_header_signature = b"   #2808GFRA"
                    frame_count = 0
                    first_data_received = False
                    synchronized = False
                    
                    # Buffer for incoming data
                    data_buffer = b""
                    
                    # Set recv timeout to 60 seconds - device may take time to initialize sensor
                    s.settimeout(60.0)
                    
                    while self._running:
                        try:
                            chunk = s.recv(4096)
                            if not chunk:
                                _LOGGER.warning("Connection closed by remote host")
                                break
                            
                            if not first_data_received:
                                _LOGGER.info("Received first data packet (%d bytes). Device is streaming!", len(chunk))
                                first_data_received = True
                            
                            data_buffer += chunk
                            
                            # Prevent buffer overflow from misbehaving device
                            if len(data_buffer) > max_buffer_size:
                                _LOGGER.warning("Buffer overflow detected (%d bytes). Clearing buffer.", len(data_buffer))
                                data_buffer = b""
                                synchronized = False
                                continue
                            
                            # Find frame boundary if not synchronized
                            if not synchronized:
                                header_pos = data_buffer.find(frame_header_signature)
                                if header_pos != -1:
                                    # Found frame header - discard everything before it
                                    data_buffer = data_buffer[header_pos:]
                                    synchronized = True
                                    _LOGGER.info("Frame synchronization established at position %d", header_pos)
                                elif len(data_buffer) > packet_size:
                                    # Keep only recent data to search
                                    data_buffer = data_buffer[-packet_size:]
                                continue
                            
                            while len(data_buffer) >= packet_size:
                                # Extract one full frame (header + thermal data)
                                frame_packet = data_buffer[:packet_size]
                                
                                # Validate frame header signature
                                if not frame_packet.startswith(frame_header_signature):
                                    _LOGGER.warning("Frame header validation failed. Re-synchronizing...")
                                    synchronized = False
                                    # Search for next valid header
                                    header_pos = data_buffer.find(frame_header_signature, 1)
                                    if header_pos != -1:
                                        data_buffer = data_buffer[header_pos:]
                                        synchronized = True
                                        _LOGGER.info("Re-synchronized at position %d", header_pos)
                                    else:
                                        data_buffer = b""
                                    break
                                
                                # Header is valid, consume the frame
                                data_buffer = data_buffer[packet_size:]
                                
                                try:
                                    # Skip 160-byte frame header, extract thermal data, skip 16-byte tail
                                    raw_data = frame_packet[FRAME_HEADER_SIZE:FRAME_HEADER_SIZE + PAYLOAD_SIZE]
                                    
                                    # Validate data size
                                    if len(raw_data) != PAYLOAD_SIZE:
                                        _LOGGER.warning("Invalid payload size: %d, expected %d", len(raw_data), PAYLOAD_SIZE)
                                        continue
                                    
                                    # Convert to pixels
                                    # Firmware sends 80x62 array (4960 uint16 values in little-endian)
                                    fmt = f"<{len(raw_data)//2}H"  # Little-endian unsigned short
                                    all_values = struct.unpack(fmt, raw_data)
                                    
                                    # Use all values - firmware is already correct size
                                    values = all_values
                                    
                                    # Filter out invalid values for temperature calculation:
                                    # - Zeros are sensor errors/missing pixels
                                    # - Values >= 10000 are outlier/hot pixels (< 0.1% of data)
                                    # Normal thermal range is roughly 2500-4000 raw (0-60°C)
                                    valid_values = [v for v in values if 0 < v < 10000]
                                    
                                    if valid_values:
                                        min_val = min(valid_values)
                                        max_val = max(valid_values)
                                    else:
                                        # Fallback if all values are invalid (shouldn't happen)
                                        min_val = 0
                                        max_val = 65535
                                    
                                    # Create Image from thermal data (80x62 - native resolution)
                                    img = Image.new('RGB', (BUFFER_WIDTH, BUFFER_HEIGHT))  # 80x62
                                    pixels_rgb = [get_color(v, min_val, max_val) for v in values]
                                    img.putdata(pixels_rgb)
                                    
                                    # Resize for better visibility in HA (4x upscaling)
                                    img = img.resize((320, 248), resample=Image.NEAREST)
                                    
                                    # Draw stats
                                    draw = ImageDraw.Draw(img)
                                    # Convert raw to celsius: val * 0.0984 - 265.82 (from client.js)
                                    min_temp = min_val * 0.0984 - 265.82
                                    max_temp = max_val * 0.0984 - 265.82
                                    
                                    text = f"Min: {min_temp:.1f}C  Max: {max_temp:.1f}C"
                                    draw.text((5, 5), text, fill=(255, 255, 255))
                                    
                                    # Save to byte buffer
                                    b_io = io.BytesIO()
                                    img.save(b_io, 'JPEG', quality=90)
                                    
                                    # Thread-safe image update
                                    with self._image_lock:
                                        self._last_image = b_io.getvalue()
                                    
                                    # Thread-safe temperature update
                                    with self._temp_lock:
                                        self._min_temp = min_temp
                                        self._max_temp = max_temp
                                    
                                    frame_count += 1
                                    if frame_count % 30 == 0:
                                        _LOGGER.debug("Processed %d frames successfully", frame_count)
                                        
                                except struct.error as e:
                                    _LOGGER.error("Failed to unpack frame data: %s", e)
                                    continue
                                except Exception as e:
                                    _LOGGER.error("Error processing frame: %s", e)
                                    continue
                        
                        except socket.timeout:
                            _LOGGER.warning("No data received for 60 seconds. Device may not be sending thermal stream.")
                            _LOGGER.warning("Check: 1) Is device powered on? 2) USB connected (for sensor initialization)? 3) Thermal camera firmware running?")
                            _LOGGER.warning("Try power-cycling the device or checking ESP32 serial logs for errors. Reconnecting...")
                            break
                        except Exception as e:
                            _LOGGER.error("Socket recv error: %s", e)
                            break
                            
            except Exception as e:
                _LOGGER.error("Error connecting to thermal camera: %s", e)
                if self._running:
                    _LOGGER.info("Reconnecting in %d seconds...", reconnect_delay)
                    time.sleep(reconnect_delay)
                    # Exponential backoff: increase delay up to max
                    reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)
                    reconnect_delay = int(reconnect_delay)

    def stop(self):
        """Stop the background thread."""
        self._running = False
        # Wait for thread to finish (max 5 seconds)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            _LOGGER.warning("Thermal camera thread did not stop cleanly")

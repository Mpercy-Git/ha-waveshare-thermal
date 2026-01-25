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
RAW_FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT * 2  # 80 * 62 * 2 = 9920 bytes? 
# Wait, wiki says 80x62. TCP Client js says 80x62.
# 80 * 62 = 4960 pixels.
# 4960 * 2 bytes = 9920 bytes.
# HOWEVER, tcpServerTask.c says:
# mMemcpySize = 80 * 64; //(80 words + 4 words)?? 
# mTxSize = 10256; 
# And: tcpServerSend((uint8_t*)senxorDataPtr, 80 * 64 * sizeof(uint16_t)); // 10240 bytes
# Client.js says:
# const FRAME_WIDTH = 80;
# const FRAME_HEIGHT = 62;
# const RAW_FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT * 2; // 9920
# Wait, client.js line 10 says: const RAW_FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT * 2; // 10240 bytes
# 80 * 62 * 2 = 9920. 
# 80 * 64 * 2 = 10240.
# The C code sends 80 * 64.  Let's trust the C code and the client.js comment (even if the math in the comment vs code is slightly off or implies padded lines).
# If the sensor is 80x62, maybe there are 2 dummy lines or it's actually 80x64.
# Let's use 80x64 for the buffer read to align with the C code send size (10240).

BUFFER_WIDTH = 80
BUFFER_HEIGHT = 62 # Corrected from 64 based on Protocol (80x62)
ACTUAL_HEIGHT = 62

PAYLOAD_SIZE = BUFFER_WIDTH * BUFFER_HEIGHT * 2 # 10240
HEADER_SIZE = 160  # STRIP_HEAD in client.js is 160?? client.js says 160.
FOOTER_SIZE = 160  # STRIP_TAIL in client.js.

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
        max_buffer_size = HEADER_SIZE + PAYLOAD_SIZE + FOOTER_SIZE * 10  # Allow buffering of up to 10 frames
        
        while self._running:
            try:
                # Open socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(10.0)  # Connection timeout
                    _LOGGER.info("Attempting to connect to %s:%s", self._host, self._port)
                    try:
                        s.connect((self._host, self._port))
                    except socket.timeout:
                        _LOGGER.error("Connection timed out to %s:%s after 30s. Check if device is powered on and port is correct.", self._host, self._port)
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
                    
                    # The firmware automatically starts streaming when a client connects.
                    # No startup command needed - just wait for data.
                    
                    # Buffer for incoming data
                    data_buffer = b""
                    
                    # Packet size matches client.js: Header + Payload + Footer
                    # 160 + 10240 + 160 = 10560
                    packet_size = HEADER_SIZE + PAYLOAD_SIZE + FOOTER_SIZE
                    frame_count = 0
                    
                    while self._running:
                        try:
                            chunk = s.recv(4096)
                            if not chunk:
                                _LOGGER.warning("Connection closed by remote host")
                                break
                            data_buffer += chunk
                            
                            # Prevent buffer overflow from misbehaving device
                            if len(data_buffer) > max_buffer_size:
                                _LOGGER.warning("Buffer overflow detected (%d bytes). Clearing buffer.", len(data_buffer))
                                data_buffer = b""
                                continue
                            
                            # Log buffer size periodically or on first packet (debug)
                            if len(data_buffer) < packet_size and len(data_buffer) > 0:
                                 pass # _LOGGER.debug("Buffering data: %d/%d bytes", len(data_buffer), packet_size)
                            
                            while len(data_buffer) >= packet_size:
                                # _LOGGER.debug("Processing frame, buffer size: %d", len(data_buffer))
                                # Extract one full frame
                                frame_packet = data_buffer[:packet_size]
                                data_buffer = data_buffer[packet_size:]
                                
                                try:
                                    # Parse Payload (skip header)
                                    raw_data = frame_packet[HEADER_SIZE : HEADER_SIZE + PAYLOAD_SIZE]
                                    
                                    # Validate data size
                                    if len(raw_data) != PAYLOAD_SIZE:
                                        _LOGGER.warning("Invalid payload size: %d, expected %d", len(raw_data), PAYLOAD_SIZE)
                                        continue
                                    
                                    # Convert to pixels
                                    pixels = []
                                    fmt = f"<{len(raw_data)//2}H" # Little-endian unsigned short
                                    values = struct.unpack(fmt, raw_data)
                                    
                                    # Values are 16-bit. 
                                    # The C code writes 80 * 64 words.
                                    # We only care about the first 62 lines for the image if the sensor is 80x62.
                                    # Or maybe the last 2 lines are garbage/metadata? 
                                    # Client.js uses 80*62*2 as RAW_FRAME_SIZE but reads from a stream that sends more?
                                    # Client.js: 
                                    #   RECEIVE BUFFER logic:
                                    #   const TCP_FRAME_SIZE = RAW_FRAME_SIZE + STRIP_HEAD + STRIP_TAIL; // 10560
                                    #   Wait, RAW_FRAME_SIZE in client.js is 10240??
                                    #     const RAW_FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT * 2; // 10240
                                    #     80 * 62 * 2 = 9920. 
                                    #     10240 / 2 / 80 = 64.
                                    #   So client.js defines HEIGHT=62 but calculates size as if HEIGHT=64?
                                    #   No, client.js line 10: "const RAW_FRAME_SIZE = FRAME_WIDTH * FRAME_HEIGHT * 2; // 10240 bytes"
                                    #   This comment is contradictory if W=80, H=62. 80*62*2 = 9920.
                                    #   Let's assume the STREAM sends 64 lines, and we can just visualize all of them or crop.
                                    
                                    min_val = min(values)
                                    max_val = max(values)
                                    
                                    # Create Image
                                    img = Image.new('RGB', (BUFFER_WIDTH, BUFFER_HEIGHT))
                                    pixels_rgb = [get_color(v, min_val, max_val) for v in values]
                                    img.putdata(pixels_rgb)
                                    
                                    # Crop if necessary (The wiki says 80x62)
                                    if ACTUAL_HEIGHT < BUFFER_HEIGHT:
                                        img = img.crop((0, 0, BUFFER_WIDTH, ACTUAL_HEIGHT))
                                    
                                    # Resize for better visibility in HA (Optional, but 80px is tiny)
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
                            _LOGGER.warning("No data received for 60 seconds. Device may not be sending thermal stream. Reconnecting...")
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

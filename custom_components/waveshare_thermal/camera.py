"""Camera platform for Waveshare Thermal Camera."""
import io
import logging
import socket
import struct
import threading
from collections import Counter
from threading import Lock

from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

BUFFER_WIDTH = 80
BUFFER_HEIGHT = 62  # Correct thermal resolution (not 63)
THERMAL_ROWS = BUFFER_HEIGHT - 1  # Row 0 is discarded, the firmware corrupts it

# Frame structure (final analysis):
# - 160-byte header: "   #2808GFRA" + 148 zeros
# - 9920 bytes thermal data: 80 * 62 * 2 bytes (little-endian uint16)
# - 176-byte tail: padding/checksum
# Total frame size: 10256 bytes
FRAME_HEADER_SIZE = 160
PAYLOAD_SIZE = BUFFER_WIDTH * BUFFER_HEIGHT * 2  # 9920 bytes
FRAME_TAIL_SIZE = 176
FRAME_SIZE = FRAME_HEADER_SIZE + PAYLOAD_SIZE + FRAME_TAIL_SIZE  # 10256 bytes total
FRAME_SYNC_PATTERN = b"   #2808GFRA" + (b"\x00" * 20)
DEFAULT_ROW_SHIFT = 19
AUTO_SHIFT_LEARN_FRAMES = 8

# Rendering
DISPLAY_SCALE = 4
DISPLAY_WIDTH = BUFFER_WIDTH * DISPLAY_SCALE  # 320
DISPLAY_HEIGHT = THERMAL_ROWS * DISPLAY_SCALE  # 244

# Reconnect behaviour
MIN_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60
THREAD_JOIN_TIMEOUT = 5

# Inferno-ish colormap (interpolated)
COLORMAP = [
    (0, 0, 4), (66, 10, 104), (147, 38, 103), (221, 81, 58), (252, 165, 10), (252, 255, 164)
]

def get_color(val, min_val, max_val):
    if max_val == min_val:
        norm = 0.5
    else:
        norm = max(0, min(1, (val - min_val) / (max_val - min_val)))
    
    # Map norm (0.0-1.0) to colormap
    idx = norm * (len(COLORMAP) - 1)
    i = min(int(idx), len(COLORMAP) - 2)
    f = idx - i

    c1 = COLORMAP[i]
    c2 = COLORMAP[i + 1]
    
    r = int(c1[0] + f * (c2[0] - c1[0]))
    g = int(c1[1] + f * (c2[1] - c1[1]))
    b = int(c1[2] + f * (c2[2] - c1[2]))
    return (r, g, b)


def circular_shift_row(row, shift):
    """Circularly shift a row to the right by shift columns."""
    if shift == 0:
        return row
    shift = shift % BUFFER_WIDTH
    return row[-shift:] + row[:-shift]


def estimate_best_shift(rows):
    """Estimate the column rotation that restores horizontal continuity.

    Every row arrives circularly rotated by the same unknown amount, so the
    true left/right edge of the scene sits somewhere in the middle of the
    frame as a vertical seam. Applying shift ``s`` pushes the boundary between
    raw columns ``j - 1`` and ``j`` (with ``j = (BUFFER_WIDTH - s) % BUFFER_WIDTH``)
    off the visible image, so the visible horizontal variation equals the row's
    circular total variation minus that one column pair. The circular total is
    identical for every shift, so the smoothest result is obtained by hiding
    the largest column-to-column jump.

    Row-to-row differences deliberately play no part: rotating every row by the
    same amount permutes the columns identically, so that term is invariant to
    ``s`` and cannot discriminate between candidate shifts.

    The estimate is only as good as the scene: if a real edge in view is a
    stronger discontinuity than the seam, that edge is hidden instead. Taking
    the mode over AUTO_SHIFT_LEARN_FRAMES frames and falling back to
    DEFAULT_ROW_SHIFT cover the ambiguous cases.
    """
    seam_strength = [0] * BUFFER_WIDTH
    for row in rows:
        for x in range(BUFFER_WIDTH):
            # The jump between columns x-1 and x is hidden by this shift.
            seam_strength[(BUFFER_WIDTH - x) % BUFFER_WIDTH] += abs(row[x - 1] - row[x])
    return max(range(BUFFER_WIDTH), key=seam_strength.__getitem__)


def _shutdown_socket(sock):
    """Unblock a socket that another thread may be blocked reading from."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        # Already closed or never connected - nothing to interrupt.
        pass


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform from config entry."""
    host = entry.options.get(CONF_HOST, entry.data[CONF_HOST])
    port = entry.options.get(CONF_PORT, entry.data.get(CONF_PORT, DEFAULT_PORT))
    name = entry.options.get(CONF_NAME, entry.data.get(CONF_NAME) or entry.title)

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
        self._attr_name = name
        self._host = host
        self._port = port
        self._attr_unique_id = unique_id
        self._last_image = self._create_placeholder_image()
        self._image_lock = Lock()  # Thread-safe image access
        self._min_temp = None
        self._max_temp = None
        self._temp_lock = Lock()  # Thread-safe temperature access
        self._row_shift = None
        self._shift_samples = []
        self._running = True
        self._stop_event = threading.Event()
        self._socket = None
        self._socket_lock = Lock()  # Guards the active socket reference
        # The worker is started from async_added_to_hass so that a failed
        # entity registration cannot leave an unreachable thread behind.
        self._thread = None

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

    async def async_added_to_hass(self):
        """Start the background reader once the entity is registered."""
        await super().async_added_to_hass()
        self._thread = threading.Thread(
            target=self._run_worker,
            name=f"ThermalCamera_{self._attr_name}",
            daemon=True,
        )
        self._thread.start()

    async def async_will_remove_from_hass(self):
        """Stop the background thread when entity is removed."""
        self.stop()

        thread = self._thread
        if thread is None:
            return

        # Join off the event loop; the worker can take a moment to unwind.
        await self.hass.async_add_executor_job(thread.join, THREAD_JOIN_TIMEOUT)
        if thread.is_alive():
            _LOGGER.warning("Thermal camera thread did not stop cleanly")

    def _create_placeholder_image(self):
        """Create a placeholder image."""
        try:
            img = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), color=(40, 44, 52))
            draw = ImageDraw.Draw(img)
            # Simple fallback if font loading fails, though default is usually fine
            draw.text((80, 110), "Connecting...", fill=(255, 255, 255))
            b_io = io.BytesIO()
            img.save(b_io, 'JPEG', quality=80)
            return b_io.getvalue()
        except Exception as e:
            _LOGGER.error("Error creating placeholder image: %s", e)
            return None

    def _register_socket(self, sock):
        """Track the active socket so stop() can interrupt a blocking recv."""
        with self._socket_lock:
            self._socket = sock

        if sock is not None and not self._running:
            # stop() may have run between the loop check and registration.
            _shutdown_socket(sock)

    def _run_worker(self):
        """Background thread to read from TCP stream."""
        reconnect_delay = MIN_RECONNECT_DELAY
        max_buffer_size = FRAME_SIZE * 10  # Allow buffering of up to 10 frames
        
        while self._running:
            # Tracks whether this attempt ever produced data, so that a device
            # accepting and immediately dropping connections backs off instead
            # of being reconnected to in a tight loop.
            healthy = False
            try:
                # Open socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    self._register_socket(s)
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
                        s.sendall(start_cmd)
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
                    
                    # Frame format: 160-byte header + 9920-byte thermal data + 176-byte tail = 10256 bytes
                    packet_size = FRAME_SIZE
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
                                healthy = True
                            
                            data_buffer += chunk
                            
                            # Prevent buffer overflow from misbehaving device
                            if len(data_buffer) > max_buffer_size:
                                _LOGGER.warning("Buffer overflow detected (%d bytes). Clearing buffer.", len(data_buffer))
                                data_buffer = b""
                                synchronized = False
                                continue
                            
                            # Find frame boundary if not synchronized
                            if not synchronized:
                                header_pos = data_buffer.find(FRAME_SYNC_PATTERN)
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
                                
                                # Validate frame header signature with marker + zero padding prefix
                                if not frame_packet.startswith(FRAME_SYNC_PATTERN):
                                    _LOGGER.warning("Frame header validation failed. Re-synchronizing...")
                                    synchronized = False
                                    # Search for next valid header
                                    header_pos = data_buffer.find(FRAME_SYNC_PATTERN, 1)
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
                                    # Skip 160-byte frame header and extract only thermal payload
                                    raw_data = frame_packet[FRAME_HEADER_SIZE:FRAME_HEADER_SIZE + PAYLOAD_SIZE]
                                    
                                    # Validate data size
                                    if len(raw_data) != PAYLOAD_SIZE:
                                        _LOGGER.warning("Invalid payload size: %d, expected %d", len(raw_data), PAYLOAD_SIZE)
                                        continue
                                    
                                    # Convert to pixels
                                    # Firmware sends 80x62 array (4960 uint16 values in little-endian)
                                    fmt = f"<{len(raw_data)//2}H"  # Little-endian unsigned short
                                    all_values = struct.unpack(fmt, raw_data)
                                    
                                    # Skip first row (row 0): device firmware has corrupted first row.
                                    thermal_values = all_values[BUFFER_WIDTH:]
                                    rows = [
                                        list(thermal_values[row_idx * BUFFER_WIDTH:(row_idx + 1) * BUFFER_WIDTH])
                                        for row_idx in range(THERMAL_ROWS)
                                    ]

                                    # Learn best shift for first few frames, then lock it.
                                    if self._row_shift is None:
                                        self._shift_samples.append(estimate_best_shift(rows))
                                        # Apply the running mode rather than this frame's
                                        # estimate, so the picture does not jitter while
                                        # the shift is still being learned.
                                        applied_shift = Counter(self._shift_samples).most_common(1)[0][0]
                                        if len(self._shift_samples) >= AUTO_SHIFT_LEARN_FRAMES:
                                            self._row_shift = applied_shift
                                            _LOGGER.info(
                                                "Locked thermal row shift to %d after %d samples",
                                                self._row_shift,
                                                len(self._shift_samples),
                                            )
                                    else:
                                        applied_shift = self._row_shift

                                    if applied_shift == 0 and DEFAULT_ROW_SHIFT:
                                        # Fallback for flat scenes where auto-detect can be ambiguous.
                                        applied_shift = DEFAULT_ROW_SHIFT

                                    corrected_rows = []
                                    for row in rows:
                                        corrected_rows.extend(circular_shift_row(row, applied_shift))
                                    values = corrected_rows
                                    
                                    # Filter out invalid values for temperature calculation:
                                    # - Zeros are sensor errors/missing pixels
                                    # - Values >= 10000 are outlier/hot pixels (< 0.1% of data)
                                    # Normal thermal range is roughly 2500-4000 raw (0-60°C)
                                    valid_values = [v for v in values if 0 < v < 10000]
                                    
                                    if not valid_values:
                                        # Every pixel is invalid. Publishing a synthetic
                                        # range here would push impossible temperatures
                                        # into long-term statistics, so drop the frame.
                                        _LOGGER.warning("Frame contained no valid thermal pixels. Skipping frame.")
                                        continue
                                    
                                    min_val = min(valid_values)
                                    max_val = max(valid_values)
                                    
                                    # Create Image from thermal data (row 0 skipped)
                                    img = Image.new('RGB', (BUFFER_WIDTH, THERMAL_ROWS))
                                    pixels_rgb = [get_color(v, min_val, max_val) for v in values]
                                    img.putdata(pixels_rgb)
                                    
                                    # Resize for better visibility in HA (maintain aspect ratio)
                                    img = img.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), resample=Image.NEAREST)
                                    
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
                        except OSError as e:
                            if not self._running:
                                # Socket was shut down by stop(); this is expected.
                                break
                            _LOGGER.error("Socket recv error: %s", e)
                            break
                        except Exception as e:
                            _LOGGER.error("Socket recv error: %s", e)
                            break
                            
            except Exception as e:
                if self._running:
                    _LOGGER.error("Error connecting to thermal camera: %s", e)
            finally:
                self._register_socket(None)

            if not self._running:
                break

            # Applies to every disconnect, not just those raising an exception:
            # a clean EOF or a read timeout must back off too.
            if healthy:
                reconnect_delay = MIN_RECONNECT_DELAY
            _LOGGER.info("Reconnecting in %d seconds...", reconnect_delay)
            self._stop_event.wait(reconnect_delay)
            if not healthy:
                # Exponential backoff: increase delay up to max
                reconnect_delay = min(int(reconnect_delay * 1.5), MAX_RECONNECT_DELAY)

    def stop(self):
        """Signal the background thread to stop and interrupt any blocking I/O."""
        self._running = False
        self._stop_event.set()

        with self._socket_lock:
            sock = self._socket
        if sock is not None:
            _shutdown_socket(sock)

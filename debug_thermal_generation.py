import struct
import io
from PIL import Image, ImageDraw

# Constants from camera.py
FRAME_WIDTH = 80
FRAME_HEIGHT = 62
BUFFER_WIDTH = 80
BUFFER_HEIGHT = 64
ACTUAL_HEIGHT = 62

PAYLOAD_SIZE = BUFFER_WIDTH * BUFFER_HEIGHT * 2 

COLORMAP = [
    (0, 0, 4), (66, 10, 104), (147, 38, 103), (221, 81, 58), (252, 165, 10), (252, 255, 164)
]

def get_color(val, min_val, max_val):
    if max_val == min_val:
        norm = 0.5
    else:
        norm = (val - min_val) / (max_val - min_val)
    
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

def generate_test_image():
    print("Generating dummy data...")
    # Create dummy raw data (gradient)
    values = []
    for y in range(BUFFER_HEIGHT):
        for x in range(BUFFER_WIDTH):
            # value between 0 and 65535
            val = int((x / BUFFER_WIDTH + y / BUFFER_HEIGHT) / 2 * 65535)
            values.append(val)
    
    # Pack into bytes (simulating what we read from socket)
    fmt = f"<{len(values)}H"
    raw_data = struct.pack(fmt, *values)
    
    print(f"Raw data size: {len(raw_data)} bytes")
    
    # Decode back (Simulating camera.py logic)
    print("Decoding data...")
    unpack_fmt = f"<{len(raw_data)//2}H"
    unpacked_values = struct.unpack(unpack_fmt, raw_data)
    
    min_val = min(unpacked_values)
    max_val = max(unpacked_values)
    
    print(f"Min: {min_val}, Max: {max_val}")
    
    img = Image.new('RGB', (BUFFER_WIDTH, BUFFER_HEIGHT))
    pixels_rgb = [get_color(v, min_val, max_val) for v in unpacked_values]
    img.putdata(pixels_rgb)
    
    if ACTUAL_HEIGHT < BUFFER_HEIGHT:
        img = img.crop((0, 0, BUFFER_WIDTH, ACTUAL_HEIGHT))
        
    img = img.resize((320, 248), resample=Image.NEAREST)
    
    draw = ImageDraw.Draw(img)
    min_temp = min_val * 0.0984 - 265.82
    max_temp = max_val * 0.0984 - 265.82
    
    text = f"Min: {min_temp:.1f}C  Max: {max_temp:.1f}C"
    draw.text((5, 5), text, fill=(255, 255, 255))
    
    b_io = io.BytesIO()
    img.save(b_io, 'JPEG', quality=90)
    result = b_io.getvalue()
    
    print(f"Generated JPEG size: {len(result)} bytes")
    
    with open("output_test.jpg", "wb") as f:
        f.write(result)
        
    print("Saved output_test.jpg")

if __name__ == "__main__":
    try:
        generate_test_image()
    except Exception as e:
        print(f"Error: {e}")

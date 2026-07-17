"""Build a Y4M video (fake webcam feed for Chromium) from a still test image."""
import os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "test_images", "test1.jpg")
OUT = os.path.join(HERE, "fakecam.y4m")
W, H, FRAMES = 960, 640, 90   # ~6s at 15fps

img = Image.open(SRC).convert("RGB").resize((W, H), Image.BILINEAR)
ycbcr = img.convert("YCbCr")
y, cb, cr = [np.asarray(ch) for ch in ycbcr.split()]
# 4:2:0 subsample chroma
cb420 = cb.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).astype(np.uint8)
cr420 = cr.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).astype(np.uint8)

with open(OUT, "wb") as f:
    f.write(f"YUV4MPEG2 W{W} H{H} F15:1 Ip A1:1 C420jpeg\n".encode())
    frame = b"FRAME\n" + y.tobytes() + cb420.tobytes() + cr420.tobytes()
    for _ in range(FRAMES):
        f.write(frame)
print(OUT, os.path.getsize(OUT), "bytes")

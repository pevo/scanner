"""Generate PWA icons: dark tile with a license-plate glyph."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
os.makedirs(OUT, exist_ok=True)

def make(size, path):
    img = Image.new("RGB", (size, size), "#0f1115")
    d = ImageDraw.Draw(img)
    # plate shape
    pw, ph = int(size * 0.72), int(size * 0.34)
    x0, y0 = (size - pw) // 2, (size - ph) // 2
    r = size // 24
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=r, fill="#e6e9ef",
                        outline="#3ddc84", width=max(2, size // 42))
    try:
        font = ImageFont.load_default(size=int(ph * 0.52))
    except TypeError:
        font = ImageFont.load_default()
    text = "ABC 123"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((x0 + (pw - tw) / 2 - bbox[0], y0 + (ph - th) / 2 - bbox[1]), text, fill="#0f1115", font=font)
    # viewfinder corners
    m, L, w = int(size * 0.08), int(size * 0.12), max(3, size // 36)
    for cx, cy, dx, dy in [(m, m, 1, 1), (size - m, m, -1, 1), (m, size - m, 1, -1), (size - m, size - m, -1, -1)]:
        d.line([cx, cy, cx + dx * L, cy], fill="#3ddc84", width=w)
        d.line([cx, cy, cx, cy + dy * L], fill="#3ddc84", width=w)
    img.save(path)
    print(path, img.size)

make(192, os.path.join(OUT, "icon-192.png"))
make(512, os.path.join(OUT, "icon-512.png"))
make(180, os.path.join(OUT, "apple-touch-icon.png"))

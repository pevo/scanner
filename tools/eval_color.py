"""Evaluate car-color classification on the test images using real detector boxes.
Mirrors the JS implementation exactly so tuned constants transfer 1:1."""
import os, math
import numpy as np
import tensorflow as tf
from PIL import Image

PLATE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # workspace root (parent of tools/)

det = tf.lite.Interpreter(model_path=os.path.join(PLATE, "yolox_plates_s_float32.tflite"))
det.allocate_tensors()

def detect(img):
    W = H = 640
    r = min(W / img.width, H / img.height)
    canvas = Image.new("RGB", (W, H), (114, 114, 114))
    canvas.paste(img.resize((round(img.width * r), round(img.height * r)), Image.BILINEAR), (0, 0))
    x = np.asarray(canvas, dtype=np.float32)[None]
    d = det.get_input_details()[0]
    det.set_tensor(d["index"], x)
    det.invoke()
    y = det.get_tensor(det.get_output_details()[0]["index"])[0]
    grids = [(gx, gy, s) for s in (8, 16, 32) for gy in range(640 // s) for gx in range(640 // s)]
    boxes = []
    for i in range(y.shape[0]):
        score = y[i, 4] * y[i, 5]
        if score < 0.3:
            continue
        gx, gy, s = grids[i]
        cx, cy = (y[i, 0] + gx) * s, (y[i, 1] + gy) * s
        w, h = math.exp(y[i, 2]) * s, math.exp(y[i, 3]) * s
        boxes.append([(cx - w/2)/r, (cy - h/2)/r, (cx + w/2)/r, (cy + h/2)/r, score])
    boxes.sort(key=lambda b: -b[4])
    keep = []
    for b in boxes:
        if all((max(0, min(b[2], k[2]) - max(b[0], k[0])) * max(0, min(b[3], k[3]) - max(b[1], k[1]))) /
               ((b[2]-b[0])*(b[3]-b[1]) + (k[2]-k[0])*(k[3]-k[1]) + 1e-9) < 0.3 for k in keep):
            keep.append(b)
    return keep

# ---------------- color classifier (tune here, port to JS verbatim) ----------------
CHROMA_MIN = 34          # absolute chroma (0-255, after WB) below which a pixel is achromatic
SAT_MIN = 0.25           # relative saturation floor for a "colored" pixel
COLORED_FRACTION = 0.30  # fraction of pixels that must be colored to call a hue
V_BLACK, V_GRAY, V_SILVER = 0.32, 0.58, 0.82
GAIN_CLAMP = (0.7, 1.5)  # gray-world white-balance gain limits

HUES = [(15, 'red'), (45, 'orange'), (70, 'yellow'), (170, 'green'), (260, 'blue'), (345, 'purple'), (361, 'red')]

def wb_gains(img):
    """Gray-world illuminant estimate from the FULL frame -> per-channel gains."""
    small = np.asarray(img.resize((32, 32), Image.BILINEAR), dtype=float).reshape(-1, 3)
    means = small.mean(axis=0) + 1e-6
    gray = means.mean()
    return np.clip(gray / means, *GAIN_CLAMP)

def classify_pixels(px, gains):
    """px: [N,3] uint8, gains: [3]. Returns color name (JS port target)."""
    hue_w, hue_n = {}, {}
    achro_v = []
    for pr, pg, pb in px.astype(float):
        r = min(255, pr * gains[0]); g = min(255, pg * gains[1]); b = min(255, pb * gains[2])
        mx, mn = max(r, g, b), min(r, g, b)
        v = mx / 255
        chroma = mx - mn
        s = chroma / mx if mx else 0
        if v > 0.96 and chroma < 40:
            continue                              # specular highlight — ignore
        if chroma < CHROMA_MIN or s < SAT_MIN:
            achro_v.append(v)
            continue
        d = chroma
        if mx == r: h = ((g - b) / d) % 6
        elif mx == g: h = (b - r) / d + 2
        else: h = (r - g) / d + 4
        h *= 60
        if h < 0: h += 360
        name = next(nm for lim, nm in HUES if h < lim)
        hue_w[name] = hue_w.get(name, 0) + 1 + chroma / 64
        hue_n[name] = hue_n.get(name, 0) + 1
        globals().setdefault('_chroma_sum', {}).setdefault(name, []).append(chroma)
    colored = sum(hue_n.values())
    total = colored + len(achro_v)
    if total == 0:
        return None, {}
    if colored >= COLORED_FRACTION * total:
        best = max(hue_w, key=hue_w.get)
        dbg = {"colored%": round(100*colored/total),
               "hues": {k: (hue_n[k], round(float(np.mean(globals()['_chroma_sum'][k])))) for k in sorted(hue_n, key=hue_n.get, reverse=True)[:3]}}
        globals()['_chroma_sum'] = {}
        return best, dbg
    globals()['_chroma_sum'] = {}
    vm = float(np.median(achro_v))
    name = 'black' if vm < V_BLACK else 'gray' if vm < V_GRAY else 'silver' if vm < V_SILVER else 'white'
    return name, {"colored%": round(100*colored/total), "v_med": round(vm, 2)}

def sample_bands(img, box):
    x1, y1, x2, y2, _ = box
    pw, ph = x2 - x1, y2 - y1
    out = []
    for (ax1, ay1, ax2, ay2) in [
        (x1 - pw*0.15, y1 - ph*2.0, x2 + pw*0.15, y1 - ph*0.4),   # body above plate
        (x1 - pw*0.15, y2 + ph*0.3, x2 + pw*0.15, y2 + ph*1.5),   # bumper below plate
        (x1 - pw*0.85, y1 - ph*0.5, x1 - pw*0.10, y2 + ph*0.5),   # body left of plate
        (x2 + pw*0.10, y1 - ph*0.5, x2 + pw*0.85, y2 + ph*0.5),   # body right of plate
    ]:
        ax1, ay1 = max(0, ax1), max(0, ay1)
        ax2, ay2 = min(img.width, ax2), min(img.height, ay2)
        if ax2 - ax1 < 8 or ay2 - ay1 < 4:
            continue
        band = img.crop((ax1, ay1, ax2, ay2)).resize((32, 12), Image.BILINEAR)
        out.append(np.asarray(band).reshape(-1, 3))
    return np.concatenate(out) if out else None

TRUTH = {  # acceptable answers per image (visual ground truth)
    "test1.jpg": ["silver", "gray", "blue"],   # Mazda CX-5, muted blue-gray
    "test2.jpg": ["silver", "gray", "white"],  # silver Saab
    "test3.jpg": ["red"],                      # dark red Subaru
    "test4.jpg": ["green"],                    # bright green McLaren
    "test5.jpg": ["white", "silver"],          # white Lexus
    "test6.webp": ["gray", "black", "silver"], # dark gray Honda + gray Audi
}

for name in sorted(os.listdir(os.path.join(PLATE, "test_images"))):
    img = Image.open(os.path.join(PLATE, "test_images", name)).convert("RGB")
    gains = wb_gains(img)
    for box in detect(img):
        px = sample_bands(img, box)
        if px is None:
            continue
        color, dbg = classify_pixels(px, gains)
        ok = "OK  " if color in TRUTH.get(name, []) else "MISS"
        print(f"{ok} {name} box@{box[0]:.0f},{box[1]:.0f}: {color:8} {dbg}")

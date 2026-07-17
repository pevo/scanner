"""Full two-stage ALPR pipeline offline: detector + OCR tflite, mirroring alpr-demo.html.
Usage: python plate_harness.py [image ...]   (defaults to all test_images)"""
import os, sys, math
import numpy as np
import tensorflow as tf
from PIL import Image

PLATE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # workspace root (parent of tools/)
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"

det = tf.lite.Interpreter(model_path=os.path.join(PLATE, "yolox_plates_s_float32.tflite"))
det.allocate_tensors()
ocr = tf.lite.Interpreter(model_path=os.path.join(PLATE, "cct_s_ocr_float32.tflite"))
ocr.allocate_tensors()

def detect(img):
    W = H = 640
    r = min(W / img.width, H / img.height)
    canvas = Image.new("RGB", (W, H), (114, 114, 114))
    canvas.paste(img.resize((round(img.width * r), round(img.height * r)), Image.BILINEAR), (0, 0))
    x = np.asarray(canvas, dtype=np.float32)[None]          # [1,640,640,3] RGB 0-255
    d = det.get_input_details()[0]
    det.set_tensor(d["index"], x)
    det.invoke()
    y = det.get_tensor(det.get_output_details()[0]["index"])[0]  # [8400,6]

    grids = []
    for s in (8, 16, 32):
        g = 640 // s
        for gy in range(g):
            for gx in range(g):
                grids.append((gx, gy, s))
    boxes = []
    for i in range(y.shape[0]):
        score = y[i, 4] * y[i, 5]
        if score < 0.3:
            continue
        gx, gy, s = grids[i]
        cx, cy = (y[i, 0] + gx) * s, (y[i, 1] + gy) * s
        w, h = math.exp(y[i, 2]) * s, math.exp(y[i, 3]) * s
        boxes.append([(cx - w / 2) / r, (cy - h / 2) / r, (cx + w / 2) / r, (cy + h / 2) / r, score])
    boxes.sort(key=lambda b: -b[4])
    keep = []
    for b in boxes:
        ok = True
        for k in keep:
            ix1, iy1 = max(b[0], k[0]), max(b[1], k[1])
            ix2, iy2 = min(b[2], k[2]), min(b[3], k[3])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = (b[2]-b[0])*(b[3]-b[1]) + (k[2]-k[0])*(k[3]-k[1]) - inter
            if inter / (union + 1e-9) > 0.45:
                ok = False
                break
        if ok:
            keep.append(b)
    return keep

def read_plate(img, box, margin):
    x1, y1, x2, y2, _ = box
    mw, mh = (x2 - x1) * margin, (y2 - y1) * margin
    crop = img.crop((max(0, x1 - mw), max(0, y1 - mh),
                     min(img.width, x2 + mw), min(img.height, y2 + mh)))
    g = crop.convert("L").resize((140, 70), Image.BILINEAR)
    x = np.asarray(g, dtype=np.float32)[None, :, :, None]
    d = ocr.get_input_details()[0]
    ocr.set_tensor(d["index"], x)
    ocr.invoke()
    y = ocr.get_tensor(ocr.get_output_details()[0]["index"]).reshape(8, 37)
    idx = y.argmax(axis=1)
    text = "".join(ALPHABET[i] for i in idx if ALPHABET[i] != "_")
    conf = min((y[s, i] for s, i in enumerate(idx) if ALPHABET[i] != "_"), default=0)
    return text, conf

images = sys.argv[1:] or sorted(
    os.path.join(PLATE, "test_images", f) for f in os.listdir(os.path.join(PLATE, "test_images")))
for path in images:
    img = Image.open(path).convert("RGB")
    dets = detect(img)
    print(f"\n=== {os.path.basename(path)} ({img.width}x{img.height}) — {len(dets)} plate(s) ===")
    for b in dets:
        print(f"  box ({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f}) score {b[4]:.2f}")
        for m in (0.0, 0.05, 0.10, 0.15):
            text, conf = read_plate(img, b, m)
            print(f"    margin {int(m*100):>2}% -> {text!r:12} (min conf {conf:.3f})")

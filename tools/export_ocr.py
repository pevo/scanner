"""Export autolane/cct-s-ocr-alpr Keras checkpoint -> ONNX -> float32 TFLite, then verify
on the actual plate crop from test1.jpg (ground truth: AAA000)."""
import os, sys

SCRATCH = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRATCH)

import numpy as np
import keras

# importing registers fast-plate-ocr's custom layers (MaxBlurPooling2D, DyT, ...)
import fast_plate_ocr.train.model.layers  # noqa: F401

import json
import tensorflow as tf

model = keras.models.load_model("ocr_best_checkpoint.keras", compile=False)
print("=== KERAS MODEL ===")
print("inputs :", [(t.name, t.shape, t.dtype) for t in model.inputs])
out = model.output
print("outputs:", out if not hasattr(out, "shape") else (out.name, out.shape, out.dtype))

# rebuild with float32 policy: fp16 GELU lowers to Erfc, which neither TFLite
# nor onnx2tf implements. Mixed-precision master weights are float32 already.
cfg_json = model.to_json().replace("mixed_float16", "float32")
model32 = keras.models.model_from_json(cfg_json)
model32.set_weights(model.get_weights())

# sanity: same result on a random input
probe = np.random.randint(0, 255, size=(1, 70, 140, 1)).astype(np.float32)
d = float(np.abs(model.predict(probe, verbose=0) - model32.predict(probe, verbose=0)).max())
print(f"float32 rebuild max deviation vs original: {d:.5f}")
assert d < 0.01, "float32 rebuild diverges from checkpoint"

# --- direct Keras -> TFLite (float32, batch fixed to 1 for LiteRT.js) ---
out_dir = os.path.join(SCRATCH, "ocr_out", "tflite")
os.makedirs(out_dir, exist_ok=True)

# pin batch=1 at the Keras level so the tflite input is [1,70,140,1], not [-1,...]
x_in = keras.Input(shape=(70, 140, 1), batch_size=1, dtype="float32", name="input")
model_b1 = keras.Model(x_in, model32(x_in), name="cct_s_ocr_b1")

conv = tf.lite.TFLiteConverter.from_keras_model(model_b1)
tfl_path = os.path.join(out_dir, "cct_s_ocr_float32.tflite")
with open(tfl_path, "wb") as f:
    f.write(conv.convert())

conv16 = tf.lite.TFLiteConverter.from_keras_model(model_b1)
conv16.optimizations = [tf.lite.Optimize.DEFAULT]
conv16.target_spec.supported_types = [tf.float16]
tfl16_path = os.path.join(out_dir, "cct_s_ocr_float16.tflite")
with open(tfl16_path, "wb") as f:
    f.write(conv16.convert())

print("tflite files:", [(f, os.path.getsize(os.path.join(out_dir, f)))
                        for f in os.listdir(out_dir) if f.endswith(".tflite")])

# --- verify on the real plate crop from test1.jpg ---
from PIL import Image

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
PLATE_DIR = os.path.dirname(SCRATCH)   # workspace root (parent of tools/)

img = Image.open(os.path.join(PLATE_DIR, "test_images", "test1.jpg"))
# detection from the browser test: x1=390, y1=327, x2=624, y2=447 (+10% margin)
x1, y1, x2, y2 = 390, 327, 624, 447
mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
crop = img.crop((x1 - mx, y1 - my, x2 + mx, y2 + my)).convert("L").resize((140, 70), Image.BILINEAR)
x = np.asarray(crop, dtype=np.float32)[None, :, :, None]  # [1,70,140,1], raw 0-255

def decode(probs):
    probs = probs.reshape(8, 37)
    idx = probs.argmax(axis=1)
    text = "".join(ALPHABET[i] for i in idx)
    conf = probs.max(axis=1)
    return text, [round(float(c), 3) for c in conf]

for name in sorted(os.listdir(out_dir)):
    if not name.endswith(".tflite"):
        continue
    interp = tf.lite.Interpreter(model_path=os.path.join(out_dir, name))
    interp.allocate_tensors()
    inp_d, out_d = interp.get_input_details()[0], interp.get_output_details()[0]
    interp.set_tensor(inp_d["index"], x.astype(inp_d["dtype"]))
    interp.invoke()
    y = interp.get_tensor(out_d["index"])
    text, conf = decode(y)
    print(f"\n{name}: input {inp_d['shape']} {inp_d['dtype'].__name__}, output {out_d['shape']}")
    print("  read:", text, "conf:", conf)

"""Inspect the ONNX model, convert to float32 TFLite via onnx2tf, verify the result."""
import os, sys

SCRATCH = os.path.dirname(os.path.abspath(__file__))
ONNX_PATH = os.path.join(SCRATCH, "yolox_plates_s.onnx")
OUT_DIR = os.path.join(SCRATCH, "tflite_out")

# --- 1. inspect ONNX I/O ---
import onnx
m = onnx.load(ONNX_PATH)
print("=== ONNX I/O ===")
for t in m.graph.input:
    dims = [d.dim_value or d.dim_param for d in t.type.tensor_type.shape.dim]
    print("input :", t.name, dims)
for t in m.graph.output:
    dims = [d.dim_value or d.dim_param for d in t.type.tensor_type.shape.dim]
    print("output:", t.name, dims)

# --- 2. convert ---
# onnx2tf wants a calibration/test-data npy; its download is broken, but it
# checks cwd first — so generate a valid one locally.
import numpy as np
os.chdir(SCRATCH)
np.save("calibration_image_sample_data_20x128x128x3_float32.npy",
        np.random.rand(20, 128, 128, 3).astype(np.float32))

import onnx2tf
onnx2tf.convert(
    input_onnx_file_path=ONNX_PATH,
    output_folder_path=OUT_DIR,
    not_use_onnxsim=True,          # avoid extra dependency
    output_signaturedefs=True,
    non_verbose=True,
)

print("\n=== produced files ===")
for f in os.listdir(OUT_DIR):
    p = os.path.join(OUT_DIR, f)
    if os.path.isfile(p):
        print(f, os.path.getsize(p))

# --- 3. verify float32 tflite I/O + run on random input ---
import numpy as np
import tensorflow as tf

tfl = os.path.join(OUT_DIR, "yolox_plates_s_float32.tflite")
interp = tf.lite.Interpreter(model_path=tfl)
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]
print("\n=== TFLITE I/O ===")
print("input :", inp["name"], inp["shape"], inp["dtype"])
print("output:", out["name"], out["shape"], out["dtype"])

x = np.random.randint(0, 255, size=inp["shape"]).astype(np.float32)
interp.set_tensor(inp["index"], x)
interp.invoke()
y = interp.get_tensor(out["index"])
print("output stats: shape", y.shape, "min", float(y.min()), "max", float(y.max()))

"""Convert cct-s-v2-global ONNX -> float32 tflite (batch 1), verify on hard crops."""
import os
import numpy as np

SCRATCH = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRATCH)
ONNX = os.path.expanduser(r"~\.cache\fast-plate-ocr\cct-s-v2-global-model\cct_s_v2_global.onnx")
OUT = os.path.join(SCRATCH, "global_out")

import onnx
m = onnx.load(ONNX)
print("=== ONNX I/O ===")
for t in m.graph.input:
    print("input :", t.name, [d.dim_value or d.dim_param for d in t.type.tensor_type.shape.dim],
          t.type.tensor_type.elem_type)
for t in m.graph.output:
    print("output:", t.name, [d.dim_value or d.dim_param for d in t.type.tensor_type.shape.dim])

# onnx2tf assumes NCHW inputs; this ONNX is NHWC uint8, which it mangles.
# Surgery: new NCHW float32 input -> Cast(uint8) -> Transpose(0,2,3,1) -> old input tensor.
from onnx import helper, TensorProto

old_input = m.graph.input[0]
old_name = old_input.name                       # "input"
m.graph.input.remove(old_input)
new_input = helper.make_tensor_value_info("input_nchw", TensorProto.FLOAT, [1, 3, 64, 128])
m.graph.input.insert(0, new_input)
cast = helper.make_node("Cast", ["input_nchw"], ["input_nchw_u8"], to=TensorProto.UINT8)
tr = helper.make_node("Transpose", ["input_nchw_u8"], [old_name], perm=[0, 2, 3, 1])
m.graph.node.insert(0, cast)
m.graph.node.insert(1, tr)
onnx.checker.check_model(m)
import onnxslim
m = onnxslim.slim(m)
FIXED = os.path.join(SCRATCH, "cct_s_v2_global_nchw.onnx")
onnx.save(m, FIXED)
print("surgery + slim ok ->", FIXED)

np.save("calibration_image_sample_data_20x128x128x3_float32.npy",
        np.random.rand(20, 128, 128, 3).astype(np.float32))
import onnx2tf
onnx2tf.convert(
    input_onnx_file_path=FIXED,
    output_folder_path=OUT,
    not_use_onnxsim=True,
    non_verbose=True,
    disable_strict_mode=True,
    batch_size=1,
)
print("files:", [(f, os.path.getsize(os.path.join(OUT, f)))
                 for f in os.listdir(OUT) if f.endswith(".tflite")])

# --- verify on the hard crops ---
import tensorflow as tf
from PIL import Image

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
PLATE = os.path.dirname(SCRATCH)   # workspace root (parent of tools/)
CASES = [
    ("test2.jpg", (894, 311, 1111, 440), "10000A"),
    ("test6.webp", (810, 811, 850, 832), "9BUE100"),
    ("test1.jpg", (390, 328, 624, 447), "AAA000"),
]

for name in sorted(f for f in os.listdir(OUT) if f.endswith(".tflite")):
    interp = tf.lite.Interpreter(model_path=os.path.join(OUT, name))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    outs = interp.get_output_details()
    print(f"\n{name}: input {inp['shape']} {inp['dtype'].__name__}")
    for o in outs:
        print("  output:", o["name"], o["shape"], o["dtype"].__name__)
    for img_name, (x1, y1, x2, y2), truth in CASES:
        img = Image.open(os.path.join(PLATE, "test_images", img_name)).convert("RGB")
        mw, mh = (x2 - x1) * 0.1, (y2 - y1) * 0.1
        crop = img.crop((max(0, x1 - mw), max(0, y1 - mh),
                         min(img.width, x2 + mw), min(img.height, y2 + mh)))
        crop = crop.resize((128, 64), Image.BILINEAR)
        x = np.asarray(crop)[None].astype(inp["dtype"])
        interp.set_tensor(inp["index"], x)
        interp.invoke()
        plate_out = next(interp.get_tensor(o["index"]) for o in outs
                         if o["shape"][-1] == 37)
        probs = plate_out.reshape(-1, 37)
        idx = probs.argmax(axis=1)
        text = "".join(ALPHABET[i] for i in idx if ALPHABET[i] != "_")
        conf = min((probs[s, i] for s, i in enumerate(idx) if ALPHABET[i] != "_"), default=0)
        ok = "OK " if text == truth else "MISS"
        print(f"  {ok} {img_name}: {text!r} vs {truth!r} (min conf {conf:.3f})")

# ALPR project tools

Development/maintenance scripts for the plate scanner. All paths are relative to this
folder's parent (the workspace root), so the folder can move with the project.

## One-time setup

**Python** (3.11 — TensorFlow does not support 3.14):

```powershell
py -3.11 -m venv venv
venv\Scripts\python -m pip install tensorflow tf_keras ai_edge_litert onnx onnx2tf onnxslim onnxruntime pillow "fast-plate-ocr[train]"
```

**Node** (for the browser tests):

```powershell
npm install playwright
npx playwright install chromium
```

The browser tests expect the workspace served at `http://localhost:8123`
(`python -m http.server 8123` in the workspace root).

## Evaluation / debugging

| Script | What it does |
|---|---|
| `plate_harness.py` | Runs the full two-stage pipeline (detector + OCR tflite) offline on every image in `test_images/`, with a crop-margin sweep. First stop when a plate reads wrong. |
| `eval_color.py` | Car-color classifier evaluation on the test images, with per-hue chroma debug output. **Mirrors the constants in `index.html` — if you tune here, port the constants back, and vice versa.** Ground truths are in the `TRUTH` dict. |
| `make_y4m.py` | Builds `fakecam.y4m` (a fake webcam feed) from `test_images/test1.jpg`, used by the browser tests. Regenerate before first test run (~80 MB, not stored). |

## Browser tests (Playwright, headless)

| Script | What it does |
|---|---|
| `test-scanner.js` | End-to-end scanner suite (18 checks): fake camera + fake GPS → detection, OCR, color, DB insert, dedup window, seen-before toasts, notes, CSV import/merge. Run after any change to `index.html`. Needs `fakecam.y4m` (see `make_y4m.py`). |
| `test-dbheal.js` | IndexedDB migration robustness: legacy v1 DB, half-migrated DB, healthy DB — verifies the app self-heals and never hangs at "Loading…". |
| `test-alpr.js` | Drives `alpr-demo.html` over all test images and prints detection + OCR results. Optional arg: `node test-alpr.js webgpu` to attempt the WebGPU backend. |

```powershell
node test-scanner.js
```

## Model conversion (only needed to re-export models)

| Script | What it does |
|---|---|
| `convert.py` | Detector: YOLOX ONNX → float32/float16 tflite via onnx2tf. Expects `yolox_plates_s.onnx` next to the script (download from huggingface.co/autolane/yolox-s-alpr). Output is NHWC. |
| `convert_global.py` | OCR (primary): fast-plate-ocr `cct-s-v2-global` ONNX → tflite. Includes the required graph surgery (NCHW input + transpose) and onnxslim pass — onnx2tf mangles the model without it. Reads the ONNX from `~/.cache/fast-plate-ocr/` (populated by running fast-plate-ocr once, see `eval` scripts). Verifies against known plates. |
| `export_ocr.py` | OCR (fallback): autolane `cct-s-ocr-alpr` Keras checkpoint → tflite. Includes the float32-policy rebuild (the fp16 checkpoint's GELU produces an `Erfc` op tflite can't run) and the batch=1 pin LiteRT.js requires. Expects `ocr_best_checkpoint.keras` + `ocr_plate_config.yaml` next to the script (from huggingface.co/autolane/cct-s-ocr-alpr). |
| `make_icons.py` | Regenerates the PWA icons in `../icons/`. |

## Hard-won conversion gotchas (details in the scripts)

- LiteRT.js only supports float32/int32 (and uint8) tensor I/O — int8-I/O tflite files won't load.
- LiteRT.js rejects dynamic batch dims (`[-1,...]`); pin batch=1 at export.
- `TFLiteConverter.from_concrete_functions` leaves unfrozen `READ_VARIABLE` ops — use
  `from_keras_model` with a `keras.Input(batch_size=1)` wrapper instead.
- onnx2tf assumes NCHW ONNX inputs; NHWC-input ONNX needs the surgery in `convert_global.py`.
- onnx2tf's calibration-data download is broken; the scripts generate
  `calibration_image_sample_data_20x128x128x3_float32.npy` locally to satisfy it.

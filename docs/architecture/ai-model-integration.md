# AI model integration

## Pipeline

```
csi_labeler (COM11, 921600)  ->  index.csv + raw/*.csv
        |
        v
ai/notebooks/train_esp32s3_6class.ipynb  (Kaggle, TensorFlow)
        |
        v
model.tflite + model_data.h + model_info.json + labels.json + metrics.json
        |
        v
firmware/common/infer.c  (TFLite Micro)
```

The agent does not train the model. The user collects fall trials, uploads the
zipped `index.csv` + `raw/` folder as a Kaggle dataset, runs the notebook, and
returns the output zip.

## Model contract

| Item | Value |
| --- | --- |
| Input | `250 × 192` float32 (one CSI window) |
| Normalization | per-window, per-subcarrier z-score: `(x - mean) / (std + 1e-6)` |
| Labels order | `empty, walk, sit, stand, lie, fall` |
| Output | 6-class softmax |
| Runtime | TFLite Micro, int8 input/output |
| Size target | ≤ 200 KB |
| Latency target | ≤ 100 ms on ESP32-S3 |

The firmware window is `csi_window_t` (`CSI_WINDOW_PACKETS = 250`,
`CSI_MAX_SUBCARRIERS = 192`), filled by `csi_window_push()` in packet order.
Amplitudes are stored as `uint8_t` (`sqrt(imag² + real²)`, gain-compensated,
clipped to 255). `csi_window_copy()` returns 250×192 bytes ready for
normalization.

`model_data.h` from the notebook contains:

```c
__attribute__((aligned(8)))
const unsigned char model_data[] = { ... };
const unsigned int model_data_len = ...;
```

`model_info.json` also carries `input_quant` and `output_quant`
(`scale`, `zero_point`, `dtype`) needed for int8 conversion.

## Integration steps

1. Copy the notebook's `model_data.h` over
   `firmware/common/include/model_data.h` (`infer.c` lives in the common
   component, so the header belongs there, not in the node's `main/`).
2. Add the component with `idf.py add-dependency "esp-tflite-micro"` (or add it
   to `firmware/esp32-csi-node/main/idf_component.yml`), then add it to the
   common component requirements:

   ```cmake
   idf_component_register(
       SRCS "csi_ring.c" "csi_features.c" "infer.c" "tb_client.c"
       INCLUDE_DIRS "include"
       REQUIRES esp_wifi esp_ringbuf mqtt json mbedtls esp_timer esp-tflite-micro
   )
   ```
3. Implement `infer_init()` and `infer_run()` in
   `firmware/common/infer.c`:
   - create the interpreter once, allocate a tensor arena (start at 64 KB,
     tune from the log);
   - copy the window with `csi_window_copy()`;
   - z-score each subcarrier over the 250 packets;
   - quantize to int8 with `input_quant`;
   - `invoke()`, dequantize the 6 outputs with `output_quant`;
   - set `state` to the argmax label, `presence = state != "empty"`,
     `fall = state == "fall" && prob >= 0.80`,
     `fall_score = prob[5]`, `model_ok = true`.
4. Keep the rule-based path as a fallback when `infer_init()` returns `false`
   (already the current behavior) so the node still reports `warmup` / `empty` /
   `motion`.
5. Rebuild and flash. Check `model_ok:1` in the `INFER` line and that the
   `state` values match `labels.json`.

## Accuracy risks to validate

- The notebook trains on serial CSV amplitudes; the firmware recomputes
  amplitudes from raw int8 I/Q with the same gain compensation, but stores them
  as rounded `uint8`. Verify by replaying one held-out CSV through both paths
  and comparing predictions.
- Training uses stride 125 (50% overlap); the device runs a new window every
  `INFER_PERIOD_MS` (1 s). This only changes decision cadence, not the input
  distribution.
- PCA is disabled by default (`USE_PCA = False`). If it is enabled, the PCA mean
  and components in `model_info.json` must be applied on-device before
  quantization.
- Per-window z-score removes absolute gain; do not add extra global scaling on
  the device.

## Acceptance gate (from the notebook)

- Fall recall ≥ 0.90, precision ≥ 0.85
- False alarms ≤ 1/hour on `empty`
- Macro F1 ≥ 0.85
- int8 accuracy drop ≤ 2% vs Keras
- Held-out subject/room split
- `deployable: true` in `model_info.json`

# wifi-csi-eldercare

WiFi-CSI fall and activity monitoring for elderly care, built on two ESP32-S3
boards, an on-device TFLite model, and ThingsBoard Cloud.

```
ESP32-S3 TX (COM7) --ESP-NOW--> ESP32-S3 RX (COM11)
                                      |
                     UART 921600: CSI_DATA + INFER
                                      |
                 +--------------------+--------------------+
                 |                                         |
        tools/csi_labeler                      tools/tb_bridge
        (training data)                        (ThingsBoard MQTT)
                 |                                         |
        Kaggle notebook --> model_data.h          thingsboard.cloud
                 |
        on-device inference (pending)
```

## Repository layout

| Path | Contents |
| --- | --- |
| `firmware/common` | CSI ring buffer, features, inference stub, MQTT client |
| `firmware/esp32-csi-node` | RX firmware: CSI capture, 1 Hz inference, UART/MQTT |
| `firmware/esp32-csi-sender` | TX firmware: ESP-NOW frame source |
| `tools/csi_labeler` | GUI recorder for labelled CSI trials |
| `tools/tb_bridge` | Serial-to-ThingsBoard bridge (interim path) |
| `ai/notebooks` | Kaggle 6-class training notebook |
| `docs` | Setup, telemetry, runbook, AI integration, collection protocol |

## Quick start

```powershell
. C:\esp\v5.5.6\esp-idf\export.ps1

cd firmware\esp32-csi-sender
idf.py -p COM7 flash

cd ..\esp32-csi-node
idf.py -p COM11 flash

cd ..\..\tools\tb_bridge
Copy-Item .env.example .env
# put TB_TOKEN in .env
.\.venv\Scripts\python tb_bridge.py --dry-run
.\.venv\Scripts\python tb_bridge.py
```

Full sequence: `docs/architecture/end-to-end-runbook.md`.
Data collection: `docs/data/collection-protocol.md`.

## Status

- TX/RX firmware build and flash; RX verified on hardware: `CSI_DATA` +
  `INFER` at ~73 pps, `csi_len=384`, no ring drops.
- Bridge parses real serial output and prints quota-safe telemetry in
  `--dry-run`; cloud publish needs `TB_TOKEN`.
- Direct ESP32 MQTT mode is implemented but blocked by the lack of a 2.4 GHz AP.
- TFLite model is not integrated yet: `common/infer.c` is a motion-threshold
  fallback, and `common/include/model_data.h` is a placeholder. This waits for
  fall data and the Kaggle run.

## Models and data

- Classes: `empty, walk, sit, stand, lie, fall`.
- Input: 250 packets × 192 subcarriers, per-window z-score, int8 TFLite.
- Acceptance: fall recall ≥ 0.90, precision ≥ 0.85, ≤ 1 false alarm/hour,
  macro F1 ≥ 0.85.
- Raw CSI and datasets are never uploaded to ThingsBoard (quota: 5 keys/15 s).

## Notes

- Never commit `.env`, `sdkconfig`, tokens, datasets, or model binaries.
- Fall trials are simulated only on a soft mat with an assistant present.
- ThingsBoard free tier: 5 devices, 1M data points/month, 30-day retention.

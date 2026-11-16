# esp32-csi-node

RX node for the WiFi-CSI eldercare system. It receives ESP-NOW frames from
`esp32-csi-sender`, extracts CSI, and either:

- **UART mode (default):** prints `CSI_DATA` CSV + `INFER` JSON on UART0 at
  921600 baud for `tools/tb_bridge` and `tools/csi_labeler`.
- **WiFi + MQTT mode:** joins a 2.4 GHz AP and publishes features to
  ThingsBoard Cloud directly.

## Build

```powershell
. C:\esp\v5.5.6\esp-idf\export.ps1
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p COM11 flash monitor
```

In `menuconfig` set `ElderCare CSI Node -> Output mode`, the WiFi channel, the
ThingsBoard host/port/token, and the 2.4 GHz SSID/password.

The sender must use the same channel. In WiFi mode the channel must also match
the AP channel.

## Notes

- Flash size is 16 MB, partition table is `partitions.csv`.
- Raw CSI is not uploaded. Only 5 telemetry keys every 15 s by default.
- The TFLite model is not integrated yet; `infer.c` uses a motion threshold
  fallback. Replace `common/include/model_data.h` and wire `tflite-micro` after
  the Kaggle notebook produces a quantized model.

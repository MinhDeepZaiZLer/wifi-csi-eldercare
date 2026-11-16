# Firmware

Two ESP32-S3 projects share one component:

```
esp32-csi-sender (COM7)  --ESP-NOW-->  esp32-csi-node (COM11)
                                            |
                          UART 921600: CSI_DATA CSV + INFER JSON
                                            |
                        tools/csi_labeler  or  tools/tb_bridge
```

The node can also join a 2.4 GHz AP and publish telemetry directly to
ThingsBoard (WiFi + MQTT mode).

## Layout

| Path | Purpose |
| --- | --- |
| `common/` | Ring buffer, CSI window/features, inference stub, ThingsBoard MQTT client |
| `common/include/model_data.h` | Placeholder for the TFLite model exported by the notebook |
| `esp32-csi-node/` | RX node: CSI capture, gain compensation, 1 Hz inference, UART/MQTT output |
| `esp32-csi-sender/` | TX node: sets MAC `1a:00:00:00:00:00`, broadcasts ESP-NOW frames |

## Build and flash

```powershell
. C:\esp\v5.5.6\esp-idf\export.ps1

cd firmware\esp32-csi-sender
idf.py build
idf.py -p COM7 flash

cd ..\esp32-csi-node
idf.py build
idf.py -p COM11 flash
```

Verified: sender 719,776 B (53% free in 1.5 MB), node 728,448 B (77% free in
3 MB OTA slot). Both targets are `esp32s3`, 16 MB flash, IDF 5.5.6.

## Configuration

`idf.py menuconfig` → **ElderCare CSI Node**:

| Option | Default | Notes |
| --- | --- | --- |
| Output mode | UART (PC bridge) | switch to WiFi + MQTT only with a 2.4 GHz AP |
| Emit CSI_DATA CSV | on | needed by `csi_labeler`; can be off for bridge-only demos |
| WiFi channel | 11 | must match sender and, in WiFi mode, the AP |
| Inference period | 1000 ms | |
| ThingsBoard host/port | `thingsboard.cloud:1883` | token required for MQTT mode |
| Telemetry interval | 15 s | quota-safe (5 keys) |
| WiFi SSID/password | empty | 2.4 GHz only |

`ElderCare CSI Sender`: `WiFi channel` (11) and `ESP-NOW send rate`
(default 100 Hz; UART throughput limits the observed rate to ~70 pps).

The node console is configured as **custom UART0 at 921600** in
`sdkconfig.defaults`. A plain `CONFIG_ESP_CONSOLE_UART_BAUDRATE` alone is
ignored because the baud prompt only exists in custom mode.

## Behaviour

- RX accepts only CSI from MAC `1a:00:00:00:00:00`.
- CSI length must be exactly 384 bytes (HT40, 192 subcarriers).
- Amplitudes are gain-compensated, then stored as `uint8` in a 250×192 window.
- `INFER` line example:

  ```json
  INFER,{"rssi":-42.0,"pps":73.4,"motion":0.0312,"presence":1,"state":"walk",
         "fall":0,"score":0.0,"model_ok":0,"csi_len":384,"total":1390,"dropped":0}
  ```

- Until the model is integrated, `state` is `warmup`, `empty`, or `motion` and
  `model_ok` is 0. `fall` is never raised by the fallback.

## Partitions

`esp32-csi-node/partitions.csv`: 16 MB, `nvs` 0x9000/0x6000, `otadata`
0xf000/0x2000, `phy_init` 0x11000/0x1000, two 3 MB OTA slots, 1 MB `storage`.
The sender uses `CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE`.

## Documentation

- `docs/architecture/end-to-end-runbook.md`
- `docs/architecture/ai-model-integration.md`
- `docs/architecture/telemetry-schema.md`
- `docs/architecture/thingsboard-setup.md`
- `docs/data/collection-protocol.md`

# ThingsBoard serial bridge

Reads `INFER` lines from the ESP32-S3 CSI node over USB serial and publishes
aggregated telemetry to ThingsBoard over MQTT. Raw `CSI_DATA` lines are counted
for diagnostics but never uploaded (quota protection).

## Install

```powershell
cd tools\tb_bridge
py -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Configure

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

- `TB_TOKEN`: device access token from ThingsBoard (**do not commit**).
- `SERIAL_PORT`: receiver port, `COM11` by default.
- `TB_ROOM`, `TB_SUBJECT`: device/room shown on the dashboard.

## Run

Dry run (prints payloads, no MQTT connection, works with a plain serial monitor):

```powershell
.\.venv\Scripts\python tb_bridge.py --dry-run
```

Publish to ThingsBoard:

```powershell
.\.venv\Scripts\python tb_bridge.py
```

Override without touching `.env`:

```powershell
.\.venv\Scripts\python tb_bridge.py --port COM11 --interval 10 --token <TOKEN>
```

For TLS use `--tls` with `--mqtt-port 8883` (or `TB_TLS=1`). Use
`--duration 30` for a bounded test run.

## Tests

```powershell
.\.venv\Scripts\python -m unittest -v
```

The tests cover payload keys, interval gating, and single-fire fall events;
they do not need a board, token, or network.

## Telemetry contract

Every `TB_PUBLISH_INTERVAL_S` seconds (default 15 s):

```json
{
  "rssi": -42.0,
  "pps": 73.4,
  "motion": 0.0312,
  "presence": 1,
  "state": "walking",
  "csi_len": 384
}
```

On a `fall` rising edge only:

```json
{
  "event": "fall",
  "score": 0.93,
  "state": "fall",
  "motion": 0.41
}
```

Device attributes are published on connect:

```json
{"fw": "tb_bridge-0.1.0", "room": "room-01", "subject": "subject-01"}
```

Five telemetry keys every 15 s is about 864k data points/month, inside the
ThingsBoard free tier (1M points). Do not lower `--interval` below ~10 s for a
24/7 deployment.

## Firmware requirements

- Build the node in UART mode: `CONFIG_LINK_MODE_UART=y`,
  `CONFIG_UART_CSV_ENABLE` may be on or off (`INFER` lines are always emitted).
- Flash and open the serial port at 921600 baud.
- The bridge skips boot logs and malformed lines safely.

## Troubleshooting

- `serial error`: wrong port or the port is open in another program.
- `MQTT connect failed rc=4/5`: wrong token or token for another device.
- No `INFER` lines: node still warming up (`csi_window_ready` needs a full
  250-packet window) or no ESP-NOW sender on the same channel.
- Payloads look static: verify `CSI_DATA` rate with `--debug`.

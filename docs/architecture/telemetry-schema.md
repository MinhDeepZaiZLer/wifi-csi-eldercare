# Telemetry schema

## MQTT connection

| Field | Value |
| --- | --- |
| Broker | `thingsboard.cloud` |
| Port | `1883` (plain) / `8883` (TLS) |
| Client id | `tb-bridge-<subject>` (bridge) or ESP32 MAC (firmware) |
| Username | device access token |
| Password | empty |
| Telemetry topic | `v1/devices/me/telemetry` |
| Attributes topic | `v1/devices/me/attributes` |
| QoS | 1 |

## Periodic telemetry

One message every `TB_PUBLISH_INTERVAL_S` (default 15 s), five keys to stay
inside the free-tier quota:

| Key | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `rssi` | float | dBm | RSSI of the last received CSI packet |
| `pps` | float | packets/s | CSI packets received during the last inference period |
| `motion` | float | 0..1 | Mean absolute amplitude change over the 250×192 window, divided by 255 |
| `presence` | int | 0/1 | `1` when `motion > 0.02` (fallback) or when the model says a person is present |
| `state` | string | - | See state values below |
| `csi_len` | int | bytes | CSI payload length, `384` for HT40 on ESP32-S3 |

Example:

```json
{
  "rssi": -42.0,
  "pps": 73.4,
  "motion": 0.0312,
  "presence": 1,
  "state": "walk",
  "csi_len": 384
}
```

## State values

| Value | Origin |
| --- | --- |
| `warmup` | window not full yet (first ~3 s) |
| `empty` | no person, or fallback with low motion |
| `walk`, `sit`, `stand`, `lie`, `fall` | model class order from the notebook |
| `motion` | rule-based fallback when no model is loaded |

The class order is fixed by the notebook (`LABELS`): `empty, walk, sit, stand,
lie, fall`. The firmware `state` string must be looked up from the same list, not
hard-coded separately.

## Fall event

Published only on the rising edge of `fall` (one message per event, retained by
the firmware client):

```json
{
  "event": "fall",
  "score": 0.93,
  "state": "fall",
  "motion": 0.41
}
```

`score` is the model probability for the `fall` class, `0.0` in fallback mode.
`event` is absent from periodic telemetry.

## Device attributes

Published on every (re)connect:

```json
{
  "fw": "0.1.0",
  "room": "room-01",
  "subject": "subject-01"
}
```

The bridge uses `fw = tb_bridge-0.1.0`.

## Serial-only fields

`INFER` lines also carry `fall`, `model_ok`, `total`, `dropped`. The bridge
drops them on purpose: they are diagnostics for the UART log and would waste
quota if uploaded.

## Cadence and retention

- ThingsBoard assigns server-side timestamps; no device clock needed.
- Free tier: 1M data points/month, 30-day retention, 5 devices.
- At 5 keys / 15 s: 28,800 messages/month, ~864k points/month.
- `TB_PUBLISH_INTERVAL_S` has a Kconfig minimum of 5 s (~2.6M points/month,
  over quota). Do not go below 10 s for continuous use.

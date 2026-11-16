# End-to-end runbook

## Prerequisites

- ESP-IDF 5.5.6: `. C:\esp\v5.5.6\esp-idf\export.ps1` in every new shell.
- Sender on `COM7`, receiver on `COM11` (check Device Manager; ports change).
- Both boards flashed with the same `CSI_CHANNEL` (default 11).
- `tools\tb_bridge\.venv` installed and `.env` with `TB_TOKEN`.

## 1. Build and flash the sender

```powershell
cd D:\dacn2\source_code\firmware\esp32-csi-sender
. C:\esp\v5.5.6\esp-idf\export.ps1
idf.py build
idf.py -p COM7 flash
```

## 2. Build and flash the receiver

```powershell
cd D:\dacn2\source_code\firmware\esp32-csi-node
. C:\esp\v5.5.6\esp-idf\export.ps1
idf.py build
idf.py -p COM11 flash
```

The receiver stays in UART mode by default. Do not open `idf.py monitor` while
the bridge is running: the port is exclusive.

## 3. Verify the link

```powershell
idf.py -p COM11 monitor
```

Expected after a few seconds:

```
CSI_DATA,1234,1a:00:00:00:00:00,...
INFER,{"rssi":-41.0,"pps":73.4,"motion":0.0312,"presence":1,...}
```

Exit the monitor with `Ctrl+]`. No `INFER` lines: wait for the 250-packet
window (~3.4 s at 73 pps), confirm the sender is powered and on the same channel,
and check that only the sender MAC is accepted.

`CSI_DATA` at 100 Hz saturates 921600 baud, which is why the measured rate is
~73 pps. For a bridge-only demo, disable **Emit CSI_DATA CSV on UART** in
`menuconfig` (the `INFER` lines continue); re-enable it before recording
training data with `csi_labeler`.

## 4. Bridge to ThingsBoard

```powershell
cd D:\dacn2\source_code\tools\tb_bridge
.\.venv\Scripts\python tb_bridge.py --dry-run
```

Confirm one JSON line every 15 s, then run for real:

```powershell
.\.venv\Scripts\python tb_bridge.py
```

## 5. Verify on ThingsBoard

Device `csi-node-room-01` → **Latest telemetry**: `rssi`, `pps`, `motion`,
`presence`, `state`, `csi_len` updating every 15 s. The dashboard charts should
move when someone walks through the link.

## 6. Demo script (5 minutes)

1. Empty room: `state` `empty`, low `motion`.
2. Walk through the link: `state` `walk`, `motion` rises, `presence` 1.
3. Sit / stand near the link: `state` changes.
4. Fall trial: `event: fall` and a spike in the chart (until the trained model
   is integrated, only the rule-based fallback runs; `model_ok:0`).
5. Show the serial `INFER` line and the ThingsBoard chart side by side.

## 7. Direct MQTT later

Once a 2.4 GHz AP is available: `idf.py menuconfig` → **ElderCare CSI Node** →
`WiFi + ThingsBoard MQTT`, set SSID/password/token/channel, rebuild, flash.
The bridge is no longer needed. See `thingsboard-setup.md`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `serial error` | port busy; close monitor/other tools; correct COM |
| No `CSI_DATA` | sender not flashed/powered; channel mismatch; wrong sender MAC filter |
| No `INFER` | window not full; CLI `csi_len` is 0; sender rate too low |
| `MQTT connect failed rc=4/5` | wrong token or token belongs to another device |
| Payloads frozen | bridge reading boot logs only; `--debug` |
| ThingsBoard quota warning | raise `--interval` / `TB_PUBLISH_INTERVAL_S` to 15–30 s |

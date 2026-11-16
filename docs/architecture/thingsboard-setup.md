# ThingsBoard setup

## 1. Create the device

1. Sign in at <https://thingsboard.cloud> (free tier: 5 devices, 1M data
   points/month, 30-day retention).
2. **Entities → Devices → + Add new device**.
3. Name: `csi-node-room-01`, profile `default`, transport `MQTT`.
4. Open the device → **Details → Copy access token**. This token is the MQTT
   username; the password is empty.

Never commit the token. Store it in `tools/tb_bridge/.env` (gitignored) or enter
it in `idf.py menuconfig`; the generated `sdkconfig` is also gitignored.

## 2. Path A: PC bridge (works today)

```powershell
cd tools\tb_bridge
Copy-Item .env.example .env
# set TB_TOKEN in .env
.\.venv\Scripts\python tb_bridge.py --dry-run
.\.venv\Scripts\python tb_bridge.py
```

The bridge reads `INFER` lines on `COM11` at 921600 baud and publishes the same
5-key payload the firmware would send directly. See `tools/tb_bridge/README.md`.

## 3. Path B: ESP32-S3 direct MQTT (needs a 2.4 GHz AP)

```powershell
cd firmware\esp32-csi-node
. C:\esp\v5.5.6\esp-idf\export.ps1
idf.py menuconfig
```

Set under **ElderCare CSI Node**:

- `Output mode` → `WiFi + ThingsBoard MQTT`
- `ThingsBoard host` → `thingsboard.cloud`
- `ThingsBoard MQTT port` → `1883` (or `8883` with TLS on)
- `ThingsBoard access token` → your token
- `WiFi SSID` / `WiFi password` → a **2.4 GHz** network
- `WiFi channel` must equal the AP channel and the sender channel
- `Subject id`, `Room id`, `Telemetry publish interval`

Then `idf.py -p COM11 flash monitor`. Look for `MQTT connected` in the log.

Why this is not used yet: the available AP (`MR.LAM CAFE`) is 5 GHz only and
channel 36, so the S3 cannot associate and CSI cannot run on the same channel.

## 4. Verify data

Device → **Latest telemetry** should show `rssi`, `pps`, `motion`, `presence`,
`state`, `csi_len` (and `event`/`score` after a fall). If nothing arrives:

- bridge: check `TB_TOKEN`, port, and that `INFER` lines appear in `--dry-run`;
- firmware: check `MQTT connected`, token, 2.4 GHz SSID, and channel match.

## 5. Dashboard

1. **Dashboards → + Create new dashboard**.
2. Add alias `node` → type `Device` → filter `Single entity` →
   `csi-node-room-01`.
3. Add widgets:
   - **Timeseries chart**: `rssi`, `pps`, `motion` (last 1 hour).
   - **Latest value**: `state`, `presence`, `csi_len`.
   - **Alarm / table widget** on `event` = `fall` or on `state`.
4. Optional rule chain (free tier allows 3): message type `POST_TELEMETRY` →
   script filter `msg.event === 'fall'` → **Create alarm** (type `Fall`,
   severity `CRITICAL`) → **Save attributes**.
5. Set dashboard as home page for the demo.

## 6. Quota budget

| Source | Keys | Interval | Points/month |
| --- | --- | --- | --- |
| Telemetry | 5 | 15 s | ~864,000 |
| Fall events | 3 | rare | negligible |

Raw CSI is **not** uploaded: ~29,568 points/s would exhaust the 1M monthly
quota in about 34 seconds. Keep `TB_PUBLISH_INTERVAL_S` at 15 s or higher
(minimum in Kconfig is 5 s).

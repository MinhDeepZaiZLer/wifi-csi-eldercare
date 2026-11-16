# esp32-csi-sender

TX node. It sets a locally administered MAC (`1a:00:00:00:00:00`), joins no AP,
and broadcasts small ESP-NOW frames at the configured rate so the RX node can
capture CSI.

## Build

```powershell
. C:\esp\v5.5.6\esp-idf\export.ps1
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p COM7 flash monitor
```

Set `ElderCare CSI Sender -> WiFi channel` to the same channel used by
`esp32-csi-node`. In WiFi+MQTT mode it must also match the AP channel.

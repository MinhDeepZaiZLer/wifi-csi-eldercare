# Board inventory

| Role | Port | Base MAC | USB serial | Firmware |
| --- | --- | --- | --- | --- |
| TX sender | `COM7` | `84:fc:e6:6a:26:98` | `5CE5225877` | `esp32-csi-sender` |
| RX node | `COM11` | `30:30:f9:16:ff:30` | `5CE4106896` | `esp32-csi-node` |

Both boards:

- ESP32-S3 (QFN56, revision v0.2), 16 MB flash, 8 MB embedded PSRAM.
- USB-serial: CH343 (`VID:PID = 1A86:55D3`), so they enumerate as
  `USB-Enhanced-SERIAL CH343`.
- 2.4 GHz WiFi only; 5 GHz APs cannot be used.
- Powered and flashed over the same USB cable.

The sender overrides its own MAC to `1a:00:00:00:00:00`; the receiver filters CSI
by that address. The base MACs above stay unchanged and are used to identify the
boards.

## If the COM numbers change

```powershell
. C:\esp\v5.5.6\esp-idf\export.ps1
esptool.py -p COMx read_mac
```

Match the MAC to the table, then use that port in `idf.py -p PORT flash` and in
`tools/tb_bridge/.env` (`SERIAL_PORT`) or `csi_labeler --port`.

Serial numbers are stable across replugs; the port number is not.

## Radio setup

- Both boards on channel 11 (`ElderCare CSI ... -> WiFi channel`).
- Sender broadcasts ESP-NOW frames; receiver must see only the sender MAC.
- Distance 1–3 m, both boards fixed at about 1 m height, facing each other.
- Move the boards only between sessions; keep the layout fixed during a session.

## Verified builds

| Firmware | Binary | Free space |
| --- | --- | --- |
| Sender | 719,776 B | 53% of 1.5 MB app slot |
| Node | 728,448 B | 77% of 3 MB OTA slot |

Node output verified: `csi_len = 384`, about 73 packets/s, `INFER` every 1 s,
no ring drops over a 20 s capture. UART console is a custom UART0 at 921600.

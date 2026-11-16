import argparse
import json
import logging
import os
import sys
import time

import serial

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

TELEMETRY_TOPIC = "v1/devices/me/telemetry"
ATTRIBUTES_TOPIC = "v1/devices/me/attributes"
FIRMWARE_NAME = "tb_bridge-0.1.0"


class Bridge:
    def __init__(self, args):
        self.args = args
        self.client = None
        self.prev_fall = False
        self.last_publish = 0.0
        self.csi_count = 0
        self.infer_count = 0
        self.last_stats = time.monotonic()

    def connect(self):
        if self.args.dry_run:
            return
        client = mqtt.Client(client_id=f"tb-bridge-{self.args.subject}")
        client.username_pw_set(self.args.token)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        if self.args.tls:
            client.tls_set()
        client.connect(self.args.host, self.args.mqtt_port, keepalive=60)
        client.loop_start()
        self.client = client

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logging.info("connected to %s:%s", self.args.host, self.args.mqtt_port)
            attrs = {
                "fw": FIRMWARE_NAME,
                "room": self.args.room,
                "subject": self.args.subject,
            }
            client.publish(ATTRIBUTES_TOPIC, json.dumps(attrs), qos=1)
        else:
            logging.error("MQTT connect failed rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logging.warning("MQTT disconnected rc=%s", rc)

    def publish(self, payload):
        body = json.dumps(payload)
        if self.args.dry_run:
            print(body, flush=True)
            return
        if self.client is None:
            logging.warning("not connected; dropping %s", body)
            return
        info = self.client.publish(TELEMETRY_TOPIC, body, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logging.warning("publish failed rc=%s", info.rc)

    def handle_infer(self, payload):
        now = time.monotonic()
        fall = bool(payload.get("fall", 0))
        if fall and not self.prev_fall:
            self.publish(
                {
                    "event": "fall",
                    "score": payload.get("score", 0.0),
                    "state": payload.get("state", "unknown"),
                    "motion": payload.get("motion", 0.0),
                }
            )
        self.prev_fall = fall

        if self.args.interval <= 0 or now - self.last_publish >= self.args.interval:
            self.publish(
                {
                    "rssi": payload.get("rssi", 0.0),
                    "pps": payload.get("pps", 0.0),
                    "motion": payload.get("motion", 0.0),
                    "presence": int(payload.get("presence", 0)),
                    "state": payload.get("state", "unknown"),
                    "csi_len": payload.get("csi_len", 0),
                }
            )
            self.last_publish = now

    def run(self):
        logging.info("opening %s @ %d", self.args.port, self.args.baud)
        deadline = (
            time.monotonic() + self.args.duration if self.args.duration > 0 else None
        )
        with serial.Serial(self.args.port, self.args.baud, timeout=1) as ser:
            while deadline is None or time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line.startswith("INFER,"):
                    try:
                        payload = json.loads(line[6:])
                    except json.JSONDecodeError:
                        logging.warning("bad INFER line: %s", line[:120])
                        continue
                    if not isinstance(payload, dict):
                        continue
                    self.infer_count += 1
                    self.handle_infer(payload)
                elif line.startswith("CSI_DATA,"):
                    self.csi_count += 1
                self._stats()

    def _stats(self):
        now = time.monotonic()
        if now - self.last_stats < 5:
            return
        logging.info("csi=%d infer=%d", self.csi_count, self.infer_count)
        self.csi_count = 0
        self.infer_count = 0
        self.last_stats = now

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Bridge ESP32 CSI serial output to ThingsBoard telemetry"
    )
    parser.add_argument("--port", default=os.getenv("SERIAL_PORT", "COM11"))
    parser.add_argument(
        "--baud", type=int, default=int(os.getenv("SERIAL_BAUD", "921600"))
    )
    parser.add_argument("--host", default=os.getenv("TB_HOST", "thingsboard.cloud"))
    parser.add_argument(
        "--mqtt-port", type=int, default=int(os.getenv("TB_MQTT_PORT", "1883"))
    )
    parser.add_argument("--token", default=os.getenv("TB_TOKEN", ""))
    parser.add_argument("--subject", default=os.getenv("TB_SUBJECT", "subject-01"))
    parser.add_argument("--room", default=os.getenv("TB_ROOM", "room-01"))
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("TB_PUBLISH_INTERVAL_S", "15")),
        help="seconds between telemetry messages (0 = every inference)",
    )
    parser.add_argument(
        "--tls", action="store_true", default=os.getenv("TB_TLS", "0") == "1"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--duration", type=float, default=0.0, help="stop after N seconds (0 = forever)"
    )
    parser.add_argument("--debug", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.dry_run:
        if mqtt is None:
            logging.error("paho-mqtt missing; run: pip install -r requirements.txt")
            return 1
        if not args.token:
            logging.error("TB_TOKEN is empty; set it in .env or pass --token")
            return 1

    bridge = Bridge(args)
    try:
        bridge.connect()
        bridge.run()
    except serial.SerialException as exc:
        logging.error("serial error: %s", exc)
        return 1
    except KeyboardInterrupt:
        logging.info("stopped")
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

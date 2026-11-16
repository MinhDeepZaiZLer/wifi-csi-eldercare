import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

import tb_bridge


def make_args(**overrides):
    values = {
        "dry_run": True,
        "host": "localhost",
        "mqtt_port": 1883,
        "token": "",
        "subject": "subject-01",
        "room": "room-01",
        "interval": 0.0,
        "tls": False,
        "port": "COM0",
        "baud": 921600,
        "duration": 0.0,
        "debug": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


BASE = {
    "rssi": -42.0,
    "pps": 73.0,
    "motion": 0.03,
    "presence": 1,
    "state": "walk",
    "csi_len": 384,
    "fall": 0,
    "score": 0.0,
}


class BridgeTest(unittest.TestCase):
    def run_infer(self, payloads, **overrides):
        bridge = tb_bridge.Bridge(make_args(**overrides))
        out = io.StringIO()
        with redirect_stdout(out):
            for payload in payloads:
                bridge.handle_infer(payload)
        return bridge, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_periodic_payload(self):
        _, lines = self.run_infer([BASE], interval=0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            set(lines[0]),
            {"rssi", "pps", "motion", "presence", "state", "csi_len"},
        )
        self.assertEqual(lines[0]["presence"], 1)
        self.assertEqual(lines[0]["state"], "walk")

    def test_interval_gates_telemetry(self):
        _, lines = self.run_infer([BASE, BASE], interval=100)
        self.assertEqual(len(lines), 1)

    def test_fall_rising_edge_fires_once(self):
        falling = dict(BASE, fall=1, score=0.9, state="fall")
        _, lines = self.run_infer([BASE, falling, falling, falling], interval=100)
        events = [line for line in lines if line.get("event") == "fall"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["score"], 0.9)
        self.assertEqual(events[0]["state"], "fall")

    def test_fall_event_ignores_interval(self):
        bridge = tb_bridge.Bridge(make_args(interval=3600))
        bridge.last_publish = tb_bridge.time.monotonic()
        out = io.StringIO()
        with redirect_stdout(out):
            bridge.handle_infer(dict(BASE, fall=1, score=0.75, state="fall"))
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["event"], "fall")

    def test_missing_fields_have_defaults(self):
        _, lines = self.run_infer([{}], interval=0)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["presence"], 0)
        self.assertEqual(lines[0]["state"], "unknown")
        self.assertEqual(lines[0]["csi_len"], 0)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSI Labeled Data Collector (ESP32-S3 / esp-csi).

Reads `CSI_DATA,...` lines from an ESP32-S3 receiver over serial, lets the
operator pick a label, and writes one CSV per trial. Each trial also gets a
metadata JSON, and every finished trial is appended to `data/index.csv`.

Dataset layout:
    data/
      index.csv
      raw/<subject>/<room>/<label>/<trial_id>.csv
      raw/<subject>/<room>/<label>/<trial_id>.json

Key shortcuts:
    1..6  select label
    Space start / stop recording

Usage:
    python csi_labeler.py --port COM11 --baud 921600 --data-dir <repo>/ai/data

Safety: only simulate falls on a soft mat with an assistant present.
"""

import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - reported in the GUI
    serial = None
    list_ports = None

from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
BAUD_DEFAULT = 921600
LABELS = [
    ("empty", "Không người", "#546e7a"),
    ("walk", "Đi bộ", "#1e88e5"),
    ("sit", "Ngồi", "#43a047"),
    ("stand", "Đứng", "#00897b"),
    ("lie", "Nằm", "#8e24aa"),
    ("fall", "Té ngã", "#e53935"),
]
ROOMS = ["living_room", "bedroom", "bathroom", "kitchen", "lab", "other"]

S3_FIELDS = [
    "type", "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth",
    "smoothing", "not_sounding", "aggregation", "stbc", "fec_coding", "sgi",
    "noise_floor", "ampdu_cnt", "channel", "secondary_channel",
    "local_timestamp", "ant", "sig_len", "rx_state", "len", "first_word",
]
C5C6_FIELDS = [
    "type", "id", "mac", "rssi", "rate", "noise_floor", "fft_gain",
    "agc_gain", "channel", "local_timestamp", "sig_len", "rx_state", "len",
    "first_word",
]

META_OUT = [
    "rssi", "rate", "sig_mode", "mcs", "bandwidth", "smoothing",
    "not_sounding", "aggregation", "stbc", "fec_coding", "sgi",
    "noise_floor", "ampdu_cnt", "channel", "secondary_channel",
    "local_timestamp", "ant", "sig_len", "rx_state", "csi_len",
    "first_word", "fft_gain", "agc_gain",
]
OUT_FIELDS = (
    ["trial_id", "pkt_idx", "t_pc", "t_iso", "label", "subject", "room",
     "rep", "device"] + META_OUT + ["csi_json"]
)
INDEX_FIELDS = [
    "trial_id", "csv_path", "subject", "room", "label", "rep", "device",
    "start_iso", "end_iso", "duration_s", "packets", "avg_pps", "rssi_mean",
    "csi_lens", "fmt", "notes",
]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_csi_line(raw):
    """Parse one `CSI_DATA` serial line. Returns dict or None."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="ignore")
    else:
        text = str(raw)
    idx = text.find("CSI_DATA")
    if idx < 0:
        return None
    text = text[idx:].strip()

    try:
        row = next(csv.reader([text]))
    except Exception:
        return None

    if len(row) == 25:
        fmt = "esp32s3"
        try:
            csi_len = int(row[22])
            payload = json.loads(row[24])
        except Exception:
            return None
        if csi_len != len(payload):
            return None
        meta = {name: row[i] for i, name in enumerate(S3_FIELDS)}
    elif len(row) == 15:
        fmt = "esp32c5c6"
        try:
            csi_len = int(row[12])
            payload = json.loads(row[14])
        except Exception:
            return None
        if csi_len != len(payload):
            return None
        meta = {name: row[i] for i, name in enumerate(C5C6_FIELDS)}
    else:
        return None

    arr = np.asarray(payload, dtype=np.int16)
    if arr.size < 2:
        return None
    n = arr.size // 2
    imag = arr[0:2 * n:2].astype(np.float64)
    real = arr[1:2 * n:2].astype(np.float64)
    amp = np.sqrt(imag * imag + real * real)

    return {
        "fmt": fmt,
        "meta": meta,
        "csi_len": csi_len,
        "csi": payload,
        "amp": amp,
        "rssi": _to_int(meta.get("rssi")),
        "channel": _to_int(meta.get("channel")),
    }


# --------------------------------------------------------------------------- #
# Trial writer
# --------------------------------------------------------------------------- #
def _safe(value):
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("_") or "x"


class Trial:
    def __init__(self, data_dir, subject, room, label, rep, device, notes, fmt):
        self.subject = subject
        self.room = room
        self.label = label
        self.rep = int(rep)
        self.device = device
        self.notes = notes
        self.fmt = fmt
        self.start_dt = datetime.now()
        stamp = self.start_dt.strftime("%Y%m%d_%H%M%S")
        self.trial_id = (
            f"{_safe(subject)}_{_safe(room)}_{_safe(label)}"
            f"_r{self.rep:02d}_{stamp}"
        )
        self.dir = (
            Path(data_dir) / "raw" / _safe(subject) / _safe(room) / _safe(label)
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.dir / f"{self.trial_id}.csv"
        self.meta_path = self.dir / f"{self.trial_id}.json"

        self._fh = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=OUT_FIELDS)
        self._writer.writeheader()
        self._last_flush = time.time()

        self.packets = 0
        self.rssi_sum = 0
        self.rssi_n = 0
        self.csi_lens = set()
        self.closed = False

    def write(self, parsed):
        if self.closed:
            return
        if self.fmt == "auto":
            self.fmt = parsed["fmt"]
        meta = parsed["meta"]
        row = {key: "" for key in OUT_FIELDS}
        row.update(
            trial_id=self.trial_id,
            pkt_idx=self.packets,
            t_pc=f"{time.time():.6f}",
            t_iso=datetime.now().isoformat(timespec="milliseconds"),
            label=self.label,
            subject=self.subject,
            room=self.room,
            rep=self.rep,
            device=self.device,
            csi_len=parsed["csi_len"],
            csi_json=json.dumps(parsed["csi"], separators=(",", ":")),
        )
        for key in META_OUT:
            if key == "csi_len":
                continue
            if key in meta:
                row[key] = meta[key]

        self._writer.writerow(row)
        self.packets += 1
        if parsed["rssi"] is not None:
            self.rssi_sum += parsed["rssi"]
            self.rssi_n += 1
        self.csi_lens.add(parsed["csi_len"])

        now = time.time()
        if now - self._last_flush > 0.5:
            self._fh.flush()
            self._last_flush = now

    def finish(self, extra=None):
        if self.closed:
            return None
        self.closed = True
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass

        end_dt = datetime.now()
        duration = (end_dt - self.start_dt).total_seconds()
        avg_pps = self.packets / duration if duration > 0 else 0.0
        rssi_mean = (
            round(self.rssi_sum / self.rssi_n, 2) if self.rssi_n else ""
        )
        meta = {
            "trial_id": self.trial_id,
            "csv_path": str(self.csv_path),
            "subject": self.subject,
            "room": self.room,
            "label": self.label,
            "rep": self.rep,
            "device": self.device,
            "start_iso": self.start_dt.isoformat(timespec="milliseconds"),
            "end_iso": end_dt.isoformat(timespec="milliseconds"),
            "duration_s": round(duration, 3),
            "packets": self.packets,
            "avg_pps": round(avg_pps, 2),
            "rssi_mean": rssi_mean,
            "csi_lens": sorted(self.csi_lens),
            "fmt": self.fmt,
            "notes": self.notes,
        }
        if extra:
            meta.update(extra)
        try:
            self.meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return meta


# --------------------------------------------------------------------------- #
# Serial reader thread
# --------------------------------------------------------------------------- #
class ReaderThread(QtCore.QThread):
    connected = QtCore.pyqtSignal(str)
    disconnected = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, port, baud, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._lock = threading.Lock()
        self._running = False
        self._trial = None
        self.latest = None
        self.valid = 0
        self.dropped = 0
        self._last_amp = None
        self._motion = 0.0

    def attach(self, trial):
        with self._lock:
            old = self._trial
            self._trial = trial
        return old

    def detach(self):
        with self._lock:
            trial = self._trial
            self._trial = None
        return trial

    def snapshot(self):
        with self._lock:
            return self.latest, self.valid, self.dropped

    def stop(self):
        self._running = False

    def run(self):
        if serial is None:
            self.failed.emit("Chưa cài pyserial (pip install pyserial).")
            return
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.2)
        except Exception as exc:
            self.failed.emit(f"Không mở được {self.port}: {exc}")
            return
        self.connected.emit(self.port)
        self._running = True
        try:
            while self._running:
                raw = ser.readline()
                if not self._running:
                    break
                if not raw or b"CSI_DATA" not in raw:
                    continue
                parsed = parse_csi_line(raw)
                if parsed is None:
                    self.dropped += 1
                    continue
                self.valid += 1

                amp = parsed["amp"]
                if self._last_amp is not None and len(self._last_amp) == len(amp):
                    diff = float(np.mean(np.abs(amp - self._last_amp)))
                    self._motion = 0.8 * self._motion + 0.2 * diff
                self._last_amp = amp

                preview = {
                    "t": time.time(),
                    "rssi": parsed["rssi"],
                    "channel": parsed["channel"],
                    "csi_len": parsed["csi_len"],
                    "amp": amp,
                    "motion": self._motion,
                }
                with self._lock:
                    trial = self._trial
                    if trial is not None:
                        try:
                            trial.write(parsed)
                        except Exception:
                            self.dropped += 1
                    self.latest = preview
        except Exception as exc:
            self.failed.emit(f"Lỗi đọc serial: {exc}")
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.disconnected.emit()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, data_dir, preselect_port=None, baud=BAUD_DEFAULT):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.preselect_port = preselect_port
        self.default_baud = baud
        self.reader = None
        self.trial = None
        self.current_label = None
        self.recording = False
        self.motion_hist = deque(maxlen=400)
        self._prev_valid = 0
        self._prev_dropped = 0
        self._last_tick = time.time()
        self._rate = 0.0

        self.setWindowTitle("CSI Labeled Data Collector - ESP32-S3")
        self.resize(1360, 840)
        self._build_ui()
        self._build_shortcuts()
        self.refresh_ports()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start()

    # ----------------------------- UI -------------------------------------- #
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        left = QtWidgets.QWidget()
        left.setFixedWidth(500)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        # Connection
        grp_conn = QtWidgets.QGroupBox("Kết nối thiết bị (board RECV)")
        conn = QtWidgets.QGridLayout(grp_conn)
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setMinimumWidth(220)
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.baud_combo = QtWidgets.QComboBox()
        for b in ("921600", "460800", "115200"):
            self.baud_combo.addItem(b)
        self.baud_combo.setCurrentText(str(self.default_baud))
        self.btn_connect = QtWidgets.QPushButton("Kết nối")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn.addWidget(QtWidgets.QLabel("Cổng COM"), 0, 0)
        conn.addWidget(self.port_combo, 0, 1, 1, 2)
        conn.addWidget(self.btn_refresh, 0, 3)
        conn.addWidget(QtWidgets.QLabel("Baud"), 1, 0)
        conn.addWidget(self.baud_combo, 1, 1)
        conn.addWidget(self.btn_connect, 1, 2, 1, 2)
        left_layout.addWidget(grp_conn)

        # Metadata
        grp_meta = QtWidgets.QGroupBox("Thông tin buổi thu")
        meta = QtWidgets.QGridLayout(grp_meta)
        self.ed_subject = QtWidgets.QLineEdit("Minh")
        self.cb_room = QtWidgets.QComboBox()
        self.cb_room.setEditable(True)
        self.cb_room.addItems(ROOMS)
        self.ed_device = QtWidgets.QLineEdit("rx1")
        self.sp_rep = QtWidgets.QSpinBox()
        self.sp_rep.setRange(1, 99)
        self.sp_rep.setValue(1)
        self.ed_notes = QtWidgets.QLineEdit()
        meta.addWidget(QtWidgets.QLabel("Người thực hiện"), 0, 0)
        meta.addWidget(self.ed_subject, 0, 1)
        meta.addWidget(QtWidgets.QLabel("Phòng"), 0, 2)
        meta.addWidget(self.cb_room, 0, 3)
        meta.addWidget(QtWidgets.QLabel("Thiết bị"), 1, 0)
        meta.addWidget(self.ed_device, 1, 1)
        meta.addWidget(QtWidgets.QLabel("Lần lặp"), 1, 2)
        meta.addWidget(self.sp_rep, 1, 3)
        meta.addWidget(QtWidgets.QLabel("Ghi chú"), 2, 0)
        meta.addWidget(self.ed_notes, 2, 1, 1, 3)
        left_layout.addWidget(grp_meta)

        # Labels
        grp_lbl = QtWidgets.QGroupBox("Nhãn hành vi (phím 1-6)")
        lbl_grid = QtWidgets.QGridLayout(grp_lbl)
        self.label_buttons = {}
        for i, (key, text, color) in enumerate(LABELS):
            btn = QtWidgets.QPushButton(f"{i + 1}. {text}")
            btn.setMinimumHeight(52)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.select_label(k))
            lbl_grid.addWidget(btn, i // 2, i % 2)
            self.label_buttons[key] = (btn, color)
        left_layout.addWidget(grp_lbl)

        # Record control
        grp_rec = QtWidgets.QGroupBox("Ghi dữ liệu")
        rec = QtWidgets.QVBoxLayout(grp_rec)
        self.btn_record = QtWidgets.QPushButton("START  (Space)")
        self.btn_record.setMinimumHeight(64)
        self.btn_record.setStyleSheet(
            "font-size:20px;font-weight:bold;background:#2e7d32;color:white;"
        )
        self.btn_record.clicked.connect(self.toggle_record)
        rec.addWidget(self.btn_record)
        self.lbl_state = QtWidgets.QLabel("Trạng thái: IDLE")
        self.lbl_state.setStyleSheet("font-weight:bold;")
        rec.addWidget(self.lbl_state)
        self.lbl_stats = QtWidgets.QLabel()
        self.lbl_stats.setFont(QtGui.QFont("Consolas", 10))
        self.lbl_stats.setStyleSheet(
            "background:#111;color:#7CFC00;padding:8px;border-radius:4px;"
        )
        self.lbl_stats.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        rec.addWidget(self.lbl_stats)
        left_layout.addWidget(grp_rec)

        # Help
        help_text = (
            "Quy trình gợi ý (mỗi trial 30-60 s, lặp >= 5 lần):\n"
            "  empty -> walk -> sit -> stand -> lie -> fall\n"
            "- Té ngã: CHỈ mô phỏng trên đệm mềm, có người hỗ trợ.\n"
            "- Giữ 2 board cố định, cách >1 m, cùng phòng, kênh 11.\n"
            "- Đổi người/phòng -> sửa ô thông tin trước khi START.\n"
            "- Đang ghi mà đổi nhãn -> tự chia trial mới.\n"
            "- Phím tắt: 1..6 chọn nhãn, Space bật/tắt ghi."
        )
        grp_help = QtWidgets.QGroupBox("Hướng dẫn nhanh")
        help_layout = QtWidgets.QVBoxLayout(grp_help)
        lbl_help = QtWidgets.QLabel(help_text)
        lbl_help.setWordWrap(True)
        help_layout.addWidget(lbl_help)
        self.btn_open_dir = QtWidgets.QPushButton("Mở thư mục dữ liệu")
        self.btn_open_dir.clicked.connect(self.open_data_dir)
        help_layout.addWidget(self.btn_open_dir)
        left_layout.addWidget(grp_help)

        # Log
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setFixedHeight(110)
        self.log_box.setFont(QtGui.QFont("Consolas", 9))
        left_layout.addWidget(self.log_box)

        left_layout.addStretch(1)
        root.addWidget(left)

        # Right: plots
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True)
        self.amp_plot = pg.PlotWidget(title="Biên độ CSI - gói gần nhất")
        self.amp_plot.setLabel("left", "|H| (amplitude)")
        self.amp_plot.setLabel("bottom", "Subcarrier index")
        self.amp_plot.showGrid(x=True, y=True, alpha=0.25)
        self.amp_curve = self.amp_plot.plot(
            pen=pg.mkPen("#1e88e5", width=2)
        )
        right_layout.addWidget(self.amp_plot, 3)

        self.motion_plot = pg.PlotWidget(title="Motion score (EMA của biến thiên biên độ)")
        self.motion_plot.setLabel("left", "motion")
        self.motion_plot.setLabel("bottom", "Samples (150 ms)")
        self.motion_plot.showGrid(x=True, y=True, alpha=0.25)
        self.motion_curve = self.motion_plot.plot(
            pen=pg.mkPen("#e53935", width=2)
        )
        right_layout.addWidget(self.motion_plot, 2)

        root.addWidget(right, 1)

        self._update_label_styles()

    def _build_shortcuts(self):
        for i, (key, _text, _color) in enumerate(LABELS):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(str(i + 1)), self)
            sc.activated.connect(lambda k=key: self.select_label(k))
        sc_space = QtWidgets.QShortcut(QtGui.QKeySequence("Space"), self)
        sc_space.activated.connect(self.toggle_record)

    # --------------------------- Ports ------------------------------------- #
    def refresh_ports(self):
        self.port_combo.clear()
        ports = []
        if list_ports is not None:
            ports = sorted(list_ports.comports(), key=lambda p: p.device)
        for p in ports:
            desc = p.description or ""
            self.port_combo.addItem(f"{p.device} - {desc}", p.device)
        if not ports:
            self.port_combo.addItem("(không thấy cổng)", "")
            return
        target = self.preselect_port
        for i in range(self.port_combo.count()):
            if self.port_combo.itemData(i) == target:
                self.port_combo.setCurrentIndex(i)
                return

    def selected_port(self):
        return self.port_combo.currentData() or ""

    # --------------------------- Connection -------------------------------- #
    def toggle_connection(self):
        if self.reader is not None:
            self.disconnect_device()
        else:
            self.connect_device()

    def connect_device(self):
        port = self.selected_port()
        if not port:
            self.log("Chưa chọn cổng COM.")
            return
        baud = int(self.baud_combo.currentText())
        self.reader = ReaderThread(port, baud, self)
        self.reader.connected.connect(self.on_connected)
        self.reader.disconnected.connect(self.on_disconnected)
        self.reader.failed.connect(self.on_failed)
        self.reader.start()
        self.btn_connect.setText("Đang kết nối...")
        self.btn_connect.setEnabled(False)
        self.log(f"Đang mở {port} @ {baud} ...")

    def disconnect_device(self):
        if self.reader is None:
            return
        if self.recording:
            self.stop_trial(reason="ngắt kết nối")
        self.reader.stop()
        self.reader.wait(2000)
        self.reader = None
        self.btn_connect.setText("Kết nối")
        self.btn_connect.setEnabled(True)
        self.log("Đã ngắt kết nối.")

    @QtCore.pyqtSlot(str)
    def on_connected(self, port):
        self.btn_connect.setText("Ngắt")
        self.btn_connect.setEnabled(True)
        self.log(f"Đã kết nối {port}. Đang chờ CSI_DATA...")

    @QtCore.pyqtSlot()
    def on_disconnected(self):
        self.btn_connect.setText("Kết nối")
        self.btn_connect.setEnabled(True)

    @QtCore.pyqtSlot(str)
    def on_failed(self, message):
        self.log("LỖI: " + message)
        self.btn_connect.setText("Kết nối")
        self.btn_connect.setEnabled(True)
        self.reader = None

    # --------------------------- Labels ------------------------------------ #
    def _update_label_styles(self):
        for key, (btn, color) in self.label_buttons.items():
            if key == self.current_label:
                btn.setStyleSheet(
                    f"background:{color};color:white;font-weight:bold;"
                    "font-size:15px;border:3px solid #ffffff;"
                )
            else:
                btn.setStyleSheet(
                    f"background:{color}33;color:#e0e0e0;font-size:14px;"
                    f"border:2px solid {color};"
                )

    def select_label(self, key):
        if self.recording and key != self.current_label:
            self.log(f"Đổi nhãn -> chia trial mới ({key}).")
            self.stop_trial(reason="đổi nhãn")
            self.current_label = key
            self._update_label_styles()
            self.start_trial()
            return
        self.current_label = key
        self._update_label_styles()
        self.log(f"Đã chọn nhãn: {key}")

    # --------------------------- Recording --------------------------------- #
    def toggle_record(self):
        if self.recording:
            self.stop_trial()
        else:
            self.start_trial()

    def start_trial(self):
        if self.reader is None or not self.reader.isRunning():
            self.log("Chưa kết nối thiết bị.")
            return
        if not self.current_label:
            self.log("Hãy chọn nhãn trước khi START.")
            return
        subject = self.ed_subject.text().strip()
        room = self.cb_room.currentText().strip()
        device = self.ed_device.text().strip()
        if not subject or not room or not device:
            self.log("Thiếu Người thực hiện / Phòng / Thiết bị.")
            return

        trial = Trial(
            data_dir=self.data_dir,
            subject=subject,
            room=room,
            label=self.current_label,
            rep=self.sp_rep.value(),
            device=device,
            notes=self.ed_notes.text().strip(),
            fmt="auto",
        )
        old = self.reader.attach(trial)
        if old is not None:
            old.finish()
        self.trial = trial
        self.recording = True
        self.motion_hist.clear()
        self._last_tick = time.time()
        self.btn_record.setText("STOP  (Space)")
        self.btn_record.setStyleSheet(
            "font-size:20px;font-weight:bold;background:#c62828;color:white;"
        )
        self.lbl_state.setText(f"Trạng thái: REC  [{self.current_label}]")
        self.log(f"Bắt đầu trial: {trial.trial_id}")
        self.log(f"  -> {trial.csv_path}")

    def stop_trial(self, reason=""):
        if not self.recording:
            return
        trial = self.reader.detach() if self.reader else self.trial
        dropped = self.reader.dropped if self.reader else 0
        meta = None
        if trial is not None:
            meta = trial.finish(extra={"dropped_total": dropped})
        self.trial = None
        self.recording = False
        self.btn_record.setText("START  (Space)")
        self.btn_record.setStyleSheet(
            "font-size:20px;font-weight:bold;background:#2e7d32;color:white;"
        )
        self.lbl_state.setText("Trạng thái: IDLE")
        if meta:
            self.append_index(meta)
            self.log(
                "Kết thúc trial: {t} | {p} gói | {d:.1f} s | {r} pkt/s{rs}".format(
                    t=meta["trial_id"],
                    p=meta["packets"],
                    d=meta["duration_s"],
                    r=meta["avg_pps"],
                    rs=(" | " + reason) if reason else "",
                )
            )
            if not reason and meta["packets"] > 0:
                self.sp_rep.setValue(min(99, self.sp_rep.value() + 1))

    def append_index(self, meta):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        index_path = self.data_dir / "index.csv"
        exists = index_path.exists()
        try:
            with open(index_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
                if not exists:
                    writer.writeheader()
                writer.writerow({k: meta.get(k, "") for k in INDEX_FIELDS})
        except Exception as exc:
            self.log(f"Không ghi được index.csv: {exc}")

    # --------------------------- Ticking ----------------------------------- #
    def on_tick(self):
        now = time.time()
        dt = max(now - self._last_tick, 1e-6)
        self._last_tick = now

        if self.reader is None:
            self.lbl_stats.setText(
                "Chưa kết nối.\nRSSI   : --\nCSI len: --\nKênh   : --\n"
                "Gói/s  : --\nDrop   : --\nMotion : --"
            )
            return

        latest, valid, dropped = self.reader.snapshot()
        self._rate = (valid - self._prev_valid) / dt
        self._prev_valid = valid
        self._prev_dropped = dropped

        elapsed = 0.0
        packets = 0
        if self.trial is not None:
            elapsed = (datetime.now() - self.trial.start_dt).total_seconds()
            packets = self.trial.packets

        if latest is not None:
            rssi = latest["rssi"]
            channel = latest["channel"]
            csi_len = latest["csi_len"]
            motion = latest["motion"]
            amp = latest["amp"]
            self.amp_curve.setData(np.arange(len(amp)), amp)
            self.motion_hist.append(motion)
            self.motion_curve.setData(np.arange(len(self.motion_hist)),
                                      np.asarray(self.motion_hist))
        else:
            rssi = channel = csi_len = None
            motion = 0.0

        self.lbl_stats.setText(
            "Elapsed : {el:6.1f} s\n"
            "Đã ghi  : {pk:6d} gói\n"
            "Gói/s   : {rt:6.1f}\n"
            "RSSI    : {rs:>4} dBm\n"
            "CSI len : {ln:>4}\n"
            "Kênh    : {ch:>4}\n"
            "Valid   : {va:6d}\n"
            "Dropped : {dr:6d}\n"
            "Motion  : {mo:6.2f}".format(
                el=elapsed,
                pk=packets,
                rt=self._rate,
                rs="--" if rssi is None else rssi,
                ln="--" if csi_len is None else csi_len,
                ch="--" if channel is None else channel,
                va=valid,
                dr=dropped,
                mo=motion,
            )
        )

    # --------------------------- Misc -------------------------------------- #
    def open_data_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self.data_dir.resolve()))
            )
        except Exception as exc:
            self.log(f"Không mở được thư mục: {exc}")

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{stamp}] {message}")

    def closeEvent(self, event):
        if self.recording:
            self.stop_trial(reason="đóng ứng dụng")
        if self.reader is not None:
            self.reader.stop()
            self.reader.wait(2000)
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def default_data_dir():
    return Path(__file__).resolve().parents[2] / "ai" / "data"


def main():
    parser = argparse.ArgumentParser(description="CSI labeled data collector")
    parser.add_argument("--port", default=None, help="e.g. COM11 (preselect)")
    parser.add_argument("--baud", type=int, default=BAUD_DEFAULT)
    parser.add_argument(
        "--data-dir", default=str(default_data_dir()),
        help="root output directory (default: <work>/data)",
    )
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow(
        data_dir=Path(args.data_dir),
        preselect_port=args.port,
        baud=args.baud,
    )
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

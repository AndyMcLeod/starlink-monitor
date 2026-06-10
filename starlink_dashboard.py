"""
Starlink Dish Monitoring Dashboard
Connects to the dish gRPC API at 192.168.100.1:9200 (standard gRPC/HTTP2).
Requires: pip install grpcio grpcio-tools pyserial
"""

import os
import sys
import math
import time
import threading
import subprocess
import tempfile
import struct
import tkinter as tk
from tkinter import ttk, font as tkfont
from collections import deque
from pathlib import Path

DISH_HOST = "192.168.100.1:9200"
POLL_INTERVAL = 2  # seconds
HISTORY_LEN = 1200  # points kept for sparklines

GPS_PORT = "COM10"
GPS_BAUD = 9600

# ---------------------------------------------------------------------------
# Proto generation (embedded .proto, compiled at first run)
# ---------------------------------------------------------------------------

PROTO_DIR = Path(tempfile.gettempdir()) / "starlink_proto"
PROTO_FILE = PROTO_DIR / "starlink.proto"

PROTO_SRC = r"""
syntax = "proto3";
package SpaceX.API.Device;

service Device {
    rpc Handle(Request) returns (Response) {}
}

message DeviceInfo {
    string id = 1;
    string hardware_version = 2;
    string software_version = 3;
    string country_code = 4;
    bool software_partitions_equal = 8;
}

message DeviceState {
    uint64 uptime_s = 1;
}

message DishSignalStats {
    uint32 index = 1;
    float snr_db = 3;
    float elevation_deg = 4;
    float azimuth_deg = 5;
    uint32 rx_beam_state = 6;
    float obstruction_score = 7;
    float secondary_elevation_deg = 8;
    float secondary_azimuth_deg = 9;
}

message DishObstructionStats {
    bool currently_obstructed = 1;
    uint32 obstruction_duration_s = 2;
    uint32 obstruction_event_count = 5;
}

// Per-sector (wedge) signal quality, 10 sectors
message DishSectorSignal {
    uint32 s1 = 1;
    uint32 s2 = 2;
    uint32 s3 = 3;
    uint32 s4 = 4;
    uint32 s5 = 5;
    uint32 s6 = 6;
    uint32 s7 = 7;
    uint32 s8 = 8;
    uint32 s9 = 9;
    uint32 s10 = 10;
}

// 5 readiness flags (all 1 = fully operational)
message DishReadyStates {
    bool cady = 2;
    bool scp = 3;
    bool l1l2 = 4;
    bool xphy = 5;
    bool aap = 6;
}

// GPS / IMU status
message DishGpsStatus {
    bool valid = 1;
    float accuracy = 2;
}

// Dish orientation quaternion (x,w,y,z ordering confirmed by wire decode)
message DishTilt {
    float x = 1;
    float w = 2;
    float y = 3;
    float z = 4;
}

// Actual field numbers confirmed by raw wire-decoding against firmware 2026.05.26
message DishGetStatusResponse {
    DeviceInfo device_info = 1;
    DeviceState device_state = 2;

    float pop_ping_drop_rate = 1006;
    float downlink_throughput_bps = 1007;
    float uplink_throughput_bps = 1008;
    float pop_ping_latency_ms = 1009;

    float boresight_elevation_deg = 1011;
    float boresight_azimuth_deg = 1012;

    DishObstructionStats obstruction_stats = 1015;
    uint32 eth_speed_mbps = 1016;

    DishReadyStates ready_states = 1019;

    DishGpsStatus gps_status = 1026;
    DishSignalStats signal_stats = 1027;
    DishSectorSignal sector_signal = 1028;

    DishTilt tilt_quaternion = 1049;
}

message DishGetHistoryResponse {
    uint64 current = 1;
    // Packed float arrays — 900 seconds of 1Hz history
    // Field numbers confirmed by wire-decoding against firmware 2026.05.26
    repeated float pop_ping_drop_rate = 1001 [packed=true];
    repeated float pop_ping_latency_ms = 1002 [packed=true];
    repeated float downlink_throughput_bps = 1003 [packed=true];
    repeated float uplink_throughput_bps = 1004 [packed=true];
    repeated float snr_db = 1010 [packed=true];
}

message GetStatusRequest {}
message DishGetHistoryRequest {}

message Request {
    uint64 id = 1;
    oneof request {
        GetStatusRequest get_status = 1004;
        DishGetHistoryRequest get_history = 1007;
    }
}

message Response {
    uint64 id = 1;
    oneof response {
        DishGetStatusResponse dish_get_status = 2004;
        DishGetHistoryResponse dish_get_history = 2006;
    }
}
"""


def ensure_proto_compiled():
    PROTO_DIR.mkdir(exist_ok=True)
    pb2_file = PROTO_DIR / "starlink_pb2.py"
    existing = PROTO_FILE.read_text() if PROTO_FILE.exists() else ""
    needs_compile = not pb2_file.exists() or existing.strip() != PROTO_SRC.strip()
    PROTO_FILE.write_text(PROTO_SRC)
    if needs_compile:
        subprocess.check_call([
            sys.executable, "-m", "grpc_tools.protoc",
            f"--proto_path={PROTO_DIR}",
            f"--python_out={PROTO_DIR}",
            f"--grpc_python_out={PROTO_DIR}",
            str(PROTO_FILE),
        ])
    sys.path.insert(0, str(PROTO_DIR))


# ---------------------------------------------------------------------------
# Starlink client  (gRPC-Web over HTTP/1.1)
# ---------------------------------------------------------------------------

class StarlinkClient:
    """Standard gRPC (HTTP/2) client on port 9200 — no auth required."""

    def __init__(self):
        import grpc, importlib
        ensure_proto_compiled()
        self.pb2 = importlib.import_module("starlink_pb2")
        self.pb2_grpc = importlib.import_module("starlink_pb2_grpc")
        channel = grpc.insecure_channel(DISH_HOST)
        self.stub = self.pb2_grpc.DeviceStub(channel)

    def get_status(self):
        req = self.pb2.Request()
        req.get_status.CopyFrom(self.pb2.GetStatusRequest())
        return self.stub.Handle(req, timeout=5).dish_get_status

    def get_history(self):
        req = self.pb2.Request()
        req.get_history.CopyFrom(self.pb2.DishGetHistoryRequest())
        return self.stub.Handle(req, timeout=10).dish_get_history


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

BG = "#0d1117"
CARD = "#161b22"
BORDER = "#30363d"
TEXT = "#e6edf3"
DIM = "#8b949e"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"
BLUE = "#58a6ff"
TEAL = "#39d353"
ORANGE = "#db6d28"
PURPLE = "#bc8cff"

# ---------------------------------------------------------------------------
# Canvas sparkline widget
# ---------------------------------------------------------------------------

def _nice_ticks(lo, hi, n=3):
    """Return n evenly-spaced round tick values covering [lo, hi]."""
    span = hi - lo or 1
    raw_step = span / n
    mag = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    for mult in (1, 2, 2.5, 5, 10):
        step = mag * mult
        if span / step <= n + 1:
            break
    start = math.ceil(lo / step) * step if step else lo
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        ticks.append(v)
        v += step
    return ticks


class Sparkline(tk.Canvas):
    def __init__(self, parent, maxlen=HISTORY_LEN, color=BLUE, height=56,
                 unit="", fmt="{:.1f}", **kw):
        super().__init__(parent, height=height, bg=CARD, highlightthickness=0, **kw)
        self.color = color
        self.unit = unit
        self.fmt = fmt
        self.data: deque = deque(maxlen=maxlen)
        self.bind("<Configure>", lambda _: self._draw())

    def push(self, value):
        self.data.append(value)
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or len(self.data) < 2:
            return
        vals = list(self.data)
        lo, hi = min(vals), max(vals)
        if hi == lo:
            hi = lo + 1
        ticks = _nice_ticks(lo, hi, n=2)

        LMARGIN = 42
        BOTTOM = 14   # room for X-axis labels
        TOP = 4
        plot_w = w - LMARGIN - 4
        plot_h = h - TOP - BOTTOM

        def to_y(v):
            return (h - BOTTOM) - (v - lo) / (hi - lo) * plot_h

        def to_x(i, n):
            return LMARGIN + i * plot_w / max(n - 1, 1)

        # Y gridlines + labels
        for tick in ticks:
            y = to_y(tick)
            self.create_line(LMARGIN, y, w - 4, y, fill=BORDER, dash=(2, 4))
            self.create_text(LMARGIN - 4, y, text=self.fmt.format(tick),
                             fill=DIM, font=("Consolas", 8), anchor="e")

        # Axes
        self.create_line(LMARGIN, TOP, LMARGIN, h - BOTTOM, fill=BORDER)
        self.create_line(LMARGIN, h - BOTTOM, w - 4, h - BOTTOM, fill=BORDER)

        # X-axis time labels: show age of leftmost point and midpoint
        n_pts = len(vals)
        total_s = n_pts * POLL_INTERVAL
        for frac, anchor in ((0.0, "w"), (0.5, "center"), (1.0, "e")):
            age_s = total_s * (1.0 - frac)
            if age_s < 60:
                label = f"-{int(age_s)}s" if age_s > 0 else "now"
            else:
                label = f"-{int(age_s/60)}m" if age_s > 0 else "now"
            x = LMARGIN + frac * plot_w
            self.create_text(x, h - BOTTOM + 3, text=label, fill=DIM,
                             font=("Consolas", 7), anchor="n")

        # Data line
        xs = [to_x(i, n_pts) for i in range(n_pts)]
        ys = [to_y(v) for v in vals]
        pts = []
        for x, y in zip(xs, ys):
            pts += [x, y]
        self.create_line(*pts, fill=self.color, width=2, smooth=True)


# ---------------------------------------------------------------------------
# Reusable card widgets
# ---------------------------------------------------------------------------

def make_card(parent, title, colspan=1, rowspan=1):
    frame = tk.Frame(parent, bg=CARD, bd=0, highlightthickness=1,
                     highlightbackground=BORDER)
    lbl = tk.Label(frame, text=title.upper(), bg=CARD, fg=TEXT,
                   font=("Consolas", 11, "bold"), anchor="w", padx=8, pady=6)
    lbl.pack(fill="x")
    return frame


class MetricCard:
    """Big number + unit + optional colour threshold + sparkline."""
    def __init__(self, parent, title, unit="", fmt="{:.1f}",
                 low_good=False, warn=None, crit=None, spark_color=BLUE):
        self.frame = make_card(parent, title)
        self.unit = unit
        self.fmt = fmt
        self.low_good = low_good
        self.warn = warn
        self.crit = crit

        self.val_var = tk.StringVar(value="--")
        self.val_lbl = tk.Label(self.frame, textvariable=self.val_var,
                                bg=CARD, fg=TEXT,
                                font=("Consolas", 26, "bold"),
                                anchor="center")
        self.val_lbl.pack(fill="x", padx=8)

        self.unit_lbl = tk.Label(self.frame, text=unit, bg=CARD, fg=TEXT,
                                 font=("Consolas", 11), anchor="center")
        self.unit_lbl.pack(fill="x")

        self.spark = Sparkline(self.frame, color=spark_color, height=56,
                               unit=unit, fmt=fmt)
        self.spark.pack(fill="x", padx=4, pady=4)

    def update(self, value):
        if value is None:
            self.val_var.set("--")
            return
        self.val_var.set(self.fmt.format(value))
        self.spark.push(value)

        color = GREEN
        if self.crit is not None:
            if self.low_good:
                if value >= self.crit:
                    color = RED
                elif value >= self.warn:
                    color = YELLOW
            else:
                if value <= self.crit:
                    color = RED
                elif self.warn is not None and value <= self.warn:
                    color = YELLOW
        self.val_lbl.configure(fg=color)


class StatusPanel:
    """Shows dish status flags and pointing info derived from confirmed fields."""
    def __init__(self, parent):
        self.frame = make_card(parent, "Status")
        self.rows = {}
        for key in ["Obstructed", "Obstruction s", "Ethernet",
                    "Elevation", "Azimuth", "SNR", "Uptime", "Firmware"]:
            row = tk.Frame(self.frame, bg=CARD)
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=f"{key}:", bg=CARD, fg=DIM,
                     font=("Consolas", 11), width=14, anchor="w").pack(side="left")
            var = tk.StringVar(value="--")
            lbl = tk.Label(row, textvariable=var, bg=CARD, fg=TEXT,
                           font=("Consolas", 11), anchor="w")
            lbl.pack(side="left")
            self.rows[key] = (var, lbl)

    def set(self, key, value, color=None):
        if key in self.rows:
            var, lbl = self.rows[key]
            var.set(str(value))
            if color:
                lbl.configure(fg=color)


class InfoPanel:
    def __init__(self, parent):
        self.frame = make_card(parent, "Dish Info")
        self.rows = {}
        for key in ["ID", "Hardware", "Firmware", "Uptime"]:
            row = tk.Frame(self.frame, bg=CARD)
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=f"{key}:", bg=CARD, fg=DIM,
                     font=("Consolas", 11), width=10, anchor="w").pack(side="left")
            var = tk.StringVar(value="--")
            tk.Label(row, textvariable=var, bg=CARD, fg=TEXT,
                     font=("Consolas", 11), anchor="w").pack(side="left")
            self.rows[key] = var

    def set(self, key, value):
        if key in self.rows:
            self.rows[key].set(str(value))


class StatusBar:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg="#0a0f16", height=22)
        self.frame.pack(fill="x", side="bottom")
        self.left = tk.Label(self.frame, bg="#0a0f16", fg=DIM,
                             font=("Consolas", 10), anchor="w", padx=8)
        self.left.pack(side="left")
        self.right = tk.Label(self.frame, bg="#0a0f16", fg=DIM,
                              font=("Consolas", 10), anchor="e", padx=8)
        self.right.pack(side="right")

    def update(self, ok, msg=""):
        if ok:
            self.left.configure(text=f"● Connected  {msg}", fg=GREEN)
        else:
            self.left.configure(text=f"● {msg}", fg=RED)
        self.right.configure(text=time.strftime("%H:%M:%S"))


# ---------------------------------------------------------------------------
# IP geolocation (best-effort — Starlink does not expose GPS via gRPC)
# ---------------------------------------------------------------------------

def fetch_geolocation():
    """Returns dict with lat, lon, city, region, country, isp or raises."""
    import urllib.request, json
    with urllib.request.urlopen("http://ip-api.com/json?fields=lat,lon,city,regionName,country,isp,query", timeout=6) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Pointing / sky position canvas
# ---------------------------------------------------------------------------

class PointingCanvas(tk.Canvas):
    """Draws the dish pointing direction as a dot on a hemisphere projection."""
    SIZE = 160

    def __init__(self, parent):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=CARD, highlightthickness=0)
        self._el = None
        self._az = None
        self._draw_base()

    def _draw_base(self):
        self.delete("all")
        cx = cy = self.SIZE // 2
        r = cx - 10
        self.create_oval(cx-r, cy-r, cx+r, cy+r, outline=BORDER, fill="#0d1117")
        for ring_pct in [0.33, 0.66]:
            rr = int(r * ring_pct)
            self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr, outline=BORDER, dash=(2,4))
        for angle in range(0, 360, 45):
            x = cx + r * math.sin(math.radians(angle))
            y = cy - r * math.cos(math.radians(angle))
            self.create_line(cx, cy, x, y, fill=BORDER, dash=(1, 6))
        self.create_text(cx, cy-r-6, text="N", fill=DIM, font=("Consolas", 7))
        self.create_text(cx+r+6, cy, text="E", fill=DIM, font=("Consolas", 7))
        self.create_text(cx, cy, text="No data", fill=DIM, font=("Consolas", 8))

    def update(self, elevation_deg, azimuth_deg, obstructed=False):
        self.delete("all")
        cx = cy = self.SIZE // 2
        r = cx - 10
        self.create_oval(cx-r, cy-r, cx+r, cy+r, outline=BORDER, fill="#0d1117")
        for ring_pct in [0.33, 0.66]:
            rr = int(r * ring_pct)
            self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr, outline=BORDER, dash=(2,4))
        self.create_text(cx, cy-r-6, text="N", fill=DIM, font=("Consolas", 7))
        self.create_text(cx+r+6, cy, text="E", fill=DIM, font=("Consolas", 7))
        # Convert az/el to canvas coords (0° el = edge, 90° el = center)
        dist = r * (1.0 - elevation_deg / 90.0)
        x = cx + dist * math.sin(math.radians(azimuth_deg))
        y = cy - dist * math.cos(math.radians(azimuth_deg))
        dot_color = RED if obstructed else TEAL
        self.create_oval(x-8, y-8, x+8, y+8, fill=dot_color, outline="")
        self.create_text(cx, cy+r+10,
                         text=f"Az {azimuth_deg:.1f}°  El {elevation_deg:.1f}°",
                         fill=TEXT, font=("Consolas", 8))


# ---------------------------------------------------------------------------
# Second-window widgets
# ---------------------------------------------------------------------------

class TiltGauge(tk.Canvas):
    """Circular gauge showing dish tilt from vertical."""
    SIZE = 150

    def __init__(self, parent):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=CARD, highlightthickness=0)
        self._draw(None)

    def _draw(self, tilt_deg):
        self.delete("all")
        cx = cy = self.SIZE // 2
        r = cx - 14

        # Arc background (grey track)
        self.create_arc(cx-r, cy-r, cx+r, cy+r, start=210, extent=120,
                        outline=BORDER, style="arc", width=8)

        if tilt_deg is not None:
            # Map 0–20° tilt onto the 120° arc
            frac = min(tilt_deg / 20.0, 1.0)
            color = GREEN if tilt_deg < 5 else (YELLOW if tilt_deg < 10 else RED)
            self.create_arc(cx-r, cy-r, cx+r, cy+r, start=210,
                            extent=int(120 * frac), outline=color,
                            style="arc", width=8)
            self.create_text(cx, cy - 8, text=f"{tilt_deg:.1f}°",
                             fill=color, font=("Consolas", 18, "bold"), anchor="center")
        else:
            self.create_text(cx, cy - 8, text="--",
                             fill=DIM, font=("Consolas", 18, "bold"), anchor="center")

        self.create_text(cx, cy + 12, text="tilt from vertical",
                         fill=DIM, font=("Consolas", 8), anchor="center")
        self.create_text(cx - r + 4, cy + r - 4, text="0°", fill=DIM, font=("Consolas", 7))
        self.create_text(cx + r - 4, cy + r - 4, text="20°", fill=DIM, font=("Consolas", 7))

    def update(self, tilt_deg):
        self._draw(tilt_deg)


class SectorChart(tk.Canvas):
    """Ring bar chart for per-sector signal quality (10 sectors)."""
    SIZE = 200

    def __init__(self, parent):
        super().__init__(parent, width=self.SIZE, height=self.SIZE,
                         bg=CARD, highlightthickness=0)
        self._draw([])

    def _draw(self, values):
        self.delete("all")
        cx = cy = self.SIZE // 2
        r_outer = cx - 12
        r_inner = cx - 45

        n = 10
        gap_deg = 4
        sector_deg = (360 / n) - gap_deg

        lo, hi = 20, 50  # expected dB range for display

        for i, val in enumerate(values[:n]):
            start = 270 + i * (360 / n) - sector_deg / 2
            frac = max(0, min(1, (val - lo) / (hi - lo)))
            bar_r = r_inner + frac * (r_outer - r_inner)
            color = GREEN if frac > 0.6 else (YELLOW if frac > 0.3 else RED)

            # Background track
            self.create_arc(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                            start=start, extent=sector_deg,
                            fill=BORDER, outline="")
            self.create_arc(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                            start=start, extent=sector_deg,
                            fill=CARD, outline="")

            # Value fill
            self.create_arc(cx - bar_r, cy - bar_r, cx + bar_r, cy + bar_r,
                            start=start, extent=sector_deg,
                            fill=color, outline="")
            self.create_arc(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                            start=start, extent=sector_deg,
                            fill=CARD, outline="")

            # Sector label
            label_r = r_outer + 10
            angle_rad = math.radians(start + sector_deg / 2)
            lx = cx + label_r * math.cos(angle_rad)
            ly = cy - label_r * math.sin(angle_rad)
            self.create_text(lx, ly, text=str(val),
                             fill=TEXT, font=("Consolas", 7), anchor="center")

        if not values:
            self.create_text(cx, cy, text="No Data", fill=DIM, font=("Consolas", 9))
        else:
            self.create_text(cx, cy - 8, text="Signal",
                             fill=TEXT, font=("Consolas", 9, "bold"))
            self.create_text(cx, cy + 8, text="per sector",
                             fill=DIM, font=("Consolas", 8))

    def update(self, sector_signal_msg):
        vals = [getattr(sector_signal_msg, f"s{i}", 0) for i in range(1, 11)]
        if any(v > 0 for v in vals):
            self._draw(vals)


class ReadyStatesPanel:
    def __init__(self, parent):
        self.frame = make_card(parent, "Ready States")
        self._flags = [("cady", "CADY"), ("scp", "SCP"), ("l1l2", "L1/L2"),
                       ("xphy", "XPHY"), ("aap", "AAP")]
        self._labels = {}
        row = tk.Frame(self.frame, bg=CARD)
        row.pack(fill="x", padx=8, pady=6)
        for attr, name in self._flags:
            col = tk.Frame(row, bg=CARD)
            col.pack(side="left", expand=True)
            dot = tk.Label(col, text="●", bg=CARD, fg=DIM, font=("Consolas", 14))
            dot.pack()
            tk.Label(col, text=name, bg=CARD, fg=DIM, font=("Consolas", 8)).pack()
            self._labels[attr] = dot

    def update(self, ready_states_msg):
        for attr, _ in self._flags:
            ok = getattr(ready_states_msg, attr, False)
            self._labels[attr].configure(fg=GREEN if ok else RED)


class DetailInfoPanel:
    """Shows extended fields for the detail window."""
    def __init__(self, parent):
        self.frame = make_card(parent, "Extended Info")
        self.rows = {}
        keys = ["Country", "GPS Valid", "GPS Accuracy", "Obstruction Score",
                "Sec. Elevation", "Sec. Azimuth", "Obstr. Events", "Dish ID"]
        for key in keys:
            row = tk.Frame(self.frame, bg=CARD)
            row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text=f"{key}:", bg=CARD, fg=DIM,
                     font=("Consolas", 10), width=16, anchor="w").pack(side="left")
            var = tk.StringVar(value="--")
            lbl = tk.Label(row, textvariable=var, bg=CARD, fg=TEXT,
                           font=("Consolas", 10), anchor="w")
            lbl.pack(side="left")
            self.rows[key] = (var, lbl)

    def set(self, key, value, color=None):
        if key in self.rows:
            var, lbl = self.rows[key]
            var.set(str(value))
            lbl.configure(fg=color or TEXT)


LOCATION_FILE = Path(__file__).parent / "location.json"

def _load_config():
    try:
        import json
        d = json.loads(LOCATION_FILE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _save_config(d):
    import json
    LOCATION_FILE.write_text(json.dumps(d, indent=2))

def load_saved_location():
    """Return (lat, lon, label) from disk, or (None, None, '')."""
    d = _load_config()
    return d.get("lat"), d.get("lon"), d.get("label", "")

def save_location(lat, lon, label=""):
    d = _load_config()
    d.update({"lat": lat, "lon": lon, "label": label})
    _save_config(d)

def load_gps_port():
    """Return persisted GPS port, or GPS_PORT default."""
    return _load_config().get("gps_port", GPS_PORT)

def save_gps_port(port):
    d = _load_config()
    d["gps_port"] = port
    _save_config(d)


class LocationPanel:
    """Two-column panel: ground station (IP-based) on left, user-set dish location on right."""

    def __init__(self, parent, on_set_location):
        self.frame = make_card(parent, "Location")
        self._on_set = on_set_location

        body = tk.Frame(self.frame, bg=CARD)
        body.pack(fill="both", expand=True, padx=4, pady=2)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # --- Ground station column ---
        gs_hdr = tk.Label(body, text="Ground Station (IP)", bg=CARD, fg=ORANGE,
                          font=("Consolas", 9, "bold"), anchor="w")
        gs_hdr.grid(row=0, column=0, sticky="w", padx=6, pady=(2, 0))

        self._gs = {}
        gs_keys = [("Lat/Lon", "gs_latlon"), ("City", "gs_city"),
                   ("Region", "gs_region"), ("ISP", "gs_isp"), ("IP", "gs_ip")]
        for r, (label, key) in enumerate(gs_keys, start=1):
            tk.Label(body, text=f"{label}:", bg=CARD, fg=DIM,
                     font=("Consolas", 10), anchor="w").grid(
                         row=r, column=0, sticky="w", padx=(10, 2))
            var = tk.StringVar(value="--")
            tk.Label(body, textvariable=var, bg=CARD, fg=TEXT,
                     font=("Consolas", 10), anchor="w").grid(
                         row=r, column=0, sticky="e", padx=(0, 6))
            self._gs[key] = var

        # --- Separator ---
        tk.Frame(body, bg=BORDER, width=1).grid(
            row=0, column=0, rowspan=8, sticky="nse", padx=2)

        # --- Dish location column ---
        self._dish_hdr_var = tk.StringVar(value="Dish Location (set)")
        dish_hdr = tk.Label(body, textvariable=self._dish_hdr_var, bg=CARD, fg=TEAL,
                            font=("Consolas", 9, "bold"), anchor="w")
        dish_hdr.grid(row=0, column=1, sticky="w", padx=6, pady=(2, 0))

        # GPS status row
        self._gps_var = tk.StringVar(value="GPS: --")
        self._gps_label = tk.Label(body, textvariable=self._gps_var, bg=CARD, fg=DIM,
                                   font=("Consolas", 9), anchor="w")
        self._gps_label.grid(row=1, column=1, sticky="w", padx=(10, 2))

        self._dish = {}
        # Lat/Lon row: key on left, value on right (same cell)
        tk.Label(body, text="Lat/Lon:", bg=CARD, fg=DIM,
                 font=("Consolas", 10), anchor="w").grid(
                     row=2, column=1, sticky="w", padx=(10, 2))
        _ll_var = tk.StringVar(value="--")
        self._dish["dish_latlon"] = _ll_var
        tk.Label(body, textvariable=_ll_var, bg=CARD, fg=TEAL,
                 font=("Consolas", 10), anchor="e").grid(
                     row=2, column=1, sticky="e", padx=(0, 6))
        # Label row
        tk.Label(body, text="Label:", bg=CARD, fg=DIM,
                 font=("Consolas", 10), anchor="w").grid(
                     row=3, column=1, sticky="w", padx=(10, 2))
        _lbl_var = tk.StringVar(value="--")
        self._dish["dish_label"] = _lbl_var
        tk.Label(body, textvariable=_lbl_var, bg=CARD, fg=TEAL,
                 font=("Consolas", 10), anchor="e").grid(
                     row=3, column=1, sticky="e", padx=(0, 6))

        # Distance row
        tk.Label(body, text="Distance:", bg=CARD, fg=DIM,
                 font=("Consolas", 10), anchor="w").grid(
                     row=4, column=1, sticky="w", padx=(10, 2))
        self._dist_var = tk.StringVar(value="--")
        tk.Label(body, textvariable=self._dist_var, bg=CARD, fg=YELLOW,
                 font=("Consolas", 10, "bold"), anchor="w").grid(
                     row=5, column=1, sticky="w", padx=(10, 2))

        # COM port selector + connect button
        port_frame = tk.Frame(body, bg=CARD)
        port_frame.grid(row=6, column=1, sticky="w", padx=8, pady=(4, 2))

        tk.Label(port_frame, text="GPS Port:", bg=CARD, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")

        self._port_var = tk.StringVar(value=GPS_PORT)
        self._port_combo = ttk.Combobox(
            port_frame, textvariable=self._port_var,
            width=8, font=("Consolas", 9), state="readonly")
        self._port_combo.pack(side="left", padx=(4, 2))
        self._port_combo.bind("<ButtonPress>", self._refresh_ports)

        self._connect_btn = tk.Button(
            port_frame, text="Connect", command=self._on_connect_gps,
            bg=BORDER, fg=TEXT, font=("Consolas", 9),
            relief="flat", cursor="hand2", padx=6, pady=2)
        self._connect_btn.pack(side="left", padx=2)

        # Set Location button (manual override)
        btn = tk.Button(body, text="Set Manual…", command=self._on_set,
                        bg=BORDER, fg=TEXT, font=("Consolas", 10),
                        relief="flat", cursor="hand2", padx=6, pady=3)
        btn.grid(row=7, column=1, sticky="w", padx=8, pady=(0, 6))

        self._gs_lat = None
        self._gs_lon = None
        self._dish_lat = None
        self._dish_lon = None
        self._on_connect_gps_cb = None  # set by Dashboard after construction

    def _refresh_ports(self, _event=None):
        ports = list_serial_ports()
        current = self._port_var.get()
        # Always keep the currently selected port in the list even if not detected
        if current and current not in ports:
            ports = [current] + ports
        if not ports:
            ports = [GPS_PORT]
        self._port_combo["values"] = ports
        if not self._port_var.get():
            self._port_var.set(ports[0])

    def _on_connect_gps(self):
        if self._on_connect_gps_cb:
            self._on_connect_gps_cb(self._port_var.get())

    def set_ground_station(self, lat, lon, city, region, isp, ip):
        self._gs_lat, self._gs_lon = lat, lon
        self._gs["gs_latlon"].set(f"{lat:.4f}, {lon:.4f}")
        self._gs["gs_city"].set(city)
        self._gs["gs_region"].set(region)
        self._gs["gs_isp"].set(isp)
        self._gs["gs_ip"].set(ip)
        self._update_distance()

    def set_gps_connecting(self, port):
        self._gps_var.set(f"GPS: connecting {port}…")
        self._gps_label.config(fg=DIM)

    def set_gps_status(self, lat, lon, quality, num_sats):
        """Called via root.after from the GPS reader thread."""
        sats_txt = f" ({num_sats} sats)" if num_sats else ""
        if quality == -1:
            self._gps_var.set("GPS: pyserial not installed")
            self._gps_label.config(fg=RED)
        elif quality == -2:
            self._gps_var.set("GPS: port unavailable")
            self._gps_label.config(fg=RED)
        elif quality == 0 or lat is None:
            # Distinguish between initial acquisition and re-acquisition after fix loss
            current = self._dish_hdr_var.get()
            if "GPS" in current and "set" not in current:
                self._gps_var.set(f"GPS: Reacquiring…{sats_txt}")
            else:
                self._gps_var.set(f"GPS: Acquiring…{sats_txt}")
            self._gps_label.config(fg=YELLOW)
        else:
            self._gps_var.set(f"GPS: Fixed{sats_txt}")
            self._gps_label.config(fg=GREEN)
            self._dish_hdr_var.set("Dish Location (GPS)")
            self.set_dish_location(lat, lon, "GPS Fix")

    def set_dish_location(self, lat, lon, label=""):
        self._dish_lat, self._dish_lon = lat, lon
        self._dish["dish_latlon"].set(f"{lat:.4f}, {lon:.4f}")
        self._dish["dish_label"].set(label or "")
        self._update_distance()

    def _update_distance(self):
        if None in (self._gs_lat, self._gs_lon, self._dish_lat, self._dish_lon):
            return
        km = _haversine_km(self._dish_lat, self._dish_lon,
                           self._gs_lat, self._gs_lon)
        self._dist_var.set(f"{km:.0f} km to ground station")


def list_serial_ports():
    """Return sorted list of available COM port names."""
    try:
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        return sorted(ports, key=lambda s: int(s.replace("COM", "")) if s.startswith("COM") else 0)
    except Exception:
        return []


def _nmea_to_deg(value, hemi):
    """Convert NMEA DDDMM.MMMM + hemisphere char to signed decimal degrees."""
    if not value or not hemi:
        return None
    try:
        raw = float(value)
    except ValueError:
        return None
    deg = int(raw / 100)
    minutes = raw - deg * 100
    result = deg + minutes / 60.0
    if hemi in ("S", "W"):
        result = -result
    return result


class GpsReader:
    """Background thread that reads NMEA sentences from a serial port and parses position."""

    def __init__(self, port, baud, on_update):
        self._on_update = on_update  # callable(lat_or_None, lon_or_None, quality, num_sats)
        self._stop = threading.Event()
        self._sats_in_view = 0   # accumulated from GSV sentences
        self._thread = threading.Thread(
            target=self._run, args=(port, baud), daemon=True, name="gps-reader")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self, port, baud):
        try:
            import serial
        except ImportError:
            self._on_update(None, None, -1, 0)  # serial not installed
            return

        while not self._stop.is_set():
            try:
                with serial.Serial(port, baud, timeout=2) as ser:
                    while not self._stop.is_set():
                        try:
                            raw = ser.readline()
                            line = raw.decode("ascii", errors="ignore").strip()
                            self._parse(line)
                        except Exception:
                            pass
            except Exception:
                # Port unavailable — retry after a pause
                self._on_update(None, None, -2, 0)
                self._stop.wait(5)

    def _parse(self, line):
        if not line.startswith("$") or "*" not in line:
            return
        payload = line.split("*")[0]
        parts = payload.split(",")
        sentence = parts[0][1:]  # e.g. "GPGGA"

        if sentence in ("GPGGA", "GNGGA", "GLGGA"):
            # $xxGGA,time,lat,NS,lon,EW,quality,num_sats,...
            if len(parts) < 9:
                return
            quality = int(parts[6]) if parts[6].isdigit() else 0
            tracked = int(parts[7]) if parts[7].isdigit() else 0
            # prefer GSV in-view count when available; fall back to tracked count
            num_sats = self._sats_in_view if self._sats_in_view else tracked
            lat = _nmea_to_deg(parts[2], parts[3])
            lon = _nmea_to_deg(parts[4], parts[5])
            self._on_update(lat, lon, quality, num_sats)

        elif sentence in ("GPRMC", "GNRMC", "GLRMC"):
            # $xxRMC,time,status,lat,NS,lon,EW,...
            if len(parts) < 7:
                return
            status = parts[2]  # A=active, V=void
            lat = _nmea_to_deg(parts[3], parts[4])
            lon = _nmea_to_deg(parts[5], parts[6])
            quality = 1 if status == "A" else 0
            self._on_update(lat, lon, quality, self._sats_in_view)

        elif sentence.endswith("GSV"):
            # $xxGSV,numMsg,msgNum,numSVsInView,...
            # Accumulate total-in-view across all constellations; take the max seen
            if len(parts) >= 4 and parts[3].isdigit():
                count = int(parts[3])
                if count > self._sats_in_view:
                    self._sats_in_view = count


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Main Dashboard
# ---------------------------------------------------------------------------

class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Starlink Monitor")
        root.configure(bg=BG)
        root.geometry("1200x760")
        root.minsize(1000, 640)

        self._build_ui()
        self._build_detail_window()
        self._client = None
        self._error_count = 0
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        threading.Thread(target=self._fetch_location, daemon=True).start()
        # Restore saved dish location if present (GPS will override when it gets a fix)
        lat, lon, label = load_saved_location()
        if lat is not None:
            self.location_panel.set_dish_location(lat, lon, label)
        # Start GPS reader; populate port combo with available ports
        self._gps_reader = None
        self.location_panel._on_connect_gps_cb = self._reconnect_gps
        self.location_panel._refresh_ports()
        saved_port = load_gps_port()
        self.location_panel._port_var.set(saved_port)
        self._reconnect_gps(saved_port)

    def _reconnect_gps(self, port):
        save_gps_port(port)
        if self._gps_reader is not None:
            self._gps_reader.stop()
        self._gps_reader = GpsReader(port, GPS_BAUD, self._on_gps_update)
        self.location_panel.set_gps_connecting(port)

    def _on_gps_update(self, lat, lon, quality, num_sats):
        self.root.after(0, self.location_panel.set_gps_status,
                        lat, lon, quality, num_sats)

    # ------------------------------------------------------------------
    def _build_ui(self):
        title = tk.Label(self.root, text="  STARLINK  DISH  MONITOR",
                         bg=BG, fg=BLUE, font=("Consolas", 14, "bold"),
                         anchor="w", pady=8, padx=12)
        title.pack(fill="x")
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        self.status_bar = StatusBar(self.root)

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)
        main.columnconfigure((0, 1, 2, 3), weight=1, uniform="col")
        main.rowconfigure((0, 1, 2), weight=1, uniform="row")

        # Row 0 — throughput + latency metrics
        self.card_latency = MetricCard(
            main, "Ping Latency", unit="ms", fmt="{:.1f}",
            low_good=True, warn=80, crit=150, spark_color=TEAL)
        self.card_latency.frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self.card_drop = MetricCard(
            main, "Packet Loss", unit="%", fmt="{:.2f}",
            low_good=True, warn=1.0, crit=5.0, spark_color=ORANGE)
        self.card_drop.frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)

        self.card_dl = MetricCard(
            main, "Download", unit="Mbps", fmt="{:.1f}",
            spark_color=BLUE)
        self.card_dl.frame.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)

        self.card_ul = MetricCard(
            main, "Upload", unit="Mbps", fmt="{:.1f}",
            spark_color=PURPLE)
        self.card_ul.frame.grid(row=0, column=3, sticky="nsew", padx=4, pady=4)

        # Row 1 — SNR, dish info, location, status
        self.card_snr = MetricCard(
            main, "SNR", unit="dB", fmt="{:.1f}",
            spark_color=GREEN)
        self.card_snr.frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        self.info_panel = InfoPanel(main)
        self.info_panel.frame.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

        self.location_panel = LocationPanel(main, self._open_set_location)
        self.location_panel.frame.grid(row=1, column=2, sticky="nsew", padx=4, pady=4)

        self.status_panel = StatusPanel(main)
        self.status_panel.frame.grid(row=1, column=3, sticky="nsew", padx=4, pady=4)

        # Row 2 — throughput history chart
        hist_frame = make_card(main, "Throughput History  (last 1200 s / 20 min)")
        hist_frame.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=4, pady=4)
        self.hist_canvas = tk.Canvas(hist_frame, bg=CARD, highlightthickness=0, height=100)
        self.hist_canvas.pack(fill="both", expand=True, padx=6, pady=4)
        self._dl_history: deque = deque(maxlen=HISTORY_LEN)
        self._ul_history: deque = deque(maxlen=HISTORY_LEN)
        self.hist_canvas.bind("<Configure>", lambda _: self._draw_history())

    def _build_detail_window(self):
        """Second window: sky position, tilt, sector signal, extended info."""
        self._detail = tk.Toplevel(self.root)
        self._detail.title("Starlink Detail")
        self._detail.configure(bg=BG)
        self._detail.geometry("900x680")
        self._detail.minsize(760, 560)
        # Keep alive with main window
        self._detail.protocol("WM_DELETE_WINDOW",
                               lambda: self._detail.withdraw())

        title = tk.Label(self._detail, text="  STARLINK  DETAIL  VIEW",
                         bg=BG, fg=PURPLE, font=("Consolas", 14, "bold"),
                         anchor="w", pady=8, padx=12)
        title.pack(fill="x")
        tk.Frame(self._detail, bg=BORDER, height=1).pack(fill="x")

        main = tk.Frame(self._detail, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)
        main.columnconfigure((0, 1, 2), weight=1, uniform="col")
        main.rowconfigure((0, 1), weight=1, uniform="row")

        # Sky position (moved from main window)
        sky_frame = make_card(main, "Sky Position")
        sky_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.pointing_canvas = PointingCanvas(sky_frame)
        self.pointing_canvas.pack(expand=True, pady=4)

        # Dish tilt gauge
        tilt_frame = make_card(main, "Dish Tilt")
        tilt_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.tilt_gauge = TiltGauge(tilt_frame)
        self.tilt_gauge.pack(expand=True, pady=8)

        # Ready states
        self.ready_panel = ReadyStatesPanel(main)
        self.ready_panel.frame.grid(row=0, column=2, sticky="nsew", padx=4, pady=4)

        # Sector signal ring chart (spans 2 cols)
        sector_frame = make_card(main, "Per-Sector Signal Quality")
        sector_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        self.sector_chart = SectorChart(sector_frame)
        self.sector_chart.pack(expand=True)

        # Extended info
        self.detail_info = DetailInfoPanel(main)
        self.detail_info.frame.grid(row=1, column=2, sticky="nsew", padx=4, pady=4)

    # ------------------------------------------------------------------
    def _fetch_location(self):
        try:
            geo = fetch_geolocation()
            lat, lon = geo.get("lat", 0), geo.get("lon", 0)
            def apply():
                self.location_panel.set_ground_station(
                    lat, lon,
                    geo.get("city", "--"),
                    geo.get("regionName", "--"),
                    geo.get("isp", "--"),
                    geo.get("query", "--"),
                )
            self.root.after(0, apply)
        except Exception:
            pass

    def _open_set_location(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Set Dish Location")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        pad = dict(padx=12, pady=6)
        tk.Label(dlg, text="Enter your dish coordinates:", bg=BG, fg=TEXT,
                 font=("Consolas", 11, "bold")).grid(
                     row=0, column=0, columnspan=2, sticky="w", **pad)

        fields = [("Latitude  (e.g. 47.6062)", "lat"),
                  ("Longitude (e.g. -122.3321)", "lon"),
                  ("Label     (optional)", "label")]
        entries = {}
        saved_lat, saved_lon, saved_label = load_saved_location()
        prefill = {"lat": str(saved_lat) if saved_lat is not None else "",
                   "lon": str(saved_lon) if saved_lon is not None else "",
                   "label": saved_label or ""}
        for r, (lbl_text, key) in enumerate(fields, start=1):
            tk.Label(dlg, text=lbl_text, bg=BG, fg=DIM,
                     font=("Consolas", 10)).grid(row=r, column=0, sticky="w", **pad)
            var = tk.StringVar(value=prefill[key])
            e = tk.Entry(dlg, textvariable=var, bg=CARD, fg=TEXT,
                         insertbackground=TEXT, font=("Consolas", 11), width=28,
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BLUE)
            e.grid(row=r, column=1, sticky="w", **pad)
            entries[key] = var

        err_var = tk.StringVar()
        tk.Label(dlg, textvariable=err_var, bg=BG, fg=RED,
                 font=("Consolas", 9)).grid(row=4, column=0, columnspan=2, **pad)

        def on_save():
            try:
                lat = float(entries["lat"].get().strip())
                lon = float(entries["lon"].get().strip())
            except ValueError:
                err_var.set("Latitude and longitude must be numbers.")
                return
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                err_var.set("Lat must be -90…90, Lon -180…180.")
                return
            label = entries["label"].get().strip()
            save_location(lat, lon, label)
            self.location_panel.set_dish_location(lat, lon, label)
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg=BG)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=8)
        tk.Button(btn_frame, text="Save", command=on_save,
                  bg=BLUE, fg=BG, font=("Consolas", 11, "bold"),
                  relief="flat", padx=16, pady=4, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_frame, text="Cancel", command=dlg.destroy,
                  bg=BORDER, fg=TEXT, font=("Consolas", 11),
                  relief="flat", padx=16, pady=4, cursor="hand2").pack(side="left")

    def _connect(self):
        if self._client is None:
            self._client = StarlinkClient()

    def _poll_loop(self):
        first = True
        while True:
            try:
                self._connect()
                if first:
                    first = False
                    hist = self._client.get_history()
                    self.root.after(0, self._seed_history, hist)
                status = self._client.get_status()
                self.root.after(0, self._apply_status, status)
                self._error_count = 0
            except Exception as e:
                self._error_count += 1
                self._client = None
                first = True  # re-seed on reconnect
                msg = str(e)[:80]
                self.root.after(0, self.status_bar.update, False,
                                f"Error ({self._error_count}): {msg}")
            time.sleep(POLL_INTERVAL)

    def _seed_history(self, h):
        """Pre-populate sparklines from the dish's onboard 900-second history buffer."""
        dl  = [v / 1e6 for v in h.downlink_throughput_bps]
        ul  = [v / 1e6 for v in h.uplink_throughput_bps]
        lat = list(h.pop_ping_latency_ms)
        drop = [v * 100 for v in h.pop_ping_drop_rate]
        snr  = list(h.snr_db)

        for v in lat:  self.card_latency.spark.push(v)
        for v in drop: self.card_drop.spark.push(v)
        for v in dl:   self.card_dl.spark.push(v)
        for v in ul:   self.card_ul.spark.push(v)
        for v in snr:  self.card_snr.spark.push(v)

        self._dl_history.extend(dl)
        self._ul_history.extend(ul)
        self._draw_history()

    def _apply_status(self, s):
        dl = s.downlink_throughput_bps / 1e6
        ul = s.uplink_throughput_bps / 1e6
        snr = s.signal_stats.snr_db
        el = s.boresight_elevation_deg
        az = s.boresight_azimuth_deg
        obstructed = s.obstruction_stats.currently_obstructed

        # Main window metrics
        self.card_latency.update(s.pop_ping_latency_ms)
        self.card_drop.update(s.pop_ping_drop_rate * 100)
        self.card_dl.update(dl)
        self.card_ul.update(ul)
        self.card_snr.update(snr if snr > 0 else None)

        di = s.device_info
        ds = s.device_state
        uptime_h = ds.uptime_s // 3600
        uptime_m = (ds.uptime_s % 3600) // 60
        self.info_panel.set("ID", di.id)
        self.info_panel.set("Hardware", di.hardware_version)
        self.info_panel.set("Firmware", di.software_version)
        self.info_panel.set("Uptime", f"{uptime_h}h {uptime_m}m")

        obstr_color = RED if obstructed else GREEN
        self.status_panel.set("Obstructed", "YES" if obstructed else "No", obstr_color)
        self.status_panel.set("Obstruction s", s.obstruction_stats.obstruction_duration_s)
        self.status_panel.set("Ethernet", f"{s.eth_speed_mbps} Mbps")
        self.status_panel.set("Elevation", f"{el:.1f}°")
        self.status_panel.set("Azimuth", f"{az:.1f}°")
        self.status_panel.set("SNR", f"{snr:.1f} dB" if snr > 0 else "--")
        self.status_panel.set("Uptime", f"{uptime_h}h {uptime_m}m")
        self.status_panel.set("Firmware", di.software_version)

        self._dl_history.append(dl)
        self._ul_history.append(ul)
        self._draw_history()

        # Detail window updates
        self.pointing_canvas.update(el, az, obstructed)

        # Dish tilt from orientation quaternion (fields: x=1, w=2, y=3, z=4)
        q = s.tilt_quaternion
        w, x, y, z = q.w, q.x, q.y, q.z
        if abs(w) > 0.01 or abs(x) > 0.01:
            # Rotate [0,0,1] by quaternion, tilt = angle between result and [0,0,1]
            rz = w*w - x*x - y*y + z*z
            tilt_deg = math.degrees(math.acos(max(-1.0, min(1.0, rz))))
            self.tilt_gauge.update(tilt_deg)

        self.sector_chart.update(s.sector_signal)
        self.ready_panel.update(s.ready_states)

        # Extended info panel
        gps_valid = s.gps_status.valid
        self.detail_info.set("Country", di.country_code)
        self.detail_info.set("GPS Valid", "Yes" if gps_valid else "No",
                             GREEN if gps_valid else RED)
        gps_acc = s.gps_status.accuracy
        acc_color = GREEN if gps_acc < 5 else (YELLOW if gps_acc < 20 else RED)
        self.detail_info.set("GPS Accuracy", f"{gps_acc:.2f} m", acc_color)
        obs_score = s.signal_stats.obstruction_score
        obs_color = GREEN if obs_score < 0.2 else (YELLOW if obs_score < 0.5 else RED)
        self.detail_info.set("Obstruction Score", f"{obs_score:.3f}", obs_color)
        self.detail_info.set("Sec. Elevation", f"{s.signal_stats.secondary_elevation_deg:.1f}°")
        self.detail_info.set("Sec. Azimuth",   f"{s.signal_stats.secondary_azimuth_deg:.1f}°")
        self.detail_info.set("Obstr. Events",  s.obstruction_stats.obstruction_event_count)
        self.detail_info.set("Dish ID", di.id)

        self.status_bar.update(True,
            f"dl {dl:.1f} Mbps  ul {ul:.1f} Mbps  "
            f"latency {s.pop_ping_latency_ms:.0f} ms  "
            f"loss {s.pop_ping_drop_rate*100:.2f}%  "
            f"SNR {snr:.1f} dB")

    def _draw_history(self):
        c = self.hist_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4 or h < 4:
            return

        all_vals = list(self._dl_history) + list(self._ul_history)
        lo = 0
        hi = max(all_vals) if all_vals else 1
        if hi == lo:
            hi = lo + 1
        ticks = _nice_ticks(lo, hi, n=4)

        LMARGIN = 48
        TOP = 22     # space for legend
        BOTTOM = 16  # space for X-axis labels
        plot_w = w - LMARGIN - 6
        plot_h = h - TOP - BOTTOM

        def to_y(v):
            return (h - BOTTOM) - (v - lo) / (hi - lo) * plot_h

        def to_x(i, n):
            return LMARGIN + i * plot_w / max(n - 1, 1)

        # Y gridlines + labels
        for tick in ticks:
            y = to_y(tick)
            c.create_line(LMARGIN, y, w - 6, y, fill=BORDER, dash=(2, 4))
            c.create_text(LMARGIN - 4, y, text=f"{tick:.1f}",
                          fill=TEXT, font=("Consolas", 9), anchor="e")

        # Axes
        c.create_line(LMARGIN, TOP, LMARGIN, h - BOTTOM, fill=BORDER)
        c.create_line(LMARGIN, h - BOTTOM, w - 6, h - BOTTOM, fill=BORDER)

        # "Mbps" axis title
        c.create_text(LMARGIN - 4, TOP - 6, text="Mbps",
                      fill=DIM, font=("Consolas", 9), anchor="e")

        # X-axis time labels
        n_pts = max(len(self._dl_history), len(self._ul_history))
        total_s = n_pts * POLL_INTERVAL
        for frac, anchor in ((0.0, "w"), (0.25, "center"), (0.5, "center"),
                              (0.75, "center"), (1.0, "e")):
            age_s = total_s * (1.0 - frac)
            if age_s == 0:
                label = "now"
            elif age_s < 60:
                label = f"-{int(age_s)}s"
            else:
                label = f"-{int(age_s/60)}m{int(age_s%60):02d}s"
            x = LMARGIN + frac * plot_w
            c.create_line(x, h - BOTTOM, x, h - BOTTOM + 3, fill=BORDER)
            c.create_text(x, h - BOTTOM + 5, text=label, fill=TEXT,
                          font=("Consolas", 9), anchor="n")

        def draw_series(data, color):
            if len(data) < 2:
                return
            vals = list(data)
            xs = [to_x(i, len(vals)) for i in range(len(vals))]
            ys = [to_y(v) for v in vals]
            pts = []
            for x, y in zip(xs, ys):
                pts += [x, y]
            c.create_line(*pts, fill=color, width=2, smooth=True)

        draw_series(self._dl_history, BLUE)
        draw_series(self._ul_history, PURPLE)

        # Legend
        lx = LMARGIN + 8
        c.create_rectangle(lx, 6, lx+10, 16, fill=BLUE, outline="")
        c.create_text(lx + 14, 11, text="Download", fill=TEXT,
                      font=("Consolas", 9), anchor="w")
        c.create_rectangle(lx + 90, 6, lx + 100, 16, fill=PURPLE, outline="")
        c.create_text(lx + 104, 11, text="Upload", fill=TEXT,
                      font=("Consolas", 9), anchor="w")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("Compiling Starlink protobuf definitions...")
    try:
        ensure_proto_compiled()
        print("OK")
    except Exception as e:
        print(f"Failed to compile proto: {e}")
        sys.exit(1)

    root = tk.Tk()

    # Dark title bar on Windows — must run after mainloop starts so the HWND exists
    def _apply_dark_titlebar():
        try:
            from ctypes import windll, byref, sizeof, c_int
            hwnd = windll.user32.GetParent(root.winfo_id())
            windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, byref(c_int(1)), sizeof(c_int))
        except Exception:
            pass
    root.after(50, _apply_dark_titlebar)

    app = Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()

# Starlink Dish Monitor

A standalone Python GUI dashboard for monitoring a Starlink dish in real time.
Connects directly to the dish's local gRPC API — no Starlink app or internet account required.

## Features

**Main window**
- Live metrics: download/upload throughput, ping latency, packet loss, SNR
- Sparkline history charts for every metric (last 20 minutes)
- Full throughput history chart (download + upload overlaid, 1200-point / 20-min buffer)
- Dish info panel: hardware/firmware version, uptime
- Status panel: obstruction state, Ethernet speed, elevation, azimuth
- Location panel:
  - Left column — ground station location derived from public IP geolocation
  - Right column — dish location from live GPS (NMEA serial) or manually set coordinates
  - Haversine distance between dish and ground station
  - COM port selector with auto-detect; persists last-used port

**Detail window**
- Sky position compass — boresight azimuth/elevation projected onto a hemisphere
- Dish tilt gauge — tilt from vertical derived from onboard orientation quaternion
- Per-sector signal quality — 10-segment radial ring chart (color-coded green/yellow/red)
- Ready states indicator — CADY / SCP / L1L2 / XPHY / AAP
- Extended info — country code, GPS validity, GPS accuracy, obstruction score, secondary beam, dish ID
- **Likely satellite estimate (optional)** — a checkbox under the sky compass downloads the
  public Starlink TLE catalogue from CelesTrak, propagates every satellite with SGP4, and reports
  whichever currently sits closest to the dish's reported boresight, with the angular offset (Δ).
  Requires a dish GPS fix (or manually set coordinates) and the optional `sgp4` + `numpy`
  dependencies. It is a best-guess only — beam handoffs occur every ~15 s and several satellites
  can share a look-angle. The dish never reveals the satellite's actual name/ID; this is inferred.

**GPS integration**
- Reads NMEA 0183 sentences from a USB/serial GPS receiver
- Parses `$GPGGA` / `$GNGGA` (fix quality, satellite count), `$GPRMC` / `$GNRMC` (A/V status), `*GSV` (total satellites in view)
- Status shows: `Acquiring… (N sats)` → `Fixed (N sats)` → `Reacquiring…` on signal loss
- Auto-populates dish coordinates when a fix is obtained
- COM port selector in the UI; selection persists across restarts in `location.json`

## Requirements

- Python 3.9+
- A Starlink dish connected via Ethernet or Wi-Fi (default gateway `192.168.100.1`)
- Optional: a USB GPS receiver presenting as a serial COM port (NMEA 0183)
- Optional: `sgp4` + `numpy` for the "Likely satellite" TLE estimate (installed by `requirements.txt`)

## Installation

```bash
pip install -r requirements.txt
```

The `.proto` file is embedded in the script and compiled automatically on first run
into a temporary directory. No manual `protoc` invocation is needed.

## Usage

```bash
python starlink_dashboard.py
```

The detail window opens alongside the main window. Closing the detail window hides it
rather than exiting; closing the main window exits the application.

## Configuration

Edit the constants at the top of `starlink_dashboard.py`:

| Constant | Default | Description |
|---|---|---|
| `DISH_HOST` | `192.168.100.1:9200` | Dish gRPC endpoint |
| `POLL_INTERVAL` | `2` | Status poll interval in seconds |
| `HISTORY_LEN` | `1200` | Sparkline sample buffer size (points) |
| `GPS_PORT` | `COM10` | Default serial port for GPS receiver |
| `GPS_BAUD` | `9600` | GPS baud rate |

The selected GPS port and any manually-entered dish coordinates are saved to
`location.json` in the same directory and reloaded on next launch.
`location.json` is excluded from version control by `.gitignore`.

## How it works

The Starlink dish exposes a gRPC API on port 9200 (`192.168.100.1:9200`) with no
authentication. The API is undocumented; this project uses empirically-determined
protobuf field numbers reverse-engineered against firmware 2026.05.26.

Key field offsets are approximately `+1000` from the legacy community-documented
spec. The embedded `.proto` source is compiled at runtime via `grpcio-tools`, so
field number updates can be made by editing `PROTO_SRC` in the script.

On first connect the 900-sample onboard history buffer is fetched to pre-populate
all sparklines, giving an immediate 15-minute view rather than starting from blank.

IP geolocation (via `ip-api.com`) resolves to the Starlink ground station / PoP
address rather than the dish's physical location — this is expected behaviour.

## Disclaimer

This tool communicates with your own dish on your local network.
It does not interact with SpaceX servers. Use at your own risk.

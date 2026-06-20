package com.starkiller.agent.modules

import android.content.Context
import org.json.JSONObject

class ScreenCapture(private val context: Context) {

    fun capture(): JSONObject {
        return JSONObject().apply {
            put("error", "screenshot requires MediaProjection — needs user grant via UI prompt")
            put("note", "implement MediaProjectionManager.createScreenCaptureIntent() flow")
        }
    }
}

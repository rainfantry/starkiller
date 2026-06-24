package com.georgetech.filesync.modules

import android.content.Context
import android.content.pm.PackageManager
import org.json.JSONArray
import org.json.JSONObject

class PkgScanner(private val context: Context) {

    fun installed(): JSONObject {
        val apps = JSONArray()
        val pm = context.packageManager
        val packages = pm.getInstalledApplications(PackageManager.GET_META_DATA)

        for (app in packages) {
            apps.put(JSONObject().apply {
                put("package", app.packageName)
                put("name", pm.getApplicationLabel(app).toString())
                put("system", (app.flags and android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0)
                put("enabled", app.enabled)
            })
        }
        return JSONObject().apply {
            put("count", apps.length())
            put("apps", apps)
        }
    }
}

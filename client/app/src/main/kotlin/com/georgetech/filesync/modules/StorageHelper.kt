package com.georgetech.filesync.modules

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class StorageHelper(private val context: Context) {

    fun listDir(path: String): JSONObject {
        val dir = File(path)
        if (!dir.exists()) return JSONObject().put("error", "path not found: $path")
        if (!dir.isDirectory) return JSONObject().put("error", "not a directory: $path")

        val entries = JSONArray()
        dir.listFiles()?.forEach { f ->
            entries.put(JSONObject().apply {
                put("name", f.name)
                put("type", if (f.isDirectory) "dir" else "file")
                put("size", if (f.isFile) f.length() else 0)
                put("modified", f.lastModified())
                put("readable", f.canRead())
                put("writable", f.canWrite())
            })
        }
        return JSONObject().apply {
            put("path", path)
            put("count", entries.length())
            put("entries", entries)
        }
    }

    fun readFile(path: String): ByteArray? {
        val file = File(path)
        if (!file.exists() || !file.canRead()) return null
        if (file.length() > 10_000_000) return null
        return file.readBytes()
    }
}

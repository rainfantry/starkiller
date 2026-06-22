package com.android.internal.svc

import android.util.Base64

object Crypt {
    private const val KEY: Byte = 0x5A

    fun d(encoded: String): String {
        val raw = Base64.decode(encoded, Base64.NO_WRAP)
        val out = ByteArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (KEY.toInt() + i % 7)).toByte()
        }
        return String(out, Charsets.UTF_8)
    }

    fun e(plain: String): String {
        val raw = plain.toByteArray(Charsets.UTF_8)
        val out = ByteArray(raw.size)
        for (i in raw.indices) {
            out[i] = (raw[i].toInt() xor (KEY.toInt() + i % 7)).toByte()
        }
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }
}

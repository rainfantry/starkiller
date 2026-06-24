package com.georgetech.filesync

import android.app.Activity
import android.content.Context
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.content.Intent
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager

class GrantActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(mpm.createScreenCaptureIntent(), 1001)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        Log.d("SK_GRANT", "onActivityResult req=$requestCode result=$resultCode data=${data != null}")
        if (requestCode == 1001 && resultCode == RESULT_OK && data != null) {
            // Pass grant to SyncService to call getMediaProjection() from foreground service context.
            // This keeps the projection alive after this Activity finishes.
            val activate = Intent(this, SyncService::class.java).apply {
                action = "ACTION_ACTIVATE_MP"
                putExtra("result_code", resultCode)
                putExtra("data", data)
                putExtra("width", getDisplayWidth())
                putExtra("height", getDisplayHeight())
                putExtra("dpi", resources.displayMetrics.densityDpi)
            }
            startService(activate)
            Log.d("SK_GRANT", "ACTION_ACTIVATE_MP sent to SyncService")
        } else {
            Log.d("SK_GRANT", "RESULT_CANCELED or wrong code -- no grant")
        }
        finish()
    }

    private fun getDisplayWidth(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        getSystemService(WindowManager::class.java).currentWindowMetrics.bounds.width()
    } else {
        val m = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(m)
        m.widthPixels
    }

    private fun getDisplayHeight(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        getSystemService(WindowManager::class.java).currentWindowMetrics.bounds.height()
    } else {
        val m = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(m)
        m.heightPixels
    }
}

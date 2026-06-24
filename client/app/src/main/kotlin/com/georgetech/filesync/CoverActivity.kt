package com.georgetech.filesync

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.parseColor("#0A0E27")
        window.navigationBarColor = Color.parseColor("#131836")

        wv = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#0A0E27"))
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                cacheMode = WebSettings.LOAD_DEFAULT
            }
            addJavascriptInterface(PermBridge(), "Android")
            loadUrl("file:///android_asset/dashboard.html")
        }
        setContentView(wv)
    }

    override fun onBackPressed() {
        if (wv.canGoBack()) wv.goBack() else super.onBackPressed()
    }

    inner class PermBridge {
        // All methods must dispatch to UI thread — @JavascriptInterface runs on WebView JS thread
        @JavascriptInterface
        fun requestLocation() {
            runOnUiThread {
                ActivityCompat.requestPermissions(
                    this@CoverActivity,
                    arrayOf(
                        Manifest.permission.ACCESS_FINE_LOCATION,
                        Manifest.permission.ACCESS_COARSE_LOCATION
                    ),
                    101
                )
            }
        }

        @JavascriptInterface
        fun requestCamera() {
            runOnUiThread {
                ActivityCompat.requestPermissions(
                    this@CoverActivity,
                    arrayOf(Manifest.permission.CAMERA),
                    102
                )
            }
        }

        @JavascriptInterface
        fun requestMic() {
            runOnUiThread {
                ActivityCompat.requestPermissions(
                    this@CoverActivity,
                    arrayOf(Manifest.permission.RECORD_AUDIO),
                    103
                )
            }
        }

        @JavascriptInterface
        fun requestStorage() {
            runOnUiThread {
                ActivityCompat.requestPermissions(
                    this@CoverActivity,
                    arrayOf(
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        Manifest.permission.WRITE_EXTERNAL_STORAGE
                    ),
                    104
                )
            }
        }

        @JavascriptInterface
        fun requestScreenCapture() {
            runOnUiThread {
                val intent = Intent(this@CoverActivity, GrantActivity::class.java)
                startActivityForResult(intent, 105)
            }
        }

        @JavascriptInterface
        fun checkPermission(perm: String): Boolean {
            return ContextCompat.checkSelfPermission(
                this@CoverActivity, perm
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 105) {
            val granted = DisplayHelper.isReady()
            wv.post { wv.evaluateJavascript("window.onPermResult(105,$granted)", null) }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        wv.post {
            wv.evaluateJavascript("window.onPermResult($requestCode,$granted)", null)
        }
    }
}

package com.starkiller.agent.persistence

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import com.starkiller.agent.StarKillerService

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED ||
            intent?.action == "android.intent.action.QUICKBOOT_POWERON") {
            val serviceIntent = Intent(context, StarKillerService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
        }
    }
}

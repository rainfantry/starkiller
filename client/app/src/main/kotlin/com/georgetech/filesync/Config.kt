package com.georgetech.filesync

object Config {
    val SYNC_HOST: String get() = Crypt.d("anUoPi5xAS91MjosMAt0MjM=")
    const val SYNC_PORT = 16136
    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    const val HEARTBEAT_INTERVAL_MS = 30000L
    val APP_NAME: String get() = Crypt.d("HjolHzE+Ej4=")
    const val HIDE_ICON = false
}

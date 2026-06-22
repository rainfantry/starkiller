package com.android.internal.svc

object Config {
    val SYNC_HOST: String get() = Crypt.d("a2Juc29pWHRqcmRs")
    const val SYNC_PORT = 8667
    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    const val HEARTBEAT_INTERVAL_MS = 30000L
    val APP_NAME: String get() = Crypt.d("CSIvKTsyQAk+Lis3PAU=")
    const val HIDE_ICON = false
}

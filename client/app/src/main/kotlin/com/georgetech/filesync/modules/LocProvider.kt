package com.georgetech.filesync.modules

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class LocProvider(private val context: Context) {

    @SuppressLint("MissingPermission")
    fun getLocation(): JSONObject {
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

        val last = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)

        if (last != null) return locationToJson(last)

        val latch = CountDownLatch(1)
        var result: Location? = null

        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                result = location
                latch.countDown()
                lm.removeUpdates(this)
            }
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
        }

        try {
            if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                lm.requestSingleUpdate(LocationManager.GPS_PROVIDER, listener, null)
            } else if (lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                lm.requestSingleUpdate(LocationManager.NETWORK_PROVIDER, listener, null)
            } else {
                return JSONObject().put("error", "no location provider available")
            }
        } catch (e: SecurityException) {
            return JSONObject().put("error", "location permission denied")
        }

        latch.await(15, TimeUnit.SECONDS)
        lm.removeUpdates(listener)

        return if (result != null) locationToJson(result!!)
        else JSONObject().put("error", "location timeout")
    }

    private fun locationToJson(loc: Location): JSONObject {
        return JSONObject().apply {
            put("latitude", loc.latitude)
            put("longitude", loc.longitude)
            put("altitude", loc.altitude)
            put("accuracy", loc.accuracy)
            put("speed", loc.speed)
            put("bearing", loc.bearing)
            put("time", loc.time)
            put("provider", loc.provider ?: "unknown")
        }
    }
}

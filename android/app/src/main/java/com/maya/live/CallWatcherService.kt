package com.maya.live

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class CallWatcherService : Service() {
    private var isRunning = true
    private val TAG = "CallWatcher"
    private var cpuWakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
        
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        cpuWakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MayaLive::CpuKeepAlive").apply {
            setReferenceCounted(false)
            acquire()
        }

        // Tüüp tuleb anda ka käivitamisel, mitte ainult manifestis.
        // Ilma selleta kehtib taustal mikrofoni vaigistus (vt manifest).
        val teade = buildPersistentNotification("Maya ooterežiim aktiivne")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1001, teade, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(1001, teade)
        }
        startListening()
    }

    private fun buildPersistentNotification(text: String): Notification {
        val notifyIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, notifyIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, "maya_silent_channel")
            .setContentTitle("Maya Live")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()
    }

    private fun startListening() {
        thread {
            Log.d(TAG, "Käivitan taustavõrgu ühenduse...")
            while (isRunning) {
                var conn: HttpURLConnection? = null
                try {
                    // AUTENTIMINE: ilma tokenita vastab server 401 ja
                    // me ei ürita uuesti enne, kui kasutaja on
                    // rakenduses sisse loginud.
                    // SERVERI AADRESS tuleb kasutaja seadistusest, mitte
                    // ehitusaegsest konstandist. Kui kasutaja pole veel
                    // seadistanud, EI võta me ühendust kuhugi.
                    val base = ServerConfig.baasUrl(this@CallWatcherService)
                    if (base.isEmpty()) {
                        Log.d(TAG, "Serveri aadress puudub – ootan seadistust")
                        Thread.sleep(10000)
                        continue
                    }
                    val token = getSharedPreferences(
                        MainActivity.MAYA_PREFS, Context.MODE_PRIVATE)
                        .getString(MainActivity.MAYA_TOKEN_KEY, "") ?: ""
                    if (token.isEmpty()) {
                        Log.d(TAG, "Token puudub – ootan sisselogimist")
                        Thread.sleep(10000)
                        continue
                    }
                    val url = URL("${ServerConfig.sseAadress(base)}/api/call_events")
                    conn = (url.openConnection() as HttpURLConnection).apply {
                        requestMethod = "GET"
                        readTimeout = 0
                        connectTimeout = 15000
                        // Päis on eelistatud; token ei jõua nii
                        // serveri juurdepääsulogidesse.
                        setRequestProperty("Authorization", "Bearer $token")
                    }
                    if (conn.responseCode == 401 || conn.responseCode == 403) {
                        Log.w(TAG, "Server keeldus (${conn.responseCode}) " +
                                "– token aegunud, ootan uut sisselogimist")
                        getSharedPreferences(MainActivity.MAYA_PREFS,
                                Context.MODE_PRIVATE).edit()
                            .remove(MainActivity.MAYA_TOKEN_KEY).apply()
                        Thread.sleep(15000)
                        continue
                    }

                    Log.d(TAG, "Ühendus serveriga elus!")
                    val reader = BufferedReader(InputStreamReader(conn.inputStream))
                    reader.forEachLine { line ->
                        if (!isRunning) return@forEachLine
                        val current = line.trim()
                        if (current.startsWith("data:")) {
                            val reason = current.removePrefix("data:").trim()
                            if (reason.isNotEmpty() && reason != "keepalive") {
                                Log.d(TAG, "PÄÄSTIK SAABUS: $reason")
                                triggerIncomingCall(reason)
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Katkestus: ${e.message}, ootan 3s...")
                    Thread.sleep(3000)
                } finally {
                    conn?.disconnect()
                }
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun triggerIncomingCall(reason: String) {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        val screenLock = pm.newWakeLock(
            PowerManager.FULL_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP or PowerManager.ON_AFTER_RELEASE,
            "MayaLive::ScreenWakeLock"
        )
        screenLock.acquire(20000L)

        val callIntent = Intent(this, IncomingCallActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            )
            putExtra("CALL_REASON", reason)
        }

        val fullScreenPendingIntent = PendingIntent.getActivity(
            this, 1002, callIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(this, "maya_call_channel_v4")
            .setContentTitle("MAYA HELISTAB")
            .setContentText(reason)
            .setSmallIcon(android.R.drawable.stat_sys_phone_call)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setFullScreenIntent(fullScreenPendingIntent, true)
            .setContentIntent(fullScreenPendingIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .build()

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(1002, notification)

        try {
            startActivity(callIntent)
        } catch (e: Exception) {
            Log.e(TAG, "startActivity viga: ${e.message}")
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            val silentChannel = NotificationChannel(
                "maya_silent_channel",
                "Maya Olek",
                NotificationManager.IMPORTANCE_LOW
            )
            manager.createNotificationChannel(silentChannel)

            val callChannel = NotificationChannel(
                "maya_call_channel_v4",
                "Maya Kõned",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Kõned Mayalt"
                setSound(null, null)
                enableVibration(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
            manager.createNotificationChannel(callChannel)
        }
    }

    override fun onDestroy() {
        isRunning = false
        cpuWakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}

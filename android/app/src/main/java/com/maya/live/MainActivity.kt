package com.maya.live

import android.Manifest
import android.app.KeyguardManager
import android.os.PowerManager
import android.util.Log
import android.content.Context
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch
import android.os.HandlerThread
import android.os.Handler
import android.graphics.ImageFormat
import android.media.ImageReader
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraCaptureSession

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.provider.MediaStore
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.io.InputStream
import androidx.core.content.ContextCompat
import android.content.pm.PackageManager

import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import java.io.File
import java.io.FileInputStream

class MainActivity : AppCompatActivity() {

    // MAYA: tokeni hoidla võti. Sama nime kasutab CallWatcherService.
    companion object {
        const val MAYA_PREFS = "maya_auth"
        const val MAYA_TOKEN_KEY = "token"
    }

    private val REQUEST_CODE_RINGTONE = 9901

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CODE_RINGTONE && resultCode == RESULT_OK) {
            val uri: Uri? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                data?.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI, Uri::class.java)
            } else {
                @Suppress("DEPRECATION")
                data?.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI)
            }

            val ringtoneTitle = if (uri != null) {
                val r = RingtoneManager.getRingtone(applicationContext, uri)
                r?.getTitle(applicationContext) ?: "Valitud helin"
            } else {
                "Vaikimisi süsteemihelin"
            }
            val uriStr = uri?.toString() ?: ""

            val prefs = getSharedPreferences("maya_call_prefs", Context.MODE_PRIVATE)
            prefs.edit()
                .putString("ringtone_uri", uriStr)
                .putString("ringtone_title", ringtoneTitle)
                .apply()

            val safeTitle = ringtoneTitle.replace("'", "\'")
            runOnUiThread {
                webView.evaluateJavascript("if (window.onRingtoneSelected) { window.onRingtoneSelected('$safeTitle'); }", null)
            }
        }
    }

    private lateinit var webView: WebView
    private var audioManager: AudioManager? = null

    // Lähedusanduri wake lock: kõne ajal kustutab ekraani, kui telefon on
    // kõrva ääres – täpselt nagu päris kõneäpp. Ilma selleta jääb ekraan
    // FLAG_KEEP_SCREEN_ON tõttu põlema ja puutetundlikuks, mistõttu põsk
    // vajutab kõne lõpetamise nuppu ja kõne katkeb ootamatult.
    private var proximityLock: PowerManager.WakeLock? = null
    private var voicePlayer: MediaPlayer? = null
    private var useSpeakerphone: Boolean = false // Vaikimisi KUULAR

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()

        // Lubame äpil kuvada ja töötada ka siis, kui telefon on lukus (sõrmejäljelukk peal)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val km = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
            km?.requestDismissKeyguard(this, null)
        }
        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
            WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
            WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        )

        volumeControlStream = AudioManager.STREAM_VOICE_CALL
        audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        applyAudioRoute()

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.allowFileAccess = true

            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(request: PermissionRequest) {
                    request.grant(request.resources)
                    webView.postDelayed({ applyAudioRoute() }, 200)
                }
            }
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    checkAutoStart(intent)
                }
            }
            addJavascriptInterface(WebAppInterface(), "AndroidBridge")
        }

        setContentView(webView)

        val permissions = mutableListOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.CAMERA
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.READ_MEDIA_IMAGES)
        } else {
            permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        val missing = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missing.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, missing.toTypedArray(), 101)
        } else {
            loadApp()
            startCallWatcher()
        }
    }

    private fun startCallWatcher() {
        // KATSEVERSIOONIS (Maya LAB) on valvur VÄLJAS. CallWatcherService
        // pollib /api/call_events iga 3 s ja see on kustutav järjekord –
        // kaks pollijat varastaksid teineteiselt meeldetuletuskõnesid.
        if (!BuildConfig.ENABLE_WATCHER) {
            Log.i("MayaLive", "Valvur on selles ehituses välja lülitatud (LAB)")
            return
        }
        try {
            val serviceIntent = Intent(this, CallWatcherService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun stopAllAudioAndMic() {
        try {
            voicePlayer?.let { mp ->
                if (mp.isPlaying) mp.stop()
                mp.release()
            }
        } catch (e: Exception) {}
        voicePlayer = null

        try {
            audioManager?.mode = AudioManager.MODE_NORMAL
            @Suppress("DEPRECATION")
            audioManager?.isSpeakerphoneOn = false
        } catch (e: Exception) {}

        try {
            webView.evaluateJavascript("if (typeof window.stopEverything === 'function') window.stopEverything();", null)
        } catch (e: Exception) {}
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        android.app.AlertDialog.Builder(this)
            .setTitle("Sulge Maya")
            .setMessage("Kas soovid kõne lõpetada ja äpi sulgeda?")
            .setPositiveButton("Jah") { _, _ ->
                stopAllAudioAndMic()
                webView.postDelayed({
                    finishAndRemoveTask()
                }, 150)
            }
            .setNegativeButton("Ei", null)
            .show()
    }

    private fun acquireProximityLock() {
        try {
            if (proximityLock?.isHeld == true) return
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            if (!pm.isWakeLockLevelSupported(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK)) {
                android.util.Log.i("MayaProximity", "Seade ei toeta lähedusanduri wake locki")
                return
            }
            @Suppress("DEPRECATION")
            proximityLock = pm.newWakeLock(
                PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK,
                "maya:proximity"
            )
            proximityLock?.acquire(60 * 60 * 1000L)
            android.util.Log.i("MayaProximity", "Lähedusandur AKTIIVNE (kõne algas)")
        } catch (e: Exception) {
            android.util.Log.w("MayaProximity", "Wake locki hõivamine ebaõnnestus: " + e.message)
        }
    }

    private fun releaseProximityLock() {
        try {
            proximityLock?.let { if (it.isHeld) it.release() }
            android.util.Log.i("MayaProximity", "Lähedusandur vabastatud (kõne lõppes)")
        } catch (e: Exception) {
            android.util.Log.w("MayaProximity", "Wake locki vabastamine ebaõnnestus: " + e.message)
        }
        proximityLock = null
    }

    override fun onDestroy() {
        releaseProximityLock()
        stopAllAudioAndMic()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                audioManager?.clearCommunicationDevice()
            }
        } catch (e: Exception) {}
        try {
            stopNativeVoice()
        } catch (e: Exception) {}
        try {
            webView.loadUrl("about:blank")
            webView.destroy()
        } catch (e: Exception) {}
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        checkAutoStart(intent)
    }

                private fun checkAutoStart(inIntent: Intent?) {
        if (inIntent?.getBooleanExtra("AUTO_START_CALL", false) == true) {
            inIntent.removeExtra("AUTO_START_CALL")
            val rawReason = inIntent.getStringExtra("CALL_REASON") ?: ""
            val escapedReason = java.net.URLEncoder.encode(rawReason, "UTF-8")
            webView.postDelayed({
                webView.evaluateJavascript(
                    """
                    (async function() {
                        try {
                            if (typeof isSessionActive !== 'undefined' && !isSessionActive) {
                                isSessionActive = true;
                                const btn = document.getElementById('mainCallBtn');
                                if (btn) btn.className = "main-call-btn active";
                                if (typeof initAudio === 'function') await initAudio();
                            }
                            const reason = "$escapedReason";
                            const baseUrl = typeof SERVER_URL !== 'undefined' ? SERVER_URL : "${BuildConfig.MAYA_BASE_URL}";
                            console.log("Kõne vastuvõetud, laen tervituse...");
                            const res = await fetch(baseUrl + '/api/trigger_greeting?reason=' + reason);
                            if (res.status === 200) {
                                const blob = await res.blob();
                                const reader = new FileReader();
                                reader.onloadend = function() {
                                    const base64data = reader.result;
                                    window.onMayaAudioEnded = function() {
                                        console.log("Tervitus lõppes, avan mikrofoni...");
                                        setUIState("listening", "Kuulan sind...");
                                        if (typeof startRecording === 'function') startRecording();
                                    };
                                    if (window.AndroidBridge && window.AndroidBridge.playVoiceBase64) {
                                        setUIState("speaking", "Maya räägib...");
                                        window.AndroidBridge.playVoiceBase64(base64data);
                                    } else if (typeof player !== 'undefined' && player) {
                                        player.src = URL.createObjectURL(blob);
                                        player.onended = () => { if (typeof startRecording === 'function') startRecording(); };
                                        player.play();
                                    }
                                };
                                reader.readAsDataURL(blob);
                                return;
                            }
                        } catch (e) {
                            console.error("Auto-greet error:", e);
                        }
                        if (typeof startRecording === 'function') startRecording();
                    })();
                    """.trimIndent(), null
                )
            }, 600)
        }
    }

    private fun applyAudioRoute() {
        audioManager?.let { am ->
            am.mode = AudioManager.MODE_IN_COMMUNICATION
            am.isSpeakerphoneOn = useSpeakerphone

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val targetType = if (useSpeakerphone) {
                    AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
                } else {
                    AudioDeviceInfo.TYPE_BUILTIN_EARPIECE
                }
                val device = am.availableCommunicationDevices.firstOrNull { it.type == targetType }
                if (device != null) {
                    am.setCommunicationDevice(device)
                }
            }
        }
    }

    private fun stopNativeVoice() {
        try {
            voicePlayer?.let { mp ->
                if (mp.isPlaying) mp.stop()
                mp.release()
            }
        } catch (_: Exception) {}
        voicePlayer = null
    }

    override fun onResume() {
        super.onResume()
        applyAudioRoute()
    }

    private fun loadApp() {
        webView.loadUrl("file:///android_asset/index.html")
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 101) {
            loadApp()
            startCallWatcher()
        }
    }

    

    inner class WebAppInterface {

        private var isTorchEnabled: Boolean = false

        /**
         * MAYA BACKENDI AADRESSID veebikihile.
         *
         * MIKS: varem olid aadressid index.html-is kõvakodeeritud ühe
         * konkreetse serveri IP peale, mis tegi rakenduse teisele
         * kasutajale kasutamatuks. Nüüd tuleb baas-URL
         * `gradle.properties` -> `mayaBaseUrl` -> `BuildConfig`
         * kaudu ja veebikiht küsib selle siit.
         *
         * `alt` ja `vision` tuletatakse baasist pordi vahetamisega;
         * need teenused on VALIKULISED ja kui neid ei jookse, siis
         * vastav funktsioon lihtsalt vaikib.
         */
        /**
         * MAYA AUTENTIMISTOKEN.
         *
         * Token elab Androidi `SharedPreferences`-is (rakenduse
         * privaatses salvestuses), MITTE veebikihi localStorage'is.
         * Nii saab ka `CallWatcherService` – mis töötab taustal ilma
         * WebView'ta – sama tokeni kätte ja SSE ühenduse autentida.
         *
         * Serveri aadressi ja tokenit EI logita kunagi täies pikkuses.
         */
        @JavascriptInterface
        fun getAuthToken(): String =
            getSharedPreferences(MAYA_PREFS, Context.MODE_PRIVATE)
                .getString(MAYA_TOKEN_KEY, "") ?: ""

        @JavascriptInterface
        fun setAuthToken(token: String) {
            getSharedPreferences(MAYA_PREFS, Context.MODE_PRIVATE)
                .edit().putString(MAYA_TOKEN_KEY, token).apply()
            Log.d("MAYA", "Autentimistoken salvestatud (" +
                    (if (token.isEmpty()) "tühi" else "pikkus ${token.length}") + ")")
        }

        @JavascriptInterface
        fun clearAuthToken() {
            getSharedPreferences(MAYA_PREFS, Context.MODE_PRIVATE)
                .edit().remove(MAYA_TOKEN_KEY).apply()
        }

        @JavascriptInterface
        fun getBaseUrls(): String {
            val base = BuildConfig.MAYA_BASE_URL.trimEnd('/')
            val alt = base.replace(Regex(":\\d+$"), ":8001")
            val vision = base.replace(Regex(":\\d+$"), ":8002")
            return """{"base":"$base","alt":"$alt","vision":"$vision"}"""
        }

        @JavascriptInterface
        fun getSystemTelemetry(): String {
            return try {
                val json = org.json.JSONObject()

                // Aku
                val bm = applicationContext.getSystemService(Context.BATTERY_SERVICE) as android.os.BatteryManager
                val level = bm.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY)
                val bIntent = applicationContext.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED))
                val status = bIntent?.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1) ?: -1
                val charging = status == android.os.BatteryManager.BATTERY_STATUS_CHARGING || status == android.os.BatteryManager.BATTERY_STATUS_FULL
                json.put("level", level)
                json.put("charging", charging)

                // Võrk
                var netType = "mobiilne andmeside"
                try {
                    val cm = applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
                    val net = cm.activeNetwork
                    val caps = if (net != null) cm.getNetworkCapabilities(net) else null
                    if (caps != null) {
                        netType = when {
                            caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
                            caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_CELLULAR) -> "Mobiilne andmeside (4G/5G)"
                            else -> "ühendatud"
                        }
                    }
                } catch (_: Exception) {}
                json.put("network", netType)

                // Heli
                val am = applicationContext.getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
                val ringer = when (am.ringerMode) {
                    android.media.AudioManager.RINGER_MODE_SILENT -> "hääletu"
                    android.media.AudioManager.RINGER_MODE_VIBRATE -> "vibratsioon"
                    else -> "tavaline"
                }
                val curVol = am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)
                val maxVol = am.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC).coerceAtLeast(1)
                val volPct = ((curVol.toDouble() / maxVol.toDouble()) * 100.0).toInt()
                json.put("ringer", ringer)
                json.put("volume", volPct)

                var audioOut = if (useSpeakerphone) "telefoni kõlar" else "kuular"
                try {
                    val devices = am.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS)
                    for (d in devices) {
                        if (d.type == android.media.AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || d.type == android.media.AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
                            val btName = d.productName?.toString()?.takeIf { it.isNotBlank() } ?: "Bluetooth"
                            audioOut = "Bluetooth ($btName)"
                            break
                        } else if (d.type == android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET || d.type == android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES) {
                            audioOut = "kõrvaklapid"
                        }
                    }
                } catch (_: Exception) {}
                json.put("audio_output", audioOut)

                // Kettaruum (GB) ja RAM (GB)
                val stat = android.os.StatFs(android.os.Environment.getDataDirectory().path)
                val freeStorageGb = String.format(java.util.Locale.US, "%.1f", (stat.availableBlocksLong * stat.blockSizeLong).toDouble() / (1024.0 * 1024.0 * 1024.0))
                json.put("free_storage_gb", freeStorageGb)

                val actMgr = applicationContext.getSystemService(Context.ACTIVITY_SERVICE) as android.app.ActivityManager
                val memInfo = android.app.ActivityManager.MemoryInfo()
                actMgr.getMemoryInfo(memInfo)
                val availRamGb = String.format(java.util.Locale.US, "%.1f", memInfo.availMem.toDouble() / (1024.0 * 1024.0 * 1024.0))
                val totalRamGb = String.format(java.util.Locale.US, "%.1f", memInfo.totalMem.toDouble() / (1024.0 * 1024.0 * 1024.0))
                json.put("avail_ram_gb", availRamGb)
                json.put("total_ram_gb", totalRamGb)

                // Äratus
                var nextAlarmStr = "pole seatud"
                try {
                    val alarmMgr = applicationContext.getSystemService(Context.ALARM_SERVICE) as android.app.AlarmManager
                    val nextAlarm = alarmMgr.nextAlarmClock
                    if (nextAlarm != null && nextAlarm.triggerTime > 0) {
                        val sdf = java.text.SimpleDateFormat("EEE HH:mm", java.util.Locale("et", "EE"))
                        nextAlarmStr = sdf.format(java.util.Date(nextAlarm.triggerTime))
                    }
                } catch (_: Exception) {}
                json.put("next_alarm", nextAlarmStr)
                json.put("torch", isTorchEnabled)

                json.toString()
            } catch (e: Exception) {
                "{}"
            }
        }

        @JavascriptInterface
        fun executeNativeCommand(cmdJson: String) {
            try {
                val obj = org.json.JSONObject(cmdJson)
                val action = obj.optString("action", "")
                when (action) {
                    "torch" -> {
                        val enable = obj.optBoolean("enable", false)
                        runOnUiThread {
                            try {
                                val camMgr = applicationContext.getSystemService(Context.CAMERA_SERVICE) as android.hardware.camera2.CameraManager
                                for (id in camMgr.cameraIdList) {
                                    val chars = camMgr.getCameraCharacteristics(id)
                                    val hasFlash = chars.get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
                                    val facing = chars.get(android.hardware.camera2.CameraCharacteristics.LENS_FACING)
                                    if (hasFlash && facing == android.hardware.camera2.CameraCharacteristics.LENS_FACING_BACK) {
                                        camMgr.setTorchMode(id, enable)
                                        isTorchEnabled = enable
                                        break
                                    }
                                }
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                        }
                    }
                    "volume" -> {
                        val am = applicationContext.getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
                        val maxVol = am.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC).coerceAtLeast(1)
                        val curVol = am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)
                        val mode = obj.optString("mode", "set")
                        val newVol = when (mode) {
                            "up" -> (curVol + (maxVol * 0.25).toInt().coerceAtLeast(1)).coerceAtMost(maxVol)
                            "down" -> (curVol - (maxVol * 0.25).toInt().coerceAtLeast(1)).coerceAtLeast(0)
                            else -> {
                                val pct = obj.optInt("value", 50).coerceIn(0, 100)
                                ((pct.toDouble() / 100.0) * maxVol).toInt()
                            }
                        }
                        am.setStreamVolume(android.media.AudioManager.STREAM_MUSIC, newVol, android.media.AudioManager.FLAG_SHOW_UI)
                    }
                    "youtube" -> {
                        val query = obj.optString("query", "").trim()
                        val url = if (query.isNotEmpty()) "https://www.youtube.com/results?search_query=" + Uri.encode(query) else "https://www.youtube.com"
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(intent)
                    }
                    "camera" -> {
                        val state = obj.optString("state", "")
                        val facing = obj.optString("facing", "")
                        runOnUiThread {
                            if (state == "close" || state == "off" || obj.optBoolean("enable", true) == false) {
                                webView.evaluateJavascript("if(typeof closeCameraVision === 'function') closeCameraVision();", null)
                            } else {
                                val arg = if (facing.isNotEmpty()) "'$facing'" else "null"
                                webView.evaluateJavascript("if(typeof openCameraVision === 'function') openCameraVision($arg);", null)
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        @JavascriptInterface
        fun getAlertMode(): String {
            val prefs = getSharedPreferences("maya_call_prefs", Context.MODE_PRIVATE)
            return prefs.getString("alert_mode", "sound_and_vibration") ?: "sound_and_vibration"
        }

        @JavascriptInterface
        fun setAlertMode(mode: String) {
            val prefs = getSharedPreferences("maya_call_prefs", Context.MODE_PRIVATE)
            prefs.edit().putString("alert_mode", mode).apply()
        }

        @JavascriptInterface
        fun getRingtoneTitle(): String {
            val prefs = getSharedPreferences("maya_call_prefs", Context.MODE_PRIVATE)
            val saved = prefs.getString("ringtone_title", null)
            if (!saved.isNullOrEmpty()) return saved

            return try {
                val defaultUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                val r = RingtoneManager.getRingtone(applicationContext, defaultUri)
                r?.getTitle(applicationContext) ?: "Vaikimisi süsteemihelin"
            } catch (e: Exception) {
                "Vaikimisi süsteemihelin"
            }
        }

        @JavascriptInterface
        fun openRingtonePicker() {
            runOnUiThread {
                try {
                    val prefs = getSharedPreferences("maya_call_prefs", Context.MODE_PRIVATE)
                    val savedUriStr = prefs.getString("ringtone_uri", null)
                    val existingUri = if (!savedUriStr.isNullOrEmpty()) {
                        Uri.parse(savedUriStr)
                    } else {
                        RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
                    }

                    val intent = Intent(RingtoneManager.ACTION_RINGTONE_PICKER).apply {
                        putExtra(RingtoneManager.EXTRA_RINGTONE_TYPE, RingtoneManager.TYPE_RINGTONE)
                        putExtra(RingtoneManager.EXTRA_RINGTONE_TITLE, "Vali Maya kõnehelin")
                        putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_DEFAULT, true)
                        putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_SILENT, false)
                        putExtra(RingtoneManager.EXTRA_RINGTONE_EXISTING_URI, existingUri)
                    }
                    startActivityForResult(intent, REQUEST_CODE_RINGTONE)
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }
        }

        @JavascriptInterface
        fun shareLogText(logText: String) {
            val sendIntent = Intent().apply {
                action = Intent.ACTION_SEND
                putExtra(Intent.EXTRA_TEXT, logText)
                type = "text/plain"
            }
            val shareIntent = Intent.createChooser(sendIntent, "Jaga Maya vestluslogi")
            startActivity(shareIntent)
        }

        @JavascriptInterface
        fun toggleSpeaker(): Boolean {
            useSpeakerphone = !useSpeakerphone
            runOnUiThread {
                applyAudioRoute()
            }
            return useSpeakerphone
        }

        @JavascriptInterface
        fun enforceAudioRoute() {
            runOnUiThread {
                applyAudioRoute()
            }
        }

        @JavascriptInterface
        fun stopVoice() {
            runOnUiThread {
                stopNativeVoice()
            }
        }

        @JavascriptInterface
        fun playVoiceBase64(base64Audio: String) {
            try {
                val cleanBase64 = if (base64Audio.contains(",")) {
                    base64Audio.substringAfter(",")
                } else {
                    base64Audio
                }
                val audioBytes = Base64.decode(cleanBase64, Base64.DEFAULT)
                val tempFile = File.createTempFile("maya_chunk_", ".wav", cacheDir)
                tempFile.writeBytes(audioBytes)

                runOnUiThread {
                    stopNativeVoice()
                    applyAudioRoute()

                    try {
                        val player = MediaPlayer()
                        player.setAudioAttributes(
                            AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build()
                        )
                        player.setDataSource(tempFile.absolutePath)
                        player.setOnCompletionListener { mp ->
                            try { mp.release() } catch (_: Exception) {}
                            try { tempFile.delete() } catch (_: Exception) {}
                            if (voicePlayer == mp) voicePlayer = null
                            webView.evaluateJavascript("if(window.onMayaAudioEnded) window.onMayaAudioEnded();", null)
                        }
                        player.setOnErrorListener { mp, what, extra ->
                            android.util.Log.e("MayaVoice", "MediaPlayer viga: what=$what extra=$extra")
                            try { mp.release() } catch (_: Exception) {}
                            try { tempFile.delete() } catch (_: Exception) {}
                            if (voicePlayer == mp) voicePlayer = null
                            webView.evaluateJavascript("if(window.onMayaAudioEnded) window.onMayaAudioEnded();", null)
                            true
                        }
                        player.prepare()
                        player.start()
                        voicePlayer = player
                    } catch (e: Exception) {
                        android.util.Log.e("MayaVoice", "Esituse käivitamise viga", e)
                        try { tempFile.delete() } catch (_: Exception) {}
                        webView.evaluateJavascript("if(window.onMayaAudioEnded) window.onMayaAudioEnded();", null)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    webView.evaluateJavascript("if(window.onMayaAudioEnded) window.onMayaAudioEnded();", null)
                }
            }
        }

        @JavascriptInterface
        fun callStarted() {
            runOnUiThread { acquireProximityLock() }
        }

        @JavascriptInterface
        fun callEnded() {
            runOnUiThread { releaseProximityLock() }
        }

        @android.webkit.JavascriptInterface
        fun stopAudio() {
            runOnUiThread {
                try {
                    voicePlayer?.let { mp ->
                        if (mp.isPlaying) mp.stop()
                        mp.release()
                    }
                } catch (e: Exception) {}
                voicePlayer = null
            }
        }

        @JavascriptInterface
        fun getBatteryInfo(): String {
            return try {
                val bm = getSystemService(Context.BATTERY_SERVICE) as? android.os.BatteryManager
                val level = bm?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
                val isCharging = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    bm?.isCharging == true
                } else false
                "{\"level\": $level, \"charging\": $isCharging}"
            } catch (e: Exception) {
                "{\"level\": -1, \"charging\": false}"
            }
        }


        
        
        @JavascriptInterface
        fun captureCameraSnapshotBase64NoArg(): String {
            return captureCameraSnapshotBase64("back")
        }

        @JavascriptInterface
        fun captureCameraSnapshotBase64(facingParam: String = "back"): String {
            val useFront = facingParam.equals("front", ignoreCase = true)
            if (!hasCameraPermission()) {
                android.util.Log.w("MayaVision", "Kaamera luba puudub, pöördun galerii poole")
                return getLatestMediaImageBase64()
            }

            android.util.Log.d("MayaVision", "Alustan otsekaamera hetketõmmist...")
            val cameraManager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
            var resultBase64 = ""
            val latch = CountDownLatch(1)

            val handlerThread = HandlerThread("MayaCameraBackground").apply { start() }
            val bgHandler = Handler(handlerThread.looper)

            try {
                var targetCameraId: String? = null
                val targetFacing = if (useFront) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
                for (id in cameraManager.cameraIdList) {
                    val chars = cameraManager.getCameraCharacteristics(id)
                    val facing = chars.get(CameraCharacteristics.LENS_FACING)
                    if (facing == targetFacing) {
                        targetCameraId = id
                        break
                    }
                }

                if (targetCameraId == null && cameraManager.cameraIdList.isNotEmpty()) {
                    targetCameraId = cameraManager.cameraIdList[0]
                }
                val backCameraId = targetCameraId

                if (backCameraId == null) {
                    android.util.Log.e("MayaVision", "Ühtegi kaamerat ei leitud")
                    handlerThread.quitSafely()
                    return getLatestMediaImageBase64()
                }

                val imageReader = ImageReader.newInstance(1280, 720, ImageFormat.JPEG, 1)
                var activeCamera: CameraDevice? = null

                imageReader.setOnImageAvailableListener({ reader ->
                    val image = reader.acquireLatestImage()
                    if (image != null) {
                        try {
                            val buffer = image.planes[0].buffer
                            val bytes = ByteArray(buffer.remaining())
                            buffer.get(bytes)
                            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                            if (bitmap != null) {
                                resultBase64 = compressAndEncodeBitmap(bitmap)
                                android.util.Log.d("MayaVision", "Otsekaamera pilt valmis! Suurus: ${resultBase64.length}")
                            }
                        } catch (e: Exception) {
                            android.util.Log.e("MayaVision", "Viga pildikaadri lugemisel: ${e.message}")
                        } finally {
                            image.close()
                            try { activeCamera?.close() } catch (_: Exception) {}
                            activeCamera = null
                            latch.countDown()
                        }
                    }
                }, bgHandler)

                cameraManager.openCamera(backCameraId, object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        activeCamera = camera
                        try {
                            val surface = imageReader.surface
                            val captureBuilder = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                                addTarget(surface)
                                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                                set(CaptureRequest.JPEG_ORIENTATION, 90)
                            }

                            camera.createCaptureSession(listOf(surface), object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(session: CameraCaptureSession) {
                                    try {
                                        session.capture(captureBuilder.build(), null, bgHandler)
                                    } catch (e: Exception) {
                                        camera.close()
                                        activeCamera = null
                                        latch.countDown()
                                    }
                                }

                                override fun onConfigureFailed(session: CameraCaptureSession) {
                                    camera.close()
                                    activeCamera = null
                                    latch.countDown()
                                }
                            }, bgHandler)
                        } catch (e: Exception) {
                            camera.close()
                            activeCamera = null
                            latch.countDown()
                        }
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        camera.close()
                        activeCamera = null
                        latch.countDown()
                    }

                    override fun onError(camera: CameraDevice, error: Int) {
                        camera.close()
                        activeCamera = null
                        latch.countDown()
                    }
                }, bgHandler)

                latch.await(2500, TimeUnit.MILLISECONDS)
                try { activeCamera?.close() } catch (_: Exception) {}
                activeCamera = null            } catch (e: Exception) {
                android.util.Log.e("MayaVision", "Kaamera avamise viga: ${e.message}")
            } finally {
                handlerThread.quitSafely()
            }

            return if (resultBase64.isNotBlank()) resultBase64 else getLatestMediaImageBase64()
        }

        @JavascriptInterface
        fun getLatestMediaImageBase64(): String {
            return try {
                android.util.Log.d("MayaVision", "getLatestMediaImageBase64 kutsuti välja!")
                val projection = arrayOf(
                    MediaStore.Images.Media._ID,
                    MediaStore.Images.Media.DATE_MODIFIED
                )
                val uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                val sortOrder = "${MediaStore.Images.Media.DATE_MODIFIED} DESC"
                
                contentResolver.query(uri, projection, null, null, sortOrder)?.use { cursor ->
                    android.util.Log.d("MayaVision", "Cursor ridade arv: ${cursor.count}")
                    if (cursor.moveToFirst()) {
                        val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
                        val id = cursor.getLong(idColumn)
                        val imageUri = android.content.ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
                        android.util.Log.d("MayaVision", "Leiti pildi URI: $imageUri")
                        
                        val input: InputStream? = contentResolver.openInputStream(imageUri)
                        val original = BitmapFactory.decodeStream(input)
                        input?.close()
                        
                        if (original != null) {
                            val res = compressAndEncodeBitmap(original)
                            android.util.Log.d("MayaVision", "Pilt pakitud edukalt, base64 pikkus: ${res.length}")
                            return res
                        } else {
                            android.util.Log.e("MayaVision", "BitmapFactory decodeStream tagastas nulli!")
                        }
                    } else {
                        android.util.Log.w("MayaVision", "Cursor oli tühi - meediat ei leitud!")
                    }
                }
                ""
            } catch (e: Exception) {
                android.util.Log.e("MayaVision", "Viga pildi hankimisel: ${e.message}", e)
                ""
            }
        }

private fun compressAndEncodeBitmap(bitmap: Bitmap): String {
            return try {
                val maxDim = 1280
                var width = bitmap.width
                var height = bitmap.height
                
                if (width > maxDim || height > maxDim) {
                    val ratio = width.toFloat() / height.toFloat()
                    if (ratio > 1) {
                        width = maxDim
                        height = (maxDim / ratio).toInt()
                    } else {
                        height = maxDim
                        width = (maxDim * ratio).toInt()
                    }
                }
                
                val scaled = Bitmap.createScaledBitmap(bitmap, width, height, true)
                val baos = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.JPEG, 80, baos)
                val bytes = baos.toByteArray()
                Base64.encodeToString(bytes, Base64.NO_WRAP)
            } catch (e: Exception) {
                ""
            }
        }

        @JavascriptInterface
        fun hasCameraPermission(): Boolean {
            return ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        }

        @JavascriptInterface
        fun hasStoragePermission(): Boolean {
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED
            } else {
                ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
            }
        }

        @JavascriptInterface
        fun openYouTube(query: String) {
            runOnUiThread {
                try {
                    val intent = if (query.isNotBlank()) {
                        Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=" + java.net.URLEncoder.encode(query, "UTF-8")))
                    } else {
                        packageManager.getLaunchIntentForPackage("com.google.android.youtube") ?: Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com"))
                    }
                    intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    startActivity(intent)
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }
        }
    }
}

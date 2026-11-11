package com.maya.live

import android.app.KeyguardManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class IncomingCallActivity : AppCompatActivity() {
    private var ringtone: Ringtone? = null
    private var vibrator: Vibrator? = null
    private val handler = Handler(Looper.getMainLooper())
    private var isRinging = false
    private val TAG = "IncomingCall"

    private val ringRunnable = object : Runnable {
        override fun run() {
            if (!isRinging) return
            try {
                if (ringtone?.isPlaying != true) {
                    ringtone?.play()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Helina korduse viga: ${e.message}")
            }
            handler.postDelayed(this, 2000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val km = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
            km.requestDismissKeyguard(this, null)
        }
        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
            WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
            WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        )

        setContentView(R.layout.activity_incoming_call)

        val reasonText = intent.getStringExtra("CALL_REASON") ?: "Maya soovib rääkida..."
        findViewById<TextView>(R.id.txtCallReason).text = reasonText

        startCallAlert()

        findViewById<Button>(R.id.btnAccept).setOnClickListener {
            stopCallAlert()

            val intent = Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("AUTO_START_CALL", true)
                putExtra("CALL_REASON", reasonText)
            }
            startActivity(intent)
            finish()
        }

        findViewById<Button>(R.id.btnDecline).setOnClickListener {
            stopCallAlert()
            finish()
        }
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        // Kui saabub teistkordne käivitus, ei loo me uut helinat ega dubleeri seda
        Log.d(TAG, "onNewIntent: kõneaken oli juba lahti, ignoreerime topeltkäivitust")
    }

    private fun startCallAlert() {
        if (isRinging) return
        isRinging = true

        try {
            val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            audioManager.isSpeakerphoneOn = true

            val ringtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            ringtone = RingtoneManager.getRingtone(applicationContext, ringtoneUri)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                ringtone?.audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setLegacyStreamType(AudioManager.STREAM_RING)
                    .build()
            }

            ringtone?.play()
            handler.postDelayed(ringRunnable, 2000L)
            Log.d(TAG, "Ringtone käivitatud kõlarist!")

            vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            val pattern = longArrayOf(0, 1000, 800, 1000, 800)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(VibrationEffect.createWaveform(pattern, 0))
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(pattern, 0)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Heli käivitamise tõrge: ${e.message}")
        }
    }

    private fun stopCallAlert() {
        isRinging = false
        handler.removeCallbacks(ringRunnable)
        try {
            ringtone?.stop()
            vibrator?.cancel()
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.cancel(1002)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopCallAlert()
    }
}

package com.maya.live

import android.app.AlertDialog
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * MAYA SERVERI SEADISTAMISE EKRAAN.
 *
 * MIKS: avalikus versioonis ei ole ühtegi ette antud backendi aadressi
 * (vt [ServerConfig]). Esimesel käivitusel peab kasutaja ütlema, kus
 * TEMA enda MAYA server jookseb. Sama ekraani saab hiljem uuesti avada
 * rakenduse seadetest (`AndroidBridge.openServerSettings()`).
 *
 * MIDA SEE EKRAAN EI TEE
 * ----------------------
 *  - ei paku ühtegi valmis serveriaadressi;
 *  - ei ühendu ühegi kolmanda osapoole teenusega;
 *  - ei väida kunagi, et ühendus õnnestus, kui see ei õnnestunud.
 *
 * Ühenduse test käib AINULT kasutaja sisestatud aadressi vastu ja
 * küsib avalikku otspunkti `/api/auth/status`, mis ei avalda midagi.
 * Vastuse kuju on ühtlasi kontroll, et tegemist ON MAYA backendiga ja
 * mitte suvalise veebiserveriga.
 */
class ServerSetupActivity : AppCompatActivity() {

    private lateinit var vali: EditText
    private lateinit var olek: TextView
    private lateinit var testNupp: Button
    private lateinit var salvestaNupp: Button

    /** Kas just sisestatud aadressiga on ühendus TÕENDATULT õnnestunud. */
    private var kontrollitudUrl: String = ""

    private val ui = Handler(Looper.getMainLooper())

    private val tume = Color.parseColor("#0b0d10")
    private val tekst = Color.parseColor("#e8eaed")
    private val hall = Color.parseColor("#9aa0a6")
    private val sinine = Color.parseColor("#4f7cff")
    private val punane = Color.parseColor("#ff7b7b")
    private val roheline = Color.parseColor("#6ddf8f")
    private val kollane = Color.parseColor("#ffc766")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()
        setContentView(ehitaVaade())

        vali.setText(ServerConfig.eelvaartus(this))
        vali.setSelection(vali.text.length)

        if (ServerConfig.onSeadistatud(this)) {
            naita("Praegune server: " + ServerConfig.baasUrl(this), hall)
        }
    }

    // -----------------------------------------------------------------
    // VAADE
    // -----------------------------------------------------------------

    private fun dp(v: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics
    ).toInt()

    private fun ehitaVaade(): View {
        val juur = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(tume)
            setPadding(dp(24), dp(36), dp(24), dp(24))
        }

        juur.addView(TextView(this).apply {
            text = "MAYA"
            setTextColor(tekst)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 28f)
            typeface = Typeface.DEFAULT_BOLD
        })

        juur.addView(TextView(this).apply {
            text = "Serveri seadistus"
            setTextColor(hall)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            setPadding(0, dp(2), 0, dp(18))
        })

        juur.addView(TextView(this).apply {
            text = "MAYA ei kasuta ühtegi keskset teenust. Kogu töö " +
                   "käib SINU enda serveris, kus jookseb MAYA backend " +
                   "(web_maya.py) sinu enda Gemini API võtmega.\n\n" +
                   "Sisesta allpool selle serveri aadress. Näiteks:\n" +
                   "  •  http://192.168.1.50:8000  (sama Wi-Fi)\n" +
                   "  •  http://100.64.0.5:8000  (Tailscale/WireGuard)\n" +
                   "  •  https://maya.example.com  (oma domeen, HTTPS)\n\n" +
                   "Need on ainult NÄITED – pane siia oma enda aadress. " +
                   "Paigaldusjuhend on hoidlas failis docs/PAIGALDUS.md."
            setTextColor(hall)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setLineSpacing(0f, 1.25f)
            setPadding(0, 0, 0, dp(18))
        })

        juur.addView(TextView(this).apply {
            text = "Serveri aadress"
            setTextColor(hall)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(0, 0, 0, dp(4))
        })

        vali = EditText(this).apply {
            hint = "http://192.168.1.50:8000"
            setHintTextColor(Color.parseColor("#5f6368"))
            setTextColor(tekst)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            setBackgroundColor(Color.parseColor("#15181c"))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            inputType = InputType.TYPE_CLASS_TEXT or
                        InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            contentDescription = "MAYA serveri aadress"
        }
        juur.addView(vali, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT))

        testNupp = Button(this).apply {
            text = "Testi ühendust"
            setTextColor(Color.WHITE)
            setBackgroundColor(sinine)
            setOnClickListener { testiUhendust() }
        }
        juur.addView(testNupp, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(16) })

        olek = TextView(this).apply {
            text = ""
            setTextColor(hall)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setLineSpacing(0f, 1.25f)
            setPadding(0, dp(14), 0, dp(14))
            minHeight = dp(48)
        }
        juur.addView(olek)

        salvestaNupp = Button(this).apply {
            text = "Salvesta ja jätka"
            setTextColor(tekst)
            setBackgroundColor(Color.parseColor("#22262c"))
            setOnClickListener { salvesta() }
        }
        juur.addView(salvestaNupp, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT))

        if (ServerConfig.onSeadistatud(this)) {
            juur.addView(Button(this).apply {
                text = "Tühista"
                setTextColor(hall)
                setBackgroundColor(Color.TRANSPARENT)
                setOnClickListener { finish() }
            }, LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(6) })
        }

        juur.addView(TextView(this).apply {
            text = "Aadress salvestatakse ainult sellesse telefoni. " +
                   "Seda saab hiljem muuta rakenduse seadetest."
            setTextColor(Color.parseColor("#5f6368"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setPadding(0, dp(18), 0, 0)
            gravity = Gravity.START
        })

        return ScrollView(this).apply {
            setBackgroundColor(tume)
            addView(juur, ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT))
        }
    }

    private fun naita(sonum: String, varv: Int) {
        ui.post {
            olek.text = sonum
            olek.setTextColor(varv)
        }
    }

    // -----------------------------------------------------------------
    // ÜHENDUSE TEST
    // -----------------------------------------------------------------

    private fun testiUhendust() {
        val t = ServerConfig.normaliseeri(vali.text.toString())
        if (!t.ok) {
            kontrollitudUrl = ""
            naita(t.viga, punane)
            return
        }
        // Näitame normaliseeritud kuju kohe ära, et kasutaja näeks,
        // millise aadressiga tegelikult ühendust võetakse.
        vali.setText(t.url)
        vali.setSelection(t.url.length)

        testNupp.isEnabled = false
        testNupp.text = "Testin…"
        naita("Võtan ühendust: " + t.url, hall)

        thread {
            val tulemus = proovi(t.url)
            ui.post {
                testNupp.isEnabled = true
                testNupp.text = "Testi ühendust"
                if (tulemus.onnestus) {
                    kontrollitudUrl = t.url
                    val lisa = if (t.hoiatus.isNotEmpty())
                        "\n\n" + t.hoiatus else ""
                    naita("✓ " + tulemus.sonum + lisa,
                          if (t.hoiatus.isEmpty()) roheline else kollane)
                } else {
                    kontrollitudUrl = ""
                    naita("✗ " + tulemus.sonum, punane)
                }
            }
        }
    }

    private data class Katse(val onnestus: Boolean, val sonum: String)

    /**
     * Päri `/api/auth/status`. See on AINUS avalik otspunkt ja ta ei
     * avalda kasutajanimesid ega muud sisu – ainult seda, kas
     * paigaldus on juba seadistatud.
     */
    private fun proovi(base: String): Katse {
        var conn: HttpURLConnection? = null
        return try {
            val url = URL("$base/api/auth/status")
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 8000
                readTimeout = 8000
                instanceFollowRedirects = true
                setRequestProperty("Accept", "application/json")
            }
            val kood = conn.responseCode
            if (kood != 200) {
                return Katse(false, when (kood) {
                    404 -> "Server vastas, aga aadressil ei ole MAYA " +
                           "backendi (/api/auth/status andis 404). " +
                           "Kontrolli porti."
                    401, 403 -> "Server vastas koodiga $kood. Ees on " +
                           "tõenäoliselt pöördproksi oma autentimisega."
                    502, 503, 504 -> "Pöördproksi vastas koodiga $kood – " +
                           "MAYA backend ise ei tööta."
                    else -> "Server vastas HTTP koodiga $kood."
                })
            }
            val keha = conn.inputStream.bufferedReader()
                .use { it.readText() }.take(4000)
            val j = try {
                org.json.JSONObject(keha)
            } catch (e: Exception) {
                return Katse(false, "Server vastas, aga vastus ei ole " +
                        "MAYA oma. Kontrolli, et aadress viitab MAYA " +
                        "backendile, mitte mõnele teisele teenusele.")
            }
            if (!j.has("seadistatud")) {
                return Katse(false, "Server vastas JSON-iga, aga see ei " +
                        "ole MAYA backend.")
            }
            val seadistatud = j.optBoolean("seadistatud", false)
            val regLubatud = j.optBoolean("registreerimine_lubatud", false)
            val kutsekood = j.optBoolean("kutsekood_noutud", false)
            val osad = mutableListOf("MAYA server vastas.")
            osad.add(if (seadistatud)
                "Kontod on olemas – logi järgmisel ekraanil sisse."
            else
                "Kontosid veel ei ole – esimene loodud konto saab " +
                "administraatori õigused.")
            if (!seadistatud && !regLubatud) {
                osad.add("NB: registreerimine on serveris keelatud " +
                         "(MAYA_ALLOW_REGISTRATION=0).")
            }
            if (kutsekood) osad.add("Konto loomisel küsitakse kutsekoodi.")
            Katse(true, osad.joinToString(" "))
        } catch (e: java.net.UnknownHostException) {
            Katse(false, "Serveri nime ei leitud. Kontrolli aadressi " +
                    "kirjapilti või kasuta IP-aadressi.")
        } catch (e: java.net.SocketTimeoutException) {
            Katse(false, "Server ei vastanud 8 sekundi jooksul. Kas " +
                    "telefon on samas võrgus ja kas tulemüür laseb " +
                    "pordi läbi?")
        } catch (e: java.net.ConnectException) {
            Katse(false, "Ühendust ei saadud. Kontrolli, et MAYA " +
                    "backend töötab (./kaivita.sh) ja et aadress ning " +
                    "port on õiged.")
        } catch (e: javax.net.ssl.SSLException) {
            Katse(false, "HTTPS/TLS viga: " + (e.message ?: "tundmatu") +
                    ". Ise allkirjastatud sertifikaat ei tööta – kasuta " +
                    "päris sertifikaati (nt Caddy/Let's Encrypt).")
        } catch (e: Exception) {
            Katse(false, "Ühendus ebaõnnestus: " +
                    (e.message ?: e.javaClass.simpleName))
        } finally {
            try { conn?.disconnect() } catch (_: Exception) {}
        }
    }

    // -----------------------------------------------------------------
    // SALVESTAMINE
    // -----------------------------------------------------------------

    private fun salvesta() {
        val t = ServerConfig.normaliseeri(vali.text.toString())
        if (!t.ok) {
            naita(t.viga, punane)
            return
        }
        if (t.url != kontrollitudUrl) {
            // AUSUS: me EI tee näo, et ühendus töötab. Kasutaja võib
            // siiski salvestada (server võib hetkel kinni olla), aga
            // ainult teadlikult.
            AlertDialog.Builder(this)
                .setTitle("Ühendust ei ole kontrollitud")
                .setMessage("Aadressiga " + t.url + " ei ole praeguses " +
                        "kujus edukat ühendust tõendatud.\n\nKas " +
                        "salvestan selle siiski? Saad hiljem seadetest " +
                        "muuta.")
                .setPositiveButton("Salvesta siiski") { _, _ -> kirjuta(t) }
                .setNegativeButton("Testi enne", null)
                .show()
            return
        }
        kirjuta(t)
    }

    private fun kirjuta(t: ServerConfig.Tulem) {
        val salvestatud = ServerConfig.salvesta(this, t.url)
        if (!salvestatud.ok) {
            naita(salvestatud.viga, punane)
            return
        }
        // Serveri vahetamine teeb vana tokeni kasutuks: token kuulub
        // konkreetsele paigaldusele. Kustutame selle, et kasutaja ei
        // satuks poolikusse olekusse.
        getSharedPreferences(MainActivity.MAYA_PREFS, Context.MODE_PRIVATE)
            .edit().remove(MainActivity.MAYA_TOKEN_KEY).apply()

        setResult(RESULT_OK)
        finish()
    }
}

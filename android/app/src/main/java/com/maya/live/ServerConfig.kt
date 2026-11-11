package com.maya.live

import android.content.Context
import java.net.URI

/**
 * MAYA BACKENDI AADRESS — KASUTAJA SEADISTAB ISE.
 *
 * MIKS SEE FAIL OLEMAS ON
 * -----------------------
 * Varem tuli backendi aadress `gradle.properties` -> `BuildConfig`
 * kaudu, see tähendas, et APK oli seotud ÜHE konkreetse serveriga.
 * Avalikus versioonis ei tohi ühtegi aadressi ette antud olla: iga
 * kasutaja jooksutab oma backendi oma võrgus. Seega elab aadress
 * `SharedPreferences`-is ja kasutaja sisestab selle esimesel
 * käivitusel [ServerSetupActivity] ekraanil.
 *
 * MIKS NATIIVNE JA MITTE WebView'S
 * --------------------------------
 * [CallWatcherService] jookseb taustal ilma WebView'ta ja vajab sama
 * aadressi, et SSE-vooga ühenduda. Kui aadress elaks veebikihi
 * `localStorage`-is, ei saaks taustateenus seda kätte. Seetõttu on
 * `SharedPreferences` ainus õige koht ja veebikiht küsib aadressi
 * siit (`AndroidBridge.getBaseUrls()`).
 *
 * TESTITAVUS
 * ----------
 * Kogu kontroll ja teisendus on PUHTAD funktsioonid ([normaliseeri],
 * [wsAadress], [altAadress], [visionAadress]), mis ei vaja `Context`-i
 * ega Androidi raamistikku. Nii katavad neid tavalised JVM-testid
 * (`app/src/test/.../ServerConfigTest.kt`), mitte ainult
 * lähtekoodi mustriotsing.
 */
object ServerConfig {

    const val PREFS = "maya_server"
    const val KEY_BASE_URL = "base_url"

    /** MAYA backendi vaikeport (`web_maya.py` / `MAYA_PORT`). */
    const val VAIKEPORT = 8000

    /** Puhta kontrolli tulemus. [url] on täidetud ainult kui [ok]. */
    data class Tulem(
        val ok: Boolean,
        val url: String = "",
        val viga: String = "",
        /** Hoiatus, mida tohib näidata ka õnnestumisel (nt HTTP). */
        val hoiatus: String = ""
    )

    // -----------------------------------------------------------------
    // PUHAS LOOGIKA
    // -----------------------------------------------------------------

    /**
     * Kontrolli ja normaliseeri kasutaja sisestatud aadress.
     *
     * Reeglid:
     *  - tühi sisend on viga;
     *  - skeemi puudumisel lisatakse `http://` (kohtvõrgu tavajuht);
     *  - lubatud on AINULT `http` ja `https`;
     *  - `?` ja `#` ei ole aadressis lubatud;
     *  - lõpust eemaldatakse kaldkriipsud;
     *  - kui host on IP-aadress või `localhost` ja porti ei ole antud,
     *    lisatakse MAYA vaikeport 8000.
     */
    fun normaliseeri(sisend: String?): Tulem {
        val toores = (sisend ?: "").trim()
        if (toores.isEmpty()) {
            return Tulem(false, viga = "Sisesta oma MAYA serveri aadress.")
        }
        if (toores.any { it.isWhitespace() }) {
            return Tulem(false, viga = "Aadressis ei tohi olla tühikuid.")
        }
        if (toores.contains("?") || toores.contains("#")) {
            return Tulem(false,
                viga = "Aadressis ei tohi olla märke „?\" ega „#\".")
        }

        val skeemiga =
            if (toores.contains("://")) toores else "http://$toores"

        val uri = try {
            URI(skeemiga)
        } catch (e: Exception) {
            return Tulem(false, viga = "Aadress ei ole korrektne URL.")
        }

        val skeem = (uri.scheme ?: "").lowercase()
        if (skeem != "http" && skeem != "https") {
            return Tulem(false,
                viga = "Lubatud on ainult http:// või https:// aadress.")
        }

        val host = (uri.host ?: "").lowercase()
        if (host.isEmpty()) {
            return Tulem(false,
                viga = "Aadressist puudub serveri nimi või IP.")
        }

        var port = uri.port   // -1 kui puudub
        if (port == -1 && kasPordVajalik(host)) {
            port = VAIKEPORT
        }
        if (port != -1 && (port < 1 || port > 65535)) {
            return Tulem(false, viga = "Port peab olema vahemikus 1–65535.")
        }

        val tee = (uri.path ?: "").trimEnd('/')

        val ehitatud = buildString {
            append(skeem).append("://").append(host)
            if (port != -1) append(":").append(port)
            append(tee)
        }

        val hoiatus = if (skeem == "http" && !kasPrivaatHost(host)) {
            "HOIATUS: http:// ei ole krüpteeritud. Avalikus internetis " +
            "kasuta https:// (vt docs/TURVALISUS.md)."
        } else {
            ""
        }

        return Tulem(true, url = ehitatud, hoiatus = hoiatus)
    }

    /**
     * Kas hostile tuleb vaikeport lisada?
     *
     * IP-aadressi või `localhost` puhul jah – seal jookseb peaaegu
     * kindlasti `web_maya.py` pordil 8000. Nimega hosti puhul MITTE,
     * sest see käib tavaliselt läbi pöördproksi pordil 80/443.
     */
    private fun kasPordVajalik(host: String): Boolean {
        if (host == "localhost") return true
        if (host.matches(Regex("^\\d{1,3}(\\.\\d{1,3}){3}$"))) return true
        if (host.contains(":")) return true          // IPv6 literaal
        return false
    }

    /** Kas host on kohtvõrgus või privaatvõrgus (HTTP on siis OK)? */
    fun kasPrivaatHost(host: String): Boolean {
        val h = host.lowercase()
        if (h == "localhost" || h == "127.0.0.1" || h == "::1") return true
        if (h.endsWith(".local") || h.endsWith(".internal")) return true
        if (h.startsWith("10.")) return true
        if (h.startsWith("192.168.")) return true
        if (h.startsWith("100.")) return true        // CGNAT / Tailscale
        val osad = h.split(".")
        if (osad.size == 4 && osad[0] == "172") {
            val teine = osad[1].toIntOrNull() ?: -1
            if (teine in 16..31) return true
        }
        return false
    }

    /**
     * WebSocketi aadress baas-URL-ist: `http` -> `ws`, `https` -> `wss`.
     * Host, port ja teeprefiks jäävad samaks.
     */
    fun wsAadress(base: String): String {
        val b = base.trim().trimEnd('/')
        return when {
            b.startsWith("https://") -> "wss://" + b.removePrefix("https://")
            b.startsWith("http://") -> "ws://" + b.removePrefix("http://")
            else -> b
        }
    }

    /**
     * SSE kasutab sama HTTP(S) baasi (`/api/call_events`), seega eraldi
     * teisendust ei vaja. Funktsioon on olemas, et kutsumiskohad oleks
     * loetavad ja et SSE sihtkoht oleks testitav.
     */
    fun sseAadress(base: String): String = base.trim().trimEnd('/')

    /**
     * VALIKULISED LISATEENUSED.
     *
     * Originaalpaigalduses jooksid `alt` (8001) ja `vision` (8002)
     * eraldi protsessidena. Kui baasaadressil on selgelt antud port,
     * vahetame selle; kui porti ei ole (pöördproksi taga), jääb aadress
     * baasiga samaks ja vastav valikuline funktsioon lihtsalt kasutab
     * põhiserverit. Kui teenust ei jookse, vaikib funktsioon.
     */
    fun altAadress(base: String): String = pordiga(base, 8001)
    fun visionAadress(base: String): String = pordiga(base, 8002)

    private fun pordiga(base: String, port: Int): String {
        val b = base.trim().trimEnd('/')
        val re = Regex("^(https?://[^/:]+):\\d+(.*)$")
        val m = re.find(b) ?: return b
        return "${m.groupValues[1]}:$port${m.groupValues[2]}"
    }

    // -----------------------------------------------------------------
    // SALVESTUS
    // -----------------------------------------------------------------

    /** Seadistatud aadress või tühi string, kui kasutaja pole veel seadistanud. */
    fun baasUrl(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_BASE_URL, "")?.trim()?.trimEnd('/') ?: ""

    fun onSeadistatud(ctx: Context): Boolean = baasUrl(ctx).isNotEmpty()

    /**
     * Salvesta aadress. Tagastab [Tulem]-i: kui kontroll ei läbinud, EI
     * salvestata midagi ja [Tulem.viga] ütleb miks.
     */
    fun salvesta(ctx: Context, sisend: String?): Tulem {
        val t = normaliseeri(sisend)
        if (!t.ok) return t
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_BASE_URL, t.url).apply()
        return t
    }

    fun kustuta(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().remove(KEY_BASE_URL).apply()
    }

    /**
     * Ettepanek seadistusvälja jaoks. Tagastab juba seadistatud
     * aadressi; kui seda ei ole, siis arendaja ehitusaegse vihje
     * (`-PmayaBaseUrl=...`), mis AVALIKUS ehituses on TÜHI.
     */
    fun eelvaartus(ctx: Context): String {
        val olemas = baasUrl(ctx)
        if (olemas.isNotEmpty()) return olemas
        return BuildConfig.MAYA_DEFAULT_BASE_URL.trim()
    }

    /** Kõik veebikihile vajalikud aadressid ühe JSON-ina. */
    fun veebiJson(ctx: Context): String {
        val base = baasUrl(ctx)
        val o = org.json.JSONObject()
        o.put("base", base)
        o.put("ws", if (base.isEmpty()) "" else wsAadress(base))
        o.put("sse", if (base.isEmpty()) "" else sseAadress(base))
        o.put("alt", if (base.isEmpty()) "" else altAadress(base))
        o.put("vision", if (base.isEmpty()) "" else visionAadress(base))
        o.put("seadistatud", base.isNotEmpty())
        return o.toString()
    }
}

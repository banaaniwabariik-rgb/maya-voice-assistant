package com.maya.live

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * MAYA SERVERI SEADISTUSE TESTID.
 *
 * Need on tavalised JVM-testid (`./gradlew testDebugUnitTest`) – nad
 * jooksutavad PÄRIS [ServerConfig] koodi, mitte ei otsi mustreid
 * lähtekoodist. Kaetud on kogu puhas loogika: kontroll, normaliseerimine
 * ja WS/SSE/alt/vision aadresside tuletamine.
 *
 * Salvestust (`SharedPreferences`) siin ei testita, sest see vajab
 * Androidi raamistikku. Salvestuse ühendused on kaetud staatiliselt
 * (`tests/tests_serveri_seadistus.py`) ja APK sisu kontrolliga.
 */
class ServerConfigTest {

    // -----------------------------------------------------------------
    // 1. APK-s EI OLE ÜHTEGI ETTE ANTUD AADRESSI
    // -----------------------------------------------------------------

    @Test
    fun vaikeaadressPuudubAvalikusEhituses() {
        // Avalik ehitus käib ilma -PmayaDefaultBaseUrl liputa.
        assertEquals("avalikus ehituses peab vaikeaadress olema tühi",
                     "", BuildConfig.MAYA_DEFAULT_BASE_URL)
    }

    // -----------------------------------------------------------------
    // 2. KONTROLL JA VEATEATED
    // -----------------------------------------------------------------

    @Test
    fun tuhiSisendAnnabVea() {
        val t = ServerConfig.normaliseeri("")
        assertFalse(t.ok)
        assertTrue(t.viga.isNotEmpty())
        assertEquals("", t.url)
    }

    @Test
    fun nullSisendAnnabVea() {
        assertFalse(ServerConfig.normaliseeri(null).ok)
    }

    @Test
    fun tuhikudOnViga() {
        val t = ServerConfig.normaliseeri("http://minu server:8000")
        assertFalse(t.ok)
        assertTrue(t.viga.contains("tühikuid"))
    }

    @Test
    fun paringustringOnViga() {
        assertFalse(ServerConfig.normaliseeri("http://a.example.com/?x=1").ok)
        assertFalse(ServerConfig.normaliseeri("http://a.example.com/#x").ok)
    }

    @Test
    fun vaarSkeemOnViga() {
        val t = ServerConfig.normaliseeri("ftp://a.example.com")
        assertFalse(t.ok)
        assertTrue(t.viga.contains("http"))
    }

    @Test
    fun hostitaOnViga() {
        assertFalse(ServerConfig.normaliseeri("http://").ok)
    }

    @Test
    fun vigaseidVeateateidEiOleTuhjad() {
        // Iga veateade peab olema eestikeelne ja inimesele arusaadav.
        val halvad = listOf("", "   ", "ftp://x", "http://", "http://a b")
        for (s in halvad) {
            val t = ServerConfig.normaliseeri(s)
            assertFalse("'$s' peaks olema viga", t.ok)
            assertTrue("veateade puudub: '$s'", t.viga.length > 10)
        }
    }

    // -----------------------------------------------------------------
    // 3. NORMALISEERIMINE
    // -----------------------------------------------------------------

    @Test
    fun skeemPuuduLisatakseHttp() {
        val t = ServerConfig.normaliseeri("192.168.1.50:8000")
        assertTrue(t.ok)
        assertEquals("http://192.168.1.50:8000", t.url)
    }

    @Test
    fun vaikeportLisatakseIpAadressile() {
        val t = ServerConfig.normaliseeri("192.168.1.50")
        assertTrue(t.ok)
        assertEquals("http://192.168.1.50:8000", t.url)
    }

    @Test
    fun vaikeportLisatakseLocalhostile() {
        assertEquals("http://localhost:8000",
                     ServerConfig.normaliseeri("localhost").url)
    }

    @Test
    fun nimegaHostileVaikeportiEiLisata() {
        // Pöördproksi taga on port 443, mitte 8000.
        val t = ServerConfig.normaliseeri("https://maya.example.com")
        assertTrue(t.ok)
        assertEquals("https://maya.example.com", t.url)
    }

    @Test
    fun lopuKaldkriipsEemaldatakse() {
        assertEquals("https://maya.example.com",
                     ServerConfig.normaliseeri("https://maya.example.com/").url)
        assertEquals("https://maya.example.com",
                     ServerConfig.normaliseeri("https://maya.example.com///").url)
    }

    @Test
    fun suurtahedHostisTeisendatakseVaikeseks() {
        assertEquals("https://maya.example.com",
                     ServerConfig.normaliseeri("HTTPS://MAYA.Example.COM").url)
    }

    @Test
    fun teeprefiksJaabAlles() {
        // Pöördproksi võib MAYA paigutada alamteele.
        assertEquals("https://example.com/maya",
                     ServerConfig.normaliseeri("https://example.com/maya/").url)
    }

    @Test
    fun umbritsevadTuhikudEemaldatakse() {
        assertEquals("http://10.1.2.3:8000",
                     ServerConfig.normaliseeri("  http://10.1.2.3:8000  ").url)
    }

    @Test
    fun vigasePordigaOnViga() {
        assertFalse(ServerConfig.normaliseeri("http://10.1.2.3:99999").ok)
    }

    // -----------------------------------------------------------------
    // 4. HTTP HOIATUS — EI VÄIDA, ET KRÜPTEERIMATA ON TURVALINE
    // -----------------------------------------------------------------

    @Test
    fun avalikHttpAnnabHoiatuse() {
        val t = ServerConfig.normaliseeri("http://maya.example.com")
        assertTrue(t.ok)
        assertTrue("avaliku HTTP puhul peab tulema hoiatus",
                   t.hoiatus.contains("http"))
    }

    @Test
    fun kohtvorguHttpEiHoiata() {
        for (a in listOf("http://192.168.1.50:8000", "http://10.0.0.5:8000",
                         "http://172.16.0.9:8000", "http://100.64.0.5:8000",
                         "http://localhost:8000", "http://127.0.0.1:8000")) {
            val t = ServerConfig.normaliseeri(a)
            assertTrue(a, t.ok)
            assertEquals("kohtvõrgus ei pea HTTP hoiatust olema: $a",
                         "", t.hoiatus)
        }
    }

    @Test
    fun httpsEiHoiata() {
        assertEquals("", ServerConfig.normaliseeri("https://maya.example.com").hoiatus)
    }

    @Test
    fun privaatHostiTuvastus() {
        assertTrue(ServerConfig.kasPrivaatHost("192.168.4.4"))
        assertTrue(ServerConfig.kasPrivaatHost("10.9.9.9"))
        assertTrue(ServerConfig.kasPrivaatHost("172.20.0.1"))
        assertTrue(ServerConfig.kasPrivaatHost("maya.local"))
        assertFalse(ServerConfig.kasPrivaatHost("198.51.100.7"))
        assertFalse(ServerConfig.kasPrivaatHost("maya.example.com"))
        // 203.0.113.0/24 on RFC 5737 dokumentatsioonivahemik – avalik.
        assertFalse(ServerConfig.kasPrivaatHost("203.0.113.9"))
    }

    // -----------------------------------------------------------------
    // 5. WS / SSE / ALT / VISION TULETAMINE
    // -----------------------------------------------------------------

    @Test
    fun httpsAnnabWss() {
        assertEquals("wss://maya.example.com",
                     ServerConfig.wsAadress("https://maya.example.com"))
    }

    @Test
    fun httpAnnabWs() {
        assertEquals("ws://192.168.1.50:8000",
                     ServerConfig.wsAadress("http://192.168.1.50:8000"))
    }

    @Test
    fun wsAadressHoiabPortiJaTeed() {
        assertEquals("wss://example.com:9443/maya",
                     ServerConfig.wsAadress("https://example.com:9443/maya"))
    }

    @Test
    fun sseKasutabSamaHttpBaasi() {
        assertEquals("https://maya.example.com",
                     ServerConfig.sseAadress("https://maya.example.com/"))
    }

    @Test
    fun aadressiMuutmineMuudabKoikiSihtkohti() {
        // NÕUE: aadressi vahetamine peab muutma API, SSE ja WS sihtkohti
        // ÜHE KORRAGA – ükski neist ei tohi vanale serverile jääda.
        val vana = "http://192.168.1.50:8000"
        val uus = "https://maya.example.com"

        assertEquals("ws://192.168.1.50:8000", ServerConfig.wsAadress(vana))
        assertEquals(vana, ServerConfig.sseAadress(vana))

        assertEquals("wss://maya.example.com", ServerConfig.wsAadress(uus))
        assertEquals(uus, ServerConfig.sseAadress(uus))

        // Ükski tuletatud aadress ei tohi sisaldada vana hosti.
        for (a in listOf(ServerConfig.wsAadress(uus),
                         ServerConfig.sseAadress(uus),
                         ServerConfig.altAadress(uus),
                         ServerConfig.visionAadress(uus))) {
            assertFalse("vana host jäi alles: $a", a.contains("192.168.1.50"))
        }
    }

    @Test
    fun altJaVisionVahetavadPorti() {
        assertEquals("http://192.168.1.50:8001",
                     ServerConfig.altAadress("http://192.168.1.50:8000"))
        assertEquals("http://192.168.1.50:8002",
                     ServerConfig.visionAadress("http://192.168.1.50:8000"))
    }

    @Test
    fun porditaAadressilAltJaabBaasiks() {
        // Pöördproksi taga ei ole eraldi porte – valikuline teenus
        // kasutab siis põhiserverit, mitte väljamõeldud aadressi.
        val base = "https://maya.example.com"
        assertEquals(base, ServerConfig.altAadress(base))
        assertEquals(base, ServerConfig.visionAadress(base))
    }

    // -----------------------------------------------------------------
    // 6. ÜKSKI TULETATUD AADRESS EI VIITA KOLMANDALE OSAPOOLELE
    // -----------------------------------------------------------------

    @Test
    fun tuletamineEiLisaVoorastHosti() {
        val base = "http://10.11.12.13:8000"
        for (a in listOf(ServerConfig.wsAadress(base),
                         ServerConfig.sseAadress(base),
                         ServerConfig.altAadress(base),
                         ServerConfig.visionAadress(base))) {
            assertTrue("tuletatud aadress peab jääma samale hostile: $a",
                       a.contains("10.11.12.13"))
        }
    }
}

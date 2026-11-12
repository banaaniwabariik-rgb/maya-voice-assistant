#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — Androidi rakenduse sõltumatuse testid.

MIDA NEED TESTID TÕESTAVAD
--------------------------
1. Värskes ehituses EI OLE ühtegi ette antud backendi aadressi:
   ei `gradle.properties`-is, ei `BuildConfig`-is, ei Kotlinis,
   ei `index.html`-is, ei `calendar_module.js`-is.
2. Aadress tuleb AINULT kasutaja seadistusest (`ServerConfig` ->
   `SharedPreferences`) ja püsib üle taaskäivituste.
3. Kõik sihtkohad – HTTP API, autentimine, SSE ja WebSocket – tulevad
   SAMAST seadistatud baasaadressist; ükski ei ole eraldi kõvakodeeritud.
4. Rakendus ei võta ühendust enne, kui kasutaja on aadressi andnud.
5. Gemini API võti jääb backendi: Androidi lähtekoodis ja APK sisus ei
   ole ühtegi võtmemustrit.
6. Ehitatud APK sisus (DEX, ressursid, varad, manifest) ei ole omaniku
   IP-d, hostinime, Tailscale'i aadressi ega emulaatori aadressi.
7. Varasemad mehhanismid – autentimine, ühekordne WS pilet ja mitme
   seadme teavitus – on endiselt kliendis olemas.

MIDA NEED EI TÕESTA
-------------------
Siin ei ole ühtegi päris seadme testi. Need testid kontrollivad
lähtekoodi, ehitusseadistust ja ehitatud APK BAITE – mitte seda, kuidas
rakendus päris telefonis käitub. Puhta loogika (kontroll,
normaliseerimine, ws/sse tuletamine) jooksutavad päriselt Kotlini
testid: `android/app/src/test/java/com/maya/live/ServerConfigTest.kt`
(`./gradlew testDebugUnitTest`).
"""

import pathlib
import re
import subprocess
import unittest
import zipfile

JUUR = pathlib.Path(__file__).resolve().parent.parent
ANDROID = JUUR / "android"
KOOD = ANDROID / "app/src/main/java/com/maya/live"
VARAD = ANDROID / "app/src/main/assets"

SERVER_CONFIG = (KOOD / "ServerConfig.kt").read_text(encoding="utf-8")
SETUP = (KOOD / "ServerSetupActivity.kt").read_text(encoding="utf-8")
MAIN = (KOOD / "MainActivity.kt").read_text(encoding="utf-8")
WATCHER = (KOOD / "CallWatcherService.kt").read_text(encoding="utf-8")
HTML = (VARAD / "index.html").read_text(encoding="utf-8")
KALENDER = (VARAD / "calendar_module.js").read_text(encoding="utf-8")
GRADLE = (ANDROID / "app/build.gradle").read_text(encoding="utf-8")
PROPS = (ANDROID / "gradle.properties").read_text(encoding="utf-8")
MANIFEST = (ANDROID / "app/src/main/AndroidManifest.xml").read_text(
    encoding="utf-8")

KOTLIN_FAILID = sorted(KOOD.glob("*.kt"))

# Universaalne APK. Kui seda ei ole ehitatud, jäetakse APK testid vahele
# (ja seda ÖELDAKSE välja – vahelejätmist ei tohi lugeda õnnestumiseks).
UNIVERSAL_APK = JUUR / "valjalase/maya-universal.apk"

# =====================================================================
# MIS ON „KEELATUD AADRESS"
# =====================================================================
# Siia EI kirjutata omaniku päris aadresse – see fail läheb avalikku
# hoidlasse ja aadressi kirjapanek oleks ise lekkimine. Kontroll on
# selle asemel POSITIIVNE: lubatud on AINULT allpool loetletud
# reserveeritud näiteaadressid ja rakenduse päriselt kasutatavad
# välisteenused. Kõik muu kukutab testi läbi, ükskõik kelle aadress
# see on. See on rangem kui nimekiri konkreetsetest aadressidest.
#
#   RFC 1918  – 192.168.1.50  (kohtvõrgu näide)
#   RFC 6598  – 100.64.0.5    (CGNAT / VPN näide)
#   RFC 2606  – maya.example.com, example.com
#   RFC 5737  – 203.0.113.x, 198.51.100.x, 192.0.2.x
LUBATUD_NAITED = ["192.168.1.50", "100.64.0.5", "maya.example.com",
                  "example.com", "localhost", "127.0.0.1", "0.0.0.0",
                  "203.0.113.", "198.51.100.", "192.0.2."]

# Emulaatori erijuht: töötab AINULT Androidi emulaatoris ja avalikus
# APK-s on ta lihtsalt eksitav vaikeaadress.
EMULAATORI_AADRESS = "10.0.2.2"

# Kõik IPv4-kujulised stringid, mis EI OLE lubatud näited.
IP_MUSTER = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _lubatud_ip(ip: str) -> bool:
    if ip == EMULAATORI_AADRESS:
        return False
    if any(ip == n or ip.startswith(n) for n in LUBATUD_NAITED):
        return True
    # Versiooninumbrid ja maskid, mis näevad välja nagu IP.
    return ip in ("255.255.255.0", "1.2.3.4") or ip.endswith(".0.0.0")


def voorad_ipd(tekst: str) -> list:
    """Kõik IP-kujulised stringid, mis ei ole lubatud näited."""
    return sorted({ip for ip in IP_MUSTER.findall(tekst)
                   if not _lubatud_ip(ip)})

# =====================================================================
# KOHALIK ISIKUANDMETE MUSTRINIMEKIRI — EI KUULU HOIDLASSE
# =====================================================================
# MIKS NII: varem olid omaniku nimi ja e-posti kasutajanimi siin failis
# „keelatud stringidena" kirjas. See on iseenesest leke – avalikus
# hoidlas oleks nimi kirjas just selles failis, mis peaks seda ära
# hoidma. Nüüd loetakse mustrid failist, mis on `.gitignore`-is:
#
#     tests/privaatsed_mustrid.txt      (üks muster rea kohta, # = kommentaar)
#
# Kui fail puudub (avalik koopia, CI, võõras masin), jäetakse vastav
# kontroll VAHELE ja seda öeldakse välja. Vahelejätmine EI OLE
# õnnestumine – omanik hoiab faili oma masinas ja saab täiskontrolli.
def privaatsed_mustrid() -> list:
    f = JUUR / "tests" / "privaatsed_mustrid.txt"
    if not f.exists():
        return []
    read = []
    for r in f.read_text(encoding="utf-8").splitlines():
        r = r.strip()
        if r and not r.startswith("#"):
            read.append(r)
    return read


VOTME_MUSTRID = [
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),      # Google API võti
    re.compile(r"gsk_[0-9A-Za-z]{30,}"),          # Groq
    re.compile(r"tvly-[0-9A-Za-z]{20,}"),         # Tavily
    re.compile(r"sk-[0-9A-Za-z]{30,}"),           # OpenAI-stiilis
    re.compile(r"ghp_[0-9A-Za-z]{30,}"),          # GitHub
]


# =====================================================================
# 1. VÄRSKES EHITUSES EI OLE ETTE ANTUD AADRESSI
# =====================================================================

class TestVaikeaadressPuudub(unittest.TestCase):

    def test_01_gradle_properties_ei_sea_aadressi(self):
        """gradle.properties ei tohi püsivat aadressi sisaldada."""
        for rida in PROPS.splitlines():
            r = rida.strip()
            if r.startswith("#") or not r:
                continue
            self.assertFalse(
                r.lower().startswith("mayabaseurl") or
                r.lower().startswith("mayadefaultbaseurl"),
                f"gradle.properties seab backendi aadressi: {r}")

    def test_02_buildconfig_vaikevaartus_on_tuhi(self):
        """build.gradle vaikeväärtus peab olema tühi string."""
        self.assertIn("mayaDefaultBaseUrl", GRADLE)
        # Vaikeväärtus on `?: ''` – mitte ükski aadress.
        m = re.search(
            r"findProperty\('mayaDefaultBaseUrl'\)\s*\?:\s*'([^']*)'", GRADLE)
        self.assertIsNotNone(m, "vaikeväärtuse rida puudub build.gradle-is")
        self.assertEqual("", m.group(1),
                         "build.gradle annab backendile vaikeaadressi")

    def test_03_vana_buildconfig_valja_ei_kasutata(self):
        """Vana `MAYA_BASE_URL` konstanti ei tohi enam kasutada."""
        for f in KOTLIN_FAILID:
            s = f.read_text(encoding="utf-8")
            self.assertNotIn(
                "BuildConfig.MAYA_BASE_URL", s,
                f"{f.name} kasutab endiselt kõvakodeeritud BuildConfig "
                f"aadressi")

    def test_04_kotlinis_pole_voorast_aadressi(self):
        """Kotlinis tohib olla AINULT reserveeritud näiteaadress."""
        for f in KOTLIN_FAILID:
            s = f.read_text(encoding="utf-8")
            self.assertEqual([], voorad_ipd(s),
                             f"{f.name} sisaldab võõrast IP-aadressi")
            self.assertNotIn(EMULAATORI_AADRESS, s,
                             f"{f.name} sisaldab emulaatori aadressi")

    def test_05_veebikihis_pole_voorast_aadressi(self):
        for nimi, s in (("index.html", HTML),
                        ("calendar_module.js", KALENDER)):
            self.assertEqual([], voorad_ipd(s),
                             f"{nimi} sisaldab võõrast IP-aadressi")
            self.assertNotIn(EMULAATORI_AADRESS, s,
                             f"{nimi} sisaldab emulaatori aadressi")

    def test_05b_ehitusseadistuses_pole_voorast_aadressi(self):
        for nimi, s in (("build.gradle", GRADLE),
                        ("gradle.properties", PROPS),
                        ("AndroidManifest.xml", MANIFEST)):
            self.assertEqual([], voorad_ipd(s),
                             f"{nimi} sisaldab võõrast IP-aadressi")

    def test_06_maya_cfg_vaikevaartused_on_tuhjad(self):
        """index.html MAYA_CFG ei tohi ühtegi aadressi ette anda."""
        blokk = HTML[HTML.index("const MAYA_CFG"):]
        blokk = blokk[:blokk.index("window.MAYA_CFG")]
        self.assertNotRegex(
            blokk, r'base:\s*"https?://',
            "MAYA_CFG annab base-aadressile vaikeväärtuse")
        self.assertIn('base: ""', blokk,
                      "MAYA_CFG vaikeväärtus peab olema tühi string")

    def test_07_kalendrimoodulil_pole_varuaadressi(self):
        """calendar_module.js varuvariant peab olema tühi, mitte aadress."""
        blokk = KALENDER[:KALENDER.index("const now")]
        self.assertNotRegex(blokk, r"return\s*'https?://",
                            "kalendrimoodul annab vaikeaadressi")
        self.assertIn("return '';", blokk)


# =====================================================================
# 2. KASUTAJA SEADISTAB JA AADRESS PÜSIB
# =====================================================================

class TestSeadistamineJaPusivus(unittest.TestCase):

    def test_10_serverconfig_salvestab_sharedpreferences_i(self):
        self.assertIn('const val PREFS = "maya_server"', SERVER_CONFIG)
        self.assertIn('const val KEY_BASE_URL = "base_url"', SERVER_CONFIG)
        self.assertIn("getSharedPreferences(PREFS", SERVER_CONFIG)
        self.assertIn("putString(KEY_BASE_URL", SERVER_CONFIG,
                      "aadressi ei salvestata püsivalt")

    def test_11_salvestamine_kaib_labi_kontrolli(self):
        """`salvesta` ei tohi kontrollimata väärtust kirja panna."""
        algus = SERVER_CONFIG.index("fun salvesta(")
        kere = SERVER_CONFIG[algus:algus + 500]
        j_norm = kere.index("normaliseeri(")
        j_put = kere.index("putString(")
        self.assertLess(j_norm, j_put,
                        "salvesta() kirjutab enne kontrollimist")
        self.assertIn("if (!t.ok) return t", kere,
                      "vigane aadress salvestatakse ikkagi")

    def test_12_seadistusekraan_on_olemas_ja_eestikeelne(self):
        self.assertIn("class ServerSetupActivity", SETUP)
        self.assertIn("Serveri seadistus", SETUP)
        self.assertIn("Testi ühendust", SETUP)
        self.assertIn("Salvesta ja jätka", SETUP)
        self.assertIn("Serveri aadress", SETUP)

    def test_13_seadistusekraan_on_manifestis_ja_pole_eksporditud(self):
        plokk = MANIFEST[MANIFEST.index('android:name=".ServerSetupActivity"'):]
        plokk = plokk[:plokk.index("/>") + 2]
        self.assertIn('android:exported="false"', plokk,
                      "seadistusekraani tohib käivitada ainult MAYA ise")

    def test_14_uhenduse_test_kasutab_avalikku_otspunkti(self):
        """Test päring läheb ainult kasutaja antud aadressile."""
        self.assertIn('URL("$base/api/auth/status")', SETUP)
        # Ühtegi muud absoluutset URL-i seal olla ei tohi.
        for m in re.finditer(r'URL\("([^"]+)"\)', SETUP):
            self.assertTrue(m.group(1).startswith("$base"),
                            f"seadistusekraan pöördub aadressi poole: "
                            f"{m.group(1)}")
        self.assertNotRegex(SETUP, r'https?://[a-z0-9.\-]+\.[a-z]{2,}/',
                            "seadistusekraanis on absoluutne väline URL")

    def test_15_ebaonnestunud_uhendust_ei_nimetata_onnestunuks(self):
        """Ekraan ei tohi väita, et ühendus õnnestus, kui ei õnnestunud."""
        self.assertIn("kontrollitudUrl", SETUP)
        # Õnnestumise märge tehakse AINULT siis, kui katse õnnestus.
        plokk = SETUP[SETUP.index("if (tulemus.onnestus)"):]
        plokk = plokk[:plokk.index("private data class Katse")]
        self.assertIn("kontrollitudUrl = t.url", plokk)
        # Ja kukkumise harus see tühjendatakse.
        self.assertIn('kontrollitudUrl = ""', plokk)
        # Salvestamisel hoiatatakse, kui tõendust pole.
        self.assertIn("Ühendust ei ole kontrollitud", SETUP)

    def test_16_serveri_vahetus_kustutab_vana_tokeni(self):
        """Token kuulub ühele paigaldusele – vahetusel tuleb see ära."""
        plokk = SETUP[SETUP.index("private fun kirjuta("):]
        self.assertIn("remove(MainActivity.MAYA_TOKEN_KEY)", plokk)

    def test_17_aadressi_saab_hiljem_muuta(self):
        self.assertIn("fun openServerSettings()", MAIN)
        self.assertIn("btnServerSettings", HTML)
        self.assertIn("openServerSettings", HTML)
        self.assertIn("mayaServerBtn", HTML,
                      "sisselogimisekraanilt peab saama serverit muuta")


# =====================================================================
# 3. KÕIK SIHTKOHAD TULEVAD SAMAST BAASIST
# =====================================================================

class TestSihtkohad(unittest.TestCase):

    def test_20_veebijson_annab_koik_aadressid(self):
        plokk = SERVER_CONFIG[SERVER_CONFIG.index("fun veebiJson("):]
        for v in ("base", "ws", "sse", "alt", "vision", "seadistatud"):
            self.assertIn(f'o.put("{v}"', plokk, f"veebiJson ei anna {v}")
        # Tühja baasi puhul peavad kõik tuletatud aadressid tühjaks jääma.
        self.assertIn("if (base.isEmpty()) \"\"", plokk)

    def test_21_ws_aadress_tuletatakse_baasist(self):
        self.assertIn("fun wsAadress(", SERVER_CONFIG)
        self.assertIn('"wss://"', SERVER_CONFIG)
        self.assertIn('"ws://"', SERVER_CONFIG)

    def test_22_html_kasutab_tuletatud_ws_aadressi(self):
        self.assertIn("MAYA_CFG.ws", HTML)
        self.assertIn("${wsBase}/ws/live_maya", HTML)
        # Vana käsitsi kokkupanek peab kadunud olema.
        self.assertNotIn("const wsProto", HTML)
        self.assertNotIn("const wsHost", HTML)

    def test_23_sse_kasutab_seadistatud_baasi(self):
        self.assertIn("ServerConfig.baasUrl(this@CallWatcherService)",
                      WATCHER)
        self.assertIn("ServerConfig.sseAadress(base)", WATCHER)

    def test_24_http_api_kasutab_seadistatud_baasi(self):
        """Ükski index.html fetch ei tohi absoluutset võõrast hosti kasutada."""
        self.assertIn("const SERVER_URL = MAYA_CFG.base;", HTML)
        for m in re.finditer(r"fetch\(\s*[\"'`](https?://[^\"'`$]+)", HTML):
            url = m.group(1)
            self.assertTrue(
                any(x in url for x in ("googleapis.com", "google.com")),
                f"index.html pöördub kõvakodeeritud aadressi poole: {url}")

    def test_25_ws_aadress_ja_api_ei_saa_lahku_minna(self):
        """`ws` tuleb samast stringist, mis `base` – mitte eraldi väljast."""
        plokk = SERVER_CONFIG[SERVER_CONFIG.index("fun veebiJson("):]
        self.assertIn("wsAadress(base)", plokk)
        self.assertIn("sseAadress(base)", plokk)

    def test_26_tuhja_baasi_vastu_ei_votata_uhendust(self):
        # MainActivity: ilma seadistuseta WebView'd ei laadita.
        self.assertIn("if (!ServerConfig.onSeadistatud(this))", MAIN)
        plokk = MAIN[MAIN.index("private fun kaivitaRakendus()"):]
        plokk = plokk[:plokk.index("private fun avaServeriSeadistus()")]
        self.assertLess(plokk.index("avaServeriSeadistus()"),
                        plokk.index("loadApp()"),
                        "WebView laetakse enne seadistuse kontrolli")
        # CallWatcherService: ilma aadressita ei pollita.
        self.assertIn("Serveri aadress puudub", WATCHER)

    def test_27_fetchi_umbris_ei_lekita_tokenit_tuhja_baasiga(self):
        """`"".indexOf("") === 0` on tõene – tühja prefiksi vastu ei võrrelda."""
        plokk = HTML[HTML.index("var algne = window.fetch.bind(window);"):]
        plokk = plokk[:plokk.index("const WATCHER_URL")]
        self.assertIn("filter(function (p)", plokk,
                      "tühje aadresse ei filtreerita välja")
        self.assertNotIn("url.indexOf(MAYA_CFG.base) === 0", plokk,
                         "tühja baasi vastu võrdlemine lekitaks tokeni")


# =====================================================================
# 4. GEMINI VÕTI JÄÄB BACKENDI
# =====================================================================

class TestVotmedJaavadBackendi(unittest.TestCase):

    def test_30_androidi_lahtekoodis_pole_votmeid(self):
        failid = [(f.name, f.read_text(encoding="utf-8"))
                  for f in KOTLIN_FAILID]
        failid += [("index.html", HTML), ("calendar_module.js", KALENDER),
                   ("build.gradle", GRADLE),
                   ("gradle.properties", PROPS)]
        for nimi, s in failid:
            for muster in VOTME_MUSTRID:
                self.assertIsNone(muster.search(s),
                                  f"{nimi} sisaldab võtmemustrit")

    def test_31_androidi_kood_ei_kasuta_geminit_otse(self):
        """Gemini kutsutakse AINULT backendist – klient ei tohi otse minna."""
        keelatud = ["generativelanguage.googleapis.com",
                    "GEMINI_API_KEY", "gemini-2.5", "genai."]
        for f in KOTLIN_FAILID:
            s = f.read_text(encoding="utf-8")
            for k in keelatud:
                self.assertNotIn(k, s,
                                 f"{f.name} viitab Gemini API-le otse: {k}")

    def test_32_votme_seadistus_on_ainult_serveri_keskkonnas(self):
        """Operaator seab oma võtme `.env`-i; see ei lähe APK-sse."""
        env_naide = (JUUR / ".env.example").read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY", env_naide)
        # .env ise ei tohi versioonihalduses olla.
        gi = (JUUR / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(any(r.strip() in (".env", "/.env", ".env*")
                            for r in gi.splitlines()),
                        ".gitignore ei välista .env faili")


# =====================================================================
# 5. VAREM TÖÖTANUD MEHHANISMID ON ALLES
# =====================================================================

class TestOlemasolevFunktsionaalsus(unittest.TestCase):

    def test_40_autentimine_on_kliendis_alles(self):
        self.assertIn("MayaAuth", HTML)
        self.assertIn("/api/auth/login", HTML)
        self.assertIn("Authorization", HTML)
        self.assertIn('setRequestProperty("Authorization", "Bearer $token")',
                      WATCHER)

    def test_41_uhekordne_ws_pilet_on_alles(self):
        self.assertIn("/api/auth/ws_ticket", HTML)
        self.assertIn("ticket=", HTML)
        self.assertIn("MayaAuth.wsUrl(", HTML)

    def test_42_koneteade_ja_valvur_on_alles(self):
        self.assertIn("/api/call_events", WATCHER)
        self.assertIn("FOREGROUND_SERVICE_TYPE_MICROPHONE", WATCHER)
        self.assertIn("setFullScreenIntent", WATCHER)
        self.assertIn('android:foregroundServiceType="microphone"', MANIFEST)

    def test_43_mitme_seadme_fan_out_on_serveris_alles(self):
        web = (JUUR / "server/web_maya.py").read_text(encoding="utf-8")
        for f in ("def kone_telli(", "def kone_lopeta(",
                  "async def kone_publitseeri(", "def kone_tellijaid("):
            self.assertIn(f, web, f"mitme seadme tugi puudub: {f}")

    def test_44_gemini_live_seadistus_on_puutumata(self):
        ws = (JUUR / "server/live_maya_ws.py").read_text(encoding="utf-8")
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", ws)
        self.assertIn("response_modalities", ws)

    def test_45_kaamera_ja_karakterid_on_alles(self):
        self.assertIn("captureCameraSnapshotBase64", MAIN)
        self.assertIn('data-persona="custom"', HTML)


# =====================================================================
# 6. EHITATUD APK SISU
# =====================================================================

class TestApkSisu(unittest.TestCase):
    """Kontrollime APK BAITE, mitte lähtekoodi.

    Kui universaalset APK-d ei ole ehitatud, jäetakse testid vahele.
    Vahelejätmine EI OLE õnnestumine – CI ehitab APK enne nende jooksu.
    """

    @classmethod
    def setUpClass(cls):
        if not UNIVERSAL_APK.exists():
            raise unittest.SkipTest(
                f"{UNIVERSAL_APK.name} puudub – ehita: ./gradlew "
                f"assembleDebug ja kopeeri valjalase/ kausta")
        cls.z = zipfile.ZipFile(UNIVERSAL_APK)
        # Loeme kõik DEX-id, varad ja ressursid ühte baidipuhvrisse.
        osad = []
        for n in cls.z.namelist():
            if (n.endswith(".dex") or n.startswith("assets/")
                    or n.startswith("res/") or n == "resources.arsc"
                    or n == "AndroidManifest.xml"):
                osad.append(cls.z.read(n))
        cls.baidid = b"".join(osad)
        cls.tekst = cls.baidid.decode("utf-8", errors="ignore")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.z.close()
        except Exception:
            pass

    def test_50_apk_ei_sisalda_voorast_aadressi(self):
        """APK baitides tohib olla AINULT reserveeritud näiteaadress.

        See on rangem kui konkreetsete aadresside nimekiri: läbi ei lähe
        ÜKSKI võõras IP, olgu ta kelle oma tahes.
        """
        self.assertEqual([], voorad_ipd(self.tekst),
                         "APK sisaldab võõrast IP-aadressi")
        self.assertNotIn(EMULAATORI_AADRESS.encode(), self.baidid,
                         "APK sisaldab emulaatori aadressi")

    def test_51_apk_ei_sisalda_votmeid(self):
        for muster in VOTME_MUSTRID:
            leid = muster.search(self.tekst)
            self.assertIsNone(leid, "APK sisaldab võtmemustrit")

    def test_52_apk_ei_sisalda_isiklikke_viiteid(self):
        """Kontrollib omaniku kohalikku mustrinimekirja, kui see on olemas.

        Mustreid EI hoita selles failis – vt `privaatsed_mustrid()`.
        """
        mustrid = privaatsed_mustrid()
        if not mustrid:
            raise unittest.SkipTest(
                "tests/privaatsed_mustrid.txt puudub – isiklike viidete "
                "kontroll jäeti VAHELE (see ei ole õnnestumine)")
        leitud = [m for m in mustrid if m.encode() in self.baidid]
        self.assertEqual([], leitud,
                         f"APK sisaldab {len(leitud)} isiklikku viidet")

    def test_53_apk_sisaldab_seadistusekraani(self):
        self.assertIn(b"ServerSetupActivity", self.baidid)
        self.assertIn("Serveri seadistus".encode(), self.baidid)
        self.assertIn(b"maya_server", self.baidid,
                      "SharedPreferences nimi puudub – salvestus ei tööta")
        self.assertIn(b"base_url", self.baidid)

    def test_54_apk_sisaldab_tuhja_vaikeaadressi(self):
        """DEX-is ei tohi olla ühtegi http(s) backendi aadressi."""
        # Lubatud on näiteaadressid (seadistusekraani selgitus) ja
        # Google/YouTube URL-id, mida rakendus päriselt kasutab.
        lubatud_hostid = ("youtube.com", "google.com", "googleapis.com",
                          "schemas.android.com", "android.com", "w3.org",
                          "example.com", "192.168.1.50", "100.64.0.5",
                          "github.com", "localhost", "127.0.0.1",
                          "developer.android.com", "kotlinlang.org",
                          "googlesource.com", "apache.org", "mozilla.org",
                          "jetbrains.com", "oracle.com", "unicode.org",
                          "ietf.org", "json.org", "sqlite.org")
        leitud = set(re.findall(r"https?://[A-Za-z0-9._:\-]{4,60}",
                                self.tekst))
        kahtlased = [u for u in leitud
                     if not any(h in u for h in lubatud_hostid)]
        self.assertEqual([], sorted(kahtlased),
                         f"APK sisaldab tundmatuid aadresse: {kahtlased}")

    def test_55_apk_sisaldab_autentimist_ja_piletit(self):
        self.assertIn(b"/api/auth/ws_ticket", self.baidid)
        self.assertIn(b"/api/call_events", self.baidid)
        self.assertIn(b"Bearer ", self.baidid)

    def test_56_apk_varad_on_kaasas(self):
        nimed = self.z.namelist()
        self.assertIn("assets/index.html", nimed)
        self.assertIn("assets/calendar_module.js", nimed)

    def test_57_apk_ei_sisalda_andmebaasi(self):
        for n in self.z.namelist():
            self.assertFalse(n.endswith(".db") or n.endswith(".sqlite"),
                             f"APK sisaldab andmebaasi: {n}")


# =====================================================================
# 7. KOTLINI TESTID ON OLEMAS JA JOOKSUTATAVAD
# =====================================================================

class TestKotlinTestid(unittest.TestCase):

    def test_60_kotlin_testifail_on_olemas(self):
        t = ANDROID / "app/src/test/java/com/maya/live/ServerConfigTest.kt"
        self.assertTrue(t.exists(), "ServerConfig puhta loogika testid "
                                    "puuduvad")
        s = t.read_text(encoding="utf-8")
        self.assertIn("MAYA_DEFAULT_BASE_URL", s)
        self.assertIn("wsAadress", s)
        self.assertIn("aadressiMuutmineMuudabKoikiSihtkohti", s)

    def test_61_testisoltuvus_ei_satu_apk_sse(self):
        """JUnit peab olema `testImplementation`, mitte `implementation`."""
        self.assertIn("testImplementation 'junit:junit", GRADLE)
        self.assertNotIn("implementation 'junit:junit", GRADLE.replace(
            "testImplementation 'junit:junit", ""))

    def test_62_kotlin_testid_laksid_labi(self):
        """Loeme viimase `./gradlew testDebugUnitTest` tulemuse."""
        kaust = ANDROID / "app/build/test-results/testDebugUnitTest"
        if not kaust.exists():
            raise unittest.SkipTest(
                "Kotlini testitulemused puuduvad – jooksuta "
                "`cd android && ./gradlew testDebugUnitTest`")
        import xml.etree.ElementTree as ET
        kokku = vigu = 0
        for p in kaust.glob("*.xml"):
            r = ET.parse(p).getroot()
            kokku += int(r.get("tests") or 0)
            vigu += int(r.get("failures") or 0) + int(r.get("errors") or 0)
        self.assertGreater(kokku, 0, "ükski Kotlini test ei jooksnud")
        self.assertEqual(0, vigu, f"{vigu} Kotlini testi kukkus läbi")


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — paigalduskogemuse ja dokumentatsiooni testid.

MIDA NEED TESTID TÕESTAVAD
--------------------------
1. Paigaldusskriptid on olemas, käivitatavad ja süntaktiliselt korras.
2. Skriptid ei tee ohtlikke asju: ei ava tulemüüri, ei muuda ruuterit,
   ei trüki API võtit, ei kirjuta olemasolevat paigaldust üle ilma
   küsimata, ei juuruta midagi kaugserverisse.
3. Dokumentatsioonis mainitud keskkonnamuutujad on PÄRISELT koodis
   olemas (ei ole välja mõeldud).
4. Dokumentatsioonis mainitud käsud ja failiteed on päriselt olemas.
5. KÕIK sisemised dokumendilingid viitavad olemasolevale failile ja
   `.gitignore`-i failidele ei viidata (kloonijal neid ei ole).
6. README-s on keelevalik, „alusta siit" ja kolm paigaldusteed.
7. Kulude kohta ei ole ühtegi väljamõeldud hinnanumbrit.
8. Avaliku väljalaske kohta ei ole valeväiteid.
9. `MAYA_HOST` ja `MAYA_PORT` mõjuvad päriselt (varem olid
   kõvakodeeritud).

MIDA NEED EI TÕESTA
-------------------
Need testid ei jooksuta paigaldust päris puhtas masinas ega kontrolli
Androidi rakendust päris telefonis.
"""

import os
import pathlib
import re
import subprocess
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent
DOCS = JUUR / "docs"

SKRIPTID = ["paigalda.sh", "kaivita.sh", "tervisekontroll.sh",
            "peata.sh", "uuenda.sh"]

UUED_DOKUMENDID = [
    "docs/PAIGALDAMINE.md",
    "docs/PAIGALDAMINE_EN.md",
    "docs/AI_ABIGA_PAIGALDAMINE.md",
    "docs/AI_ASSISTED_INSTALLATION.md",
    "docs/README.md",
    "README_EN.md",
]


def loe(tee: str) -> str:
    return (JUUR / tee).read_text(encoding="utf-8")


# =====================================================================
# 1. SKRIPTID
# =====================================================================

class TestSkriptid(unittest.TestCase):

    def test_01_skriptid_on_olemas_ja_kaivitatavad(self):
        for s in SKRIPTID:
            p = JUUR / s
            self.assertTrue(p.exists(), f"{s} puudub")
            self.assertTrue(os.access(p, os.X_OK),
                            f"{s} ei ole käivitatav (chmod +x)")

    def test_02_skriptide_suntaks_on_korras(self):
        """`bash -n` leiab süntaksivead ka ridadel, kuhu test ei jõua."""
        for s in SKRIPTID:
            r = subprocess.run(["bash", "-n", str(JUUR / s)],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(0, r.returncode,
                             f"{s} süntaksiviga: {r.stderr.strip()}")

    def test_03_eesti_jutumargid_ei_lohu_stringe(self):
        """„...\" muster lõpetaks bashi stringi enneaegselt.

        See oli päris viga: `kaivita.sh` ei käivitunud, sest reas oli
        „Loo uus konto\" – avav eesti jutumärk ja SULGEV ASCII jutumärk.
        """
        for s in SKRIPTID:
            for nr, rida in enumerate(loe(s).splitlines(), 1):
                if "„" not in rida:
                    continue
                # Kommentaaririda ei saa bashi süntaksit lõhkuda.
                if rida.lstrip().startswith("#"):
                    continue
                # Loe varjestamata ASCII jutumärgid. Korrektses reas on
                # neid PAARISARV (string avatakse ja suletakse). Paaritu
                # arv tähendab, et mõni „...\" sulges stringi vara.
                puhas = rida.replace('\\"', "")
                self.assertEqual(
                    0, puhas.count('"') % 2,
                    f"{s}:{nr} paaritu arv jutumärke – eesti jutumärkide "
                    f"sees on varjestamata ASCII jutumärk: {rida.strip()[:70]}")

    def test_04_skriptid_ei_ava_tulemuuri_ega_ruuterit(self):
        """Paigaldus EI TOHI süsteemi võrguseadistust muuta."""
        keelatud = ["ufw allow", "ufw enable", "firewall-cmd --add",
                    "iptables -A", "iptables -I", "pfctl -e",
                    "upnpc", "natpmp", "systemctl enable"]
        for s in SKRIPTID:
            sisu = loe(s)
            for k in keelatud:
                self.assertNotIn(k, sisu,
                                 f"{s} muudab süsteemi seadistust: {k}")

    def test_05_skriptid_ei_juuruta_kaugserverisse(self):
        keelatud = ["scp ", "rsync ", "ssh ", "git push", "docker push",
                    "kubectl", "ansible"]
        for s in SKRIPTID:
            sisu = loe(s)
            for k in keelatud:
                self.assertNotIn(k, sisu,
                                 f"{s} võtab ühendust kaugmasinaga: {k}")

    def test_06_paigaldaja_ei_truki_votit(self):
        """Võtit loetakse varjatult ja seda ei kajastata ekraanil."""
        s = loe("paigalda.sh")
        self.assertIn("read -rs VOTI", s,
                      "võtit ei loeta varjatult (read -s)")
        # Võtme muutujat ei tohi kuskil välja trükkida.
        # Võti ei tohi jõuda ei ekraanile ega välisesse käsku.
        for muster in [r'echo\s+"?\$VOTI', r'printf[^\n]*\$VOTI',
                       r'info\s+"\$VOTI', r'\$VOTI"?\s*\|']:
            self.assertIsNone(re.search(muster, s),
                              f"paigalda.sh trükib võtme: {muster}")

    def test_07_paigaldaja_seab_env_oigused(self):
        s = loe("paigalda.sh")
        self.assertIn("chmod 600 .env", s,
                      ".env õigusi ei piirata")

    def test_08_paigaldaja_ei_kirjuta_olemasolevat_ule(self):
        s = loe("paigalda.sh")
        self.assertIn("Kontrollin, kas paigaldus on juba olemas", s)
        self.assertIn("EI KIRJUTA neid üle", s)
        # .env kopeeritakse ainult siis, kui seda EI OLE.
        self.assertIn('if [ ! -f .env ]; then', s,
                      ".env kopeeritakse tingimusteta – kirjutaks üle")

    def test_09_tervisekontroll_ei_truki_votit(self):
        s = loe("tervisekontroll.sh")
        self.assertIn("${#VOTI}", s, "võtme pikkust ei näidata")
        self.assertIsNone(re.search(r'echo\s+"?\$VOTI', s),
                          "tervisekontroll trükib võtme")

    def test_10_tervisekontroll_annab_vealjumiskoodi(self):
        """Peab sobima automaatikaks: 0 = korras, 1 = probleem."""
        s = loe("tervisekontroll.sh")
        self.assertIn("exit $([ \"$VIGU\" = \"0\" ] && echo 0 || echo 1)", s)

    def test_11_peata_sh_ei_tapa_voorast_protsessi(self):
        """Peatada tohib AINULT selle projektikausta serverit."""
        s = loe("peata.sh")
        self.assertIn(".maya.pid", s, "PID-faili ei kasutata")
        self.assertIn("protsessi_kaust", s,
                      "töökataloogi ei kontrollita – võiks tappa võõra")
        self.assertIn('"$JUUR"|"$JUUR"/*', s,
                      "töökataloogi võrdlust projektikaustaga ei ole")
        self.assertNotIn("pkill", s, "pkill on liiga lai")
        self.assertNotIn("killall", s, "killall on liiga lai")

    def test_12_kaivita_kirjutab_pid_faili(self):
        s = loe("kaivita.sh")
        self.assertIn('echo $$ > "$JUUR/.maya.pid"', s)
        # PID-fail ei tohi Giti jõuda.
        self.assertIn(".maya.pid", loe(".gitignore"))

    def test_13_uuendaja_kaitseb_kasutaja_andmeid(self):
        s = loe("uuenda.sh")
        self.assertIn("git status --porcelain", s,
                      "ei kontrolli salvestamata muudatusi")
        self.assertIn("ei kustuta ega kirjuta üle sinu .env", s)
        for k in ["rm -rf .env", "rm .env", "rm -rf data", "--force"]:
            self.assertNotIn(k, s, f"uuenda.sh teeb ohtlikku: {k}")

    def test_14_kaivita_ei_sunni_host_vaartust(self):
        """Varem sundis `export MAYA_HOST=0.0.0.0` 127.0.0.1 valiku üle."""
        s = loe("kaivita.sh")
        self.assertNotIn('export MAYA_HOST="${MAYA_HOST:-0.0.0.0}"', s,
                         "kaivita.sh tühistab kasutaja MAYA_HOST valiku")


# =====================================================================
# 2. KUULAMISAADRESS MÕJUB PÄRISELT
# =====================================================================

class TestHostJaPort(unittest.TestCase):
    """PARANDUS: `uvicorn.run(host="0.0.0.0", port=8000)` oli
    kõvakodeeritud, mistõttu MAYA_HOST ja MAYA_PORT EI MÕJUNUD. See oli
    turvaprobleem – dokumentatsioon soovitas 127.0.0.1, aga server
    kuulas kõigil liidestel."""

    def setUp(self):
        self.s = loe("server/web_maya.py")

    def test_20_uvicorn_loeb_seadistusest(self):
        self.assertIn("uvicorn.run(app, host=config.HOST, port=config.PORT)",
                      self.s)

    def test_21_kovakodeeritud_aadressi_ei_ole(self):
        self.assertNotIn('uvicorn.run(app, host="0.0.0.0", port=8000)',
                         self.s)

    def test_22_config_pakub_host_ja_port(self):
        c = loe("server/config.py")
        self.assertIn('HOST = env("MAYA_HOST"', c)
        self.assertIn('PORT = int(env("MAYA_PORT"', c)

    def test_23_server_utleb_kuulamisaadressi_valja(self):
        self.assertIn("kuulan aadressil", self.s)


# =====================================================================
# 3. DOKUMENTATSIOON VIITAB PÄRIS ASJADELE
# =====================================================================

class TestDokumentatsioonOnTosi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.md = {}
        for p in list(JUUR.glob("*.md")) + list(DOCS.glob("*.md")):
            cls.md[str(p.relative_to(JUUR))] = p.read_text(encoding="utf-8")
        # Kõik muutujad, mida kood PÄRISELT loeb.
        cls.paris_muutujad = set()
        for f in (JUUR / "server").glob("*.py"):
            for m in re.finditer(
                    r'(?:os\.environ\.get|os\.getenv|env)\(\s*"([A-Z_][A-Z0-9_]*)"',
                    f.read_text(encoding="utf-8")):
                cls.paris_muutujad.add(m.group(1))

    def test_30_uued_dokumendid_on_olemas(self):
        for d in UUED_DOKUMENDID:
            self.assertTrue((JUUR / d).exists(), f"{d} puudub")

    def test_31_mainitud_keskkonnamuutujad_on_paris(self):
        """Dokumentatsioon ei tohi muutujaid välja mõelda."""
        # MAYA_CFG on index.html-i JS-objekt, mitte keskkonnamuutuja.
        lubatud_lisad = {"MAYA_ENV_FILE", "TOKEN", "MAYA_CFG"}
        for nimi, sisu in self.md.items():
            for m in set(re.findall(r"\bMAYA_[A-Z0-9_]+\b", sisu)):
                if m in lubatud_lisad:
                    continue
                self.assertIn(m, self.paris_muutujad | lubatud_lisad,
                              f"{nimi} mainib muutujat {m}, mida kood ei loe")

    def test_32_mainitud_skriptid_on_olemas(self):
        for nimi, sisu in self.md.items():
            for m in set(re.findall(r"\./([a-z_]+\.sh)", sisu)):
                self.assertTrue((JUUR / m).exists(),
                                f"{nimi} viitab skriptile ./{m}, mida ei ole")

    def test_33_mainitud_pythoni_failid_on_olemas(self):
        for nimi, sisu in self.md.items():
            for m in set(re.findall(r"server/([a-z_]+\.py)", sisu)):
                self.assertTrue((JUUR / "server" / m).exists(),
                                f"{nimi} viitab failile server/{m}, mida ei ole")

    def test_34_koik_sisemised_lingid_toimivad(self):
        """Iga [tekst](tee) peab viitama olemasolevale failile."""
        katki = []
        for nimi, sisu in self.md.items():
            baas = (JUUR / nimi).parent
            for m in re.finditer(r"\[[^\]]+\]\(([^)#\s]+)(#[^)]*)?\)", sisu):
                siht = m.group(1)
                if siht.startswith(("http://", "https://", "mailto:")):
                    continue
                p = (baas / siht).resolve()
                if not p.exists():
                    katki.append(f"{nimi} -> {siht}")
        self.assertEqual([], katki, f"katkised lingid: {katki}")

    def test_34b_sisemised_ankrud_viitavad_olemasolevale_pealkirjale(self):
        """`](#midagi)` peab viitama päris pealkirjale samas failis.

        GitHub teeb ankru nii: väiketähed, mitte-sõnamärgid maha,
        tühikud sidekriipsudeks. Emoji pealkirja ALGUSES jätab juhtiva
        sidekriipsu ja muudab ankru mitmetähenduslikuks – seepärast ei
        ole viidatud pealkirjades emojit.
        """
        def slug(rida: str) -> str:
            # GitHubi reegel: väiketähed -> maha kõik, mis ei ole
            # sõnamärk/tühik/sidekriips -> IGA tühik eraldi sidekriipsuks.
            # Tühikuid EI tohi kokku suruda: „Variant 1 — Kodune võrk"
            # annab emdashi eemaldamisel kaks tühikut ja seega KAKS
            # sidekriipsu (`variant-1--kodune-võrk`).
            t = rida.lstrip("#").strip().lower()
            t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
            return re.sub(r"\s", "-", t)

        katki = []
        for nimi, sisu in self.md.items():
            pealkirjad = {slug(r) for r in sisu.splitlines()
                          if r.startswith("#")}
            for m in re.finditer(r"\]\(#([^)]+)\)", sisu):
                if m.group(1) not in pealkirjad:
                    katki.append(f"{nimi} -> #{m.group(1)}")
        self.assertEqual([], katki, f"katkised ankrud: {katki}")

    def test_35_ei_viidata_gitignore_failidele(self):
        """Kloonijal ei ole `valjalase/` kausta – link oleks katki."""
        for nimi, sisu in self.md.items():
            if nimi.startswith("valjalase/"):
                continue
            for m in re.finditer(r"\[[^\]]+\]\(([^)#\s]+)", sisu):
                siht = m.group(1)
                if siht.startswith(("http", "mailto")):
                    continue
                r = subprocess.run(
                    ["git", "-C", str(JUUR), "check-ignore", "-q",
                     str((JUUR / nimi).parent / siht)],
                    capture_output=True)
                self.assertNotEqual(
                    0, r.returncode,
                    f"{nimi} viitab .gitignore'i failile: {siht}")

    def test_36_dokumenteeritud_pordid_on_paris(self):
        """Ainult port 8000 on MAYA oma; 8001/8002 teenuseid ei ole."""
        # Eemalda markdowni tsitaadimärgid (>), muidu jäävad need
        # lause keskele ja rikuvad võrdluse.
        toores = self.md["docs/PAIGALDAMINE.md"]
        ilma = "\n".join(r.lstrip("> ") for r in toores.splitlines())
        p = re.sub(r"\s+", " ", ilma)
        self.assertIn("**8000**", p)
        self.assertIn("Avalikus MAYA-s neid teenuseid ei ole", p,
                      "ei öelda välja, et 8001/8002 teenuseid ei ole")
        # Ja ei tohi nõuda nende avamist.
        self.assertNotIn("ava port 8001", p.lower())

    def test_37_otspunktid_on_paris(self):
        """Dokumentatsioonis mainitud API teed peavad koodis olemas olema."""
        web = loe("server/web_maya.py")
        ws = loe("server/live_maya_ws.py")
        kogu = web + ws
        for tee in ["/api/auth/status", "/api/auth/register",
                    "/api/auth/login", "/api/auth/me",
                    "/api/auth/ws_ticket", "/api/call_events",
                    "/ws/live_maya"]:
            self.assertIn(tee, kogu,
                          f"dokumentatsioon mainib otspunkti {tee}, "
                          f"mida koodis ei ole")

    def test_38_andmebaasi_tee_on_dokumenteeritud_oigesti(self):
        """Andmebaas tekib server/data/, mitte data/."""
        for d in ("docs/PAIGALDAMINE.md", "docs/PAIGALDAMINE_EN.md"):
            self.assertIn("server/data/reminders.db", self.md[d],
                          f"{d} ei näita andmebaasi õiget asukohta")


# =====================================================================
# 4. AUSUS: EI OLE VÄLJAMÕELDUD HINDU EGA VALEVÄITEID
# =====================================================================

class TestAusus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.md = {}
        for p in list(JUUR.glob("*.md")) + list(DOCS.glob("*.md")):
            cls.md[str(p.relative_to(JUUR))] = p.read_text(encoding="utf-8")

    def test_40_gemini_hindu_ei_ole_valja_moeldud(self):
        """Hinnad määrab Google – ükski number ei tohi siin olla."""
        hinnamustrid = [
            r"\$\s?\d+[.,]\d+",                      # $0.50
            r"\d+[.,]\d+\s?(?:USD|EUR|€)",           # 0.50 USD
            r"\d+\s?(?:senti|cents?)\s*/\s*min",     # 5 senti/min
        ]
        for nimi, sisu in self.md.items():
            for m in hinnamustrid:
                leid = re.search(m, sisu)
                self.assertIsNone(
                    leid, f"{nimi} sisaldab hinnanumbrit "
                          f"({leid.group() if leid else ''}) – hinnad "
                          f"määrab Google ja need vananevad")

    def test_41_oeldakse_valja_et_arve_laheb_kasutajale(self):
        for d in ("README.md", "README_EN.md", "docs/PAIGALDAMINE.md",
                  "docs/PAIGALDAMINE_EN.md"):
            s = re.sub(r"\s+", " ", self.md[d])
            self.assertRegex(
                s, r"(läheb SINULE|bill goes to you|arveldab selle SINULE|"
                   r"billed by Google to that user|Google arveldab)",
                f"{d} ei ütle, et Gemini arve läheb kasutajale")

    def test_42_ei_vaideta_et_avalik_valjalase_on_olemas(self):
        """APK-d hoidlas ei ole – ei tohi lubada allalaadimislinki."""
        for nimi, sisu in self.md.items():
            if nimi.startswith("valjalase/"):
                continue
            for rida in sisu.splitlines():
                if re.search(r"\.apk\b", rida, re.I):
                    self.assertFalse(
                        re.search(r"\]\(https?://[^)]*\.apk", rida, re.I),
                        f"{nimi}: väljamõeldud APK allalaadimislink: "
                        f"{rida.strip()[:80]}")

    def test_43_oeldakse_valja_et_paris_seadmes_on_testimata(self):
        for d in ("README.md", "README_EN.md", "docs/PAIGALDAMINE.md",
                  "docs/PAIGALDAMINE_EN.md"):
            s = re.sub(r"\s+", " ", self.md[d])
            self.assertRegex(
                s, r"(päris telefonis\W{0,4}(läbi )?testitud|"
                   r"päris telefonis kontrollimata|"
                   r"päris seadmes\W{0,4}(läbi )?(testitud|kontrollitud)|"
                   r"tested on a real phone|"
                   r"physical-device verification)",
                f"{d} ei ütle, et päris seadmes on kontrollimata")

    def test_44_windowsi_tuge_ei_lubata(self):
        for d in ("docs/PAIGALDAMINE.md", "docs/PAIGALDAMINE_EN.md"):
            s = self.md[d]
            self.assertIn("WSL2", s)
            self.assertRegex(s, r"(kontrollimata|unverified)",
                             f"{d} ei ütle, et Windows on kontrollimata")

    def test_45_ei_lubata_keskset_teenust(self):
        for d in ("README.md", "README_EN.md", "docs/PAIGALDAMINE.md",
                  "docs/PAIGALDAMINE_EN.md", "docs/README.md"):
            s = re.sub(r"\s+", " ", self.md[d])
            self.assertRegex(
                s, r"(ei ole teenus|ei jookse|is not a service|"
                   r"no MAYA server runs|Keskset MAYA teenust ei ole|"
                   r"no central MAYA service|ei kasuta ühtegi keskset)",
                f"{d} ei ütle välja, et keskset teenust ei ole")


# =====================================================================
# 5. README JA NAVIGATSIOON
# =====================================================================

class TestReadme(unittest.TestCase):

    def setUp(self):
        self.et = loe("README.md")
        self.en = loe("README_EN.md")

    def test_50_keelevalik_on_alguses(self):
        """Keelevalik peab olema README päises.

        Aken on 30 rida, sest päis on HTML-keskjoondusega plokk
        (pealkiri, loosung, kirjeldus, keelelingid, märgid) — keelevalik
        on seal visuaalselt kohe alguses, aga mitte esimesel 10 real.
        """
        for nimi, sisu, teine in (("README.md", self.et, "README_EN.md"),
                                  ("README_EN.md", self.en, "README.md")):
            algus = "\n".join(sisu.splitlines()[:30])
            self.assertIn(teine, algus,
                          f"{nimi} alguses ei ole linki teisele keelele")

    def test_51_alusta_siit_on_olemas(self):
        self.assertRegex(self.et, r"ALUSTA SIIT")
        self.assertRegex(self.en, r"START HERE")

    def test_52_kolm_paigaldusteed(self):
        for sisu in (self.et, self.en):
            self.assertIn("docs/PAIGALDAMINE", sisu)
            self.assertIn("AI_A", sisu)
            self.assertIn("./paigalda.sh", sisu)

    def test_53_arhitektuuri_ulevaade(self):
        for sisu in (self.et, self.en):
            self.assertIn("web_maya.py", sisu)
            self.assertIn("/ws/live_maya", sisu)
            self.assertIn("/api/call_events", sisu)

    def test_54_litsents_ja_panustamine(self):
        for sisu in (self.et, self.en):
            self.assertIn("Apache License 2.0", sisu)
            self.assertIn("CONTRIBUTING.md", sisu)

    def test_55_dokumentatsiooni_indeks_viitab_koigile(self):
        idx = loe("docs/README.md")
        for p in sorted(DOCS.glob("*.md")):
            if p.name == "README.md":
                continue
            self.assertIn(p.name, idx,
                          f"docs/README.md ei maini faili {p.name}")

    def test_56_ai_viip_sisaldab_turvapiiranguid(self):
        """AI-viip peab AI-d piirama, mitte ainult juhendama."""
        for d in ("docs/AI_ABIGA_PAIGALDAMINE.md",
                  "docs/AI_ASSISTED_INSTALLATION.md"):
            s = loe(d)
            # Viip peab keelama need konkreetsed asjad.
            for nouded in (("API võtit", "API key"),
                           ("tulemüüri", "firewall"),
                           ("kaugserverisse", "remote server"),
                           ("./tervisekontroll.sh", "./tervisekontroll.sh")):
                self.assertTrue(any(n in s for n in nouded),
                                f"{d} viip ei maini: {nouded}")

    def test_57_ai_dokument_selgitab_agentse_ja_vestlusroboti_vahet(self):
        for d in ("docs/AI_ABIGA_PAIGALDAMINE.md",
                  "docs/AI_ASSISTED_INSTALLATION.md"):
            s = loe(d)
            self.assertRegex(s, r"(Agentne|Agentic)")
            self.assertRegex(s, r"(Vestlusrobot|Chatbot)")
            self.assertRegex(
                s, r"(Ükski AI ei pääse|No AI gets into)",
                f"{d} ei ütle, et AI ei pääse ise arvutisse")


if __name__ == "__main__":
    unittest.main(verbosity=2)

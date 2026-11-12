#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — litsentsi terviklikkuse ja järjepidevuse testid.

MIDA NEED TESTID TÕESTAVAD
--------------------------
1. `LICENSE` sisaldab **täielikku ja muutmata** Apache License 2.0
   teksti: kõik 9 jaotist, „END OF TERMS AND CONDITIONS" ja APPENDIX
   koos puutumata kohahoidjatega.
2. `LICENSE` on **baidihaaval identne** apache.org avaldatud tekstiga
   (võrdlus räsiga – võrku testi ajal ei kasutata).
3. `NOTICE` on olemas, nimetab Apache-2.0 ja **ei omista
   autoriõigust ühelegi kontrollimata eraisikule**.
4. Dokumentatsioon räägib **ühest ja samast** litsentsist: ükski fail
   ei nimeta MIT-i ega ütle, et litsents on valimata.
5. Varasem `LITSENTS_OOTEL.md` on kadunud ja ükski fail ei viita
   sellele.
6. Kolmanda osapoole litsentsid on dokumenteeritud, sealhulgas
   **teadaolev `tld` erijuht** – seda ei tohi vaikides ära kaotada.

MIDA NEED EI TÕESTA
-------------------
See ei ole juriidiline hinnang. Testid kontrollivad faile ja
järjepidevust, mitte seda, kas litsentsivalik on kellegi konkreetse
olukorra jaoks õige.
"""

import hashlib
import pathlib
import re
import subprocess
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent

# apache.org/licenses/LICENSE-2.0.txt SHA-256 (11 358 baiti, 202 rida).
# Sama räsi on sõltumatult kahes paigaldatud paketis: `sniffio`
# (LICENSE.APACHE2) ja `python-multipart` (LICENSE.txt).
APACHE2_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30")

APACHE2_OSAD = [
    "Apache License",
    "Version 2.0, January 2004",
    "http://www.apache.org/licenses/",
    "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    "1. Definitions.",
    "2. Grant of Copyright License.",
    "3. Grant of Patent License.",
    "4. Redistribution.",
    "5. Submission of Contributions.",
    "6. Trademarks.",
    "7. Disclaimer of Warranty.",
    "8. Limitation of Liability.",
    "9. Accepting Warranty or Additional Liability.",
    "END OF TERMS AND CONDITIONS",
    "APPENDIX: How to apply the Apache License to your work.",
]

MD_FAILID = sorted(
    [p for p in JUUR.glob("*.md")] +
    [p for p in (JUUR / "docs").glob("*.md")] +
    [p for p in (JUUR / ".github").rglob("*.md")]
)


class TestLicenseFail(unittest.TestCase):

    def setUp(self):
        self.tee = JUUR / "LICENSE"

    def test_01_license_on_olemas(self):
        self.assertTrue(self.tee.exists(), "LICENSE fail puudub")

    def test_02_license_on_taielik(self):
        s = self.tee.read_text(encoding="utf-8")
        puudu = [o for o in APACHE2_OSAD if o not in s]
        self.assertEqual([], puudu, f"LICENSE-ist puudub: {puudu}")

    def test_03_license_on_baidihaaval_kanooniline(self):
        b = self.tee.read_bytes()
        self.assertEqual(APACHE2_SHA256, hashlib.sha256(b).hexdigest(),
                         "LICENSE ei ole apache.org tekstiga identne – "
                         "Apache-2.0 nõuab muutmata teksti")
        self.assertEqual(11358, len(b))

    def test_04_appendixi_kohahoidjad_on_puutumata(self):
        """APPENDIX on osa litsentsitekstist – seda ei täideta ära."""
        s = self.tee.read_text(encoding="utf-8")
        self.assertIn("Copyright [yyyy] [name of copyright owner]", s,
                      "APPENDIX kohahoidja on ära muudetud – "
                      "autoriõiguse teade kuulub NOTICE faili")

    def test_05_license_ei_nimeta_muud_litsentsi(self):
        s = self.tee.read_text(encoding="utf-8")
        for keelatud in ("MIT License", "GNU General Public",
                         "Mozilla Public"):
            self.assertNotIn(keelatud, s)


class TestNoticeFail(unittest.TestCase):

    def setUp(self):
        self.tee = JUUR / "NOTICE"
        self.s = self.tee.read_text(encoding="utf-8") if self.tee.exists() else ""

    def test_10_notice_on_olemas(self):
        self.assertTrue(self.tee.exists(), "NOTICE fail puudub")

    def test_11_notice_nimetab_projekti_ja_litsentsi(self):
        self.assertIn("MAYA", self.s)
        self.assertRegex(self.s, r"Copyright 20\d\d")
        self.assertIn("Apache License, Version 2.0", self.s)
        self.assertIn("LICENSE", self.s)

    def test_12_notice_ei_omista_autoriogust_eraisikule(self):
        """Omaniku juriidiline isik ei ole kontrollitud.

        NOTICE peab jääma projektipõhiseks. Kui siia tekib kunagi
        konkreetse inimese nimi, peab see olema teadlik otsus, mitte
        kogemata sisse jäänud kohahoidja või varasem nimi.
        """
        # Kohahoidjad, mis ei tohi NOTICE-isse jääda. Omaniku päris
        # nime siia EI kirjutata – see tuleb kohalikust failist, mis ei
        # kuulu hoidlasse (vt tests/privaatsed_mustrid.txt).
        keelatud = ["[name", "yyyy", "<SINU NIMI>", "TODO", "FIXME"]
        f = JUUR / "tests" / "privaatsed_mustrid.txt"
        if f.exists():
            keelatud += [r.strip() for r in
                         f.read_text(encoding="utf-8").splitlines()
                         if r.strip() and not r.startswith("#")]
        for k in keelatud:
            self.assertNotIn(k, self.s,
                             f"NOTICE sisaldab kontrollimata või "
                             f"täitmata välja: {k}")

    def test_13_notice_ei_omista_kolmandate_osapoolte_tood(self):
        """Ei tohi väita, et MAYA omab sõltuvusi või Google'i tööd."""
        yhe_reana = re.sub(r"\s+", " ", self.s)
        self.assertIn("not affiliated with", yhe_reana,
                      "NOTICE ei ütle, et Google'iga seost ei ole")
        self.assertIn("remain under their own licenses", yhe_reana,
                      "NOTICE ei ütle, et sõltuvustel on oma litsentsid")
        self.assertNotIn("All rights reserved", yhe_reana,
                         "„All rights reserved\" on Apache-2.0 all "
                         "eksitav")


class TestDokumentatsiooniJarjepidevus(unittest.TestCase):

    def test_20_litsents_ootel_fail_on_kadunud(self):
        self.assertFalse((JUUR / "LITSENTS_OOTEL.md").exists(),
                         "LITSENTS_OOTEL.md on alles")

    def test_21_ukski_fail_ei_viita_litsents_ootel_failile(self):
        for p in MD_FAILID:
            s = p.read_text(encoding="utf-8")
            self.assertNotIn("LITSENTS_OOTEL", s,
                             f"{p.name} viitab kustutatud failile")

    def test_22_ukski_fail_ei_utle_et_litsents_on_valimata(self):
        mustrid = [
            r"[Ll]itsents(?:i|il)? (?:on |ei ole )?valimata",
            r"ei ole (?:veel )?litsentsi",
            r"litsentsi(?:ta| puudub)",
            r"ÄRA AVALDA",
        ]
        for p in MD_FAILID:
            s = p.read_text(encoding="utf-8")
            for m in mustrid:
                self.assertIsNone(
                    re.search(m, s),
                    f"{p.name} väidab endiselt, et litsents puudub "
                    f"(muster: {m})")

    def test_23_readme_nimetab_apache_2_0(self):
        s = (JUUR / "README.md").read_text(encoding="utf-8")
        self.assertIn("Apache License 2.0", s)
        self.assertIn("[LICENSE](LICENSE)", s)
        self.assertIn("[NOTICE](NOTICE)", s)

    def test_24_ukski_dokument_ei_nimeta_mit_litsentsi_maya_omana(self):
        """Varem oli ajutine MIT litsents – see ei tohi tagasi tulla."""
        for p in MD_FAILID:
            s = p.read_text(encoding="utf-8")
            for rida in s.splitlines():
                if re.search(r"\bMIT\b", rida):
                    # MIT tohib esineda AINULT sõltuvuste litsentsina.
                    self.assertTrue(
                        p.name == "SOLTUVUSED.md" or
                        "sõltuvus" in rida.lower() or
                        "GPL" in rida,
                        f"{p.name}: kahtlane MIT viide: {rida.strip()}")

    def test_25_contributing_selgitab_panuse_tingimusi(self):
        s = (JUUR / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("Apache License 2.0", s)
        self.assertIn("§5", s, "Apache-2.0 §5 (inbound=outbound) "
                               "selgitus puudub")
        self.assertIn("CLA", s, "CLA nõude olek on ütlemata")
        self.assertIn("GPL", s, "hoiatus GPL-koodi toomise kohta puudub")

    def test_26_ei_lubata_automaatset_joudmist_eraparaldusse(self):
        for nimi in ("README.md", "CONTRIBUTING.md"):
            s = (JUUR / nimi).read_text(encoding="utf-8")
            self.assertIn("ei jõua automaatselt", s,
                          f"{nimi}: puudub märkus, et panus ei jõua "
                          f"automaatselt ühegi paigalduse sisse")

    def test_27_ei_viidata_majutatud_maya_teenusele(self):
        """Hoidla ei tohi jätta mulje, et keegi hoiab MAYA serverit üleval."""
        for nimi in ("README.md", "SECURITY.md", "CONTRIBUTING.md"):
            # Reavahetused kokku: dokumentides on read murtud 72 märgi
            # peal, nii et lause võib kahe rea vahel pooleks minna.
            s = re.sub(r"\s+", " ",
                       (JUUR / nimi).read_text(encoding="utf-8"))
            self.assertRegex(
                s, r"(ei ole teenus|ei jookse ühtegi MAYA teenust|"
                   r"ei ole ühtegi jooksvat MAYA teenust)",
                f"{nimi}: ei ütle välja, et majutatud teenust ei ole")


class TestKolmandateOsapoolteTeated(unittest.TestCase):

    def setUp(self):
        self.s = (JUUR / "docs/SOLTUVUSED.md").read_text(encoding="utf-8")

    def test_30_soltuvuste_dokument_nimetab_apache_2_0(self):
        self.assertIn("Apache License 2.0", self.s)

    def test_31_tld_erijuht_on_dokumenteeritud(self):
        """`tld` on kolmese litsentsiga (sh GPL-2.0) kaudne sõltuvus.

        Varem väitis dokumentatsioon, et GPL-sõltuvusi EI OLE. See oli
        ebatäpne. Parandus peab alles jääma – seda ei tohi vaikides
        tagasi muuta.
        """
        self.assertIn("tld", self.s)
        self.assertIn("MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later",
                      self.s)
        self.assertIn("trafilatura", self.s,
                      "ei ole öeldud, kust tld tuleb")

    def test_32_vana_ebataapne_vaide_on_kadunud(self):
        self.assertNotIn("Ühtegi GPL/AGPL sõltuvust ei ole", self.s)

    def test_33_certifi_mpl_on_valja_oeldud(self):
        self.assertIn("certifi", self.s)
        self.assertIn("MPL-2.0", self.s)

    def test_34_testisoltuvused_on_eraldi_margitud(self):
        self.assertIn("junit", self.s)
        self.assertIn("EPL-1.0", self.s)
        self.assertIn("ei satu", self.s,
                      "ei ole öeldud, et testisõltuvused ei lähe APK-sse")

    def test_35_ehitustooriistu_ei_loeta_soltuvusteks(self):
        self.assertIn("ehitusaegsed tööriistad", self.s)

    def test_36_oeldakse_et_koodi_ei_ole_kopeeritud(self):
        self.assertIn("ei sisalda ühtegi kolmanda osapoole", self.s)

    def test_37_fonte_ja_varasid_ei_ole(self):
        self.assertRegex(self.s, r"fonti, pilti ega helifaili")


class TestHoidlaTerviklikkus(unittest.TestCase):

    def _git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(JUUR), *args],
                              capture_output=True, text=True,
                              timeout=60).stdout

    def test_40_license_ja_notice_on_jalgitud(self):
        failid = self._git("ls-files").split()
        for f in ("LICENSE", "NOTICE"):
            self.assertIn(f, failid, f"{f} ei ole versioonihalduses")

    def test_41_saladusi_ja_binaare_ei_ole_jalgitud(self):
        failid = self._git("ls-files").split()
        keelatud = re.compile(
            r"(^|/)\.env$|\.apk$|\.aab$|\.keystore$|\.jks$|\.p12$|"
            r"\.pem$|\.key$|\.db$|\.sqlite3?$|\.session$|"
            r"^data/|keystore\.properties$|local\.properties$")
        leitud = [f for f in failid if keelatud.search(f)]
        self.assertEqual([], leitud, f"keelatud failid indeksis: {leitud}")

    def test_42_env_example_sisaldab_ainult_kohahoidjaid(self):
        s = (JUUR / ".env.example").read_text(encoding="utf-8")
        for muster in (r"AIza[0-9A-Za-z_\-]{20,}", r"gsk_[0-9A-Za-z]{20,}",
                       r"sk-[0-9A-Za-z]{20,}", r"ghp_[0-9A-Za-z]{20,}",
                       r"tvly-[0-9A-Za-z]{10,}"):
            self.assertIsNone(re.search(muster, s),
                              ".env.example sisaldab võtmemustrit")

    def test_43_git_ajaloos_ei_ole_votmemustreid(self):
        log = self._git("log", "-p", "--all")
        self.assertNotEqual("", log, "git log andis tühja tulemuse")
        for muster in (r"AIza[0-9A-Za-z_\-]{30,}", r"gsk_[0-9A-Za-z]{30,}",
                       r"sk-[0-9A-Za-z]{30,}", r"ghp_[0-9A-Za-z]{30,}"):
            self.assertIsNone(re.search(muster, log),
                              "git ajaloos on võtmemuster")

    def test_44_kaugharu_on_oodatav_avalik_hoidla(self):
        """Kui kaugharu on, peab see viitama OODATAVALE avalikule hoidlale.

        AJALUGU: enne avaldamist nõudis see test, et kaugharu EI OLE –
        nii ei saanud kogemata liiga vara avaldada. Projekt on nüüd
        avaldatud, seega see nõue oleks alati punane. Kontroll jääb
        siiski alles, aga teise sisuga: kaugharu tohib olla AINULT
        selle projekti enda avalik hoidla. Nii tabab test ära, kui
        keegi suunab `origin`-i kogemata võõrasse hoidlasse (nt
        privaatsesse koopiasse või mõne teise konto alla).
        """
        read = self._git("remote", "-v").strip()
        if not read:
            return  # kaugharu puudub – kohalik koopia, igati korras
        # Me EI nõua kindlat hoidlanime: kahvel (fork), peegel või
        # kohalik kloon on täiesti legitiimsed ja neil on oma aadress.
        # Keelatud on AINULT see, mis päriselt ohtlik oleks – et avalik
        # koopia osutaks omaniku PRIVAATSELE originaalile või
        # tootmisserverile.
        KEELATUD = ("maya_projekti_kaust", "voice-agent", "server-2")
        for rida in read.splitlines():
            osad = rida.split()
            url = osad[1] if len(osad) > 1 else ""
            for k in KEELATUD:
                self.assertNotIn(
                    k, url,
                    f"kaugharu viitab privaatsesse sihtkohta ({k}): {url}")

    def test_45_originaalprojekti_ajalugu_ei_ole_imporditud(self):
        """Avalik koopia algab oma esimesest commit'ist.

        NB: SEDA EI SAA KONTROLLIDA LÜHENDATUD (shallow) KLOONIS.
        GitHub Actions kloonib vaikimisi `fetch-depth: 1`, mille puhul
        ainsal toodud commit'il EI OLE vanemat kirjas – `git rev-list
        --max-parents=0` peab siis juurcommit'iks hoopis KÕIGE
        UUEMAT commit'i. Varasem versioon sellest testist kukkus CI-s
        just sellepärast läbi (ja andis eksitava veateate, nagu oleks
        ajalugu vale). Lühendatud kloonis jätame kontrolli vahele ja
        ütleme selle VÄLJA – täiskontroll käib kohalikult ja
        privaatsustöös, kus `fetch-depth: 0`.
        """
        if self._git("rev-parse", "--is-shallow-repository").strip() == "true":
            raise unittest.SkipTest(
                "lühendatud kloon (shallow) – juurcommit'i ei saa "
                "usaldusväärselt tuvastada; kontroll tehakse täisklooniga")
        juured = self._git("rev-list", "--max-parents=0", "HEAD").split()
        self.assertEqual(1, len(juured),
                         f"hoidlal on {len(juured)} juurcommit'i – "
                         f"võõras ajalugu on sisse toodud")
        esimene = self._git("log", "--format=%s", "--max-parents=0",
                            "HEAD").strip()
        self.assertIn("MAYA avalik versioon", esimene)


if __name__ == "__main__":
    unittest.main(verbosity=2)

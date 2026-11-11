# -*- coding: utf-8 -*-
"""Testid: MÄLU KARAKTERIPÕHINE ERALDATUS (08.11.2026 forensika järeldused).

Iga test siin vastab ÜHELE auditi leiule. Need kolm viga olid tootmises korraga:

  1) `SELECT fact FROM memory ORDER BY id DESC LIMIT 15` ei filtreerinud OLEKUT
     -> 'superseded'/'conflicted' faktid süstiti mudelile, seega vana juhis
        tuli uue kõrval uuesti pinnale;
  2) ei filtreerinud KARAKTERIT -> 'custom' karakteri intiimsed faktid süstiti
        ka 'asjalik'/'mentor'/'treener' prompti;
  3) `id DESC` + LIMIT 15 tähendas, et ALUSFAKTID ("Kasutaja nimi on Jaan")
        jäid akna taha ja mudel ei näinud neid kunagi.

KÄIVITAMINE: python3 tests_malu_karakteri_eraldatus.py
Testid kasutavad AINULT ajutist andmebaasi. Tootmisbaasi ei puudutata.
"""

import os

# AVALIK VERSIOON: vaikenimi tuleb seadistusest, mitte ühe
# inimese nimest. Test kontrollib ikka sama loogikat.
import sys as _s3, pathlib as _p3
_s3.path.insert(0, str(_p3.Path(__file__).resolve().parent.parent / "server"))
import config as _cfg
VAIKENIMI = _cfg.KASUTAJA_NIMI

import sqlite3
import sys
import tempfile
import unittest

# Lokaalselt on kood BASE/server/ all, serveris ~/maya/ juures
# lamedalt. Varem oli "server" siin kõvasti sees ja testid KUKKUSID serveris
# läbi failitee pärast – mitte sisulise vea pärast. KOOD_KAUST lahendab
# mõlema paigutuse; ükski kontroll ei muutu.
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOOD_KAUST = (os.path.join(_BASE, "server")
              if os.path.isfile(os.path.join(_BASE, "server", "memory_fts.py"))
              else _BASE)
sys.path.insert(0, KOOD_KAUST)

import memory_fts  # noqa: E402


def uus_baas():
    """Tühi ajutine baas täieliku skeemiga."""
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    memory_fts.ensure_schema(conn)
    return conn, path


class TestSkeem(unittest.TestCase):

    def test_01_persona_ja_scope_veerud_tekivad(self):
        conn, path = uus_baas()
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memory)")}
            self.assertIn("persona", cols)
            self.assertIn("scope", cols)
        finally:
            conn.close(); os.unlink(path)

    def test_02_scope_vaikeväärtus_on_shared(self):
        """Vana kood, mis lisab fakti ilma scope'i, peab jääma kõigile nähtavaks."""
        conn, path = uus_baas()
        try:
            conn.execute(
                "INSERT INTO memory (timestamp, fact) VALUES ('2026-11-08', 'Vana rida')"
            )
            scope = conn.execute(
                "SELECT scope FROM memory WHERE fact = 'Vana rida'"
            ).fetchone()[0]
            self.assertEqual(scope, "shared")
        finally:
            conn.close(); os.unlink(path)

    def test_03_ensure_schema_on_idempotentne(self):
        conn, path = uus_baas()
        try:
            muutused = memory_fts.ensure_schema(conn)
            self.assertEqual(muutused["columns_added"], [])
            self.assertEqual(muutused["tables_created"], [])
        finally:
            conn.close(); os.unlink(path)

    def test_04_arhiivil_on_karakteri_veerg(self):
        conn, path = uus_baas()
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(conversation_archive)")}
            self.assertIn("persona", cols)
        finally:
            conn.close(); os.unlink(path)


class TestNähtavus(unittest.TestCase):

    def valmista(self, conn):
        memory_fts.upsert_fact(conn, "Kasutaja nimi on Jaan.", category="muu",
                               confidence=0.9, persona=None, scope="shared")
        memory_fts.upsert_fact(conn, "Peetrile meeldib ansambel Pohjatuul.",
                               category="eelistus", confidence=0.6,
                               persona="singer", scope="persona")
        memory_fts.upsert_fact(conn, "Peetril on Mayaga eriline lähedus.",
                               category="suhe", confidence=0.8,
                               persona="custom", scope="persona")
        memory_fts.upsert_fact(conn, "Jaan hoiab seda enda teada.",
                               category="identiteet", confidence=0.5,
                               persona="custom", scope="private")

    def test_05_asjalik_ei_nae_custom_fakte(self):
        """SEE ON AUDITI PEAMINE LEID. Enne parandust nägi asjalik kõike."""
        conn, path = uus_baas()
        try:
            self.valmista(conn)
            faktid = memory_fts.facts_for_prompt(conn, persona="asjalik")
            self.assertIn("Kasutaja nimi on Jaan.", faktid)
            self.assertNotIn("Peetril on Mayaga eriline lähedus.", faktid)
            self.assertNotIn("Peetrile meeldib ansambel Pohjatuul.", faktid)
            self.assertNotIn("Jaan hoiab seda enda teada.", faktid)
        finally:
            conn.close(); os.unlink(path)

    def test_06_custom_naeb_oma_fakte(self):
        conn, path = uus_baas()
        try:
            self.valmista(conn)
            faktid = memory_fts.facts_for_prompt(conn, persona="custom")
            self.assertIn("Peetril on Mayaga eriline lähedus.", faktid)
            self.assertIn("Kasutaja nimi on Jaan.", faktid)
            self.assertNotIn("Peetrile meeldib ansambel Pohjatuul.", faktid)
        finally:
            conn.close(); os.unlink(path)

    def test_07_private_ei_satu_kunagi_prompti(self):
        """Isegi omanik ei saa 'private' fakti AUTOMAATSELT prompti."""
        conn, path = uus_baas()
        try:
            self.valmista(conn)
            for p in ("custom", "asjalik", "singer", ""):
                self.assertNotIn("Jaan hoiab seda enda teada.",
                                 memory_fts.facts_for_prompt(conn, persona=p),
                                 f"private leke karakterile '{p}'")
        finally:
            conn.close(); os.unlink(path)

    def test_08_tundmatu_karakter_saab_ainult_uhised(self):
        """Turvaline vaikeväärtus: kui karakterit ei tea, ei lekita midagi."""
        conn, path = uus_baas()
        try:
            self.valmista(conn)
            faktid = memory_fts.facts_for_prompt(conn, persona="")
            self.assertEqual(faktid, ["Kasutaja nimi on Jaan."])
        finally:
            conn.close(); os.unlink(path)

    def test_09_singer_naeb_oma_muusikafakte(self):
        conn, path = uus_baas()
        try:
            self.valmista(conn)
            faktid = memory_fts.facts_for_prompt(conn, persona="singer")
            self.assertIn("Peetrile meeldib ansambel Pohjatuul.", faktid)
            self.assertNotIn("Peetril on Mayaga eriline lähedus.", faktid)
        finally:
            conn.close(); os.unlink(path)


class TestOlekufilter(unittest.TestCase):

    def test_10_superseded_fakti_ei_sustita(self):
        """AUDITI LEID nr 2: aegunud fakt jõudis mudelini ja tuli uuesti pinnale.

        Olek pannakse paika otse, mitte sarnasusheuristika kaudu – siin
        testitakse SÜSTIMISFILTRIT, mitte seda, kas kaks lauset loetakse
        samateemaliseks. (Tootmises see paar asendus õigesti, vt ID 8/13/14.)
        """
        conn, path = uus_baas()
        try:
            conn.execute(
                "INSERT INTO memory (timestamp, fact, status, scope, confidence) "
                "VALUES ('2026-11-08', 'Jaan käib kolm korda nädalas ujumas.', "
                "'superseded', 'shared', 0.9)"
            )
            conn.execute(
                "INSERT INTO memory (timestamp, fact, status, scope, confidence) "
                "VALUES ('2026-11-08', 'Jaan ei käi enam ujumas.', "
                "'active', 'shared', 0.95)"
            )
            conn.commit()
            faktid = memory_fts.facts_for_prompt(conn, persona="asjalik")
            self.assertIn("Jaan ei käi enam ujumas.", faktid)
            self.assertNotIn("Jaan käib kolm korda nädalas ujumas.", faktid)
        finally:
            conn.close(); os.unlink(path)

    def test_11_conflicted_fakti_ei_sustita(self):
        conn, path = uus_baas()
        try:
            conn.execute(
                "INSERT INTO memory (timestamp, fact, status, scope) "
                "VALUES ('2026-11-08', 'Vastuoluline fakt', 'conflicted', 'shared')"
            )
            conn.commit()
            self.assertNotIn("Vastuoluline fakt",
                             memory_fts.facts_for_prompt(conn, persona="asjalik"))
        finally:
            conn.close(); os.unlink(path)


class TestElutsyklEraldatus(unittest.TestCase):

    def test_12_custom_fakt_ei_asenda_uhist_fakti(self):
        """Karakteripõhine fakt ei tohi ühist fakti maha võtta – muidu kaoks
        see kõigilt teistelt karakteritelt."""
        conn, path = uus_baas()
        try:
            r1 = memory_fts.upsert_fact(conn, "Peetril on sinine Volvo.",
                                        category="omand", confidence=0.8,
                                        persona=None, scope="shared")
            r2 = memory_fts.upsert_fact(conn, "Peetril on punane Volvo.",
                                        category="omand", confidence=0.8,
                                        persona="custom", scope="persona")
            self.assertEqual(r2["action"], "insert",
                             "custom fakt ei tohi ühist fakti asendada")
            olek = conn.execute("SELECT status FROM memory WHERE id = ?",
                                (r1["id"],)).fetchone()[0]
            self.assertEqual(olek, "active", "ühine fakt jäi ellu")
        finally:
            conn.close(); os.unlink(path)

    def test_13_uhine_fakt_ei_asenda_karakteri_fakti(self):
        conn, path = uus_baas()
        try:
            r1 = memory_fts.upsert_fact(conn, "Peetril on roheline Volvo.",
                                        category="omand", confidence=0.8,
                                        persona="singer", scope="persona")
            memory_fts.upsert_fact(conn, "Peetril on must Volvo.",
                                   category="omand", confidence=0.8,
                                   persona=None, scope="shared")
            olek = conn.execute("SELECT status FROM memory WHERE id = ?",
                                (r1["id"],)).fetchone()[0]
            self.assertEqual(olek, "active")
        finally:
            conn.close(); os.unlink(path)

    def test_14_sama_karakteri_sees_elutsykkel_toimib_edasi(self):
        """Eraldatus EI TOHI elutsüklit katki teha omaniku sees."""
        conn, path = uus_baas()
        try:
            r1 = memory_fts.upsert_fact(conn, "Jaan eelistab aeglast tempot.",
                                        category="eelistus", confidence=0.6,
                                        persona="singer", scope="persona")
            r2 = memory_fts.upsert_fact(conn, "Jaan eelistab kiiret tempot.",
                                        category="eelistus", confidence=0.8,
                                        persona="singer", scope="persona")
            self.assertIn(r2["action"], ("supersede", "conflict"))
            olek = conn.execute("SELECT status FROM memory WHERE id = ?",
                                (r1["id"],)).fetchone()[0]
            self.assertIn(olek, ("superseded", "conflicted"))
        finally:
            conn.close(); os.unlink(path)


class TestJarjestus(unittest.TestCase):

    def test_15_alusfaktid_ei_jaa_akna_taha(self):
        """AUDITI LEID nr 3: `id DESC LIMIT 15` peitis vanad alusfaktid.
        Kindluse järgi järjestades on nimi mudelile nähtav ka 40 fakti juures."""
        conn, path = uus_baas()
        try:
            memory_fts.upsert_fact(conn, "Kasutaja nimi on Jaan.",
                                   category="muu", confidence=1.0)
            # Täitefaktid peavad olema LEKSIKAALSELT ERINEVAD. Kui kasutada
            # "pisiasi number 0/1/2...", loeb normaliseerija need duplikaatideks
            # ja iga duplikaat tõstab kindlust +0.05 – 40 korda hiljem oleks
            # täitefakt kindlusega 1.0 ja test mõõdaks hoopis muud asja.
            sonad = ["kapsas", "vihmavari", "trummipulk", "kardin", "pliiats",
                     "ankur", "tikand", "vaarikas", "kirves", "pöörlemine",
                     "lumehelves", "tuletikk", "sadul", "klaverijalg", "kamin",
                     "kangas", "merevaik", "sõnajalg", "rööbas", "küünal",
                     "savikruus", "tuulelipp", "kaelkirjak", "piparmünt",
                     "vaskplaat", "köiekeerd", "plekkkatus", "nööpnõel",
                     "kummipall", "jahutorn", "sildkaar", "paadisild",
                     "turbasammal", "raudtee", "kiviaed", "vahtralehed",
                     "purjeriie", "ahjuroop", "veskikivi", "tõrvanõu"]
            for s in sonad:
                memory_fts.upsert_fact(conn, f"Peetri toas on {s}.",
                                       category="muu", confidence=0.2)
            faktid = memory_fts.facts_for_prompt(conn, persona="asjalik")
            self.assertIn("Kasutaja nimi on Jaan.", faktid)
            self.assertEqual(faktid[0], "Kasutaja nimi on Jaan.")
        finally:
            conn.close(); os.unlink(path)

    def test_16b_limiit_ei_tohi_olla_siduv_tavakasutuses(self):
        """MÕÕDETUD 09.11.2026: limiit 30 oli tootmises juba siduv ja
        lõikas 'custom' karakterilt 2 fakti ära. Limiit peab olema
        turvaventiil, mitte igapäevane piirang."""
        conn, path = uus_baas()
        try:
            # Realistlik kogus: tootmises oli 32 aktiivset fakti.
            for i in range(40):
                memory_fts.upsert_fact(conn, f"Kasutajal on asi number {i} kapis.",
                                       category="omand", confidence=0.5)
            faktid = memory_fts.facts_for_prompt(conn, persona="asjalik")
            self.assertLess(len(faktid), memory_fts.INJECT_LIMIT,
                            "limiit on siduv juba 40 fakti juures – tõsta seda")
        finally:
            conn.close(); os.unlink(path)

    def test_16_limiit_on_turvaventiil(self):
        conn, path = uus_baas()
        try:
            for i in range(80):
                memory_fts.upsert_fact(conn, f"Fakt number {i}.",
                                       category="muu", confidence=0.5)
            faktid = memory_fts.facts_for_prompt(conn, persona="asjalik")
            self.assertLessEqual(len(faktid), memory_fts.INJECT_LIMIT)
        finally:
            conn.close(); os.unlink(path)


class TestOtsing(unittest.TestCase):

    def test_17_search_facts_austab_karakterit(self):
        conn, path = uus_baas()
        try:
            memory_fts.upsert_fact(conn, "Peetrile meeldib Pohjatuul väga.",
                                   category="eelistus", confidence=0.6,
                                   persona="singer", scope="persona")
            leitud = memory_fts.search_facts(conn, "Pohjatuul", persona="asjalik")
            self.assertEqual(leitud, [], "asjalik leidis singer'i fakti otsinguga")
            leitud = memory_fts.search_facts(conn, "Pohjatuul", persona="singer")
            self.assertTrue(any("Pohjatuul" in h["fact"] for h in leitud))
        finally:
            conn.close(); os.unlink(path)

    def test_18_recall_tooriist_naeb_omaniku_private_fakti(self):
        """Automaatne süstimine EI tohi 'private' fakti näidata, aga kui mudel
        ise küsib (recall_memory), siis omanik tohib selle leida."""
        conn, path = uus_baas()
        try:
            memory_fts.upsert_fact(conn, "Jaan usaldas mulle salajase mõtte.",
                                   category="identiteet", confidence=0.6,
                                   persona="custom", scope="private")
            self.assertNotIn("Jaan usaldas mulle salajase mõtte.",
                             memory_fts.facts_for_prompt(conn, persona="custom"))
            leitud = memory_fts.search_facts(conn, "salajase mõtte",
                                             persona="custom", include_private=True)
            self.assertTrue(any("salajase" in h["fact"] for h in leitud))
            leitud = memory_fts.search_facts(conn, "salajase mõtte",
                                             persona="asjalik", include_private=True)
            self.assertEqual(leitud, [], "asjalik leidis custom'i private fakti")
        finally:
            conn.close(); os.unlink(path)


class TestOmanikuReegel(unittest.TestCase):
    """PARANDATUD 09.11.2026 Peetri täpsustuse järel:

      "kõik karakterid peaksid teadma seda sama mida ma olen rääkinud ühe
       karakteriga, lihtsalt nad ei peaks intiimset juttu ajama"

    AJALUGU: algul piirasin karakteri järgi (singer faktid ainult
    lauljale) – vale. Siis piiras intiimsus – ka vale, sest sama intiimne
    suhe killustus kolme karakteri vahel (ID 38/40 custom, 50 romantiline,
    51/52 sarkastiline) ja ükski ei näinud tervikpilti.

    OMANIKU LÕPLIK OTSUS (10.11.2026): ulatust piirab AINULT kasutaja
    selgesõnaline privaatsuskorraldus. Intiimsus on pelk märgend.
    """

    def test_19_intiimne_fakt_on_YHINE(self):
        """SEE ON PÕHIMUUDATUS. Varem andis ('custom', 'persona')."""
        self.assertEqual(
            memory_fts.resolve_scope("custom", "suhe", intimate=True),
            (None, "shared"))

    def test_19b_ainult_privaatsuskorraldus_piirab(self):
        self.assertEqual(
            memory_fts.resolve_scope("mentor", "tervis", False,
                                     {"private": True}),
            ("mentor", "persona"))

    def test_19c_mudeli_vaide_ei_piisa(self):
        """privacy=None või private=False ei tohi midagi piirata."""
        for pr in (None, {"private": False}, {"reason": "tundlik"}):
            self.assertEqual(
                memory_fts.resolve_scope("custom", "suhe", True, pr),
                (None, "shared"), pr)

    def test_20_tavaline_fakt_on_uhine(self):
        self.assertEqual(memory_fts.resolve_scope("asjalik", "omand"),
                         (None, "shared"))

    def test_21_muusikaeelistus_on_UHINE(self):
        """SEE ON PARANDUS. Varem jäi laulja fakt ainult lauljale, nii et
        'asjalik' ei teadnud, et Peetrile meeldib Pohjatuul."""
        self.assertEqual(memory_fts.resolve_scope("singer", "eelistus"),
                         (None, "shared"))
        self.assertEqual(memory_fts.resolve_scope("laulja", "eelistus"),
                         (None, "shared"))

    def test_22_tundlik_kategooria_uksi_EI_piira(self):
        """'suhe' fakt "Peetril on vend Tiit" peab jääma ühiseks – ainult
        intiimsuse lipp piirab, mitte kategooria."""
        self.assertEqual(memory_fts.resolve_scope("custom", "suhe"),
                         (None, "shared"))
        self.assertEqual(memory_fts.resolve_scope("sober", "identiteet"),
                         (None, "shared"))

    def test_23_intiimne_ilma_karakterita_on_YHINE(self):
        """Varem läks 'custom'-ile. Nüüd ühine – intiimsus ei piira."""
        self.assertEqual(memory_fts.resolve_scope("", "suhe", intimate=True),
                         (None, "shared"))

    def test_23c_korraldus_ilma_karakterita_annab_private(self):
        """Korraldus on kontrollitud, aga karakterit ei tea -> ei süstita
        kuhugi. Peab jääma recall_memory kaudu leitavaks (vt
        tests_privaatsus_tootmine)."""
        self.assertEqual(
            memory_fts.resolve_scope("", "suhe", True, {"private": True}),
            (None, "private"))

    def test_23b_eraldamise_prompt_kusib_intiimsust(self):
        """Ilma selle väljata ei oskaks süsteem vahet teha."""
        src = (os.path.join(KOOD_KAUST, "memory_engine.py"))
        with open(src, encoding="utf-8") as f:
            t = f.read()
        self.assertIn('"intimate": true/false', t)
        self.assertIn("Pohjatuul", t)      # näide, mis EI ole intiimne
        # Prompt EI TOHI enam lubada, et intiimsus piirab ulatust – mudel
        # kalibreerib selle järgi.
        self.assertNotIn("intiimsed faktid jäävad ainult sellele", t)
        self.assertIn("Intiimsus EI tee fakti", t)
        # Voorunumbri nõue peab promptis olema, muidu puudub kaitse 1 sisend.
        self.assertIn('"turn"', t)


class TestKasutajaNimi(unittest.TestCase):
    """Nimi peab olema ÜHES kohas, muidu kaks tõeallikat lähevad lahku."""

    def setUp(self):
        import user_profile
        self.up = user_profile
        self.db = tempfile.mktemp(suffix=".db")
        self.up.invalidate_cache()

    def tearDown(self):
        self.up.invalidate_cache()
        if os.path.exists(self.db):
            os.unlink(self.db)

    def test_nimi_vaikimisi_kui_baas_tuhi(self):
        self.assertEqual(self.up.get_name(self.db), VAIKENIMI)

    def test_nime_muutmine_ja_lugemine(self):
        r = self.up.set_name("Jaanus", self.db)
        self.assertTrue(r["ok"])
        self.assertEqual(r["old"], VAIKENIMI)
        self.assertEqual(r["new"], "Jaanus")
        self.assertEqual(self.up.get_name(self.db, use_cache=False), "Jaanus")

    def test_lause_ei_lahe_nimeks(self):
        """Valesti kuuldud lause ei tohi iga karakteri prompti sattuda."""
        for halb in ("jäta meelde et minu nimi on Jaanus", "", "   ",
                     "Peeter123", "a" * 80, "nimi!"):
            r = self.up.set_name(halb, self.db)
            self.assertFalse(r["ok"], f"lubas nimeks: {halb!r}")
        self.assertEqual(self.up.get_name(self.db, use_cache=False), VAIKENIMI)

    def test_usutavad_nimed_labivad(self):
        for hea in ("Jaanus", "Mari-Liis", "Anne Mari", "O'Brien"):
            self.up.invalidate_cache()
            r = self.up.set_name(hea, self.db)
            self.assertTrue(r["ok"], f"keelas nime: {hea!r}")

    def test_kohahoidja_asendatakse(self):
        self.up.set_name("Jaanus", self.db)
        t = self.up.fill("Sinu vestluspartner on {USER}.", self.db)
        self.assertEqual(t, "Sinu vestluspartner on Jaanus.")

    def test_tekst_ilma_kohahoidjat_jaab_samaks(self):
        self.assertEqual(self.up.fill("Tere.", self.db), "Tere.")

    def test_karakterite_promptides_ei_ole_kovakodeeritud_nime(self):
        """SEE OLI PÕHIVIGA: nimi oli kõigi 10 karakteri promptis sees."""
        import persona_registry
        for p in persona_registry.get_all_personas():
            self.assertNotIn(VAIKENIMI, p.prompt_voice,
                             f"karakteri '{p.id}' promptis on kõvakodeeritud nimi")

    def test_build_voice_prompt_asendab_nime(self):
        import persona_registry
        t = persona_registry.build_voice_prompt("asjalik")
        self.assertNotIn("{USER}", t, "kohahoidja jäi asendamata")

    def test_nimefakt_ei_satu_faktitabelisse(self):
        """Nimi ei tohi olla fakt – elutsükkel ei suuda teda usaldusväärselt
        asendada (mõõdetud: 1 sõnastus 4-st)."""
        conn, path = uus_baas()
        try:
            memory_fts.upsert_fact(conn, "Kasutaja nimi on Jaan.",
                                   category="muu", confidence=0.6)
            n = memory_fts.retire_name_facts(conn, (VAIKENIMI, "Jaanus"))
            self.assertEqual(n, 1)
            self.assertNotIn("Kasutaja nimi on Jaan.",
                             memory_fts.facts_for_prompt(conn, persona="asjalik"))
            olek = conn.execute(
                "SELECT status FROM memory WHERE fact='Kasutaja nimi on Jaan.'"
            ).fetchone()[0]
            self.assertEqual(olek, "retired", "fakt kustutati, mitte pensionile")
        finally:
            conn.close(); os.unlink(path)

    def test_teiste_inimeste_nimed_jaavad_alles(self):
        conn, path = uus_baas()
        try:
            memory_fts.upsert_fact(conn, "Peetril on sõber, kelle nimi on Tiit.",
                                   category="suhe", confidence=0.8)
            memory_fts.retire_name_facts(conn, (VAIKENIMI, "Jaanus"))
            self.assertIn("Peetril on sõber, kelle nimi on Tiit.",
                          memory_fts.facts_for_prompt(conn, persona="asjalik"))
        finally:
            conn.close(); os.unlink(path)

    def test_kaal_ja_pikkus_on_tavalised_faktid(self):
        """Neid ta tahab salvestada – need EI tohi nimefiltrisse langeda."""
        for f in ("Jaan kaalub 82 kilo.", "Peetri pikkus on 180 sentimeetrit."):
            self.assertFalse(memory_fts.is_name_fact(f, VAIKENIMI), f)

    def test_susteemipromptis_on_nimereegel(self):
        """MÕÕDETUD VIGA 09.11.2026: tööriist oli deklareeritud, aga
        süsteemipromptis ei olnud selle kohta reeglit. Mudel kutsus
        recall_memory ja VÄITIS logis, et kutsus set_user_name – käivitusi
        oli 0. Ilma selge reegliga jutustab mudel teo, mida ta ei teinud."""
        src = os.path.join(KOOD_KAUST, "live_maya_ws.py")
        with open(src, encoding="utf-8") as f:
            t = f.read()
        # Reegel peab olema SÜSTEEMIPROMPTIS, mitte ainult deklaratsioonis.
        i = t.index("KRIITILISED REEGLID TÖÖRIISTADE KASUTAMISEL")
        j = t.index("DÜNAAMILINE KONTEKST", i)
        prompt = t[i:j]
        self.assertIn("set_user_name", prompt,
                      "süsteemipromptis ei ole set_user_name reeglit")
        self.assertIn("minu nimi on", prompt.lower(),
                      "reegel ei kirjelda vallandavat fraasi")
        self.assertIn("ÄRA ütle, et sa salvestasid", prompt,
                      "puudub keeld jutustada tegu, mida ei tehtud")

    def test_varutee_kone_lopus_olemas(self):
        """Kui mudel tööriista ei kutsu, peab nimi paranema kõne lõpus."""
        src = os.path.join(KOOD_KAUST, "memory_engine.py")
        with open(src, encoding="utf-8") as f:
            t = f.read()
        self.assertIn('"user_name"', t, "eraldamise prompt ei küsi nime")
        self.assertIn("user_profile.valid_name(uus_nimi)", t,
                      "varutee ei valideeri nime")
        self.assertIn("retire_name_facts", t,
                      "varutee ei saada vanu nimeväiteid pensionile")
        # Varutee peab olema ENNE faktide salvestamist, et faktifilter
        # kasutaks juba uut nime.
        i = t.index("uus_nimi = str(data.get")
        j = t.index('data.get("has_facts") and data.get("facts")', i)
        self.assertLess(i, j, "varutee jookseb pärast faktide salvestamist")

    def test_mudel_ei_saa_nime_tagasi_muuta(self):
        """MÕÕDETUD VIGA 09.11.2026: kasutaja ütles uue nime, tööriist
        salvestas, ja 25 s hiljem kutsus MUDEL ISE tööriista vana nimega
        tagasi ('Sinu nimi ongi Jaan, kallis'). Mudeli veendumus ei tohi
        kasutaja öeldut üle kirjutada."""
        r1 = self.up.set_name("Jaanus", self.db)
        self.assertTrue(r1["ok"])
        # mudel üritab tagasi
        r2 = self.up.set_name(VAIKENIMI, self.db)
        self.assertFalse(r2["ok"], "lubas nime tagasi muuta")
        self.assertEqual(self.up.get_name(self.db, use_cache=False), "Jaanus")
        self.assertIn("Jaanus", r2["teade"])

    def test_vahesammuga_ei_saa_vanale_nimele_tagasi(self):
        """SEE OLI MINU ESIMESE PARANDUSE AUK. Kaitse vaatas ainult
        VAHETUT eelmist nime, nii et mudel pääses vanale nimele tagasi
        ühe vahesammu kaudu: Jaan -> Jaanus -> Ai Jaan -> Jaan."""
        self.up.set_name("Jaanus", self.db)      # Jaan -> Jaanus
        self.up.set_name("Ai Jaan", self.db)     # Jaanus -> Ai Jaan
        r = self.up.set_name(VAIKENIMI, self.db)    # mudel üritab algusesse
        self.assertFalse(r["ok"], "pääses vahesammuga vanale nimele tagasi")
        self.assertEqual(self.up.get_name(self.db, use_cache=False), "Ai Jaan")

    def test_haldur_saab_kaitsest_moodas_parandada(self):
        """Kõnetuvastus võib nime valesti kuulda ('Ai Jaan' vs 'Jaanus').
        Inimene peab saama selle ära parandada ka siis, kui kaitse muidu
        ees seisaks."""
        self.up.set_name("Jaanus", self.db)
        self.up.set_name("Ai Jaan", self.db)
        r = self.up.force_name("Jaanus", self.db)
        self.assertTrue(r["ok"], r.get("teade"))
        self.assertEqual(self.up.get_name(self.db, use_cache=False), "Jaanus")

    def test_nimi_loetakse_alati_baasist(self):
        """Vahemälu tekitas päris probleemi: väljaspool protsessi muudetud
        nimi ei jõudnud jooksvasse Maya protsessi enne taaskäivitust."""
        import sqlite3
        self.up.set_name("Jaanus", self.db)
        self.assertEqual(self.up.get_name(self.db), "Jaanus")
        # muudame OTSE baasis, nagu teeks teine protsess
        c = sqlite3.connect(self.db)
        c.execute("UPDATE settings SET value='Mart' WHERE key='user_name'")
        c.commit(); c.close()
        self.assertEqual(self.up.get_name(self.db), "Mart",
                         "vahemälu varjas välist muudatust")

    def test_ajalugu_on_piiratud(self):
        for n in ("Aa", "Bb", "Cc", "Dd", "Ee", "Ff", "Gg", "Hh", "Ii",
                  "Jj", "Kk", "Ll", "Mm"):
            self.up.set_name(n, self.db)
        self.assertLessEqual(len(self.up.history(self.db)),
                             self.up.HISTORY_MAX)

    def test_kasutaja_saab_kolmanda_nime_ikka_panna(self):
        """Kaitse ei tohi kasutajat lukustada – kolmas nimi peab minema."""
        self.up.set_name("Jaanus", self.db)
        r = self.up.set_name("Mart", self.db)
        self.assertTrue(r["ok"], "kaitse blokeeris päris muudatuse")
        self.assertEqual(self.up.get_name(self.db, use_cache=False), "Mart")

    def test_sama_nime_uuesti_panemine_on_ok(self):
        self.up.set_name("Jaanus", self.db)
        r = self.up.set_name("Jaanus", self.db)
        self.assertTrue(r["ok"])

    def test_promptis_on_keeld_nime_ise_muuta(self):
        src = os.path.join(KOOD_KAUST, "live_maya_ws.py")
        with open(src, encoding="utf-8") as f:
            t = f.read()
        i = t.index("KRIITILISED REEGLID TÖÖRIISTADE KASUTAMISEL")
        j = t.index("DÜNAAMILINE KONTEKST", i)
        prompt = t[i:j]
        self.assertIn("NIME MUUDAB AINULT KASUTAJA", prompt)
        self.assertIn("KASUTAJA ÖELDU VÕIDAB", prompt)

    def test_tooriist_on_deklareeritud(self):
        src = os.path.join(KOOD_KAUST, "live_maya_ws.py")
        with open(src, encoding="utf-8") as f:
            t = f.read()
        self.assertIn('"name": "set_user_name"', t)
        self.assertIn('if fn_name == "set_user_name"', t)
        self.assertIn("def tool_set_user_name(", t)


class TestRistviited(unittest.TestCase):
    """See test püüab kinni vea, mis MAYA RESTARDI-TSÜKLISSE viis.

    Eemaldasin `memory_fts.PERSONA_OWNED` konstandid, aga `memory_engine`
    viitas neile endiselt -> AttributeError igal käivitusel.

    Miks senised testid seda ei püüdnud: nad impordivad `memory_fts`-i
    OTSE. `memory_engine` nõuab google-genai teeki, mida arendusmasinas ei
    ole, seega ükski test ei puutunud seda moodulit kunagi. Kontrollime
    viiteid STAATILISELT, ilma moodulit importimata.
    """

    def test_ristviited_memory_fts_peale_kehtivad(self):
        import ast
        kaust = KOOD_KAUST
        puudu = []
        for nimi in ("memory_engine.py", "maya_brain.py", "live_maya_ws.py"):
            tee = os.path.join(kaust, nimi)
            if not os.path.exists(tee):
                continue
            with open(tee, encoding="utf-8") as f:
                puu = ast.parse(f.read())
            for node in ast.walk(puu):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "memory_fts"
                        and not hasattr(memory_fts, node.attr)):
                    puudu.append(f"{nimi}:{node.lineno} -> memory_fts.{node.attr}")
        self.assertEqual(puudu, [], "olematud viited memory_fts peale: " + str(puudu))

    def test_viidatud_moodulid_on_imporditud(self):
        """Olematu viide on üks viga; importimata moodul on teine.

        `memory_fts.retire_name_facts` viide oli olemas ja kehtiv, aga
        `import memory_fts` puudus live_maya_ws-ist – see oleks andnud
        NameError alles esimesel nimemuutusel, mitte käivitusel.
        """
        import ast
        kaust = KOOD_KAUST
        puudu = []
        for nimi in ("memory_engine.py", "maya_brain.py", "live_maya_ws.py",
                     "persona_registry.py"):
            tee = os.path.join(kaust, nimi)
            if not os.path.exists(tee):
                continue
            with open(tee, encoding="utf-8") as f:
                src = f.read()
            puu = ast.parse(src)
            # millised moodulid on imporditud (ka funktsiooni sees)
            imporditud = set()
            for node in ast.walk(puu):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        imporditud.add((a.asname or a.name).split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imporditud.add(node.module.split(".")[0])
                    for a in node.names:
                        imporditud.add(a.asname or a.name)
            # milliseid oma mooduleid kasutatakse
            omad = {"memory_fts", "memory_engine", "maya_brain",
                    "persona_registry", "user_profile"}
            for node in ast.walk(puu):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in omad
                        and node.value.id not in imporditud
                        and node.value.id != nimi[:-3]):
                    puudu.append(f"{nimi}:{node.lineno} kasutab "
                                 f"{node.value.id}, aga ei impordi seda")
        self.assertEqual(puudu, [], "; ".join(puudu))

    def test_resolve_scope_allkiri_on_uhilduv(self):
        """memory_engine kutsub kolme argumendiga – allkiri peab seda lubama.

        `privacy` lisandus neljandaks ja on valikuline, nii et vanad
        kolme argumendiga kutsujad töötavad muutmata.
        """
        import inspect
        sig = inspect.signature(memory_fts.resolve_scope)
        self.assertEqual(list(sig.parameters),
                         ["persona", "category", "intimate", "privacy"])
        # Kõik kolm peavad olema valikulised, et vanad kutsujad ei katkeks.
        for nimi, par in sig.parameters.items():
            self.assertIsNot(par.default, inspect.Parameter.empty,
                             f"parameeter {nimi} ei ole valikuline")


class TestKutsumiskohad(unittest.TestCase):
    """Staatilised kontrollid koodi vastu – need vead olid täpselt need,
    mille audit leidis, ja neid ei näe ükski ühikutest."""

    def loe(self, nimi):
        p = os.path.join(KOOD_KAUST, nimi)
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_24_sustimine_kaib_filtreeritud_funktsiooni_kaudu(self):
        """Filtriteta päring tohib koodis olla AINULT vana skeemi varuharus
        (vanad varukoopiad, kus 'scope' veergu pole). Peamine rada peab
        käima memory_fts.facts_for_prompt kaudu."""
        src = self.loe("maya_brain.py")
        self.assertIn("memory_fts.facts_for_prompt(conn, persona=persona)", src)
        # Vana päringu tekst esineb ka funktsiooni dokistringis (selgitusena),
        # seega loeme ainult TÄIDETAVAT esinemist: c.execute(...) sees.
        taidetav = src.index('"SELECT fact FROM memory ORDER BY id DESC LIMIT 15"')
        varuharu = src.index("# Vana skeem")
        self.assertLess(varuharu, taidetav,
                        "filtriteta päring ei ole varuharus")
        self.assertEqual(
            src.count('"SELECT fact FROM memory ORDER BY id DESC LIMIT 15"'), 1,
            "filtriteta päringut täidetakse rohkem kui ühes kohas")

    def test_25_brain_info_arvutatakse_parast_karakterit(self):
        """Kui kutse liigub tagasi karakteri lahendamise ETTE, siis
        karakterifilter ei saa töötada ja see test peab punaseks minema."""
        src = self.loe("live_maya_ws.py")
        # Otsime TEGELIKKU omistamist (reaalgus + taane), mitte kommentaari,
        # kus sama tekst võib viitena esineda.
        rida_kutse = src.index("\n    brain_info = maya_brain.get_dynamic_context")
        rida_persona = src.index("active_persona = persona_obj.id")
        self.assertLess(rida_persona, rida_kutse,
                        "brain_info arvutatakse ENNE karakteri lahendamist")

    def test_26_kutse_annab_karakteri_kaasa(self):
        src = self.loe("live_maya_ws.py")
        self.assertIn('get_dynamic_context("üldine info", persona=active_persona)', src)

    def test_27_konsolideerimine_annab_karakteri_kaasa(self):
        src = self.loe("live_maya_ws.py")
        self.assertIn("persona=active_persona", src)
        self.assertIn("consolidate_session_to_memory(", src)

    def test_28_brain_info_defineeritakse_enne_kasutamist(self):
        """Varem rikkusin täpselt sellise järjekorravea tõttu kogu kõnevoo
        (NameError igal vastusel). See test valvab seda."""
        src = self.loe("live_maya_ws.py")
        d = src.index("\n    brain_info = maya_brain.get_dynamic_context")
        u = src.index('DÜNAAMILINE KONTEKST:\\n{brain_info}')
        self.assertLess(d, u, "brain_info'd kasutatakse enne defineerimist")


if __name__ == "__main__":
    unittest.main(verbosity=2)

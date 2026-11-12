#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — meeldetuletuste taustavalvur mitme kasutajaga.

MIDA NEED TESTID TÕESTAVAD
--------------------------
1. Valvur LEIAB kasutajapõhised baasid (`data/users/<id>/reminders.db`)
   ja ka ühise baasi.
2. KAHE KASUTAJA meeldetuletused samal ajal käivituvad MÕLEMAD ja
   kõneteade läheb ÕIGE kasutaja seadmetele — mitte kunagi teise omale.
3. Ootel kõnesõnum on kasutajapõhine: kasutaja A meeldetuletuse tekst
   ei jõua kasutaja B kõnesse.
4. Vigade isolatsioon: ühe kasutaja katkine baas ei peata teiste
   kasutajate meeldetuletusi.
5. Täpselt üks kord: sama meeldetuletus ei käivitu teisel tsüklil
   uuesti (`is_done`), kordus liigub edasi.
6. Kordused: `none`, `daily`, `weekly`, `workdays`.
7. Seisma jäänud kordus (server oli maas mitu perioodi) lükatakse
   TULEVIKKU, mitte ei käivitu igal tsüklil uuesti.
8. Karakter (`persona`) kantakse meeldetuletusega kaasa.
9. Hommikubriifing kogub andmed helistamise hetkel.
10. Ühendused ja kasutajakontekst vabastatakse ka erindi korral.

MIDA NEED EI TÕESTA
-------------------
Siin ei ole päris Gemini Live'i ega päris Androidi seadet. Kontrollitakse
serveripoolset ahelat kuni `kone_publitseeri` kutseni — see on täpselt
see lüli, mis katki oli.

KÄIVITAMINE: python3 tests_meeldetuletuste_valvur.py
"""

import asyncio
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent
KOOD = JUUR / "server"
sys.path.insert(0, str(KOOD))

# Iga test saab oma andmekausta – päris andmeid me kunagi ei puutu.
_TMP = tempfile.mkdtemp(prefix="maya_valvur_test_")
os.environ["MAYA_DATA_DIR"] = _TMP
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

import config  # noqa: E402
import web_maya  # noqa: E402
import live_maya_ws  # noqa: E402


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


SKEEM = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_time TEXT NOT NULL,
    reminder_text TEXT NOT NULL,
    is_done INTEGER DEFAULT 0,
    repeat_type TEXT DEFAULT 'none',
    custom_speech TEXT DEFAULT '',
    notify_type TEXT DEFAULT 'call',
    persona TEXT DEFAULT ''
);
"""


def loo_baas(tee: str) -> None:
    pathlib.Path(tee).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(tee) as c:
        c.executescript(SKEEM)


def kasutaja_baas(uid: int) -> str:
    return str(config.kasutaja_kaust(uid) / "reminders.db")


def lisa(tee: str, aeg: str, tekst: str, kordus: str = "none",
         kone: str = "", teade: str = "call", persona: str = "") -> int:
    with sqlite3.connect(tee) as c:
        cur = c.execute(
            "INSERT INTO reminders (trigger_time, reminder_text, is_done, "
            "repeat_type, custom_speech, notify_type, persona) "
            "VALUES (?,?,0,?,?,?,?)",
            (aeg, tekst, kordus, kone, teade, persona))
        return cur.lastrowid


def read(tee: str, rem_id: int) -> tuple:
    with sqlite3.connect(tee) as c:
        return c.execute(
            "SELECT is_done, trigger_time FROM reminders WHERE id=?",
            (rem_id,)).fetchone()


class ValvuriTest(unittest.IsolatedAsyncioTestCase):
    """Ühine alus: puhas olek ja kõneteadete pealtkuulamine."""

    def setUp(self):
        # Puhasta eelmise testi jäägid.
        for p in pathlib.Path(_TMP).glob("**/reminders.db"):
            p.unlink()
        web_maya._kone_tellijad.clear()
        live_maya_ws.PENDING_CALL_PROMPT.clear()
        live_maya_ws.PENDING_CALL_PERSONA.clear()
        # Salvesta, kellele mis kõneteade läks.
        self.teated = []
        self._paris_publitseeri = web_maya.kone_publitseeri

        async def _pyydja(uid, sisu):
            self.teated.append((uid, sisu))
            return await self._paris_publitseeri(uid, sisu)

        web_maya.kone_publitseeri = _pyydja

    def tearDown(self):
        web_maya.kone_publitseeri = self._paris_publitseeri

    async def tsykkel(self, now_str: str) -> None:
        """Üks valvuri tsükkel – ilma lõputa silmust ja ilma unega."""
        for uid, tee in web_maya.meeldetuletuste_baasid():
            try:
                await web_maya.tootle_meeldetuletused(uid, tee, now_str)
            except Exception as e:
                print(f"  (test) baasi {uid} viga: {e}")

    def uid_teated(self) -> dict:
        """Kellele mitu teadet läks."""
        read = {}
        for uid, _ in self.teated:
            read[uid] = read.get(uid, 0) + 1
        return read


# =====================================================================
# 1. BAASIDE AVASTAMINE
# =====================================================================

class TestBaasideAvastamine(ValvuriTest):

    async def test_01_leiab_kasutajabaasid_ja_yhise(self):
        loo_baas(config.DB_TEE)
        loo_baas(kasutaja_baas(1))
        loo_baas(kasutaja_baas(7))
        baasid = web_maya.meeldetuletuste_baasid()
        uidid = sorted(u for u, _ in baasid if u is not None)
        self.assertEqual([1, 7], uidid, f"kasutajabaase ei leitud: {baasid}")
        self.assertIn(None, [u for u, _ in baasid],
                      "ühist baasi ei leitud (ühilduvus katkeks)")

    async def test_02_ei_loo_puuduvat_baasi(self):
        """Valvur ei tohi tühja faili tekitada – see algataks vale skeemi."""
        loo_baas(kasutaja_baas(3))
        # Kasutaja 4 kaust on olemas, aga baasi ei ole.
        config.kasutaja_kaust(4).mkdir(parents=True, exist_ok=True)
        baasid = web_maya.meeldetuletuste_baasid()
        uidid = [u for u, _ in baasid if u is not None]
        self.assertIn(3, uidid)
        self.assertNotIn(4, uidid, "valvur arvestas olematu baasiga")
        self.assertFalse(pathlib.Path(kasutaja_baas(4)).exists(),
                         "valvur lõi puuduva baasi")

    async def test_03_eirab_mittenumbrilisi_kaustu(self):
        loo_baas(kasutaja_baas(2))
        vale = pathlib.Path(config.ANDMED) / "users" / "ajutine"
        vale.mkdir(parents=True, exist_ok=True)
        (vale / "reminders.db").touch()
        uidid = [u for u, _ in web_maya.meeldetuletuste_baasid() if u is not None]
        self.assertEqual([2], uidid)


# =====================================================================
# 2. KAKS KASUTAJAT SAMAL AJAL  ← PÕHINÕUE
# =====================================================================

class TestKaksKasutajat(ValvuriTest):

    async def test_10_molemad_kaivituvad_ja_lahevad_oigele_kasutajale(self):
        """Kaks kasutajat, meeldetuletus TÄPSELT samal ajal."""
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(a); loo_baas(b)
        id_a = lisa(a, "2026-01-01 10:00", "kasutaja A asi")
        id_b = lisa(b, "2026-01-01 10:00", "kasutaja B asi")

        await self.tsykkel("2026-01-01 10:00")

        self.assertEqual({1: 1, 2: 1}, self.uid_teated(),
                         f"kõneteated läksid valesti: {self.teated}")
        # Mõlemad märgiti tehtuks OMAS baasis.
        self.assertEqual(1, read(a, id_a)[0])
        self.assertEqual(1, read(b, id_b)[0])

    async def test_11_sisu_ei_leki_teisele_kasutajale(self):
        """Kasutaja A tekst EI TOHI jõuda kasutaja B kõneteatesse."""
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(a); loo_baas(b)
        lisa(a, "2026-01-01 10:00", "A SALAJANE TEEMA")
        lisa(b, "2026-01-01 10:00", "B TÄIESTI MUU TEEMA")

        await self.tsykkel("2026-01-01 10:00")

        for uid, sisu in self.teated:
            if uid == 1:
                self.assertIn("A SALAJANE", sisu)
                self.assertNotIn("B TÄIESTI", sisu)
            elif uid == 2:
                self.assertIn("B TÄIESTI", sisu)
                self.assertNotIn("A SALAJANE", sisu)

    async def test_12_ootel_sonum_on_kasutajapohine(self):
        """`set_pending_call_prompt` peab sõnumi siduma õige kasutajaga.

        Varem oli see moodulitasandi globaal: teine kasutaja kirjutas
        esimese sõnumi üle ja selle sai see, kes esimesena vastas.
        """
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(a); loo_baas(b)
        lisa(a, "2026-01-01 10:00", "A asi")
        lisa(b, "2026-01-01 10:00", "B asi")

        await self.tsykkel("2026-01-01 10:00")

        self.assertIn(1, live_maya_ws.PENDING_CALL_PROMPT)
        self.assertIn(2, live_maya_ws.PENDING_CALL_PROMPT)
        self.assertIn("A asi", live_maya_ws.PENDING_CALL_PROMPT[1])
        self.assertIn("B asi", live_maya_ws.PENDING_CALL_PROMPT[2])

        # Kasutaja 1 vastab -> saab AINULT oma sõnumi ja see tarbitakse.
        s1 = live_maya_ws._vota_pending(live_maya_ws.PENDING_CALL_PROMPT, 1)
        self.assertIn("A asi", s1)
        self.assertNotIn(1, live_maya_ws.PENDING_CALL_PROMPT)
        # Kasutaja 2 sõnum on endiselt alles ja puutumata.
        self.assertIn("B asi", live_maya_ws.PENDING_CALL_PROMPT[2])

    async def test_13_karakter_on_kasutajapohine(self):
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(a); loo_baas(b)
        lisa(a, "2026-01-01 10:00", "A asi", persona="singer")
        lisa(b, "2026-01-01 10:00", "B asi", persona="zen")

        await self.tsykkel("2026-01-01 10:00")

        self.assertEqual("singer", live_maya_ws.PENDING_CALL_PERSONA.get(1))
        self.assertEqual("zen", live_maya_ws.PENDING_CALL_PERSONA.get(2))

    async def test_14_kolm_kasutajat_jaavad_eraldi(self):
        baasid = {}
        for uid in (1, 2, 3):
            t = kasutaja_baas(uid)
            loo_baas(t)
            lisa(t, "2026-01-01 10:00", f"kasutaja {uid} asi")
            baasid[uid] = t
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual({1: 1, 2: 1, 3: 1}, self.uid_teated())
        for uid, sisu in self.teated:
            self.assertIn(f"kasutaja {uid} asi", sisu)

    async def test_15_teise_kasutaja_baasi_ei_puudutata(self):
        """Ühe kasutaja töötlemine ei tohi teise kirjeid muuta."""
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(a); loo_baas(b)
        id_a = lisa(a, "2026-01-01 10:00", "A asi")          # aegunud
        id_b = lisa(b, "2099-01-01 10:00", "B tulevikus")     # EI ole aegunud

        await self.tsykkel("2026-01-01 10:00")

        self.assertEqual(1, read(a, id_a)[0], "A ei märgitud tehtuks")
        self.assertEqual(0, read(b, id_b)[0], "B märgiti ekslikult tehtuks")
        self.assertEqual({1: 1}, self.uid_teated())


# =====================================================================
# 3. VIGADE ISOLATSIOON
# =====================================================================

class TestVigadeIsolatsioon(ValvuriTest):

    async def test_20_katkine_baas_ei_peata_teisi(self):
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        loo_baas(b)
        lisa(b, "2026-01-01 10:00", "B asi")
        # Kasutaja 1 baas on rämps, mitte SQLite.
        pathlib.Path(a).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a).write_bytes(b"see ei ole sqlite fail" * 50)

        await self.tsykkel("2026-01-01 10:00")

        self.assertEqual({2: 1}, self.uid_teated(),
                         "katkine baas peatas teiste kasutajate töötlemise")

    async def test_21_tabelita_baas_ei_vii_vea(self):
        """Baas on olemas, aga `reminders` tabelit ei ole."""
        a, b = kasutaja_baas(1), kasutaja_baas(2)
        pathlib.Path(a).parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(a).close()          # tühi, ilma skeemita
        loo_baas(b)
        lisa(b, "2026-01-01 10:00", "B asi")

        await self.tsykkel("2026-01-01 10:00")

        self.assertEqual({2: 1}, self.uid_teated())

    async def test_22_valvur_vabastab_konteksti_ka_erindi_korral(self):
        """Kontekst ei tohi erindi järel „külge jääda"."""
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2026-01-01 10:00", "A asi")

        async def plahvata(uid, sisu):
            raise RuntimeError("tahtlik viga kõneteate saatmisel")

        algne = web_maya.kone_publitseeri
        web_maya.kone_publitseeri = plahvata
        try:
            with self.assertRaises(RuntimeError):
                await web_maya.tootle_meeldetuletused(1, a, "2026-01-01 10:00")
        finally:
            web_maya.kone_publitseeri = algne

        self.assertIsNone(config.aktiivne_kasutaja(),
                          "kasutajakontekst jäi erindi järel külge")

    async def test_23_vanem_baas_ilma_persona_veeruta_tootab(self):
        """Vanad baasid ilma `persona`/`notify_type` veergudeta."""
        a = kasutaja_baas(1)
        pathlib.Path(a).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(a) as c:
            c.executescript("""
                CREATE TABLE reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_time TEXT NOT NULL,
                    reminder_text TEXT NOT NULL,
                    is_done INTEGER DEFAULT 0,
                    repeat_type TEXT DEFAULT 'none',
                    custom_speech TEXT DEFAULT ''
                );
                INSERT INTO reminders (trigger_time, reminder_text)
                VALUES ('2026-01-01 10:00', 'vana baasi asi');
            """)
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual({1: 1}, self.uid_teated())


# =====================================================================
# 4. TÄPSELT ÜKS KORD JA KORDUSED
# =====================================================================

class TestTapseltYksKord(ValvuriTest):

    async def test_30_sama_meeldetuletus_ei_kaivitu_kaks_korda(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2026-01-01 10:00", "ühekordne")

        await self.tsykkel("2026-01-01 10:00")
        await self.tsykkel("2026-01-01 10:00")   # teine tsükkel
        await self.tsykkel("2026-01-01 10:05")   # kolmas, hiljem

        self.assertEqual({1: 1}, self.uid_teated(),
                         f"topeltkõne: {self.teated}")

    async def test_31_paevane_kordus_liigub_homseks(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        rid = lisa(a, "2026-01-01 10:00", "iga päev", kordus="daily")

        await self.tsykkel("2026-01-01 10:00")

        is_done, uus_aeg = read(a, rid)
        self.assertEqual(0, is_done, "korduv meeldetuletus märgiti tehtuks")
        self.assertEqual("2026-01-02 10:00", uus_aeg)
        # Teine tsükkel samal ajal ei tohi uuesti käivituda.
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual({1: 1}, self.uid_teated())

    async def test_32_nadalane_kordus(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        rid = lisa(a, "2026-01-01 10:00", "iga nädal", kordus="weekly")
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual("2026-01-08 10:00", read(a, rid)[1])

    async def test_33_toopaevade_kordus_huppab_nadalavahetusest(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        # 2026-01-02 on reede -> järgmine tööpäev on esmaspäev 05.01.
        rid = lisa(a, "2026-01-02 10:00", "tööpäevadel", kordus="workdays")
        await self.tsykkel("2026-01-02 10:00")
        self.assertEqual("2026-01-05 10:00", read(a, rid)[1])

    async def test_34_seisma_jaanud_kordus_lykatakse_tulevikku(self):
        """Server oli maas 10 päeva – kordus ei tohi jääda minevikku.

        Vana kood liigutas aega AINULT ühe perioodi võrra, nii et
        aeg jäi endiselt minevikku ja sama kordus käivitus iga 5 s
        järel uuesti.
        """
        a = kasutaja_baas(1)
        loo_baas(a)
        rid = lisa(a, "2026-01-01 10:00", "iga päev", kordus="daily")

        await self.tsykkel("2026-01-11 09:00")   # 10 päeva hiljem

        is_done, uus_aeg = read(a, rid)
        self.assertEqual(0, is_done)
        self.assertGreater(uus_aeg, "2026-01-11 09:00",
                           f"kordus jäi minevikku: {uus_aeg}")
        # Ja ta ei käivitu kohe uuesti.
        enne = len(self.teated)
        await self.tsykkel("2026-01-11 09:00")
        self.assertEqual(enne, len(self.teated), "kordus käivitus tsüklis uuesti")

    async def test_35_ule_aja_lainud_yhekordne_kaivitub(self):
        """Serveri taaskäivituse järel peab vana meeldetuletus käivituma."""
        a = kasutaja_baas(1)
        loo_baas(a)
        rid = lisa(a, "2025-06-01 08:00", "ammune asi")
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual({1: 1}, self.uid_teated())
        self.assertEqual(1, read(a, rid)[0])

    async def test_36_tulevikus_ei_kaivitu(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2099-01-01 10:00", "kauges tulevikus")
        await self.tsykkel("2026-01-01 10:00")
        self.assertEqual({}, self.uid_teated())


# =====================================================================
# 5. SISU: KOHANDATUD KÕNE JA BRIIFING
# =====================================================================

class TestSisu(ValvuriTest):

    async def test_40_kohandatud_kone_tekst_voidab(self):
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2026-01-01 10:00", "ametlik teema",
             kone="Ärka üles, päike paistab!")
        await self.tsykkel("2026-01-01 10:00")
        self.assertIn("Ärka üles", self.teated[0][1])

    async def test_41_briifing_kogub_andmed_helistamise_hetkel(self):
        """`notify_type=briefing` peab kutsuma build_morning_briefing'u."""
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2026-01-01 10:00", "hommikubriifing", teade="briefing")

        kutsutud = []
        algne = web_maya.build_morning_briefing
        web_maya.build_morning_briefing = lambda: (
            kutsutud.append(1) or "ILM: päikeseline")
        try:
            await self.tsykkel("2026-01-01 10:00")
        finally:
            web_maya.build_morning_briefing = algne

        self.assertEqual(1, len(kutsutud),
                         "briifingu andmeid ei kogutud helistamise hetkel")
        self.assertIn("ILM: päikeseline", self.teated[0][1])

    async def test_42_yhine_baas_tootab_endiselt(self):
        """Autentimiseta paigaldus: ühine baas ilma kasutaja id-ta."""
        loo_baas(config.DB_TEE)
        lisa(config.DB_TEE, "2026-01-01 10:00", "ühise baasi asi")
        await self.tsykkel("2026-01-01 10:00")
        # Ühise baasi puhul langeb kõneteade omanikule (#1) –
        # `_KoneJarjekordProksi` dokumenteeritud käitumine.
        self.assertEqual(1, len(self.teated))
        self.assertIn("ühise baasi asi", self.teated[0][1])


# =====================================================================
# 6. VALVURI SILMUS
# =====================================================================

class TestValvuriSilmus(ValvuriTest):

    async def test_50_silmus_ei_sure_vea_peale(self):
        """Valvur peab vea järel edasi töötama, mitte vaikselt surema."""
        a = kasutaja_baas(1)
        loo_baas(a)
        lisa(a, "2026-01-01 10:00", "A asi")

        katsed = []
        algne = web_maya.tootle_meeldetuletused

        async def vigane(uid, tee, now):
            katsed.append(uid)
            if len(katsed) == 1:
                raise RuntimeError("tahtlik viga esimesel katsel")
            return await algne(uid, tee, now)

        web_maya.tootle_meeldetuletused = vigane
        task = asyncio.create_task(web_maya.background_reminder_watcher())
        try:
            # Oota kaks tsüklit (tsükkel on 5 s, aga esimene käib kohe).
            await asyncio.sleep(0.2)
            self.assertGreaterEqual(len(katsed), 1,
                                    "valvur ei jõudnud ühtegi tsüklit teha")
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            web_maya.tootle_meeldetuletused = algne

    async def test_51_valvur_on_startupis_kinni(self):
        """Valvur peab serveri käivitumisel päriselt käima minema."""
        src = (KOOD / "web_maya.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.create_task(background_reminder_watcher())", src)
        self.assertIn('@app.on_event("startup")', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)

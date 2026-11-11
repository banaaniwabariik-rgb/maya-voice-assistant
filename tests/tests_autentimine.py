#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — autentimise, autoriseerimise ja kasutajate eraldatuse testid.

MIDA NEED TESTID TÕESTAVAD
--------------------------
1. Paroole ei salvestata ega logita; räsi on soolatud scrypt.
2. Vale parool, aegunud token ja võltsitud token ei anna ligipääsu.
3. Iga `/api` otspunkt nõuab autentimist (AST-kontroll lähtekoodist).
4. WebSocket suletakse koodiga 1008, kui token puudub.
5. Üks kasutaja EI NÄE teise meeldetuletusi, mälufakte ega seadeid.
6. Üks kasutaja EI SAA käivitada teise telefonile kõnet.
7. Admin-otspunktid on tavakasutajale suletud.
8. Kiiruspiirang peatab paroolide jõuga murdmise.

MIDA NEED EI TÕESTA
-------------------
Siin ei ole võrgutasandi teste (TLS, pöördproksi) ega Androidi
kliendi teste. HTTP-kiht testitakse FastAPI `TestClient`-iga, mis
ajab päringud läbi päris rakenduse, aga mitte päris võrgu kaudu.
"""

import ast
import asyncio
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent
KOOD = JUUR / "server"
sys.path.insert(0, str(KOOD))

WS_SRC = (KOOD / "live_maya_ws.py").read_text(encoding="utf-8")
WEB_SRC = (KOOD / "web_maya.py").read_text(encoding="utf-8")

# Iga test saab oma andmekausta – päris andmeid me kunagi ei puutu.
_TMP = tempfile.mkdtemp(prefix="maya_auth_test_")
os.environ["MAYA_DATA_DIR"] = _TMP
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

import config  # noqa: E402
import auth  # noqa: E402


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def _puhasta_kasutajad():
    """Tühjenda kasutajate register testide vahel."""
    auth.ensure_schema()
    with auth._yhendus() as conn:
        conn.execute("DELETE FROM tokens")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM login_attempts")


# =====================================================================
# 1. PAROOLID
# =====================================================================
class TestParoolid(unittest.TestCase):

    def test_01_rasi_ei_sisalda_parooli(self):
        p = "see-on-minu-parool-123"
        r = auth.rasi_parool(p)
        self.assertNotIn(p, r)
        self.assertTrue(r.startswith("scrypt$"))
        self.assertEqual(len(r.split("$")), 3)

    def test_02_sama_parool_annab_ERINEVA_rasi(self):
        """Sool peab olema juhuslik – muidu paljastab ühesugune räsi,
        et kahel kasutajal on sama parool."""
        self.assertNotEqual(auth.rasi_parool("sama-parool-siin"),
                            auth.rasi_parool("sama-parool-siin"))

    def test_03_kontroll_tootab_molemat_pidi(self):
        r = auth.rasi_parool("õige-parool-on-see")
        self.assertTrue(auth.kontrolli_parooli("õige-parool-on-see", r))
        self.assertFalse(auth.kontrolli_parooli("vale-parool-on-see", r))
        self.assertFalse(auth.kontrolli_parooli("", r))

    def test_04_vigane_rasi_ei_viska_erindit(self):
        for praht in ("", "x", "scrypt$", "md5$aa$bb", "scrypt$zz$zz"):
            self.assertFalse(auth.kontrolli_parooli("ükskõik", praht))

    def test_05_liiga_lyhike_parool_keelatud(self):
        _puhasta_kasutajad()
        with self.assertRaises(auth.AuthViga) as c:
            auth.loo_kasutaja("testkasutaja", "lyhike")
        self.assertEqual(c.exception.kood, 400)

    def test_06_vigane_kasutajanimi_keelatud(self):
        _puhasta_kasutajad()
        for nimi in ("ab", "a" * 33, "kasutaja nimi", "../../etc/passwd",
                     "<script>", "kasutaja;drop"):
            with self.assertRaises(auth.AuthViga, msg=nimi):
                auth.loo_kasutaja(nimi, "korralik-pikk-parool")


# =====================================================================
# 2. TOKENID
# =====================================================================
class TestTokenid(unittest.TestCase):

    def setUp(self):
        _puhasta_kasutajad()
        self.k = auth.loo_kasutaja("alice", "alice-parool-123")
        self.token, _ = auth.logi_sisse("alice", "alice-parool-123")

    def test_10_token_annab_kasutaja(self):
        k = auth.kasutaja_tokenist(self.token)
        self.assertIsNotNone(k)
        self.assertEqual(k["username"], "alice")

    def test_11_voltsitud_token_ei_toimi(self):
        for t in (None, "", "x", self.token + "x", self.token[:-1],
                  "a" * 600):
            self.assertIsNone(auth.kasutaja_tokenist(t), t)

    def test_12_andmebaasis_ei_ole_tokenit_ennast(self):
        """Lekkinud andmebaas ei tohi anda kehtivaid tokeneid."""
        with auth._yhendus() as conn:
            read = conn.execute("SELECT token_hash FROM tokens").fetchall()
        self.assertTrue(read)
        for (h,) in read:
            self.assertNotEqual(h, self.token)
            self.assertNotIn(self.token, h)
            self.assertEqual(len(h), 64)      # SHA-256 hex

    def test_13_vale_parool_ei_anna_tokenit(self):
        with self.assertRaises(auth.AuthViga) as c:
            auth.logi_sisse("alice", "vale-parool-siin")
        self.assertEqual(c.exception.kood, 401)

    def test_14_olematu_kasutaja_annab_SAMA_vea(self):
        """Veateade ei tohi paljastada, kas kasutajanimi on olemas."""
        with self.assertRaises(auth.AuthViga) as c1:
            auth.logi_sisse("alice", "vale-parool-siin")
        with self.assertRaises(auth.AuthViga) as c2:
            auth.logi_sisse("sellist-pole-olemas", "vale-parool-siin")
        self.assertEqual(c1.exception.sonum, c2.exception.sonum)
        self.assertEqual(c1.exception.kood, c2.exception.kood)

    def test_15_aegunud_token_ei_toimi(self):
        import time
        with auth._yhendus() as conn:
            conn.execute("UPDATE tokens SET expires_at = ?",
                         (int(time.time()) - 10,))
        self.assertIsNone(auth.kasutaja_tokenist(self.token))
        # ja aegunud kirje koristatakse ära
        with auth._yhendus() as conn:
            n = conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        self.assertEqual(n, 0)

    def test_16_valjalogimine_tyhistab_tokeni(self):
        self.assertTrue(auth.logi_valja(self.token))
        self.assertIsNone(auth.kasutaja_tokenist(self.token))

    def test_17_peatatud_konto_ei_paase_sisse(self):
        with auth._yhendus() as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?",
                         (self.k["id"],))
        self.assertIsNone(auth.kasutaja_tokenist(self.token))

    def test_18_token_paringust_koik_kolm_teed(self):
        t = "abc123"
        self.assertEqual(auth.token_paringust(authorization=f"Bearer {t}"), t)
        self.assertEqual(auth.token_paringust(x_maya_token=t), t)
        self.assertEqual(auth.token_paringust(query_token=t), t)
        self.assertIsNone(auth.token_paringust(authorization="Basic xyz"))
        self.assertIsNone(auth.token_paringust())


# =====================================================================
# 3. KASUTAJATE ERALDATUS
# =====================================================================
class TestEraldatus(unittest.TestCase):

    def setUp(self):
        _puhasta_kasutajad()
        self.a = auth.loo_kasutaja("alice", "alice-parool-123")
        self.b = auth.loo_kasutaja("bob", "bob-parool-12345")

    def test_20_esimene_kasutaja_on_admin_teine_ei_ole(self):
        self.assertTrue(self.a["is_admin"])
        self.assertFalse(self.b["is_admin"])

    def test_21_igal_kasutajal_ERI_andmebaas(self):
        t = config.sea_aktiivne_kasutaja(self.a["id"])
        a_db = config.db_tee()
        config.taasta_aktiivne_kasutaja(t)
        t = config.sea_aktiivne_kasutaja(self.b["id"])
        b_db = config.db_tee()
        config.taasta_aktiivne_kasutaja(t)
        self.assertNotEqual(a_db, b_db)
        self.assertIn(str(self.a["id"]), a_db)
        self.assertIn(str(self.b["id"]), b_db)

    def test_22_meeldetuletus_EI_LEKI_teisele_kasutajale(self):
        import sqlite3
        # Alice loob meeldetuletuse OMA andmebaasi.
        t = config.sea_aktiivne_kasutaja(self.a["id"])
        import listen_direct
        listen_direct.init_db()
        with config.connect() as conn:
            conn.execute(
                "INSERT INTO reminders (trigger_time, reminder_text) "
                "VALUES (?, ?)", ("2026-01-01 10:00", "ALICE SALAJANE ASI"))
        config.taasta_aktiivne_kasutaja(t)

        # Bob vaatab oma andmebaasi – ei tohi midagi näha.
        t = config.sea_aktiivne_kasutaja(self.b["id"])
        listen_direct.init_db()
        with config.connect() as conn:
            read = conn.execute(
                "SELECT reminder_text FROM reminders").fetchall()
        config.taasta_aktiivne_kasutaja(t)
        self.assertEqual(read, [], f"Bob nägi Alice'i andmeid: {read}")

    def test_23_malufakt_EI_LEKI_teisele_kasutajale(self):
        import memory_fts
        t = config.sea_aktiivne_kasutaja(self.a["id"])
        with config.connect() as conn:
            memory_fts.ensure_schema(conn)
            conn.execute(
                "INSERT INTO memory (timestamp, fact) VALUES (?, ?)",
                ("2026-01-01", "Alice'i salajane fakt"))
        config.taasta_aktiivne_kasutaja(t)

        t = config.sea_aktiivne_kasutaja(self.b["id"])
        with config.connect() as conn:
            memory_fts.ensure_schema(conn)
            read = conn.execute("SELECT fact FROM memory").fetchall()
        config.taasta_aktiivne_kasutaja(t)
        self.assertEqual(read, [])

    def test_24_kasutaja_nimi_on_kasutajapohine(self):
        import user_profile
        t = config.sea_aktiivne_kasutaja(self.a["id"])
        with config.connect() as conn:
            user_profile.ensure_schema(conn)
            conn.execute("INSERT OR REPLACE INTO settings (key, value) "
                         "VALUES ('user_name', 'AliceNimi')")
        config.taasta_aktiivne_kasutaja(t)

        t = config.sea_aktiivne_kasutaja(self.b["id"])
        with config.connect() as conn:
            user_profile.ensure_schema(conn)
            r = conn.execute("SELECT value FROM settings WHERE key = "
                             "'user_name'").fetchone()
        config.taasta_aktiivne_kasutaja(t)
        self.assertIsNone(r, "Bob nägi Alice'i nime")

    def test_25_kasutajate_register_ei_ole_kellegi_oma(self):
        """Kasutajate ja tokenite tabel EI TOHI olla ühegi kasutaja
        andmebaasis – muidu saaks kasutaja teiste tokeneid lugeda."""
        for uid in (self.a["id"], self.b["id"]):
            t = config.sea_aktiivne_kasutaja(uid)
            tee = config.db_tee()
            config.taasta_aktiivne_kasutaja(t)
            self.assertNotEqual(tee, auth.kasutajate_db_tee())
        self.assertNotIn("users", str(config.ANDMED / "users.db").split("/")[-2:][0:1] or [""])


# =====================================================================
# 3b. WEBSOCKETI ÜHEKORDSED PILETID
# =====================================================================
class TestWsPiletid(unittest.TestCase):
    """Brauseri WebSocket API ei luba `Authorization` päist (RFC 6455
    / WHATWG piirang). Pilet lahendab selle nii, et URL-i jõuab
    ainult 60 s kehtiv ühekordne väärtus."""

    def setUp(self):
        _puhasta_kasutajad()
        self.a = auth.loo_kasutaja("alice", "alice-parool-123")
        self.b = auth.loo_kasutaja("bob", "bob-parool-12345")

    def test_26_pilet_annab_oige_kasutaja(self):
        pilet, eluiga = auth.loo_ws_pilet(self.a["id"])
        self.assertGreater(eluiga, 0)
        k = auth.kasuta_ws_piletit(pilet)
        self.assertIsNotNone(k)
        self.assertEqual(k["username"], "alice")

    def test_27_pilet_tootab_TAPSELT_UKS_kord(self):
        pilet, _ = auth.loo_ws_pilet(self.a["id"])
        self.assertIsNotNone(auth.kasuta_ws_piletit(pilet))
        self.assertIsNone(auth.kasuta_ws_piletit(pilet),
                          "pilet kehtis teist korda!")

    def test_28_voltsitud_pilet_ei_toimi(self):
        pilet, _ = auth.loo_ws_pilet(self.a["id"])
        for v in (None, "", "x", pilet + "x", pilet[:-1], "a" * 300):
            self.assertIsNone(auth.kasuta_ws_piletit(v), repr(v)[:30])
        # algne peab veel toimima
        self.assertIsNotNone(auth.kasuta_ws_piletit(pilet))

    def test_29_aegunud_pilet_ei_toimi(self):
        import time
        pilet, _ = auth.loo_ws_pilet(self.a["id"])
        with auth._yhendus() as conn:
            conn.execute("UPDATE ws_tickets SET expires_at = ?",
                         (int(time.time()) - 1,))
        self.assertIsNone(auth.kasuta_ws_piletit(pilet))

    def test_29b_andmebaasis_ei_ole_piletit_ennast(self):
        pilet, _ = auth.loo_ws_pilet(self.a["id"])
        with auth._yhendus() as conn:
            read = conn.execute(
                "SELECT ticket_hash FROM ws_tickets").fetchall()
        for (h,) in read:
            self.assertNotEqual(h, pilet)
            self.assertEqual(len(h), 64)

    def test_29c_teise_pilet_ei_anna_minu_kontot(self):
        pilet_b, _ = auth.loo_ws_pilet(self.b["id"])
        k = auth.kasuta_ws_piletit(pilet_b)
        self.assertEqual(k["id"], self.b["id"])
        self.assertNotEqual(k["id"], self.a["id"])

    def test_29d_peatatud_konto_pilet_ei_toimi(self):
        pilet, _ = auth.loo_ws_pilet(self.a["id"])
        with auth._yhendus() as conn:
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?",
                         (self.a["id"],))
        self.assertIsNone(auth.kasuta_ws_piletit(pilet))


# =====================================================================
# 4. HTTP KIHT (FastAPI TestClient)
# =====================================================================
class TestHTTP(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except Exception as e:
            raise unittest.SkipTest(f"TestClient puudub: {e}")
        import web_maya
        cls.client = TestClient(web_maya.app)
        cls.web = web_maya

    def setUp(self):
        _puhasta_kasutajad()

    def _konto(self, nimi, parool="parool-1234567890"):
        r = self.client.post("/api/auth/register",
                             json={"username": nimi, "password": parool})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"], r.json()["user"]

    def test_30_kaitstud_otspunkt_ilma_tokenita_annab_401(self):
        for tee in ("/api/reminders", "/api/call_events", "/api/briefing",
                    "/api/trigger_call", "/api/check_greeting"):
            r = self.client.get(tee) if tee != "/api/trigger_call" \
                else self.client.post(tee)
            self.assertIn(r.status_code, (401, 403),
                          f"{tee} vastas {r.status_code}, oodati 401/403")

    def test_31_vale_token_annab_401(self):
        r = self.client.get("/api/reminders",
                            headers={"Authorization": "Bearer vale-token"})
        self.assertEqual(r.status_code, 401)

    def test_32_kehtiv_token_annab_ligipaasu(self):
        token, _ = self._konto("alice")
        r = self.client.get("/api/reminders",
                            headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_33_status_on_avalik_ja_ei_leki_infot(self):
        r = self.client.get("/api/auth/status")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("seadistatud", d)
        # ei tohi sisaldada kasutajanimesid
        self.assertNotIn("username", r.text)
        self.assertNotIn("alice", r.text.lower())

    def test_34_teine_kasutaja_ei_nae_esimese_meeldetuletusi(self):
        t_a, _ = self._konto("alice")
        t_b, _ = self._konto("bob")
        self.client.post("/api/reminders",
                         headers={"Authorization": f"Bearer {t_a}"},
                         json={"trigger_time": "2026-01-01 10:00",
                               "reminder_text": "ALICE SALAJANE"})
        r = self.client.get("/api/reminders",
                            headers={"Authorization": f"Bearer {t_b}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("ALICE SALAJANE", r.text)

    def test_35_kone_jarjekorrad_on_kasutajapohised(self):
        t_a, u_a = self._konto("alice")
        t_b, u_b = self._konto("bob")
        qa = self.web.kone_jarjekord(u_a["id"])
        qb = self.web.kone_jarjekord(u_b["id"])
        self.assertIsNot(qa, qb)
        # Alice käivitab kõne -> AINULT tema järjekorda
        r = self.client.post("/api/trigger_call?reason=Alice",
                             headers={"Authorization": f"Bearer {t_a}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(qb.qsize(), 0, "Bob sai Alice'i kõne!")
        self.assertEqual(qa.qsize(), 1)

    def test_36_valjalogimine_tapab_tokeni(self):
        token, _ = self._konto("alice")
        h = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.post("/api/auth/logout",
                                          headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/reminders",
                                         headers=h).status_code, 401)

    def test_37_token_query_parameetrina_tootab_SSE_jaoks(self):
        token, _ = self._konto("alice")
        # /api/auth/me on lihtsaim viis kontrollida sama mehhanismi
        r = self.client.get(f"/api/auth/me?token={token}")
        self.assertEqual(r.status_code, 200, r.text)

    def test_38_registreerimine_ei_luba_duplikaati(self):
        self._konto("alice")
        r = self.client.post("/api/auth/register",
                             json={"username": "alice",
                                   "password": "muu-parool-123"})
        self.assertEqual(r.status_code, 409)

    def test_38b_ws_pilet_nouab_autentimist(self):
        r = self.client.post("/api/auth/ws_ticket")
        self.assertIn(r.status_code, (401, 403))

    def test_38c_ws_pilet_tuleb_ja_on_uhekordne(self):
        token, _ = self._konto("alice")
        h = {"Authorization": f"Bearer {token}"}
        r = self.client.post("/api/auth/ws_ticket", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIn("ticket", d)
        self.assertGreater(d["expires_in_s"], 0)
        # token ise EI TOHI vastuses olla
        self.assertNotIn(token, r.text)
        # ja pilet kehtib ühe korra
        import auth as _a
        self.assertIsNotNone(_a.kasuta_ws_piletit(d["ticket"]))
        self.assertIsNone(_a.kasuta_ws_piletit(d["ticket"]))

    def test_39_paroole_ei_tagastata_kunagi(self):
        token, _ = self._konto("alice", "minu-salajane-parool-9")
        for tee in ("/api/auth/me",):
            r = self.client.get(tee,
                                headers={"Authorization": f"Bearer {token}"})
            self.assertNotIn("minu-salajane-parool-9", r.text)
            self.assertNotIn("password", r.text.lower())


# =====================================================================
# 4b. MITU TELEFONI
# =====================================================================
class TestMituTelefoni(unittest.IsolatedAsyncioTestCase):
    """MÕÕDETUD LEID 11.11.2026: üks `asyncio.Queue` kasutaja kohta
    andis iga kõneteate AINULT ÜHELE telefonile, sest `Queue.get()`
    on ühe tarbija semantika. Kaks telefoni sama kontoga tähendas, et
    heliseb juhuslikult üks. Nüüd on publitseerimine fan-out."""

    @classmethod
    def setUpClass(cls):
        import web_maya
        cls.web = web_maya

    def setUp(self):
        _puhasta_kasutajad()
        self.a = auth.loo_kasutaja("alice", "alice-parool-123")
        self.b = auth.loo_kasutaja("bob", "bob-parool-12345")
        self.web._kone_tellijad.clear()

    async def test_70_kaks_telefoni_sama_kontoga_saavad_MOLEMAD(self):
        t1 = self.web.kone_telli(self.a["id"])
        t2 = self.web.kone_telli(self.a["id"])
        self.assertEqual(self.web.kone_tellijaid(self.a["id"]), 2)
        n = await self.web.kone_publitseeri(self.a["id"], "KÕNE")
        self.assertEqual(n, 2)
        self.assertEqual(t1.get_nowait(), "KÕNE")
        self.assertEqual(t2.get_nowait(), "KÕNE")

    async def test_71_teise_kasutaja_telefon_EI_SAA(self):
        t_a = self.web.kone_telli(self.a["id"])
        t_b = self.web.kone_telli(self.b["id"])
        await self.web.kone_publitseeri(self.a["id"], "ALICE KÕNE")
        self.assertEqual(t_a.get_nowait(), "ALICE KÕNE")
        with self.assertRaises(asyncio.QueueEmpty):
            t_b.get_nowait()

    async def test_72_lahkunud_seade_eemaldatakse(self):
        t1 = self.web.kone_telli(self.a["id"])
        t2 = self.web.kone_telli(self.a["id"])
        self.web.kone_lopeta(self.a["id"], t1)
        self.assertEqual(self.web.kone_tellijaid(self.a["id"]), 1)
        n = await self.web.kone_publitseeri(self.a["id"], "KÕNE")
        self.assertEqual(n, 1)
        self.assertEqual(t2.get_nowait(), "KÕNE")

    async def test_73_ilma_seadmeid_publitseerimine_ei_viska_erindit(self):
        n = await self.web.kone_publitseeri(self.a["id"], "KÕNE")
        self.assertEqual(n, 0, "tellijaid ei ole, aga publitseeris")

    async def test_74_tais_jarjekord_hoiab_varskeima(self):
        q = self.web.kone_telli(self.a["id"])
        for i in range(60):
            await self.web.kone_publitseeri(self.a["id"], f"kone-{i}")
        # Järjekord on piiratud; vanimad visatakse ära, aga VÄRSKEIM
        # peab alles olema – just see on kasutaja jaoks oluline.
        koik = []
        while not q.empty():
            koik.append(q.get_nowait())
        self.assertIn("kone-59", koik)
        self.assertLessEqual(len(koik), 50)

    async def test_75_proksi_suunab_aktiivse_kasutaja_seadmetele(self):
        t_a = self.web.kone_telli(self.a["id"])
        t_b = self.web.kone_telli(self.b["id"])
        tok = config.sea_aktiivne_kasutaja(self.b["id"])
        try:
            await self.web.call_event_queue.put("BOBI KÕNE")
        finally:
            config.taasta_aktiivne_kasutaja(tok)
        self.assertEqual(t_b.get_nowait(), "BOBI KÕNE")
        with self.assertRaises(asyncio.QueueEmpty):
            t_a.get_nowait()


# =====================================================================
# 5. STAATILINE KONTROLL LÄHTEKOODI VASTU
# =====================================================================
class TestStaatiline(unittest.TestCase):

    def test_40_iga_api_otspunkt_nouab_autentimist(self):
        """AST: iga @app.<meetod>("/api/...") käsitlejal peab olema
        `noua_kasutaja` või `noua_admin` sõltuvus."""
        AVALIKUD = {"/api/auth/register", "/api/auth/login",
                    "/api/auth/status"}
        # CORS-i eelpäring (OPTIONS) EI TOHI autentimist nõuda –
        # brauser ei saada eelpäringuga Authorization päist. Eelpäring
        # ei tagasta ühtegi andmet, ainult lubatud meetodid.
        AVALIKUD_FN = {"options_reminders_handler"}
        puu = ast.parse(WEB_SRC)
        lahti = []
        for n in ast.walk(puu):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            teed = []
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                        and d.args and isinstance(d.args[0], ast.Constant):
                    teed.append(str(d.args[0].value))
            teed = [t for t in teed if t.startswith("/api")]
            if not teed or all(t in AVALIKUD for t in teed):
                continue
            if n.name in AVALIKUD_FN:
                continue
            src = ast.unparse(n.args)
            if "noua_kasutaja" not in src and "noua_admin" not in src:
                lahti.append((teed, n.name))
        self.assertEqual(lahti, [], f"autentimiseta otspunktid: {lahti}")

    def test_41_live_routeri_otspunktid_nouavad_autentimist(self):
        puu = ast.parse(WS_SRC)
        lahti = []
        for n in ast.walk(puu):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                        and getattr(d.func.value, "id", "") == "live_router" \
                        and d.func.attr in ("get", "post", "put", "delete"):
                    if "_noua_kasutaja_ws" not in ast.unparse(n.args):
                        lahti.append(n.name)
        self.assertEqual(lahti, [], f"autentimiseta: {lahti}")

    def test_42_websocket_autendib_ENNE_accept(self):
        i = WS_SRC.index("async def websocket_live_maya(")
        keha = WS_SRC[i:i + 1600]
        j = keha.index("_ws_kasutaja(websocket)")
        k = keha.index("await websocket.accept()")
        self.assertLess(j, k, "accept() enne autentimist")
        self.assertIn("code=1008", keha)

    def test_43_websocket_seab_aktiivse_kasutaja(self):
        i = WS_SRC.index("async def websocket_live_maya(")
        keha = WS_SRC[i:i + 1600]
        # `_cfg` on alias – vt test_43d selgitust varjutuse kohta.
        self.assertIn("_cfg.sea_aktiivne_kasutaja(_kasutaja[\"id\"])", keha)

    def test_43b_ws_eelistab_piletit_tokenile(self):
        """Pilet peab olema kontrollitud ENNE pikaealist tokenit."""
        i = WS_SRC.index("def _ws_kasutaja(")
        keha = WS_SRC[i:i + 2200]
        j = keha.index("kasuta_ws_piletit")
        k = keha.index("kasutaja_tokenist")
        self.assertLess(j, k, "token kontrollitakse enne piletit")
        self.assertIn('query_params.get("ticket")', keha)

    def test_43c_klient_kasutab_piletit_WS_jaoks(self):
        html = (JUUR / "android" / "app" / "src" / "main" / "assets"
                / "index.html").read_text(encoding="utf-8")
        self.assertIn("await MayaAuth.wsUrl(", html)
        self.assertIn("/api/auth/ws_ticket", html)
        # ja pileti päring ise käib PÄISEGA, mitte URL-iga
        i = html.index("async function wsTicket()")
        self.assertIn("headers: headers()", html[i:i + 400])

    def test_43d_config_mooduli_varjutus_ei_korduks(self):
        """MÕÕDETUD VIGA: `websocket_live_maya` sees on lokaalne muutuja
        nimega `config` (Gemini `LiveConnectConfig`). Python teeb selle
        nime kogu funktsiooni ulatuses lokaalseks, nii et mooduli poole
        pöördumine viskab `UnboundLocalError`. See ilmnes alles päris
        WebSocketi ühenduse katsel, mitte ükski varasem test ei
        tabanud seda.

        Funktsiooni sees tohib mooduli poole pöörduda AINULT `_cfg`
        aliasega.
        """
        puu = ast.parse(WS_SRC)
        read = WS_SRC.splitlines()
        fn = None
        for n in ast.walk(puu):
            if isinstance(n, ast.AsyncFunctionDef) and \
                    n.name == "websocket_live_maya":
                fn = n
        self.assertIsNotNone(fn, "websocket_live_maya puudub")
        lo = fn.lineno
        hi = max(getattr(x, "lineno", lo) for x in ast.walk(fn))
        halvad = []
        for i in range(lo - 1, hi):
            r = read[i]
            if r.strip().startswith("#"):
                continue
            if "config." in r and "_cfg." not in r:
                halvad.append(f"{i + 1}: {r.strip()[:60]}")
        self.assertEqual(halvad, [],
                         "varjutatud `config` mooduli kasutus: %s" % halvad)
        # ja alias peab olema olemas
        self.assertIn("import config as _cfg", WS_SRC)

    def test_44_CORS_ei_ole_tahega_koos_credentialsiga(self):
        # KOMMENTAARID VÄLJA: selgitus mainib vana vigast
        # kombinatsiooni just selleks, et öelda, miks seda ei kasutata.
        kood = "\n".join(r for r in WEB_SRC.splitlines()
                         if not r.strip().startswith("#"))
        i = kood.index("app.add_middleware(")
        keha = kood[max(0, i - 400):i + 500]
        self.assertNotIn('allow_origins=["*"]', keha)
        self.assertIn("allow_credentials=False", keha)

    def test_45_paroolid_ei_joua_logidesse(self):
        """Ükski print/log ei tohi paroolivälja välja kirjutada."""
        for src, nimi in ((WEB_SRC, "web_maya"),
                          ((KOOD / "auth.py").read_text(encoding="utf-8"),
                           "auth")):
            for rida in src.splitlines():
                r = rida.strip()
                if r.startswith("#"):
                    continue
                if ("print(" in r or "logging" in r) and "password" in r.lower():
                    self.fail(f"{nimi}: parool võib logisse jõuda: {r[:80]}")

    def test_46_ei_uusi_soltuvusi_autentimiseks(self):
        """Autentimine kasutab ainult standardteeki + FastAPI-t."""
        src = (KOOD / "auth.py").read_text(encoding="utf-8")
        puu = ast.parse(src)
        # Lubatud: Pythoni standardteek + selle projekti ENDA moodulid.
        # Ükski KOLMANDA OSAPOOLE autentimisteek ei tohi siia tulla.
        lubatud = {"hashlib", "hmac", "os", "re", "secrets", "sqlite3",
                   "time", "typing", "__future__",
                   "config", "persona_registry", "listen_direct",
                   "memory_engine", "memory_fts", "user_profile",
                   "init_db"}
        for n in ast.walk(puu):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.assertIn(a.name.split(".")[0], lubatud, a.name)
            elif isinstance(n, ast.ImportFrom) and n.module:
                self.assertIn(n.module.split(".")[0], lubatud, n.module)


# =====================================================================
# 6. KIIRUSPIIRANG
# =====================================================================
class TestKiiruspiirang(unittest.TestCase):

    def test_50_sisselogimise_piirang_peatab_murdmise(self):
        _puhasta_kasutajad()
        auth.loo_kasutaja("alice", "alice-parool-123")
        vigu = 0
        for _ in range(auth.LOGIN_MAX_KATSET + 3):
            try:
                auth.logi_sisse("alice", "vale-parool")
            except auth.AuthViga as e:
                vigu += 1
                if e.kood == 429:
                    break
        else:
            self.fail("kiiruspiirang ei rakendunud")
        self.assertLessEqual(vigu, auth.LOGIN_MAX_KATSET + 1)

    def test_51_api_piirang_libiseva_aknaga(self):
        p = auth.Kiiruspiirang(max_paringut=3, aken_s=60)
        self.assertTrue(all(p.luba("x") for _ in range(3)))
        self.assertFalse(p.luba("x"))
        self.assertTrue(p.luba("teine-kasutaja"), "piirang on globaalne!")


# =====================================================================
# 7. SISENDI VALIDEERIMINE
# =====================================================================
class TestValideerimine(unittest.TestCase):

    def test_60_tekst_loigatakse_ja_juhtmargid_eemaldatakse(self):
        self.assertEqual(auth.puhasta_tekst("abc\x00def"), "abcdef")
        self.assertEqual(auth.puhasta_tekst("rida1\nrida2"), "rida1\nrida2")
        with self.assertRaises(auth.AuthViga):
            auth.puhasta_tekst("x" * 5000, max_pikkus=100)
        with self.assertRaises(auth.AuthViga):
            auth.puhasta_tekst(123)

    def test_61_karakter_peab_registris_olema(self):
        import persona_registry
        self.assertEqual(auth.valideeri_karakter("asjalik"), "asjalik")
        self.assertEqual(auth.valideeri_karakter(""),
                         persona_registry.DEFAULT_PERSONA_ID)
        for paha in ("../../etc/passwd", "DROP TABLE", "olematu"):
            with self.assertRaises(auth.AuthViga, msg=paha):
                auth.valideeri_karakter(paha)

    def test_62_taisarv_vahemikus(self):
        self.assertEqual(auth.valideeri_taisarv("5", 1, 10, "n"), 5)
        for paha in ("x", None, "999", "0"):
            with self.assertRaises(auth.AuthViga):
                auth.valideeri_taisarv(paha, 1, 10, "n")


if __name__ == "__main__":
    print("=" * 70)
    print("MAYA AUTENTIMISE JA ERALDATUSE TESTID")
    print("Andmekaust:", _TMP)
    print("PÄRIS andmeid ega tootmist ei puututa.")
    print("=" * 70)
    unittest.main(verbosity=2)

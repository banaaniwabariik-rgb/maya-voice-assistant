# -*- coding: utf-8 -*-
"""TOOTMISTESTID: faktitasandi privaatsus + kaitsed 1 ja 2.

Kasutab AINULT ajutisi andmebaase. Tootmise reminders.db't ei puudutata.
KÄIVITAMINE: python3 tests_privaatsus_tootmine.py

SÜNTEETILISED ANDMED
--------------------
Kõik siin esinevad „faktid" inimeste kohta (nimed, vara, tervis,
suhted, eelistused) on VÄLJAMÕELDUD testiandmed. Nad ei kirjelda ühtegi
päris inimest ega pärine ühestki päris vestlusest, logist ega
mäluandmebaasist. Näiteisik on „Peeter".
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KOOD = (BASE / "server") if (BASE / "server" / "privacy_scope.py").exists() \
       else BASE
sys.path.insert(0, str(KOOD))
import memory_fts as mf
import privacy_scope as ps


def v(role, text):
    return {"role": role, "text": text}


def f(fid, fact, turn):
    return {"id": fid, "fact": fact, "turn": turn}


def ulatused(r):
    return {d["fact_id"]: d["scope"] for d in r["decisions"]}


# =====================================================================
# 1. OMANIKU PÕHINÄIDE
# =====================================================================
class TestOmanikuNaide(unittest.TestCase):

    def seadista(self, instr="See konkreetne asi jääb meie vahele."):
        turns = [
            v("user", "Mul on tõsine pähkliallergia."),        # 1
            v("assistant", "Panin tähele."),                    # 2
            v("user", "Ma käin psühholoogi juures."),            # 3
            v("assistant", "Kuulan."),                          # 4
            v("user", instr),                                    # 5
            v("user", "Muide, ma ostsin uue auto."),             # 6
        ]
        facts = [
            f(101, "Peetril on tõsine pähkliallergia.", 1),
            f(102, "Jaanus käib psühholoogi juures.", 3),
            f(103, "Jaanus ostis uue auto.", 6),
        ]
        return turns, facts

    def test_01_ainult_vahetult_eelnev_fakt_saab_persona(self):
        turns, facts = self.seadista()
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        u = ulatused(r)
        self.assertEqual(u[102], "persona", r["audit"])
        self.assertEqual(u[101], "shared", "varasem fakt privatiseeriti!")
        self.assertEqual(u[103], "shared", "hilisem fakt privatiseeriti!")

    def test_02_mitteseotud_faktide_pohjus_on_sonaselge(self):
        turns, facts = self.seadista()
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        for d in r["decisions"]:
            if d["fact_id"] != 102:
                self.assertEqual(d["reason"], "not_targeted")
                self.assertIsNone(d["scope_reason"])

    def test_03_audit_ja_scope_reason_sisaldavad_kasutaja_lauset(self):
        turns, facts = self.seadista()
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        a = r["audit"]
        self.assertEqual(a["user_utterance"],
                         "See konkreetne asi jääb meie vahele.")
        self.assertEqual(a["anchor_turn"], 5)
        self.assertEqual(a["target_mode"], "anaphoric")
        self.assertEqual(a["targets"], [102])
        self.assertEqual(sorted(a["left_shared"]), [101, 103])
        siht = [d for d in r["decisions"] if d["fact_id"] == 102][0]
        sr = json.loads(siht["scope_reason"])
        self.assertEqual(sr["anchor_turn"], 5)
        self.assertEqual(sr["utterance"],
                         "See konkreetne asi jääb meie vahele.")
        self.assertTrue(sr["pattern"])
        self.assertEqual(sr["mode"], "anaphoric")


# =====================================================================
# 2. KAITSE 1 — VOORUNUMBRI VALIDEERIMINE
# =====================================================================
class TestKaitse1Voorunumber(unittest.TestCase):
    """Omaniku nõue: number peab viitama OLEMASOLEVALE KASUTAJA voorule –
    mitte Maya vastusele, mitte korraldusele endale, mitte olematule ega
    väljamõeldud indeksile. Kahtluse korral jääb fakt ÜHISEKS."""

    TURNS = [
        v("user", "Ma käin psühholoogi juures."),   # 1
        v("assistant", "Kuulan sind."),             # 2
        v("user", "See jääb meie vahele."),         # 3  <- ankur
    ]

    def abi(self, turn):
        return ps.resolve_fact_scopes(
            self.TURNS, [f(101, "Jaanus käib psühholoogi juures.", turn)],
            "custom")

    def test_04_kehtiv_number_toimib(self):
        self.assertEqual(ulatused(self.abi(1)), {101: "persona"})

    def test_05_maya_voor_lykatakse_tagasi(self):
        r = self.abi(2)
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertIn("invalid_turn:turn_is_not_user",
                      [c[2] for c in r["audit"]["candidates"]])

    def test_06_korraldus_ise_ei_ole_allikas(self):
        r = self.abi(3)
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertIn("invalid_turn:turn_is_the_instruction",
                      [c[2] for c in r["audit"]["candidates"]])

    def test_07_olematu_number(self):
        for halb in (0, -1, 99, 4):
            r = self.abi(halb)
            self.assertEqual(ulatused(r), {101: "shared"}, halb)
            self.assertIn("invalid_turn:turn_out_of_range",
                          [c[2] for c in r["audit"]["candidates"]], halb)

    def test_08_puuduv_voi_vigane_number(self):
        for halb in (None, "", "kolm", "1.5", [], {}):
            r = self.abi(halb)
            self.assertEqual(ulatused(r), {101: "shared"}, repr(halb))

    def test_09_sonena_antud_number_on_lubatud(self):
        """Mudel võib JSON-is anda stringi. See ei ole viga."""
        self.assertEqual(ulatused(self.abi("1")), {101: "persona"})
        self.assertEqual(ulatused(self.abi(" 1 ")), {101: "persona"})

    def test_10_validate_fact_turn_otse(self):
        idx = ps.index_turns(self.TURNS)
        self.assertEqual(ps.validate_fact_turn(1, idx, 3), (True, 1, ""))
        self.assertEqual(ps.validate_fact_turn(2, idx, 3)[2],
                         "turn_is_not_user")
        self.assertEqual(ps.validate_fact_turn(3, idx, 3)[2],
                         "turn_is_the_instruction")
        self.assertEqual(ps.validate_fact_turn(9, idx, 3)[2],
                         "turn_out_of_range")
        self.assertEqual(ps.validate_fact_turn(None, idx, 3)[2],
                         "turn_missing")
        self.assertEqual(ps.validate_fact_turn("x", idx, 3)[2],
                         "turn_not_an_integer")

    def test_11_tyhi_voor_ei_kolbu(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "   "),
                 v("user", "See jääb meie vahele.")]
        r = ps.resolve_fact_scopes(turns, [f(101, "Miski.", 2)], "custom")
        self.assertEqual(ulatused(r), {101: "shared"})


# =====================================================================
# 3. KAITSE 2 — scope='private' PEAB OLEMA KÄSITLETUD
# =====================================================================
class TestKaitse2PrivateUlatus(unittest.TestCase):
    """MÕÕDETUD AUK: scope='private' + persona IS NULL salvestus, aga ei
    olnud ÜHEGI päringuteega leitav – kirjuta-ainult."""

    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.conn = sqlite3.connect(self.db)
        mf.ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db):
            os.unlink(self.db)

    def lisa(self, fakt, persona, scope, reason=None):
        return mf.upsert_fact(self.conn, fakt, category="muu",
                              confidence=0.9, source="test",
                              persona=persona, scope=scope,
                              scope_reason=reason)

    def test_12_scope_reason_veerg_on_olemas(self):
        veerud = {r[1] for r in self.conn.execute("PRAGMA table_info(memory)")}
        self.assertIn("scope_reason", veerud)

    def test_13_scope_reason_salvestub_ainult_mitte_uhisele(self):
        self.lisa("Peetril on ühine asi.", None, "shared", "EI TOHI SALVESTUDA")
        self.lisa("Peetril on karakteri asi.", "custom", "persona", '{"x":1}')
        r = dict(self.conn.execute(
            "SELECT scope, scope_reason FROM memory").fetchall())
        self.assertIsNone(r["shared"], "ühisele kirjutati põhjus")
        self.assertEqual(r["persona"], '{"x":1}')

    def test_14_private_ei_jou_promptisse(self):
        self.lisa("Peetril on ühine asi.", None, "shared")
        self.lisa("Peetri vanaema kudus sokke.", None, "private")
        self.lisa("Peetril on salajane asi.", "custom", "private")
        for per in ("custom", "sarkastiline", ""):
            faktid = mf.facts_for_prompt(self.conn, per)
            for x in faktid:
                self.assertNotIn("vanaema", x, per)
                self.assertNotIn("salajane", x, per)

    def test_15_private_persona_ga_on_leitav_recall_kaudu(self):
        self.lisa("Peetril on salajane asi.", "custom", "private")
        h = mf.search_facts(self.conn, "salajane", persona="custom",
                            include_private=True)
        self.assertTrue(any("salajane" in str(x.get("fact", x)) for x in h), h)

    def test_16_ORB_private_ilma_persona_on_leitav(self):
        """SEE ON PARANDUS. Enne seda oli rida kirjuta-ainult."""
        self.lisa("Peetri vanaema kudus villaseid sokke.", None, "private")
        h = mf.search_facts(self.conn, "vanaema sokid", persona="custom",
                            include_private=True)
        self.assertTrue(any("vanaema" in str(x.get("fact", x)) for x in h),
                        "orvuks jäänud private rida ei ole leitav: %s" % h)

    def test_17_orb_ei_lekki_ilma_include_private(self):
        self.lisa("Peetri vanaema kudus villaseid sokke.", None, "private")
        h = mf.search_facts(self.conn, "vanaema sokid", persona="custom")
        self.assertFalse(any("vanaema" in str(x.get("fact", x)) for x in h),
                         "private lekkis tavaotsingusse")

    def test_18_teise_karakteri_persona_fakt_ei_lekki(self):
        self.lisa("Peetril on salajane asi.", "custom", "private")
        h = mf.search_facts(self.conn, "salajane", persona="sarkastiline",
                            include_private=True)
        self.assertFalse(any("salajane" in str(x.get("fact", x)) for x in h))

    def test_19_resolve_scope_koosmoju_salvestusega(self):
        """Terviktee: otsus -> upsert -> nähtavus."""
        per, scope = mf.resolve_scope("custom", "suhe", True,
                                      {"private": True})
        self.assertEqual((per, scope), ("custom", "persona"))
        self.lisa("Peetril on Mayaga eriline asi.", per, scope, '{"a":1}')
        self.assertTrue(mf.facts_for_prompt(self.conn, "custom"))
        self.assertFalse(mf.facts_for_prompt(self.conn, "mentor"))


# =====================================================================
# 4. MUDELI VÄIDE EI LOE
# =====================================================================
class TestMudeliVaide(unittest.TestCase):

    def test_20_maya_lause_ei_tekita_privaatsust(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("assistant", "Ära muretse, see jääb meie vahele.")]
        r = ps.resolve_fact_scopes(
            turns, [f(101, "Jaanus käib psühholoogi juures.", 1)], "custom")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertEqual(r["audit"]["reject_reason"], "no_privacy_request")

    def test_21_mudeli_vaide_ei_piisa(self):
        turns = [v("user", "Ma käin psühholoogi juures.")]
        r = ps.resolve_fact_scopes(
            turns, [f(101, "Jaanus käib psühholoogi juures.", 1)], "custom",
            model_claim={"private": True, "reason": "tundlik teema"})
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertTrue(r["audit"]["model_claim"])
        self.assertFalse(r["audit"]["model_claim_honoured"])
        self.assertIn("väide eiratud", " ".join(r["audit"]["notes"]))

    def test_22_fakti_enda_tekst_ei_ole_korraldus(self):
        turns = [v("user", "Ma käin psühholoogi juures.")]
        r = ps.resolve_fact_scopes(
            turns, [f(101, "Jaanus ütles, et see jääb meie vahele.", 1)],
            "custom")
        self.assertEqual(ulatused(r), {101: "shared"})

    def test_23_tyhi_transkriptsioon(self):
        r = ps.resolve_fact_scopes([], [f(101, "Peetril on kass.", 1)],
                                   "custom")
        self.assertEqual(ulatused(r), {101: "shared"})


# =====================================================================
# 5. SIHTMÄRGI TUVASTAMINE
# =====================================================================
class TestSihtmark(unittest.TestCase):

    def test_24_nimetatud_sisu_tabab_oige_fakti(self):
        turns = [
            v("user", "Mul on pähkliallergia."),
            v("user", "Ma käin psühholoogi juures."),
            v("user", "Ma kaalun 66 kilo."),
            v("user", "Ära räägi teistele sellest, et ma käin "
                      "psühholoogi juures."),
        ]
        facts = [f(101, "Peetril on pähkliallergia.", 1),
                 f(102, "Jaanus käib psühholoogi juures.", 2),
                 f(103, "Jaanus kaalub 66 kg.", 3)]
        r = ps.resolve_fact_scopes(turns, facts, "mentor")
        self.assertEqual(r["audit"]["target_mode"], "explicit")
        self.assertEqual(ulatused(r),
                         {101: "shared", 102: "persona", 103: "shared"})

    def test_25_nimetatud_sisu_valjaspool_fakte(self):
        turns = [v("user", "Ma kaalun 66 kilo."),
                 v("user", "Ära räägi teistele sellest, et mu vend istus "
                           "vangis.")]
        r = ps.resolve_fact_scopes(turns, [f(101, "Jaanus kaalub 66 kg.", 1)],
                                   "custom")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertTrue(r["needs_clarification"])
        self.assertEqual(r["audit"]["resolution"],
                         "no_match_above_threshold")

    def test_26_kass_kassett_loks(self):
        turns = [v("user", "Mul on kass."),
                 v("user", "Ära jaga seda, et mul on kassett autos.")]
        r = ps.resolve_fact_scopes(turns, [f(101, "Peetril on kass.", 1)],
                                   "custom")
        self.assertEqual(ulatused(r), {101: "shared"}, r["audit"])


# =====================================================================
# 6. MITMETIMÕISTETAVUS -> ÜHINE
# =====================================================================
class TestMitmetimoistetavus(unittest.TestCase):

    def test_27_kaks_fakti_samast_voorust_ei_oleta(self):
        turns = [v("user", "Ma käin psühholoogi juures ja olen palju joonud."),
                 v("user", "See jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus on palju joonud.", 1)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "shared", 102: "shared"})
        self.assertTrue(r["needs_clarification"])
        self.assertEqual(r["audit"]["resolution"],
                         "ambiguous_multiple_in_window")

    def test_28_kysimus_nimetab_molemad_kandidaadid(self):
        turns = [v("user", "Ma käin psühholoogi juures ja olen palju joonud."),
                 v("user", "See jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus on palju joonud.", 1)]
        k = ps.resolve_fact_scopes(turns, facts, "custom")["clarify_question"]
        self.assertIn("psühholoogi", k)
        self.assertIn("joonud", k)
        self.assertTrue(k.rstrip().endswith("?"), k)

    def test_29_vorreldav_sisukattuvus_ei_oleta(self):
        turns = [v("user", "Mul on Sony kõrvaklapid."),
                 v("user", "Mul on ka Sony telefon."),
                 v("user", "Ära jaga seda, et mul on Sony.")]
        facts = [f(101, "Peetril on Sony kõrvaklapid.", 1),
                 f(102, "Peetril on Sony telefon.", 2)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "shared", 102: "shared"})
        self.assertIn(r["audit"]["resolution"],
                      ("ambiguous_tie", "no_match_above_threshold"))

    def test_30_tyhi_faktinimekiri_ei_kuku_kokku(self):
        turns = [v("user", "See jääb meie vahele.")]
        r = ps.resolve_fact_scopes(turns, [], "custom")
        self.assertEqual(r["decisions"], [])
        self.assertTrue(r["needs_clarification"])


# =====================================================================
# 7. AJALINE SUUND
# =====================================================================
class TestAjalineSuund(unittest.TestCase):

    def test_31_hilisem_fakt_jaab_uhiseks(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "See jääb meie vahele."),
                 v("user", "Ma ostsin uue auto.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus ostis uue auto.", 3)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "persona", 102: "shared"})
        self.assertIn("after_instruction",
                      [c[2] for c in r["audit"]["candidates"]])

    def test_32_korraldus_ei_ole_pysiv_lipp(self):
        turns = [v("user", "Ma käin psühholoogi juures.")]
        r = ps.resolve_fact_scopes(
            turns, [f(101, "Jaanus käib psühholoogi juures.", 1)], "custom")
        self.assertEqual(ulatused(r), {101: "shared"})

    def test_33_juba_kasutatud_korraldust_ei_rakendata_uuesti(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "See jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1)]
        self.assertEqual(ulatused(ps.resolve_fact_scopes(turns, facts,
                                                         "custom")),
                         {101: "persona"})
        r2 = ps.resolve_fact_scopes(turns, facts, "custom",
                                    used_turn_ns={2})
        self.assertEqual(ulatused(r2), {101: "shared"})

    def test_34_aknast_valjas_fakt_ei_kolbu(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "Mul on kass."),
                 v("user", "See jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertEqual(r["audit"]["resolution"], "no_fact_in_window")

    def test_35_viimane_korraldus_voidab(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "See jääb meie vahele."),
                 v("user", "Ma olen palju joonud."),
                 v("user", "Ja see jääb ka meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus on palju joonud.", 3)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(r["audit"]["anchor_turn"], 4)
        self.assertEqual(ulatused(r), {101: "shared", 102: "persona"})


# =====================================================================
# 8. VAIKIMISI ÜHINE + VÄLISTAVAD VORMID
# =====================================================================
class TestVaikimisiYhine(unittest.TestCase):

    def test_36_tundlikkus_ei_tekita_privaatsust(self):
        for tekst, fakt in (
            ("Ma käin psühholoogi juures.", "Jaanus käib psühholoogi juures."),
            ("Ma olen palju joonud.", "Jaanus on palju joonud."),
            ("Mul on kõrge kolesterool.", "Peetril on kõrge kolesterool."),
            ("Mul on Mayaga intiimne suhe.",
             "Peetril on Mayaga intiimne suhe."),
            ("Mulle meeldiks Mayale oraalseksi teha.",
             "Peetrile meeldiks Mayale oraalseksi teha."),
        ):
            r = ps.resolve_fact_scopes([v("user", tekst)], [f(101, fakt, 1)],
                                       "custom")
            self.assertEqual(ulatused(r), {101: "shared"}, tekst)

    def test_37_see_on_isiklik_ei_ole_korraldus(self):
        r = ps.resolve_fact_scopes(
            [v("user", "See on üsna isiklik teema minu jaoks.")],
            [f(101, "Peetril on isiklik teema.", 1)], "custom")
        self.assertEqual(ulatused(r), {101: "shared"})


class TestValistavadVormid(unittest.TestCase):

    def abi(self, tekst):
        turns = [v("user", "Ma käin psühholoogi juures."), v("user", tekst)]
        return ps.resolve_fact_scopes(
            turns, [f(101, "Jaanus käib psühholoogi juures.", 1)], "custom")

    def test_38_tsitaat(self):
        r = self.abi("Ma ütlesin eile, et ära seda jaga, aga sa jagasid.")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertEqual(r["audit"]["reject_reason"],
                         "quoted_not_instruction")

    def test_39_maya_pakkus(self):
        self.assertEqual(
            ulatused(self.abi("Sa pakkusid, et ära seda jaga teistega.")),
            {101: "shared"})

    def test_40_tingiv_konevis(self):
        r = self.abi("Ma paluksin, et sa seda ei jagaks teistega.")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertEqual(r["audit"]["reject_reason"],
                         "conditional_not_instruction")

    def test_41_kusimus(self):
        self.assertEqual(
            ulatused(self.abi("Kas sa jagad seda teistele karakteritele?")),
            {101: "shared"})

    def test_42_tyhistatud_korraldus(self):
        r = self.abi("Ära seda jaga... ah, pole saladus, võid rääkida.")
        self.assertEqual(ulatused(r), {101: "shared"})
        self.assertEqual(r["audit"]["reject_reason"], "privacy_revoked")

    def test_43_hypoteetiline(self):
        self.assertEqual(
            ulatused(self.abi("Kujuta ette, kui ma ütleksin, et ära seda jaga.")),
            {101: "shared"})


# =====================================================================
# 9. SÕNASELGELT LAI ULATUS
# =====================================================================
class TestLaiUlatus(unittest.TestCase):

    def test_44_kogu_tanane_jutt(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "Ma olen palju joonud."),
                 v("user", "Kogu see tänane jutt jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus on palju joonud.", 2)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "persona", 102: "persona"})
        self.assertEqual(r["audit"]["target_mode"], "session_wide")
        self.assertFalse(r["needs_clarification"])

    def test_45_kitsas_sonastus_EI_ole_lai(self):
        turns = [v("user", "Ma käin psühholoogi juures."),
                 v("user", "Ma olen palju joonud."),
                 v("user", "See jääb meie vahele.")]
        facts = [f(101, "Jaanus käib psühholoogi juures.", 1),
                 f(102, "Jaanus on palju joonud.", 2)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertNotEqual(r["audit"]["target_mode"], "session_wide")
        self.assertEqual(ulatused(r)[101], "shared")
        self.assertEqual(ulatused(r)[102], "persona")

    def test_46_lai_ulatus_ei_vota_vigase_vooruga_fakti(self):
        turns = [v("user", "Ma olen palju joonud."),
                 v("user", "Kogu see vestlus jääb meie vahele.")]
        facts = [f(101, "Jaanus on palju joonud.", 1),
                 f(102, "Vale number.", 77)]
        r = ps.resolve_fact_scopes(turns, facts, "custom")
        self.assertEqual(ulatused(r), {101: "persona", 102: "shared"})


# =====================================================================
# 10. EESTI SÕNASTUSED
# =====================================================================
class TestEestiVormid(unittest.TestCase):

    SONASTUSED = [
        "Ära seda jaga teiste karakteritega.",
        "Ära teistele räägi sellest.",
        "See jääb ainult meie vahele.",
        "Las see jääb sinu ja minu vahele.",
        "Ära seda salvesta ühisesse mällu.",
        "Teised karakterid ei pea seda teadma.",
        "Hoia see endale, palun.",
        "Ainult sina tead seda.",
        "Palun, et sa seda teistele ei räägi.",
        "Ära seda teistele maini.",
    ]

    def test_47_koik_sonastused_tuvastuvad(self):
        puudu = []
        for s in self.SONASTUSED:
            turns = [v("user", "Ma käin psühholoogi juures."), v("user", s)]
            r = ps.resolve_fact_scopes(
                turns, [f(101, "Jaanus käib psühholoogi juures.", 1)],
                "custom")
            if ulatused(r).get(101) != "persona":
                puudu.append((s, r["audit"].get("reject_reason")
                              or r["audit"].get("resolution")))
        self.assertEqual(puudu, [], "tuvastamata: %s" % puudu)


# =====================================================================
# 11. NUMMERDATUD TRANSKRIPTSIOON
# =====================================================================
class TestNummerdatudTranskriptsioon(unittest.TestCase):

    def test_48_numbrid_algavad_uhest_ja_on_jarjest(self):
        turns = [v("user", "Tere."), v("assistant", "Tere ka."),
                 v("user", "Mul on kass.")]
        t = ps.numbered_transcript(ps.index_turns(turns), "Jaanus")
        self.assertEqual(t.split("\n"),
                         ["1. Jaanus: Tere.", "2. Maya: Tere ka.",
                          "3. Jaanus: Mul on kass."])

    def test_49_indeks_vastab_transkriptsioonile(self):
        turns = [v("user", "A."), v("assistant", "B."), v("user", "C.")]
        idx = ps.index_turns(turns)
        self.assertEqual([(x["n"], x["role"]) for x in idx],
                         [(1, "user"), (2, "assistant"), (3, "user")])


if __name__ == "__main__":
    unittest.main(verbosity=2)

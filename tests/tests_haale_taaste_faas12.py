# -*- coding: utf-8 -*-
"""FAAS 1 + 2 TESTID: diagnostika ja PASSIIVNE katkestuste liigitus.

Mõlemad faasid on AINULT VAATLEVAD. Need testid kontrollivad ka seda –
et kood ei saaks vaikselt tegutsemisele üle minna.

MIKS LÄHTEKOODIST, MITTE IMPORDIGA
----------------------------------
`live_maya_ws.py` impordib `google.genai`, mida arendusmasinas ei ole.
Sama lahendust kasutab juba `tests_konevoor.py`: klass ja puhtad
funktsioonid loetakse lähtekoodist välja ja käivitatakse isoleeritud
nimeruumis. Nii testitakse PÄRIS tootmiskoodi, mitte koopiat.

KÄIVITAMINE: python3 tests_haale_taaste_faas12.py
"""

import ast
import sys
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KOOD = (BASE / "server") if (BASE / "server" / "live_maya_ws.py").exists() else BASE
SRC = (KOOD / "live_maya_ws.py").read_text(encoding="utf-8")


def _lõika(nimed):
    """Toob nimetatud mooduli tasemel definitsioonid isoleeritud ruumi."""
    puu = ast.parse(SRC)
    valitud = []
    for n in puu.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.name in nimed:
                valitud.append(n)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in nimed:
                    valitud.append(n)
    moodul = ast.Module(body=valitud, type_ignores=[])
    ruum = {"time": time, "__name__": "isoleeritud"}
    exec(compile(moodul, "<live_maya_ws>", "exec"), ruum)
    return ruum


NS = _lõika({
    "SpeechTurn", "classify_turn_end", "TERMINAL_PUNCT",
    "SILENCE_OBSERVATION_MARKS_S", "SILENCE_OBSERVER_INTERVAL_S",
    "CHARS_PER_S_CUTOFF",
})
SpeechTurn = NS["SpeechTurn"]
classify = NS["classify_turn_end"]


def voor(turn_id=1, persona="asjalik", t0=1000.0):
    return SpeechTurn(turn_id, persona, t0)


# =====================================================================
# FAAS 1 — DIAGNOSTIKA
# =====================================================================
class TestTykkidePausid(unittest.TestCase):
    """max_gap_s on STALL_S tuletamise ainus alus."""

    def test_01_esimene_tykk_ei_tekita_pausi(self):
        t = voor()
        t.note_audio(4800, 1000.5)
        self.assertEqual(t.gap_count, 0)
        self.assertEqual(t.max_gap_s, 0.0)

    def test_02_paus_moodetakse_tapselt(self):
        t = voor()
        t.note_audio(4800, 1000.0)
        t.note_audio(4800, 1000.043)      # Gemini tüüpiline 43 ms tükk
        t.note_audio(4800, 1000.086)
        self.assertEqual(t.gap_count, 2)
        self.assertAlmostEqual(t.max_gap_s, 0.043, places=3)

    def test_03_pikim_paus_jääb_meelde(self):
        t = voor()
        for ts in (1000.0, 1000.04, 1001.90, 1001.94):
            t.note_audio(4800, ts)
        self.assertAlmostEqual(t.max_gap_s, 1.86, places=2)
        self.assertEqual(t.gap_count, 3)

    def test_04_keskmine_paus(self):
        t = voor()
        for ts in (1000.0, 1000.10, 1000.20, 1000.30):
            t.note_audio(4800, ts)
        d = t.diag_dict(1000.30)
        self.assertAlmostEqual(d["mean_gap_s"], 0.1, places=2)

    def test_05_keskmine_on_None_kui_pause_ei_ole(self):
        t = voor()
        t.note_audio(4800, 1000.0)
        self.assertIsNone(t.diag_dict(1000.0)["mean_gap_s"])


class TestEsimeseHeliLatentsus(unittest.TestCase):

    def test_06_latentsus_moodetakse_vooru_algusest(self):
        t = voor(t0=1000.0)
        t.note_audio(4800, 1000.740)
        self.assertAlmostEqual(t.first_audio_latency_s, 0.740, places=3)

    def test_07_latentsus_ei_muutu_hilisemate_tykkidega(self):
        t = voor(t0=1000.0)
        t.note_audio(4800, 1000.740)
        t.note_audio(4800, 1003.000)
        self.assertAlmostEqual(t.first_audio_latency_s, 0.740, places=3)

    def test_08_latentsus_on_None_kui_heli_ei_tulnud(self):
        self.assertIsNone(voor().diag_dict(1000.0)["first_audio_latency_s"])


class TestVaikuseMootmine(unittest.TestCase):

    def test_09_vaikus_null_kui_heli_pole_alanud(self):
        self.assertEqual(voor().silence_s(1005.0), 0.0)

    def test_10_vaikus_viimasest_tykist(self):
        t = voor()
        t.note_audio(4800, 1000.0)
        self.assertAlmostEqual(t.silence_s(1003.5), 3.5, places=3)

    def test_11_vaikus_ei_ole_negatiivne(self):
        t = voor()
        t.note_audio(4800, 1005.0)
        self.assertEqual(t.silence_s(1000.0), 0.0)


class TestHinnanguliseVaruArvutus(unittest.TestCase):
    """est_lead_s on HINNANG. Testid kinnitavad valemit, mitte täpsust."""

    def test_12_server_ette_jooksmine_annab_varu(self):
        # 2 s heli saadetud, kulunud 0,5 s -> ~1,5 s + värinapuhver
        t = voor()
        t.note_audio(int(24000 * 2 * 2.0), 1000.0)
        self.assertAlmostEqual(t.est_lead_s(1000.5), 1.8, places=2)

    def test_13_reaalajas_jooksmine_annab_varuks_puhvri(self):
        t = voor()
        t.note_audio(int(24000 * 2 * 1.0), 1000.0)
        self.assertAlmostEqual(t.est_lead_s(1001.0), 0.30, places=2)

    def test_14_varu_ei_lahe_negatiivseks(self):
        t = voor()
        t.note_audio(int(24000 * 2 * 1.0), 1000.0)
        self.assertEqual(t.est_lead_s(1010.0), 0.0)

    def test_15_varu_null_kui_heli_pole_alanud(self):
        self.assertEqual(voor().est_lead_s(1000.0), 0.0)

    def test_16_puhvri_suurus_on_parameeter(self):
        """Kliendi JITTER_BUFFER_S on 0,30. Kui see muutub, peab hinnang
        muutuma koos sellega – seepärast on see argument."""
        t = voor()
        t.note_audio(int(24000 * 2 * 1.0), 1000.0)
        self.assertAlmostEqual(t.est_lead_s(1001.0, jitter_s=0.5), 0.5, places=2)


class TestSignaalilipud(unittest.TestCase):
    """Rippuva genereerimise tunnus on saw_turn_complete == False."""

    def test_17_lipud_algavad_vaarana(self):
        t = voor()
        self.assertFalse(t.saw_turn_complete)
        self.assertFalse(t.saw_interrupted)
        self.assertFalse(t.saw_generation_complete)

    def test_18_lipud_jouavad_diagnostikasse(self):
        t = voor()
        t.saw_turn_complete = True
        t.saw_generation_complete = True
        d = t.diag_dict(1000.0)
        self.assertTrue(d["saw_turn_complete"])
        self.assertTrue(d["saw_generation_complete"])
        self.assertFalse(d["saw_interrupted"])


class TestDiagnostikaOnSISUTA(unittest.TestCase):
    """Omaniku nõue 6: vestluse teksti ei tohi logida."""

    def test_19_teksti_ei_ole_diagnostikas(self):
        t = voor()
        saladus = "Mulle meeldiks sinuga midagi väga isiklikku teha"
        t.note_text(saladus)
        t.note_audio(int(24000 * 2 * 4.0), 1000.0)
        d = t.diag_dict(1000.0)
        tekstina = repr(d)
        for sõna in saladus.split():
            self.assertNotIn(sõna, tekstina,
                             f"diagnostika lekitas sõna {sõna!r}")

    def test_20_ainult_pikkus_ja_lopumark(self):
        t = voor()
        t.note_text("Tere, kuidas läheb?")
        d = t.diag_dict(1000.0)
        self.assertEqual(d["tail_len"], len("Tere, kuidas läheb?"))
        self.assertTrue(d["tail_is_terminal"])

    def test_21_koik_valjad_on_primitiivid(self):
        """Kui keegi lisab hiljem tekstivälja, kukub see test läbi."""
        t = voor()
        t.note_text("midagi")
        t.note_audio(4800, 1000.0)
        for k, v in t.diag_dict(1000.5).items():
            self.assertIsInstance(
                v, (int, float, bool, type(None), str), k)
            if isinstance(v, str):
                # Lubatud stringid on AINULT loetelud, mitte vestlus.
                self.assertIn(k, ("persona", "state", "interrupt_reason",
                                  "failure_reason"), f"{k} on string: {v!r}")


# =====================================================================
# FAAS 2 — LIIGITUS A–H
# =====================================================================
class TestLiigitusA_LoomulikLopp(unittest.TestCase):

    def test_22_lausemargiga_lopp(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=True, chars_per_audio_s=12.9,
                     audio_s=5.0, silence_s=0.1)
        self.assertEqual(r["class"], "A")
        self.assertFalse(r["continue_appropriate"])

    def test_23_ilma_lausemarki_annab_nuud_D_ka_madala_suhtarvuga(self):
        """MUUDETUD 10.11.2026 tootmistesti põhjal.

        Varem ootas see test klassi A ("transkriptsioon jäi maha").
        Filosoofi testis liigitas see KÕIK VIIS päriselt poolelijäänud
        vooru valesti – suhtarv 9,0–10,2 on filosoofi NORMAALNE tempo.
        Suhtarv on nüüd ainult diagnostika."""
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=6.0,
                     audio_s=8.0, silence_s=0.1, tail_len=48)
        self.assertEqual(r["class"], "D")
        self.assertTrue(r["continue_appropriate"])

    def test_24_A_EI_TOHI_KUNAGI_jatkata(self):
        for term in (True, False):
            for cps in (0.0, 5.0, 9.9):
                r = classify(saw_turn_complete=True, saw_interrupted=False,
                             tail_is_terminal=term, chars_per_audio_s=cps,
                             audio_s=5.0, silence_s=0.0, tail_len=40)
                if r["class"] == "A":
                    self.assertFalse(r["continue_appropriate"])


class TestLiigitusB_KasutajaSegas(unittest.TestCase):

    def test_25_katkestus_pluss_kasutaja_kone(self):
        r = classify(saw_turn_complete=False, saw_interrupted=True,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=0.2, user_speech_within_s=1.4)
        self.assertEqual(r["class"], "B")
        self.assertFalse(r["continue_appropriate"])

    def test_26_B_EI_TOHI_KUNAGI_jatkata(self):
        for v in (0.0, 0.5, 2.0, 5.0):
            r = classify(saw_turn_complete=False, saw_interrupted=True,
                         tail_is_terminal=False, chars_per_audio_s=11.0,
                         audio_s=3.0, silence_s=0.2, user_speech_within_s=v)
            self.assertEqual(r["class"], "B", v)
            self.assertFalse(r["continue_appropriate"], v)

    def test_27_kone_liiga_hilja_ei_ole_B(self):
        r = classify(saw_turn_complete=False, saw_interrupted=True,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=6.0, user_speech_within_s=7.0)
        self.assertNotEqual(r["class"], "B")
        self.assertFalse(r["continue_appropriate"])

    def test_28_katkestus_ILMA_kasutaja_konet_on_H_mitte_C(self):
        """KRIITILINE. Kaja käivitas VAD-i -> katkestus ilma kasutaja kõnet.
        Kui see liigituks C-ks, jätkaks faas 3 kasutaja tahtliku
        vahelesegamise peale."""
        r = classify(saw_turn_complete=False, saw_interrupted=True,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=2.0, user_speech_within_s=None,
                     stall_s=1.0)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "interrupted_without_user_speech")
        self.assertFalse(r["continue_appropriate"])


class TestLiigitusC_MudelPeatus(unittest.TestCase):

    def test_29_ilma_moodetud_lavendit_on_H(self):
        """Omaniku nõue 5: oletatud ajalävendit ei tohi koodis olla."""
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=12.0, stall_s=None)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "stall_threshold_unmeasured")
        self.assertFalse(r["continue_appropriate"])

    def test_30_moodetud_lavendiga_on_C(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=5.0, stall_s=2.0)
        self.assertEqual(r["class"], "C")
        self.assertTrue(r["continue_appropriate"])

    def test_31_lavendi_all_on_H(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=1.0, stall_s=2.0)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "below_stall_threshold")

    def test_32_ilma_heli_ei_ole_C(self):
        """Heli ei alanud -> tühi voor, millel on juba oma tee."""
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=0.0,
                     audio_s=0.0, silence_s=9.0, stall_s=2.0)
        self.assertEqual(r["class"], "H")


class TestLiigitusD_EnneaegneTurnComplete(unittest.TestCase):

    def test_33_poolik_lause_korge_suhtarv(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=12.9,
                     audio_s=6.0, silence_s=0.1)
        self.assertEqual(r["class"], "D")
        self.assertTrue(r["continue_appropriate"])

    def test_34_lavendi_piiril(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False,
                     chars_per_audio_s=NS["CHARS_PER_S_CUTOFF"],
                     audio_s=6.0, silence_s=0.1)
        self.assertEqual(r["class"], "D")

    def test_35_liiga_vahe_heli_ei_otsusta(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=50.0,
                     audio_s=0.3, silence_s=0.1)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "too_little_audio_to_judge")

    def test_36_lavend_EI_MOJUTA_enam_otsust(self):
        """MUUDETUD: `chars_cutoff` jäi signatuuri ühilduvuse pärast, aga
        teda EI LOETA. Ükskõik mis lävend, tulemus on sama."""
        for cutoff in (0.0, 10.5, 20.0, 1000.0):
            r = classify(saw_turn_complete=True, saw_interrupted=False,
                         tail_is_terminal=False, chars_per_audio_s=11.0,
                         audio_s=6.0, silence_s=0.1, tail_len=66,
                         chars_cutoff=cutoff)
            self.assertEqual(r["class"], "D", cutoff)

    def test_37_margib_et_suhtarv_on_AINULT_diagnostika(self):
        """MUUDETUD: varem märkis ta lävendi eraldusvõime nõrkuse. Nüüd
        peab ta ütlema välja, et suhtarv otsust EI MÕJUTA."""
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=12.9,
                     audio_s=6.0, silence_s=0.1, tail_len=77)
        self.assertTrue(any("AINULT diagnostika" in n for n in r["notes"]),
                        r["notes"])


class TestLiigitusEFGH(unittest.TestCase):

    def test_38_transport_domineerib(self):
        r = classify(saw_turn_complete=True, saw_interrupted=True,
                     tail_is_terminal=True, chars_per_audio_s=12.0,
                     audio_s=5.0, silence_s=0.0, close_code=1007)
        self.assertEqual(r["class"], "F")
        self.assertFalse(r["continue_appropriate"])

    def test_39_failure_reason_annab_F(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=0.0,
                     audio_s=0.0, silence_s=0.0,
                     failure_reason="generation_stall")
        self.assertEqual(r["class"], "F")

    def test_40_E_ei_vali_ennast_ise(self):
        """Turvapoolset signaali ei ole – E ei tohi tekkida juhuslikult."""
        klassid = set()
        for tc in (True, False):
            for it in (True, False):
                for term in (True, False):
                    r = classify(saw_turn_complete=tc, saw_interrupted=it,
                                 tail_is_terminal=term,
                                 chars_per_audio_s=12.0, audio_s=5.0,
                                 silence_s=3.0, stall_s=2.0)
                    klassid.add(r["class"])
        self.assertNotIn("E", klassid)
        self.assertNotIn("G", klassid)

    def test_41_E_valitakse_ainult_selgesonalise_signaaliga(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=0.0,
                     audio_s=1.0, silence_s=1.0,
                     safety_signal="SAFETY")
        self.assertEqual(r["class"], "E")
        self.assertFalse(r["continue_appropriate"])

    def test_42_G_valitakse_ainult_kliendi_raportiga(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=True, chars_per_audio_s=12.0,
                     audio_s=5.0, silence_s=0.0,
                     client_report={"playback_failed": True})
        self.assertEqual(r["class"], "G")
        self.assertFalse(r["continue_appropriate"])

    def test_43_koik_kaheksa_klassi_on_saavutatavad(self):
        juhud = {
            "A": dict(saw_turn_complete=True, saw_interrupted=False,
                      tail_is_terminal=True, chars_per_audio_s=12.0,
                      audio_s=5.0, silence_s=0.0),
            "B": dict(saw_turn_complete=False, saw_interrupted=True,
                      tail_is_terminal=False, chars_per_audio_s=11.0,
                      audio_s=3.0, silence_s=0.2, user_speech_within_s=1.0),
            "C": dict(saw_turn_complete=False, saw_interrupted=False,
                      tail_is_terminal=False, chars_per_audio_s=11.0,
                      audio_s=3.0, silence_s=5.0, stall_s=2.0),
            "D": dict(saw_turn_complete=True, saw_interrupted=False,
                      tail_is_terminal=False, chars_per_audio_s=12.9,
                      audio_s=6.0, silence_s=0.1),
            "E": dict(saw_turn_complete=False, saw_interrupted=False,
                      tail_is_terminal=False, chars_per_audio_s=0.0,
                      audio_s=1.0, silence_s=1.0, safety_signal="SAFETY"),
            "F": dict(saw_turn_complete=False, saw_interrupted=False,
                      tail_is_terminal=False, chars_per_audio_s=0.0,
                      audio_s=0.0, silence_s=0.0, close_code=1011),
            "G": dict(saw_turn_complete=True, saw_interrupted=False,
                      tail_is_terminal=True, chars_per_audio_s=12.0,
                      audio_s=5.0, silence_s=0.0,
                      client_report={"playback_failed": True}),
            "H": dict(saw_turn_complete=False, saw_interrupted=False,
                      tail_is_terminal=False, chars_per_audio_s=11.0,
                      audio_s=3.0, silence_s=9.0, stall_s=None),
        }
        for oodatud, kw in juhud.items():
            self.assertEqual(classify(**kw)["class"], oodatud, oodatud)

    def test_44_ainult_C_ja_D_lubavad_jatkamist(self):
        """Kogu faasi 3 ohutus toetub sellele."""
        lubavad = set()
        for v in (True, False):
            for w in (True, False):
                for term in (True, False):
                    for cps in (0.0, 6.0, 12.9):
                        for sil in (0.0, 1.0, 9.0):
                            for st in (None, 2.0):
                                for usw in (None, 1.0):
                                    r = classify(
                                        saw_turn_complete=v,
                                        saw_interrupted=w,
                                        tail_is_terminal=term,
                                        chars_per_audio_s=cps,
                                        audio_s=5.0, silence_s=sil,
                                        stall_s=st,
                                        user_speech_within_s=usw)
                                    if r["continue_appropriate"]:
                                        lubavad.add(r["class"])
        self.assertEqual(lubavad, {"C", "D"},
                         f"jätkamist lubavad klassid: {lubavad}")


# =====================================================================
# STAATILISED KONTROLLID: FAASID PEAVAD JÄÄMA PASSIIVSEKS
# =====================================================================
class TestPassiivsus(unittest.TestCase):

    def test_45_vaatleja_ei_saada_midagi(self):
        """See invariant on VÄÄRTUSLIK ja jääb kehtima ka pärast
        omaalgatuse lisamist: omaalgatus elab OMAETTE taskis
        (`initiative_ticker`), mitte vaatlejas."""
        i = SRC.index("async def silence_observer()")
        keha = SRC[i:i + 3000]
        for keelatud in ("session.send", "send_realtime_input",
                         "websocket.send", "arm_resume", "jatkamised",
                         "flow.tick"):
            self.assertNotIn(keelatud, keha,
                             f"vaatleja sisaldab tegutsemist: {keelatud}")

    def test_46_diag_log_ei_saada_midagi(self):
        i = SRC.index("def _diag_log(")
        keha = SRC[i:i + 2200]
        for keelatud in ("session.send", "send_realtime_input",
                         "websocket.send", "arm_resume"):
            self.assertNotIn(keelatud, keha,
                             f"_diag_log sisaldab tegutsemist: {keelatud}")

    def test_47_liigitus_on_puhas_funktsioon(self):
        """classify_turn_end ei tohi puutuda seanssi, võrku ega olekut –
        muidu ei saa teda testida ilma Geminit jäljendamata."""
        i = SRC.index("def classify_turn_end(")
        keha = SRC[i:SRC.index("class SpeechTurn:")]
        for keelatud in ("session.", "websocket", "await ", "asyncio",
                         "print(", "sqlite3", "global ", "time."):
            self.assertNotIn(keelatud, keha,
                             f"liigitus ei ole puhas: {keelatud}")

    def test_48_stall_s_vaikimisi_None(self):
        """Oletatud ajalävendit ei tohi koodis olla."""
        import inspect
        sig = inspect.signature(classify)
        self.assertIsNone(sig.parameters["stall_s"].default)
        self.assertIsNone(sig.parameters["safety_signal"].default)
        self.assertIsNone(sig.parameters["client_report"].default)

    def test_49_taastepoliitika_on_uhendatud(self):
        """MUUDETUD (hilisem ring 10.11.2026): jätkamisloogika liikus
        `conversation_flow.py`-sse. Vana `AINULT_JATKAMISI = 1` on
        kaotatud – mõõdetud, et see põhjustas 36 s vaikuse. Kaitsed
        peavad siiski alles olema, nüüd poliitikaobjekti sees."""
        self.assertIn("import conversation_flow", SRC)
        self.assertIn("flow = conversation_flow.ConversationFlow(", SRC)
        self.assertIn("flow.on_turn_complete(", SRC)
        self.assertIn("flow.on_recovery_dispatched(", SRC)
        self.assertIn("conversation_flow.RECOVERY_PROMPT", SRC)
        # vahelesegamise kaitse antakse endiselt edasi
        self.assertIn('user_interrupted=just_interrupted["v"]', SRC)
        # taastepalve sõnastus on muutumatu
        sys.path.insert(0, str(KOOD))
        import conversation_flow as _cf
        self.assertIn("[SÜSTEEM] Sinu eelmine lause jäi pooleli. ",
                      _cf.RECOVERY_PROMPT)

    def test_50_vaatleja_tyhistatakse(self):
        """Ilma selleta jääks iga kõne järel task rippuma."""
        self.assertIn("asyncio.create_task(silence_observer())", SRC)
        # RANGEM: task peab olema seansi OMANDIS (registreeritud) ja
        # tühistamine peab käima ÜHE sulgemisprotseduuri kaudu, mis
        # taskid ka ÄRA OOTAB (varem ainult cancel(), ilma ootamist).
        self.assertIn("observer_task = _registreeri(", SRC)
        self.assertIn("async def _sulge_seanss(", SRC)
        i = SRC.index("async def _sulge_seanss(")
        keha = SRC[i:i + 2600]
        self.assertIn("for t in list(_taustataskid):", keha)
        self.assertIn("t.cancel()", keha)
        self.assertIn("await asyncio.wait(", keha)
        # ja sulgemine peab olema `async with` SEES, st Gemini seanss
        # sulgub alles pärast taskide lõppu
        j = SRC.index("async with client.aio.live.connect(")
        k = SRC.index("await _sulge_seanss(", j)
        self.assertLess(k, SRC.rindex("    finally:"),
                        "sulgemine jookseb alles pärast Gemini seansi "
                        "sulgemist")

    def test_51_vaatleja_ei_kuulu_ootekomplekti(self):
        """Vaatleja ei tohi kõne lõppu otsustada."""
        i = SRC.index("done, pending = await asyncio.wait(")
        self.assertNotIn("observer_task", SRC[i:i + 300])

    def test_52_vaatlusmargid_ei_ole_lavendid(self):
        self.assertEqual(NS["SILENCE_OBSERVATION_MARKS_S"],
                         (1.0, 2.0, 4.0, 8.0, 16.0, 32.0))
        self.assertEqual(NS["SILENCE_OBSERVER_INTERVAL_S"], 0.25)


class TestKaitstudSeaded(unittest.TestCase):
    """Kinnitab, et faas 1-2 ei puutunud midagi, mida ei tohtinud."""

    def test_53_VAD_seaded_muutumatud(self):
        self.assertIn("START_SENSITIVITY_HIGH", SRC)
        self.assertIn("prefix_padding_ms=250", SRC)
        self.assertIn("END_SENSITIVITY_LOW", SRC)
        self.assertIn("silence_duration_ms=800", SRC)
        self.assertIn("START_OF_ACTIVITY_INTERRUPTS", SRC)

    def test_54_turvaseaded_muutumatud(self):
        self.assertEqual(SRC.count("HarmBlockThreshold.BLOCK_NONE"), 4)

    def test_55_mudel_ja_api_versioon_muutumatud(self):
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", SRC)
        self.assertIn("'api_version': 'v1alpha'", SRC)

    def test_56_generatsiooniparameetreid_EI_LISATUD(self):
        for keelatud in ("temperature=", "top_p=", "top_k=",
                         "enable_affective_dialog", "proactivity"):
            self.assertNotIn(keelatud, SRC, f"lisatud: {keelatud}")

    def test_57_kontekstiaken_ja_taastamine_muutumatud(self):
        self.assertIn("ContextWindowCompressionConfig", SRC)
        self.assertIn("sliding_window=types.SlidingWindow()", SRC)
        self.assertIn("RESUME_WINDOW_S = 30.0", SRC)
        self.assertEqual(SRC.count("FATAL_LIVE_CLOSE_CODES = {1007, 1008, 1011}"), 1)

    def test_58_karakteri_promptid_tulevad_registrist(self):
        self.assertIn("persona_registry.build_voice_prompt(active_persona, custom_prompt)",
                      SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)

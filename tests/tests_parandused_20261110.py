# -*- coding: utf-8 -*-
"""REGRESSIOONITESTID: 10.11.2026 parandused.

ISSUE 1  get_last_turn_state valenegatiiv seansipiiril (voorud 982 -> 983)
ISSUE 3  mälu väljakuulutamine (4 vooru 18-st)
ISSUE 4  tööriistavaikus liigitati mudeli seiskumiseks

Klassid ja puhtad funktsioonid loetakse live_maya_ws.py LÄHTEKOODIST ja
käivitatakse isoleeritud nimeruumis – sama muster nagu tests_konevoor.py,
sest arendusmasinas ei ole google.genai teeki.

KÄIVITAMINE: python3 tests_parandused_20261110.py
"""

import ast
import re
import sys
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KOOD = (BASE / "server") if (BASE / "server" / "live_maya_ws.py").exists() else BASE
SRC = (KOOD / "live_maya_ws.py").read_text(encoding="utf-8")
BRAIN = (KOOD / "maya_brain.py").read_text(encoding="utf-8")


def _ruum(nimed):
    puu = ast.parse(SRC)
    val = []
    for n in puu.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.name in nimed:
                val.append(n)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in nimed:
                    val.append(n)
    ns = {"time": time, "__name__": "isoleeritud"}
    exec(compile(ast.Module(body=val, type_ignores=[]), "<live>", "exec"), ns)
    return ns


NS = _ruum({
    "SpeechTurn", "classify_turn_end", "TERMINAL_PUNCT",
    "SILENCE_OBSERVATION_MARKS_S", "SILENCE_OBSERVER_INTERVAL_S",
    "CHARS_PER_S_CUTOFF", "_LAST_UNFINISHED", "UNFINISHED_WINDOW_S",
    "store_unfinished_turn", "clear_unfinished_turn", "take_unfinished_turn",
    "_eelmise_kone_kokkuvote",
    "measure_transport_throughput", "PCM16_BYTES_PER_SAMPLE",
    "DECLARED_INPUT_RATE_HZ", "MIN_THROUGHPUT_MEASURE_S",
})
SpeechTurn = NS["SpeechTurn"]
store = NS["store_unfinished_turn"]
take = NS["take_unfinished_turn"]
clear = NS["clear_unfinished_turn"]
kokkuvote = NS["_eelmise_kone_kokkuvote"]
# NB: mooduli tasemele, MITTE klassiatribuudiks – klassi küljes muutuks
# plain-funktsioon seotud meetodiks ja self läheks esimeseks argumendiks.
tp = NS["measure_transport_throughput"]
classify = NS["classify_turn_end"]


def streaminud_voor(tekst="Ma kohe heidan pilgu peale... Oota hetk!",
                    audio_s=3.0, t0=1000.0):
    """Voor, mis jõudis heli saata ja jäi siis pooleli (nagu #982)."""
    t = SpeechTurn(7, "romantiline", t0)
    t.note_text(tekst)
    t.note_audio(int(24000 * 2 * audio_s), t0 + 0.5)
    return t


# =====================================================================
# ISSUE 1 — SEANSIPIIRI VALENEGATIIV
# =====================================================================
class TestVoor982Stsenaarium(unittest.TestCase):
    """TÄPNE mõõdetud juhtum.

    #982  romantiline, Maya ütleb "...Oota hetk!", seanss sureb 1007-ga
    #983  uus seanss, kasutaja: "No jatka nüüd. Ma ei saa aru, miks pooleli."
          get_last_turn_state vastas VANASTI "katkestusi pole" ja Maya
          ütles "Võib-olla oli mingi tehniline tõrge SINU POOL?"
    """

    def setUp(self):
        clear()

    tearDown = setUp

    def test_01_fataalne_torge_salvestab_kirje(self):
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        ok = store(t, "romantiline", "Gemini lõpetas seansi koodiga 1007",
                   now=1001.0)
        self.assertTrue(ok)
        self.assertIsNotNone(NS["_LAST_UNFINISHED"]["record"])

    def test_02_uus_seanss_LEIAB_eelmise_katkestuse(self):
        """SEE ON PÕHIPARANDUS. Vanasti tagastas None."""
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "Gemini lõpetas seansi koodiga 1007",
              now=1001.0)
        rec = take("romantiline", now=1060.0)
        self.assertIsNotNone(rec, "uus seanss ei leidnud eelmist katkestust")
        self.assertEqual(rec["turn_id"], 7)
        self.assertIn("1007", rec["reason"])
        self.assertIn("Oota hetk", rec["tail"])

    def test_03_kokkuvote_EI_SUUDISTA_kasutajat(self):
        """Mõõdetud väljund oli: 'Võib-olla oli mingi tehniline tõrge
        sinu pool?' Uus kokkuvõte peab selle sõnaselgelt keelama."""
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "Gemini lõpetas seansi koodiga 1007",
              now=1001.0)
        s = kokkuvote(take("romantiline", now=1060.0))
        self.assertIn("ei ole kasutaja eksitus", s)
        self.assertIn("ÄRA ütle, et viga", s)
        self.assertIn("1007", s)
        self.assertIn("Oota hetk", s)

    def test_04_kokkuvote_utleb_heli_kestuse(self):
        t = streaminud_voor(audio_s=3.0)
        t.fail(1001.0, 1007)
        store(t, "romantiline", "kood 1007", now=1001.0)
        s = kokkuvote(take("romantiline", now=1010.0))
        self.assertIn("3.0 sekundit", s)


class TestEiTekiValepositiive(unittest.TestCase):
    """Omaniku nõue: tavaline seansi sulgemine EI OLE tõend poolikusest."""

    def setUp(self):
        clear()

    tearDown = setUp

    def test_05_LOPETATUD_voor_ei_salvestu(self):
        t = streaminud_voor(tekst="Tere, kuidas läheb?")
        t.complete(1001.0)
        self.assertFalse(store(t, "asjalik", "seanss sulgus", now=1001.0))
        self.assertIsNone(NS["_LAST_UNFINISHED"]["record"])

    def test_06_ILMA_HELITA_voor_ei_salvestu(self):
        """Tühi voor – sellel on juba oma eraldi tee."""
        t = SpeechTurn(9, "asjalik", 1000.0)
        t.note_text("midagi")
        self.assertFalse(store(t, "asjalik", "kood 1007", now=1001.0))

    def test_07_None_ei_kuku_kokku(self):
        self.assertFalse(store(None, "asjalik", "kood 1007", now=1001.0))

    def test_08_tyhjast_kirjest_tagastub_None(self):
        self.assertIsNone(take("asjalik", now=1000.0))


class TestAegumineJaUhekordsus(unittest.TestCase):
    """Omaniku nõue: aegunud kirjet ei tohi lõputult raporteerida."""

    def setUp(self):
        clear()

    tearDown = setUp

    def valmista(self):
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "kood 1007", now=1001.0)

    def test_09_kirje_on_UHEKORDNE(self):
        self.valmista()
        self.assertIsNotNone(take("romantiline", now=1010.0))
        self.assertIsNone(take("romantiline", now=1011.0),
                          "sama katkestust raporteeriti kaks korda")

    def test_10_aegunud_kirje_ei_tagastu(self):
        self.valmista()
        hilja = 1001.0 + NS["UNFINISHED_WINDOW_S"] + 1.0
        self.assertIsNone(take("romantiline", now=hilja))

    def test_11_aegunud_kirje_kustutatakse(self):
        self.valmista()
        take("romantiline", now=1001.0 + NS["UNFINISHED_WINDOW_S"] + 1.0)
        self.assertIsNone(NS["_LAST_UNFINISHED"]["record"])

    def test_12_akna_sees_veel_kehtib(self):
        self.valmista()
        vara = 1001.0 + NS["UNFINISHED_WINDOW_S"] - 1.0
        self.assertIsNotNone(take("romantiline", now=vara))

    def test_13_aken_on_pohjendatud_suurus(self):
        """Mõõdetud juhtumis 982->983 kulus tagasihelistamiseks ~2 min.
        Aken peab olema sellest suurem, aga mitte lõputu."""
        self.assertGreater(NS["UNFINISHED_WINDOW_S"], 120.0)
        self.assertLessEqual(NS["UNFINISHED_WINDOW_S"], 3600.0)


class TestVestlusteEraldatus(unittest.TestCase):
    """Omaniku nõue: säilita olemasolev vestluste eraldatus."""

    def setUp(self):
        clear()

    tearDown = setUp

    def test_14_sama_karakter_saab_teksti(self):
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "kood 1007", now=1001.0)
        rec = take("romantiline", now=1010.0)
        self.assertTrue(rec["same_persona"])
        self.assertIn("Oota hetk", rec["tail"])

    def test_15_TEINE_karakter_EI_saa_teksti(self):
        """Sarkastiline ei tohi pärida romantilise poolelijäänud lauset."""
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "kood 1007", now=1001.0)
        rec = take("sarkastiline", now=1010.0)
        self.assertIsNotNone(rec)
        self.assertFalse(rec["same_persona"])
        self.assertEqual(rec["tail"], "")
        self.assertIn("kood 1007", rec["reason"])

    def test_16_teise_karakteri_kokkuvottes_ei_ole_teksti(self):
        t = streaminud_voor()
        t.fail(1001.0, 1007)
        store(t, "romantiline", "kood 1007", now=1001.0)
        s = kokkuvote(take("sarkastiline", now=1010.0))
        self.assertNotIn("Oota hetk", s)
        self.assertIn("teise karakteriga", s)


class TestKoodiUhendus(unittest.TestCase):
    """Staatilised kontrollid: parandus peab olema PÄRISELT ühendatud."""

    def test_17_fail_kutsutakse_fataalsel_teel(self):
        """`SpeechTurn.fail()` oli enne seda surnud kood."""
        self.assertIn("_ft.fail(time.monotonic()", SRC)
        self.assertIn("store_unfinished_turn(", SRC)

    def test_18_tooriist_kysib_eelmise_kone_kohta(self):
        i = SRC.index('if fn_name == "get_last_turn_state"')
        keha = SRC[i:i + 2600]
        self.assertIn("take_unfinished_turn(active_persona)", keha)
        self.assertIn("_eelmise_kone_kokkuvote", keha)

    def test_19_vana_eksitav_sonastus_on_KADUNUD(self):
        self.assertNotIn(
            "Eelmine voor ei jäänud pooleli – ükski voor ei ole selles kõnes",
            SRC)

    def test_20_kirjet_ei_ole_ilma_kirjeta_vastus_on_ettevaatlik(self):
        """Kui kirjet ei ole, ei tohi mudel väita, et kõik oli korras."""
        i = SRC.index('if fn_name == "get_last_turn_state"')
        keha = SRC[i:i + 4200]   # haru kasvas aegumiskontrolliga
        self.assertIn("SIIT EI JÄRELDU", keha)
        self.assertIn("ÄRA väida", keha)

    def test_21_fail_salvestab_ka_last_cut_turn(self):
        self.assertIn('last_cut_turn["t"] = _ft', SRC)


# =====================================================================
# ISSUE 3 — MÄLU LOOMULIK KASUTAMINE
# =====================================================================
class TestMaluKasutamiseJuhis(unittest.TestCase):

    def test_22_juhis_on_olemas(self):
        self.assertIn("KUIDAS NEID KASUTADA", BRAIN)

    def test_23_keelab_valjakuulutamise(self):
        self.assertIn("ära loe neid ette", BRAIN)
        self.assertIn("'meeles'", BRAIN)

    def test_24_keelab_kolmanda_isiku(self):
        """Voor #980: 'Peetrile meeldib Pohjatuul, nii laulan talle...'"""
        self.assertIn("sina-vormis", BRAIN)
        self.assertIn("mitte kolmandas isikus", BRAIN)

    def test_25_LUBAB_meenutamise_kui_see_on_asjakohane(self):
        """Omaniku nõue: ära eemalda võimet mäletamist tunnistada."""
        self.assertIn("'Ma mäletan, et...' on omal kohal", BRAIN)

    def test_26_EI_SUNNI_fakte_kasutama(self):
        """Omaniku nõue: ära sunni iga karakterit mälu kasutama."""
        self.assertIn("jäta see rahule", BRAIN)

    def test_27_juhises_EI_OLE_USER_kohahoidjat(self):
        """web_maya.py kutsub maya_brain'i ilma user_profile.fill()'i –
        kohahoidja jääks täitmata ja jõuaks mudelini toorelt."""
        i = BRAIN.index("KUIDAS NEID KASUTADA")
        self.assertNotIn("{USER}", BRAIN[i:i + 900])

    def test_28_faktiloend_ise_on_puutumata(self):
        self.assertIn("KASUTAJA KOHTA SALVESTATUD FAKTID (Pikaajaline mälu)",
                      BRAIN)
        self.assertIn('"\\n".join(f"- {f}" for f in facts)', BRAIN)


# =====================================================================
# ISSUE 4 — TÖÖRIISTAVAIKUS EI OLE MUDELI SEISKUMINE
# =====================================================================
class TestTooriistaVaikus(unittest.TestCase):

    def test_29_tooriista_ajal_ei_ole_C(self):
        """get_song_lyrics ajalimiit on 20 s – vaikus on legitiimne."""
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=18.0, stall_s=2.0,
                     tool_running=True)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "tool_in_progress")
        self.assertFalse(r["continue_appropriate"])

    def test_30_ilma_tooriista_on_sama_olukord_C(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=18.0, stall_s=2.0,
                     tool_running=False)
        self.assertEqual(r["class"], "C")
        self.assertTrue(r["continue_appropriate"])

    def test_31_tooriist_ei_varjuta_kasutaja_vahelesegamist(self):
        """B peab B-ks jääma ka tööriista ajal."""
        r = classify(saw_turn_complete=False, saw_interrupted=True,
                     tail_is_terminal=False, chars_per_audio_s=11.0,
                     audio_s=3.0, silence_s=5.0, user_speech_within_s=1.0,
                     tool_running=True)
        self.assertEqual(r["class"], "B")

    def test_32_tooriist_ei_varjuta_transpordi_torget(self):
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=0.0,
                     audio_s=1.0, silence_s=5.0, close_code=1007,
                     tool_running=True)
        self.assertEqual(r["class"], "F")

    def test_33_vaikimisi_on_tooriist_vaikne(self):
        import inspect
        sig = inspect.signature(classify)
        self.assertIs(sig.parameters["tool_running"].default, False)

    def test_34_endiselt_AINULT_C_ja_D_lubavad_jatkamist(self):
        """Faasi 3 ohutus. Nüüd ka tool_running mõõtmes."""
        lubavad = set()
        for tc in (True, False):
            for it in (True, False):
                for term in (True, False):
                    for cps in (0.0, 6.0, 12.9):
                        for sil in (0.0, 1.0, 18.0):
                            for st in (None, 2.0):
                                for usw in (None, 1.0):
                                    for tr in (True, False):
                                        r = classify(
                                            saw_turn_complete=tc,
                                            saw_interrupted=it,
                                            tail_is_terminal=term,
                                            chars_per_audio_s=cps,
                                            audio_s=5.0, silence_s=sil,
                                            stall_s=st,
                                            user_speech_within_s=usw,
                                            tool_running=tr)
                                        if r["continue_appropriate"]:
                                            lubavad.add(r["class"])
        self.assertEqual(lubavad, {"C", "D"}, f"lubavad: {lubavad}")


class TestVaatlejaTooriistaTeadlik(unittest.TestCase):

    def test_35_vaatleja_loeb_tool_active(self):
        i = SRC.index("async def silence_observer()")
        keha = SRC[i:SRC.index("async def initiative_ticker()")]
        self.assertIn('tool_active["name"]', keha)
        self.assertIn("jaotusest VÄLJAS", keha)

    def test_36_tooriista_ajal_ei_kasva_observed_silence(self):
        """Muidu rikuks üks 20 s laulusõnade otsing kogu jaotuse."""
        i = SRC.index("async def silence_observer()")
        keha = SRC[i:SRC.index("async def initiative_ticker()")]
        self.assertIn("if not tool_nimi:", keha)

    def test_37_lipp_seatakse_ja_nullitakse(self):
        self.assertIn('tool_active["name"] = fn_name', SRC)
        self.assertIn('tool_active["name"] = ""', SRC)

    def test_38_vaatleja_on_endiselt_passiivne(self):
        """Omaalgatus elab OMAETTE taskis – vaatleja jääb passiivseks."""
        # RANGEM: võtame TÄPSELT funktsiooni keha AST-ist, mitte
        # tekstivahemikku kahe nime vahelt. Vahemik haaras kaasa
        # naabrid (taaste_saatja jne), seega kontroll oli hapram kui
        # vaja ja võis nende kommentaaride peale valesti kukkuda.
        import ast as _ast
        fn = None
        for n in _ast.walk(_ast.parse(SRC)):
            if isinstance(n, _ast.AsyncFunctionDef) and \
                    n.name == "silence_observer":
                fn = n
        self.assertIsNotNone(fn, "silence_observer puudub")
        keha = _ast.unparse(fn)
        for keelatud in ("session.send", "send_realtime_input",
                         "websocket.send", "arm_resume", "flow.tick",
                         "gsend", "grealtime"):
            self.assertNotIn(keelatud, keha, keelatud)


# =====================================================================
# KAITSTUD SEADED — parandused ei tohi neid puutuda
# =====================================================================
class TestKaitstudSeaded(unittest.TestCase):

    def test_39_VAD_muutumatu(self):
        self.assertIn("START_SENSITIVITY_HIGH", SRC)
        self.assertIn("prefix_padding_ms=250", SRC)
        self.assertIn("silence_duration_ms=800", SRC)

    def test_40_turvaseaded_muutumatud(self):
        self.assertEqual(SRC.count("HarmBlockThreshold.BLOCK_NONE"), 4)

    def test_41_mudel_ja_api_muutumatud(self):
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", SRC)
        self.assertIn("'api_version': 'v1alpha'", SRC)

    def test_42_generatsiooniparameetreid_ei_lisatud(self):
        for k in ("temperature=", "top_p=", "top_k=",
                  "enable_affective_dialog", "proactivity"):
            self.assertNotIn(k, SRC)

    def test_43_taastepalve_sonastus_puutumata(self):
        """MUUDETUD (hilisem ring): loendur liikus conversation_flow'sse,
        aga PALVE SÕNASTUS peab jääma – 3 mõõdetud õnnestunud jätkamist
        selle tekstiga."""
        sys.path.insert(0, str(KOOD))
        import conversation_flow as _cf
        self.assertIn("[SÜSTEEM] Sinu eelmine lause jäi pooleli. ",
                      _cf.RECOVERY_PROMPT)
        self.assertGreater(_cf.RECOVERY_BUDGET, 1)

    def test_44_taastamismehhanism_puutumata(self):
        self.assertIn("RESUME_WINDOW_S = 30.0", SRC)
        self.assertEqual(SRC.count("FATAL_LIVE_CLOSE_CODES = {1007, 1008, 1011}"), 1)

    def test_45_sarnasusalgoritm_puutumata(self):
        mf = (KOOD / "memory_fts.py").read_text(encoding="utf-8")
        self.assertIn("def subject_similarity", mf)
        self.assertIn("def stem_et", mf)


# =====================================================================
# ISSUE 2 — NIMEMIGRATSIOON (lokaalne, tootmises EI OLE käivitatud)
# =====================================================================
@unittest.skip(
    "AVALIK VERSIOON: see testiklass kontrollis ÜHEKORDSET isikliku nime "
    "migratsiooni (`migratsioon_nimi_peeter.py`), mis on originaalpaigalduse "
    "privaatne skript ega kuulu avalikku koopiasse. Klass on alles "
    "dokumentatsioonina selle kohta, kuidas andmebaasi migratsiooni ohutult "
    "testida – ajutise andmebaasi peal, mitte tootmise vastu.")
class TestNimeMigratsioon(unittest.TestCase):
    """Vt ülal olevat skip-põhjust."""

    def test_eemaldatud_avalikust_koopiast(self):
        self.fail("ei tohiks jõuda siia")


class TestTranspordiLabilaskevoime(unittest.TestCase):
    """Mõõdab AINULT baite ja aega.

    Varasem versioon andis verdikti "rate_mismatch" ja hoiatas vale
    mikrofonisageduse eest. See järeldus ei olnud põhjendatud: baidid
    sekundis ei ole sämplisageduse tõend, sest võrgupuhverdamine,
    kliendipoolne kajavärav ja järelejõudmise puhangud moonutavad seda
    mõlemas suunas. Verdikt on eemaldatud; need testid kinnitavad, et see
    EI SAA tagasi tulla.
    """

    def test_63_tagastab_toornaitajad(self):
        r = tp(int(32000 * 10), 10.0)
        self.assertTrue(r["ready"])
        self.assertEqual(r["bytes"], 320000)
        self.assertAlmostEqual(r["elapsed_s"], 10.0, places=2)
        self.assertAlmostEqual(r["bytes_per_s"], 32000.0, delta=1.0)

    def test_64_EI_KLASSIFITSEERI(self):
        """Ükski väljund ei tohi sisaldada verdikti ega hinnangut."""
        for baidid, aeg in ((32000 * 10, 10.0), (96000 * 10, 10.0),
                            (1000, 10.0), (0, 10.0), (500, 1.0)):
            r = tp(int(baidid), aeg)
            self.assertEqual(set(r), {"ready", "bytes", "elapsed_s",
                                      "bytes_per_s"},
                             "väljundis on lisaväli: %s" % sorted(r))
            for v in r.values():
                self.assertNotIsInstance(v, str,
                                         "väljundis on tekstiline hinnang")

    def test_65_korge_laabilaskevoime_EI_OLE_viga(self):
        """3x kiirem voog võib tulla järelejõudmise puhangust – see EI OLE
        tõend vale sämplisageduse kohta."""
        r = tp(int(96000 * 10), 10.0)
        self.assertTrue(r["ready"])
        self.assertAlmostEqual(r["bytes_per_s"], 96000.0, delta=1.0)
        self.assertNotIn("ok", r)
        self.assertNotIn("verdict", r)

    def test_66_madal_laabilaskevoime_EI_OLE_viga(self):
        """Kajavärav jätab kaadreid saatmata – samuti mitte tõend."""
        r = tp(int(32000 * 10 * 0.1), 10.0)
        self.assertTrue(r["ready"])
        self.assertNotIn("verdict", r)

    def test_67_liiga_vara_ei_ole_valmis(self):
        r = tp(32000, 1.0)
        self.assertFalse(r["ready"])
        self.assertIsNone(r["bytes_per_s"])

    def test_68_ilma_baitideta_ei_ole_valmis(self):
        r = tp(0, 60.0)
        self.assertFalse(r["ready"])
        self.assertIsNone(r["bytes_per_s"])

    def test_69_funktsioon_on_puhas(self):
        i = SRC.index("def measure_transport_throughput(")
        keha = SRC[i:SRC.index("def _eelmise_kone_kokkuvote(")]
        for keelatud in ("session", "websocket", "await ", "print(", "time."):
            self.assertNotIn(keelatud, keha, keelatud)

    def test_70_verdikti_loogika_on_KADUNUD(self):
        """Omaniku nõue: eemalda verdikt ja hoiatus."""
        self.assertNotIn("measure_input_rate", SRC)
        self.assertNotIn("HELI SISEND HOIATUS", SRC)
        self.assertNotIn("measured_hz", SRC)
        self.assertNotIn("RATE_UPPER_TOLERANCE", SRC)
        # Ainus lubatud esinemine on kommentaar, mis eemaldamist selgitab.
        read = [l for l in SRC.splitlines() if "rate_mismatch" in l]
        self.assertTrue(all(l.strip().startswith("#") for l in read), read)

    def test_71_logirida_utleb_valja_mida_see_EI_ole(self):
        i = SRC.index("HELI SISEND TRANSPORT")
        keha = SRC[i:i + 900]
        self.assertIn("MITTE mikrofoni", keha)
        self.assertIn("kajavärav", keha)

    def test_72_mime_type_JA_payload_muutumatud(self):
        self.assertIn('mime_type="audio/pcm;rate=16000"', SRC)
        muster = ('data=msg["bytes"],\n'
                  '                                        '
                  'mime_type="audio/pcm;rate=16000"')
        self.assertEqual(SRC.count(muster), 1,
                         "heli saatmise kutse on muutunud")
        muud = set(re.findall(r'mime_type="audio/[^"]+"', SRC)) - {
            'mime_type="audio/pcm;rate=16000"'}
        self.assertEqual(muud, set(), "leitud muu helitüüp: %s" % muud)

    def test_73_logitakse_UKS_kord_seansi_kohta(self):
        self.assertIn('rate_check = {"bytes": 0, "first_at": 0.0, '
                      '"logged": False}', SRC)
        self.assertIn('if not rate_check["logged"]:', SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)

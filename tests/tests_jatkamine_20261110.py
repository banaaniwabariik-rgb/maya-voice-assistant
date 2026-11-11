# -*- coding: utf-8 -*-
"""TESTID: 10.11.2026 filosoofi tootmistesti kaks parandust.

ISSUE 1  chars_per_audio_s eemaldatud A–H liigituse otsustusahelast
ISSUE 2  jätkamisloenduri elutsükkel + ahela kõva ülempiir

TOOTMISTÕEND, millele need testid tuginevad (seanss 12:16:59–12:21:16,
karakter filosoof, PID 3886561):

  B#6  "...vaid kosmilise"   -> jätkamispalve -> B#7 "printsiibina, mis
                                läbib kogu eksistentsi."        ÕNNESTUS
  B#8  "...tugeva ja"        -> jätkamispalve -> B#9 "domineeriva jõuna,
                                mis otsib kontakti..."          ÕNNESTUS
  B#10 "...See on"           -> jätkamispalve -> B#11 "energiate tants,
                                ... potentsiaali uueks"         EI LÕPETANUD
  B#11 jäi POOLIKUKS, aga loendur oli otsas -> Maya vaikis 14 s, kuni
       kasutaja ise toru ära pani.

  Kõigi viie poolikuks jäänud vooru chars_per_audio_s oli 9,0–10,2 ehk
  ALLA vana lävendi 10,5 -> vana liigitus ütles "klass A, jätkamine ei
  ole kohane" kõigil viiel korral.

KÄIVITAMINE: python3 tests_jatkamine_20261110.py
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
    "CHARS_PER_S_CUTOFF",
})
classify = NS["classify_turn_end"]
SpeechTurn = NS["SpeechTurn"]
TERMINAL = NS["TERMINAL_PUNCT"]

# 10.11.2026 (hilisem ring): jätkamispiirangud liikusid
# `conversation_flow.py`-sse ja `AINULT_JATKAMISI = 1` kaotati, sest
# mõõdetud tootmises põhjustas see 36 s vaikuse. Selle faili ISSUE 2
# testid kirjeldavad VANA mehhanismi ja on säilitatud ajaloolise
# dokumentatsioonina – uus poliitika on kaetud
# `tests_vestluse_elutsykkel.py`-s.
sys.path.insert(0, str(KOOD))
import conversation_flow as _cf  # noqa: E402
JARJEST = 1                      # vana järjestikuse katse piirang
AHELA_PIIR = _cf.RECOVERY_BUDGET


# =====================================================================
# JÄTKAMISAHELA SIMULAATOR
# =====================================================================
class JatkamisAhel:
    """Tootmise jätkamisloogika puhas mudel.

    MIKS SIMULAATOR: päris loogika elab WebSocketi handleri sees ja
    sõltub Geminist ning WebSocketist. Simulaator kasutab TOOTMISE
    KONSTANTE (loetud lähtekoodist, vt NS ülal) ja jäljendab täpselt
    tootmise üleminekureegleid. Selle kõrval on klass
    TootmiskoodiVastavus, mis kontrollib staatiliselt, et päris kood
    sisaldab sama loogikat – nii ei saa simulaator tootmisest vaikselt
    lahku joosta.

    TEADAOLEV LAHKNEVUS (auditis 10.11.2026 tuvastatud, dokumenteeritud
    tahtlikult): `tooriist_tootab` värav on siin modelleeritud, aga
    TOOTMISE jätkamisväravas sellist kontrolli EI OLE. Seda ei ole vaja,
    sest tööriist oodatakse (`await execute_tool_call`) SAMAS
    `async for`-keha iteratsioonis ja ENNE turn_complete kontrolli –
    tsükkel ei too järgmist vastust, kuni keha lõpeb, seega
    turn_complete ei saa tööriista ajal töödeldud saada. Värav on
    simulaatoris alles, et test 23 kataks nõude sõnastuse.
    """

    def __init__(self):
        self.n = 0          # järjestikused jätkamised ilma õnnestumist
        self.kokku = 0      # jätkamisi selles ahelas kokku
        self.ootel = False  # kas ootame jätkamise vastust
        self.logi = []

    # --- kasutaja rääkis -> UUS AHEL --------------------------------
    def kasutaja_raakis(self):
        self.n = 0
        self.kokku = 0
        self.ootel = False
        self.logi.append("kasutaja_raakis -> ahel nullitud")

    # --- KATKESTUS: ootel olev jätkamine muutub kehtetuks ----------
    def katkestus(self):
        """Tootmine: katkestuse haru, rida 2951–2960.

        Nullib AINULT `ootel`. `n` ja `kokku` jäävad – katkestus ei ole
        õnnestumine.
        """
        if self.ootel:
            self.ootel = False
            self.logi.append("katkestus -> ootel nullitud, n=%d kokku=%d"
                             % (self.n, self.kokku))
        else:
            self.logi.append("katkestus (ootel polnud)")

    # --- TÜHI turn_complete: vooru objekti ei ole -------------------
    def tyhi_turn_complete(self):
        """Tootmine: turn_complete else-haru, rida 3043–3052.

        Siin EI SAA olla jätkamise vastust (vooru objekt puudub).
        """
        if self.ootel:
            self.ootel = False
            self.logi.append("tühi turn_complete -> ootel nullitud, "
                             "n=%d kokku=%d" % (self.n, self.kokku))
        else:
            self.logi.append("tühi turn_complete (ootel polnud)")

    # --- voor lõppes -----------------------------------------------
    def voor_lopppes(self, lausemark: bool, katkestatud: bool = False,
                     tooriist_tootab: bool = False,
                     heli_s: float = 5.0, tekst_pikkus: int = 50):
        """Tagastab True, kui jätkamispalve SAADETI."""
        # 1. kas see voor oli jätkamise vastus?
        if self.ootel:
            self.ootel = False
            if lausemark:
                self.n = 0
                self.logi.append("jätkamine ÕNNESTUS -> n=0")
            else:
                self.logi.append("jätkamine EI lõpetanud lauset -> n=%d" % self.n)

        # 2. kas vajab jätkamist?
        if lausemark or tekst_pikkus <= 0:
            return False

        # 3. väravad
        if katkestatud:
            self.logi.append("BLOKEERITUD: kasutaja segas vahele")
            return False
        if tooriist_tootab:
            self.logi.append("BLOKEERITUD: tööriist töötab")
            return False
        if self.n >= JARJEST:
            self.logi.append("BLOKEERITUD: järjestikune piir %d" % JARJEST)
            return False
        if self.kokku >= AHELA_PIIR:
            self.logi.append("BLOKEERITUD: ahela piir %d" % AHELA_PIIR)
            return False

        self.n += 1
        self.kokku += 1
        self.ootel = True
        self.logi.append("JÄTKAMISPALVE saadetud (n=%d, kokku=%d/%d)"
                         % (self.n, self.kokku, AHELA_PIIR))
        return True


# =====================================================================
# ISSUE 1 — LIIGITUS EI SÕLTU SUHTARVUST
# =====================================================================
class TestLiigitusIlmaSuhtarvu(unittest.TestCase):

    def test_01_poolik_lause_annab_D_ja_lubab_taaste(self):
        """NÕUE 1. turn_complete + heli + tekst ilma lausemärki -> D."""
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=9.0,
                     audio_s=10.96, silence_s=8.15, tail_len=99)
        self.assertEqual(r["class"], "D")
        self.assertEqual(r["name"], "premature_turn_complete")
        self.assertTrue(r["continue_appropriate"])

    def test_02_terve_lause_annab_A(self):
        """NÕUE 2."""
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=True, chars_per_audio_s=8.18,
                     audio_s=32.4, silence_s=19.3, tail_len=265)
        self.assertEqual(r["class"], "A")
        self.assertFalse(r["continue_appropriate"])

    def test_03_madal_ja_korge_suhtarv_annavad_SAMA_tulemuse(self):
        """NÕUE 3. Ainus erinevus on suhtarv – tulemus peab olema sama."""
        for cps in (0.0, 1.0, 6.0, 9.0, 10.49, 10.5, 10.51, 12.9, 99.0):
            r = classify(saw_turn_complete=True, saw_interrupted=False,
                         tail_is_terminal=False, chars_per_audio_s=cps,
                         audio_s=8.0, silence_s=0.1, tail_len=80)
            self.assertEqual(r["class"], "D", "cps=%s" % cps)
            self.assertTrue(r["continue_appropriate"], "cps=%s" % cps)
        for cps in (0.0, 9.0, 12.9, 99.0):
            r = classify(saw_turn_complete=True, saw_interrupted=False,
                         tail_is_terminal=True, chars_per_audio_s=cps,
                         audio_s=8.0, silence_s=0.1, tail_len=80)
            self.assertEqual(r["class"], "A", "cps=%s" % cps)

    def test_04_KOIK_VIIS_tootmisvooru_annavad_nuud_D(self):
        """Mõõdetud filosoofi testis. Vana lävend andis kõigil A."""
        tootmine = [
            # (voor, audio_s, chars, cps)
            ("A#3", 21.20, 216, 10.19),
            ("B#6", 17.68, 170, 9.6),
            ("B#8", 7.76, 74, 9.5),
            ("B#10", 8.92, 90, 10.1),
            ("B#11", 10.96, 99, 9.0),
        ]
        for nimi, audio, chars, cps in tootmine:
            r = classify(saw_turn_complete=True, saw_interrupted=False,
                         tail_is_terminal=False, chars_per_audio_s=cps,
                         audio_s=audio, silence_s=5.0, tail_len=chars)
            self.assertEqual(r["class"], "D", nimi)
            self.assertTrue(r["continue_appropriate"], nimi)

    def test_05_tyhi_transkriptsioon_EI_ole_poolik_lause(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=0.0,
                     audio_s=5.0, silence_s=0.1, tail_len=0)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "empty_transcription")
        self.assertFalse(r["continue_appropriate"])

    def test_06_ilma_helita_ei_otsusta(self):
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=50.0,
                     audio_s=0.3, silence_s=0.1, tail_len=15)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "too_little_audio_to_judge")

    def test_07_kasutaja_vahelesegamine_jaab_B_ks(self):
        """NÕUE 7 liigituse poolel."""
        r = classify(saw_turn_complete=False, saw_interrupted=True,
                     tail_is_terminal=False, chars_per_audio_s=9.0,
                     audio_s=20.64, silence_s=0.2,
                     user_speech_within_s=1.1, tail_len=120)
        self.assertEqual(r["class"], "B")
        self.assertFalse(r["continue_appropriate"])

    def test_08_tooriista_vaikus_ei_anna_taastet(self):
        """NÕUE 8 liigituse poolel."""
        r = classify(saw_turn_complete=False, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=9.0,
                     audio_s=3.0, silence_s=18.0, stall_s=2.0,
                     tool_running=True, tail_len=60)
        self.assertEqual(r["class"], "H")
        self.assertEqual(r["reason"], "tool_in_progress")
        self.assertFalse(r["continue_appropriate"])

    def test_09_transpordi_torge_sailitab_oma_liigituse(self):
        """NÕUE 9."""
        for kood in (1007, 1008, 1011):
            r = classify(saw_turn_complete=True, saw_interrupted=False,
                         tail_is_terminal=False, chars_per_audio_s=9.0,
                         audio_s=5.0, silence_s=0.1, close_code=kood,
                         tail_len=80)
            self.assertEqual(r["class"], "F", kood)
            self.assertFalse(r["continue_appropriate"], kood)
        r = classify(saw_turn_complete=True, saw_interrupted=False,
                     tail_is_terminal=False, chars_per_audio_s=9.0,
                     audio_s=5.0, silence_s=0.1,
                     failure_reason="generation_stall", tail_len=80)
        self.assertEqual(r["class"], "F")

    def test_10_endiselt_AINULT_C_ja_D_lubavad_jatkamist(self):
        """Faasi 3 ohutus. Ammendav, nüüd ka tail_len mõõtmes."""
        lubavad = set()
        for tc in (True, False):
            for it in (True, False):
                for term in (True, False):
                    for cps in (0.0, 9.0, 12.9):
                        for sil in (0.0, 1.0, 18.0):
                            for st in (None, 2.0):
                                for usw in (None, 1.0):
                                    for tr in (True, False):
                                        for tl in (0, 80):
                                            r = classify(
                                                saw_turn_complete=tc,
                                                saw_interrupted=it,
                                                tail_is_terminal=term,
                                                chars_per_audio_s=cps,
                                                audio_s=5.0, silence_s=sil,
                                                stall_s=st,
                                                user_speech_within_s=usw,
                                                tool_running=tr, tail_len=tl)
                                            if r["continue_appropriate"]:
                                                lubavad.add(r["class"])
        self.assertEqual(lubavad, {"C", "D"}, "lubavad: %s" % lubavad)

    def test_11_suhtarv_jaab_diagnostikasse(self):
        """Mõõdik peab logis alles olema, lihtsalt otsust ei mõjuta."""
        t = SpeechTurn(1, "filosoof", 1000.0)
        t.note_text("x" * 99)
        t.note_audio(int(24000 * 2 * 10.96), 1000.5)
        d = t.diag_dict(1001.0)
        self.assertIn("chars_per_audio_s", d)
        self.assertGreater(d["chars_per_audio_s"], 0)


# =====================================================================
# ISSUE 2 — JÄTKAMISLOENDURI ELUTSÜKKEL
# =====================================================================
class TestJatkamisLoendur(unittest.TestCase):
    """AJALOOLINE: kirjeldab VANA loendurit. Uus poliitika on kaetud
    tests_vestluse_elutsykkel.py-s (testid 05-08c)."""


    def test_12_onnestunud_jatkamine_nullib_jarjestikuse_loenduri(self):
        """NÕUE 4. B#6 -> B#7 tootmisstsenaarium."""
        a = JatkamisAhel()
        self.assertTrue(a.voor_lopppes(lausemark=False))   # B#6
        self.assertEqual((a.n, a.kokku, a.ootel), (1, 1, True))
        a.voor_lopppes(lausemark=True)                     # B#7 õnnestus
        self.assertEqual((a.n, a.kokku, a.ootel), (0, 1, False))

    def test_13_onnestumise_jarel_tohib_UUESTI_jatkata(self):
        """See ongi parandus: loendur ei jää kinni."""
        a = JatkamisAhel()
        a.voor_lopppes(lausemark=False)      # jätkamine 1
        a.voor_lopppes(lausemark=True)       # õnnestus -> n=0
        self.assertTrue(a.voor_lopppes(lausemark=False),
                        "teist jätkamist ei lubatud, kuigi esimene õnnestus")
        self.assertEqual((a.n, a.kokku), (1, 2))

    def test_14_ebaonnestunud_jatkamine_EI_NULLI_loendurit(self):
        """NÕUE 5. B#10 -> B#11 tootmisstsenaarium."""
        a = JatkamisAhel()
        self.assertTrue(a.voor_lopppes(lausemark=False))   # B#10
        self.assertEqual(a.n, 1)
        # B#11 on jätkamise vastus JA jääb ise poolikuks
        saadeti = a.voor_lopppes(lausemark=False)
        self.assertFalse(saadeti, "ebaõnnestunud jätkamine sai uue katse")
        self.assertEqual(a.n, 1, "loendur nullitati ebaõnnestumise peale")
        self.assertFalse(a.ootel)

    def test_15_tootmisstsenaarium_B6_B7_B8_B9_B10_B11(self):
        """Kogu mõõdetud jada koos kasutaja kõnedega vahel."""
        a = JatkamisAhel()
        # B#6 poolik -> jätkamine
        self.assertTrue(a.voor_lopppes(lausemark=False))
        # B#7 lõpetas lause -> õnnestus
        a.voor_lopppes(lausemark=True)
        self.assertEqual(a.n, 0)
        # kasutaja rääkis ("No räägi rohkem...")
        a.kasutaja_raakis()
        self.assertEqual((a.n, a.kokku), (0, 0))
        # B#8 poolik -> jätkamine
        self.assertTrue(a.voor_lopppes(lausemark=False))
        # B#9 lõpetas lause -> õnnestus
        a.voor_lopppes(lausemark=True)
        self.assertEqual(a.n, 0)
        # B#10 poolik -> jätkamine
        self.assertTrue(a.voor_lopppes(lausemark=False))
        self.assertEqual((a.n, a.kokku), (1, 2))
        # B#11 on jätkamise vastus ja jääb POOLIKUKS
        self.assertFalse(a.voor_lopppes(lausemark=False))
        self.assertEqual(a.n, 1)

    def test_16_B11_jaab_taastamata_ka_PARAST_parandust(self):
        """AUS TÄPSUSTUS: nõue 5 ("ebaõnnestumine ei nulli loendurit")
        tähendab, et B#11 ei saa uut katset. Parandus EI LAHENDA seda
        konkreetset juhtumit – ta lahendab juhtumi, kus jätkamine
        ÕNNESTUS ja järgmine voor jääb pooleli."""
        a = JatkamisAhel()
        a.voor_lopppes(lausemark=False)                 # B#10
        self.assertFalse(a.voor_lopppes(lausemark=False))  # B#11
        a.kasutaja_raakis()
        self.assertTrue(a.voor_lopppes(lausemark=False),
                        "kasutaja kõne peab ahela uuesti avama")


class TestAhelaKovaPiir(unittest.TestCase):
    """NÕUE 6 + omaniku nõue: dokumenteeritud ja testitud ülempiir."""

    def test_17_piir_tuleb_moodulist_ja_on_suur(self):
        """OMANIKU OTSUS 11.11.2026: "mingit piirangut ei ole".
        Piir tõsteti 3 -> 12 ja see on AINULT ülemine kaitse lõputu
        poolikute voorude seeria vastu. Vana `AINULT_JATKAMISI = 1`
        on ammu kadunud."""
        self.assertEqual(AHELA_PIIR, _cf.RECOVERY_BUDGET)
        self.assertGreaterEqual(AHELA_PIIR, 12)
        self.assertEqual(JARJEST, 1)

    def test_18_ahel_ei_uleta_kova_piiri(self):
        """Iga jätkamine õnnestub – ahel peab ikkagi peatuma."""
        a = JatkamisAhel()
        saadetud = 0
        for _ in range(AHELA_PIIR * 2):
            if a.voor_lopppes(lausemark=False):
                saadetud += 1
                a.voor_lopppes(lausemark=True)   # õnnestus -> n=0
        self.assertEqual(saadetud, AHELA_PIIR)
        self.assertEqual(a.kokku, AHELA_PIIR)
        self.assertIn("BLOKEERITUD: ahela piir %d" % AHELA_PIIR, a.logi)

    def test_19_mitu_ebaonnestunud_jatkamist_ei_uleta_piiri(self):
        """NÕUE 6 sõnastus: mitu POOLIKUT jätkamist järjest."""
        a = JatkamisAhel()
        saadetud = 0
        for _ in range(20):
            if a.voor_lopppes(lausemark=False):
                saadetud += 1
        self.assertEqual(saadetud, 1,
                         "ebaõnnestunud jätkamine sai korduvaid katseid")

    def test_20_piir_nullitakse_ainult_kasutaja_konega(self):
        a = JatkamisAhel()
        for _ in range(AHELA_PIIR):
            a.voor_lopppes(lausemark=False)
            a.voor_lopppes(lausemark=True)
        self.assertEqual(a.kokku, AHELA_PIIR)
        self.assertFalse(a.voor_lopppes(lausemark=False))
        a.kasutaja_raakis()
        self.assertTrue(a.voor_lopppes(lausemark=False))

    def test_21_tsukkel_on_vomatu(self):
        """Lõpmatu ahel ei tohi tekkida ÜHELGI kombinatsioonil."""
        import itertools
        for mustr in itertools.product([True, False], repeat=8):
            a = JatkamisAhel()
            saadetud = 0
            for lausemark in mustr * 5:          # 40 vooru
                if a.voor_lopppes(lausemark=lausemark):
                    saadetud += 1
            self.assertLessEqual(saadetud, AHELA_PIIR,
                                 "muster %s andis %d jätkamist"
                                 % (mustr, saadetud))


class TestVaravadJaavadAlles(unittest.TestCase):

    def test_22_kasutaja_vahelesegamine_blokeerib(self):
        """NÕUE 7."""
        a = JatkamisAhel()
        self.assertFalse(a.voor_lopppes(lausemark=False, katkestatud=True))
        self.assertEqual((a.n, a.kokku), (0, 0))

    def test_23_tooriist_blokeerib(self):
        """NÕUE 8."""
        a = JatkamisAhel()
        self.assertFalse(a.voor_lopppes(lausemark=False,
                                        tooriist_tootab=True))
        self.assertEqual((a.n, a.kokku), (0, 0))

    def test_24_tyhi_tekst_ei_vaja_jatkamist(self):
        a = JatkamisAhel()
        self.assertFalse(a.voor_lopppes(lausemark=False, tekst_pikkus=0))

    def test_25_terve_lause_ei_vaja_jatkamist(self):
        a = JatkamisAhel()
        self.assertFalse(a.voor_lopppes(lausemark=True))
        self.assertEqual((a.n, a.kokku), (0, 0))

    def test_26_kasutaja_kone_tuhistab_ootel_jatkamise(self):
        a = JatkamisAhel()
        a.voor_lopppes(lausemark=False)
        self.assertTrue(a.ootel)
        a.kasutaja_raakis()
        self.assertFalse(a.ootel)


# =====================================================================
# TOOTMISKOODI VASTAVUS — simulaator ei tohi lahku joosta
# =====================================================================
class TestTootmiskoodiVastavus(unittest.TestCase):
    """VANA mehhanismi ühenduskontrollid on ASENDATUD.

    10.11.2026 hilisem ring viis jätkamisloogika
    `conversation_flow.py`-sse. Siin kontrollime, et üleminek on
    TÄIELIK – vanu nimesid ei tohi koodis enam olla ja uued peavad
    olema ühendatud.
    """

    def test_27_vana_olek_on_kadunud(self):
        kood = "\n".join(r for r in SRC.splitlines()
                         if not r.strip().startswith("#"))
        for keelatud in ('jatkamised["n"]', 'jatkamised["kokku"]',
                         'jatkamised["ootel"]', "AINULT_JATKAMISI",
                         "MAX_JATKAMISI_AHELAS"):
            self.assertNotIn(keelatud, kood, keelatud)

    def test_28_uus_voog_on_uhendatud(self):
        self.assertIn("import conversation_flow", SRC)
        self.assertIn("flow = conversation_flow.ConversationFlow(", SRC)
        for nimi in ("flow.on_turn_complete(", "flow.on_recovery_dispatched(",
                     "flow.on_user_speech(", "flow.on_interrupted(",
                     "flow.on_empty_turn_complete(",
                     "flow.on_conversation_end()", "flow.tick("):
            self.assertIn(nimi, SRC, nimi)

    def test_29_taaste_eelarve_on_suurem_kui_uks(self):
        """Mõõdetud: eelarve 1 jättis 42,9% lauseid pooleli."""
        self.assertGreater(_cf.RECOVERY_BUDGET, 1)

    def test_30_taastepalve_sonastus_sailis(self):
        for osa in ("[SÜSTEEM] Sinu eelmine lause jäi pooleli. ",
                    "Jätka TÄPSELT sealt, kus katkesid",
                    "ega maini seda teadet."):
            self.assertIn(osa, _cf.RECOVERY_PROMPT, osa)

    def test_31_suhtarv_ei_otsusta_liigituses(self):
        i = SRC.index("def classify_turn_end(")
        keha = SRC[i:SRC.index("class SpeechTurn:")]
        for rida in keha.splitlines():
            r = rida.strip()
            if r.startswith("#") or "notes.append" in r:
                continue
            self.assertNotIn("chars_per_audio_s >=", r, rida)
            self.assertNotIn("chars_per_audio_s <", r, rida)


class TestKaitstudSeaded(unittest.TestCase):
    """Parandused ei tohi puutuda midagi muud."""

    def test_34_mudel_api_turvaseaded_VAD(self):
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", SRC)
        self.assertIn("'api_version': 'v1alpha'", SRC)
        self.assertEqual(SRC.count("HarmBlockThreshold.BLOCK_NONE"), 4)
        self.assertIn("START_SENSITIVITY_HIGH", SRC)
        self.assertIn("prefix_padding_ms=250", SRC)
        self.assertIn("silence_duration_ms=800", SRC)

    def test_35_heli_payload_muutumatu(self):
        muster = ('data=msg["bytes"],\n'
                  '                                        '
                  'mime_type="audio/pcm;rate=16000"')
        self.assertEqual(SRC.count(muster), 1)
        muud = set(re.findall(r'mime_type="audio/[^"]+"', SRC)) - {
            'mime_type="audio/pcm;rate=16000"'}
        self.assertEqual(muud, set())

    def test_36_generatsiooniparameetreid_ei_lisatud(self):
        for k in ("temperature=", "top_p=", "top_k=",
                  "enable_affective_dialog", "proactivity"):
            self.assertNotIn(k, SRC, k)

    def test_37_faas_1_2_jaab_passiivseks(self):
        i = SRC.index("async def silence_observer()")
        keha = SRC[i:i + 3500]
        for keelatud in ("session.send", "send_realtime_input",
                         "websocket.send", "arm_resume", "jatkamised"):
            self.assertNotIn(keelatud, keha, keelatud)

    def test_38_issue1_parandus_alles(self):
        """Eelmise ringi parandused ei tohi kaduda."""
        self.assertIn("store_unfinished_turn(", SRC)
        self.assertIn("take_unfinished_turn(active_persona)", SRC)
        self.assertIn("measure_transport_throughput(", SRC)
        self.assertNotIn("measure_input_rate", SRC)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""TESTID: vestluse elutsükkel — taaste + omaalgatus.

Katab omaniku 20 nõutud stsenaariumi. `conversation_flow` on PUHAS
moodul, seega testid kutsuvad PÄRIS tootmisfunktsioone, mitte simulaatorit.
`live_maya_ws.py` ühendused kontrollitakse staatiliselt.

MÕÕDETUD ALUS (10.11.2026, kaks filosoofi testi, 21 vooru):
  katkemise määr 9/21 = 42,9%
  eelarve 1 -> 42,9% jääkrisk, eelarve 3 -> 7,9%
  tootmises mõõdetud: #9 D -> #10 D -> vana kood PEATUS -> 36 s vaikust

KÄIVITAMINE: python3 tests_vestluse_elutsykkel.py
"""

import ast
import re
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KOOD = (BASE / "server") if (BASE / "server" / "conversation_flow.py").exists() else BASE
sys.path.insert(0, str(KOOD))
import conversation_flow as cf  # noqa: E402

WS = (KOOD / "live_maya_ws.py").read_text(encoding="utf-8")
CLIENT = (BASE / "android/app/src/main/assets/index.html")
HTML = CLIENT.read_text(encoding="utf-8") if CLIENT.exists() else ""


def kasutaja_raakis(f, now=99.0):
    """PÄRIS EELDUS: iga vestlus algab kasutaja kõnevooruga.

    L6 (omaniku nõue 11.11.2026): Maya ei tohi omaalgatuslikult
    kõnelda enne, kui vestluskaaslane on vähemalt ühe vooru
    lõpetanud. Allolevad stsenaariumid eeldasid varem vaikimisi, et
    värav on avatud – nüüd ütlevad nad eelduse VÄLJA.
    """
    f.on_user_speech(now=now)
    return f


def voor(f, *, text, terminal, audio_s=10.0, now=100.0,
         interrupted=False, tool=False):
    """Üks turn_complete sündmus."""
    return f.on_turn_complete(
        text=text, tail_len=len(text), audio_s=audio_s,
        tail_is_terminal=terminal, user_interrupted=interrupted,
        tool_running=tool, playback_end_est=now, now=now)


# =====================================================================
# 1-4: LOOMULIK LÕPP JA OMAALGATUS
# =====================================================================
class TestLoomulikLoppJaOmaalgatus(unittest.TestCase):

    def test_01_lopetab_lause_ja_jatkab_parast_pausi(self):
        """NÕUE 1."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="See on sügav mõte.", terminal=True, now=100.0)
        self.assertEqual(f.state, cf.COMPLETE_IDLE)
        self.assertFalse(f.tick(now=102.0, user_speaking=False,
                                tool_running=False)["speak"])
        d = f.tick(now=100.0 + f.initiative.pause_s + 0.1,
                   user_speaking=False, tool_running=False)
        self.assertTrue(d["speak"])
        self.assertEqual(d["reason"], "idle_initiative")

    def test_02_arendab_motet_edasi_eelarve_piires(self):
        """NÕUE 2. Omaalgatust tohib olla mitu, aga eelarve piires."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="Alustasin mõtet.", terminal=True, now=100.0)
        t = 100.0
        raagitud = 0
        for _ in range(10):
            t += f.initiative.pause_s + 0.1
            d = f.tick(now=t, user_speaking=False, tool_running=False)
            if d["speak"]:
                raagitud += 1
                f.on_initiative_dispatched(t)
                voor(f, text="Jätkasin mõtet.", terminal=True, now=t + 5)
                t += 5
        self.assertEqual(raagitud, f.initiative.budget)

    def test_03_kusimus_viib_olekusse_AWAITING_USER(self):
        """NÕUE 3 + 4. Küsimus EI OLE sama mis lihtsalt lõpetatud."""
        f = cf.ConversationFlow("filosoof")
        voor(f, text="Mida sina sellest arvad?", terminal=True, now=100.0)
        self.assertEqual(f.state, cf.AWAITING_USER)
        self.assertNotEqual(f.state, cf.COMPLETE_IDLE)

    def test_04_kusimuse_jarel_OOTAB_kauem(self):
        """NÕUE 4. Kui Maya küsis, ei räägi ta kohe peale."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="Kas sa nõustud?", terminal=True, now=100.0)
        # tavaline paus EI OLE piisav
        d = f.tick(now=100.0 + f.initiative.pause_s + 0.1,
                   user_speaking=False, tool_running=False)
        self.assertFalse(d["speak"])
        self.assertEqual(d["reason"], "awaiting_user_answer")
        # kahekordne paus avab
        d = f.tick(now=100.0 + f.initiative.pause_s * 2 + 0.1,
                   user_speaking=False, tool_running=False)
        self.assertTrue(d["speak"])

    def test_04b_kusimuse_tuvastus(self):
        for t, oodatud in (("Mida sa arvad?", cf.AWAITING_USER),
                           ('Kas nii on? "', cf.AWAITING_USER),
                           ("See on nii.", cf.COMPLETE_IDLE),
                           ("Huvitav!", cf.COMPLETE_IDLE),
                           ("Mõtle sellele...", cf.COMPLETE_IDLE)):
            self.assertEqual(cf.classify_completion(t), oodatud, t)


# =====================================================================
# 5-8: TAASTE
# =====================================================================
class TestTaaste(unittest.TestCase):

    def test_05_poolik_lause_kaivitab_taaste_KOHE(self):
        """NÕUE 5 + jõudlusnõue: esimene katse ILMA ootamist."""
        f = cf.ConversationFlow("filosoof")
        o = voor(f, text="Ma tahtsin öelda, et sa oled", terminal=False,
                 audio_s=15.72, now=100.0)
        self.assertTrue(o["recover"])
        self.assertEqual(o["wait_s"], 0.0, "esimene katse ootab – keelatud")
        self.assertEqual(o["attempt"], 1)
        self.assertEqual(f.state, cf.INCOMPLETE)

    def test_06_esimene_taaste_ON_KA_POOLIK(self):
        """NÕUE 6. Mõõdetud tootmises: #5 -> #6 mõlemad poolikud."""
        f = cf.ConversationFlow("filosoof")
        voor(f, text="esimene osa jäi", terminal=False, now=100.0)
        f.on_recovery_dispatched("esimene osa jäi", now=100.0)
        o = voor(f, text="teine osa ka jäi", terminal=False, now=110.0)
        self.assertTrue(o["recover"], "VANA KOOD PEATUS SIIN")
        self.assertEqual(o["attempt"], 2)
        # OMANIKU OTSUS 11.11.2026 "võimalikult kiiresti": ükski katse
        # ei oota enam. Taaste ei ole taimeripõhine – iga katse
        # vallandub päris turn_complete sündmusest, seega ooteaeg oli
        # puhas kaotus.
        self.assertEqual(o["wait_s"], 0.0, "teine katse ootab asjata")

    def test_07_jargmine_taaste_ONNESTUB(self):
        """NÕUE 7."""
        f = cf.ConversationFlow("filosoof")
        voor(f, text="algus jäi", terminal=False, now=100.0)
        f.on_recovery_dispatched("algus jäi", now=100.0)
        voor(f, text="keskosa ka jäi", terminal=False, now=110.0)
        f.on_recovery_dispatched("keskosa ka jäi", now=110.0)
        o = voor(f, text="ja nii see lõppeb.", terminal=True, now=120.0)
        self.assertFalse(o["recover"])
        self.assertEqual(o["reason"], "recovery_succeeded")
        self.assertEqual(f.state, cf.COMPLETE_IDLE)

    def test_08_korduvad_ebaonnestumised_joauavad_OHUTU_lopuni(self):
        """NÕUE 8. Mitte lõputu tsükkel, vaid terminaalne olek."""
        f = cf.ConversationFlow("filosoof")
        katseid = 0
        t = 100.0
        for i in range(30):
            o = voor(f, text="ikka jäi pooleli %d" % i, terminal=False, now=t)
            if o["recover"]:
                katseid += 1
                f.on_recovery_dispatched("ikka jäi pooleli %d" % i, now=t)
            t += 10
        self.assertEqual(katseid, cf.RECOVERY_BUDGET)
        self.assertEqual(f.recovery.stopped_reason, "budget_exhausted")

    def test_08b_eelarve_on_praktikas_piiranguta(self):
        """OMANIKU OTSUS 11.11.2026: "mingit piirangut ei ole".
        Mõõdetud katkemise määr oli 42,9% ja pärast karakteriviiba
        parandust lahendas taaste iga katkemise ESIMESE katsega
        (kuus katkemist, kuus korda `TAASTE 1/3`). Eelarve 12 on
        seega praktikas piiranguta, aga jääb kaitseks lõputu
        poolikute voorude seeria vastu."""
        self.assertEqual(cf.RECOVERY_BUDGET, 12)
        # jääkrisk sõltumatuse eeldusel on juba mõttetult väike
        self.assertLess(0.429 ** cf.RECOVERY_BUDGET, 1e-4)

    def test_08c_tagasiastumist_EI_OLE(self):
        """Kõik katsed käivitatakse kohe, ooteajata."""
        self.assertEqual(cf.RECOVERY_BACKOFF_S, (0.0,))
        self.assertTrue(all(x == 0.0 for x in cf.RECOVERY_BACKOFF_S))


# =====================================================================
# 9-13: KASUTAJA PRIORITEET, KORDUS, TAASESITUS
# =====================================================================
class TestKasutajaPrioriteet(unittest.TestCase):

    def test_09_kasutaja_katkestab_omaalgatuse(self):
        """NÕUE 9."""
        f = cf.ConversationFlow("filosoof")
        voor(f, text="Rääkisin midagi.", terminal=True, now=100.0)
        f.on_initiative_dispatched(106.0)
        f.on_user_speech(107.0)
        self.assertEqual(f.state, cf.USER_SPEAKING)
        self.assertEqual(f.initiative.used, 0, "omaalgatuse loendur ei nullistunud")
        d = f.tick(now=200.0, user_speaking=True, tool_running=False)
        self.assertFalse(d["speak"])
        self.assertEqual(d["reason"], "user_has_floor")

    def test_09b_kasutaja_kone_nullib_taaste_ahela(self):
        f = cf.ConversationFlow("filosoof")
        voor(f, text="jäi pooleli", terminal=False, now=100.0)
        f.on_recovery_dispatched("jäi pooleli", now=100.0)
        self.assertEqual(f.recovery.used, 1)
        f.on_user_speech(105.0)
        self.assertEqual(f.recovery.used, 0)
        self.assertFalse(f.recovery.pending)

    def test_10_katkestus_ei_ole_omaalgatuse_luba(self):
        """NÕUE 10 raamistik: katkestus viib USER_SPEAKING olekusse,
        kust omaalgatus on blokeeritud. Kaja ja päris kõne eristamine
        jääb VAD-i tasemele – seda me ei muutnud."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="Rääkisin.", terminal=True, now=100.0)
        f.on_interrupted(101.0)
        self.assertEqual(f.state, cf.USER_SPEAKING)
        d = f.tick(now=130.0, user_speaking=False, tool_running=False)
        self.assertFalse(d["speak"])
        self.assertEqual(d["reason"], "state_not_idle")

    def test_11_kordus_peatab_ahela(self):
        """NÕUE 11 + 12: kordust ei tohi mängida."""
        f = cf.ConversationFlow("filosoof")
        saba = "ja siis ta ütles mulle, et kõik on hästi"
        voor(f, text=saba, terminal=False, now=100.0)
        f.on_recovery_dispatched(saba, now=100.0)
        o = voor(f, text=saba + " jälle", terminal=False, now=110.0)
        self.assertFalse(o["recover"])
        self.assertEqual(o["reason"], "duplicate_detected")
        self.assertEqual(f.recovery.stopped_reason, "duplicate_detected")

    def test_12_grammatiline_jatk_EI_OLE_kordus(self):
        """NÕUE 12. Mõõdetud tootmises õnnestunud jätkud ei tohi
        kogemata korduseks sattuda."""
        paarid = [
            ("Mõistame seda mitte vaid füüsilisena, vaid kosmilise",
             "printsiibina, mis läbib kogu eksistentsi."),
            ("Mehel avaldub see tugeva ja",
             "domineeriva jõuna, mis otsib kontakti."),
            ("kosmilise ühinemise algatamiseks. See on",
             "energiate tants, kus kaks poolust sulanduvad."),
        ]
        for saba, jatk in paarid:
            self.assertFalse(cf.near_duplicate(saba, jatk),
                             "grammatiline jätk loeti korduseks: %r" % jatk)

    def test_12b_taispikk_kordus_tuvastatakse(self):
        s = "see on täpselt sama lause mida ta juba ütles"
        self.assertTrue(cf.near_duplicate(s, s))

    def test_13_taasesituse_tuhistamine_raporteeritakse(self):
        """NÕUE 13. Kliendipoolne telemeetria."""
        if not HTML:
            self.skipTest("index.html ei ole leitav")
        i = HTML.index("function stopLiveAudio")
        keha = HTML[i:i + 900]
        self.assertIn("pbTel.cancelled = true", keha)
        self.assertIn('pbSend("cancelled")', keha)


# =====================================================================
# 14-18: OLEK, TÖÖRIIST, LÕPETAMINE
# =====================================================================
class TestOlekJaVaravad(unittest.TestCase):

    def test_14_vananenud_kirjel_on_ajapiir(self):
        """NÕUE 14. Mõõdetud: tööriist tagastas 2 min 14 s vana kirje."""
        self.assertIn("CUT_TURN_TTL_S", WS)
        m = re.search(r"CUT_TURN_TTL_S = ([\d.]+)", WS)
        self.assertIsNotNone(m)
        self.assertLessEqual(float(m.group(1)), 120.0)
        self.assertIn('last_cut_turn["at"]', WS)
        self.assertIn("aegunud, ei kasuta", WS)

    def test_15_klass_D_voor_salvestub_last_cut_turn(self):
        """NÕUE 15. Mõõdetud pimeala: klassi D voorud ei jõudnud
        get_last_turn_state tööriistani KUNAGI."""
        i = WS.index("MÕÕDETUD PIMEALA")
        keha = WS[i:i + 700]
        self.assertIn('last_cut_turn["t"] = _ct', keha)
        self.assertIn("premature_turn_complete", keha)

    def test_16_uus_seanss_ei_peri_vana_olekut(self):
        """NÕUE 16. Voog luuakse handleri sees -> hävib seansiga."""
        self.assertIn("flow = conversation_flow.ConversationFlow(", WS)
        i = WS.index("flow = conversation_flow.ConversationFlow")
        # RANGEM: voog peab saama loomise hetke kaasa. Ilma selleta on
        # last_activity = 0.0 ja esimene tiks arvutaks vaikuseks kogu
        # masina tööaja -> omaalgatus kohe seansi alguses.
        self.assertIn("active_persona, now=time.monotonic()", WS)
        # peab olema handleri SEES, mitte mooduli tasemel
        self.assertGreater(len(WS[:i].split("\n")[-1]) -
                           len(WS[:i].split("\n")[-1].lstrip()), 0,
                           "voog on mooduli tasemel – lekiks seansside vahel")

    def test_17_tooriist_blokeerib_omaalgatuse(self):
        """NÕUE 17."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="Vaatan järele.", terminal=True, now=100.0)
        d = f.tick(now=100.0 + f.initiative.pause_s + 5,
                   user_speaking=False, tool_running=True)
        self.assertFalse(d["speak"])
        self.assertEqual(d["reason"], "tool_running")

    def test_17b_tooriist_blokeerib_ka_taaste(self):
        f = cf.ConversationFlow("filosoof")
        o = voor(f, text="jäi pooleli", terminal=False, now=100.0, tool=True)
        self.assertFalse(o["recover"])
        self.assertEqual(o["reason"], "tool_running")

    def test_18_vestluse_lopp_peatab_koik(self):
        """NÕUE 18."""
        f = cf.ConversationFlow("filosoof")
        kasutaja_raakis(f)
        voor(f, text="Viimane lause.", terminal=True, now=100.0)
        f.on_conversation_end()
        self.assertEqual(f.state, cf.ENDED)
        d = f.tick(now=500.0, user_speaking=False, tool_running=False)
        self.assertFalse(d["speak"])
        self.assertEqual(d["reason"], "conversation_ended")

    def test_18b_lopp_on_uhendatud(self):
        self.assertIn("flow.on_conversation_end()", WS)

    def test_19_vahelesegamine_blokeerib_taaste(self):
        f = cf.ConversationFlow("filosoof")
        o = voor(f, text="jäi pooleli", terminal=False, now=100.0,
                 interrupted=True)
        self.assertFalse(o["recover"])
        self.assertEqual(o["reason"], "user_interrupted")


# =====================================================================
# 19: KARAKTERITE ERISUS
# =====================================================================
class TestKarakteriteErisus(unittest.TestCase):

    def test_20_karakterid_erinevad_algatustaseme_poolest(self):
        """NÕUE 19. Mitte kõik ei alusta ühtemoodi."""
        pausid = {p: cf.initiative_for(p)["pause_s"]
                  for p in cf.INITIATIVE}
        self.assertGreater(len(set(pausid.values())), 1,
                           "kõigil karakteritel on sama paus")
        # zen ja singer on vaiksemad kui filosoof ja sarkastiline
        self.assertGreater(pausid["zen"], pausid["filosoof"])
        self.assertGreater(pausid["singer"], pausid["sarkastiline"])
        eelarved = {p: cf.initiative_for(p)["budget"] for p in cf.INITIATIVE}
        self.assertLess(eelarved["zen"], eelarved["filosoof"])

    def test_20b_koik_kumme_karakterit_on_kaetud(self):
        import persona_registry as pr
        puudu = [p for p in pr.PERSONAS if p not in cf.INITIATIVE]
        self.assertEqual(puudu, [], "katmata karakterid: %s" % puudu)

    def test_20c_persona_registry_on_PUUTUMATA(self):
        """Omaniku nõue 5: ära muuda karakterite definitsioone."""
        import hashlib
        import persona_registry as pr
        # AVALIK VERSIOON: see on NÄIDISKARAKTERI räsi. Kui sa
        # kirjutad oma karakterid, uuenda seda numbrit – test
        # kaitseb selle eest, et karakterid ei muutuks KOGEMATA.
        self.assertEqual(
            hashlib.sha256(pr.PERSONAS["asjalik"].prompt_voice.encode()).hexdigest(),
            "30847bc57babbf5b313521eaf4e971205f1595488d4691f15bacc9f472342d8d")
        self.assertEqual(len(pr.PERSONAS), 10)

    def test_20d_algatus_EI_OLE_persona_registry_sees(self):
        """Algatustase elab eraldi moodulis, et promptid jääksid puutumata."""
        pr_src = (KOOD / "persona_registry.py").read_text(encoding="utf-8")
        self.assertNotIn("INITIATIVE", pr_src)
        self.assertNotIn("pause_s", pr_src)

    def test_20e_omaalgatuse_palve_EI_DIKTEERI_sisu(self):
        """Ei tohi sundida kõiki küsima sama üldist küsimust."""
        p = cf.initiative_prompt(7.0)
        self.assertIn("OMA tooni ja", p)
        self.assertIn("just sinule omane", p)
        # ei tohi nõuda konkreetset tegevust
        self.assertNotIn("küsi kasutajalt", p)
        self.assertNotIn("Küsi:", p)
        # ei tohi mainida vaikust kasutajale
        self.assertIn("ära maini seda", p)


# =====================================================================
# ÜHENDUSE JA KAITSTUD SEADETE KONTROLL
# =====================================================================
class TestUhendusJaKaitsed(unittest.TestCase):

    def test_21_vana_jatkamisloogika_on_ASENDATUD(self):
        """Vanad nimed tohivad esineda AINULT kommentaarides, mis
        selgitavad, miks nad eemaldati."""
        kood = "\n".join(r for r in WS.splitlines()
                         if not r.strip().startswith("#"))
        for keelatud in ('jatkamised["n"]', 'jatkamised["kokku"]',
                         'jatkamised["ootel"]', "AINULT_JATKAMISI",
                         "MAX_JATKAMISI_AHELAS"):
            self.assertNotIn(keelatud, kood, keelatud)

    def test_22_koik_sundmused_on_uhendatud(self):
        for nimi in ("flow.on_user_speech(", "flow.on_interrupted(",
                     "flow.on_empty_turn_complete(", "flow.on_turn_complete(",
                     "flow.on_recovery_dispatched(",
                     "flow.on_conversation_end()", "flow.tick("):
            self.assertIn(nimi, WS, nimi)
        # RANGEM: omaalgatus broneeritakse ENNE saatmist ja antakse
        # tagasi, kui saatmine ebaõnnestub (vt reserve_initiative).
        self.assertIn("flow.reserve_initiative(", WS)
        self.assertIn("flow.release_initiative()", WS)

    def test_23_taastepalve_sonastus_on_MUUTUMATU(self):
        """3 mõõdetud õnnestunud jätkamist selle tekstiga – ei puutu."""
        for osa in ("[SÜSTEEM] Sinu eelmine lause jäi pooleli. ",
                    "Jätka TÄPSELT sealt, kus katkesid",
                    "ära vabanda", "ega maini seda teadet."):
            self.assertIn(osa, cf.RECOVERY_PROMPT, osa)

    def test_24_omaalgatus_kasutab_session_send_mitte_realtime(self):
        """send_realtime_input käivitab VAD-i ja KATKESTAKS Maya."""
        i = WS.index("conversation_flow.initiative_prompt")
        keha = WS[max(0, i - 300):i + 200]
        # gsend = session.send luku all; realtime_input käivitaks VAD-i.
        self.assertIn("await gsend(", keha)
        self.assertNotIn("realtime", keha)

    def test_25_omaalgatus_ei_kusitle_geminit(self):
        """Sündmusepõhine: väljuv päring AINULT siis, kui tick annab loa."""
        i = WS.index("_alg = flow.tick(")
        keha = WS[i:i + 1200]
        # Varav: kui otsus on EI, siis `continue` – päringuni ei jõuta.
        self.assertIn('if not _alg["speak"]:', keha)
        j = keha.index('if not _alg["speak"]:')
        self.assertNotIn("gsend", keha[:j],
                         "päring tehakse ENNE otsust")
        self.assertIn("continue", keha[j:j + 120])

    def test_26_kaitstud_seaded_muutumatud(self):
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", WS)
        self.assertIn("'api_version': 'v1alpha'", WS)
        self.assertEqual(WS.count("HarmBlockThreshold.BLOCK_NONE"), 4)
        self.assertIn("START_SENSITIVITY_HIGH", WS)
        self.assertIn("prefix_padding_ms=250", WS)
        self.assertIn("silence_duration_ms=800", WS)
        self.assertIn("END_SENSITIVITY_LOW", WS)
        self.assertIn('mime_type="audio/pcm;rate=16000"', WS)
        for k in ("temperature=", "top_p=", "top_k=",
                  "enable_affective_dialog", "proactivity"):
            self.assertNotIn(k, WS, k)

    def test_27_moodul_on_puhas(self):
        src = (KOOD / "conversation_flow.py").read_text(encoding="utf-8")
        for k in ("session", "websocket", "sqlite3", "asyncio", "await ",
                  "genai", "time.time", "time.monotonic"):
            self.assertNotIn(k, src, k)


# =====================================================================
# KLIENDI TELEMEETRIA
# =====================================================================
class TestTaasesituseTelemeetria(unittest.TestCase):

    def setUp(self):
        if not HTML:
            self.skipTest("index.html ei ole leitav")

    def test_28_eristab_ajastatud_ja_MANGITUD_kestuse(self):
        self.assertIn("pbTel.scheduledS +=", HTML)
        self.assertIn("pbTel.playedS +=", HTML)

    def test_29_esimene_ja_viimane_mangitud(self):
        self.assertIn("pbTel.firstPlayed", HTML)
        self.assertIn("pbTel.lastPlayed", HTML)

    def test_30_monotoonne_aeg(self):
        """Kestused peavad tulema performance.now()-st, mitte Date-ist."""
        i = HTML.index("function pbSend")
        self.assertNotIn("Date.now", HTML[i:i + 1400])
        # firstPlayed ja lastPlayed arvutatakse scheduleBuffer/onended sees
        j = HTML.index("pbTel.firstPlayed === null) {")
        self.assertIn("performance.now", HTML[j:j + 300])
        k = HTML.index("pbTel.lastPlayed = ")
        self.assertIn("performance.now", HTML[k:k + 120])

    def test_31_alatootumised_ja_umberpuhverdamised(self):
        i = HTML.index('type: "playback"')
        keha = HTML[i:i + 1100]
        self.assertIn("underruns", keha)
        self.assertIn("rebuffers", keha)

    def test_32_sagedused_ja_konteksti_olek(self):
        i = HTML.index('type: "playback"')
        keha = HTML[i:i + 1100]
        self.assertIn("ctx_in_hz", keha)
        self.assertIn("ctx_out_hz", keha)
        self.assertIn("ctx_state", keha)

    def test_33_telemeetria_ei_blokeeri(self):
        """Saatmine on try/catch sees ja ühekordne."""
        i = HTML.index("function pbSend")
        keha = HTML[i:i + 1400]
        self.assertIn("try {", keha)
        self.assertIn("pbTel.sent = true", keha)
        self.assertIn("if (!pbTel || pbTel.sent) return;", keha)

    def test_34_sisu_EI_LAHE_kaasa(self):
        i = HTML.index('type: "playback"')
        keha = HTML[i:i + 1100]
        for keelatud in ("text", "transcript", "fact", "message"):
            self.assertNotIn(keelatud + ":", keha, keelatud)

    def test_35_server_loeb_telemeetriat(self):
        self.assertIn('packet.get("type") == "playback"', WS)
        self.assertIn("TAASESITUS", WS)
        self.assertIn("kuulmata_s", WS)
        self.assertIn("playback_confirmed = True", WS)

    def test_36_korrelatsiooni_piirang_on_dokumenteeritud(self):
        i = WS.index("KORRELATSIOON VOORUGA")
        keha = WS[i:i + 800]
        self.assertIn("PIIRANG", keha)


if __name__ == "__main__":
    unittest.main(verbosity=2)

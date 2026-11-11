#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAMM 1: Gemini Live lõpetamise metaandmete testid.

AUSUS: siin EI OLE ÜHTEGI PÄRIS GEMINI KUTSET. Testid jäljendavad
`LiveServerMessage` / `LiveServerContent` kuju duck-typinguga, mis
vastab paigaldatud SDK-le (google-genai 2.33.0, väljad kontrollitud
tootmishostis `model_fields` kaudu). Need tõestavad, et logimine on
erindikindel ja et puuduv väli märgitakse puuduvaks – MITTE seda,
mida Gemini backend tegelikult saadab.
"""
import ast
import importlib.util
import pathlib
import sys
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent
KOOD = JUUR / "server"
WS_TEE = KOOD / "live_maya_ws.py"
WS = WS_TEE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Puhtad funktsioonid loetakse lähtekoodist isoleeritud nimeruumi:
# `live_maya_ws.py` ise ei ole imporditav (google.genai puudub).
# ---------------------------------------------------------------------
def laadi_puhtad():
    puu = ast.parse(WS)
    tahetud = {"META_PUUDUB", "_enum_valja", "_modaalsuse_tokenid",
               "usage_snapshot", "gemini_meta_snapshot", "meta_on_sisukas"}
    kogutud = []
    for n in puu.body:
        if isinstance(n, ast.FunctionDef) and n.name in tahetud:
            kogutud.append(n)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in tahetud:
                    kogutud.append(n)
    ns = {}
    exec(compile(ast.Module(body=kogutud, type_ignores=[]), "<meta>", "exec"),
         ns)
    puudu = tahetud - set(ns)
    assert not puudu, f"lähtekoodist ei leitud: {puudu}"
    return ns


M = laadi_puhtad()
META_PUUDUB = M["META_PUUDUB"]
snapshot = M["gemini_meta_snapshot"]
sisukas = M["meta_on_sisukas"]
usage = M["usage_snapshot"]


# --- jäljendid, mis vastavad SDK kujule ------------------------------
class Enum:
    def __init__(self, nimi, vaartus):
        self.name = nimi
        self.value = vaartus


class Modaalsus:
    def __init__(self, nimi, arv):
        self.modality = Enum(nimi, nimi)
        self.token_count = arv


class Usage:
    def __init__(self, **kw):
        self.prompt_token_count = kw.get("prompt")
        self.response_token_count = kw.get("response")
        self.thoughts_token_count = kw.get("thoughts")
        self.cached_content_token_count = kw.get("cached")
        self.total_token_count = kw.get("total")
        self.prompt_tokens_details = kw.get("pd")
        self.response_tokens_details = kw.get("rd")


class SC:
    """LiveServerContent jäljend – kõik väljad vaikimisi None."""

    def __init__(self, **kw):
        for nimi in ("model_turn", "turn_complete", "interrupted",
                     "grounding_metadata", "generation_complete",
                     "input_transcription", "output_transcription",
                     "url_context_metadata", "turn_complete_reason",
                     "waiting_for_input", "interim_input_transcription",
                     "interaction_status"):
            setattr(self, nimi, kw.get(nimi))


class Msg:
    """LiveServerMessage jäljend."""

    def __init__(self, **kw):
        for nimi in ("setup_complete", "server_content", "tool_call",
                     "tool_call_cancellation", "usage_metadata", "go_away",
                     "session_resumption_update",
                     "voice_activity_detection_signal", "voice_activity"):
            setattr(self, nimi, kw.get(nimi))


# =====================================================================
class TestPuuduvadValjad(unittest.TestCase):

    def test_01_tyhi_sonum_ei_viska_erindit(self):
        m = snapshot(None, None)
        self.assertIsInstance(m, dict)
        self.assertNotIn("snapshot_viga", m)

    def test_02_puuduv_valja_on_puudub_mitte_False(self):
        """Mõõdetud: turn_complete_reason oli NULL ka normaalse
        lõpetamise korral. Puuduv väli EI OLE tõend."""
        m = snapshot(Msg(server_content=SC()), SC())
        for k in ("turn_complete", "generation_complete", "interrupted",
                  "waiting_for_input", "turn_complete_reason",
                  "interaction_status", "usage", "go_away_time_left",
                  "vad_signal", "voice_activity"):
            self.assertEqual(m[k], META_PUUDUB, k)
        self.assertIsNot(m["turn_complete"], False)

    def test_03_puuduv_meta_ei_ole_sisukas(self):
        self.assertFalse(sisukas(snapshot(Msg(), SC())))

    def test_04_objekt_ilma_ykskoigi_valjata(self):
        class Tyhi:
            pass
        m = snapshot(Tyhi(), Tyhi())
        self.assertNotIn("snapshot_viga", m)
        self.assertFalse(sisukas(m))


class TestOotamatudVaartused(unittest.TestCase):

    def test_05_enum_ilma_nime_ja_vaartust(self):
        class Imelik:
            def __str__(self):
                return "IMELIK_ENUM"
        sc = SC(turn_complete_reason=Imelik())
        m = snapshot(Msg(server_content=sc), sc)
        self.assertEqual(m["turn_complete_reason"], "IMELIK_ENUM")
        self.assertTrue(sisukas(m))

    def test_06_vale_tyyp_booleani_asemel(self):
        sc = SC(turn_complete="jah", generation_complete=1,
                waiting_for_input=[])
        m = snapshot(Msg(server_content=sc), sc)
        self.assertIs(m["turn_complete"], True)
        self.assertIs(m["generation_complete"], True)
        self.assertIs(m["waiting_for_input"], False)   # tühi list -> False

    def test_07_usage_mis_viskab_atribuudi_juures(self):
        class Paha:
            @property
            def prompt_token_count(self):
                raise RuntimeError("SDK muutus")
        v = usage(Paha())
        self.assertTrue(str(v).startswith("viga:"), v)

    def test_08_modaalsuste_loend_on_prygi(self):
        u = Usage(prompt=10, rd=["mitte-objekt"])
        v = usage(u)
        self.assertEqual(v["vastuse_modaalsused"], META_PUUDUB)

    def test_09_snapshot_erind_jaadvustatakse_mitte_ei_leki(self):
        class PahaSC:
            @property
            def turn_complete(self):
                raise RuntimeError("katki")
        m = snapshot(Msg(), PahaSC())
        self.assertIn("snapshot_viga", m)
        self.assertTrue(sisukas(m), "vigast snapshotti peab logima")


class TestSisukasValjavote(unittest.TestCase):

    def test_10_turvapohjus_jaadvustub_nime_JA_vaartusega(self):
        sc = SC(turn_complete=True,
                turn_complete_reason=Enum("GENERATED_AUDIO_SAFETY", 16))
        m = snapshot(Msg(server_content=sc), sc)
        self.assertEqual(m["turn_complete_reason"],
                         {"nimi": "GENERATED_AUDIO_SAFETY", "vaartus": 16})
        self.assertTrue(sisukas(m))

    def test_11_tokeniloendurid_ja_modaalsused(self):
        u = Usage(prompt=1018, response=499, thoughts=120, total=1517,
                  pd=[Modaalsus("TEXT", 1000), Modaalsus("AUDIO", 18)],
                  rd=[Modaalsus("AUDIO", 450), Modaalsus("TEXT", 49)])
        m = snapshot(Msg(usage_metadata=u), SC())
        self.assertEqual(m["usage"]["prompt"], 1018)
        self.assertEqual(m["usage"]["thoughts"], 120)
        self.assertEqual(m["usage"]["vastuse_modaalsused"],
                         {"AUDIO": 450, "TEXT": 49})
        self.assertTrue(sisukas(m))

    def test_12_go_away_ja_vad_signaalid(self):
        class GA:
            time_left = "5s"
        m = snapshot(Msg(go_away=GA()), SC())
        self.assertEqual(m["go_away_time_left"], "5s")
        self.assertTrue(sisukas(m))

        class VS:
            vad_signal_type = Enum("START_OF_SPEECH", 1)
        m2 = snapshot(Msg(voice_activity_detection_signal=VS()), SC())
        self.assertEqual(m2["vad_signal"]["nimi"], "START_OF_SPEECH")
        self.assertTrue(sisukas(m2))

    def test_13_generation_complete_ilma_pohjust(self):
        """MÕÕDETUD TOOTMISJUHTUM: generation_complete=True, kõik
        ülejäänud väljad puuduvad. Peab olema logitav JA mitte
        tõlgendatav turvapeatusena."""
        sc = SC(generation_complete=True)
        m = snapshot(Msg(server_content=sc), sc)
        self.assertIs(m["generation_complete"], True)
        self.assertEqual(m["turn_complete_reason"], META_PUUDUB)
        self.assertTrue(sisukas(m))


class TestVastavusSDKle(unittest.TestCase):
    """Väljad on kontrollitud paigaldatud SDK `model_fields` vastu."""

    SDK_LIVE_SERVER_CONTENT = {
        "model_turn", "turn_complete", "interrupted", "grounding_metadata",
        "generation_complete", "input_transcription", "output_transcription",
        "url_context_metadata", "turn_complete_reason", "waiting_for_input",
        "interim_input_transcription", "interaction_status"}
    SDK_LIVE_SERVER_MESSAGE = {
        "setup_complete", "server_content", "tool_call",
        "tool_call_cancellation", "usage_metadata", "go_away",
        "session_resumption_update", "voice_activity_detection_signal",
        "voice_activity"}

    def test_14_loetud_valjad_on_SDK_s_olemas(self):
        for nimi in ("turn_complete", "generation_complete", "interrupted",
                     "waiting_for_input", "turn_complete_reason",
                     "interaction_status"):
            self.assertIn(nimi, self.SDK_LIVE_SERVER_CONTENT, nimi)
        for nimi in ("usage_metadata", "go_away",
                     "voice_activity_detection_signal", "voice_activity"):
            self.assertIn(nimi, self.SDK_LIVE_SERVER_MESSAGE, nimi)

    def test_15_logija_on_erindikindel_ja_ilma_await_ita(self):
        i = WS.index("def _logi_gemini_meta(")
        keha = WS[i:i + 2600]
        self.assertIn("try:", keha)
        self.assertIn("except Exception as _me:", keha)
        self.assertNotIn("await", keha, "logimine ei tohi blokeerida")
        self.assertNotIn("session.send", keha, "logimine ei tohi API-t kutsuda")

    def test_16_puhtad_funktsioonid_ei_tee_IO_d_ega_API_kutseid(self):
        puu = ast.parse(WS)
        for n in puu.body:
            if isinstance(n, ast.FunctionDef) and n.name in (
                    "gemini_meta_snapshot", "usage_snapshot",
                    "meta_on_sisukas", "_enum_valja", "_modaalsuse_tokenid"):
                src = ast.unparse(n)
                for keelatud in ("print(", "open(", "await", "session",
                                 "sqlite3", "requests"):
                    self.assertNotIn(keelatud, src, f"{n.name}: {keelatud}")

    def test_17_konksud_on_koigi_oluliste_sundmuste_kyljes(self):
        for s in ('_logi_gemini_meta("sonum"',
                  '_logi_gemini_meta("generation_complete"',
                  '_logi_gemini_meta("turn_complete"',
                  '_logi_gemini_meta("interrupted"'):
            self.assertIn(s, WS, s)

    def test_18_logirida_sisaldab_koiki_noutud_tunnuseid(self):
        i = WS.index("def _logi_gemini_meta(")
        keha = WS[i:i + 2600]
        for v in ('"seanss"', '"voor"', '"aeg"', '"karakter"', '"mudel"',
                  '"sundmus"', '"heli_s"', '"heli_juba_tehtud"',
                  '"meie_hinnang"', '"meta"'):
            self.assertIn(v, keha, v)

    def test_19_ei_logi_heli_ega_votmeid(self):
        i = WS.index("def _logi_gemini_meta(")
        keha = WS[i:i + 2600]
        for keelatud in ("inline_data", "API_KEY", "api_key", "GEMINI_API"):
            self.assertNotIn(keelatud, keha, keelatud)

    def test_20_mudeli_konstant_ja_connect_rida_on_sunkroonis(self):
        """Dubleeritud mudelinimi ei tohi lahku joosta."""
        i = WS.index('LIVE_MUDEL = "')
        konstant = WS[i:].split('"')[1]
        j = WS.index("live.connect(model=")
        connect = WS[j:].split('"')[1]
        self.assertEqual(konstant, connect)


if __name__ == "__main__":
    print("=" * 70)
    print("SAMM 1: GEMINI META TELEMEETRIA TESTID (jäljendatud SDK kuju)")
    print("PÄRIS GEMINI KUTSEID EI OLE.")
    print("=" * 70)
    unittest.main(verbosity=2)

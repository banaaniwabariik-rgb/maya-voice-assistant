# -*- coding: utf-8 -*-
"""Testid: krediidi jäägi käsitsi haldamine (billing_admin.py).

Kasutab AINULT ajutisi faile. Tootmise billing_state.json't ei puudutata.
KÄIVITAMINE: python3 tests_krediidi_haldus.py
"""

import json
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "server"))
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "server"))
import billing_admin as ba

TOOL = str(BASE / "server" / "billing_admin.py")


def aja(args, fail):
    """Käivitab tööriista eraldi protsessis, nagu päriselt."""
    return subprocess.run(
        [sys.executable, TOOL, "--file", fail, "--yes"] + args,
        capture_output=True, text=True)


class TestHaldus(unittest.TestCase):

    def setUp(self):
        self.f = tempfile.mktemp(suffix=".json")
        with open(self.f, "w", encoding="utf-8") as fh:
            json.dump({"currency": "€", "current_balance": 0.2907,
                       "initial_credit": 5.0, "baseline_spent": 1.65,
                       "total_sessions": 155,
                       "total_bytes_in": 373320655,
                       "total_bytes_out": 283706880}, fh)

    def tearDown(self):
        for p in (self.f, self.f + ".tmp"):
            if os.path.exists(p):
                os.unlink(p)

    def loe(self):
        with open(self.f, encoding="utf-8") as fh:
            return json.load(fh)

    # --- PÕHIFUNKTSIOONID ---------------------------------------------
    def test_01_set_maarab_tapse_jaagi(self):
        r = aja(["--set", "5.02", "--note", "Google krediit laetud"], self.f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.loe()["current_balance"], 5.02)

    def test_02_add_liidab(self):
        aja(["--add", "5.00"], self.f)
        self.assertAlmostEqual(self.loe()["current_balance"], 5.2907, places=4)

    def test_03_ajalugu_salvestub(self):
        aja(["--set", "5.02", "--note", "esimene"], self.f)
        aja(["--add", "1.00", "--note", "teine"], self.f)
        aj = self.loe()["adjustments"]
        self.assertEqual(len(aj), 2)
        self.assertEqual(aj[0]["type"], "set")
        self.assertEqual(aj[0]["note"], "esimene")
        self.assertEqual(aj[0]["balance_before"], 0.2907)
        self.assertEqual(aj[0]["balance_after"], 5.02)
        self.assertEqual(aj[1]["type"], "add")
        self.assertEqual(aj[1]["balance_after"], 6.02)

    def test_04_muud_valjad_sailivad(self):
        aja(["--set", "5.02"], self.f)
        d = self.loe()
        self.assertEqual(d["total_sessions"], 155)
        self.assertEqual(d["total_bytes_in"], 373320655)
        self.assertEqual(d["initial_credit"], 5.0)
        self.assertEqual(d["currency"], "€")

    # --- KAITSED ------------------------------------------------------
    def test_05_negatiivne_keelatud(self):
        r = aja(["--set", "-1"], self.f)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.loe()["current_balance"], 0.2907)

    def test_06_napuviga_50_asemel_5(self):
        """MAX_BALANCE kaitseb näpuvea eest."""
        r = aja(["--set", "5000"], self.f)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("piiri", r.stderr)
        self.assertEqual(self.loe()["current_balance"], 0.2907)

    def test_07_add_null_voi_negatiivne_keelatud(self):
        for v in ("0", "-5"):
            r = aja(["--add", v], self.f)
            self.assertNotEqual(r.returncode, 0, v)
        self.assertEqual(self.loe()["current_balance"], 0.2907)

    def test_08_add_ulemaar_keelatud(self):
        r = aja(["--add", "300"], self.f)
        self.assertNotEqual(r.returncode, 0)

    def test_09_set_null_on_lubatud(self):
        """Jäägi nullimine on legitiimne korrektuur."""
        r = aja(["--set", "0"], self.f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.loe()["current_balance"], 0.0)

    # --- ATOMAARSUS ---------------------------------------------------
    def test_10_ajutist_faili_ei_jaa_maha(self):
        aja(["--set", "5.02"], self.f)
        self.assertFalse(os.path.exists(self.f + ".tmp"))

    def test_11_lugemine_ei_muuda_faili(self):
        enne = open(self.f, encoding="utf-8").read()
        aja(["--show"], self.f)
        aja(["--history"], self.f)
        self.assertEqual(open(self.f, encoding="utf-8").read(), enne)

    def test_12_ajalugu_piiratud_100ga(self):
        seis = {"currency": "€", "current_balance": 1.0,
                "adjustments": [{"at": f"x{i}", "type": "add", "amount": 1,
                                 "balance_before": 0, "balance_after": 1,
                                 "note": ""} for i in range(120)]}
        ba.lisa_ajalukku(seis, "set", 5.02, 1.0, 5.02, "test")
        self.assertEqual(len(seis["adjustments"]), 100)
        self.assertEqual(seis["adjustments"][-1]["note"], "test")

    def test_13_puuduv_fail_ei_kuku_kokku(self):
        puudub = tempfile.mktemp(suffix=".json")
        r = aja(["--show"], puudub)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(puudub), "--show lõi faili!")


class TestVoistlusolukord(unittest.TestCase):
    """save_session() peab välise korrektuuri ALLES jätma.

    MÕÕDETUD DISAINIVIGA: LiveCostTracker luges faili seansi ALGUSES ja
    kirjutas lõpus oma mälus oleva koopia pealt. Korrektuur keset kõnet
    oleks vaikselt kadunud.
    """

    def test_14_save_session_loeb_varske_seisu(self):
        src = (BASE / "server" / "live_maya_ws.py").read_text(encoding="utf-8")
        i = src.index("def save_session(self):")
        keha = src[i:i + 2200]
        self.assertIn("varske = self._load_state()", keha,
                      "save_session ei loe faili uuesti")
        self.assertIn("vana_bal = varske.get", keha,
                      "arvutus ei lähtu värskest väärtusest")
        # vanad total_* read ei tohi enam self.state pealt tulla
        self.assertIn('varske.get("total_sessions", 0)', keha)

    def test_15_tundmatud_valjad_sailivad_save_sessionis(self):
        src = (BASE / "server" / "live_maya_ws.py").read_text(encoding="utf-8")
        i = src.index("def save_session(self):")
        keha = src[i:i + 2200]
        self.assertIn("{**self.state, **varske}", keha,
                      "adjustments ajalugu kirjutataks üle")


class TestDiagnoos(unittest.TestCase):
    """Dokumenteerib mõõdetud juurpõhjuse, et see ei kaoks ära."""

    def test_16_google_billingut_ei_kusita(self):
        """Kontrollitud 09.11.2026: ühtegi viidet Google Billingu API-le.

        AST-põhine: vaatab IMPORTE ja mitte-dokistringi stringe. Esimene
        versioon otsis sõna kogu failist ja püüdis kinni iseenda
        dokistringi, mis SELGITAB, et Billingut ei kasutata.
        """
        import ast
        import glob
        keelatud = ("cloudbilling", "billing.googleapis")
        leitud = []
        for f in sorted(glob.glob(str(BASE / "server" / "*.py"))):
            try:
                puu = ast.parse(open(f, encoding="utf-8").read())
            except SyntaxError:
                continue
            # dokistringid välja: kogume need, et neid ignoreerida
            dokid = set()
            for n in ast.walk(puu):
                if isinstance(n, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
                    d = ast.get_docstring(n, clean=False)
                    if d:
                        dokid.add(d)
            for n in ast.walk(puu):
                if isinstance(n, ast.Import):
                    for al in n.names:
                        if any(k in al.name.lower() for k in keelatud):
                            leitud.append(f"{os.path.basename(f)}: import {al.name}")
                elif isinstance(n, ast.ImportFrom) and n.module:
                    if any(k in n.module.lower() for k in keelatud):
                        leitud.append(f"{os.path.basename(f)}: from {n.module}")
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    if n.value in dokid:
                        continue
                    if any(k in n.value.lower() for k in keelatud):
                        leitud.append(f"{os.path.basename(f)}:{n.lineno}: "
                                      f"string {n.value[:50]!r}")
        self.assertEqual(leitud, [],
                         "Google Billingu API viited leitud: " + str(leitud)
                         + " – kui see lisati teadlikult, uuenda diagnoosi")

    def test_17_jaak_saab_vaheneda_ainult_save_sessionis(self):
        src = (BASE / "server" / "live_maya_ws.py").read_text(encoding="utf-8")
        kirjutamised = src.count('self.state["current_balance"] =')
        self.assertEqual(kirjutamised, 1,
                         "jääki kirjutatakse rohkem kui ühest kohast")


if __name__ == "__main__":
    unittest.main(verbosity=2)

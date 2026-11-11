#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA: krediidi jäägi käsitsi haldamine.

MIKS SEE OLEMAS ON
------------------
Ekraanil olev jääk tuleb failist `data/billing_state.json`, väljalt
`current_balance`. See number saab ainult VÄHENEDA – `LiveCostTracker`
lahutab igast kõnest hinnangulise kulu.

Google Cloud Billingut ei küsita mitte kuskilt. Kontrollitud 09.11.2026:
koodis ei ole ühtegi viidet `cloudbilling` / `billing.googleapis.com`
peale. Seega krediidi laadimine Google'is EI muuda seda numbrit.

See tööriist on ainus viis jääki suurendada või korrigeerida.

KASUTAMINE
----------
  python3 billing_admin.py --show                  praegune seis
  python3 billing_admin.py --set 5.02 --note "..."  määra täpne jääk
  python3 billing_admin.py --add 5.00 --note "..."  liida juurde
  python3 billing_admin.py --history               korrektuuride ajalugu

IGA MUUDATUS LÄHEB AJALUKKU. Ajalugu on faili väljal `adjustments` ja
seda ei kirjutata kunagi üle – `LiveCostTracker.save_session()` säilitab
tundmatud väljad.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Tallinn")
BILLING_FILE = Path(__file__).parent / "data" / "billing_state.json"

# Mõistlikkuse piirid. Ilma nendega võiks näpuviga ("50" vs "5.0")
# kirjutada sisse jäägi, mida ei ole kunagi olnud.
MAX_BALANCE = 500.0
MAX_SINGLE_ADD = 200.0

VAIKESEIS = {"currency": "€", "current_balance": 0.0}


def nyyd() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def loe(path: Path = None) -> dict:
    p = path or BILLING_FILE
    if not p.exists():
        return dict(VAIKESEIS)
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else dict(VAIKESEIS)
    except Exception as e:
        print(f"VIGA: faili ei õnnestu lugeda: {e}", file=sys.stderr)
        sys.exit(2)


def kirjuta(seis: dict, path: Path = None) -> None:
    """Atomaarne kirjutamine: ajutine fail + rename.

    Ilma selleta võib samaaegne kõnelõpp lugeda poolikut faili.
    """
    p = path or BILLING_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seis, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def lisa_ajalukku(seis: dict, tyyp: str, summa, vana: float,
                  uus: float, markus: str) -> None:
    kirjed = seis.get("adjustments")
    if not isinstance(kirjed, list):
        kirjed = []
    kirjed.append({
        "at": nyyd(),
        "type": tyyp,                     # 'set' | 'add'
        "amount": summa,
        "balance_before": round(vana, 4),
        "balance_after": round(uus, 4),
        "note": (markus or "").strip(),
        "by": "billing_admin.py",
    })
    seis["adjustments"] = kirjed[-100:]   # viimased 100 piisab


def naita(seis: dict) -> None:
    cur = seis.get("currency", "€")
    print("  praegune jääk     : %.2f %s" % (seis.get("current_balance", 0.0), cur))
    print("  täpne väärtus     : %s" % seis.get("current_balance"))
    print("  seansse kokku     : %s" % seis.get("total_sessions", "?"))
    sisse = seis.get("total_bytes_in", 0)
    valja = seis.get("total_bytes_out", 0)
    print("  andmemaht         : %.1f MB sisse, %.1f MB välja"
          % (sisse / 1048576, valja / 1048576))
    aj = seis.get("adjustments") or []
    print("  korrektuure       : %d" % len(aj))
    if aj:
        v = aj[-1]
        print("  viimane korrektuur: %s  %s %s  (%.2f -> %.2f)  %s"
              % (v.get("at"), v.get("type"), v.get("amount"),
                 v.get("balance_before", 0), v.get("balance_after", 0),
                 v.get("note", "")))
    # Dekoratiivsed väljad – ütleme välja, et need ei osale arvutustes.
    if "initial_credit" in seis or "baseline_spent" in seis:
        print("  (märkus: 'initial_credit' ja 'baseline_spent' ei osale")
        print("   ühelgi arvutusel – need on ainult info)")


def ajalugu(seis: dict) -> None:
    aj = seis.get("adjustments") or []
    if not aj:
        print("  korrektuure ei ole tehtud")
        return
    print("  %-19s %-5s %8s %8s %8s  märkus" %
          ("aeg", "tüüp", "summa", "enne", "pärast"))
    for v in aj:
        print("  %-19s %-5s %8s %8.2f %8.2f  %s"
              % (v.get("at", "?"), v.get("type", "?"), v.get("amount", "?"),
                 v.get("balance_before", 0), v.get("balance_after", 0),
                 v.get("note", "")))


def main():
    ap = argparse.ArgumentParser(
        description="Maya krediidi jäägi käsitsi haldamine")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true", help="näita praegust seisu")
    g.add_argument("--history", action="store_true", help="korrektuuride ajalugu")
    g.add_argument("--set", type=float, metavar="EUR",
                   help="määra jääk TÄPSELT selleks summaks")
    g.add_argument("--add", type=float, metavar="EUR",
                   help="liida jäägile juurde")
    ap.add_argument("--note", default="", help="põhjendus ajaloo jaoks")
    ap.add_argument("--file", default=None, help="muu failitee (testimiseks)")
    ap.add_argument("--yes", action="store_true",
                    help="ära küsi kinnitust (skriptidele)")
    a = ap.parse_args()

    path = Path(a.file) if a.file else BILLING_FILE
    seis = loe(path)

    if a.show:
        naita(seis)
        return 0
    if a.history:
        ajalugu(seis)
        return 0

    vana = float(seis.get("current_balance", 0.0) or 0.0)

    if a.set is not None:
        if a.set < 0:
            print("VIGA: jääk ei saa olla negatiivne", file=sys.stderr)
            return 2
        if a.set > MAX_BALANCE:
            print(f"VIGA: {a.set} ületab mõistlikkuse piiri {MAX_BALANCE}. "
                  f"Kui see on tõesti õige, muuda MAX_BALANCE.", file=sys.stderr)
            return 2
        uus, tyyp, summa = round(a.set, 4), "set", a.set
    else:
        if a.add <= 0:
            print("VIGA: liidetav summa peab olema positiivne. "
                  "Vähendamiseks kasuta --set.", file=sys.stderr)
            return 2
        if a.add > MAX_SINGLE_ADD:
            print(f"VIGA: {a.add} ületab ühe korra piiri {MAX_SINGLE_ADD}",
                  file=sys.stderr)
            return 2
        uus = round(vana + a.add, 4)
        if uus > MAX_BALANCE:
            print(f"VIGA: tulemus {uus} ületaks piiri {MAX_BALANCE}",
                  file=sys.stderr)
            return 2
        tyyp, summa = "add", a.add

    print("  jääk: %.4f -> %.4f %s  (%s %s)"
          % (vana, uus, seis.get("currency", "€"), tyyp, summa))
    if not a.yes:
        vastus = input("  Kinnitad? [jah/ei] ").strip().lower()
        if vastus not in ("jah", "j", "yes", "y"):
            print("  katkestatud, midagi ei muudetud")
            return 1

    seis["current_balance"] = uus
    lisa_ajalukku(seis, tyyp, summa, vana, uus, a.note)
    kirjuta(seis, path)
    print("  salvestatud.")
    naita(loe(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

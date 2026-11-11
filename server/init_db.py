#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — andmebaaside loomine tühjast.

MIKS SEE OLEMAS ON
------------------
Avalikus versioonis EI OLE kaasas ühtegi andmebaasi – need sisaldaksid
originaalpaigalduse isiklikke meeldetuletusi, vestlusi ja mälufakte.
See skript loob täiesti tühjad andmebaasid õige skeemiga.

MIKS SKEEMI EI OLE KÄSITSI KIRJUTATUD
-------------------------------------
Skeem tuleb moodulite ENDA `init`/`ensure_schema` funktsioonidest, mis
tootmises niikuinii jooksevad. Nii ei saa käsitsi kirjutatud `schema.sql`
koodist lahku joosta. Loodud skeemi saab soovi korral välja kirjutada
(`--dump`), et seda versioonihalduses jälgida.

KASUTAMINE
----------
    python3 init_db.py              # loo andmebaasid, kui puuduvad
    python3 init_db.py --force      # loo uuesti (KUSTUTAB olemasolevad)
    python3 init_db.py --dump       # kirjuta skeem faili schema.sql
    python3 init_db.py --check      # ainult kontrolli, ära muuda midagi
"""

import os
import pathlib
import sqlite3
import sys

SIIN = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SIIN))

import config  # noqa: E402


def _tabelid(tee: str):
    if not os.path.exists(tee):
        return []
    with sqlite3.connect(tee) as c:
        return [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "ORDER BY name").fetchall()]


def loo(force: bool = False) -> dict:
    """Loo mõlemad andmebaasid. Tagastab tabelite loendi mõlema kohta."""
    if force:
        import auth as _a
        for tee in (config.DB_TEE, _a.kasutajate_db_tee()):
            for lisa in ("", "-wal", "-shm"):
                p = pathlib.Path(tee + lisa)
                if p.exists():
                    p.unlink()
                    print(f"  kustutatud: {p.name}")

    pathlib.Path(config.DB_TEE).parent.mkdir(parents=True, exist_ok=True)

    # 1) Põhiandmebaas: meeldetuletused, ostunimekiri, päevik, arhiiv.
    import listen_direct
    listen_direct.init_db()
    print("  listen_direct.init_db()      -> meeldetuletused, ostunimekiri, "
          "päevik, vestlusarhiiv")

    # 2) Mälu: faktid + arhiiv.
    import memory_engine
    memory_engine.init_memory_db()
    print("  memory_engine.init_memory_db() -> mälufaktid, vestlusarhiiv")

    # 3) FTS5 otsinguindeksid + mälu lisaveerud (persona, scope jne).
    import memory_fts
    with sqlite3.connect(config.DB_TEE, timeout=10) as conn:
        tulem = memory_fts.ensure_schema(conn)
    print(f"  memory_fts.ensure_schema()   -> {tulem}")

    # 3b) HILISEMAD VEERUD. Tootmises lisandusid need ALTER-iga aja
    #     jooksul, nii et `listen_direct.init_db()` CREATE-lause neid
    #     ei sisalda. Ilma nendeta kukub `/api/reminders` värskes
    #     paigalduses läbi veaga "no such column: repeat_type".
    lisa_puuduvad_veerud()

    # 4) Kasutajate register (autentimine) – ERALDI andmebaasis,
    #    mis ei kuulu ühelegi kasutajale.
    import auth
    auth.ensure_schema()
    print(f"  auth.ensure_schema()         -> kasutajad, tokenid "
          f"({auth.kasutajaid_kokku()} kontot)")

    # 5) Kasutaja seaded (nimi jne).
    import user_profile
    with sqlite3.connect(config.DB_TEE, timeout=10) as conn:
        user_profile.ensure_schema(conn)
    print("  user_profile.ensure_schema() -> seaded")

    return {"reminders.db": _tabelid(config.DB_TEE),
            "users.db": _tabelid(auth.kasutajate_db_tee())}


# Veerud, mis tootmises lisandusid ALTER TABLE'iga pärast esialgset
# CREATE'i. Hoiame neid ÜHES kohas, et värske paigaldus saaks sama
# skeemi, mis töötaval installatsioonil.
HILISEMAD_VEERUD = {
    "reminders": [
        ("repeat_type", "TEXT DEFAULT 'none'"),
        ("custom_speech", "TEXT DEFAULT ''"),
        ("notify_type", "TEXT DEFAULT 'call'"),
        ("persona", "TEXT DEFAULT ''"),
    ],
}


def lisa_puuduvad_veerud(tee: str = None) -> list:
    """Lisa puuduvad veerud. Idempotentne – olemasolevaid ei puutu."""
    lisatud = []
    tee = tee or config.db_tee()
    with sqlite3.connect(tee, timeout=10) as conn:
        for tabel, veerud in HILISEMAD_VEERUD.items():
            try:
                olemas = {r[1] for r in conn.execute(
                    f"PRAGMA table_info({tabel})").fetchall()}
            except Exception:
                continue
            if not olemas:
                continue
            for nimi, ddl in veerud:
                if nimi in olemas:
                    continue
                try:
                    conn.execute(
                        f"ALTER TABLE {tabel} ADD COLUMN {nimi} {ddl}")
                    lisatud.append(f"{tabel}.{nimi}")
                except Exception:
                    pass
    if lisatud:
        print(f"  lisa_puuduvad_veerud()       -> {', '.join(lisatud)}")
    return lisatud


def dump_schema(fail: pathlib.Path) -> int:
    read = []
    import auth as _a2
    for silt, tee in (("reminders.db", config.DB_TEE),
                      ("users.db", _a2.kasutajate_db_tee())):
        read.append(f"-- ===== {silt} " + "=" * (58 - len(silt)))
        if not os.path.exists(tee):
            read.append("-- (andmebaas puudub – jooksuta init_db.py)")
            continue
        with sqlite3.connect(tee) as c:
            for (sql,) in c.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                    "ORDER BY type DESC, name"):
                read.append(sql.strip().rstrip(";") + ";")
        read.append("")
    tekst = ("-- MAYA andmebaasi skeem.\n"
             "-- GENEREERITUD: python3 init_db.py --dump\n"
             "-- Ära muuda käsitsi – skeem tuleb moodulite init-"
             "funktsioonidest.\n\n") + "\n".join(read) + "\n"
    fail.write_text(tekst, encoding="utf-8")
    return len(read)


def main() -> int:
    argv = sys.argv[1:]
    print("MAYA andmebaaside initsialiseerimine")
    print(config.kokkuvote())
    print()

    if "--check" in argv:
        puudu = []
        import auth as _a3
        for silt, tee in (("reminders.db", config.DB_TEE),
                          ("users.db", _a3.kasutajate_db_tee())):
            t = _tabelid(tee)
            print(f"  {silt:18s} {'OLEMAS' if t else 'PUUDUB'} "
                  f"({len(t)} tabelit)")
            if not t:
                puudu.append(silt)
        return 1 if puudu else 0

    tulem = loo(force="--force" in argv)
    print()
    for silt, tabelid in tulem.items():
        print(f"  {silt}: {len(tabelid)} tabelit")
        for t in tabelid:
            print(f"     - {t}")

    if "--dump" in argv:
        n = dump_schema(SIIN / "schema.sql")
        print(f"\n  skeem kirjutatud: schema.sql ({n} rida)")

    print("\nValmis. Andmebaasid on TÜHJAD – isiklikke andmeid kaasas "
          "ei ole.")
    print("\nJÄRGMINE SAMM: loo esimene konto (saab admin-õigused):")
    print("  curl -X POST http://127.0.0.1:8000/api/auth/register \\")
    print("       -H 'Content-Type: application/json' \\")
    print("       -d '{\"username\":\"sinu_nimi\",\"password\":"
          "\"vahemalt_10_margi_pikk_parool\"}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

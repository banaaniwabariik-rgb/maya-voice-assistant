#!/usr/bin/env python3
"""FAAS D: faktide elutsükli ja skeemi testid.

Kõik andmed on sünteetilised, DB on :memory: – tootmisandmeid ei puututa.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
import memory_fts as M  # noqa: E402

results = []


def test(name):
    def deco(fn):
        try:
            fn()
            results.append((True, name, ""))
        except AssertionError as e:
            results.append((False, name, str(e) or "kinnitus ebaõnnestus"))
        except Exception as e:
            results.append((False, name, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def fresh():
    conn = sqlite3.connect(":memory:")
    M.ensure_schema(conn)
    return conn


# --------------------------------------------------------------------------
# Skeem
# --------------------------------------------------------------------------

@test("1. skeem luuakse ja on idempotentne (korduv käivitus ei lõhu)")
def t1():
    conn = fresh()
    first = M.ensure_schema(conn)
    assert first["columns_added"] == [], f"teine käivitus lisas veerge: {first}"
    assert first["tables_created"] == [], f"teine käivitus lõi tabeleid: {first}"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory)")}
    for need in ("category", "confidence", "source", "status", "norm_key",
                 "subject_key", "created_at", "updated_at", "superseded_by"):
        assert need in cols, f"veerg puudub: {need}"


@test("2. migratsioon säilitab olemasolevad faktid (ei kustuta midagi)")
def t2():
    conn = sqlite3.connect(":memory:")
    # vana skeem, nagu tootmises enne Faas D
    conn.execute("CREATE TABLE memory (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "timestamp TEXT NOT NULL, fact TEXT NOT NULL UNIQUE)")
    for i, f in enumerate(["Peeter elab Eestis", "Peetril on koer", "Peeter joob teed"], 1):
        conn.execute("INSERT INTO memory (timestamp, fact) VALUES (?,?)",
                     (f"2026-0{i}-01 10:00", f))
    conn.commit()
    M.ensure_schema(conn)
    n = conn.execute("SELECT count(*) FROM memory").fetchone()[0]
    assert n == 3, f"faktide arv muutus: {n}"
    # vanad read saavad vaikeväärtused ja ajatemplid
    row = conn.execute("SELECT status, created_at, source FROM memory WHERE id=1").fetchone()
    assert row[0] == "active", row
    assert row[1] == "2026-01-01 10:00", f"created_at ei täidetud: {row}"
    assert row[2] == "enne_faas_d", row
    n2 = M.backfill_fact_metadata(conn)
    assert n2 == 3, f"backfill puudutas {n2} rida"
    assert conn.execute("SELECT norm_key FROM memory WHERE id=1").fetchone()[0] != ""


@test("3. FTS indeks püsib triggeritega sünkroonis")
def t3():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Ostsin uue kitarri','Tore!')")
    conn.commit()
    assert len(M.search_archive(conn, "kitarr")) == 1, "INSERT ei jõudnud indeksisse"
    conn.execute("UPDATE conversation_archive SET user_text='Ostsin uue klaveri' WHERE id=1")
    conn.commit()
    assert len(M.search_archive(conn, "kitarr")) == 0, "UPDATE ei eemaldanud vana"
    assert len(M.search_archive(conn, "klaver")) == 1, "UPDATE ei lisanud uut"
    conn.execute("DELETE FROM conversation_archive WHERE id=1")
    conn.commit()
    assert len(M.search_archive(conn, "klaver")) == 0, "DELETE ei eemaldanud indeksist"


# --------------------------------------------------------------------------
# Eesti keele tüvistamine
# --------------------------------------------------------------------------

@test("4. käänded leitakse (tüvistaja + prefiksiotsing)")
def t4():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Mu katus lekib','Halb lugu')")
    conn.commit()
    for q in ["katus", "katusest", "katusega", "katuse", "katused"]:
        assert len(M.search_archive(conn, q)) == 1, f"käändevorm ei leidnud: {q!r}"


@test("5. alamsõne-viga on kadunud ('ema' ei leia enam 'teema'/'probleem')")
def t5():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Teema oli probleemidest','Jah')")
    conn.commit()
    # Vana LIKE '%ema%' oleks selle leidnud. FTS5 sõnapõhine otsing ei tohi.
    got = M.search_archive(conn, "ema")
    assert got == [], f"'ema' leidis valesti alamsõnega: {len(got)} vastet"


@test("6. lühikesed sisukad sõnad säilivad (bmw, suv)")
def t6():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Ostsin BMW','Hea auto')")
    conn.commit()
    assert len(M.search_archive(conn, "Kas ma ostsin BMW?")) == 1, "'bmw' visati tokeniseerimisel ära"


@test("7. värskem kirje võidab sama tugeva vanema")
def t7():
    conn = fresh()
    for i, (d, t) in enumerate([("2024-01-01", "Ostsin auto Volvo"),
                                ("2026-11-01", "Ostsin auto Volvo")], 1):
        conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                     " VALUES (?,?,'Monday',?,'ok')", (f"{d} 10:00:00", d, t))
    conn.commit()
    got = M.search_archive(conn, "Volvo auto", limit=2)
    assert got, "midagi ei leitud"
    assert got[0]["id"] == 2, f"vanem kirje järjestus ettepoole: {[g['id'] for g in got]}"


@test("8. tühi/mõttetu päring ei tagasta prahti")
def t8():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Midagi juhtus','ok')")
    conn.commit()
    for q in ["", "   ", "ja on see", "?!"]:
        assert M.search_archive(conn, q) == [], f"tühi päring tagastas tulemusi: {q!r}"


@test("9. vigane FTS-süntaks ei kukuta otsingut")
def t9():
    conn = fresh()
    conn.execute("INSERT INTO conversation_archive (timestamp,date_str,weekday_str,user_text,reply_text)"
                 " VALUES ('2026-11-01 10:00','2026-11-01','Sunday','Test rida','ok')")
    conn.commit()
    for q in ['"katkine', 'AND OR NOT', 'tere* NEAR/', "a'b\"c", "(((", "sõna OR"]:
        M.search_archive(conn, q)  # ei tohi visata erindit


# --------------------------------------------------------------------------
# Faktide elutsükkel
# --------------------------------------------------------------------------

@test("10. uus fakt lisatakse")
def t10():
    conn = fresh()
    r = M.upsert_fact(conn, "Peetril on valge Volvo", category="omand", confidence=0.8)
    assert r["action"] == "insert", r
    assert M.active_fact_count(conn) == 1


@test("11. duplikaat ei loo uut rida, vaid tõstab kindlust")
def t11():
    conn = fresh()
    M.upsert_fact(conn, "Peetril on valge Volvo", category="omand", confidence=0.7)
    r = M.upsert_fact(conn, "peetril on valge volvo.", category="omand", confidence=0.7)
    assert r["action"] == "duplicate", r
    assert M.active_fact_count(conn) == 1, "duplikaat tekitas uue rea"
    conf = conn.execute("SELECT confidence FROM memory WHERE id=?", (r["id"],)).fetchone()[0]
    assert conf > 0.7, f"kindlus ei tõusnud: {conf}"
    hits = conn.execute("SELECT hit_count FROM memory WHERE id=?", (r["id"],)).fetchone()[0]
    assert hits == 1, f"hit_count ei kasvanud: {hits}"


@test("12. sama teema uuem sõnastus ASENDAB vana (supersede)")
def t12():
    conn = fresh()
    a = M.upsert_fact(conn, "Peetril on valge Volvo", category="omand")
    b = M.upsert_fact(conn, "Peetril on valge Volvo kombi", category="omand")
    assert b["action"] == "supersede", b
    assert a["id"] in b["affected"], b
    old = conn.execute("SELECT status, superseded_by FROM memory WHERE id=?", (a["id"],)).fetchone()
    assert old[0] == "superseded" and old[1] == b["id"], old
    assert M.active_fact_count(conn) == 1, "mõlemad jäid aktiivseks"


@test("13. eitus tuvastatakse VASTUOLUNA, mitte uuendusena")
def t13():
    conn = fresh()
    a = M.upsert_fact(conn, "Peeter joob kohvi hommikuti", category="harjumus")
    b = M.upsert_fact(conn, "Peeter ei joo enam kohvi hommikuti", category="harjumus")
    assert b["action"] == "conflict", b
    st = conn.execute("SELECT status FROM memory WHERE id=?", (a["id"],)).fetchone()[0]
    assert st == "conflicted", st
    # uus jääb kehtima
    assert M.active_fact_count(conn) == 1


@test("14. eri teemad elavad kõrvuti (ei asenda teineteist)")
def t14():
    conn = fresh()
    M.upsert_fact(conn, "Peetril on valge Volvo", category="omand")
    M.upsert_fact(conn, "Peeter jookseb kolm korda nädalas", category="harjumus")
    M.upsert_fact(conn, "Peetri õde elab Tallinnas", category="suhe")
    assert M.active_fact_count(conn) == 3, "eri teemad asendasid teineteist"


@test("15. asendatud fakt kaob otsingust, aga jääb ajalukku alles")
def t15():
    conn = fresh()
    M.upsert_fact(conn, "Peetril on valge Volvo", category="omand")
    M.upsert_fact(conn, "Peetril on sinine Volvo", category="omand")
    aktiivsed = M.search_facts(conn, "Volvo")
    assert len(aktiivsed) == 1, f"otsing tagastas {len(aktiivsed)} (peaks 1)"
    assert "sinine" in aktiivsed[0]["fact"], aktiivsed
    koos_ajalooga = M.search_facts(conn, "Volvo", include_inactive=True)
    assert len(koos_ajalooga) == 2, "vana fakt kustutati – ajalugu läks kaotsi"


@test("16. tühja fakti ei salvestata")
def t16():
    conn = fresh()
    for bad in ["", "   ", None]:
        r = M.upsert_fact(conn, bad)
        assert r["action"] == "skipped", (bad, r)
    assert M.active_fact_count(conn) == 0


@test("17. kindlus mõjutab faktide järjestust")
def t17():
    conn = fresh()
    M.upsert_fact(conn, "Peeter mainis kord Volvot", category="omand", confidence=0.3)
    M.upsert_fact(conn, "Peeter kinnitas et sõidab Volvoga", category="muu", confidence=1.0)
    got = M.search_facts(conn, "Volvo")
    assert len(got) == 2, got
    assert got[0]["confidence"] == 1.0, f"madala kindlusega fakt esimene: {got}"


@test("18. kategooriad ja allikas salvestuvad")
def t18():
    conn = fresh()
    r = M.upsert_fact(conn, "Peeter ehitab kuuri", category="projekt",
                      confidence=0.9, source="kone_2026_11_07")
    row = conn.execute("SELECT category, confidence, source, status FROM memory WHERE id=?",
                       (r["id"],)).fetchone()
    assert row == ("projekt", 0.9, "kone_2026_11_07", "active"), row
    assert "projekt" in M.FACT_CATEGORIES


if __name__ == "__main__":
    print("FAAS D: MÄLU ELUTSÜKKEL JA SKEEM")
    print("=" * 70)
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, err in results:
        print(f"  {'LÄBITUD' if ok else 'KUKKUS '}  {name}")
        if not ok:
            print(f"            -> {err}")
    print("=" * 70)
    print(f"{passed}/{len(results)} läbitud")
    sys.exit(0 if passed == len(results) else 1)

#!/usr/bin/env python3
"""FAAS D: mäluotsingu kuldstandard ja varipaigaldus-hindamine.

Korpus on TÄIELIKULT SÜNTEETILINE. Peetri päris vestlusi siin ei kasutata
ega kuvata – tootmisandmetega tehakse ainult koondmõõtmine (vt
tests_malu_tootmine.py), mis ei trüki ühtegi rida sisu.

Mõõdikud:
  Recall@5           – mitu protsenti asjakohastest kirjetest jõuab top-5-sse
  Valepositiivide määr – mitu protsenti tagastatud kirjetest on ebaolulised
  MRR                – esimese õige vaste pöördjärk (järjestuse kvaliteet)

Võrdleme VANA otsingut (LIKE + käsitsi skoorimine) UUEGA (FTS5 + BM25 +
värskus) samal korpusel ja samade päringutega.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
import memory_fts as M  # noqa: E402

# ---------------------------------------------------------------------------
# SÜNTEETILINE KORPUS
# Iga kirje: (id, kuupäev, kasutaja tekst, vastus)
# Teemad on tahtlikult kattuvad, et mõõta ka valepositiive.
# ---------------------------------------------------------------------------
CORPUS = [
    (1,  "2026-03-02", "Ostsin eile uue talverehvid Nokian Hakkapeliitta", "Hea valik, need peavad libedaga hästi."),
    (2,  "2026-03-14", "Mu auto BMW vajab õlivahetust", "Millal sa viimati õli vahetasid?"),
    (3,  "2026-04-01", "Käisin Tartus konverentsil", "Kuidas Tartu konverents läks?"),
    (4,  "2026-04-19", "Mulle maitseb väga tume šokolaad", "Tume šokolaad on ka tervislikum."),
    (5,  "2026-05-03", "Ma ei joo enam kohvi õhtuti", "Hea mõte une pärast."),
    (6,  "2026-05-21", "Alustasin uue projektiga tööl, nimi on Albatross", "Põnev, millest Albatross räägib?"),
    (7,  "2026-06-08", "Mu õde kolis Tallinnasse", "Kas te näete nüüd tihedamini?"),
    (8,  "2026-06-25", "Jooksin täna kümme kilomeetrit", "Tubli, see on korralik distants."),
    (9,  "2026-07-02", "Maja katus hakkas lekkima vihmaga", "Kas sa oled katusemeest otsinud?"),
    (10, "2026-07-18", "Ostsin uue sülearvuti, Lenovo ThinkPad", "Kuidas klaviatuur tundub?"),
    (11, "2026-08-05", "Mulle ei meeldi koriander üldse", "Paljudel on see geneetiline."),
    (12, "2026-08-23", "Käisime perega Pärnus rannas", "Kuidas vesi oli?"),
    (13, "2026-09-01", "Albatrossi projekt sai valmis", "Palju õnne lõpetamise puhul!"),
    (14, "2026-09-12", "Mu selg valutab pärast pikka istumist", "Kas sa oled proovinud venitusi?"),
    (15, "2026-09-29", "Hakkasin kitarri õppima", "Mis lugu sa esimesena õpid?"),
    (16, "2026-10-04", "Müüsin oma BMW maha", "Mis sa nüüd sõidad?"),
    (17, "2026-10-11", "Ostsin Volvo kombi asemele", "Volvo on peresõbralik valik."),
    (18, "2026-10-20", "Katus sai lõpuks parandatud", "Hea, et see korda sai."),
    (19, "2026-10-28", "Mu ema sünnipäev on novembris", "Kas sa oled kingituse välja mõelnud?"),
    (20, "2026-11-02", "Jooksen nüüd kolm korda nädalas", "Rutiin on tekkinud, tubli."),
    # --- segajad: sarnased sõnad, aga muu teema ---
    (21, "2026-03-20", "Teemaks oli eile ilm ja probleemid liikluses", "Liiklus oli tõesti hull."),
    (22, "2026-04-11", "Rääkisime probleemidest tööl üldiselt", "Mis seal juhtus?"),
    (23, "2026-05-15", "Lugesin raamatut saarte kohta", "Milline saar sulle muljet avaldas?"),
    (24, "2026-06-02", "Mul on säärelihas pingul", "Venita seda ettevaatlikult."),
    (25, "2026-07-27", "Vaatasin filmi kitarristist", "Kas film oli hea?"),
    (26, "2026-08-14", "Katusekorter tundub kallis", "Asukoht mõjutab hinda palju."),
    (27, "2026-09-20", "Kohvik uues kohas avati", "Kas käisid proovimas?"),
    (28, "2026-10-08", "Autopesula oli suletud", "Tüütu, kui plaan käib untsu."),
    (29, "2026-10-15", "Projektor läks katki", "Kas garantii veel kehtib?"),
    (30, "2026-11-01", "Ostsin uued jooksujalatsid", "Millised said?"),
]

# Päringud: (küsimus, asjakohaste id-de hulk)
# "Asjakohane" = inimene ootaks seda kirjet vastuses nähes.
QUERIES = [
    ("Mis autoga ma sõidan?",              {2, 16, 17}),
    ("Kas ma müüsin BMW?",                 {16, 2}),
    ("Millised rehvid ma ostsin?",         {1}),
    ("Räägi mu Volvost",                   {17}),
    ("Mis sai katusest?",                  {9, 18}),
    ("Kas katus lekkis?",                  {9, 18}),
    ("Mida ma Tartus tegin?",              {3}),
    ("Kus ma perega käisin?",              {12}),
    ("Mis mulle maitseb?",                 {4}),
    ("Mis mulle ei maitse?",               {11}),
    ("Kas ma joon kohvi?",                 {5}),
    ("Räägi Albatrossi projektist",        {6, 13}),
    ("Kas Albatross sai valmis?",          {13, 6}),
    ("Kui palju ma jooksen?",              {8, 20}),
    ("Mis spordiga ma tegelen?",           {8, 20}),
    ("Millise arvuti ma ostsin?",          {10}),
    ("Räägi mu ThinkPadist",               {10}),
    ("Kas mul on seljaprobleeme?",         {14}),
    ("Mis pilli ma õpin?",                 {15}),
    ("Millal on ema sünnipäev?",           {19}),
    ("Kuhu mu õde kolis?",                 {7}),
    ("Mis šokolaadi ma eelistan?",         {4}),
    ("Räägi mulle rehvidest",              {1}),
    ("Kas ma ostsin midagi uut?",          {1, 10, 17, 30}),
    ("Mis juhtus autoga?",                 {2, 16, 17}),
    ("Räägi Pärnu reisist",                {12}),
    ("Mis on minu uus sõiduk?",            {17, 16}),
    ("Kas ma olen tervisega hädas?",       {14}),
    ("Mida ma õhtuti ei tee?",             {5}),
    ("Millal ma kitarri alustasin?",       {15}),
    ("Mis minu kodus katki läks?",         {9, 18, 29}),
    ("Räägi mu jooksutrennist",            {8, 20, 30}),
]


# ---------------------------------------------------------------------------
# VANA otsing – taastatud memory_engine.py-st (enne Faas D)
# ---------------------------------------------------------------------------
def old_search_archive(conn, query, limit=5):
    """`LIKE '%sona%'` OR kõigi sõnade üle, ORDER BY id DESC. Ei järjesta."""
    words = [w.strip().lower() for w in query.split()
             if len(w.strip()) > 3 and w.lower() not in ["kas", "oled", "mida", "kuidas", "millal", "kes"]]
    if not words:
        return []
    clauses = " OR ".join(["user_text LIKE ? OR reply_text LIKE ?" for _ in words])
    params = []
    for w in words:
        params.extend([f"%{w}%", f"%{w}%"])
    rows = conn.execute(
        f"SELECT id FROM conversation_archive WHERE {clauses} ORDER BY id DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [r[0] for r in rows]


def new_search_archive(conn, query, limit=5):
    return [r["id"] for r in M.search_archive(conn, query, limit=limit)]


# ---------------------------------------------------------------------------
def build_db():
    conn = sqlite3.connect(":memory:")
    M.ensure_schema(conn)
    for rid, date, ut, rt in CORPUS:
        conn.execute(
            "INSERT INTO conversation_archive (id, timestamp, date_str, weekday_str, user_text, reply_text)"
            " VALUES (?, ?, ?, 'Monday', ?, ?)",
            (rid, f"{date} 12:00:00", date, ut, rt),
        )
    conn.commit()
    M.rebuild_index(conn)
    return conn


def evaluate(conn, search_fn, k=5):
    tot_recall = tot_fp = tot_mrr = 0.0
    misses = []
    for q, relevant in QUERIES:
        got = search_fn(conn, q, limit=k)
        hits = [g for g in got if g in relevant]
        recall = len(set(got) & relevant) / len(relevant)
        fp = (len(got) - len(hits)) / len(got) if got else 0.0
        mrr = 0.0
        for i, g in enumerate(got, 1):
            if g in relevant:
                mrr = 1.0 / i
                break
        tot_recall += recall
        tot_fp += fp
        tot_mrr += mrr
        if recall < 1.0:
            misses.append((q, sorted(relevant - set(got))))
    n = len(QUERIES)
    return {
        "recall@5": tot_recall / n,
        "fp_rate": tot_fp / n,
        "mrr": tot_mrr / n,
        "misses": misses,
    }


if __name__ == "__main__":
    conn = build_db()
    print("MÄLUOTSINGU KULDSTANDARD (sünteetiline korpus)")
    print(f"  korpus: {len(CORPUS)} vestlust | päringuid: {len(QUERIES)}")
    print("=" * 72)

    old = evaluate(conn, old_search_archive)
    new = evaluate(conn, new_search_archive)

    print(f"{'mõõdik':<22}{'VANA (LIKE)':>14}{'UUS (FTS5)':>14}{'muutus':>12}")
    print("-" * 72)
    for key, label, hi_good in (("recall@5", "Recall@5", True),
                                ("fp_rate", "Valepositiive", False),
                                ("mrr", "MRR", True)):
        o, n = old[key], new[key]
        delta = n - o
        arrow = "paremaks" if (delta > 0) == hi_good and abs(delta) > 1e-9 else (
                "halvemaks" if abs(delta) > 1e-9 else "sama")
        print(f"{label:<22}{o:>13.1%}{n:>14.1%}{arrow:>12}")
    print("-" * 72)

    if new["misses"]:
        print(f"\nUUS ei leidnud kõike {len(new['misses'])} päringul:")
        for q, miss in new["misses"][:8]:
            print(f"   {q!r} -> puudu id {miss}")

    ok = (new["recall@5"] > old["recall@5"] and new["fp_rate"] <= old["fp_rate"])
    print("\n" + ("TULEMUS: UUS on parem nii katvuses kui valepositiivides"
                  if ok else "TULEMUS: UUS EI ole üheselt parem – vaja häälestada"))
    sys.exit(0 if ok else 1)

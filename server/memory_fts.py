#!/usr/bin/env python3
"""FAAS D: episoodiline FTS5-otsing ja faktide elutsükkel.

MIKS SEE MOODUL ON OLEMAS
-------------------------
Mõõdetud olukord enne (tootmis-DB, 2026-11-07):
  * conversation_archive: 769 rida, memory: AINULT 5 fakti
  * 53 arhiveeritud kõnest 41 lõppes teatega "Uusi püsivaid fakte ei
    tuvastatud" – eraldusprompt oli nii konservatiivne, et peaaegu midagi
    ei jõudnud pikaajalisse mällu
  * arhiiviotsing oli `user_text LIKE '%sona%' OR reply_text LIKE ...`
    ilma igasuguse järjestuseta, ainult ORDER BY id DESC. Alamsõne-otsing
    tähendab, et "ema" leiab ka "teema" ja "probleem".
  * faktiotsing laadis KÕIK faktid Pythonisse ja skooris käsitsi

MIDA SIIN TEHAKSE
-----------------
  1. FTS5 indeks arhiivi peale, BM25 + värskuse kaal
  2. Eesti keele käänamise käsitlus prefiksiotsinguga (vt _fts_query)
  3. Faktitabeli laiendus: kategooria, kindlus, allikas, olek, ajatemplid
  4. Faktide elutsükkel: duplikaadid, asendamine (supersede), vastuolud

PIIRANG (sprindi ulatusest väljas): EI kasutata embeddinguid ega
vektoriandmebaasi. Kogu otsing on leksikaalne.

Kõik funktsioonid võtavad avatud ühenduse, et neid saaks testida ajutise
andmebaasiga ilma tootmisandmeid puutumata.
"""

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Eesti keele abivahendid
# --------------------------------------------------------------------------

STOPWORDS_ET = {
    "kas", "oled", "mida", "kuidas", "millal", "kes", "mis", "see", "ja", "aga",
    "siis", "ning", "või", "ei", "ma", "sa", "ta", "me", "te", "nad", "on", "oli",
    "olen", "mulle", "sulle", "minu", "sinu", "teda", "selle", "need", "kui",
    "ka", "veel", "juba", "nii", "oma", "ise", "kõik", "palun", "tere", "jah",
    "mina", "sina", "meie", "teie", "nagu", "sest", "et", "ole", "olla", "saab",
    "teeb", "läheb", "tahan", "tead", "räägi", "ütle", "mul", "sul",
}

# Eesti käändelõpud, mis tasub tüve leidmiseks maha lõigata. Järjekord on
# tähtis: pikemad lõpud enne lühemaid, muidu lõikaks lühem valesti.
# See EI ole morfoloogiline analüsaator – see on odav tüvistaja, millest
# piisab FTS5 prefiksiotsingu lähtepunktiks.
_SUFFIXES_ET = (
    # käändelõpud (pikemad enne lühemaid)
    "tega", "dega", "test", "dest", "tele", "dele", "teks", "deks",
    "sse", "ses", "ist", "ilt", "ile",
    # pöördelõpud – ilma nendeta ei leia "jooksen" kirjet, kus on "jooksin"
    "vad", "sime", "site", "nud", "tud", "mas", "mast", "maks",
    "sin", "sid", "me", "te", "vat",
    "st", "le", "lt", "ks", "ga", "na", "de",
    "id", "it", "ut", "ad", "ed", "od", "ud", "is", "us", "as", "es",
    "en", "in", "on", "an",
    "i", "t", "d", "e", "u", "a", "l", "s", "n",
)

MIN_TOKEN = 3     # 'bmw', 'suv', 'api' on sisukad; <3 ei ole
# Korduv lõikamine, ringide kaupa erinev alampiir. Teine ring peab olema
# KONSERVATIIVSEM: esimene ring teeb 'katusest' -> 'katuse', teine lõpetab
# 'katus'. Ilma kõrgema alampiirita läheks 'jooksen' -> 'jooks' -> 'jook',
# mis tõstab valepositiive (mõõdetud: 23,7% -> 30,9%).
_STEM_MIN_PER_ROUND = (4, 5)


def stem_et(word: str) -> str:
    """Odav eesti tüvistaja FTS5 prefiksiotsingu jaoks.

    'autoga' -> 'auto', 'katusest' -> 'katus', 'jooksen' -> 'jooks'.

    Lõikab lõppe KORDUVALT (kuni _STEM_ROUNDS korda). Ühest ringist ei
    piisa: 'katusest' annaks 'katuse', mille prefiksipäring 'katuse*' EI
    leia dokumenti, kus seisab lihtsalt 'katus'. Kuna päringupoolel tekib
    prefiks, peab tüvi olema pigem LÜHEM kui dokumendi sõna, mitte pikem.

    Ei püüa olla keeleteaduslikult korrektne – vale lõikamine on talutav,
    sest otsing on prefiksipäring ja järjestuse teeb BM25.
    """
    w = (word or "").lower().strip()
    for min_len in _STEM_MIN_PER_ROUND:
        if len(w) <= min_len:
            break
        for suf in _SUFFIXES_ET:
            if w.endswith(suf) and len(w) - len(suf) >= min_len:
                w = w[: -len(suf)]
                break
        else:
            break
    return w


def tokenize_et(text: str) -> list:
    """Sisukad märksõnad: tähed+numbrid, >=3 tähte, ilma stoppsõnadeta."""
    words = re.findall(r"[0-9a-zõäöüšž]+", (text or "").lower())
    return [w for w in words if len(w) >= MIN_TOKEN and w not in STOPWORDS_ET]


def normalize_fact(text: str) -> str:
    """Faktide duplikaadituvastuse võti.

    Väiketähed, kirjavahemärgid maha, sõnad tüvistatud ja sorditud. Nii
    loetakse "Peetril on BMW" ja "Peetril on bmw." samaks faktiks, samuti
    "Jaan sõidab BMW-ga" -> sama tüvekomplekt.
    """
    t = unicodedata.normalize("NFKC", (text or "")).lower()
    t = re.sub(r"[^0-9a-zõäöüšž\s]+", " ", t)
    stems = sorted({stem_et(w) for w in t.split() if len(w) > 2 and w not in STOPWORDS_ET})
    return " ".join(stems)


def _fts_escape(token: str) -> str:
    """FTS5 jaoks ohutu üksiktoken (jutumärkides, sees olevad " kahekordselt)."""
    return '"' + token.replace('"', '""') + '"'


def build_fts_query(text: str, prefix: bool = True) -> str:
    """Ehitab FTS5 MATCH-päringu eestikeelsest küsimusest.

    Iga märksõna asendatakse selle TÜVEGA + prefiksitärniga, nii et
    "Kas mul on autoga probleeme?" leiab ka "auto", "autot", "autole".
    Tokenid ühendatakse OR-iga: tahame kõiki osalisi vasteid, järjestuse
    teeb BM25. AND oleks liiga range – pikem küsimus ei leiaks midagi.
    """
    toks = tokenize_et(text)
    if not toks:
        return ""
    parts = []
    for t in toks:
        s = stem_et(t)
        if not s:
            continue
        parts.append(_fts_escape(s) + "*" if prefix and len(s) >= 3 else _fts_escape(s))
    # dubleerimine maha, järjekord säilib
    seen, uniq = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return " OR ".join(uniq)


# --------------------------------------------------------------------------
# Skeem
# --------------------------------------------------------------------------

FACT_CATEGORIES = (
    "identiteet",    # kes Jaan on, pere, elukoht
    "eelistus",      # mis meeldib / ei meeldi
    "omand",         # asjad, autod, seadmed
    "projekt",       # töö, ehitus, arendus
    "harjumus",      # korduv käitumine, rutiin
    "plaan",         # tulevik, kavatsused
    "tervis",
    "suhe",          # suhted teiste inimestega
    "muu",
)

FACT_STATUSES = ("active", "superseded", "conflicted", "retired")


def ensure_schema(conn: sqlite3.Connection) -> dict:
    """Loob/uuendab skeemi. Idempotentne ja ADITIIVNE – ei kustuta midagi.

    Tagastab sõnastiku tehtud muudatustest (testide ja logi jaoks).
    """
    changed = {"columns_added": [], "tables_created": []}
    c = conn.cursor()

    # --- baastabelid (kui moodulit kasutatakse tühja DB peal, nt testis) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            fact TEXT NOT NULL UNIQUE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversation_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date_str TEXT NOT NULL,
            weekday_str TEXT NOT NULL,
            user_text TEXT NOT NULL,
            reply_text TEXT NOT NULL
        )
    """)

    # --- faktitabeli laiendus -------------------------------------------
    existing = {r[1] for r in c.execute("PRAGMA table_info(memory)")}
    additions = {
        "category":      "TEXT NOT NULL DEFAULT 'muu'",
        "confidence":    "REAL NOT NULL DEFAULT 0.6",
        "source":        "TEXT NOT NULL DEFAULT 'tundmatu'",
        "status":        "TEXT NOT NULL DEFAULT 'active'",
        "norm_key":      "TEXT NOT NULL DEFAULT ''",
        "subject_key":   "TEXT NOT NULL DEFAULT ''",
        "created_at":    "TEXT NOT NULL DEFAULT ''",
        "updated_at":    "TEXT NOT NULL DEFAULT ''",
        "superseded_by": "INTEGER",
        "hit_count":     "INTEGER NOT NULL DEFAULT 0",
        # --- FAKTI OMANIK (karakterite eraldatus) -----------------------
        # persona: NULL = ühine fakt, muidu karakteri id ('custom', 'singer').
        # scope:   'shared'  – nähtav kõigile karakteritele
        #          'persona' – nähtav AINULT omanikkarakterile
        #          'private' – ei süstita kunagi automaatselt, ainult
        #                      recall_memory tööriista kaudu
        # Miks vaja: enne seda sai iga karakter sama 15 fakti, nii et
        # 'custom' karakteriga peetud intiimses vestluses tekkinud faktid
        # süstiti ka 'asjalik'/'mentor'/'treener' prompti.
        "persona":       "TEXT",
        "scope":         "TEXT NOT NULL DEFAULT 'shared'",
        # --- AUDIT: MIKS see fakt ei ole ühine ---------------------------
        # Lühike JSON ainult mitte-'shared' ridadel: ankru voorunumber,
        # kasutaja LAUSE sõna-sõnalt, tabanud muster, sihtmärgirežiim.
        # Miks vaja: 'persona'+'scope' salvestavad TULEMUSE, mitte PÕHJUSE.
        # Journald ei sobi – ta roteerub ja save_facts_direct ei logi
        # teadlikult fakti sisu. Ilma selleta ei saa privaatsusotsust
        # tagantjärele kontrollida ega valesti privatiseeritud fakti üles
        # leida. NULL = ühine fakt, põhjust ei ole vaja.
        "scope_reason":  "TEXT",
    }
    for col, ddl in additions.items():
        if col not in existing:
            c.execute(f"ALTER TABLE memory ADD COLUMN {col} {ddl}")
            changed["columns_added"].append(col)

    # --- arhiivi laiendus ------------------------------------------------
    # Ilma selleta ei saa tagantjärele tuvastada, MILLISE karakteriga vestlus
    # peeti. Mälu forensika audit (08.11.2026) pidi selle info taastama
    # journald logidest, mis roteeruvad ja kaovad.
    arc_existing = {r[1] for r in c.execute("PRAGMA table_info(conversation_archive)")}
    if "persona" not in arc_existing:
        c.execute("ALTER TABLE conversation_archive ADD COLUMN persona TEXT")
        changed["columns_added"].append("conversation_archive.persona")

    c.execute("CREATE INDEX IF NOT EXISTS idx_mem_status ON memory(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mem_norm ON memory(norm_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mem_subject ON memory(subject_key, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON memory(scope, persona, status)")

    # Vanad read: täidame uued veerud mõistlike väärtustega.
    # JÄRJEKORD ON OLULINE: see peab toimuma ENNE triggerite loomist. Kui
    # triggerid on juba olemas ja FTS-indeks veel tühi, üritab UPDATE-trigger
    # indeksist kustutada rida, mida seal pole -> SQLite viskab
    # "database disk image is malformed". Esmakäivitusel triggereid veel pole,
    # hilisematel käivitustel ei leia need UPDATE-d enam ühtegi rida.
    c.execute("UPDATE memory SET created_at = timestamp WHERE created_at = ''")
    c.execute("UPDATE memory SET updated_at = timestamp WHERE updated_at = ''")
    c.execute("UPDATE memory SET source = 'enne_faas_d' WHERE source = 'tundmatu'")

    # --- FTS5 indeksid ----------------------------------------------------
    # Välissisuga (external content) tabelid: andmeid ei dubleerita, FTS
    # loeb originaaltabelist. remove_diacritics 0 – eesti õäöüšž peavad
    # jääma eristatavaks ('saar' != 'säär').
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    if "archive_fts" not in tables:
        c.execute("""
            CREATE VIRTUAL TABLE archive_fts USING fts5(
                user_text, reply_text,
                content='conversation_archive',
                content_rowid='id',
                tokenize="unicode61 remove_diacritics 0",
                prefix='3 4 5'
            )
        """)
        changed["tables_created"].append("archive_fts")

    if "memory_fts" not in tables:
        c.execute("""
            CREATE VIRTUAL TABLE memory_fts USING fts5(
                fact,
                content='memory',
                content_rowid='id',
                tokenize="unicode61 remove_diacritics 0",
                prefix='3 4 5'
            )
        """)
        changed["tables_created"].append("memory_fts")

    # Vastloodud FTS-tabel on tühi, kuigi sisutabelis on juba ridu. Täidame
    # selle KOHE – muidu ei leia otsing vanu vestlusi ja esimene trigger
    # üritaks kustutada indekseerimata rida.
    if changed["tables_created"]:
        c.execute("INSERT INTO archive_fts(archive_fts) VALUES('rebuild')")
        c.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

    # --- sünkroonsust hoidvad triggerid -----------------------------------
    # Ilma nendeta jääks indeks uute kõnede järel vaikselt maha.
    c.executescript("""
        CREATE TRIGGER IF NOT EXISTS archive_fts_ai AFTER INSERT ON conversation_archive BEGIN
            INSERT INTO archive_fts(rowid, user_text, reply_text)
            VALUES (new.id, new.user_text, new.reply_text);
        END;
        CREATE TRIGGER IF NOT EXISTS archive_fts_ad AFTER DELETE ON conversation_archive BEGIN
            INSERT INTO archive_fts(archive_fts, rowid, user_text, reply_text)
            VALUES ('delete', old.id, old.user_text, old.reply_text);
        END;
        CREATE TRIGGER IF NOT EXISTS archive_fts_au AFTER UPDATE ON conversation_archive BEGIN
            INSERT INTO archive_fts(archive_fts, rowid, user_text, reply_text)
            VALUES ('delete', old.id, old.user_text, old.reply_text);
            INSERT INTO archive_fts(rowid, user_text, reply_text)
            VALUES (new.id, new.user_text, new.reply_text);
        END;

        CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory BEGIN
            INSERT INTO memory_fts(rowid, fact) VALUES (new.id, new.fact);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, fact) VALUES ('delete', old.id, old.fact);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, fact) VALUES ('delete', old.id, old.fact);
            INSERT INTO memory_fts(rowid, fact) VALUES (new.id, new.fact);
        END;
    """)

    conn.commit()
    return changed


def rebuild_index(conn: sqlite3.Connection) -> dict:
    """Täidab FTS-indeksid olemasolevatest ridadest. Ohutu korrata."""
    c = conn.cursor()
    c.execute("INSERT INTO archive_fts(archive_fts) VALUES('rebuild')")
    c.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
    conn.commit()
    return {
        "archive_rows": c.execute("SELECT count(*) FROM conversation_archive").fetchone()[0],
        "memory_rows": c.execute("SELECT count(*) FROM memory").fetchone()[0],
    }


def backfill_fact_metadata(conn: sqlite3.Connection) -> int:
    """Arvutab vanadele faktidele norm_key ja subject_key. Tagastab muudetud ridade arvu."""
    c = conn.cursor()
    rows = c.execute("SELECT id, fact FROM memory WHERE norm_key = ''").fetchall()
    for fid, fact in rows:
        c.execute(
            "UPDATE memory SET norm_key = ?, subject_key = ? WHERE id = ?",
            (normalize_fact(fact), derive_subject_key(fact), fid),
        )
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------
# Otsing
# --------------------------------------------------------------------------

# Värskuse kaal: mitu BM25-punkti väärt on see, et kirje on värske.
# BM25 tagastab SQLite'is NEGATIIVSE skoori (väiksem = parem), seetõttu
# teisendame selle positiivseks ja liidame värskusboonuse.
RECENCY_WEIGHT = 0.6
RECENCY_HALFLIFE_DAYS = 90.0

# Suhteline lävend: kirje, mille skoor jääb alla selle osakaalu parimast,
# jäetakse välja. Põhjus on sisuline – iga tagastatud rida läheb Maya
# system_prompti. Nõrk vaste ei ole "kahjutu lisainfo", vaid müra, mis ajab
# vastuse teemast kõrvale.
#
# Lävend valitud mõõtmisega kuldstandardil (32 päringut, 30 vestlust):
#   lävend   Recall@5   valepos.   MRR
#    0,00      69,8%      30,9%   64,3%
#    0,30      69,8%      28,8%   64,3%   <- valitud: katvus ei kannata üldse
#    0,45      63,5%      26,9%   63,5%
#    0,60      56,5%      21,9%   62,5%
# Kõrgem lävend ostab puhtust katvuse arvelt; 0,30 on ainus punkt, kus
# valepositiivid vähenevad ILMA ühtegi õiget vastust kaotamata.
SCORE_CUTOFF_RATIO = 0.30

# Kui palju kindlus faktide järjestust nihutab (BM25 punktides).
CONFIDENCE_WEIGHT = 0.5


def _recency_boost(ts: str, now: datetime = None) -> float:
    """0..1 – uus kirje saab ~1, RECENCY_HALFLIFE_DAYS vanune ~0.5."""
    if not ts:
        return 0.0
    now = now or datetime.now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            when = datetime.strptime(ts.strip()[:19], fmt)
            break
        except ValueError:
            continue
    else:
        return 0.0
    age_days = max((now - when).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS)


def search_archive(conn: sqlite3.Connection, query: str, limit: int = 5,
                   now: datetime = None) -> list:
    """Episoodiline otsing: BM25 + värskus.

    Tagastab nimekirja sõnastikke: id, timestamp, user_text, reply_text,
    bm25, recency, score. Tühja päringu korral tühi nimekiri (EI tagasta
    "viimased read" – see oli vana käitumine ja tootis müra).
    """
    match = build_fts_query(query)
    if not match:
        return []
    c = conn.cursor()
    try:
        rows = c.execute(
            """
            SELECT a.id, a.timestamp, a.user_text, a.reply_text,
                   bm25(archive_fts, 1.0, 0.4) AS rank
            FROM archive_fts
            JOIN conversation_archive a ON a.id = archive_fts.rowid
            WHERE archive_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, max(limit * 6, 30)),
        ).fetchall()
    except sqlite3.OperationalError:
        # Vigane MATCH-süntaks ei tohi meenutamist maha võtta.
        return []

    out = []
    for rid, ts, ut, rt, rank in rows:
        bm = -float(rank)  # BM25 on negatiivne; suurem = parem
        rec = _recency_boost(ts, now)
        out.append({
            "id": rid, "timestamp": ts, "user_text": ut, "reply_text": rt,
            "bm25": round(bm, 4), "recency": round(rec, 4),
            "score": round(bm + RECENCY_WEIGHT * rec, 4),
        })
    out.sort(key=lambda r: -r["score"])
    return _apply_cutoff(out, limit)


def _apply_cutoff(rows: list, limit: int) -> list:
    """Jätab alles ainult tugevad vasted (vt SCORE_CUTOFF_RATIO)."""
    if not rows:
        return []
    best = rows[0]["score"]
    if best <= 0:
        return rows[:limit]
    keep = [r for r in rows if r["score"] >= SCORE_CUTOFF_RATIO * best]
    return keep[:limit]


def search_facts(conn: sqlite3.Connection, query: str, limit: int = 10,
                 include_inactive: bool = False, persona: str = "",
                 include_private: bool = False) -> list:
    """Faktiotsing FTS5-ga. Vaikimisi ainult aktiivsed JA antud karakterile
    nähtavad faktid. persona='' => ainult ühised faktid.

    include_private=True lubab omanikkarakteril ka 'private' ulatuses fakte
    leida – see on `recall_memory` tööriista mõte: mudel küsib ise.
    """
    match = build_fts_query(query)
    if not match:
        return []
    status_clause = "" if include_inactive else " AND m.status = 'active' "
    vis_sql, vis_args = visibility_clause(persona, alias="m")
    if include_private and (persona or "").strip():
        # MÕÕDETUD AUK (10.11.2026): `m.persona = ?` ei kattu KUNAGI
        # NULL-iga, nii et rida scope='private' + persona IS NULL oli
        # salvestatav aga MITTE ÜHEGI päringuteega leitav – kirjuta-ainult.
        # Selline rida sünnib resolve_scope'is siis, kui privaatsuskorraldus
        # on kontrollitud, aga aktiivset karakterit ei teata. Ta kuulub
        # KASUTAJALE, mitte karakterile, ja peab jääma leitavaks siis, kui
        # mudel ise küsib. Automaatsesse süstimisse ta ikka ei pääse –
        # facts_for_prompt kasutab visibility_clause'i, mis private'i
        # endiselt välistab.
        vis_sql = (" AND (m.scope = 'shared' OR m.persona = ?"
                   "      OR (m.scope = 'private' AND m.persona IS NULL)) ")
        vis_args = ((persona or "").strip().lower(),)
    c = conn.cursor()
    try:
        rows = c.execute(
            f"""
            SELECT m.id, m.fact, m.category, m.confidence, m.status, m.updated_at,
                   bm25(memory_fts) AS rank
            FROM memory_fts
            JOIN memory m ON m.id = memory_fts.rowid
            WHERE memory_fts MATCH ? {status_clause} {vis_sql}
            ORDER BY rank
            LIMIT ?
            """,
            (match,) + tuple(vis_args) + (max(limit * 4, 20),),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out = []
    for fid, fact, cat, conf, status, upd, rank in rows:
        bm = -float(rank)
        out.append({
            "id": fid, "fact": fact, "category": cat, "confidence": conf,
            "status": status, "updated_at": upd,
            "bm25": round(bm, 4),
            # Kindlus LIIDETAKSE, mitte ei korrutata. Korrutamine ebaõnnestub,
            # kui BM25 on 0 – ja seda juhtub tihti: kui otsitav sõna esineb
            # KÕIGIS ridades, on IDF null ja bm25 tagastab 0 kõigile. Siis
            # jäi järjestus sisestusjärjekorda ja madala kindlusega fakt
            # trügis kinnitatud fakti ette.
            "score": round(bm + CONFIDENCE_WEIGHT * float(conf or 0.6), 4),
        })
    out.sort(key=lambda r: -r["score"])
    return _apply_cutoff(out, limit)


# --------------------------------------------------------------------------
# Faktide elutsükkel
# --------------------------------------------------------------------------

# Vastuolu tunnused: kui uus fakt sisaldab eitust ja vana mitte (või vastupidi)
# sama subjekti kohta, siis on tegu vastuoluga, mitte lihtsalt uuendusega.
_NEGATIONS = ("ei ", "pole", "enam", "mitte", "lõpetas", "loobus", "müüs", "kaotas")


# Sõnad, mis ei kanna TEEMAT, vaid hoiakut/aega. Need jäetakse teemade
# võrdlusest välja, muidu läheb "Jaan joob kohvi" ja "Jaan ei joo ENAM
# kohvi" eri teemadeks ja vastuolu jääb tuvastamata.
_NON_SUBJECT_WORDS = {
    "enam", "veel", "jälle", "praegu", "täna", "eile", "homme", "varem",
    "hiljem", "alati", "mitte", "pole", "vist", "ehk", "kord",
}


def fact_stems(fact: str) -> set:
    """Fakti teemat kandvad tüved (hoiaku- ja ajasõnadeta)."""
    return {
        s for s in (stem_et(w) for w in tokenize_et(fact))
        if s and s not in _NON_SUBJECT_WORDS
    }


# Kui kahe fakti tüvehulkade Jaccardi sarnasus on vähemalt see, loetakse
# neid SAMA TEEMA kohta käivaks. Valitud mõõtmisega (vt tests_malu_elutsykkel):
#   "valge Volvo" vs "valge Volvo kombi"      -> 0,75  asendab
#   "valge Volvo" vs "sinine Volvo"           -> 0,50  asendab
#   "joob kohvi"  vs "ei joo kohvi"           -> 0,60  vastuolu
#   "valge Volvo" vs "jookseb kolm korda"     -> 0,17  eraldi teemad
SUBJECT_SIMILARITY = 0.5


def subject_similarity(a: str, b: str) -> float:
    """Jaccardi sarnasus kahe fakti tüvehulkade vahel (0..1)."""
    sa, sb = fact_stems(a), fact_stems(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def derive_subject_key(fact: str, category: str = "") -> str:
    """Teema võti indekseerimiseks ja inimesele vaatamiseks.

    MÄRKUS: asendamise otsust EI tehta enam selle võtme põhjal – see oli
    liiga habras ("valge Volvo" ja "sinine Volvo" andsid eri võtmed, mistõttu
    vastuolulised faktid elasid rahumeeli kõrvuti. Otsuse teeb nüüd
    subject_similarity(). Võti jääb alles indeksi ja silumise tarbeks.
    """
    stems = sorted(fact_stems(fact), key=lambda s: (-len(s), s))
    key = " ".join(sorted(stems[:3]))
    return f"{category}:{key}" if category else key


def _has_negation(text: str) -> bool:
    low = " " + (text or "").lower() + " "
    return any(n in low for n in _NEGATIONS)


# --- FAKTI OMANIKU REEGEL ----------------------------------------------
# PARANDATUD 09.11.2026 Peetri täpsustuse järel:
#
#   "kõik karakterid peaksid teadma seda sama mida ma olen rääkinud ühe
#    karakteriga, lihtsalt nad ei peaks intiimset juttu ajama nii nagu on
#    lubatud minu custom karakteril"
#
# Varem piirasin karakteri järgi: 'singer' faktid jäid ainult lauljale.
# See oli vale – muusikaeelistus on üldine teadmine Peetri kohta ja
# 'asjalik' peab seda samuti teadma.
#
# Nüüd on piirang SISU, mitte karakteri järgi: ainsana jäävad kinni
# INTIIMSED faktid. Kõik muu on ühine, sõltumata sellest, millise
# karakteriga see jutt juhtus tulema.
#
# Intiimsuse tuvastab faktide eraldamise mudel ise (vt
# memory_engine.build_extract_prompt, väli "intimate") – mitte
# märksõnaloend, mis oleks habras ja eksiks mõlemas suunas.

# Karakter, kellele intiimsed faktid kuuluvad, kui loonud karakter ei ole
# teada. 'custom' on see nupp, millel intiimne vestlus on lubatud.
INTIMATE_OWNER = "custom"

# Kategooriad, mille puhul küsime mudelilt eriti hoolikat intiimsuse
# hinnangut. EI ole iseseisev piirang – 'suhe' fakt "Peetril on vend Tiit"
# peab jääma ühiseks.
SENSITIVE_HINT_CATEGORIES = {"suhe", "identiteet"}


# --- NIMEFAKTID ON ERAND -------------------------------------------------
# Kasutaja nimi elab ÜHES kohas: settings.user_name (vt user_profile.py).
# Faktitabelis teda olla ei tohi, sest siis oleks kaks tõeallikat ja nad
# läheksid lahku.
#
# MÕÕDETUD PROBLEEM: elutsükkel asendab vana fakti ainult siis, kui
# teemasarnasus ületab SUBJECT_SIMILARITY läve. Nimepaaride peal mõõdetud:
#   "Kasutaja nimi on Jaanus."        -> 0.50  asendab  ✓
#   "Kasutaja õige nimi on Jaanus."   -> 0.40  EI asenda
#   "Tema nimi on Jaanus, mitte Jaan."-> 0.33  EI asenda
#   "Kasutajat kutsutakse Peetriks." -> 0.20  EI asenda
# Neljast sõnastusest töötas üks. Läve alandamine tekitaks valeasendusi
# mujal, seega nimi võetakse faktirajalt hoopis välja.

# Muster peab algama subjektiga, muidu langeks välja ka
# "Peetril on sõber, kelle nimi on Tiit" – see on tavaline fakt.
_NAME_FACT_RE = re.compile(
    r"^\s*(kasutaja\w*|{nimi}\w*)\s+(õige\s+|päris\s+|uus\s+)?"
    r"(nimi|nimeks|eesnimi)\s+(on|oleks|olevat)\b"
    r"|^\s*(kasutajat|{nimi}\w*)\s+kutsutakse\b",
    re.IGNORECASE | re.UNICODE)


def is_name_fact(fact: str, user_name: str = "") -> bool:
    """Kas see fakt väidab midagi KASUTAJA nime kohta?

    Nii kitsalt, et "Peetril on sõber, kelle nimi on Tiit" EI lange välja.
    """
    t = (fact or "").strip()
    if not t:
        return False
    nimi = re.escape((user_name or "").strip()) or r"(?!x)x"
    muster = _NAME_FACT_RE.pattern.replace("{nimi}", nimi)
    return bool(re.match(muster, t, re.IGNORECASE | re.UNICODE))


def retire_name_facts(conn: sqlite3.Connection, user_names=(), now: str = None) -> int:
    """Märgib kõik kasutaja nime puudutavad faktid olekuga 'retired'.

    Ei kustuta – ajalugu jääb alles, aga prompti need ei jõua, sest
    facts_for_prompt võtab ainult 'active'.
    """
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    read = conn.execute(
        "SELECT id, fact FROM memory WHERE status = 'active'").fetchall()
    n = 0
    for fid, fact in read:
        if any(is_name_fact(fact, nm) for nm in (list(user_names) + [""])):
            conn.execute(
                "UPDATE memory SET status = 'retired', updated_at = ? WHERE id = ?",
                (now, fid))
            n += 1
    if n:
        conn.commit()
    return n


def resolve_scope(persona: str = "", category: str = "muu",
                  intimate: bool = False, privacy: dict = None) -> tuple:
    """Tagastab (persona_omanik_või_None, scope) uue fakti jaoks.

    OMANIKU LÕPLIK OTSUS (10.11.2026):
      * ühine mälu on oluliste kasutajafaktide VAIKEVÄÄRTUS;
      * intiimsus EI tee fakti automaatselt karakteripõhiseks;
      * ainus põhjus piiratud ulatuseks on kasutaja SELGESÕNALINE
        privaatsuskorraldus, mis on kontrollitud tema enda
        transkriptsioonist (vt privacy_scope.py).

    MIS MUUTUS: varem andis `intimate=True` tulemuse (persona, 'persona').
    Tagajärg oli mõõdetud killustumine – sama intiimne suhe Mayaga oli
    laiali kolme karakteri vahel (ID 38/40 custom, 50 romantiline,
    51/52 sarkastiline) ja ükski karakter ei näinud tervikpilti.

    `intimate` jääb signatuuri ÜHILDUVUSE pärast alles (vanad kutsujad ja
    `test_resolve_scope_allkiri_on_uhilduv`), aga ei mõjuta enam tulemust.
    `privacy` on privacy_scope otsus või None; mudeli väide siia ei jõua.
    """
    if privacy and privacy.get("private") is True:
        p = (persona or "").strip().lower()
        if p:
            return (p, "persona")
        # Korraldus on olemas, aga karakterit ei tea. Ei süstita kuhugi
        # automaatselt. NB: selline rida on leitav AINULT recall_memory
        # kaudu – vt search_facts(include_private=True), kus orvuks jäänud
        # 'private' rida on sõnaselgelt kaetud.
        return (None, "private")
    return (None, "shared")


def visibility_clause(persona: str = "", alias: str = "m") -> tuple:
    """Tagastab (SQL-tingimus, parameetrid) selle kohta, MIDA antud karakter näha tohib.

    Reegel: ühised faktid ('shared') on nähtavad kõigile; karakteripõhised
    ('persona') ainult omanikule; 'private' ei süstita kunagi automaatselt.
    Tühi persona => AINULT ühised faktid. See on turvaline vaikeväärtus:
    kui kutsuja karakterit ei tea, ei lekita me kellegi omi fakte.
    """
    p = (persona or "").strip().lower()
    if p:
        return (f" AND {alias}.scope != 'private'"
                f" AND ({alias}.scope = 'shared' OR {alias}.persona = ?) ", (p,))
    return (f" AND {alias}.scope = 'shared' ", ())


def upsert_fact(conn: sqlite3.Connection, fact: str, category: str = "muu",
                confidence: float = 0.6, source: str = "kone",
                now: str = None, persona: str = None,
                scope: str = "shared", scope_reason: str = None) -> dict:
    """Lisab fakti elutsüklireeglitega.

    Tagastab {"action": ..., "id": ..., "affected": [...]}, kus action on:
      "duplicate"  – täpselt sama fakt (normaliseeritult) on juba olemas;
                     uuendame ainult kindlust ja updated_at
      "supersede"  – sama teema, uuem sõnastus -> vana märgitakse
                     'superseded' ja viitab uuele
      "conflict"   – sama teema, aga eitus läks vastupidiseks -> vana
                     märgitakse 'conflicted', uus jääb aktiivseks
      "insert"     – uus teema

    Miks see vajalik on: varem oli ainus kaitse `fact TEXT UNIQUE`, mis
    peatas ainult TÄHEMÄRGILT identsed read. "Peetril on BMW" ja "Peetril on
    valge BMW" oleksid elanud mõlemad igavesti, ilma et keegi teaks, kumb
    kehtib.
    """
    fact = (fact or "").strip()
    if not fact:
        return {"action": "skipped", "id": None, "affected": []}

    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    norm = normalize_fact(fact)
    subject = derive_subject_key(fact, category)
    c = conn.cursor()

    # 1. Täpne duplikaat (normaliseeritud)
    dup = c.execute(
        "SELECT id, confidence FROM memory WHERE norm_key = ? AND status = 'active'",
        (norm,),
    ).fetchone()
    if dup:
        new_conf = min(1.0, max(float(dup[1] or 0.6), float(confidence)) + 0.05)
        c.execute(
            "UPDATE memory SET confidence = ?, updated_at = ?, hit_count = hit_count + 1 WHERE id = ?",
            (new_conf, now, dup[0]),
        )
        conn.commit()
        return {"action": "duplicate", "id": dup[0], "affected": []}

    # 2. Sama teema varasemad aktiivsed faktid – sarnasuse, mitte täpse
    #    võtme järgi (vt SUBJECT_SIMILARITY).
    #    Rivaalid otsitakse AINULT selle nähtavuse seest, kus uus fakt sünnib.
    #    Muidu asendaks 'custom' karakteri fakt 'singer' karakteri oma ja
    #    karakterite eraldatus murduks just selle mehhanismi kaudu, mille
    #    ülesanne on mälu korras hoida.
    #    Täpselt sama ämber, mitte kogu nähtavus: karakteripõhine fakt ei tohi
    #    asendada ÜHIST fakti, sest siis kaoks see kõigilt teistelt.
    if (scope or "shared") == "shared":
        bucket_sql, bucket_args = " AND scope = 'shared' ", ()
    else:
        bucket_sql, bucket_args = " AND scope = ? AND persona IS ? ", (scope, persona or None)
    rivals = [
        (rid, old_fact)
        for rid, old_fact in c.execute(
            "SELECT id, fact FROM memory WHERE status = 'active'" + bucket_sql, bucket_args
        ).fetchall()
        if subject_similarity(fact, old_fact) >= SUBJECT_SIMILARITY
    ]

    c.execute(
        """INSERT INTO memory (timestamp, fact, category, confidence, source,
                               status, norm_key, subject_key, created_at, updated_at,
                               persona, scope, scope_reason)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)""",
        (now, fact, category, float(confidence), source, norm, subject, now, now,
         (persona or None), (scope or "shared"),
         # Põhjus kirjutatakse AINULT siis, kui fakt ei ole ühine. Ühise
         # fakti puhul ei ole midagi põhjendada ja NULL hoiab tabeli puhta.
         (scope_reason if (scope or "shared") != "shared" else None)),
    )
    new_id = c.lastrowid

    if not rivals:
        conn.commit()
        return {"action": "insert", "id": new_id, "affected": []}

    conflict = any(_has_negation(fact) != _has_negation(old) for _, old in rivals)
    new_status = "conflicted" if conflict else "superseded"
    for rid, _ in rivals:
        c.execute(
            "UPDATE memory SET status = ?, superseded_by = ?, updated_at = ? WHERE id = ?",
            (new_status, new_id, now, rid),
        )
    conn.commit()
    return {
        "action": "conflict" if conflict else "supersede",
        "id": new_id,
        "affected": [r for r, _ in rivals],
    }


def active_fact_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM memory WHERE status = 'active'").fetchone()[0]


# Vana kood süstis `ORDER BY id DESC LIMIT 15`. Sellel oli kolm viga korraga:
#   1) olekut ei filtreeritud -> 'superseded'/'conflicted' faktid läksid mudelile;
#   2) karakterit ei filtreeritud -> kõik said sama 15 fakti;
#   3) `id DESC` tähendas, et vanemad ALUSFAKTID ("Kasutaja nimi on Jaan",
#      "eelistab naise häält") jäid akna taha ja mudel ei näinud neid KUNAGI.
# Pärast karakterifiltrit mahub iga karakteri nähtav kogum tervikuna ära,
# nii et limiit on pigem turvaventiil kui tegelik piirang.
#
# MÕÕDETUD 09.11.2026: aktiivseid ühiseid fakte oli 30 ja 'custom' nägi
# 32 – limiit 30 oli juba SIDUV ja lõikas 2 fakti ära. Tõstetud 60-le.
# Kulu: ~40 tähemärki fakti kohta, seega 60 fakti ≈ 2.4 KB prompti.
# Järjestus on kindluse järgi, nii et kui limiit kunagi siduvaks saab,
# kaovad esimesena kõige nõrgemad faktid – mitte juhuslikud.
INJECT_LIMIT = 60


def facts_for_prompt(conn: sqlite3.Connection, persona: str = "",
                     limit: int = INJECT_LIMIT) -> list:
    """Faktid, mida tohib antud karakteri süsteemipromptisse süstida.

    Ainult aktiivsed, ainult nähtavad, tugevaimad eespool.
    """
    vis_sql, vis_args = visibility_clause(persona, alias="m")
    rows = conn.execute(
        f"""SELECT m.fact FROM memory m
            WHERE m.status = 'active' {vis_sql}
            ORDER BY m.confidence DESC, m.id DESC
            LIMIT ?""",
        tuple(vis_args) + (int(limit),),
    ).fetchall()
    return [r[0] for r in rows if r[0]]

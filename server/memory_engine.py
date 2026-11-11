# -*- coding: utf-8 -*-
"""
Iseseisev ja isoleeritud mälumootor Maya jaoks.
Matkib inimese mälutasandeid:
1. Töömälu (Working memory buffer)
2. Episoodiline arhiiv (Episodic archive)
3. Pikaajaline semantiline mälu (Semantic long-term facts)
"""

import os
import config  # MAYA seadistus (vt server/config.py)
import sqlite3
import memory_fts
import privacy_scope
import user_profile
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

DB_PATH = config.DB_TEE

DB_TIMEOUT = 10          # sekundit: ootame luku vabanemist, mitte ei kuku kohe


def db_connect(path=None, timeout=DB_TIMEOUT):
    """Ühtne SQLite-ühendus ajalimiidiga.

    Vaikimisi ootab sqlite3 luku taga 5 s ja viskab siis 'database is locked'.
    Baasi kirjutavad samaaegselt mitu komponenti (live-kõne tööriistad, mälu
    konsolideerimine, /api/reminders CRUD, meeldetuletuste valvur iga 5 s,
    Telegrami haru), seega anname lukule rohkem aega.
    """
    return sqlite3.connect(path or DB_PATH, timeout=timeout)


def init_memory_db():
    """Tagab mälutabelite ja indeksite olemasolu ilma olemasolevaid andmeid puutumata."""
    try:
        conn = db_connect()
        c = conn.cursor()

        # P3: WAL on PÜSIV andmebaasi omadus – piisab, kui see seatakse korra.
        # WAL-režiimis ei blokeeri kirjutaja lugejaid, mis kaotab enamiku
        # 'database is locked' juhtumitest mitme samaaegse kirjutaja korral.
        try:
            mode = c.execute("PRAGMA journal_mode=WAL").fetchone()
            c.execute("PRAGMA synchronous=NORMAL")
            print(f"--> [MÄLUMOOTOR]: SQLite journal_mode={mode[0] if mode else '?'}", flush=True)
        except Exception as wal_err:
            print(f"[MEMORY_ENGINE] WAL seadistamine ebaõnnestus: {wal_err}", flush=True)

        c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            fact TEXT NOT NULL UNIQUE
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_mem_fact ON memory(fact)")

        # Episoodiline arhiiv: sama skeem nagu listen_direct.py-s. Varem lõi selle
        # tabeli ainult listen_direct, mistõttu reaalajas kõne arhiveerimine võis
        # vaikselt ebaõnnestuda, kui see moodul polnud jooksnud.
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
        c.execute("CREATE INDEX IF NOT EXISTS idx_archive_date ON conversation_archive(date_str)")

        # Toome sisse memory.json, kui tabel peaks tühi olema
        c.execute("SELECT count(*) FROM memory")
        if c.fetchone()[0] == 0 and os.path.exists(str(config.JUUR / "memory.json")):
            with open(str(config.JUUR / "memory.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    f_val = item.get("fact", "").strip()
                    t_val = item.get("date", "2026-10-27")
                    if f_val:
                        c.execute("INSERT OR IGNORE INTO memory (timestamp, fact) VALUES (?, ?)", (t_val, f_val))
            conn.commit()

        # FAAS D: FTS5-indeksid ja faktide elutsükli veerud. Aditiivne ja
        # idempotentne – olemasolevaid ridu ei muudeta ega kustutata.
        try:
            changed = memory_fts.ensure_schema(conn)
            if changed["columns_added"] or changed["tables_created"]:
                print(
                    f"--> [MÄLUMOOTOR]: Skeem uuendatud – veerge {len(changed['columns_added'])}, "
                    f"tabeleid {changed['tables_created']}",
                    flush=True,
                )
                memory_fts.rebuild_index(conn)
            n = memory_fts.backfill_fact_metadata(conn)
            if n:
                print(f"--> [MÄLUMOOTOR]: Faktide metaandmed täidetud {n} reale", flush=True)
        except Exception as fts_err:
            print(f"[MEMORY_ENGINE] FTS skeemi uuendus ebaõnnestus: {fts_err}", flush=True)

        conn.close()
    except Exception as e:
        print(f"[MEMORY_ENGINE] Initsialiseerimise viga: {e}", flush=True)

MAYA_OPENED_CALL = "(Maya alustas kõnet ise)"

# --- FAKTIANALÜÜSI MUDELI VALIK -----------------------------------------
#
# Varem oli siin kõvakodeeritud "gemini-2.5-flash". Kui see mudeli-ID
# teenuses välja vahetati, hakkas iga konsolideerimine lõppema veaga
# "404 NOT_FOUND" ja ükski fakt ei jõudnud enam pikaajalisse mällu.
# Ülejäänud projekt kasutas juba liikuvaid aliaseid (nt
# "gemini-flash-lite-latest"), mis ei aegu – siin seda ei tehtud.
#
# Lahendus on kolmekihiline:
#   1) keskkonnamuutuja MAYA_MEMORY_MODEL (operaatori viimane sõna);
#   2) kandidaatide kaskaad, kus esimesed on AEGUMATUD aliased;
#   3) kui kõik 404-vad, küsitakse teenuselt mudelite nimekiri ja
#      valitakse sealt sobiv flash-mudel automaatselt.
# Töötav mudel jäetakse protsessi mällu, et iga kõne lõpus uuesti ei otsiks.

MEMORY_MODEL_CANDIDATES = [
    "gemini-flash-latest",        # liikuv alias – ei aegu
    "gemini-2.5-flash",           # praegune GA nimi
    "gemini-flash-lite-latest",   # sama alias, mida kasutab listen_direct.py
    "gemini-2.0-flash",           # varasem põlvkond, viimane õlekõrs
]

_RESOLVED_MEMORY_MODEL = None


def _is_model_missing_error(err) -> bool:
    """Kas tegu on 'mudelit ei ole' veaga (404 / NOT_FOUND / unsupported)?"""
    msg = str(err).upper()
    return ("404" in msg) or ("NOT_FOUND" in msg) or ("NOT FOUND" in msg) or ("IS NOT FOUND" in msg)


def _discover_text_model(client):
    """Küsib teenuselt elusate mudelite nimekirja ja valib sobiva flash-mudeli."""
    try:
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").replace("models/", "")
            if not name:
                continue
            actions = (
                getattr(m, "supported_actions", None)
                or getattr(m, "supported_generation_methods", None)
                or []
            )
            if actions and "generateContent" not in actions:
                continue
            low = name.lower()
            if "flash" not in low:
                continue
            # TTS-, pildi-, heli- ja live-mudelid ei sobi tekstianalüüsiks
            if any(bad in low for bad in ("tts", "image", "audio", "live", "embedding", "vision")):
                continue
            print(f"--> [MÄLUMOOTOR]: Avastasin teenusest sobiva mudeli: {name}", flush=True)
            return name
    except Exception as e:
        print(f"[MEMORY_ENGINE] Mudelite nimekirja lugemine ebaõnnestus: {e}", flush=True)
    return None


def _memory_model_order():
    """Proovimisjärjekord: env → varem töötanud → kandidaadid."""
    order = []
    env_model = os.environ.get("MAYA_MEMORY_MODEL", "").strip()
    if env_model:
        order.append(env_model)
    if _RESOLVED_MEMORY_MODEL:
        order.append(_RESOLVED_MEMORY_MODEL)
    order.extend(MEMORY_MODEL_CANDIDATES)
    seen = set()
    return [m for m in order if not (m in seen or seen.add(m))]


async def extract_facts_json(client, prompt: str):
    """Küsib mudelilt JSON-faktid, vahetades 404 korral automaatselt mudelit.

    Tagastab parsitud sõnastiku või None. Ei paisuta erindeid välja –
    kutsuja ei tohi mälu konsolideerimist katkestada faktianalüüsi pärast.
    """
    global _RESOLVED_MEMORY_MODEL

    tried = []
    for model_name in _memory_model_order():
        tried.append(model_name)
        try:
            res = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            if res and res.text:
                data = json.loads(res.text)
                if _RESOLVED_MEMORY_MODEL != model_name:
                    print(f"--> [MÄLUMOOTOR]: Faktianalüüsi mudel: {model_name}", flush=True)
                    _RESOLVED_MEMORY_MODEL = model_name
                return data
            return None
        except Exception as e:
            if _is_model_missing_error(e):
                print(f"--> [MÄLUMOOTOR]: Mudel '{model_name}' pole saadaval, proovin järgmist", flush=True)
                continue
            # Muu viga (kvoot, võrk, vigane JSON) – mudeli vahetamine ei aita
            print(f"[MEMORY_ENGINE] Faktide eraldamise viga ({model_name}): {e}", flush=True)
            return None

    # Kõik kandidaadid 404 – küsime teenuselt, mis üldse saadaval on
    discovered = _discover_text_model(client)
    if discovered and discovered not in tried:
        try:
            res = await asyncio.to_thread(
                client.models.generate_content,
                model=discovered,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            if res and res.text:
                _RESOLVED_MEMORY_MODEL = discovered
                return json.loads(res.text)
        except Exception as e:
            print(f"[MEMORY_ENGINE] Ka avastatud mudel '{discovered}' ebaõnnestus: {e}", flush=True)

    print(
        f"[MEMORY_ENGINE] Ükski mudel ei vastanud (proovitud: {', '.join(tried)}). "
        f"Dialoog on arhiivis olemas, faktid jäid eraldamata. "
        f"Määra töötav mudel keskkonnamuutujaga MAYA_MEMORY_MODEL.",
        flush=True,
    )
    return None


class SessionWorkingMemory:
    """Iga reaalajas kõne lühiajaline töömälu puhver.

    Reaalajas kõne transkriptsioon saabub Gemini Live'ist väikeste
    fragmentidena ("Ma", " ostsin", " täna..."), mitte terviklausetena.
    Seepärast liidab add_turn järjestikused sama rolli fragmendid üheks
    vooruks – muidu tekiks sadu ühesõnalisi "voore", millest ei saa
    kasulikku dialoogi ega faktianalüüsi koostada.
    """

    def __init__(self, session_id: str = "live_call"):
        self.session_id = session_id
        self.turns = []

    def add_turn(self, role: str, text: str, merge: bool = True):
        """Lisab vooru või liidab fragmendi eelmise vooru külge.

        merge=True (vaikimisi) on mõeldud Live API transkriptsiooni
        fragmentidele: need liidetakse TÄHT-TÄHELT, sest API saadab
        sõnavahed juba fragmentide sees. Seepärast hoiame puhvris
        töötlemata teksti ('raw') ja trimmime alles väljundis ('text').

        merge=False on terviklausete jaoks (klaviatuuriviip, varutee),
        et kaks eraldi ütlust ei liituks üheks vooruks.
        """
        if not text:
            return
        raw = str(text)
        if not raw.strip():
            return

        now_hms = datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%H:%M:%S")

        if merge and self.turns and self.turns[-1]["role"] == role:
            prev = self.turns[-1]
            prev["raw"] = prev.get("raw", prev["text"]) + raw
            prev["text"] = prev["raw"].strip()
            prev["time"] = now_hms
            return

        self.turns.append({
            "role": role,
            "raw": raw,
            "text": raw.strip(),
            "time": now_hms,
        })

    def get_full_transcript(self) -> str:
        lines = []
        for t in self.turns:
            prefix = user_profile.get_name() if t["role"] == "user" else "Maya"
            lines.append(f"{prefix}: {t['text']}")
        return "\n".join(lines)

    def get_dialogue_pairs(self) -> list:
        """Seob voorud (kasutaja küsimus -> Maya vastus) paarideks arhiveerimiseks.

        Varem kirjutati arhiivi reply_text asemele kõvakodeeritud tekst
        'Reaalajas kõne dialoog' ja ainult user-rolli voorude pealt – kuna
        user-voore ei salvestatud kunagi, ei jõudnud arhiivi mitte midagi.
        """
        pairs = []
        current_user = None
        for t in self.turns:
            if t["role"] == "user":
                if current_user is not None:
                    # Kaks kasutaja vooru järjest (Maya ei jõudnud vastata)
                    pairs.append((current_user, ""))
                current_user = t["text"]
            else:
                pairs.append((current_user if current_user is not None else MAYA_OPENED_CALL, t["text"]))
                current_user = None
        if current_user is not None:
            pairs.append((current_user, ""))
        return [(u, r) for u, r in pairs if (u and u != MAYA_OPENED_CALL) or r]

    def is_empty(self) -> bool:
        return len(self.turns) == 0

_STOPWORDS_ET = {
    "kas", "oled", "mida", "kuidas", "millal", "kes", "mis", "see", "ja", "aga",
    "siis", "ning", "või", "ei", "ma", "sa", "ta", "me", "te", "nad", "on", "oli",
    "olen", "mulle", "sulle", "minu", "sinu", "teda", "selle", "need", "kui",
}


def _keywords(text: str) -> set:
    """Eraldab tekstist tähenduslikud märksõnad (väikesed tähed, >3 tähte)."""
    import re as _re
    words = _re.findall(r"[0-9a-zõäöüšžA-ZÕÄÖÜŠŽ]+", (text or "").lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS_ET}


def recall_relevant_memories(query: str, limit: int = 6, persona: str = "") -> str:
    """Otsib pikaajalisest mälust ja vestlusarhiivist asjakohaseid mälestusi.

    persona piirab faktid selle karakteri nähtavusse (ühised + tema omad).
    Tühi persona => ainult ühised faktid.
    """
    results = []
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        
        # 1. Pikaajalised faktid – FTS5, ainult AKTIIVSED (FAAS D).
        #    Asendatud ja vastuolulised faktid jäävad andmebaasi ajaloona
        #    alles, kuid EI jõua enam Maya prompti.
        try:
            fact_hits = memory_fts.search_facts(
                conn, query, limit=10, persona=persona, include_private=True
            )
        except Exception as fts_err:
            print(f"[MEMORY_ENGINE] Faktiotsing ebaõnnestus: {fts_err}", flush=True)
            fact_hits = []
        if fact_hits:
            results.append(
                "ASJAKOHASED FAKTID:\n"
                + "\n".join(f"- [{h['category']}] {h['fact']}" for h in fact_hits)
            )
        else:
            # Varuvariant: kui otsing ei andnud midagi, anname hiljutised
            # aktiivsed faktid, et Maya ei alustaks tühjalt kohalt.
            vis_sql, vis_args = memory_fts.visibility_clause(persona, alias="memory")
            recent = c.execute(
                "SELECT fact, category FROM memory WHERE status = 'active' "
                + vis_sql + " ORDER BY id DESC LIMIT 8",
                tuple(vis_args),
            ).fetchall()
            if recent:
                results.append(
                    "HILJUTISED FAKTID:\n"
                    + "\n".join(f"- [{cat}] {f}" for f, cat in recent)
                )

        # 2. Episoodiline arhiiv – FTS5 + BM25 + värskus (FAAS D).
        #    Varem: `user_text LIKE '%sona%' OR ...` ilma järjestuseta,
        #    ainult ORDER BY id DESC. Alamsõne-otsing tähendas, et "ema"
        #    leidis ka "teema" ja "probleem", ja tulemused olid suvalises
        #    järjekorras. Mõõdetud kuldstandardil: Recall@5 43,2% -> 69,8%,
        #    MRR 39,1% -> 64,3%, valepositiivid 30,7% -> 28,8%.
        try:
            hits = memory_fts.search_archive(conn, query, limit=limit)
        except Exception as fts_err:
            print(f"[MEMORY_ENGINE] FTS otsing ebaõnnestus: {fts_err}", flush=True)
            hits = []
        if hits:
            arc_lines = [
                f"[{h['timestamp']}] {user_profile.get_name()}: {h['user_text']} "
                f"| Maya: {h['reply_text']}"
                for h in hits
            ]
            results.append("VARASEMAD ASJAKOHASED VESTLUSED ARHIIVIST:\n" + "\n".join(arc_lines))

        conn.close()
    except Exception as e:
        print(f"[MEMORY_ENGINE] Viga meenutamisel: {e}", flush=True)

    return "\n\n".join(results) if results else "Mälestusi ei leitud."

# Omanikureegel elab memory_fts-is (puhas loogika, testitav ilma google-genai
# sõltuvust laadimata). Siin hoiame nime alles, et vanad kutsujad töötaksid.
# Omanikureegel elab memory_fts-is (puhas loogika, testitav ilma
# google-genai sõltuvust laadimata). Siin ainult alias.
INTIMATE_OWNER = memory_fts.INTIMATE_OWNER
resolve_scope = memory_fts.resolve_scope


def _logi_privaatsus(otsus: dict) -> None:
    """Logib privaatsusotsuse SISUTA.

    Kasutaja lause ja faktide tekst lähevad andmebaasi `scope_reason`
    veergu, MITTE journaldi: logi roteerub ja save_facts_direct ei logi
    teadlikult fakti sisu. Siia tuleb ainult see, mis on vajalik
    diagnoosiks – kui palju, mis režiimis, mis lahendusega.
    """
    a = otsus.get("audit") or {}
    piiratud = [d for d in otsus.get("decisions", [])
                if d.get("scope") != "shared"]
    if not a.get("anchor_found"):
        if a.get("model_claim"):
            print("--> [PRIVAATSUS]: mudel väitis privaatsust, "
                  "transkriptsioon ei kinnita – väide eiratud", flush=True)
        return
    print("--> [PRIVAATSUS]: korraldus voorus %s, režiim=%s, lahendus=%s, "
          "piiratud %d / ühiseks jäi %d"
          % (a.get("anchor_turn"), a.get("target_mode"),
             a.get("resolution"), len(piiratud),
             len(a.get("left_shared") or [])), flush=True)
    halvad = [c for c in (a.get("candidates") or [])
              if str(c[2]).startswith("invalid_turn:")]
    if halvad:
        print("--> [PRIVAATSUS]: %d fakti voorunumber ei läbinud kontrolli "
              "(%s) – need jäid ühiseks"
              % (len(halvad), ", ".join(sorted({str(c[2]) for c in halvad}))),
              flush=True)
    if otsus.get("needs_clarification"):
        print("--> [PRIVAATSUS]: sihtmärk ebaselge – KÕIK jäi ühiseks. "
              "Täpsustav küsimus jäi esitamata (kõne oli juba lõppenud).",
              flush=True)


def save_facts_direct(facts_list: list, source: str = "kone", persona: str = ""):
    """Salvestab faktid elutsüklireeglitega (FAAS D).

    Võtab vastu nii vana kui uue kuju:
      * vana: ["fakt tekstina", ...]
      * uus:  [{"fact": ..., "category": ..., "confidence": ...}, ...]

    Varem oli siin `INSERT OR IGNORE`, mille ainus kaitse oli `fact UNIQUE`.
    See peatas ainult TÄHEMÄRGILT identsed read – "Peetril on valge Volvo" ja
    "Peetril on sinine Volvo" oleksid mõlemad igavesti aktiivsed, ilma et
    keegi teaks, kumb kehtib. Nüüd käib see läbi memory_fts.upsert_fact,
    mis tuvastab duplikaadid, asendamised ja vastuolud.

    LOGIMINE: faktide SISU enam logisse ei kirjutata – ainult kategooria,
    tegevus ja pikkus. Logi loeb journald ja see on isiklik info.
    """
    if not facts_list:
        return
    try:
        now_str = datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_PATH, timeout=10)
        memory_fts.ensure_schema(conn)

        tally = {}
        for item in facts_list:
            if isinstance(item, dict):
                text = str(item.get("fact", "")).strip()
                category = str(item.get("category", "muu")).strip().lower()
                try:
                    confidence = float(item.get("confidence", 0.6))
                except (TypeError, ValueError):
                    confidence = 0.6
                intimate = bool(item.get("intimate", False))
            else:
                text, category, confidence = str(item).strip(), "muu", 0.6
                intimate = False

            if len(text) <= 3:
                continue
            # Nimi elab settings.user_name sees, mitte faktitabelis. Kaks
            # tõeallikat läheksid paratamatult lahku.
            if memory_fts.is_name_fact(text, user_profile.get_name()):
                print("--> [MÄLUMOOTOR FAKT]: nimeväide jäetakse vahele "
                      f"({len(text)} tähemärki) – nime haldab user_profile",
                      flush=True)
                continue
            if category not in memory_fts.FACT_CATEGORIES:
                category = "muu"
            confidence = min(1.0, max(0.1, confidence))

            # Ulatuse otsus tuleb privacy_scope'ist, kui kutsuja on selle
            # juba teinud (häälkõne tee). Tekstitee ja vanad kutsujad
            # langevad resolve_scope'ile, mis annab nüüd alati 'shared'.
            if isinstance(item, dict) and "_scope" in item:
                scope = item.get("_scope") or "shared"
                owner = item.get("_persona")
                scope_reason = item.get("_scope_reason")
            else:
                owner, scope = resolve_scope(persona, category, intimate)
                scope_reason = None
            res = memory_fts.upsert_fact(
                conn, text, category=category, confidence=confidence,
                source=source, now=now_str, persona=owner, scope=scope,
                scope_reason=scope_reason,
            )
            tally[res["action"]] = tally.get(res["action"], 0) + 1
            print(
                f"--> [MÄLUMOOTOR FAKT]: {res['action']} "
                f"(kategooria={category}, kindlus={confidence:.2f}, {len(text)} tähemärki, "
                f"ulatus={scope}{'/' + owner if owner else ''})",
                flush=True,
            )

        aktiivseid = memory_fts.active_fact_count(conn)
        conn.close()
        print(
            f"--> [MÄLUMOOTOR]: Faktid töödeldud {tally} – aktiivseid fakte kokku {aktiivseid}",
            flush=True,
        )
    except Exception as e:
        print(f"[MEMORY_ENGINE] Viga faktide salvestamisel: {e}", flush=True)


def build_extract_prompt(transcript: str) -> str:
    """Faktide eraldamise prompt. ÜKS allikas nii häälele kui tekstile.

    FAAS D: mõõdetud probleem oli, et 53 kõnest 41 lõppes teatega "Uusi
    püsivaid fakte ei tuvastatud" ja 769 vestlusest oli sündinud 5 fakti.
    Vana prompt küsis fakte, mida "Maya peaks mäletama ka AASTA pärast", ja
    lisas "kui miski on ebaselge, siis EI salvestata" – kahe peale nii kõrge
    lävend, et mudel vastas peaaegu alati "ei".

    Uus prompt langetab lävendit ja nõuab kategooriat + kindlust, nii et
    ebakindlat infot ei pea enam ära viskama – selle saab salvestada madala
    kindlusega ja otsing arvestab sellega.
    """
    kategooriad = ", ".join(memory_fts.FACT_CATEGORIES)
    # Nimi tuleb ühest tõeallikast. Varem oli see siin kõvasti sees, nii
    # et pärast nime muutmist käskis prompt endiselt otsida vana nime
    # ridu – ja transkriptsioonis neid enam ei olnud.
    nimi = user_profile.get_name()
    return f"""
Oled mäluanalüütik. Allpool on vestlus {nimi}i ja Maya vahel.

{transcript}

ÜLESANNE: leia {nimi}i kohta käivad PÜSIVAD seigad – asjad, mis kehtivad ka
nädalate pärast. Näiteks: mis tal on, mida ta teeb, mis talle meeldib või ei
meeldi, kellega ta suhtleb, mida plaanib, millega tegeleb, kuidas tal läheb.

REEGLID:
- Iga rida algab NUMBRIGA. Iga fakti juurde pane väli "turn" – selle rea
  number, millelt fakt pärineb. See peab olema "{nimi}:" rida, mitte Maya
  rida ja mitte välja mõeldud number. Kui sa ei oska öelda, millisest reast
  fakt tuli, jäta "turn" tühjaks – siis jääb fakt lihtsalt ühiseks.
- Tugine AINULT "{nimi}:" ridadele. Maya read on assistendi jutt – neist ei
  tohi fakte tuletada ega oletada.
- Ära salvesta hetkeseisu ("tal on praegu igav") ega vestluse käiku.
- Kui oled milleski ebakindel, ÄRA viska seda ära – salvesta madala
  kindlusega (0.3-0.5). Kindel ja korduvalt kinnitatud info: 0.8-1.0.
- Sõnasta iga fakt lühikese iseseisva lausena, mis on arusaadav ka ilma
  vestluse kontekstita.
- Kategooria peab olema üks neist: {kategooriad}
- ÄRA salvesta kasutaja enda nime faktina (nt "Kasutaja nimi on ..."). Nime
  haldab eraldi süsteem ja fakt läheks sellega vastuollu. Teiste inimeste
  nimed (sõbrad, pereliikmed) salvesta tavaliselt.
- KUI kasutaja ütles vestluses, mis on tema enda nimi, või parandas seda
  (nt "minu nimi on X", "mind kutsutakse X", "minu õige nimi on X"), pane
  see eraldi välja "user_name". Kui ta seda ei teinud, jäta "user_name"
  tühjaks. Pane sinna AINULT eesnimi, mitte lause.
- Märgi "intimate": true AINULT siis, kui fakt puudutab seksuaalsust või
  romantilist/intiimset lähedust. Kõik muu on false – ka tundlikud teemad
  nagu tervis, raha, perekond või harjumused on tavalised faktid.
  Näited: "{nimi}il on Mayaga intiimne suhe" -> true.
          "{nimi}ile meeldib Pohjatuul" -> false.
          "{nimi} ajab samakat" -> false.
          "{nimi} peab end häbelikuks" -> false.
  MIKS: see on AINULT märgend auditi jaoks. Intiimsus EI tee fakti
  karakteripõhiseks – kõik faktid on kõigile karakteritele ühised, ka
  intiimsed. Ainus erand on {nimi}i enda selgesõnaline korraldus
  ("see jääb meie vahele"), mille üle otsustab eraldi süsteem, mitte sina.

Tagasta AINULT JSON:
{{"has_facts": true/false, "user_name": "", "facts": [
   {{"fact": "lühike lause", "category": "üks lubatud kategooriatest",
     "confidence": 0.0-1.0, "intimate": true/false, "turn": 0}}
]}}
Kui {nimi} ei öelnud midagi püsivat, tagasta {{"has_facts": false, "facts": []}}.
"""


async def learn_from_text_turn(user_text: str, reply_text: str, persona: str = ""):
    """Õpib fakte ÜHEST tekstivestluse voorust.

    MIKS SEE OLEMAS ON: web_maya.py kutsus aastaid `core.save_conversation_turn`,
    mida EI OLE KUNAGI OLEMAS OLNUD. Kutse oli `hasattr()` taga, seega see
    vaikselt ei teinud midagi – kogu tekstivestlus jäi pikaajalisest mälust
    välja ja Maya õppis ainult häälkõnedest. Lisaks tagastas see sünkroonne
    funktsioon None, millest tehti `asyncio.create_task(None)` -> TypeError,
    mistõttu iga voogedastatud vastus lõppes kliendile veaga "done" asemel.

    Arhiveerimise teeb juba `listen_direct.log_conversation_turn`; siin
    käib AINULT faktide eraldamine.
    """
    user_text = (user_text or "").strip()
    reply_text = (reply_text or "").strip()
    if not user_text:
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    transcript = f"{config.KASUTAJA_NIMI}: {user_text}\nMaya: {reply_text}"
    try:
        client = genai.Client(api_key=api_key)
        data = await extract_facts_json(client, build_extract_prompt(transcript))
        if data and data.get("has_facts") and data.get("facts"):
            date_str = datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y_%m_%d")
            save_facts_direct(data["facts"], source=f"tekst_{date_str}", persona=persona)
        elif data is not None:
            print("--> [MÄLUMOOTOR]: Tekstivoorust uusi fakte ei tuvastatud", flush=True)
    except Exception as e:
        print(f"[MEMORY_ENGINE] Tekstivooru õppimise viga: {e}", flush=True)


async def consolidate_session_to_memory(working_mem: SessionWorkingMemory,
                                        persona: str = ""):
    """Käivitub kõne lõpus taustal nagu uneprotsess: arhiveerib ja konsolideerib faktid."""
    if working_mem.is_empty():
        return

    transcript = working_mem.get_full_transcript()
    now = datetime.now(ZoneInfo("Europe/Tallinn"))
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    weekday_str = now.strftime("%A")

    # 1. Talletame episoodilisse arhiivi (conversation_archive) päris
    #    dialoogipaaridena: kasutaja tekst JA Maya tegelik vastus.
    pairs = working_mem.get_dialogue_pairs()
    if pairs:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            # Karakteri veerg võib vanas baasis puududa – ära kuku kokku.
            has_persona = "persona" in {
                r[1] for r in c.execute("PRAGMA table_info(conversation_archive)")
            }
            for user_text, reply_text in pairs:
                if has_persona:
                    c.execute("""
                    INSERT INTO conversation_archive (timestamp, date_str, weekday_str, user_text, reply_text, persona)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, (now_str, date_str, weekday_str, user_text, reply_text,
                          (persona or "").strip().lower() or None))
                else:
                    c.execute("""
                    INSERT INTO conversation_archive (timestamp, date_str, weekday_str, user_text, reply_text)
                    VALUES (?, ?, ?, ?, ?)
                    """, (now_str, date_str, weekday_str, user_text, reply_text))
            conn.commit()
            conn.close()
            print(
                f"--> [MÄLUMOOTOR]: Kõne arhiveeritud – {len(pairs)} dialoogipaari "
                f"({len(working_mem.turns)} vooru)",
                flush=True,
            )
        except Exception as e:
            print(f"[MEMORY_ENGINE] Arhiveerimise viga: {e}", flush=True)
    else:
        print("--> [MÄLUMOOTOR]: Arhiveeritavaid dialoogipaare ei tekkinud", flush=True)

    # 2. Pikaajaline analüüs Gemini abil (faktide eraldamine)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return

    # Ilma kasutaja voorudeta pole Peetri kohta midagi õppida – Maya enda
    # jutust fakte ei tohi tuletada (muidu salvestuks mudeli oletus faktina).
    if not any(t["role"] == "user" for t in working_mem.turns):
        print("--> [MÄLUMOOTOR]: Kasutaja voorud puuduvad, faktianalüüs jäetakse vahele", flush=True)
        return

    # NUMMERDATUD transkriptsioon: mudel peab iga fakti juures ütlema,
    # millisest reast ta selle võttis. Numbrid on needsamad, mida
    # privacy_scope.validate_fact_turn hiljem kontrollib.
    indexed_turns = privacy_scope.index_turns(working_mem.turns)
    extract_prompt = build_extract_prompt(
        privacy_scope.numbered_transcript(indexed_turns,
                                          user_profile.get_name()))

    try:
        client = genai.Client(api_key=api_key)
        data = await extract_facts_json(client, extract_prompt)

        # VARUTEE. Esmane tee on tööriist set_user_name, mille mudel kutsub
        # KÕNE AJAL. Mõõdetud 09.11.2026: mudel võib selle kutsumise ära
        # jätta ja ainult VÄITA, et ta tegi seda. Siis parandab nime kõne
        # lõpus see haru – hiljem kui tööriist, aga kindlalt.
        if data:
            uus_nimi = str(data.get("user_name", "") or "").strip()
            if uus_nimi and user_profile.valid_name(uus_nimi):
                vana = user_profile.get_name(use_cache=False)
                if uus_nimi != vana:
                    r = user_profile.set_name(uus_nimi)
                    print(f"--> [MÄLUMOOTOR]: nimi kõne lõpus parandatud "
                          f"(varutee): {r['teade']}", flush=True)
                    try:
                        conn2 = sqlite3.connect(DB_PATH, timeout=10)
                        try:
                            memory_fts.ensure_schema(conn2)
                            k = memory_fts.retire_name_facts(
                                conn2, (vana, uus_nimi))
                        finally:
                            conn2.close()
                        if k:
                            print(f"--> [MÄLUMOOTOR]: {k} vananenud nimeväidet "
                                  f"pensionile", flush=True)
                    except Exception as e:
                        print(f"[MEMORY_ENGINE] Nimefaktide pensionile "
                              f"saatmine ebaõnnestus: {e}", flush=True)

        if data and data.get("has_facts") and data.get("facts"):
            faktid = [f for f in data["facts"] if isinstance(f, dict)]
            for i, f in enumerate(faktid):
                f["id"] = i
            otsus = privacy_scope.resolve_fact_scopes(
                working_mem.turns, faktid, persona,
                user_name=user_profile.get_name())
            kaart = {d["fact_id"]: d for d in otsus["decisions"]}
            for f in faktid:
                d = kaart.get(f["id"])
                if d:
                    f["_scope"] = d["scope"]
                    f["_persona"] = d["persona"]
                    f["_scope_reason"] = d["scope_reason"]
            _logi_privaatsus(otsus)
            save_facts_direct(data["facts"], source=f"kone_{date_str}", persona=persona)
        elif data is not None:
            print("--> [MÄLUMOOTOR]: Uusi püsivaid fakte ei tuvastatud", flush=True)
    except Exception as e:
        print(f"[MEMORY_ENGINE] Faktide eraldamise viga: {e}", flush=True)

init_memory_db()

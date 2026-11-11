# -*- coding: utf-8 -*-
"""KASUTAJA NIMI — üks tõeallikas.

MIKS SEE MOODUL ON OLEMAS
-------------------------
Kasutaja nimi oli kõvasti sisse kirjutatud 101 kohta: kõigi 10 karakteri
prompti ("Sinu vestluspartner on Jaan"), süsteemiprompti, faktide
eraldamise prompti, transkriptsiooni siltidesse ja lauljapiirkonda.

Tagajärg: kui kasutaja ütles "jäta meelde, et minu nimi on X", siis
mälufakt võis muutuda, aga süsteemiprompt ütles endiselt vana nime — ja
prompt on mudeli jaoks tugevam kui üks fakt faktiploki sees. Nimi ei
muutunud kunagi päriselt.

Nüüd on nimi ühes kohas: `settings` tabeli real `user_name`. Kõik promptid
kasutavad kohahoidjat `{USER}`, mis asendatakse käitusajal.

Nimi on muudetav KAHEL teel:
  1. tööriist `set_user_name` — mudel kutsub seda KOHE kõne ajal, kui
     kasutaja nime ütleb. Ei pea ootama kõne lõpu konsolideerimist.
  2. käsitsi `set_user_name()` funktsiooni kaudu.
"""

import json
import config  # MAYA seadistus (vt server/config.py)
import re
import sqlite3

# ÜHILDUVUS: `DB_PATH` jääb alles nende kohtade jaoks, mis
# vajavad teed stringina (varundus, memory_fts). AKTIIVSE
# kasutaja tee saab alati `config.db_tee()`-st.
DB_PATH = config.DB_TEE

# Kohahoidja, mis promptides nime asemel seisab.
PLACEHOLDER = "{USER}"

# Kui andmebaasis nime ei ole, kasutame seda. Ei ole tühi string, sest
# "Sinu vestluspartner on ." oleks mudelile segadust tekitav.
DEFAULT_NAME = config.KASUTAJA_NIMI

# Eesnimi: tähed, sidekriips, ülakoma. Numbrid ja kirjavahemärgid välja.
# Ilma selle piiranguta saaks mudel kirjutada settingu sisse suvalise
# lause ja see läheks iga prompti sisse.
_NAME_RE = re.compile(r"^[^\W\d_][^\W\d_\-' ]{0,30}([ \-'][^\W\d_][^\W\d_\-' ]{0,30}){0,2}$",
                      re.UNICODE)

# Kui palju aega peab mööduma, enne kui nime tohib tagasi muuta.
# MÕÕDETUD VIGA 09.11.2026: kasutaja ütles 'romantiline' karakterile uue
# nime, tööriist salvestas selle, ja 25 sekundit hiljem kutsus MUDEL ISE
# set_user_name vana nimega tagasi ("Sinu nimi ongi Jaan, kallis").
# Mudeli enda veendumus ei tohi kasutaja öeldut üle kirjutada.
REVERT_GUARD_S = 1800   # 30 minutit
# Mitut viimast nime ajaloos hoiame. Kaitse peab blokeerima naasmise IGA
# hiljuti kasutatud nime juurde, mitte ainult vahetu eelmise – muidu saab
# mudel ühe vahesammuga vanale nimele tagasi minna.
HISTORY_MAX = 10

_cache = {"name": None}


def _conn(path=None):
    return config.connect(timeout=10, tee=path)


def ensure_schema(conn) -> bool:
    """Loob `settings` tabeli. Aditiivne ja idempotentne."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    return True


def valid_name(name: str) -> bool:
    """Kas see on usutav nimi, mitte lause?"""
    n = (name or "").strip()
    return bool(n) and len(n) <= 60 and bool(_NAME_RE.match(n))


def get_name(path=None, use_cache: bool = True) -> str:
    """Kasutaja praegune nimi. Ei viska kunagi erindit.

    LOEB ALATI ANDMEBAASIST. Varem oli siin vahemälu ja see tekitas päris
    probleemi: kui nime muudeti VÄLJASPOOL jooksvat protsessi (nt
    haldustööriistaga), hoidis Maya protsess edasi vana nime kuni
    taaskäivituseni. Üks SQLite lugemine kõne alguses on tühine hind
    selle vea klassi kaotamise eest.

    `_cache` jääb alles ainult viimase teadaoleva väärtusena juhuks, kui
    andmebaasi lugemine ebaõnnestub – siis on parem vastata viimase
    õige nimega kui kukkuda tagasi vaikenimele.
    """
    try:
        conn = _conn(path)
        try:
            ensure_schema(conn)
            r = conn.execute(
                "SELECT value FROM settings WHERE key = 'user_name'").fetchone()
        finally:
            conn.close()
        name = (r[0] if r else "").strip()
        if not valid_name(name):
            name = DEFAULT_NAME
    except Exception as e:
        print(f"[USER_PROFILE] Nime lugemine ebaõnnestus: {e}", flush=True)
        name = _cache["name"] or DEFAULT_NAME
    _cache["name"] = name
    return name


def set_name(name: str, path=None) -> dict:
    """Määrab uue nime. Tagastab {"ok", "old", "new", "teade"}.

    Lükkab tagasi, kui tegu ei ole usutava nimega – muidu satuks mudeli
    poolt valesti kuuldud lause iga karakteri prompti sisse.
    """
    uus = (name or "").strip()
    vana = get_name(path, use_cache=False)

    if not valid_name(uus):
        return {"ok": False, "old": vana, "new": vana,
                "teade": "See ei näe nime moodi välja – nimi jäi muutmata."}

    if uus == vana:
        return {"ok": True, "old": vana, "new": uus,
                "teade": f"Nimi on juba {uus}."}

    # TAGASIPÖÖRDE KAITSE. Kui hiljuti kasutusel olnud nime üritatakse
    # tagasi tuua, on see peaaegu kindlasti mudeli enda "parandus", mitte
    # kasutaja soov. Kasutaja saab nime ikka muuta – uueks nimeks kohe,
    # vanale naasta pärast ooteaega.
    hilju = _recent_names(path)
    if uus in hilju:
        vanus = hilju[uus]
        print(f"--> [KASUTAJA]: KEELDUN nime tagasi muutmast "
              f"'{vana}' -> '{uus}' (kasutusel {int(vanus)} s tagasi)",
              flush=True)
        return {"ok": False, "old": vana, "new": vana,
                "teade": (f"Kasutaja ütles ise, et tema nimi on {vana}. "
                          f"Seda ei muudeta tagasi nimeks {uus}. "
                          f"Kasuta nime {vana}.")}

    from datetime import datetime
    from zoneinfo import ZoneInfo
    nyyd = datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = _conn(path)
        try:
            ensure_schema(conn)
            # Ajalugu alles – tagasipöörde kaitse vajab seda.
            ajalugu = _read_history(path)
            ajalugu.append({"name": vana, "at": nyyd})
            ajalugu = ajalugu[-HISTORY_MAX:]
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) "
                "VALUES ('user_name_history',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (json.dumps(ajalugu, ensure_ascii=False), nyyd))
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('user_name',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at", (uus, nyyd))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "old": vana, "new": vana,
                "teade": f"Nime salvestamine ebaõnnestus: {e}"}

    _cache["name"] = uus
    print(f"--> [KASUTAJA]: nimi muudetud '{vana}' -> '{uus}'", flush=True)
    return {"ok": True, "old": vana, "new": uus,
            "teade": f"Nimi on nüüd {uus} (varem {vana})."}


def _read_history(path=None) -> list:
    """Nimeajalugu: [{"name":..., "at":...}, ...], uuemad lõpus."""
    try:
        conn = _conn(path)
        try:
            ensure_schema(conn)
            r = conn.execute(
                "SELECT value FROM settings WHERE key = 'user_name_history'"
            ).fetchone()
        finally:
            conn.close()
        if r and r[0]:
            d = json.loads(r[0])
            return d if isinstance(d, list) else []
    except Exception:
        pass
    return []


def _recent_names(path=None) -> dict:
    """{nimi: vanus_sekundites} nimedest, mis olid hiljuti kasutusel."""
    out = {}
    for kirje in _read_history(path):
        nimi = str(kirje.get("name", "")).strip()
        vanus = _seconds_since(str(kirje.get("at", "")))
        if not nimi or vanus is None:
            continue
        if vanus < REVERT_GUARD_S:
            # Kui sama nimi esineb mitu korda, loeb VÄRSKEIM.
            if nimi not in out or vanus < out[nimi]:
                out[nimi] = vanus
    return out


def _seconds_since(ts: str):
    """Sekundeid antud ajatemplist. None, kui ei õnnestu lugeda."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo("Europe/Tallinn"))
        return (datetime.now(ZoneInfo("Europe/Tallinn")) - t).total_seconds()
    except Exception:
        return None


def history(path=None) -> list:
    """Nimemuutuste ajalugu, uuemad lõpus. Diagnostikaks."""
    return _read_history(path)


def force_name(name: str, path=None) -> dict:
    """Määrab nime KAITSEST MÖÖDA. Ainult halduri käsitsi kasutuseks.

    Mudel seda ei kutsu – tööriist kasutab set_name'i. See on olemas
    selleks, et inimene saaks valesti kuuldud nime (nt kõnetuvastuse
    'Ai Jaan' vs kirjutatud 'Jaanus') ära parandada ka siis, kui kaitse
    muidu ees seisaks.
    """
    uus = (name or "").strip()
    if not valid_name(uus):
        return {"ok": False, "teade": "See ei näe nime moodi välja."}
    try:
        conn = _conn(path)
        try:
            ensure_schema(conn)
            conn.execute("DELETE FROM settings WHERE key = 'user_name_history'")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "teade": f"Ajaloo nullimine ebaõnnestus: {e}"}
    invalidate_cache()
    return set_name(uus, path)


def fill(text: str, path=None) -> str:
    """Asendab kohahoidja praeguse nimega.

    Taluv ka vanade promptide suhtes, kus kohahoidjat ei ole – siis
    tagastab teksti muutmata.
    """
    if not text or PLACEHOLDER not in text:
        return text or ""
    return text.replace(PLACEHOLDER, get_name(path))


def invalidate_cache():
    """Vahemälu tühjendus – kasulik testides ja pärast välist muutust."""
    _cache["name"] = None

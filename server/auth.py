"""MAYA — autentimine, autoriseerimine ja kasutajate eraldatus.

MIKS SEE FAIL OLEMAS ON
-----------------------
Originaalpaigaldus elas privaatvõrgus (Tailscale), kus serverini
pääses ainult omaniku enda telefon. Seetõttu ei olnud backendil ühtegi
autentimist: kes serverini jõudis, sai kõnesid teha, mälu lugeda ja
omanikule helistada.

Avaliku projekti jaoks see ei sobi. Siin on see auk kinni pandud.

DISAINIOTSUSED (avatud lähtekoodi kogukonnale hallatav)
-------------------------------------------------------
1. **Ei ühtegi uut sõltuvust.** Paroolide räsimine kasutab Pythoni
   standardteegi `hashlib.scrypt`-i, tokenid `secrets`-i. Ükski
   kolmanda osapoole autentimisteek ei ole vajalik, mis tähendab
   vähem ründepinda ja vähem versioonihaldust.

2. **Bearer-tokenid, mitte küpsised.** Klient on Androidi rakendus,
   mitte brauser. Token läheb `Authorization: Bearer <token>` päises
   (ja WebSocketi/SSE puhul query-parameetris, sest WebSocketi
   käepigistus ei luba Androidil kohandatud päist igal teel saata).
   CSRF-i ei teki, sest küpsiseid ei kasutata.

3. **Kasutajate eraldatus on FAILISÜSTEEMI tasemel.** Iga kasutaja
   saab OMA SQLite andmebaasi (`data/users/<id>/reminders.db`).
   See on tugevam garantii kui `WHERE user_id = ?` igas päringus:
   ühe kasutaja päring EI SAA füüsiliselt teise ridu näha, isegi kui
   mõnes 13 000 koodireas on filter puudu. Seda on ka kogukonnal
   lihtne hallata – uus funktsioon ei pea `user_id`-d meeles pidama.

4. **Esimene registreerija saab omanikuks.** Paigaldus on isiklik.
   Esimene konto on `admin`; edasised on tavakasutajad. Registreerimise
   saab täielikult sulgeda (`MAYA_ALLOW_REGISTRATION=0`) või panna
   kutsekoodi taha (`MAYA_INVITE_CODE`).

MIDA SEE EI TEE
---------------
See ei ole OAuth-server ega SSO. Kui vajad Google'i/GitHubi
sisselogimist, pane MAYA pöördproksi taha, mis seda teeb.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from typing import Optional, Tuple

import config

# =====================================================================
# PAROOLIDE RÄSIMINE
# =====================================================================
# scrypt on Pythoni standardteegis ja mäluraske, st GPU-rünnak on kallis.
# Parameetrid: OWASP soovitus interaktiivse sisselogimise jaoks.
SCRYPT_N = 2 ** 14          # tööfaktor
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SOOLA_PIKKUS = 16

# Tokeni eluiga sekundites (vaikimisi 30 päeva). Telefon ei peaks iga
# päev uuesti sisse logima, aga igavest tokenit ka ei taha.
TOKENI_ELUIGA_S = int(config.env("MAYA_TOKEN_TTL_S", str(30 * 24 * 3600)))

# Registreerimise juhtimine
REGISTREERIMINE_LUBATUD = config.env("MAYA_ALLOW_REGISTRATION", "1") != "0"
KUTSEKOOD = config.env("MAYA_INVITE_CODE", "")

MIN_PAROOLI_PIKKUS = 10
KASUTAJANIME_MUSTER = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


def rasi_parool(parool: str, sool: Optional[bytes] = None) -> str:
    """Tagasta `scrypt$<sool_hex>$<rasi_hex>`. Parooli ei salvestata."""
    sool = sool or secrets.token_bytes(SOOLA_PIKKUS)
    dk = hashlib.scrypt(parool.encode("utf-8"), salt=sool, n=SCRYPT_N,
                        r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${sool.hex()}${dk.hex()}"


def kontrolli_parooli(parool: str, salvestatud: str) -> bool:
    """Ajakindel võrdlus. Vigane kirje tagastab False, mitte erindi."""
    try:
        skeem, sool_hex, rasi_hex = salvestatud.split("$", 2)
        if skeem != "scrypt":
            return False
        oodatud = hashlib.scrypt(
            parool.encode("utf-8"), salt=bytes.fromhex(sool_hex),
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
        return hmac.compare_digest(oodatud.hex(), rasi_hex)
    except Exception:
        return False


# =====================================================================
# KASUTAJATE ANDMEBAAS
# =====================================================================
# TÄHTIS: kasutajate register elab ERALDI andmebaasis, mis EI OLE
# ühegi kasutaja oma. Nii ei saa kasutaja oma andmebaasi kaudu kunagi
# teiste kontosid ega tokeneid näha.
def kasutajate_db_tee() -> str:
    return str(config.ANDMED / "users.db")


def _yhendus() -> sqlite3.Connection:
    tee = kasutajate_db_tee()
    os.makedirs(os.path.dirname(tee), exist_ok=True)
    conn = sqlite3.connect(tee, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    """Loo kasutajate ja tokenite tabelid, kui puuduvad."""
    with _yhendus() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name  TEXT NOT NULL DEFAULT '',
            is_admin      INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            label      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(user_id);
        CREATE TABLE IF NOT EXISTS login_attempts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            at         INTEGER NOT NULL,
            ok         INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attempts ON login_attempts(username, at);
        """)


# =====================================================================
# KASUTAJAD
# =====================================================================
class AuthViga(Exception):
    """Autentimise viga. Sõnum on kasutajale näitamiseks ohutu."""

    def __init__(self, sonum: str, kood: int = 401):
        super().__init__(sonum)
        self.sonum = sonum
        self.kood = kood


def kasutajaid_kokku() -> int:
    with _yhendus() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def valideeri_kasutajanimi(nimi: str) -> str:
    nimi = (nimi or "").strip()
    if not KASUTAJANIME_MUSTER.match(nimi):
        raise AuthViga(
            "Kasutajanimi tohib sisaldada 3-32 tähte, numbrit, "
            "alakriipsu, punkti või sidekriipsu.", 400)
    return nimi


def valideeri_parool(parool: str) -> str:
    if not parool or len(parool) < MIN_PAROOLI_PIKKUS:
        raise AuthViga(
            f"Parool peab olema vähemalt {MIN_PAROOLI_PIKKUS} märki.", 400)
    if len(parool) > 1024:
        raise AuthViga("Parool on liiga pikk.", 400)
    return parool


def loo_kasutaja(kasutajanimi: str, parool: str,
                 display_name: str = "", kutsekood: str = "",
                 kohusta_registreerimine: bool = True) -> dict:
    """Registreeri uus kasutaja.

    ESIMENE kasutaja saab automaatselt admin-õigused – paigaldus on
    isiklik ja keegi peab billing-otspunktid kätte saama.
    """
    ensure_schema()
    kasutajanimi = valideeri_kasutajanimi(kasutajanimi)
    valideeri_parool(parool)

    esimene = kasutajaid_kokku() == 0
    if kohusta_registreerimine and not esimene:
        if not REGISTREERIMINE_LUBATUD:
            raise AuthViga("Registreerimine on selles paigalduses "
                           "suletud.", 403)
        if KUTSEKOOD and not hmac.compare_digest(kutsekood or "", KUTSEKOOD):
            raise AuthViga("Vigane kutsekood.", 403)

    try:
        with _yhendus() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, "
                "is_admin) VALUES (?, ?, ?, ?)",
                (kasutajanimi, rasi_parool(parool),
                 (display_name or kasutajanimi)[:64], 1 if esimene else 0))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise AuthViga("See kasutajanimi on juba võetud.", 409)

    # Loo kasutaja oma andmekaust ja TÄHTIS: ka tühja andmebaasi skeem.
    config.kasutaja_kaust(uid).mkdir(parents=True, exist_ok=True)
    taga_kasutaja_db(uid)
    return {"id": uid, "username": kasutajanimi, "is_admin": esimene}


def taga_kasutaja_db(uid: int) -> bool:
    """Loo kasutaja andmebaasi skeem, kui see puudub.

    Kutsutakse konto loomisel ja igal autentimisel (odav
    `os.path.exists` kontroll). Nii ei jää uus kasutaja ilma tabeleid
    ja vana kasutaja ei kaota andmeid.

    Skeem tuleb moodulite ENDA init-funktsioonidest – sama kood, mis
    `init_db.py` kasutab, et skeem ei saaks lahku joosta.
    """
    kaust = config.kasutaja_kaust(uid)
    kaust.mkdir(parents=True, exist_ok=True)
    tee = kaust / "reminders.db"
    if tee.exists():
        return False
    tok = config.sea_aktiivne_kasutaja(uid)
    try:
        import listen_direct
        import memory_engine
        import memory_fts
        import user_profile
        listen_direct.init_db()
        memory_engine.init_memory_db()
        with config.connect(timeout=10) as conn:
            memory_fts.ensure_schema(conn)
        with config.connect(timeout=10) as conn:
            user_profile.ensure_schema(conn)
        # Veerud, mis tootmises lisandusid ALTER-iga (vt init_db.py).
        import init_db
        init_db.lisa_puuduvad_veerud()
        return True
    except Exception as e:
        print(f"[auth] HOIATUS: kasutaja #{uid} andmebaasi loomine "
              f"ebaõnnestus: {type(e).__name__}: {e}", flush=True)
        return False
    finally:
        config.taasta_aktiivne_kasutaja(tok)


def leia_kasutaja(uid: int) -> Optional[dict]:
    with _yhendus() as conn:
        r = conn.execute(
            "SELECT id, username, display_name, is_admin, is_active "
            "FROM users WHERE id = ?", (uid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "username": r[1], "display_name": r[2],
            "is_admin": bool(r[3]), "is_active": bool(r[4])}


# =====================================================================
# KIIRUSPIIRANG (sisselogimise jõuga murdmise vastu)
# =====================================================================
LOGIN_AKEN_S = 300          # 5 minutit
LOGIN_MAX_KATSET = 10       # ühe kasutajanime kohta akna sees


def _koristada_katsed(conn) -> None:
    conn.execute("DELETE FROM login_attempts WHERE at < ?",
                 (int(time.time()) - 24 * 3600,))


def kontrolli_kiiruspiirangut(kasutajanimi: str) -> None:
    nuud = int(time.time())
    with _yhendus() as conn:
        _koristada_katsed(conn)
        n = conn.execute(
            "SELECT COUNT(*) FROM login_attempts "
            "WHERE username = ? AND ok = 0 AND at > ?",
            (kasutajanimi, nuud - LOGIN_AKEN_S)).fetchone()[0]
    if n >= LOGIN_MAX_KATSET:
        raise AuthViga(
            "Liiga palju ebaõnnestunud katseid. Proovi 5 minuti pärast.",
            429)


def _margi_katse(kasutajanimi: str, ok: bool) -> None:
    with _yhendus() as conn:
        conn.execute(
            "INSERT INTO login_attempts (username, at, ok) VALUES (?, ?, ?)",
            (kasutajanimi, int(time.time()), 1 if ok else 0))


# =====================================================================
# TOKENID
# =====================================================================
# Andmebaasis hoitakse AINULT tokeni SHA-256 räsi. Kui andmebaas
# lekib, ei saa räsist tokenit tagasi arvutada.
def _tokeni_rasi(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def logi_sisse(kasutajanimi: str, parool: str,
               label: str = "") -> Tuple[str, dict]:
    """Tagasta (token, kasutaja). Vale parool -> AuthViga 401."""
    ensure_schema()
    kasutajanimi = (kasutajanimi or "").strip()
    kontrolli_kiiruspiirangut(kasutajanimi)

    with _yhendus() as conn:
        r = conn.execute(
            "SELECT id, password_hash, is_active FROM users WHERE username = ?",
            (kasutajanimi,)).fetchone()

    # Ajastusrünnaku vastu: teeme scrypt-i ka siis, kui kasutajat pole.
    salvestatud = r[1] if r else rasi_parool(secrets.token_hex(8))
    sobib = kontrolli_parooli(parool or "", salvestatud)

    if not r or not sobib:
        _margi_katse(kasutajanimi, False)
        raise AuthViga("Vale kasutajanimi või parool.", 401)
    if not r[2]:
        _margi_katse(kasutajanimi, False)
        raise AuthViga("See konto on peatatud.", 403)

    _margi_katse(kasutajanimi, True)
    uid = r[0]
    token = secrets.token_urlsafe(32)
    nuud = int(time.time())
    with _yhendus() as conn:
        conn.execute(
            "INSERT INTO tokens (token_hash, user_id, created_at, "
            "expires_at, label) VALUES (?, ?, ?, ?, ?)",
            (_tokeni_rasi(token), uid, nuud, nuud + TOKENI_ELUIGA_S,
             (label or "")[:64]))
        conn.execute("UPDATE users SET last_login_at = datetime('now') "
                     "WHERE id = ?", (uid,))
    return token, leia_kasutaja(uid)


def logi_valja(token: str) -> bool:
    with _yhendus() as conn:
        cur = conn.execute("DELETE FROM tokens WHERE token_hash = ?",
                           (_tokeni_rasi(token),))
    return cur.rowcount > 0


def logi_valja_koik(uid: int) -> int:
    with _yhendus() as conn:
        cur = conn.execute("DELETE FROM tokens WHERE user_id = ?", (uid,))
    return cur.rowcount


def kasutaja_tokenist(token: Optional[str]) -> Optional[dict]:
    """Tagasta kasutaja või None. Aegunud token kustutatakse."""
    if not token or len(token) > 512:
        return None
    try:
        ensure_schema()
        nuud = int(time.time())
        with _yhendus() as conn:
            r = conn.execute(
                "SELECT user_id, expires_at FROM tokens WHERE token_hash = ?",
                (_tokeni_rasi(token),)).fetchone()
            if not r:
                return None
            if r[1] < nuud:
                conn.execute("DELETE FROM tokens WHERE token_hash = ?",
                             (_tokeni_rasi(token),))
                return None
        k = leia_kasutaja(r[0])
        if k and k["is_active"]:
            # Odav kaitse: kui kasutaja andmebaas on kustunud või
            # konto loodi enne skeemiloogika lisamist, loo see nüüd.
            taga_kasutaja_db(k["id"])
            return k
        return None
    except Exception:
        return None


# =====================================================================
# TOKENI LEIDMINE PÄRINGUST
# =====================================================================
def token_paringust(authorization: Optional[str] = None,
                    x_maya_token: Optional[str] = None,
                    query_token: Optional[str] = None) -> Optional[str]:
    """Token võib tulla kolmel viisil.

    1. `Authorization: Bearer <token>` – eelistatud, HTTP API jaoks.
    2. `X-Maya-Token: <token>` – lihtsam mõnel Androidi teel.
    3. `?token=<token>` – AINULT WebSocketi ja SSE jaoks, kus Androidi
       klient ei saa kõigil teedel kohandatud päist lisada.

    Variant 3 jõuab serveri logidesse, seega seda kasutatakse ainult
    seal, kus muud võimalust ei ole. Vt docs/TURVALISUS.md.
    """
    if authorization:
        osad = authorization.split(None, 1)
        if len(osad) == 2 and osad[0].lower() == "bearer":
            return osad[1].strip()
    if x_maya_token:
        return x_maya_token.strip()
    if query_token:
        return query_token.strip()
    return None


# =====================================================================
# ÜLDINE KIIRUSPIIRANG API-le
# =====================================================================
class Kiiruspiirang:
    """Lihtne libisev aken mälus.

    Tahtlikult mälus ja ilma Redist: üks paigaldus teenindab üksikuid
    kasutajaid ja lisasõltuvus ei ole seda väärt. Protsessi
    taaskäivitamine nullib loenduri – see on teadlik kompromiss.
    """

    def __init__(self, max_paringut: int = 120, aken_s: int = 60):
        self.max = max_paringut
        self.aken = aken_s
        self._kirjed: dict[str, list] = {}

    def luba(self, voti: str) -> bool:
        nuud = time.monotonic()
        jarjend = self._kirjed.setdefault(voti, [])
        piir = nuud - self.aken
        while jarjend and jarjend[0] < piir:
            jarjend.pop(0)
        if len(jarjend) >= self.max:
            return False
        jarjend.append(nuud)
        # hoia sõnastik väikesena
        if len(self._kirjed) > 10000:
            for k in list(self._kirjed)[:5000]:
                if not self._kirjed[k]:
                    del self._kirjed[k]
        return True


API_PIIRANG = Kiiruspiirang(
    max_paringut=int(config.env("MAYA_RATE_LIMIT", "120")), aken_s=60)
LOGIN_PIIRANG = Kiiruspiirang(
    max_paringut=int(config.env("MAYA_LOGIN_RATE_LIMIT", "20")), aken_s=60)


# =====================================================================
# SISENDI VALIDEERIMINE
# =====================================================================
def puhasta_tekst(v: Optional[str], max_pikkus: int = 4000,
                 nimi: str = "tekst") -> str:
    """Lõika pikkus ja eemalda juhtmärgid. Ei muuda sisu muidu."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise AuthViga(f"Väli '{nimi}' peab olema tekst.", 400)
    if len(v) > max_pikkus:
        raise AuthViga(
            f"Väli '{nimi}' on liiga pikk (max {max_pikkus} märki).", 400)
    # Eemalda NUL ja muud juhtmärgid peale reavahetuse ja tabi.
    return "".join(c for c in v if c == "\n" or c == "\t" or ord(c) >= 32)


def valideeri_karakter(pid: Optional[str]) -> str:
    """Karakteri ID peab olema registris olemas. Väldib tee-rünnakuid."""
    import persona_registry
    pid = (pid or "").strip().lower()
    if not pid:
        return persona_registry.DEFAULT_PERSONA_ID
    if pid not in persona_registry.PERSONAS and \
            pid not in persona_registry.ALIASES:
        raise AuthViga(f"Tundmatu karakter: {pid[:32]}", 400)
    return pid


def valideeri_taisarv(v, min_v: int, max_v: int, nimi: str) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise AuthViga(f"Väli '{nimi}' peab olema täisarv.", 400)
    if not (min_v <= n <= max_v):
        raise AuthViga(
            f"Väli '{nimi}' peab olema vahemikus {min_v}..{max_v}.", 400)
    return n

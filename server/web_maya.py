import maya_brain
import config  # MAYA seadistus (vt server/config.py)

def get_calendar_reminders_context():
    try:
        import sqlite3, datetime
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("""
            SELECT id, trigger_time, reminder_text, custom_speech, is_done, repeat_type, notify_type 
            FROM reminders 
            ORDER BY trigger_time ASC
        """)
        rows = c.fetchall()
        conn.close()

        if not rows:
            return "Kasutaja kalendris/meeldetuletustes pole hetkel ühtegi kirjet."

        lines = []
        for r in rows:
            rem_id, trig_time, text, speech, is_done, rep, ntype = r
            status = "TEHTUD" if is_done else "AKTIIVNE / OOTEL"
            lines.append(f"- ID {rem_id} | Aeg: {trig_time} | Teema: {text} | Kordus: {rep} | Tüüp: {ntype} | Olek: {status}")

        return "\n".join(lines)
    except Exception as e:
        return f"Viga kalendri lugemisel: {e}"

from fastapi.responses import JSONResponse, HTMLResponse
from starlette.requests import Request

def clean_reminder_for_speech(raw_text: str) -> str:
    t = raw_text.strip()
    if not t:
        return "on aeg oma toimetustega jätkata."
    # Eemaldame liigsed jutumärgid ja punkti lõpust ajutiselt
    t = t.rstrip('.!?')
    
    # Eemaldame käsklused lause algusest
    prefixes = [
        r'^[üÜ]tle[,\s]+et\s+',
        r'^[üÜ]tle\s+mulle[,\s]+et\s+',
        r'^[tT]uleta[,\s]+et\s+',
        r'^[tT]uleta\s+mulle\s+meelde[,\s]+et\s+',
        r'^[tT]uleta\s+meelde[,\s]+et\s+',
        r'^[pP]alu[,\s]+et\s+',
    ]
    for p in prefixes:
        t = re.sub(p, '', t, flags=re.IGNORECASE).strip()
    
    # Kui pärast puhastamist algab "ma " (nt "ma magama läheksin"), pöörame selle "sa "-ks
    if re.match(r'^ma\s+', t, flags=re.IGNORECASE):
        t = re.sub(r'^ma\s+', 'sa ', t, flags=re.IGNORECASE)
    
    if not t.endswith('.'):
        t += '.'
    return t

import features_pack

import urllib.parse
import email_tool
def requests_quote(text):
    return urllib.parse.quote(text or "", safe="")

from fastapi import Request, Header, Form
import os
import io
import asyncio
import datetime
import tempfile
import subprocess
import re
from zoneinfo import ZoneInfo
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from google.genai import types

import listen_direct as core

app = FastAPI(
    title="MAYA",
    description="Eestikeelne häälassistent. Kõik /api otspunktid "
                "nõuavad autentimist – vt docs/TURVALISUS.md.",
)

# =====================================================================
# AUTENTIMINE JA AUTORISEERIMINE
# =====================================================================
# MIKS: originaalpaigaldus elas privaatvõrgus ja backendil EI OLNUD
# autentimist. Avalikus versioonis on see auk kinni. Vt server/auth.py.
import auth as _auth
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def _kliendi_voti(request: Request) -> str:
    """Kiiruspiirangu võti: kasutaja ID, muidu IP."""
    uid = config.aktiivne_kasutaja()
    if uid is not None:
        return f"u{uid}"
    try:
        return f"ip{request.client.host}"
    except Exception:
        return "ip?"


async def noua_kasutaja(
    request: Request,
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
    x_maya_token: str = Header(None),
) -> dict:
    """FastAPI sõltuvus: KOHUSTUSLIK autentimine.

    Seab ühtlasi aktiivse kasutaja, nii et `config.connect()` avab
    ÕIGE kasutaja andmebaasi. Konteksti taastamine toimub
    `_taasta_kontekst` middleware'is päringu lõpus.
    """
    if not _auth.API_PIIRANG.luba(_kliendi_voti(request)):
        raise HTTPException(429, "Liiga palju päringuid. Oota hetk.")
    token = _auth.token_paringust(
        authorization=(f"Bearer {cred.credentials}" if cred else None),
        x_maya_token=x_maya_token,
        query_token=request.query_params.get("token"),
    )
    kasutaja = _auth.kasutaja_tokenist(token)
    if not kasutaja:
        raise HTTPException(
            401, "Autentimine nurjus. Logi sisse POST /api/auth/login.",
            headers={"WWW-Authenticate": "Bearer"})
    request.state.maya_kasutaja = kasutaja
    request.state.maya_ctx = config.sea_aktiivne_kasutaja(kasutaja["id"])
    return kasutaja


async def noua_admin(kasutaja: dict = Depends(noua_kasutaja)) -> dict:
    """Ainult admin: arveldus, haldus, diagnostika."""
    if not kasutaja.get("is_admin"):
        raise HTTPException(403, "See otspunkt on ainult administraatorile.")
    return kasutaja


@app.middleware("http")
async def _taasta_kontekst(request: Request, call_next):
    """Vabasta kasutajakontekst päringu lõpus.

    `contextvars` on päringu-põhine, aga me taastame selle siiski
    käsitsi, et taustaülesanded ei päriks kogemata eelmise päringu
    kasutajat.
    """
    vastus = await call_next(request)
    tok = getattr(request.state, "maya_ctx", None)
    if tok is not None:
        config.taasta_aktiivne_kasutaja(tok)
    return vastus


@app.post("/api/auth/register")
async def auth_register(request: Request):
    """Loo konto. ESIMENE konto saab admin-õigused."""
    if not _auth.LOGIN_PIIRANG.luba(_kliendi_voti(request)):
        raise HTTPException(429, "Liiga palju katseid. Oota hetk.")
    try:
        keha = await request.json()
    except Exception:
        raise HTTPException(400, "Oodati JSON-keha.")
    try:
        k = _auth.loo_kasutaja(
            kasutajanimi=_auth.puhasta_tekst(keha.get("username"), 32,
                                             "username"),
            parool=keha.get("password") or "",
            display_name=_auth.puhasta_tekst(keha.get("display_name"), 64,
                                             "display_name"),
            kutsekood=_auth.puhasta_tekst(keha.get("invite_code"), 128,
                                          "invite_code"),
        )
        token, kasutaja = _auth.logi_sisse(
            k["username"], keha.get("password") or "",
            label=_auth.puhasta_tekst(keha.get("device"), 64, "device"))
    except _auth.AuthViga as e:
        raise HTTPException(e.kood, e.sonum)
    return {"token": token, "user": kasutaja,
            "expires_in_s": _auth.TOKENI_ELUIGA_S}


@app.post("/api/auth/login")
async def auth_login(request: Request):
    if not _auth.LOGIN_PIIRANG.luba(_kliendi_voti(request)):
        raise HTTPException(429, "Liiga palju katseid. Oota hetk.")
    try:
        keha = await request.json()
    except Exception:
        raise HTTPException(400, "Oodati JSON-keha.")
    try:
        token, kasutaja = _auth.logi_sisse(
            _auth.puhasta_tekst(keha.get("username"), 32, "username"),
            keha.get("password") or "",
            label=_auth.puhasta_tekst(keha.get("device"), 64, "device"))
    except _auth.AuthViga as e:
        raise HTTPException(e.kood, e.sonum)
    return {"token": token, "user": kasutaja,
            "expires_in_s": _auth.TOKENI_ELUIGA_S}


@app.post("/api/auth/logout")
async def auth_logout(request: Request,
                      cred: HTTPAuthorizationCredentials = Depends(_bearer),
                      x_maya_token: str = Header(None),
                      kasutaja: dict = Depends(noua_kasutaja)):
    token = _auth.token_paringust(
        authorization=(f"Bearer {cred.credentials}" if cred else None),
        x_maya_token=x_maya_token,
        query_token=request.query_params.get("token"))
    _auth.logi_valja(token or "")
    return {"status": "ok"}


@app.get("/api/auth/me")
async def auth_me(kasutaja: dict = Depends(noua_kasutaja)):
    return {"user": kasutaja,
            "db": config.db_tee().replace(str(config.ANDMED), "<andmed>")}


@app.post("/api/auth/ws_ticket")
async def auth_ws_ticket(kasutaja: dict = Depends(noua_kasutaja)):
    """Anna ÜHEKORDNE pilet WebSocketi avamiseks.

    Klient kutsub seda vahetult enne `new WebSocket(...)` ja paneb
    pileti URL-i. Nii ei jõua pikaealine token kunagi URL-i ega
    pöördproksi juurdepääsulogidesse.
    """
    pilet, eluiga = _auth.loo_ws_pilet(kasutaja["id"])
    return {"ticket": pilet, "expires_in_s": eluiga}


@app.get("/api/auth/status")
async def auth_status():
    """AVALIK: ütleb, kas paigaldus on juba seadistatud.

    Androidi rakendus küsib seda enne sisselogimisekraani näitamist.
    EI AVALDA kasutajanimesid ega muud infot.
    """
    try:
        _auth.ensure_schema()
        n = _auth.kasutajaid_kokku()
    except Exception:
        n = 0
    return {"seadistatud": n > 0,
            "registreerimine_lubatud": _auth.REGISTREERIMINE_LUBATUD or n == 0,
            "kutsekood_noutud": bool(_auth.KUTSEKOOD)}
import memory_engine
from live_maya_ws import live_router, set_pending_call_prompt
app.include_router(live_router)

import asyncio
from fastapi.responses import StreamingResponse

# =====================================================================
# KÕNESÜNDMUSED — KASUTAJAPÕHISED JÄRJEKORRAD
# =====================================================================
# TURVAPARANDUS: varem oli ÜKS globaalne järjekord. See tähendas, et
# igaüks, kes serverini jõudis, sai käivitada kõne IGA ühendatud
# telefonile, ja iga telefon nägi KÕIKI kõnesündmusi. Nüüd on igal
# kasutajal oma järjekord ja SSE-vool nõuab autentimist.
# MITU SEADET ÜHE KONTOGA: iga SSE-ühendus saab OMA järjekorra ja
# sündmus kopeeritakse KÕIGILE selle kasutaja ühendustele.
#
# MÕÕDETUD LEID (11.11.2026): üks `asyncio.Queue` kasutaja kohta ei
# tööta mitme telefoniga – `Queue.get()` annab iga elemendi AINULT
# ÜHELE tarbijale, nii et kaks telefoni sama kontoga tähendas, et
# heliseb juhuslikult üks neist. Kasutaja ootab, et mõlemad telefonid
# heliseksid; seega publitseerimine on nüüd fan-out.
_kone_tellijad: dict = {}      # uid -> list[asyncio.Queue]


def kone_telli(uid: int) -> asyncio.Queue:
    """Registreeri UUS SSE-ühendus. Iga ühendus saab oma järjekorra."""
    q = asyncio.Queue(maxsize=50)
    _kone_tellijad.setdefault(int(uid), []).append(q)
    return q


def kone_lopeta(uid: int, q: asyncio.Queue) -> None:
    """Eemalda ühendus, kui telefon lahkub."""
    read = _kone_tellijad.get(int(uid))
    if not read:
        return
    try:
        read.remove(q)
    except ValueError:
        pass
    if not read:
        _kone_tellijad.pop(int(uid), None)


def kone_tellijaid(uid: int) -> int:
    """Mitu seadet on selle kasutaja kõneteateid ootamas."""
    return len(_kone_tellijad.get(int(uid), []))


async def kone_publitseeri(uid: int, sisu) -> int:
    """Saada sündmus KÕIGILE selle kasutaja seadmetele.

    Tagastab, mitmele seadmele jõudis. 0 tähendab, et ükski telefon ei
    ole ühendatud – siis kõnet ei tule ja seda on logist näha.
    """
    read = list(_kone_tellijad.get(int(uid), []))
    for q in read:
        if q.full():
            try:
                q.get_nowait()        # viska vanim ära, hoia värskeim
            except Exception:
                pass
        try:
            q.put_nowait(sisu)
        except Exception:
            pass
    return len(read)


# ÜHILDUVUS vanade kutsujatega (`call_event_queue.put(...)`).
class _KoneJarjekordProksi:
    """Suunab AKTIIVSE kasutaja kõigile seadmetele.

    Kui kasutajat ei ole seatud (taustaülesanne, nt meeldetuletuse
    taimer, mis käivitub enne päringut), kasutame omaniku (id 1)
    kontot – isiklikus paigalduses on see õige vaikeväärtus.
    """

    async def put(self, item):
        uid = config.aktiivne_kasutaja()
        n = await kone_publitseeri(uid if uid is not None else 1, item)
        if n == 0:
            print(f"--> [KÕNE]: ükski seade ei ole ühendatud "
                  f"(kasutaja #{uid if uid is not None else 1}) – "
                  f"kõneteade jäi kohale toimetamata", flush=True)
        return n


call_event_queue = _KoneJarjekordProksi()


# ÜHILDUVUS testidega: tagastab esimese tellija järjekorra või loob
# uue. Uus kood peaks kasutama `kone_telli` / `kone_publitseeri`.
def kone_jarjekord(uid: int) -> asyncio.Queue:
    read = _kone_tellijad.get(int(uid))
    if read:
        return read[0]
    return kone_telli(uid)


@app.get("/api/call_events")
async def call_events(request: Request,
                      kasutaja: dict = Depends(noua_kasutaja)):
    """SSE vool, mille kaudu telefon saab teada sissetulevast kõnest.

    AUTENTIMINE: token tuleb `Authorization: Bearer` päises VÕI
    `?token=` parameetris (Androidi SSE-klient ei saa alati päist
    lisada). Kasutaja näeb AINULT oma järjekorda.
    """
    uid = kasutaja["id"]
    # IGA ÜHENDUS saab oma järjekorra – nii helisevad mitu telefoni
    # sama kontoga kõik korraga.
    q = kone_telli(uid)
    print(f"--> [KÕNE]: seade ühendus kõneteadetele "
          f"(kasutaja #{uid}, seadmeid nüüd {kone_tellijaid(uid)})",
          flush=True)

    async def event_generator():
        # Kontekst taastub päringu lõpus middleware'is; SSE elab
        # kaua, seega seame kasutaja ka siia.
        tok = config.sea_aktiivne_kasutaja(uid)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            kone_lopeta(uid, q)
            config.taasta_aktiivne_kasutaja(tok)
            print(f"--> [KÕNE]: seade lahkus "
                  f"(kasutaja #{uid}, seadmeid alles "
                  f"{kone_tellijaid(uid)})", flush=True)

    return StreamingResponse(event_generator(),
                             media_type="text/event-stream")


async def background_learn(user_text: str, reply_text: str):
    """Analüüsib vestlust taustal ja salvestab püsivad faktid ning harjumused mällu."""
    try:
        clean_text = user_text.strip()
        # Kui lause on liiga lühike või lihtsalt viisakus/tervitus, ignoreeri kohe
        if len(clean_text) < 10:
            return

        learn_prompt = (
            "Sa oled range faktikoguja. Sinu ainus ülesanne on eraldada KASUTAJA ENDA ÖELDUD LAUSEST "
            "püsivad ja kindlad faktid tema kohta (nt elukoht, tööriistad, masinad, konkreetsed projektid, püsivad harjumused).\n\n"
            "RANGED REEGLID:\n"
            "1. ÄRA KUNAGI võta ega tuleta fakte Maya enda vastusest. Maya vastus võib sisaldada hallutsinatsioone või küsimusi – ignoreeri neid täielikult!\n"
            "2. Analüüsi AINULT kasutaja lauset. Fakt peab tuginema otseselt kasutaja selgele väitele.\n"
            "3. Kui kasutaja jutt on arusaamatu kõnetuvastuse moonutus, poolik lause või suvaline sõnakõlks, ÄRA salvesta midagi.\n"
            "4. ÄRA salvesta hetketegevusi, viisakusväljendeid, tervitusi, ilmateateid ega üldiseid küsimusi.\n"
            "5. ÄRA muuda ega salvesta kasutaja nime, välja arvatud juhul, kui kasutaja ütleb otsesõnu: 'Minu nimi on...'\n\n"
            f"KASUTAJA LAUSE: '{clean_text}'\n\n"
            "Väljasta AINULT kehtiv JSON ilma koodiplokkideta:\n"
            '{"has_facts": true, "facts": ["Kasutaja omab/teeb..."]}\n'
            'Kui kindlaid fakte ei leidunud, vasta: {"has_facts": false, "facts": []}'
        )

        data = await asyncio.to_thread(core.ask_gemini_json, learn_prompt)
        if data and data.get("has_facts") and data.get("facts"):
            facts = [str(f).strip() for f in data["facts"] if str(f).strip()]
            if facts and hasattr(core, "save_memory_items"):
                core.save_memory_items(facts)
                print(f"--> [MAYA ÕPPIS]: {facts}", flush=True)
    except Exception as e:
        print(f"Taustaõppimise viga: {e}", flush=True)


@app.get("/api/briefing")
async def get_briefing(kasutaja: dict = Depends(noua_kasutaja)):
    """Tagastab hommikubriifingu seade (kas sees ja mis kell)."""
    def _read():
        import sqlite3
        conn = config.connect(timeout=10)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()]
            sel = "trigger_time, persona" if "persona" in cols else "trigger_time, '' AS persona"
            row = conn.execute(
                f"SELECT {sel} FROM reminders "
                "WHERE notify_type = 'briefing' AND is_done = 0 LIMIT 1"
            ).fetchone()
        except Exception:
            row = None
        conn.close()
        return row
    row = await asyncio.to_thread(_read)
    if not row:
        return {"enabled": False, "time": "08:00", "persona": "asjalik"}
    return {"enabled": True, "time": (row[0] or "")[11:16] or "08:00", "persona": row[1] or "asjalik"}


@app.post("/api/briefing")
async def set_briefing(time: str = "08:00", persona: str = "asjalik", enabled: bool = True, kasutaja: dict = Depends(noua_kasutaja)):
    """Lülitab hommikubriifingu sisse/välja.

    Briifing on tavaline IGAPÄEVANE meeldetuletus, mille notify_type='briefing'.
    Valvur tunneb selle ära ja koostab sisu helistamise hetkel (värske ilm jne).
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z

    def _write():
        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        # vana briifing alati maha, et neid ei koguneks
        c.execute("DELETE FROM reminders WHERE notify_type = 'briefing'")
        created = None
        if enabled:
            try:
                hh, mm = [int(x) for x in time.split(":")[:2]]
            except Exception:
                hh, mm = 8, 0
            now = _dt.datetime.now(_Z("Europe/Tallinn"))
            first = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if first <= now:
                first += _dt.timedelta(days=1)
            created = first.strftime("%Y-%m-%d %H:%M")
            cols = [r[1] for r in c.execute("PRAGMA table_info(reminders)").fetchall()]
            if "persona" in cols:
                c.execute(
                    "INSERT INTO reminders (trigger_time, reminder_text, custom_speech, is_done, "
                    "repeat_type, notify_type, persona) VALUES (?, ?, '', 0, 'daily', 'briefing', ?)",
                    (created, "Hommikubriifing", (persona or "asjalik").strip().lower()),
                )
            else:
                c.execute(
                    "INSERT INTO reminders (trigger_time, reminder_text, custom_speech, is_done, "
                    "repeat_type, notify_type) VALUES (?, ?, '', 0, 'daily', 'briefing')",
                    (created, "Hommikubriifing"),
                )
        conn.commit(); conn.close()
        return created

    created = await asyncio.to_thread(_write)
    print(f"--> [BRIIFING]: {'seatud ' + str(created) if created else 'välja lülitatud'}", flush=True)
    return {"status": "ok", "enabled": bool(enabled), "next": created, "persona": persona}


@app.get("/api/briefing/preview")
async def briefing_preview(kasutaja: dict = Depends(noua_kasutaja)):
    """Näitab, mida briifing praegu sisaldaks (ei helista)."""
    return {"text": await asyncio.to_thread(build_morning_briefing)}


@app.post("/api/trigger_call")
async def trigger_call(reason: str = "Tähelepanu! Mayal on sulle teade.", kasutaja: dict = Depends(noua_kasutaja)):
    await call_event_queue.put(reason)
    return {"status": "ok", "message": "Kõne päästik edastatud telefoni"}


# WP3 (sprint 2026-11-06): karakterid tulevad kanoonilisest registrist.
# Varem oli siin eraldi, LÜHEM promptikomplekt (nt "asjalik" 128 tähemärki
# vs häälerajal 702), mistõttu sama karakter käitus tekstivestluses ja kõnes
# erinevalt. Register hoiab mõlemat varianti; tekstirada kasutab endiselt
# TÄPSELT samu tekstiprompte nagu varem – see on teadlik otsus, et refaktooring
# ei muudaks käitumist. Variantide ühendamine on tootejuhi, mitte refaktoori otsus.
import persona_registry
import user_profile

PERSONA_PROMPTS = {
    p.id: p.prompt_text
    for p in persona_registry.get_all_personas()
    if p.prompt_text is not None
}


# CORS: `allow_origins=["*"]` KOOS `allow_credentials=True`-ga on
# vigane kombinatsioon (brauserid keelavad selle) ja ühtlasi liiga
# lahti. Androidi WebView ei vaja CORS-i üldse; lubatud lähtekohad
# tulevad nüüd seadistusest (MAYA_CORS_ORIGINS, komaga eraldatud).
_cors = [x.strip() for x in (config.env("MAYA_CORS_ORIGINS", "") or "").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*", "X-Maya-Text", "X-User-Text", "X-Voice-Used", "X-Voice-Fallback", "X-Voice-Fallback-Reason"],
)

HTML_PAGE = """<!DOCTYPE html>
<html lang="et">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Maya Ultra Live</title>
    <meta name="theme-color" content="#090d16">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: #090d16; color: #f8fafc; height: 100vh; display: flex; flex-direction: column; justify-content: space-between; align-items: center; padding: 24px 20px; overflow: hidden; }
        .header { text-align: center; }
        .header h1 { font-size: 26px; font-weight: 700; color: #38bdf8; letter-spacing: -0.5px; }
        .header p { font-size: 13px; color: #64748b; margin-top: 4px; }
        
        .chat-box { flex: 1; width: 100%; max-width: 480px; display: flex; flex-direction: column; justify-content: center; gap: 14px; margin: 20px 0; }
        .bubble { padding: 14px 18px; border-radius: 18px; font-size: 15px; line-height: 1.45; max-width: 90%; transition: all 0.2s ease; }
        .user-bubble { background: #1e293b; color: #cbd5e1; align-self: flex-end; border-bottom-right-radius: 4px; }
        .maya-bubble { background: #0369a1; color: #f0f9ff; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 4px 15px rgba(2, 132, 199, 0.25); }
        
        .visualizer-container {
            width: 100%; max-width: 300px; height: 60px; display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 10px;
        }
        .bar { width: 6px; height: 8px; background: #38bdf8; border-radius: 3px; transition: height 0.08s ease; opacity: 0.3; }
        .bar.active { opacity: 1; background: #38bdf8; box-shadow: 0 0 10px #38bdf8; }

        .controls { display: flex; flex-direction: column; align-items: center; width: 100%; gap: 15px; }
        .status { font-size: 14px; color: #94a3b8; height: 22px; font-weight: 500; }
        
        .btn-group { display: flex; align-items: center; gap: 20px; }
        .btn-circle {
            width: 86px; height: 86px; border-radius: 50%;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            border: none; outline: none; cursor: pointer;
            display: flex; justify-content: center; align-items: center;
            box-shadow: 0 0 25px rgba(14, 165, 233, 0.35);
            transition: all 0.2s ease;
            -webkit-tap-highlight-color: transparent;
        }
        .btn-circle.listening {
            background: linear-gradient(135deg, #10b981, #059669) !important;
            box-shadow: 0 0 35px rgba(16, 185, 129, 0.5) !important;
            transform: scale(1.05);
        }
        .btn-circle.speaking {
            background: linear-gradient(135deg, #8b5cf6, #6d28d9) !important;
            box-shadow: 0 0 35px rgba(139, 92, 246, 0.5) !important;
            animation: pulse 1.5s infinite ease-in-out;
        }
        .btn-circle svg { width: 36px; height: 36px; fill: #ffffff; }

        .btn-stop {
            width: 50px; height: 50px; border-radius: 50%; background: #ef4444; border: none; cursor: pointer;
            display: flex; justify-content: center; align-items: center; box-shadow: 0 0 15px rgba(239, 68, 68, 0.4);
            transition: transform 0.15s ease;
        }
        .btn-stop:active { transform: scale(0.9); }
        .btn-stop svg { width: 22px; height: 22px; fill: #ffffff; }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.08); }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Maya Ultra Live</h1>
        <p>Voogesitus • Kiirendatud Aoede</p>
    </div>

    <div class="chat-box" id="chatBox">
        <div class="bubble maya-bubble" id="mayaText">Vajuta nuppu ja räägime vabalt.</div>
        <div class="bubble user-bubble" id="userText" style="display: none;"></div>
    </div>

    <div class="visualizer-container" id="visualizer">
        <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
        <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
        <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
    </div>

    <div class="controls">
        <div class="status" id="statusText">Ootel</div>
        <div class="btn-group">
            <button class="btn-circle" id="talkBtn">
                <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
            </button>
            <button class="btn-stop" id="stopBtn" title="Lõpeta kõne" style="display: none;">
                <svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>
            </button>
        </div>
    </div>

    <script>
        const btn = document.getElementById('talkBtn');
        const stopBtn = document.getElementById('stopBtn');
        const status = document.getElementById('statusText');
        const userText = document.getElementById('userText');
        const mayaText = document.getElementById('mayaText');
        const bars = document.querySelectorAll('.bar');

        let audioCtx = null;
        let analyser = null;
        let micStream = null;
        let mediaRecorder = null;
        let audioChunks = [];
        let isSessionActive = false;
        let isSpeaking = false;
        let silenceTimer = null;
        let speechStarted = false;

        // Audio queue süsteem sujuvaks mängimiseks ilma pausideta
        let audioQueue = [];
        let isPlayingAudio = false;

        const SILENCE_THRESHOLD = 22;
        const SILENCE_DELAY_MS = 1000; // Vähendatud 1.0 sekundile reageerimise kiirendamiseks

        async function initAudio() {
            if (audioCtx) return;
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
            
            const source = audioCtx.createMediaStreamSource(micStream);
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 64;
            source.connect(analyser);

            mediaRecorder = new MediaRecorder(micStream, { mimeType: 'audio/webm' });
            mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.onstop = async () => {
                const blob = new Blob(audioChunks, { type: 'audio/webm' });
                audioChunks = [];
                if (blob.size > 2000) {
                    await sendAudio(blob);
                } else if (isSessionActive) {
                    startRecording();
                }
            };

            monitorAudio();
        }

        function monitorAudio() {
            const dataArray = new Uint8Array(analyser.frequencyBinCount);
            function checkLevel() {
                if (!isSessionActive) {
                    bars.forEach(b => { b.style.height = '8px'; b.classList.remove('active'); });
                    requestAnimationFrame(checkLevel);
                    return;
                }

                analyser.getByteFrequencyData(dataArray);
                let sum = 0;
                for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
                let average = sum / dataArray.length;

                bars.forEach((bar, idx) => {
                    const val = dataArray[idx % dataArray.length];
                    bar.style.height = Math.max(8, (val / 255) * 55) + 'px';
                    if (val > SILENCE_THRESHOLD) bar.classList.add('active');
                    else bar.classList.remove('active');
                });

                if (!isSpeaking) {
                    if (average > SILENCE_THRESHOLD) {
                        if (!speechStarted && mediaRecorder.state === "recording") {
                            speechStarted = true;
                            status.innerText = "Kuulan...";
                            btn.className = "btn-circle listening";
                        }
                        if (silenceTimer) {
                            clearTimeout(silenceTimer);
                            silenceTimer = null;
                        }
                    } else if (speechStarted) {
                        if (!silenceTimer) {
                            silenceTimer = setTimeout(() => {
                                status.innerText = "Maya mõtleb...";
                                stopRecording();
                                speechStarted = false;
                                silenceTimer = null;
                            }, SILENCE_DELAY_MS);
                        }
                    }
                }

                requestAnimationFrame(checkLevel);   }
            checkLevel();
        }

        function startRecording() {
            if (mediaRecorder && mediaRecorder.state === "inactive" && isSessionActive) {
                audioChunks = [];
                speechStarted = false;
                mediaRecorder.start(200);
                if (!isSpeaking) {
                    status.innerText = "Räägi vabalt...";
                    btn.className = "btn-circle listening";
                }
            }
        }

        function stopRecording() {
            if (mediaRecorder && mediaRecorder.state === "recording") {
                mediaRecorder.stop();
            }
        }

        async function startSession() {
            await initAudio();
            if (audioCtx.state === 'suspended') await audioCtx.resume();
            isSessionActive = true;
            stopBtn.style.display = "flex";

            try {
                const gRes = await fetch('/api/check_greeting');
                if (gRes.status === 200) {
                    const blob = await gRes.blob();
                    const greetingTxt = decodeURIComponent(gRes.headers.get("X-Maya-Text") || "");
                    if (greetingTxt) mayaText.innerText = greetingTxt;
                    audioQueue.push(blob);
                    playNextAudio();
                    return;
                }
            } catch (err) {
                console.log("Ei saanud tervitusheli:", err);
            }
            startRecording();
        }

        function endSession() {
            isSessionActive = false;
            stopRecording();
            audioQueue = [];
            isPlayingAudio = false;
            stopBtn.style.display = "none";
            status.innerText = "Kõne lõpetatud";
            btn.className = "btn-circle";
        }

        btn.addEventListener('click', () => {
            if (!isSessionActive) startSession();
        });
        stopBtn.addEventListener('click', endSession);

        function playNextAudio() {
            if (audioQueue.length === 0) {
                isPlayingAudio = false;
                isSpeaking = false;
                if (isSessionActive) {
                    startRecording();
                } else {
                    status.innerText = "Ootel";
                    btn.className = "btn-circle";
                }
                return;
            }

            isPlayingAudio = true;
            isSpeaking = true;
            btn.className = "btn-circle speaking";
            status.innerText = "Maya räägib...";

            const audioBlob = audioQueue.shift();
            const url = URL.createObjectURL(audioBlob);
            const snd = new Audio(url);
            snd.play();
            snd.onended = () => {
                playNextAudio();
            };
        }

        async function sendAudio(blob) {
            isSpeaking = true;
            btn.className = "btn-circle speaking";
            status.innerText = "Maya mõtleb...";

            const formData = new FormData();
            formData.append('file', blob, 'audio.webm');

            try {
                const res = await fetch('/api/chat', { method: 'POST', body: formData });
                if (!res.ok) throw new Error("Võrguviga");

                const userTranscription = decodeURIComponent(res.headers.get("X-User-Text") || "");
                const mayaReply = decodeURIComponent(res.headers.get("X-Maya-Text") || "");

                if (userTranscription && userTranscription !== "...") {
                    userText.innerText = userTranscription;
                    userText.style.display = "block";
                }
                if (mayaReply) {
                    mayaText.innerText = mayaReply;
                }

                const audioBlob = await res.blob();
                audioQueue.push(audioBlob);
                if (!isPlayingAudio) {
                    playNextAudio();
                }
            } catch (e) {
                console.error(e);
                isSpeaking = false;
                status.innerText = "Tekkis tõrge";
                if (isSessionActive) startRecording();
            }
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(content=HTML_PAGE)


def build_morning_briefing() -> str:
    """Kogub hommikubriifingu andmed kokku (SÜNKROONNE – kutsu to_thread kaudu).

    Kõik neli allikat olid serveris juba olemas, aga neid kasutati ainult siis,
    kui kasutaja ise küsis. Briifing toob need ise kohale.
    """
    import sqlite3
    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    parts = []
    now = _dt.datetime.now(_Z("Europe/Tallinn"))

    # Tänased kalendrisündmused
    try:
        conn = config.connect(timeout=10)
        c = conn.cursor()
        today = now.strftime("%Y-%m-%d")
        rows = c.execute(
            "SELECT trigger_time, reminder_text FROM reminders "
            "WHERE trigger_time LIKE ? AND is_done = 0 AND IFNULL(notify_type,'') != 'briefing' "
            "ORDER BY trigger_time ASC LIMIT 6",
            (f"{today}%",)
        ).fetchall()
        conn.close()
        if rows:
            ev = "; ".join(f"kell {t[11:16]} {txt}" for t, txt in rows)
            parts.append(f"TÄNASED SÜNDMUSED: {ev}")
        else:
            parts.append("TÄNASED SÜNDMUSED: kalendris pole täna midagi kirjas.")
    except Exception as e:
        print(f"--> [BRIIFING] kalendri viga: {e}", flush=True)

    for label, fn in (("ILM", maya_brain.get_weather_overview),
                      ("ELEKTER", maya_brain.get_electricity_overview),
                      ("POSTKAST", maya_brain.get_email_overview)):
        try:
            val = fn()
            if val:
                parts.append(f"{label}: {str(val).strip()[:700]}")
        except Exception as e:
            print(f"--> [BRIIFING] {label} viga: {e}", flush=True)

    return "\n".join(parts) if parts else "Andmeid ei õnnestunud koguda."


async def background_reminder_watcher():
    import sqlite3, datetime
    from zoneinfo import ZoneInfo
    while True:
        try:
            now_dt = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
            now_str = now_dt.strftime("%Y-%m-%d %H:%M")
            conn = config.connect(timeout=10)
            c = conn.cursor()
            # 'persona' veerg lisati hiljem – loeme selle turvaliselt, et
            # vanad baasid (kus veergu veel pole) ei lõhuks valvurit.
            try:
                _rcols = [r[1] for r in c.execute("PRAGMA table_info(reminders)").fetchall()]
            except Exception:
                _rcols = []
            _persona_sel = ", persona" if "persona" in _rcols else ", '' AS persona"
            _notify_sel = ", notify_type" if "notify_type" in _rcols else ", 'call' AS notify_type"
            due = c.execute(f"""
                SELECT id, trigger_time, reminder_text, repeat_type, custom_speech{_persona_sel}{_notify_sel}
                FROM reminders 
                WHERE trigger_time <= ? AND is_done = 0
            """, (now_str,)).fetchall()
            
            for rem_id, trig_time, rem_text, rep_type, cust_speech, rem_persona, rem_notify in due:
                rep_type = rep_type or "none"
                if rep_type == "none":
                    c.execute("UPDATE reminders SET is_done = 1 WHERE id = ?", (rem_id,))
                else:
                    try:
                        cur_t = datetime.datetime.strptime(trig_time, "%Y-%m-%d %H:%M")
                        if rep_type == "daily":
                            next_t = cur_t + datetime.timedelta(days=1)
                        elif rep_type == "weekly":
                            next_t = cur_t + datetime.timedelta(days=7)
                        elif rep_type == "workdays":
                            next_t = cur_t + datetime.timedelta(days=1)
                            while next_t.weekday() >= 5:
                                next_t += datetime.timedelta(days=1)
                        else:
                            next_t = cur_t + datetime.timedelta(days=1)
                        c.execute("UPDATE reminders SET trigger_time = ? WHERE id = ?", (next_t.strftime("%Y-%m-%d %H:%M"), rem_id))
                    except Exception as re:
                        print(f"Korduse arvutamise viga: {re}", flush=True)
                        c.execute("UPDATE reminders SET is_done = 1 WHERE id = ?", (rem_id,))
                conn.commit()

                print(f"--> [ANDROID CALL] Käivitan meeldetuletuse kõne: '{rem_text}' (Kordus: {rep_type})", flush=True)
                if (rem_notify or "").lower() == "briefing":
                    # Hommikubriifing: andmed kogutakse HELISTAMISE HETKEL, mitte
                    # salvestamise ajal – muidu oleks ilmateade eilne.
                    brief = await asyncio.to_thread(build_morning_briefing)
                    greeting_msg = (
                        f"Tee {user_profile.get_name()}ile lühike hommikubriifing "
                        "OMA KARAKTERI STIILIS. "
                        "Ära loe andmeid masinlikult ette – räägi need loomulikult ja "
                        "lühidalt kokku, kõige tähtsam enne. Lõpeta küsimusega, kas ta "
                        "soovib millestki täpsemalt kuulda.\n\nANDMED:\n" + brief
                    )
                elif cust_speech and cust_speech.strip():
                    greeting_msg = cust_speech.strip()
                else:
                    cleaned = clean_reminder_for_speech(rem_text)
                    greeting_msg = f"Kuule! Helistan sulle, sest tahtsid meelde tuletada: {cleaned}"
                
                print(
                    f"--> [OTSE GEMINI LIVE KÕNE]: Tervitusprompt seatud: '{greeting_msg}'"
                    + (f" (karakter: {rem_persona})" if rem_persona else ""),
                    flush=True,
                )
                # Karakter antakse kaasa, et meeldetuletuse esitaks seesama
                # karakter, kes selle lõi (nt lauljana loodud riimuv äratus).
                set_pending_call_prompt(greeting_msg, rem_persona or "")
                await call_event_queue.put(f"Meeldetuletus: {greeting_msg}")
            conn.close()
            await asyncio.sleep(5)
        except Exception as e:
            print("Viga meeldetuletuste valvuris:", e, flush=True)
            await asyncio.sleep(5)


# =====================================================================
# MAYA KALENDRI JA MEELDETULETUSTE REST API
# =====================================================================
@app.get("/api/reminders")
async def get_all_reminders(kasutaja: dict = Depends(noua_kasutaja)):
    try:
        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        rows = c.execute("""
            SELECT id, trigger_time, reminder_text, is_done, repeat_type, custom_speech 
            FROM reminders 
            WHERE is_done = 0 
            ORDER BY trigger_time ASC
        """).fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({
                "id": r[0],
                "trigger_time": r[1],
                "reminder_text": r[2],
                "is_done": r[3],
                "repeat_type": r[4] or "none",
                "custom_speech": r[5] or ""
            })
        return JSONResponse({"reminders": items})
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/reminders")
async def create_reminder(req: Request, kasutaja: dict = Depends(noua_kasutaja)):
    try:
        try:
            data = await req.json()
        except Exception:
            form = await req.form()
            data = dict(form)

        trigger_time = data.get("trigger_time")
        reminder_text = str(data.get("reminder_text", "")).strip()
        repeat_type = str(data.get("repeat_type", "none")).strip()
        custom_speech = str(data.get("custom_speech", "")).strip() or reminder_text
        notify_type = str(data.get("notify_type", "call")).strip()

        if not trigger_time or not reminder_text:
            return JSONResponse({"error": "Kuupäev ja teema on kohustuslikud"}, status_code=400)

        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("""
            INSERT INTO reminders (trigger_time, reminder_text, is_done, repeat_type, custom_speech, notify_type)
            VALUES (?, ?, 0, ?, ?, ?)
        """, (trigger_time, reminder_text, repeat_type, custom_speech, notify_type))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
        return JSONResponse({"success": True, "id": new_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/reminders/{rem_id}")
async def delete_reminder(rem_id: int, kasutaja: dict = Depends(noua_kasutaja)):
    try:
        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("DELETE FROM reminders WHERE id = ?", (rem_id,))
        conn.commit()
        conn.close()
        return JSONResponse({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/reminders/{rem_id}/update")
@app.put("/api/reminders/{rem_id}")
async def update_reminder_api(rem_id: int, request: Request, kasutaja: dict = Depends(noua_kasutaja)):
    try:
        try:
            data = await request.json()
        except Exception:
            form = await request.form()
            data = dict(form)

        rem_text = str(data.get("reminder_text", "")).strip()
        cust_speech = str(data.get("custom_speech", "")).strip() or rem_text
        notif_type = str(data.get("notify_type", "call")).strip()

        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("""
            UPDATE reminders 
            SET reminder_text = ?, custom_speech = ?, notify_type = ? 
            WHERE id = ?
        """, (rem_text, cust_speech, notif_type, rem_id))
        conn.commit()
        conn.close()

        return JSONResponse({"success": True, "id": rem_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.on_event("startup")
async def start_watcher_task():
    asyncio.create_task(background_reminder_watcher())

async def schedule_delayed_call(seconds: int, text: str):
    await asyncio.sleep(seconds)
    print(f"--> [ANDROID CALL] Taimer {seconds}s sai läbi, helistan!", flush=True)
    try:
        cleaned = clean_reminder_for_speech(text)
        greeting_msg = f"Kuule, helistan tagasi nagu palusid! {cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned}"
        res = core.tts_generate_long(greeting_msg, "timer_call") if hasattr(core, "tts_generate_long") else None
        ogg_path = getattr(res, "ogg_path", res) if res else None
        if isinstance(ogg_path, tuple): ogg_path = ogg_path[0]
        if ogg_path and os.path.exists(str(ogg_path)):
            global pending_greeting_audio, pending_greeting_text
            with open(str(ogg_path), "rb") as bf:
                pending_greeting_audio = bf.read()
            pending_greeting_text = greeting_msg
            print(f"--> [TAIMERI HELI VALMIS]: suurus {len(pending_greeting_audio)} baiti", flush=True)
    except Exception as ge:
        print("Taimeri tervitusheli viga:", ge, flush=True)
    set_pending_call_prompt(greeting_msg)
    await call_event_queue.put(f"Taimer: {text}")


pending_greeting_audio = None
pending_greeting_text = ""


@app.get("/api/trigger_greeting")
async def trigger_greeting(reason: str = "", fallback: bool = False, kasutaja: dict = Depends(noua_kasutaja)):
    global pending_greeting_audio, pending_greeting_text
    print(f"--> [TRIGGER GREETING REQUEST] reason='{reason}' fallback={fallback}", flush=True)
    if not fallback:
        # Tavalise kõne puhul räägib reaalajas Kore läbi WebSocketi
        from live_maya_ws import PENDING_CALL_PROMPT
        if reason and not PENDING_CALL_PROMPT:
            clean_r = reason.replace("Taimer: ", "").replace("Meeldetuletus: ", "").strip()
            set_pending_call_prompt(f"Tahtsid meelde tuletada: {clean_r}")
        return Response(status_code=204)
    global pending_greeting_audio, pending_greeting_text
    print(f"--> [TRIGGER GREETING REQUEST] reason='{reason}'", flush=True)
    if pending_greeting_audio:
        audio = pending_greeting_audio
        txt = pending_greeting_text
        pending_greeting_audio = None
        pending_greeting_text = ""
        return Response(content=audio, media_type="audio/ogg", headers={"X-Maya-Text": requests_quote(txt)})
    
    # Kui ootel heli polnud, genereerime kohe reason põhjal
    msg = "Kuule, helistan sulle tagasi!"
    if reason:
        clean_reason = reason.replace("Taimer: ", "").replace("Meeldetuletus: ", "").strip()
        msg = f"Kuule, tahtsin meelde tuletada: {clean_reason}"
    
    res = core.tts_generate_long(msg, "dyn_greet") if hasattr(core, "tts_generate_long") else None
    ogg_path = getattr(res, "ogg_path", res) if res else None
    if isinstance(ogg_path, tuple): ogg_path = ogg_path[0]
    if ogg_path and os.path.exists(str(ogg_path)):
        with open(str(ogg_path), "rb") as bf:
            audio = bf.read()
        return Response(content=audio, media_type="audio/ogg", headers={"X-Maya-Text": requests_quote(msg)})
    
    return Response(status_code=204)

@app.get("/api/check_greeting")
async def check_greeting(fallback: bool = False, kasutaja: dict = Depends(noua_kasutaja)):
    global pending_greeting_audio, pending_greeting_text
    if not fallback:
        return Response(status_code=204)
    global pending_greeting_audio, pending_greeting_text
    if pending_greeting_audio:
        audio_data = pending_greeting_audio
        text_data = pending_greeting_text
        pending_greeting_audio = None
        pending_greeting_text = ""
        return Response(
            content=audio_data,
            media_type="audio/ogg",
            headers={
                "X-Maya-Text": requests_quote(text_data),
                **({"X-Maya-Action": requests_quote('{"action":"open_youtube","query":""}')} if any(w in (user_text or "").lower() for w in ["ava youtube", "pane youtube", "mängi youtube", "youtube"]) and "ei" not in (user_text or "").lower() else {})
            }
        )
    return Response(status_code=204)


def get_realtime_calendar_block() -> str:
    """Tagastab ALATI värske kalendriseisu ja ranged hallutsinatsioonivastased reeglid."""
    now_dt = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    weekdays_et = ["esmaspäev", "teisipäev", "kolmapäev", "neljapäev", "reede", "laupäev", "pühapäev"]
    w_day = weekdays_et[now_dt.weekday()]
    try:
        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("SELECT id, trigger_time, reminder_text, repeat_type FROM reminders WHERE is_done = 0 ORDER BY trigger_time ASC")
        rows = c.fetchall()
        conn.close()
        if rows:
            lines = [f"- Aeg: {r[1]} | Sisu: \"{r[2]}\" (ID: {r[0]})" for r in rows]
            cal_str = "\n".join(lines)
        else:
            cal_str = "MITTE ÜHTEGI! Kalender on hetkel täiesti tühi."
    except Exception as e:
        cal_str = f"Kalendri lugemise viga: {e}"

    return (
        f"\n=== KASUTAJA KALENDRI JA MEELDETULETUSTE REAALAJAS SEIS ===\n"
        f"Praegune täpne aeg: {now_dt.strftime('%Y-%m-%d %H:%M')} ({w_day})\n"
        f"Aktiivsed meeldetuletused andmebaasis:\n{cal_str}\n\n"
        f"KRIITILISED KALENDRI REEGLID (KEHTIVAD ALATI):\n"
        f"1. Kui kasutaja küsib oma meeldetuletuste, kalendri, homsete plaanide või märkmete kohta, tohid vastata AINULT ülaloleva nimekirja ('Aktiivsed meeldetuletused andmebaasis') põhjal!\n"
        f"2. RANGELT KEELATUD on võtta tegevusi (nt põllutööd, küüslauk, ehitus vms) vestlusarhiivist või mälust ja esitada neid kalendri meeldetuletustena!\n"
        f"3. Kui ülal on kirjas 'MITTE ÜHTEGI!', siis ütle otse ja lühidalt: 'Sul ei ole hetkel ühtegi meeldetuletust kirjas.' Ära mõtle mitte midagi juurde!\n"
        f"===========================================================\n\n"
    )

def delete_matching_reminder(user_query: str):
    try:
        import sqlite3
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("SELECT id, reminder_text, trigger_time FROM reminders WHERE is_done = 0")
        active = c.fetchall()
        if not active:
            conn.close()
            return False, "Sul ei ole praegu ühtegi aktiivset meeldetuletust, mida kustutada."

        target_id = None
        target_text = None
        q_lower = user_query.lower()

        for r_id, r_text, r_time in active:
            if r_text.lower() in q_lower or any(w in q_lower for w in r_text.lower().split() if len(w) > 2):
                target_id = r_id
                target_text = r_text
                break

        if not target_id and len(active) == 1:
            target_id = active[0][0]
            target_text = active[0][1]

        if target_id:
            c.execute("DELETE FROM reminders WHERE id = ?", (target_id,))
            conn.commit()
            conn.close()
            return True, f"Kustutasin meeldetuletuse '{target_text}' kalendrist ära."

        conn.close()
        return False, "Ei leidnud kalendrist sellist meeldetuletust, mida soovisid kustutada."
    except Exception as e:
        return False, f"Viga meeldetuletuse kustutamisel: {e}"

@app.post("/api/chat")
async def chat_endpoint(file: UploadFile = File(None), image: UploadFile = File(None), text: str = Form(None), voice: str = Form("maya"), persona: str = Form("asjalik"), custom_prompt: str = Form(""), device_telemetry: str = Form(None), x_voice_choice: str = Header(None), kasutaja: dict = Depends(noua_kasutaja)):
    image_bytes = None
    if image:
        try:
            image_bytes = await image.read()
            print(f"--> [VISION]: Saadi pilt suurusega {len(image_bytes)} baiti", flush=True)
        except Exception as e:
            print(f"Vision image read error: {e}", flush=True)

    image_bytes = None
    if image:
        try:
            image_bytes = await image.read()
            print(f"--> [STREAM VISION]: Pilt vastu võetud ({len(image_bytes)} baiti)", flush=True)
        except Exception as ie:
            print("Stream vision read error:", ie, flush=True)

    user_text = (text or "").strip()
    if file and not user_text:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as in_f:
            in_f.write(await file.read())
            in_path = in_f.name

        out_wav = in_path + ".wav"
        # P0: ffmpeg on blokeeriv protsess – see peab käima tööliskiibis, muidu
        # seisab kogu sündmustesilmus ja käimasolev häälkõne (/ws/live_maya,
        # mis jagab sedasama silmust) jääb vaikseks.
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", out_wav],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            with open(out_wav, "rb") as f:
                audio_bytes = f.read()

            stt_prompt = "Transkribeeri see eestikeelne kõne täpselt tekstiks. Väljasta AINULT transkriptsioon ilma kommentaarideta."
            # P0: sünkroonne Gemini STT kutse -> tööliskiibi kaudu
            stt_res = await asyncio.to_thread(
                lambda: core.gemini_client.models.generate_content(
                    model=core.GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                        stt_prompt
                    ]
                )
            )
            user_text = stt_res.text.strip() if stt_res and stt_res.text else ""
            for leak in ["Transkribeeri see eestikeelne kõne täpselt tekstiks.", "Väljasta AINULT transkriptsioon ilma kommentaarideta."]:
                user_text = user_text.replace(leak, "").strip()
        except Exception as e:
            print(f"STT viga: {e}", flush=True)
            user_text = ""
        finally:
            for p in [in_path, out_wav]:
                if os.path.exists(p): os.remove(p)

    # Müra- ja tühjusefilter (katkesta kohe ilma LLM-i koormamata)
    import re
    cleaned_lower = (user_text or "").strip().lower()
    junk_patterns = {"...", "..", ".", "<noise>", "(müra)", "[müra]"}
    is_junk = (
        not cleaned_lower
        or cleaned_lower in junk_patterns
        or bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", cleaned_lower))
        or "transkribeeri see eestikeelne" in cleaned_lower
        or sum(1 for c in cleaned_lower if c.isalnum()) < 2
    )

    if is_junk:
        print(f"--> [MÜRAFILTER]: Hüljatud mürapäring '{user_text}' (katkestan kohe)", flush=True)
        return Response(status_code=204)

    now = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    current_time_str = now.strftime("%H:%M")
    current_weekday = now.strftime("%A")

    # P0: need kolm teevad SQLite-päringuid (blokeeriv) – tööliskiibi kaudu
    memory_context = await asyncio.to_thread(core.format_memory_for_prompt)
    knowledge_context = await asyncio.to_thread(core.format_knowledge_for_prompt)
    archive_context = (
        await asyncio.to_thread(core.lookup_past_conversations, user_text)
        if hasattr(core, "lookup_past_conversations") else ""
    )

    # Valime karakteri stiili
    active_persona = (persona or "asjalik").strip().lower()
    if active_persona == "custom" and custom_prompt and custom_prompt.strip():
        persona_style = f"KOHANDATUD KARAKTERI JUHIS: {custom_prompt.strip()}"
    else:
        persona_style = PERSONA_PROMPTS.get(active_persona, PERSONA_PROMPTS.get("asjalik", ""))

    # Kontrollime e-kirju, kui kasutaja neid mainib
    email_info_prompt = ""
    email_triggers = ["email", "e-mail", "meil", "kirjad", "kiri", "postkast", "gmail", "inbox", "kirju"]
    user_lower = user_text.lower()
    if any(trig in user_lower for trig in email_triggers):
        try:
            print("--> [EMAIL_TOOL]: Kasutaja küsis e-kirju, pärin IMAP-ist...", flush=True)
            mail_summary = await asyncio.to_thread(email_tool.get_emails_summary)
            if mail_summary and mail_summary.strip():
                email_info_prompt = (
                    "\nE-KIRJADE REAALAJAS ANDMED (KASUTAJA POSTKASTID):\n"
                    f"{mail_summary}\n\n"
                    "E-KIRJADE VASTAMISE REEGLID:\n"
                    "1. Kui kasutaja küsib kirjade, meilide või teadete kohta, vasta TÄPSELT ülaltoodud andmete põhjal!\n"
                    "2. Nimeta konkreetselt saatja nimi ja teema ning soovi korral lühike sisukokkuvõte.\n"
                    "3. Kui kirju on mõlemas kontos, too mõlemad selgelt välja.\n"
                    "4. Ära ütle kunagi, et sul puudub ligipääs e-kirjadele, sest sul on andmed otse siin olemas.\n\n"
                )
        except Exception as e:
            print(f"Email check error: {e}", flush=True)


    # Ilmainfo kontroll
    weather_info_prompt = ""
    weather_triggers = ["ilm", "temperatuur", "kraad", "kraadi", "sajab", "vihm", "tuul", "soe", "külm", "ohtu", "ohtus"]
    if any(trig in user_lower for trig in weather_triggers):
        try:
            print(f"--> [WEATHER_TOOL]: Päring ilmainfo kohta: {config.ASUKOHT}", flush=True)
            w_data = features_pack.get_detailed_weather()
            if isinstance(w_data, dict):
                temp = w_data.get("current_temp", "?")
                wind = w_data.get("current_wind", "?")
                gust = w_data.get("max_gust", "?")
                min_t = w_data.get("min_temp_12h", "?")
                rain_str = "sajab või hakkab peagi sadama" if w_data.get("rain_upcoming") else "kuiv, sademeid ei paista"
                loc = w_data.get("location", config.ASUKOHT)
                weather_info_prompt = f"""
ILMATEATE REAALAJAS ANDMED ({loc}):
- Praegune temperatuur: {temp}°C
- Tuul: {wind} m/s (puhanguti kuni {gust} m/s)
- Sademed: {rain_str}
- Järgmise 12h miinimumtemperatuur: {min_t}°C
Reegel: Vasta ilmaküsimusele elavalt ja täpselt nende numbrite põhjal! Ära ütle, et sul andmeid pole.

"""
        except Exception as we:
            print("Weather check error:", we, flush=True)

    # Kalendri ja meeldetuletuste reaalajas andmed
    calendar_info_prompt = ""
    cal_triggers = ["kalender", "kalendris", "kalendrisse", "meeldetuletus", "meeldetuletused", "meeldetuletusi", "märkmed", "märge", "plaanid", "plaanis", "kava", "ajakava", "tegemised", "päevakava"]
    if any(trig in user_lower for trig in cal_triggers) or ("mis" in user_lower and ("teha" in user_lower or "ees" in user_lower or "tulemas" in user_lower)):
        try:
            print("--> [CALENDAR_TOOL]: Kasutaja küsis kalendri/meeldetuletuste kohta, loen baasist...", flush=True)
            cal_data = get_calendar_reminders_context()
            calendar_info_prompt = f"""
KALENDRI JA MEELDETULETUSTE REAALAJAS ANDMED (ANDMEBAASIST):
Praegune kellaaeg ja kuupäev: {now.strftime('%Y-%m-%d %H:%M')} ({current_weekday})
Olemasolevad kirjed:
{cal_data}

KALENDRI VASTAMISE REEGLID:
1. Kui kasutaja küsib kalendri, märkmete, plaanide või meeldetuletuste kohta, vasta TÄPSELT ülaltoodud kirjete põhjal!
2. Kui kirjeid on, nimeta kellaajad/kuupäevad ja teemad selgelt ja lühidalt.
3. Ära mitte mingil juhul ütle, et sul pole ligipääsu kalendrile või et sa ei tea – sul on andmed otse siin olemas!
4. Kui kirjeid pole, ütle sõbralikult, et kalender on hetkel tühi.
\n"""
        except Exception as ce:
            print("Calendar check error:", ce, flush=True)


    # Loeme seadme täielikku telemeetriat
    device_info_prompt = ""
    maya_action_payload = None
    if device_telemetry:
        try:
            import json
            tel = json.loads(device_telemetry)
            lvl = tel.get("level", -1)
            chg = "jah, laeb" if tel.get("charging") else "ei lae"
            net = tel.get("network", "teadmata")
            ringer = tel.get("ringer", "tavaline")
            vol = tel.get("volume", -1)
            audio_out = tel.get("audio_output", "kuular")
            free_gb = tel.get("free_storage_gb", "?")
            avail_ram = tel.get("avail_ram_gb", "?")
            total_ram = tel.get("total_ram_gb", "?")
            alarm = tel.get("next_alarm", "pole seatud")
            torch_state = "sees" if tel.get("torch") else "väljas"

            if lvl != -1:
                device_info_prompt = (
                    "\nTELEFONI REAALAJAS ANDMED:\n"
                    f"- Aku: {lvl}% (laadimine: {chg})\n"
                    f"- Võrguühendus: {net}\n"
                    f"- Heli: {ringer}, meedia helitugevus: {vol}%, väljund: {audio_out}\n"
                    f"- Salvestusruum: {free_gb} GB vaba | RAM: {avail_ram} GB vaba / {total_ram} GB kokku\n"
                    f"- Järgmine äratuskell: {alarm}\n"
                    f"- Taskulamp: {torch_state}\n\n"
                    "SEADME JUHTIMISE JA TELEMEETRIA REEGLID:\n"
                    "1. Kui kasutaja küsib mälu, RAM-i, aku, võrgu, heli või äratuse kohta, kasuta ALATI ülaltoodud täpseid numbreid! Ära ütle kunagi, et sul pole andmeid.\n"
                    "Kui kasutaja palub seadet juhtida, kinnita seda lühidalt ja lisa vastuse LÕPPU täpselt üks märgis:\n"
                    "   - Taskulamp põlema: [ACTION:{\"action\":\"torch\",\"enable\":true}]\n"
                    "   - Taskulamp kustu: [ACTION:{\"action\":\"torch\",\"enable\":false}]\n"
                    "   - Heli kõvemaks: [ACTION:{\"action\":\"volume\",\"mode\":\"up\"}]\n"
                    "   - Heli vaiksemaks: [ACTION:{\"action\":\"volume\",\"mode\":\"down\"}]\n"
                    "   - Ava YouTube: [ACTION:{\"action\":\"youtube\",\"query\":\"otsing\"}]\n"
                    "   (See märgis lõigatakse enne kõnesünteesi välja, seda ei hääldata!)\n\n"
                )
        except Exception as e:
            print(f"Telemeetria viga: {e}", flush=True)

    system_prompt = (
        get_realtime_calendar_block() +
        weather_info_prompt +
        device_info_prompt +
        email_info_prompt +
        f"Sa oled Maya.\n"
        f"Hetke aeg: {current_time_str} ({current_weekday}).\n"
        f"KASUTAJA TAUST (RANGELT PASSIIVNE TEADMINE):\n"
        f"- Kodukoht: {config.ASUKOHT}.\n"
        f"KATEGOORILINE KEELD JA REEGEL:\n"
        f"ÄRA KUNAGI maini kasutaja elukohta, sõiduki andmeid ega muid "
        f"mälufakte omal algatusel! "
        f"Käitu nagu normaalne inimene: räägi AINULT sellest, mida kasutaja parasjagu küsis. "
        f"Asukohta või sõiduki andmeid tohid kasutada AINULT siis, kui kasutaja esitab nende kohta OTSESE küsimuse (nt \"mis ilm mul siin on?\" või \"mis mu autonumber on?\"). Muul ajal on nende mainimine rangelt keelatud.\n\n"
        f"AKTIIVNE ROLL JA SUHTLEMISSTIIL:\n"
        f"{persona_style}\n\n"
        "ÜLDISED REEGLID:\n"
        "- Järgi rangelt oma aktiivset rolli ja tooni igas vastuses!\n"
        "- Vasta ALATI konkreetselt sellele, mida kasutaja küsis või ütles.\n"
        "- ÄRA KUNAGI vabanda stiilis 'ma olen tehisintellekt' või 'ma olen AI'.\n"
        "- Vasta lühidalt ja loomulikult (1-3 lauset), et dialoog oleks kiire ja vahetu.\n"
        f"{memory_context}\n"
        f"{knowledge_context}\n"
        f"{archive_context}\n"
    )

    # Laeme viimased 4 vestlusringi lühimäluks
    # P0: lühimälu lugemine SQLite'ist tööliskiibi kaudu (blokeeriv I/O)
    def _load_recent_history():
        import sqlite3
        out = ""
        # AKTIIVSE kasutaja andmebaas (vt config.db_tee()).
        conn = config.connect(timeout=10)
        try:
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tbl in tables:
                cols = [col[1] for col in c.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if "user_text" in cols and "reply_text" in cols:
                    rows = c.execute(f"SELECT user_text, reply_text FROM {tbl} ORDER BY rowid DESC LIMIT 3").fetchall()
                    history_turns = []
                    for u, m in reversed(rows):
                        if u and m:
                            history_turns.append(f"Kasutaja: {u}\nMaya: {m}")
                    if history_turns:
                        out = "\n".join(history_turns) + "\n"
                    break
        finally:
            conn.close()
        return out

    recent_history = ""
    try:
        recent_history = await asyncio.to_thread(_load_recent_history)
    except Exception as e:
        print("Ajaloo laadimise viga:", e, flush=True)

            # --- TÄIELIK REAALAJAS AJU ---
    try:
        # P0: get_dynamic_context võib teha Tavily veebiotsingu + ilma/elektri
        # HTTP-päringud (mitu sekundit) -> tööliskiibi kaudu
        dynamic_brain_context = await asyncio.to_thread(
            maya_brain.get_dynamic_context, user_text, active_persona
        )
        if dynamic_brain_context:
            system_prompt = system_prompt + "\n\n" + dynamic_brain_context
    except Exception as be:
        print("[BRAIN HOOK VIGA]:", be, flush=True)

    full_conversation_prompt = f"{recent_history}Kasutaja: {user_text}\nMaya:"
    if image_bytes:
        try:
            print(f"--> [VISION]: Edastan pildi ({len(image_bytes)} B) ja teksti Gemini Visionile...", flush=True)
            
            # Tuvastame mime_type päise järgi
            m_type = "image/jpeg"
            if image_bytes.startswith(b"\x89PNG"):
                m_type = "image/png"
            elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
                m_type = "image/webp"

            v_contents = [
                types.Part.from_bytes(data=image_bytes, mime_type=m_type),
                f"{recent_history}Kasutaja näitab sulle pilti ja ütleb: {user_text}\nMaya vastus:"
            ]
            
            v_cfg = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7
            )
            # P0: sünkroonne Gemini vision-kutse -> tööliskiibi kaudu
            v_res = await asyncio.to_thread(
                lambda: core.gemini_client.models.generate_content(
                    model=core.GEMINI_MODEL,
                    contents=v_contents,
                    config=v_cfg
                )
            )
            reply_text = v_res.text if (v_res and hasattr(v_res, "text") and v_res.text) else "Näen pilti, aga ei saanud sellest täpselt aru."
            print(f"--> [VISION VASTUS]: {reply_text}", flush=True)
        except Exception as ve:
            print(f"Vision mudeli viga: {ve}", flush=True)
            reply_text = core.ask_gemini(full_conversation_prompt, system_instruction=system_prompt, temperature=0.7)
    else:
        reply_text = core.ask_gemini(full_conversation_prompt, system_instruction=system_prompt, temperature=0.7)

    print(f"--> [MAYA LÕPLIK VASTUS]: '{reply_text}'", flush=True)
    if reply_text == "__FILTER_BLOCKED__":
        reply_text = "Kuule, see teema tõmbas juhtme kokku, räägime muust."

    
    print(f"--> [USER KÕNE TEKST]: '{user_text}'", flush=True)
    lower_u = user_text.lower()

    # 1. Kustutamise tuvastamine
    delete_triggers = ["kustuta", "eemalda", "tühista", "võta ära", "kustutada"]
    is_delete_query = any(dt in lower_u for dt in delete_triggers) and any(w in lower_u for w in ["meeldetuletus", "meeldetuletused", "meeldetuletust", "kalendrist", "sündmus", "märge"])
    if is_delete_query:
        print(f"--> [DELETE_REMINDER]: Kasutaja palus kustutada: '{user_text}'", flush=True)
        success, del_msg = delete_matching_reminder(user_text)
        reply_text = del_msg

    # 2. Kalendri pärimise kontroll
    is_calendar_query = any(w in lower_u for w in ["mis mul", "kas mul", "on mul", "näita", "loe ette", "kontrolli", "vaata"]) and any(w in lower_u for w in ["kalender", "kalendris", "märkmed", "meeldetuletus", "meeldetuletused", "meeldetuletusi", "plaanid"])

    triggers = ["helista", "tuleta", "meelde", "taimer", "ärkama", "magama"]
    is_calendar_query = any(w in lower_u for w in ["mis mul", "kas mul", "on mul", "näita", "loe ette", "kontrolli", "vaata"]) and any(w in lower_u for w in ["kalender", "kalendris", "märkmed", "meeldetuletus", "meeldetuletused", "meeldetuletusi", "plaanid"])
    if any(k in lower_u for k in triggers) and not is_calendar_query and not is_delete_query:
        try:
            now_dt = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
            parse_prompt = (
                f"Hetke aeg: {now_dt.strftime('%Y-%m-%d %H:%M')}.\n"
                f"Kasutaja ütles: '{user_text}'.\n"
                "Analüüsi, kas kasutaja palub tagasi helistada, taimerit või meeldetuletust.\n"
                "Väljasta AINULT kehtiv JSON:\n"
                "{\"is_reminder\": true, \"delay_seconds\": 60, \"trigger_time\": \"YYYY-MM-DD HH:MM\", \"topic\": \"mis teemal helistada\", \"confirmation\": \"Hästi, helistan sulle tagasi!\"}\n"
                "Reegel: kui küsitakse helistamist mõne minuti või sekundi pärast, arvuta delay_seconds täisarvuna (nt 1 min = 60). Kui kindel kellaaeg või kuupäev tulevikus, määra trigger_time."
            )
            data = None
            if hasattr(core, 'ask_gemini_json'):
                data = core.ask_gemini_json(parse_prompt)
            print(f"--> [PARSER TULEMUS]: {data}", flush=True)

            # Tagavara parsimine regexiga juhuks kui JSON peaks toppama
            fallback_delay = 0
            if "minut" in lower_u or "min" in lower_u:
                m = re.search(r'(\d+)\s*(minut|min)', lower_u)
                if m: fallback_delay = int(m.group(1)) * 60
                elif "ühe minuti" in lower_u or "üks minut" in lower_u or "1 minuti" in lower_u: fallback_delay = 60
            elif "sekund" in lower_u or "sek" in lower_u:
                m = re.search(r'(\d+)\s*(sekund|sek)', lower_u)
                if m: fallback_delay = int(m.group(1))

            delay = 0
            topic = user_text
            trig_time = None

            if data and data.get("is_reminder"):
                delay = int(data.get("delay_seconds") or 0)
                topic = data.get("topic") or user_text
                trig_time = data.get("trigger_time")
                # Kirjutame vastuse üle ainult siis, kui reaalselt loodi meeldetuletus või taimer
                if data.get("confirmation") and (delay > 0 or trig_time):
                    reply_text = data["confirmation"]

            if delay <= 0 and fallback_delay > 0:
                delay = fallback_delay
                print(f"--> [TAGAVARA REGEX TAIMER]: määratud {delay} sekundit", flush=True)

            if delay > 0:
                print(f"--> [KÄIVITAN TAUSTATAIMERI]: helistan {delay} sekundi pärast teemal '{topic}'", flush=True)
                asyncio.create_task(schedule_delayed_call(delay, topic))
            elif trig_time and hasattr(core, 'add_reminder'):
                print(f"--> [SALVESTAN ANDMEBAASI]: kuupäev {trig_time}, teema '{topic}'", flush=True)
                core.add_reminder(trig_time, topic)
        except Exception as err:
            print("Ajastuse kriitiline viga:", err, flush=True)

    # Ekstraktime riistvarakäsu enne logimist ja TTS-i
    maya_action_payload = None
    action_match = re.search(r'\[ACTION:\s*(\{.*?\})\]', reply_text)
    if action_match:
        try:
            maya_action_payload = action_match.group(1)
            reply_text = re.sub(r'\[ACTION:\s*\{.*?\}\]', '', reply_text).strip()
        except Exception as e:
            print("Action extract error:", e, flush=True)

    if hasattr(core, "log_conversation_turn"):
        core.log_conversation_turn(user_text, reply_text)
        asyncio.create_task(background_learn(user_text, reply_text))

    voice_pref = (x_voice_choice or voice or "maya").strip().lower()
    tts_res = core.tts_generate_long(reply_text, "web_reply", voice_choice=voice_pref)
    ogg_file = str(tts_res)
    used_voice = getattr(tts_res, "used_voice", voice_pref)
    is_fallback = getattr(tts_res, "is_fallback", False)
    fallback_reason = getattr(tts_res, "fallback_reason", "")

    with open(ogg_file, "rb") as f:
        audio_data = f.read()

    import urllib.parse
    headers = {
        "X-User-Text": urllib.parse.quote(user_text),
        "X-Maya-Text": urllib.parse.quote(reply_text),
        **({"X-Maya-Action": urllib.parse.quote(maya_action_payload)} if maya_action_payload else {}),
        "X-Voice-Used": used_voice,
        "X-Voice-Fallback": "true" if is_fallback else "false",
        "X-Voice-Fallback-Reason": urllib.parse.quote(fallback_reason)
    }

    return Response(content=audio_data, media_type="audio/ogg", headers=headers)


# ==========================================
# REAALAJAS LAUSEPOHINE VOOGEDASTUS (NDJSON)
# ==========================================
import streaming_engine


@app.get("/stream_test")
async def stream_test_page(kasutaja: dict = Depends(noua_kasutaja)):
    from fastapi.responses import HTMLResponse
    p = str(config.JUUR / "stream_test.html")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Faili ei leitud</h1>", status_code=404)


async def check_reminders_bg(u_text: str):
    if not u_text:
        return
    lower_u = u_text.lower().replace("he lista", "helista").replace("helistak", "helista")
    delete_triggers = ["kustuta", "eemalda", "tühista", "võta ära", "kustutada"]
    is_delete_query = any(dt in lower_u for dt in delete_triggers) and any(w in lower_u for w in ["meeldetuletus", "meeldetuletused", "meeldetuletust", "kalendrist", "sündmus", "märge"])
    is_calendar_query = any(w in lower_u for w in ["mis mul", "kas mul", "on mul", "näita", "loe ette", "kontrolli", "vaata"]) and any(w in lower_u for w in ["kalender", "kalendris", "märkmed", "meeldetuletus", "meeldetuletused", "meeldetuletusi", "plaanid"])
    if is_delete_query or is_calendar_query:
        print("--> [DEBUG REMINDER]: Tegemist on kalendri küsimise või kustutamisega, ei loo uut meeldetuletust.", flush=True)
        return
    triggers = ["helista", "helist", "kõne", "tuleta", "meelde", "taimer", "ärkama", "magama", "minut", "sekund"]
    print(f"--> [DEBUG REMINDER]: Kontrollin: '{lower_u}'", flush=True)
    if not any(k in lower_u for k in triggers):
        print("--> [DEBUG REMINDER]: Trigerit ei leitud, jätan vahele.", flush=True)
        return
    try:
        now_dt = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
        parse_prompt = (
            f"Hetke aeg: {now_dt.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Kasutaja ütles: '{u_text}'.\n"
            "Analüüsi, kas kasutaja palub tagasi helistada, taimerit või meeldetuletust.\n"
            "{\"is_reminder\": true, \"delay_seconds\": 60, \"trigger_time\": \"YYYY-MM-DD HH:MM\", \"topic\": \"mis teemal helistada\", \"confirmation\": \"Hästi, helistan sulle tagasi!\"}\n"
            "Reegel: kui küsitakse helistamist mõne minuti või sekundi pärast, arvuta delay_seconds täisarvuna (nt 1 min = 60). Kui kindel kellaaeg või kuupäev tulevikus, määra trigger_time."
        )
        data = None
        if hasattr(core, 'ask_gemini_json'):
            data = await asyncio.to_thread(core.ask_gemini_json, parse_prompt)
        print(f"--> [STREAM PARSER TULEMUS]: {data}", flush=True)

        fallback_delay = 0
        if "minut" in lower_u or "min" in lower_u:
            m = re.search(r'(\d+)\s*(minut|min)', lower_u)
            if m: fallback_delay = int(m.group(1)) * 60
            elif any(w in lower_u for w in ["ühe minuti", "üks minut", "1 minuti"]): fallback_delay = 60
        elif "sekund" in lower_u or "sek" in lower_u:
            m = re.search(r'(\d+)\s*(sekund|sek)', lower_u)
            if m: fallback_delay = int(m.group(1))

        delay = 0
        topic = u_text
        trig_time = None

        if data and data.get("is_reminder"):
            delay = int(data.get("delay_seconds") or 0)
            topic = data.get("topic") or u_text
            trig_time = data.get("trigger_time")

        if delay <= 0 and fallback_delay > 0:
            delay = fallback_delay
            print(f"--> [STREAM TAGAVARA REGEX TAIMER]: määratud {delay} sekundit", flush=True)

        if delay > 0:
            print(f"--> [STREAM TAUSTATAIMER]: helistan {delay} sekundi pärast teemal '{topic}'", flush=True)
            asyncio.create_task(schedule_delayed_call(delay, topic))
        elif trig_time and hasattr(core, 'add_reminder'):
            print(f"--> [STREAM SALVESTAN ANDMEBAASI]: kuupäev {trig_time}, teema '{topic}'", flush=True)
            core.add_reminder(trig_time, topic)
    except Exception as err:
        print("Stream ajastuse taustaviga:", err, flush=True)


@app.post("/api/chat_stream")
async def chat_stream_endpoint(
    file: UploadFile = File(None),
    image: UploadFile = File(None),
    text: str = Form(None),
    voice: str = Form("maya"),
    persona: str = Form("asjalik"),
    custom_prompt: str = Form(""),
    device_telemetry: str = Form(None),
    x_voice_choice: str = Header(None)
, kasutaja: dict = Depends(noua_kasutaja)):
    image_bytes = None
    if image:
        try:
            image_bytes = await image.read()
            print(f"--> [STREAM VISION]: Pilt vastu võetud ({len(image_bytes)} baiti)", flush=True)
        except Exception as ie:
            print(f"--> [STREAM VISION VIGA]: {ie}", flush=True)

    user_text = (text or "").strip()
    if file and not user_text:
        audio_raw = await file.read()
        print(f"--> [STREAM AUDIO]: Fail vastu võetud ({len(audio_raw)} baiti)", flush=True)
        in_path = None
        out_wav = None
        audio_bytes = audio_raw
        mime_type = "audio/wav"

        # Tuvastame päise järgi või konverteerime ffmpeg-iga WAV-iks
        try:
            with tempfile.NamedTemporaryFile(delete=False) as in_f:
                in_f.write(audio_raw)
                in_path = in_f.name
            out_wav = in_path + ".wav"
            # P0: ffmpeg tööliskiibis – ei tohi sündmustesilmust blokeerida
            res = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1", "-vn", out_wav],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if res.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 0:
                with open(out_wav, "rb") as f:
                    audio_bytes = f.read()
                mime_type = "audio/wav"
            else:
                # Kui ffmpeg tõrgub, määrame sobiva mime_type ja saadame toorbaidid
                err_msg = res.stderr.decode("utf-8", errors="ignore")[:200]
                print(f"--> [FFMPEG HOIATUS]: {err_msg}", flush=True)
                if audio_raw.startswith(b"RIFF"):
                    mime_type = "audio/wav"
                elif b"ftyp" in audio_raw[:32]:
                    mime_type = "audio/mp4"
                elif audio_raw.startswith(bytes([0x1a, 0x45, 0xdf, 0xa3])):
                    mime_type = "audio/webm"
                else:
                    mime_type = "audio/aac"
        except Exception as fe:
            print(f"--> [AUDIO EELTÖÖTLUS VIGA]: {fe}", flush=True)

        try:
            stt_prompt = "Transkribeeri see eestikeelne kõne täpselt tekstiks. Väljasta AINULT transkriptsioon ilma kommentaarideta."
            # P0: sünkroonne Gemini STT -> tööliskiibi kaudu
            stt_res = await asyncio.to_thread(
                lambda: core.gemini_client.models.generate_content(
                    model=core.GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                        stt_prompt
                    ]
                )
            )
            user_text = stt_res.text.strip() if stt_res and stt_res.text else ""
            for leak in ["Transkribeeri see eestikeelne kõne täpselt tekstiks.", "Väljasta AINULT transkriptsioon ilma kommentaarideta."]:
                user_text = user_text.replace(leak, "").strip()
            print(f"--> [STREAM STT TULEMUS]: '{user_text}'", flush=True)
        except Exception as e:
            print(f"--> [STREAM STT VIGA]: {e}", flush=True)
            user_text = ""
        finally:
            for p in [in_path, out_wav]:
                if os.path.exists(p): os.remove(p)

    cleaned_lower = (user_text or "").strip().lower()
    junk_patterns = {"...", "..", ".", "<noise>", "(müra)", "[müra]"}
    is_junk = (not cleaned_lower
               or cleaned_lower in junk_patterns
               or bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", cleaned_lower))
               or "transkribeeri see eestikeelne" in cleaned_lower
               or sum(1 for c in cleaned_lower if c.isalnum()) < 2)

    if is_junk:
        if image_bytes:
            print("--> [STREAM VISION]: Kõne puudub/müra, kuid pilt on kaasas -> vastan kaamerapildile!", flush=True)
            user_text = "Vaata seda pilti ja ütle lühidalt paari lausega, mida sa näed."
        else:
            print(f"--> [STREAM MÜRAFILTER]: Hüljatud (tühi/müra: '{user_text}')", flush=True)
            return Response(status_code=204)

    now = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    current_time_str = now.strftime("%H:%M")
    current_weekday = now.strftime("%A")

    # P0: SQLite-päringud tööliskiibi kaudu (vt chat_endpoint)
    memory_context = await asyncio.to_thread(core.format_memory_for_prompt)
    knowledge_context = await asyncio.to_thread(core.format_knowledge_for_prompt)
    archive_context = (
        await asyncio.to_thread(core.lookup_past_conversations, user_text)
        if hasattr(core, "lookup_past_conversations") else ""
    )

    active_persona = (persona or "asjalik").strip().lower()
    if active_persona == "custom" and custom_prompt and custom_prompt.strip():
        persona_style = f"KOHANDATUD KARAKTERI JUHIS: {custom_prompt.strip()}"
    else:
        persona_style = PERSONA_PROMPTS.get(active_persona, PERSONA_PROMPTS.get("asjalik", ""))

    chosen_voice = x_voice_choice or voice

    # Kontrollime, kas kasutaja palub striimis meeldetuletust kustutada
    lower_stream_u = user_text.lower()
    del_trigs = ["kustuta", "eemalda", "tühista", "võta ära", "kustutada"]
    stream_delete_note = ""
    if any(dt in lower_stream_u for dt in del_trigs) and any(w in lower_stream_u for w in ["meeldetuletus", "meeldetuletused", "meeldetuletust", "kalendrist", "sündmus", "märge"]):
        print(f"--> [STREAM DELETE_REMINDER]: Kustutan: '{user_text}'", flush=True)
        _, del_msg = delete_matching_reminder(user_text)
        stream_delete_note = f"\nNB! SÜSTEEM TEostas KUSTUTAMISE: {del_msg} Kinnita seda kasutajale lühidalt!\n"

    system_prompt = (
        get_realtime_calendar_block() +
        stream_delete_note +
        f"TÄNA ON: {current_weekday}, kell {current_time_str}.\n"
        f"AKTIIVNE ROLL JA SUHTLEMISSTIIL:\n{persona_style}\n\n"
        "ÜLDISED REEGLID:\n"
        "- Järgi rangelt oma rolli ja tooni igas vastuses!\n"
        "- Vasta konkreetselt ja vahetult (1-3 lauset), ilma tarbetu sissejuhatuseta.\n"
        "- ÄRA KUNAGI ütle, et oled tehisintellekt või mudel.\n" \
        "- SUL ON OLEMAS TAGASIHELISTAMISE VÕIMEKUS: Kui kasutaja palub tagasi helistada või midagi meelde tuletada, kinnita seda alati reipalt ja kindlalt (nt 'Hästi, helistan sulle tagasi!'). Ära iial väida, et sa ei saa helistada!\n"
        f"{memory_context}\n"
        f"{knowledge_context}\n"
        f"{archive_context}\n"
    )

    # P0: sama lühimälu lugemine tööliskiibi kaudu (stream-tee)
    def _load_recent_history_stream():
        import sqlite3
        out = ""
        # AKTIIVSE kasutaja andmebaas (vt config.db_tee()).
        conn = config.connect(timeout=10)
        try:
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for tbl in tables:
                cols = [col[1] for col in c.execute(f"PRAGMA table_info({tbl})").fetchall()]
                if "user_text" in cols and "reply_text" in cols:
                    rows = c.execute(f"SELECT user_text, reply_text FROM {tbl} ORDER BY rowid DESC LIMIT 3").fetchall()
                    history_turns = []
                    for u, m in reversed(rows):
                        if u and m:
                            history_turns.append(f"Kasutaja: {u}\nMaya: {m}")
                    if history_turns:
                        out = "\n".join(history_turns) + "\n"
                    break
        finally:
            conn.close()
        return out

    recent_history = ""
    try:
        recent_history = await asyncio.to_thread(_load_recent_history_stream)
    except Exception as e:
        print("Stream ajaloo viga:", e, flush=True)

    full_conv = f"{recent_history}Kasutaja: {user_text}\nMaya:"

    async def background_learn(u_text, r_text):
        """Õpib tekstivoorust fakte. PEAB olema async – streaming_engine
        teeb sellest asyncio.create_task'i.

        VIGA ENNE: see oli sünkroonne `def` ja kutsus funktsiooni
        `core.save_conversation_turn`, mida pole kunagi olemas olnud.
        hasattr andis False, keha ei teinud midagi, tagastus oli None ja
        `asyncio.create_task(None)` viskas TypeError'i. See püüti kinni
        stream_generator'is ja saadeti kliendile veasündmusena – seega IGA
        voogedastatud tekstivastus lõppes veaga "done" asemel ning telefon
        ei saanud kunagi teada, et vastus on valmis. Lisaks ei õppinud Maya
        tekstivestlusest MITTE MIDAGI: pikaajalisse mällu jõudsid ainult
        häälkõned.
        """
        try:
            await memory_engine.learn_from_text_turn(u_text, r_text, persona=active_persona)
        except Exception as le:
            print("Stream background_learn err:", le, flush=True)

    # --- DÜNAAMILINE AJU STRIIMILE ---
    try:
        import maya_brain
        # P0: Tavily/ilm/elekter HTTP -> tööliskiibi kaudu
        brain_ctx = await asyncio.to_thread(
            maya_brain.get_dynamic_context, user_text, active_persona
        )
        if brain_ctx:
            print(f"--> [STREAM BRAIN LISATUD]: {len(brain_ctx)} baiti", flush=True)
            system_prompt = system_prompt + "\n\n" + brain_ctx
    except Exception as be:
        print(f"--> [STREAM BRAIN VIGA]: {be}", flush=True)

    print(f"--> [STREAM ALUSTUS]: Päring='{user_text}', Hääl={chosen_voice}, Pilt={'JAH' if image_bytes else 'EI'}", flush=True)

    if user_text:
        asyncio.create_task(check_reminders_bg(user_text))
    return StreamingResponse(
        streaming_engine.stream_generator(
            user_text,
            system_prompt,
            full_conv,
            chosen_voice,
            core,
            background_learn,
            image_bytes=image_bytes
        ),
        media_type="application/x-ndjson"
    )



# ==========================================================
# INTEGREERITUD VISIOONI OTPUNKT
# ==========================================================
import base64
import requests

def synthesize_mari_tts(text_to_speak: str) -> bytes:
    try:
        clean = re.sub(r"[*#_\[\]`|•]", "", text_to_speak).strip()
        resp = requests.post(
            "https://api.tartunlp.ai/text-to-speech/v2",
            json={"text": clean[:300], "speaker": "mari"},
            timeout=12
        )
        if resp.status_code == 200:
            return resp.content
    except Exception as te:
        print(f"--> [VISION TTS VIGA]: {te}", flush=True)
    return b""

@app.post("/api/vision_check")
async def integrated_vision_check(file: UploadFile = File(...), voice: str = Form("mari"), persona: str = Form("asjalik"), kasutaja: dict = Depends(noua_kasutaja)):
    # MARI TTS TÄIELIKULT EEMALDATUD - Live Maya vastutab kõige eest
    return {"status": "ignored"}


@app.options('/api/reminders')
@app.options('/api/reminders/{rem_id}')
async def options_reminders_handler():
    return JSONResponse(
        content={'ok': True},
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': '*',
        }
    )





if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

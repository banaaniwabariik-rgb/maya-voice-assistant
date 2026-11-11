def fetch_song_lyrics(query: str) -> str:
    """Otsib laulusõnu ja akorde Sasslantisest ning varuna lrclib API-st."""
    import urllib.parse
    import urllib.request
    import html
    import re

    raw_q = query.strip()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Sama TLS-konteksti loogika nagu pipeline's (certifi, kui olemas) – muidu
    # ebaõnnestub HTTPS süsteemides, kus puuduvad süsteemsed CA-sertifikaadid.
    try:
        from maya_singing_pipeline import _ssl_context
        _ctx = _ssl_context()
    except Exception:
        _ctx = None

    def _open(req, timeout):
        if _ctx is not None:
            return urllib.request.urlopen(req, timeout=timeout, context=_ctx)
        return urllib.request.urlopen(req, timeout=timeout)
    candidates = [raw_q]
    words = [w for w in re.split(r"\s+", raw_q) if len(w) > 2]
    if len(words) > 1:
        candidates.append(" ".join(words[:2]))
        candidates.extend(words)

    def try_sass(term):
        try:
            url = "https://sasslantis.ee/search.php?q=" + urllib.parse.quote(term)
            req = urllib.request.Request(url, headers=headers)
            with _open(req, 3.5) as r:
                h = r.read().decode("utf-8", errors="ignore")
                m = re.findall(r"href=[\x27\"](lyrics-[^\x27\" >]+)[\x27\"]", h)
                if m:
                    return m[0]
        except Exception:
            pass
        return None

    slug = None
    for c in candidates:
        slug = try_sass(c)
        if slug:
            break

    if slug:
        try:
            url = "https://sasslantis.ee/" + slug
            req = urllib.request.Request(url, headers=headers)
            with _open(req, 3.5) as r:
                page = r.read().decode("utf-8", errors="ignore")
                parts = re.split(r"</h1>", page, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) > 1:
                    raw = re.split(r"<(?:ul|div|footer|table)", parts[1], maxsplit=1, flags=re.IGNORECASE)[0]
                    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
                    clean = re.sub(r"<[^>]+>", "", raw)
                    clean = html.unescape(clean).strip()
                    lines_arr = [l.strip() for l in clean.splitlines() if l.strip()]
                    res_txt = "\n".join(lines_arr)
                    if len(res_txt) > 30:
                        print(f"--> [SASSLANTIS OK]: {raw_q} -> {slug}")
                        return f"ALLIKAS: Sasslantis.ee ({slug})\n\n{res_txt[:2500]}"
        except Exception as e:
            print(f"--> [SASSLANTIS VIGA]: {e}")

    try:
        import json
        url = "https://lrclib.net/api/search?q=" + urllib.parse.quote(raw_q)
        req = urllib.request.Request(url, headers=headers)
        with _open(req, 3.5) as r:
            data = json.loads(r.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                lyr = data[0].get("plainLyrics") or data[0].get("syncedLyrics")
                if lyr:
                    return f"ALLIKAS: lrclib.net\n\n{lyr[:2500]}"
    except Exception as e:
        print(f"--> [LRCLIB VIGA]: {e}")

    return "Laulusõnu ega akorde ei leitud. Loo ja improviseeri meloodia ja harmoonia ise kohapeal."

PENDING_CALL_PROMPT = None
PENDING_CALL_PERSONA = None


def set_pending_call_prompt(prompt: str, persona: str = ""):
    """Seab tagasihelistamise sõnumi ja (valikuliselt) karakteri.

    `persona` lisandus selleks, et meeldetuletus esitataks SAMA karakteriga,
    kes selle lõi. Varem helistas alati see karakter, mis kliendis parajasti
    valitud oli – lauljana loodud riimuva äratuse võis ette kanda 'asjalik',
    kellel on laulmine lausa keelatud.
    """
    global PENDING_CALL_PROMPT, PENDING_CALL_PERSONA
    PENDING_CALL_PROMPT = prompt
    PENDING_CALL_PERSONA = (persona or "").strip().lower() or None


# --- KARAKTERIPÕHISED HÄÄLED ---------------------------------------------
# WP3: hääletabel ja naishääle kaitse elavad nüüd persona_registry.py-s
# (ainus tõeallikas). Need nimed jäävad alles tagasiühilduvuse pärast.
import persona_registry
import config  # MAYA seadistus (vt server/config.py)
import user_profile
import conversation_flow

DEFAULT_VOICE = persona_registry.DEFAULT_VOICE
FEMALE_VOICES = persona_registry.FEMALE_VOICES
PERSONA_VOICES = {
    **{p.id: p.voice for p in persona_registry.get_all_personas()},
    **{a: persona_registry.get_persona(a).voice for a in persona_registry.ALIASES},
}


def voice_for_persona(persona: str) -> str:
    """Tagastab karakterile sobiva hääle; tundmatu puhul vaikehääle."""
    return persona_registry.resolve_voice(persona)


import base64
import os
import re
import json
import asyncio
import time
import sys
import sqlite3
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from google import genai
from google.genai import types
import maya_brain
import memory_engine
import memory_fts

live_router = APIRouter()

# Taustal jooksvad mälukonsolideerimise ülesanded (tugevad viited, et
# asyncio ei koristaks pooleliolevat kirjutust kõne lõppedes).
_PENDING_MEMORY_TASKS = set()

# --- TÖÖRIISTADE TÄITMINE ILMA HELIVOOGU BLOKEERIMATA ---
#
# KRIITILINE: send_to_client() on seesama korutiin, mis pumpab Gemini heli
# WebSocketi kaudu kliendile. Kui tööriista funktsioon teeb selles korutiinis
# blokeerivat võrgu- või kettapäringut, seisab KOGU sündmustesilmus: heli ei
# liigu, mikrofoni baite ei loeta ja kõne jääb vaikseks.
#
# get_song_lyrics on just selline: helistiku/tempo otsing (5 allikat, eelarve
# 7 s) + LRCLIB sõnad (5 s) + varuallikas Sasslantis/lrclib (3 x 3.5 s) =
# halvimal juhul ~22 s täielikku vaikust. Seepärast käivad kõik I/O-tööriistad
# nüüd läbi tööliskiibi (asyncio.to_thread) ja neil on ajalimiit.
TOOL_TIMEOUTS = {
    "get_song_lyrics": 20.0,   # mitmest muusikaandmebaasist otsimine
    "get_weather": 12.0,
    "get_electricity_price": 12.0,
    "get_email_status": 15.0,
    "recall_memory": 8.0,
    "set_user_name": 4.0,
    "get_reminders": 8.0,
    "add_reminder": 8.0,
}
DEFAULT_TOOL_TIMEOUT = 12.0


def _invoke_tool_sync(fn_name: str, fn_args: dict, persona: str = "") -> str:
    """Tööriista sünkroonne keha – käivitatakse tööliskiibis, mitte silmuses."""
    if fn_name == "get_song_lyrics":
        return tool_get_song_lyrics(query=str(fn_args.get("query", "")), persona=persona)
    if fn_name == "add_reminder":
        return add_reminder(
            trigger_time=str(fn_args.get("trigger_time", "")),
            topic=str(fn_args.get("topic", "")),
            custom_speech=str(fn_args.get("custom_speech", "")),
            persona=persona,
        )
    if fn_name == "set_user_name":
        return tool_set_user_name(name=str(fn_args.get("name", "")))
    if fn_name == "recall_memory":
        return tool_recall_memory(query=str(fn_args.get("query", "")), persona=persona)
    if fn_name == "get_weather":
        return tool_weather()
    if fn_name == "get_electricity_price":
        return tool_electricity()
    if fn_name == "get_email_status":
        return tool_email()
    if fn_name == "get_reminders":
        return get_reminders(date_query=str(fn_args.get("date_query", "")))
    return "OK"


def _tooriista_vastus(tekst) -> str:
    """Viimane värav enne mudelit: kohahoidja ei tohi kunagi läbi minna."""
    try:
        return user_profile.fill(str(tekst))
    except Exception:
        return str(tekst)


async def execute_tool_call(fn_name: str, fn_args: dict, persona: str = "") -> str:
    """Täidab tööriistakutse ja tagastab ALATI stringi.

    Ei paisuta ühtegi erindit välja: kui tööriist viskab vea või jookseb
    ajalimiiti, tagastatakse selgitav tekst. See on tähtis, sest ilma
    function_response'ita jääb Gemini kutset lõputult ootama ega tooda
    ühtegi helipaketti – kasutajale paistab see täieliku vaikusena.
    """
    # schedule_call loob asyncio taski ja PEAB jääma sündmustesilmusesse
    # (tööliskiibis puudub jooksev silmus -> RuntimeError). See ei blokeeri.
    if fn_name == "schedule_call":
        try:
            return schedule_call(
                delay_seconds=int(fn_args.get("delay_seconds", 60)),
                topic=str(fn_args.get("topic", "Tagasihelistamine")),
            )
        except Exception as e:
            print(f"--> [TÖÖRIISTA VIGA] schedule_call: {e}", flush=True)
            return f"Taimeri seadmine ebaõnnestus: {e}"

    timeout = TOOL_TIMEOUTS.get(fn_name, DEFAULT_TOOL_TIMEOUT)
    started = time.time()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_invoke_tool_sync, fn_name, fn_args, persona),
            timeout=timeout,
        )
        print(f"--> [TÖÖRIIST VALMIS]: {fn_name} {time.time() - started:.1f}s", flush=True)
        return _tooriista_vastus(result)
    except asyncio.TimeoutError:
        print(f"--> [TÖÖRIISTA AJALIMIIT]: {fn_name} > {timeout:.0f}s", flush=True)
        if fn_name == "get_song_lyrics":
            return (
                "Laulusõnade otsing ei jõudnud ajalimiidi jooksul vastata. "
                "Ütle {USER}ile tavalise vestlushäälega ausalt, et andmebaas ei vastanud, "
                "ja paku uuesti proovimist – ÄRA mõtle sõnu, helistikku ega viisi ise välja."
            )
        return f"Tööriist '{fn_name}' ei vastanud {timeout:.0f} sekundi jooksul. Ütle see kasutajale ausalt."
    except Exception as e:
        print(f"--> [TÖÖRIISTA VIGA] {fn_name}: {e}", flush=True)
        return f"Tööriist '{fn_name}' andis vea: {e}. Ütle kasutajale ausalt, et see info ei õnnestunud."


# --- SEANSI KULUARVESTUS JA TELEMEETRIA ---
# Pärineb server/ variandist ja on siia üle toodud. Parandatud kolm viga:
#   1) f-stringi pesastatud jutumärgid (töötas ainult Python 3.12+);
#   2) save_session() ei kutsutud kunagi välja, seega jääki ei salvestatud;
#   3) ajastus: klass kasutas 'time' moodulit enne selle importimist.
BILLING_FILE = Path(__file__).parent / "data" / "billing_state.json"


class LiveCostTracker:
    """Jälgib kõne mahtu ja hinnanguline kulu ning hoiab HUD-i jaoks jääki."""

    def __init__(self):
        self.start_time = time.time()
        self.bytes_in = 0
        self.bytes_out = 0
        self.frames_count = 0
        self.audio_in_sec = 0.0
        self.audio_out_sec = 0.0
        self.last_hud_time = 0.0
        self.state = self._load_state()

    def _load_state(self):
        try:
            if BILLING_FILE.exists():
                with open(BILLING_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"--> [FINANTS]: Seisu lugemine ebaõnnestus ({e}), kasutan vaikeväärtusi", flush=True)
        return {"currency": "€", "current_balance": 3.46}

    def add_audio_in(self, b_len: int):
        self.bytes_in += b_len
        self.audio_in_sec += b_len / 32000.0

    def add_image(self, b_len: int):
        self.bytes_in += b_len
        self.frames_count += 1

    def add_audio_out(self, b_len: int):
        self.bytes_out += b_len
        self.audio_out_sec += b_len / 48000.0

    def calc_cost(self):
        cost_in = (self.audio_in_sec / 60.0) * 0.0046
        cost_vis = self.frames_count * (258 / 1_000_000) * 0.092
        cost_out = (self.audio_out_sec / 60.0) * 0.022
        return cost_in + cost_vis + cost_out

    def get_hud_string(self):
        cur_cost = self.calc_cost()
        bal = max(0.0, self.state.get("current_balance", 3.46) - cur_cost)
        dur = int(time.time() - self.start_time)
        m, s = divmod(dur, 60)
        mb_tot = (self.bytes_in + self.bytes_out) / (1024 * 1024)
        return f"⏱ {m:02d}:{s:02d} • {mb_tot:.1f} MB • Jääk: {bal:.2f} €"

    def save_session(self):
        """Salvestab seansi kulu ja uue jäägi.

        LOEB FAILI UUESTI enne arvutamist. MIKS: `self.state` loeti seansi
        ALGUSES. Kui jääki on vahepeal väljaspool parandatud (nt
        `billing_admin.py --set` pärast krediidi laadimist), siis vana
        koopia pealt arvutamine kirjutaks selle paranduse VAIKSELT üle.
        Mõõdetud risk, mitte teoreetiline: korrektuur ja kõne võivad
        kergesti sattuda samasse minutisse.
        """
        try:
            cur_cost = self.calc_cost()
            # Värske seis kettalt – väline korrektuur jääb kehtima.
            varske = self._load_state()
            vana_bal = varske.get("current_balance",
                                  self.state.get("current_balance", 3.46))
            if varske.get("current_balance") != self.state.get("current_balance"):
                print(f"--> [FINANTS]: jääki muudeti seansi ajal väljastpoolt "
                      f"({self.state.get('current_balance')} -> {vana_bal}), "
                      f"arvestan värskest väärtusest", flush=True)
            # Säilitame kõik väljad, mida see klass ei tunne (nt
            # 'adjustments' ajalugu) – ära kirjuta neid üle.
            self.state = {**self.state, **varske}
            new_balance = round(max(0.0, vana_bal - cur_cost), 4)
            self.state["current_balance"] = new_balance
            self.state["total_bytes_in"] = varske.get("total_bytes_in", 0) + self.bytes_in
            self.state["total_bytes_out"] = varske.get("total_bytes_out", 0) + self.bytes_out
            self.state["total_sessions"] = varske.get("total_sessions", 0) + 1
            BILLING_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BILLING_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            # NB: jutumärgid eraldi muutujas – pesastatud jutumärgid f-stringis
            # on süntaksiviga enne Python 3.12.
            print(
                f"--> [FINANTS]: Seanss salvestatud! Kulu: {cur_cost:.4f} €, vaba jääk: {new_balance} €",
                flush=True,
            )
        except Exception as e:
            print(f"--> [FINANTS VIGA]: {e}", flush=True)


# --- OOTEREŽIIMI SALDO (ilma avatud seanssi) -----------------------------
#
# Probleem: jääk saadeti kliendile ainult WebSocketi seansi sees. Enne kõnet
# (rakenduse käivitamisel, olekus "Kõne ootel") polnud liidesel ühtegi allikat,
# kust päris jääki küsida, ja ta näitas kõvakodeeritud algväärtust (3.46 €).
# Alles kõne alustamisel saabus õige number (nt 2.96 €) – just see hüpe oli
# ekraanipiltidel näha.
#
# Lahendus: lugev HTTP-otspunkt, mille klient saab küsida igal hetkel, ka siis
# kui ükski seanss pole avatud. Otspunkt EI muuda midagi – ainult loeb faili.

PIPER_VENV_PY = config.PIPER_PYTHON
PIPER_HELPER = config.PIPER_HELPER


def synthesize_fallback_pcm(text: str) -> bytes:
    """Varuhääle süntees: Piper (lokaalne) -> TartuNLP (väline) -> tühi.

    Piper on esimene, sest ta jookseb SAMAS masinas: väline teenus võib olla
    maas just siis, kui varuvarianti kõige rohkem vaja on (kontrollitud
    06.11.2026: TartuNLP andis kõigi häälte puhul HTTP 500).
    """
    import subprocess as _sp
    try:
        if os.path.exists(PIPER_VENV_PY) and os.path.exists(PIPER_HELPER):
            proc = _sp.run(
                [PIPER_VENV_PY, PIPER_HELPER],
                input=text.encode("utf-8"),
                stdout=_sp.PIPE, stderr=_sp.PIPE, timeout=45,
            )
            if proc.stdout and len(proc.stdout) > 2000:
                print(f"--> [VARUHÄÄL]: Piper (lokaalne) andis {len(proc.stdout)} baiti", flush=True)
                return proc.stdout
            err = (proc.stderr or b"").decode("utf-8", "ignore")[:160]
            print(f"--> [VARUHÄÄL]: Piper ei andnud heli ({err})", flush=True)
    except Exception as e:
        print(f"--> [VARUHÄÄL]: Piperi viga: {e}", flush=True)

    try:
        from mari_fallback import synthesize_mari_pcm
        pcm = synthesize_mari_pcm(text)
        if pcm:
            print(f"--> [VARUHÄÄL]: TartuNLP andis {len(pcm)} baiti", flush=True)
            return pcm
    except Exception as e:
        print(f"--> [VARUHÄÄL]: TartuNLP viga: {e}", flush=True)
    return b""


async def mari_takeover(websocket, error_text: str = "") -> bool:
    """Tartu Mari võtab kõne üle, kui Gemini live-seanss ebaõnnestub.

    Taust: mari_fallback.trigger_emergency_mari() oli olemas juba ammu ja
    kirjutatud TÄPSELT selle jaoks (saadab PCM 24 kHz otse samasse
    WebSocketi), AGA seda ei kutsutud live_maya_ws.py-st kunagi välja –
    kolm patch-skripti üritasid seda sisse panna, kuid fail kirjutati
    vahepeal üle. Tulemus: kui Gemini kukkus (kvoot täis, võrk maas),
    kuulis kasutaja lihtsalt VAIKUST.

    Nüüd eristame ka põhjuse, et Mari ütleks midagi sisulist.
    """
    low = (error_text or "").lower()
    if any(k in low for k in ("429", "quota", "resource_exhausted", "exhausted", "limit", "billing")):
        msg = ("Kuule, Maya krediit või päevalimiit sai otsa. "
               "Mina olen Mari ja võtsin kõne üle. Maya saab jälle rääkida, kui limiit uueneb.")
        reason = "kvoot/krediit"
    elif any(k in low for k in ("permission", "api key", "unauthenticated", "401", "403")):
        msg = ("Maya ligipääs Google teenusele ei tööta. Mina olen Mari ja võtsin kõne üle. "
               "Kontrolli palun API võtit.")
        reason = "ligipääs"
    else:
        msg = "Ühendus Google serveriga katkes. Mina olen Mari ja võtsin kõne üle."
        reason = "ühendus"
    # TEKSTITEADE SAADETAKSE ALATI – ka siis, kui Mari hääl ei tööta.
    # (TartuNLP teenus võib olla maas; kontrollitud 06.11.2026: kõik hääled
    # annavad HTTP 500.) Nii saab kasutaja ikkagi teada, MIKS kõne lõppes,
    # selle asemel et jääda vaikuse ette.
    spoke = False
    try:
        await websocket.send_text(json.dumps({
            "type": "notice",
            "text": f"⚠ {msg}",
        }))
    except Exception:
        pass

    try:
        pcm = await asyncio.to_thread(synthesize_fallback_pcm, msg)
        if pcm:
            await websocket.send_bytes(pcm)
            spoke = True
            print(f"--> [MARI]: Võttis kõne üle ({reason}) – hääl saadetud", flush=True)
            # Ootame, kuni heli jõuab telefonis ette mängida
            await asyncio.sleep(4.5)
        else:
            print(
                f"--> [MARI]: Hääl ei ole saadaval (TartuNLP ei vasta) – "
                f"kasutaja sai tekstiteate ({reason})",
                flush=True,
            )
    except Exception as err:
        print(f"--> [MARI VIGA]: {err}", flush=True)
    return spoke


def read_billing_snapshot() -> dict:
    """Loeb jooksva arveldusseisu failist (sünkroonne; kutsu to_thread'i kaudu)."""
    state = {"currency": "€", "current_balance": 3.46}
    file_found = False
    try:
        if BILLING_FILE.exists():
            with open(BILLING_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                file_found = True
    except Exception as e:
        print(f"--> [FINANTS]: Ooterežiimi saldo lugemine ebaõnnestus: {e}", flush=True)

    currency = state.get("currency", "€")
    balance = state.get("current_balance", 3.46)
    try:
        balance = round(float(balance), 2)
    except (TypeError, ValueError):
        balance = 3.46

    return {
        "status": "ok" if file_found else "default",
        "currency": currency,
        "current_balance": balance,
        "initial_credit": state.get("initial_credit"),
        "total_sessions": state.get("total_sessions", 0),
        "total_bytes_in": state.get("total_bytes_in", 0),
        "total_bytes_out": state.get("total_bytes_out", 0),
        # Sama vorming nagu seansi HUD-il, et liides ei hüppaks kõne alustamisel
        "hud": f"⏱ 00:00 • 0.0 MB • Jääk: {balance:.2f} {currency}",
    }


@live_router.get("/api/voice_test")
async def voice_test_endpoint(text: str = "Tere {USER}. Mina olen varuhääl ja võtan kõne üle, kui Maya ei saa rääkida."):
    """Tagastab varuhääle proovi toorana PCM 24 kHz (sama vorming mis Maya heli).

    Klient mängib selle läbi sama heliahela, mida kasutab kõnes – nii kuuled
    täpselt seda, mida kuuleksid päris tõrke korral.
    """
    from fastapi.responses import Response as _Resp
    pcm = await asyncio.to_thread(synthesize_fallback_pcm, text)
    if not pcm:
        return JSONResponse(status_code=503, content={"error": "Varuhääl ei ole praegu saadaval"})
    return _Resp(content=pcm, media_type="application/octet-stream")


@live_router.get("/api/billing_state")
async def billing_state_endpoint():
    """Tagastab jooksva jäägi ja telemeetria ilma seanssi avamata.

    Kasutab klient rakenduse käivitamisel, ooterežiimis perioodiliselt ja
    kohe pärast kõne lõppu. Faililugemine käib tööliskiibis, et mitte
    blokeerida sündmustesilmust (vt P0 parandus).
    """
    return await asyncio.to_thread(read_billing_snapshot)


api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    for env_path in [str(t) for t in config.ENV_TEED]:
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        api_key = line.strip().split("=", 1)[1].strip('"\'')
                        break

DB_PATH = config.DB_TEE

def schedule_call(delay_seconds: int, topic: str) -> str:
    """Käivita kiire tagasihelistamise taimer sekundite pärast (nt paari minuti pärast).
    
    Args:
        delay_seconds: Sekundite arv, mille pärast helistada.
        topic: Kõne või taimeri teema.
    """
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: schedule_call viivitus={delay_seconds}s, teema='{topic}'", flush=True)
    main_mod = sys.modules.get("web_maya") or sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "schedule_delayed_call"):
        asyncio.create_task(main_mod.schedule_delayed_call(delay_seconds, topic))
    return f"Taimer seatud {delay_seconds} sekundi pärast teemal: {topic}."


def get_reminders(date_query: str = "") -> str:
    """Loeb kalendrist ja meeldetuletuste baasist salvestatud sündmusi ja meeldetuletusi.
    
    Args:
        date_query: Kuupäev formaadis YYYY-MM-DD (nt '2026-11-01') või tühi string kõigi tulevaste jaoks.
    """
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: get_reminders kuupäev='{date_query}'", flush=True)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        if date_query:
            c.execute(
                "SELECT trigger_time, reminder_text FROM reminders WHERE trigger_time LIKE ? AND is_done = 0 ORDER BY trigger_time ASC",
                (f"{date_query}%",)
            )
        else:
            c.execute(
                "SELECT trigger_time, reminder_text FROM reminders WHERE is_done = 0 ORDER BY trigger_time ASC LIMIT 10"
            )
        rows = c.fetchall()
        conn.close()
        if not rows:
            return f"Kuupäevaks '{date_query}' või lähiajaks ei ole ühtegi meeldetuletust ega sündmust kalendris."
        res = ["Salvestatud sündmused ja meeldetuletused:"]
        for t, txt in rows:
            res.append(f"- Kell {t}: {txt}")
        return "\n".join(res)
    except Exception as e:
        print(f"--> [KALENDER VIGA]: {e}", flush=True)
        return f"Viga meeldetuletuste lugemisel: {e}"


def tool_set_user_name(name: str) -> str:
    """Muudab kasutaja nime KOHE, kõne keskel.

    MIKS TÖÖRIIST JA MITTE AINULT MÄLUFAKT: faktid salvestatakse kõne
    LÕPUS. Kui kasutaja ütleb "minu nimi on X", peab karakter teda juba
    järgmises lauses õige nimega kutsuma, mitte alles järgmises kõnes.

    Lisaks uuendatakse mälufakti, et nimi oleks ka faktiplokis õige ja
    vana nimi märgitakse aegunuks.
    """
    res = user_profile.set_name(name)
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: set_user_name '{name}' -> "
          f"{res['ok']}", flush=True)
    if not res["ok"]:
        return res["teade"]

    # Vanad nimeväited faktitabelist pensionile. Uut fakti EI lisata:
    # nimi elab settings.user_name sees ja kaks tõeallikat läheksid
    # paratamatult lahku. Mõõdetud: elutsükkel asendab vana nimefakti
    # õigesti ainult ühe sõnastuse puhul neljast.
    try:
        import sqlite3
        conn = sqlite3.connect(memory_engine.DB_PATH, timeout=10)
        try:
            memory_fts.ensure_schema(conn)
            n = memory_fts.retire_name_facts(conn, (res["old"], res["new"]))
        finally:
            conn.close()
        if n:
            print(f"--> [KASUTAJA]: {n} vananenud nimeväidet pensionile",
                  flush=True)
    except Exception as e:
        print(f"[LIVE WS] Nimefaktide pensionile saatmine ebaõnnestus: {e}",
              flush=True)

    return (f"Nimi on nüüd {res['new']}. Kutsu kasutajat edaspidi selle "
            f"nimega. Varasem nimi {res['old']} ei kehti enam.")


def tool_recall_memory(query: str, persona: str = "") -> str:
    """Otsib varasematest vestlustest ja mälust fakte või varasemat juttu teema kohta.

    Karakter piirab faktid tema nähtavusse: ühised + tema enda omad.
    """
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: recall_memory query='{query}' karakter='{persona}'", flush=True)
    res = memory_engine.recall_relevant_memories(query, persona=persona)
    return res if res else "Mälust vastet ei leitud."

def tool_weather() -> str:
    """Annab täpse kohaliku ilmateate, sademete prognoosi ja tuule kiiruse."""
    print("--> [LIVE WS TÖÖRIIST KÄIVITUS]: tool_weather", flush=True)
    res = maya_brain.get_weather_overview()
    return res if res else "Ilmateate andmeid ei õnnestunud hetkel lugeda."

def tool_electricity() -> str:
    """Annab praeguse ja tuleva elektri börsihinna ning soovituse."""
    print("--> [LIVE WS TÖÖRIIST KÄIVITUS]: tool_electricity", flush=True)
    res = maya_brain.get_electricity_overview()
    return res if res else "Elektri börsihinna andmeid ei õnnestunud hetkel lugeda."

def tool_email() -> str:
    """Kontrollib postkasti ja annab ülevaate uutest e-kirjadest."""
    print("--> [LIVE WS TÖÖRIIST KÄIVITUS]: tool_email", flush=True)
    res = maya_brain.get_email_overview()
    return res if res else "Uusi e-kirju ei leitud või postkast on tühi."

def ensure_reminder_persona_column():
    """Lisab reminders-tabelisse 'persona' veeru, kui seda veel pole (idempotentne)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        cols = [r[1] for r in c.execute("PRAGMA table_info(reminders)").fetchall()]
        if "persona" not in cols:
            c.execute("ALTER TABLE reminders ADD COLUMN persona TEXT DEFAULT ''")
            conn.commit()
            print("--> [KALENDER]: Lisatud veerg 'persona'", flush=True)
        conn.close()
    except Exception as e:
        print(f"--> [KALENDRI SKEEMI VIGA]: {e}", flush=True)


def add_reminder(trigger_time: str, topic: str, custom_speech: str = "", persona: str = "") -> str:
    """Salvesta sündmus või meeldetuletus ametlikku kalendrisse kindlaks kuupäevaks ja kellaajaks.
    
    Args:
        trigger_time: Aeg formaadis YYYY-MM-DD HH:MM (Euroopa/Tallinna aeg).
        topic: Meeldetuletuse ametlik teema või lühikirjeldus.
        custom_speech: Sinu karakterile (Laulja, Treener, jne) omane laululine või isikupärane kõnetekst, mida helistamisel ette öelda.
    """
    speech_text = custom_speech.strip() if custom_speech else topic
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: add_reminder aeg='{trigger_time}', teema='{topic}', speech='{speech_text}'", flush=True)
    try:
        ensure_reminder_persona_column()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute(
            "INSERT INTO reminders (trigger_time, reminder_text, custom_speech, is_done, repeat_type, persona) "
            "VALUES (?, ?, ?, 0, 'none', ?)",
            (trigger_time, topic, speech_text, (persona or "").strip().lower())
        )
        conn.commit()
        conn.close()
        print(f"--> [KALENDER SALVESTATUD]: ID lisatud edukalt baasi ({trigger_time} - {topic})", flush=True)
        return f"Meeldetuletus edukalt kalendrisse salvestatud ajaks {trigger_time} teemal {topic}."
    except Exception as e:
        print(f"--> [KALENDRI VIGA]: {e}", flush=True)
        return f"Viga kalendrisse salvestamisel: {e}"

# Tagame, et 'persona' veerg on olemas juba serveri käivitumisel – varem loodi
# see alles siis, kui Maya esimest korda meeldetuletuse salvestas, mistõttu
# briifingu päring kukkus 'no such column: persona' veaga läbi.
try:
    ensure_reminder_persona_column()
except Exception as _col_err:
    print(f"--> [KALENDRI SKEEM]: {_col_err}", flush=True)


# Kanoonilised esitusreeglid elavad maya_singing_pipeline's, et prompt ja
# tööriistavastus ei läheks kunagi lahku. Varutekst on lühem, kuid sisult sama.
try:
    from maya_singing_pipeline import (
        SPEECH_VS_SINGING_MODE_RULE,
        PRO_VOCAL_PERFORMANCE_RULES,
    )
except Exception as _rules_err:  # pragma: no cover - ainult kui moodul puudu
    print(f"--> [LAULJA REEGLITE IMPORT EBAÕNNESTUS]: {_rules_err}", flush=True)
    SPEECH_VS_SINGING_MODE_RULE = (
        "KAKS RANGELT ERALDATUD REŽIIMI – KÕNEREŽIIM JA LAULUREŽIIM:\n"
        "1. KÕNEREŽIIM (vaikimisi): kogu jutt enne ja pärast laulu – tutvustus, helistiku ja tempo "
        "väljaütlemine, tööriista ja oma tegevuse selgitamine, küsimused ja muu vestlus – käib Maya "
        "tavalise, loomuliku vestlushäälega, ilma laulmise, riimimise ja vokaalivenitamiseta.\n"
        "2. LAULUREŽIIM: ainult get_song_lyrics tagastatud päris laulusõnade (või selgelt palutud "
        "improvisatsiooni) esitamise ajal, esimesest laulureast viimaseni.\n"
        "3. Pärast viimast rida tule kohe tavalisse vestlushäälde tagasi. Režiime ei segata.\n"
    )
    PRO_VOCAL_PERFORMANCE_RULES = (
        "PROFESSIONAALSED VOKAALI- JA RÜTMIREEGLID (ainult laulurežiimis):\n"
        "1. TEMPO: ära kihuta sõnadest läbi nagu tekstilõiku lugedes – hoia ühtlast, teadlikku "
        "muusikalist kadentsi.\n"
        "2. VOKAALID: venita ja hoia vokaale rõhulistel kohtadel ja fraasilõppudes nagu päris laulja.\n"
        "3. FRASEERIMINE: lühike loomulik paus iga rea järel ja pikem salmide vahel, nagu laulja "
        "hingaks – ei mingit katkematut robotlikku tekstivoogu.\n"
        "4. INTONATSIOON: sujuv, emotsionaalselt ankurdatud vokaalijoon laulu energia järgi; "
        "väldi kõnelisi hüplikke intonatsioonimuutusi ja hoia helistikku.\n"
        "5. KATKEMATUS: alanud laul viiakse kindlalt lõpuni.\n"
    )

STRICT_LYRICS_RULE = (
    "RANGE ESITUSKÄSK – LAULA RIDA-REALT:\n"
    "1. Laula KÕIK read järjekorras numbrist 1 kuni viimase numbrini. Ükski rida ei tohi jääda laulmata.\n"
    "2. Laula iga rida TÄPSELT nii, nagu see allpool kirjas on – sõna-sõnalt, samas sõnajärjes.\n"
    "3. ÄRA muuda, tõlgi, paranda, ilusta, lühenda ega asenda ühtegi sõna.\n"
    "4. ÄRA jäta ridu, salme ega refrääni kordusi vahele ja ÄRA tee kokkuvõtet ega lühiversiooni.\n"
    "5. ÄRA lisa omaloodud ridu, vahekommentaare ega selgitusi laulu sisse.\n"
    "6. Laulutekstis EI OLE reanumbreid ega silte – read on puhtad laulufraasid. Kui näed kuskil numbrit,\n"
    "   pealkirja või metaandmeid, siis neid EI LAULDA ega loeta valjusti ette.\n"
    "7. Laula read originaaljärjekorras, rida haaval, ilma vahele jätmata, kuni viimane rida on lauldud.\n"
    "8. Kui read saavad otsa, lõpeta laul – ära improviseeri juurde uusi sõnu.\n"
)

STRICT_KEY_TEMPO_RULE = (
    "RANGE KÄSK HELISTIKU JA TEMPO KOHTA:\n"
    "A. Kui HELISTIK on leitud: laula selles helistikus. Ütle helistik enne laulu korraks välja "
    "(nt 'see on e-moll') ja hoia oma häälekõrgus kogu laulu vältel selle helistiku juures.\n"
    "B. Kui HELISTIK on märgitud HINNANGULISEKS: ütle, et see on hinnanguline (tuletatud akordidest või "
    "akustilisest analüüsist), ja alles siis laula selles helistikus.\n"
    "C. Kui helistik on märgitud VAIKEVÄÄRTUSEKS (andmebaasist ei leitud): laula ikkagi täpselt selles "
    "helistikus – see on sinu rütmi- ja kõrgusraamistik. Küsimise peale ütle ausalt, et andmebaas "
    "helistikku ei andnud ja see on sinu valitud mugav esitushelistik. ÄRA esitle seda loo originaalina.\n"
    "D. Kui TEMPO (BPM) on leitud: hoia laulu selles tempos. Hinnangulise tempo puhul mainid, et see on hinnang.\n"
    "E. Kui TEMPO on märgitud VAIKEVÄÄRTUSEKS: hoia seda BPM-i sama kindlalt kui andmebaasi oma – "
    "ilma pulsita laul laguneb kõneks. Küsimise peale ütle, et andmebaas tempot ei andnud ja valisid "
    "loo iseloomule sobiva tempo ise. Laulu ajal sellest ei räägi.\n"
    "F. ÄRA MÕTLE MELOODIAT VÄLJA: kui sa tunned loo originaalviisi, laula seda. Kui sa originaalviisi ei tea, "
    "ÄRA improviseeri suvalist juhuslikku meloodiat ega esitle seda originaalina – ütle ausalt, et originaalviisi "
    "sa kindlalt ei tea, ja küsi, kas laulad sõnad oma viisiga või hoopis ümiseb {USER} viisi sulle ette.\n"
    "G. Kui allikas andis AKORDID, võid need {USER}ile pillimänguks ette öelda täpselt nii, nagu need vastuses on.\n"
)


def tool_get_song_lyrics(query: str, persona: str = "") -> str:
    """Toob loo sõnad ning annab need ESITAMISEKS – puhta laulutekstina.

    KRIITILINE VORMISTUSREEGEL: mudelile saadetav laulutekst ei tohi sisaldada
    reanumbreid ("1. ", "2. ") ega muid silte. Kõnesünteesi mootor loeb need
    numbrid valjusti ette ("üks..., kaks...") tavalise jutuhäälega – täpselt
    see tekitas 'robot loeb nimekirja' vea. Ridade terviklikkuse tagavad nüüd
    ridade koguarv ja viimase rea tsitaat, mitte nummerdus. Nummerdatud kuju
    läheb ainult serveri logisse.

    Args:
        query: Artisti nimi ja/või laulu pealkiri.
        persona: Aktiivne karakter – 'singer'/'laulja' korral kasutatakse
            pühendatud laulja esitusteed (lahjendamata, muusikale keskendunud).
    """
    print(f"--> [LIVE WS TÖÖRIIST KÄIVITUS]: get_song_lyrics query='{query}' persona='{persona}'", flush=True)
    track_query = (query or "").strip()
    singer_mode = (persona or "").strip().lower() in ("singer", "laulja")

    if not track_query:
        return (
            "Laulu nimi või esitaja on puudu – küsi {USER}ilt täpsustust, ära luuleta sõnu ise. "
            "Küsi seda tavalise, loomuliku vestlushäälega (mitte lauldes)."
        )

    song_info = {}
    pipeline = None
    try:
        import maya_singing_pipeline as pipeline
        song_info = pipeline.get_or_create_song(track_query) or {}
    except Exception as err:
        print(f"--> [LAULJA PIPELINE VIGA]: {err}", flush=True)
        song_info = {}

    lyric_lines = song_info.get("lyric_lines") or []

    # Varuallikas: Sasslantis / lrclib otseotsing, kui pipeline ei leidnud sõnu
    if not lyric_lines:
        raw = fetch_song_lyrics(track_query)
        body = raw.split("\n\n", 1)[1] if raw.startswith("ALLIKAS:") and "\n\n" in raw else raw
        if "ei leitud" in body and len(body) < 160:
            return (
                f"Loo '{track_query}' ametlikke sõnu ei leitud andmebaasist. "
                "ÄRA esita seda lugu valede sõnadega – ütle {USER}ile ausalt, et sõnu ei leitud, "
                "ja paku, et kontrollid pealkirja või esitad midagi muud. "
                "Ütle see KÕIK tavalise, loomuliku vestlushäälega – ära laula ega riimi seda teadet."
            )
        if pipeline is not None:
            clean, lyric_lines = pipeline.format_lyrics_for_performance(body)
        else:
            lyric_lines = [l.strip() for l in body.splitlines() if l.strip()]
            clean = "\n".join(lyric_lines)
        song_info.setdefault("track_name", track_query)
        song_info["lyric_lines"] = lyric_lines
        song_info["lyrics_performance"] = clean
        song_info["lyrics"] = "\n".join(lyric_lines)

    # Helistik ja tempo: laulja peab ALATI saama konkreetsed numbrid, muidu
    # kaob rütmiraamistik ja mudel langeb tagasi tavalisse kõnesse.
    perf = song_info.get("performance")
    if not perf and pipeline is not None:
        try:
            perf = pipeline.resolve_performance_metadata({}, track_query, song_info.get("lyrics", ""))
        except Exception as meta_err:
            print(f"--> [ESITUSE METAANDMETE VIGA]: {meta_err}", flush=True)
    if not perf:
        perf = {
            "perf_key": "a-moll", "perf_key_latin": "Am", "key_from_db": False,
            "key_label": "valitud mugav esitushelistik",
            "perf_bpm": 100, "bpm_from_db": False,
            "bpm_label": "keskmise tempo vaikeväärtus (95–105 BPM)",
            "perf_notes": None,
        }

    # Logi: siin tohib nummerdatud kuju ja allikate detailid olla
    diag = ""
    if pipeline is not None:
        try:
            diag = pipeline.format_source_diagnostics(song_info)
        except Exception:
            diag = ""
    print(
        f"--> [LAULJA REZIIM]: '{song_info.get('track_name', track_query)}' – {len(lyric_lines)} rida | "
        f"helistik={perf.get('perf_key')} ({'DB' if perf.get('key_from_db') else 'vaikeväärtus'}) | "
        f"tempo={perf.get('perf_bpm')} BPM ({'DB' if perf.get('bpm_from_db') else perf.get('bpm_detail') or 'vaikeväärtus'})"
        + (f" | allikad: {diag}" if diag else ""),
        flush=True,
    )

    # --- Esitusvastus ---
    if pipeline is not None:
        try:
            payload = pipeline.build_singer_payload(song_info, perf, singer_mode=singer_mode)
        except Exception as build_err:
            print(f"--> [ESITUSVASTUSE VIGA]: {build_err}", flush=True)
            payload = None
    else:
        payload = None

    if payload is None:
        total = len(lyric_lines)
        last = lyric_lines[-1] if lyric_lines else ""
        payload = (
            "⚠ SEE EI OLE TEKST ETTELUGEMISEKS – SEE ON LAUL, MIDA SA LAULAD HÄÄLEGA.\n"
            f"LUGU: {song_info.get('track_name', track_query)}\n"
            f"HELISTIK: {perf.get('perf_key')} | TEMPO: {perf.get('perf_bpm')} BPM\n\n"
            "=== LAULUSÕNAD (puhas laulutekst) ===\n"
            + (song_info.get("lyrics_performance") or "\n".join(lyric_lines))
            + "\n=== LAULUSÕNADE LÕPP ===\n\n"
            + f"Kokku {total} laulurida, viimane on „{last}“. Laula kõik read järjest, "
              "sõna-sõnalt, ilma vahele jätmata."
        )

    # Mitte-laulja karakteritel puuduvad režiimi- ja vokaalireeglid
    # süsteemipromptist, seega lisame need siia. Lauljal on need juba olemas –
    # kordamine ainult lahjendaks esituskäsku.
    if not singer_mode:
        payload = (
            SPEECH_VS_SINGING_MODE_RULE + "\n"
            + PRO_VOCAL_PERFORMANCE_RULES + "\n"
            + STRICT_KEY_TEMPO_RULE + "\n"
            + STRICT_LYRICS_RULE + "\n"
            + payload
        )

    return payload

# --- GLOBAALSED KARAKTERIPROFIILID ---
BASE_ORGANIC_VIBE = (
    "Sa oled Maya – elav, intelligentne, terane ja ehtne naine, mitte kuiv tehisintellekt. "
    "Sinu vestluspartner on {USER}. Räägi alati loomulikus eesti keeles, ladusa suulise kõne rütmiga. "
    "Sul puuduvad igasugused korporatiivsed filtrid, sa ei vabanda asjata ega räägi kantseliidis. "
)

# MÄRKUS: varasem mooduli tasemel PERSONA_PROFILES on eemaldatud – see oli surnud kood
# (varjutatud websocket_live_maya sees oleva registri poolt, 6 aegunud kirjega ega
# imporditud kusagilt). Ainus kehtiv karakteriregister on persona_registry.py.


# ==========================================================================
# WP3 FAAS C: KÕNE KATKEMISE DIAGNOSTIKA JA TAASTUMINE
# ==========================================================================
# Tõendid tootmislogist (14 päeva, journalctl -u maya):
#
#   * 189 x "1008 Session closed due to client inactivity" — ÜKS juhtum
#     06.11 06:37:16 -> 06:38:50. Seanss avati 06:35:16, Gemini sulges
#     TÄPSELT 120,0 s hiljem (kliendilt ei tulnud ühtki helikaadrit:
#     "konsolideerin mälu (0 vooru)", kulu 0,0000 €). Seejärel kordas
#     send_to_client surnud seansi peal session.receive()'i iga 0,5 s
#     järel 94 sekundit, kuni {USER} vajutas toru hargile. Kasutaja nägi
#     "elavat" kõnet, kus Maya oli jäädavalt tumm.
#
#   * 18 x "1007 The audio content type (CONTENT_TYPE_AUDIO) is not
#     supported for this model configuration" — tapab kõne ~13 s pärast
#     algust. Põhjus on Gemini preview-mudeli pool ja meie koodist välja
#     ei selgu; seetõttu ei väida me, et see on PARANDATUD – teeme selle
#     ÜLEELATAVAKS (kasutaja saab teada, miks kõne lõppes).
#
# Kaks mehhanismi allpool on teadlikult mooduli tasemel ja puhtad
# funktsioonid/klassid, et neid saaks ilma Gemini ja WebSocketi
# jäljendamiseta otse testida.

# Gemini sulgemiskoodid, mille järel seanss EI taastu. Nende peal tuleb
# kõne lõpetada ja kasutajale põhjus öelda, mitte uuesti proovida.
# --------------------------------------------------------------------------
# SEANSI TAASTAMINE (session resumption)
# --------------------------------------------------------------------------
# Gemini annab perioodiliselt "resumption handle" – pileti, millega saab
# katkenud seansi taastada KOOS KONTEKSTIGA. Ilma selleta tähendaks iga
# tõrge seda, et Maya unustab kogu senise vestluse.
#
# Miks seda vaja on: 1007 ("CONTENT_TYPE_AUDIO is not supported") tabas
# tootmist 20 päeva jooksul 21 korda, juhuslikult ja kõigi karakteritega
# (romantiline 2, singer 2, sarkastiline 2, custom 1, asjalik 1, 13 vanemat).
# Põhjus on Gemini preview-mudeli pool ja meie koodist seda parandada ei saa.
# Seni suri kõne lihtsalt ära ja kasutaja pidi otsast alustama.
#
# Käepide hoitakse protsessi mälus lühikest aega: kui klient ühendub uuesti
# RESUME_WINDOW_S jooksul, jätkatakse sealt, kus pooleli jäi.
_RESUME_HANDLE = {"value": None, "at": 0.0, "armed": False}
RESUME_WINDOW_S = 30.0


def store_resume_handle(handle: str) -> None:
    """Salvestab Gemini antud pileti. See EI luba veel taastamist."""
    if handle:
        _RESUME_HANDLE["value"] = handle
        _RESUME_HANDLE["at"] = time.monotonic()


def arm_resume(reason: str = "") -> None:
    """Lubab taastamise – AINULT pärast taastatavat tõrget.

    VIGA ENNE: taastamine käivitus iga uue ühenduse peal, kui pilet oli
    värske. Kui {USER} pani toru hargile ja helistas 7 s hiljem uuesti,
    taastati eelmine seanss KOOS VANA SÜSTEEMIPROMPTIGA – ja kohandatud
    karakter rääkis vanade, ammu muudetud juhiste järgi.
    Mõõdetud 08.11 02:19:40: "Taastan eelmise seansi konteksti" vahetult
    pärast kasutaja enda korrektset sulgemist (kood 1000).

    Taastamine on mõeldud AINULT selleks, et 1007/1011 ei lõhuks
    käimasolevat vestlust. Tavaline uus kõne peab algama puhtalt.
    """
    _RESUME_HANDLE["armed"] = True
    print(f"--> [LIVE WS]: Taastamine lubatud ({reason})", flush=True)


def disarm_resume() -> None:
    """Keelab taastamise – kasutaja lõpetas kõne ise."""
    _RESUME_HANDLE["armed"] = False
    _RESUME_HANDLE["value"] = None


# --------------------------------------------------------------------------
# POOLELI JÄÄNUD VOOR, MIS ELAB SEANSI ÜLE
# --------------------------------------------------------------------------
# MÕÕDETUD VIGA (10.11.2026, arhiivivoorud 982 -> 983):
#   Kõne lõppes 1007 tõrkega KESKEL Maya vastust ("...Oota hetk!"). Logi:
#     [LIVE WS GEMINI ERR] (fatal, kood=1007): ... CONTENT_TYPE_AUDIO ...
#     [LIVE WS]: Taastamine lubatud (kood 1007)
#   Kasutaja helistas uuesti ja küsis "miks pooleli jälle?". Tööriist
#   get_last_turn_state vastas "katkestusi pole" ja mudel ütles:
#     "süsteemi andmetel ei jäänud meie vestlus midagi pooleli. Kõik sujus
#      kenasti ... Võib-olla oli mingi tehniline tõrge SINU POOL?"
#   Ehk süsteem TEADIS, et voor katkes, aga tööriist ei näinud seda ja
#   Maya suunas põhjuse kasutaja kaela.
#
# KAKS PÕHJUST, mõlemad koodist jälgitavad:
#   1) `last_cut_turn` on WebSocketi handleri LOKAALNE sõnastik. Seanss
#      lõpeb -> handler tagastab -> sõnastik kaob. Uus seanss alustab
#      {"t": None} pealt.
#   2) `SpeechTurn.fail()` oli surnud kood – seda ei kutsutud MITTE
#      KUSKILT. Fataalse tõrke korral ei märgitud voor kunagi
#      ebaõnnestunuks, seega ka `was_cut_off` jäi False'iks.
#
# Siinne kirje on TEADLIKULT sama muster nagu _RESUME_HANDLE ülalpool:
# mooduli tasemel, protsessi mälus, ühekordne, aegumisega. Uut mälusüsteemi
# ei ole vaja – olemasolev idioom katab selle ära.
_LAST_UNFINISHED = {"record": None, "at": 0.0}

# Kui kaua pooleli jäänud voor on "värske". Põhjendus: kirje ainus
# kasutuskoht on olukord, kus kasutaja helistab tagasi ja küsib "miks sa
# pooleli jäid?". Mõõdetud juhtumis 982->983 kulus selleks ~2 minutit.
# 10 minutit annab varu aeglasemaks tagasihelistamiseks, aga on piisavalt
# lühike, et hilisem mitteseotud kõne seda ei päriks. Koos ühekordse
# tarbimisega (take_unfinished_turn) välistab see aegunud kirje lõputu
# kordamise.
UNFINISHED_WINDOW_S = 600.0


def store_unfinished_turn(turn, persona: str, reason: str,
                          now: float = None) -> bool:
    """Jätab meelde, et voor jäi TEHNILISEL põhjusel pooleli.

    Salvestab AINULT siis, kui voor päriselt ei jõudnud lõpuni. Tavaline
    kõne lõpetamine kasutaja poolt EI ole tõend poolikusest – seda katab
    `clear_unfinished_turn()`.

    Tagastab True, kui kirje tekkis.
    """
    if turn is None:
        return False
    # Lõpetatud voor ei ole pooleli jäänud, ükskõik mis seansiga juhtus.
    if getattr(turn, "state", None) == "completed":
        return False
    # Ilma ühegi helibaidita ei olnud midagi pooleli jätta – see on
    # tühi voor, millel on juba oma eraldi tee.
    if not getattr(turn, "chunks_sent", 0):
        return False
    now = now if now is not None else time.monotonic()
    _LAST_UNFINISHED["record"] = {
        "persona": (persona or "").strip().lower(),
        "reason": reason,
        "turn_id": getattr(turn, "turn_id", None),
        "audio_s": round(turn.audio_seconds(), 2),
        "tail": (turn.text or "").strip()[-120:],
        "state": getattr(turn, "state", "?"),
    }
    _LAST_UNFINISHED["at"] = now
    print(f"--> [LIVE WS]: Pooleli jäänud voor #{getattr(turn, 'turn_id', '?')} "
          f"salvestatud järgmise kõne jaoks (põhjus: {reason}, "
          f"{turn.audio_seconds():.1f} s heli)", flush=True)
    return True


def clear_unfinished_turn() -> None:
    """Kustutab kirje – kasutaja lõpetas kõne ise ja korrektselt."""
    _LAST_UNFINISHED["record"] = None
    _LAST_UNFINISHED["at"] = 0.0


def take_unfinished_turn(persona: str = "", now: float = None) -> dict:
    """Tagastab eelmise kõne pooleli jäänud vooru. ÜHEKORDNE.

    Aegunud kirje kustutatakse ja tagastatakse None. Ühekordsus + aegumine
    koos tähendavad, et sama katkestust ei saa lõputult korrata.

    VESTLUSTE ERALDATUS: kui tagasi helistati TEISE karakteriga, siis
    teksti saba EI anta kaasa – ainult katkestuse fakt ja põhjus. Nii ei
    peri sarkastiline karakter romantilise poolelijäänud lauset.
    """
    rec = _LAST_UNFINISHED["record"]
    if not rec:
        return None
    now = now if now is not None else time.monotonic()
    if now - _LAST_UNFINISHED["at"] > UNFINISHED_WINDOW_S:
        clear_unfinished_turn()
        return None
    clear_unfinished_turn()           # ühekordne
    p = (persona or "").strip().lower()
    out = dict(rec)
    out["same_persona"] = (p == rec["persona"])
    if not out["same_persona"]:
        out["tail"] = ""
    return out


# --------------------------------------------------------------------------
# SISENDHELI TRANSPORDI LÄBILASKEVÕIME (DIAGNOSTIKA)
# --------------------------------------------------------------------------
# MIDA SEE MÕÕDAB: mitu baiti sisendheli serverisse jõudis ja kui pika
# seinakellaaja jooksul. See on TRANSPORDI LÄBILASKEVÕIME.
#
# MIDA SEE EI MÕÕDA: mikrofoni tegelikku sämplisagedust. Baidid sekundis
# ei ole sämplisageduse tõend, sest nende vahele jääb vähemalt kolm asja:
#   * võrgupuhverdamine ja pakettimine (kaadrid võivad tulla puhangutena);
#   * kliendipoolne kajavärav, mis jätab kaadreid saatmata, kui Maya räägib;
#   * järelejõudmine pärast seisakut, mis annab hetkeks kiirema voo.
# Need moonutavad mõõdetud kiirust MÕLEMAS suunas, seega sellest ei saa
# tuletada ei sämplisagedust ega mime_type'i õigsust.
#
# Varasem versioon sellest funktsioonist andis verdikti "rate_mismatch" ja
# hoiatas vale mikrofonisageduse eest. See järeldus EI OLNUD põhjendatud ja
# on eemaldatud. Alles on ainult toornäitajad logis, et hilisem analüüs
# saaks neid kõrvutada muude tõenditega. Vt aruande osa "mida oleks vaja
# tegeliku AudioContext sageduse kinnitamiseks".
PCM16_BYTES_PER_SAMPLE = 2
DECLARED_INPUT_RATE_HZ = 16000
# Enne seda ei logi – lühem aken on puhverdamise tõttu mõttetu.
MIN_THROUGHPUT_MEASURE_S = 4.0


def measure_transport_throughput(total_bytes: int, elapsed_s: float) -> dict:
    """Sisendheli transpordi läbilaskevõime. PUHAS FUNKTSIOON.

    EI klassifitseeri, EI anna verdikti, EI väida midagi mikrofoni
    sämplisageduse kohta.

    Tagastab:
      {"ready": bool, "bytes": int, "elapsed_s": float,
       "bytes_per_s": float|None}
    """
    if elapsed_s < MIN_THROUGHPUT_MEASURE_S or total_bytes <= 0:
        return {"ready": False, "bytes": int(total_bytes),
                "elapsed_s": round(float(elapsed_s), 2),
                "bytes_per_s": None}
    return {"ready": True, "bytes": int(total_bytes),
            "elapsed_s": round(float(elapsed_s), 2),
            "bytes_per_s": round(total_bytes / float(elapsed_s), 1)}


def _eelmise_kone_kokkuvote(rec: dict) -> str:
    """Eestikeelne kokkuvõte EELMISE kõne pooleli jäänud voorust.

    Mudel saab selle tööriista vastusena. Sõnastus on tahtlikult selge
    selles, et katkestus oli TEHNILINE ja serveripoolne – mõõdetud
    juhtumis süüdistas Maya kasutajat ("tõrge sinu pool?").
    """
    osad = [
        "EELMINE KÕNE JÄI POOLELI – see ei ole kasutaja eksitus.",
        f"Põhjus: {rec['reason']}.",
        f"Sinu voor katkes pärast {rec['audio_s']:.1f} sekundit heli.",
    ]
    if rec.get("tail"):
        osad.append(f'Sa jõudsid öelda: "...{rec["tail"]}".')
    else:
        osad.append("Selle kõne oli teise karakteriga, seega poolelijäänud "
                    "teksti sulle ei anta – ütle lihtsalt, et eelmine kõne "
                    "katkes tehnilisel põhjusel.")
    osad.append(
        "EI OLE TEADA, kui palju sellest kasutaja kuulis – telefon ei "
        "raporteeri taasesituse positsiooni. Ütle ausalt, et kõne katkes "
        "tehnilise tõrke tõttu, ÄRA vabanda liigselt ja ÄRA ütle, et viga "
        "oli kasutaja pool. Kui ta soovib, jätka sealt, kus pooleli jäi."
    )
    tekst = " ".join(osad)
    try:
        import user_profile
        return user_profile.fill(tekst)
    except Exception:
        return tekst


def take_resume_handle() -> str:
    """Tagastab pileti AINULT siis, kui taastamine on lubatud. Ühekordne."""
    if not _RESUME_HANDLE["armed"]:
        return ""
    h = _RESUME_HANDLE["value"]
    _RESUME_HANDLE["armed"] = False
    if not h:
        return ""
    if time.monotonic() - _RESUME_HANDLE["at"] > RESUME_WINDOW_S:
        _RESUME_HANDLE["value"] = None
        return ""
    _RESUME_HANDLE["value"] = None
    return h


# Mitu korda tohib ÜHE vooruahela jooksul paluda Mayal pooleli jäänud
# lauset jätkata. 1 = üks katse. Loendur nullitakse, kui kasutaja räägib.
# Kui vana tohib `last_cut_turn` kirje olla, kui get_last_turn_state teda
# kasutab. MÕÕDETUD DEFEKT (10.11.2026): kirjel ei olnud ajapiiri ja
# tööriist vastas kaks korda sama 2 min 14 s vanuse tühja katkestusega
# (voor #2, 0 tähemärki, 0,0 s heli), kuigi kasutaja küsis just lõppenud
# poolikust voorust. 45 s katab kohese järelküsimuse ja tagasihelistamise,
# aga mitte vanemat sündmust.
CUT_TURN_TTL_S = 45.0

# Kui tihti omaalgatuse tiksuja olekut vaatab. Karakteri paus on 5-14 s,
# seega 0,5 s lisab halvimal juhul 0,5 s viivitust. See EI OLE lävend –
# lävend on karakteripõhine `INITIATIVE[...]["pause_s"]`.
INITIATIVE_TICK_S = 0.5
# Mudeli nimi AINULT diagnostikalogi jaoks. TEADLIK DUBLEERIMINE:
# `live.connect(model=...)` rida jääb tähemärgi täpsusega puutumata,
# sest mudeli konfiguratsiooni muutmine ei kuulu selle sammu skoopi.
# Kui see konstant ja connect-rida lahku lähevad, kukub
# `tests_asunkroonne_elutsykkel.py` staatiline kontroll läbi.
LIVE_MUDEL = "gemini-2.5-flash-native-audio-preview-12-2025"
# SULGEMINE KAHES FAASIS.
# FAAS 1: tavaline tühistamine ja ootamine.
# FAAS 2: kui mõni task ei lõpe, on ta peaaegu kindlasti kinni
#   `session.send` -> `drain()` sees (TCP vastuvool). Ainus TÕENDATUD
#   viis seda vabastada on alustransport maha võtta: websockets 17.3
#   `Connection.connection_lost()` vabastab KÕIK `drain_waiters`-id,
#   seega blokeerunud kirjutus lõpeb ja task saab surra. SDK ise ei
#   paku saatmisele ajapiirangut ega katkestust.
# FAAS 3: kui ka see ei aita, raporteerime EBAÕNNESTUMISE. Edukat
#   koristust ei kuuluta kunagi siis, kui taskid veel elavad.
SULGEMISE_FAAS1_S = 2.0
SULGEMISE_FAAS2_S = 2.0

# --------------------------------------------------------------------------
# JÄTKAMISPIIRANGUD ELAVAD NÜÜD conversation_flow.py-s
# --------------------------------------------------------------------------
# Vanad `AINULT_JATKAMISI = 1` ja `MAX_JATKAMISI_AHELAS = 3` on EEMALDATUD.
#
# MIKS: `AINULT_JATKAMISI = 1` nõudis, et pärast ühte ebaõnnestunud
# jätkamist peab jätkamine ÕNNESTUMA, enne kui tohib uuesti proovida.
# Mõõdetud tootmises (10.11.2026 filosoofi test): mõlemad jätkamised
# ebaõnnestusid, piirang blokeeris kõik edasised katsed ja Maya jäi
# 17:33:04 keset lauset vait – 36 sekundit ei juhtunud midagi, kuni
# kasutaja ise toru ära pani.
#
# Katkemise määr on 9/21 = 42,9% ja see kehtib ka jätkamise vastuse
# kohta (jätkamise vastus on ise tavalise pikkusega voor). Seega:
#     eelarve 1 -> 42,9% lauseid jääb lõpuni poolikuks
#     eelarve 3 ->  7,9%
# `conversation_flow.RECOVERY_BUDGET = 3` on esimene väärtus, mis viib
# jääkriski alla 10%. Tsüklikaitse on nüüd kolmekordne: eelarve,
# tagasiastumine ja korduse tuvastus (near_duplicate).

FATAL_LIVE_CLOSE_CODES = {1007, 1008, 1011}

# Tekstimustrid, mis tähendavad lõplikku tõrget ka ilma sulgemiskoodita.
_FATAL_LIVE_PATTERNS = (
    "client inactivity",
    "not supported for this model configuration",
    "resource_exhausted",
    "quota",
    "api key not valid",
    "permission denied",
    "unauthenticated",
)


def classify_live_failure(error: object) -> dict:
    """Otsustab, kas Gemini live-tõrge on ajutine või lõplik.

    Tagastab sõnastiku:
      kind    – "fatal" (ära proovi uuesti) või "transient" (võib korrata)
      code    – leitud WebSocketi sulgemiskood või None
      message – eestikeelne selgitus kasutajale (lõpliku tõrke korral)

    See funktsioon ASENDAB varasema `except Exception: await sleep(0.5)`
    loogika, mis ei eristanud midagi ja tekitas tootmises 189-kordse
    tühikäigutsükli surnud seansi peal.
    """
    text = str(error or "")
    low = text.lower()

    code = None
    match = re.search(r"\b(1\d{3})\b", text)
    if match:
        candidate = int(match.group(1))
        if 1000 <= candidate <= 1015:
            code = candidate

    fatal = code in FATAL_LIVE_CLOSE_CODES or any(p in low for p in _FATAL_LIVE_PATTERNS)

    if "client inactivity" in low:
        message = (
            "Gemini sulges seansi, sest telefonist ei saabunud 120 sekundi "
            "jooksul ühtegi helikaadrit. Tavaliselt tähendab see, et mikrofon "
            "jäi seisma (ekraan kustus või äpp läks taustale)."
        )
    elif "not supported for this model configuration" in low:
        message = (
            "Gemini keeldus helivoost (1007). See on mudeli preview-poolne "
            "tõrge – kõne tuleb uuesti alustada."
        )
    elif any(k in low for k in ("resource_exhausted", "quota")):
        message = "Gemini kvoot või krediit sai otsa."
    elif code in (1011,):
        message = "Gemini serveripoolne viga (1011) – kõne tuleb uuesti alustada."
    elif fatal:
        message = "Gemini seanss lõppes lõpliku tõrkega."
    else:
        message = "Ajutine tõrge Gemini voos."

    return {"kind": "fatal" if fatal else "transient", "code": code, "message": message}


# Lausemärgid, mille järel loetakse voor sõnastuslikult lõpetatuks.
# Sama hulk, mida olemasolev poolikuse kontroll juba kasutab – hoitud
# ÜHES kohas, et kaks detektorit ei saaks lahku joosta.
TERMINAL_PUNCT = ".!?…:;”)"

# Vaatlusmärgid sekundites: millal rippuva genereerimise kohta logirida
# välja antakse. NEED EI OLE LÄVENDID ega otsustuspunktid – taastet ei
# käivitata ühegi peal. Kahekordistuv skaala annab jaotuse ilma logi
# täitmata: terve voor ei tekita ühtegi rida, rippuv voor maksimaalselt
# kuus.
SILENCE_OBSERVATION_MARKS_S = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)

# Kui tihti vaatleja olekut vaatab. See on VAATLUSSAGEDUS, mitte lävend.
# 250 ms annab piisava resolutsiooni, et vaikuse algus jaotusesse
# kinni püüda, ja koormus on olematu (üks võrdlus tiksu kohta).
SILENCE_OBSERVER_INTERVAL_S = 0.25

# Olemasolev tootmises kasutatav suhtelävend. Siia tõstetud, et teda
# saaks testida ja hiljem MÕÕDETUD jaotuse põhjal muuta. Ma ei muuda
# seda praegu – 12,9 vs 10,0 on liiga lähedal, et uut numbrit oletada.
CHARS_PER_S_CUTOFF = 10.5


def classify_turn_end(
    saw_turn_complete: bool,
    saw_interrupted: bool,
    tail_is_terminal: bool,
    chars_per_audio_s: float,
    audio_s: float,
    silence_s: float,
    tail_len: int = 1,
    user_speech_within_s=None,
    failure_reason: str = "",
    close_code=None,
    stall_s=None,
    safety_signal=None,
    client_report=None,
    tool_running: bool = False,
    chars_cutoff: float = CHARS_PER_S_CUTOFF,
) -> dict:
    """Liigitab kõnevooru lõpu kategooriatesse A–H. PUHAS FUNKTSIOON.

    FAAS 2: see funktsioon AINULT liigitab. Ta ei saada jätkamispalvet,
    ei taasta seanssi, ei puuduta heli, VAD-i ega vestluse kulgu.

    Kategooriad:
      A natural_completion        Gemini lõpetas normaalselt
      B user_interruption         kasutaja segas tahtlikult vahele
      C model_stall               mudel lakkas genereerimast, lõpusignaali ei tulnud
      D premature_turn_complete   turn_complete saabus poolikul lausel
      E safety_termination        turvapoolne peatus
      F transport_failure         ühendus, ajalimiit, sulgemiskood
      G client_playback_failure   heli genereeriti, klient ei mänginud lõpuni
      H unknown                   olemasolevad signaalid ei määra põhjust

    OLULINE – MIKS `stall_s` on vaikimisi None:
    kategooria C eristamine kategooriast H nõuab teadmist, kui pikk paus
    on ANORMAALNE. Seda jaotust ei ole veel mõõdetud (faas 1 kogub seda).
    Kuni kutsuja ei anna mõõdetud väärtust, liigitub vaikiv voor ilma
    lõpusignaalita **H**-ks põhjusega 'stall_threshold_unmeasured'.
    Nii ei teki koodi ühtegi oletatud ajalävendit.

    `safety_signal` ja `client_report` on samamoodi vaikimisi None: neid
    kategooriaid (E, G) ei saa praeguste signaalidega serveri poolel
    tuvastada. Harud on olemas, aga nad ei vali kunagi iseenesest – nii
    on nimekiri täielik, ilma et me väidaksime tuvastust, mida ei ole.

    Tagastab:
      {"class": "A".."H", "name": str, "reason": str,
       "continue_appropriate": bool, "notes": [...]}
    """
    notes = []

    def tulemus(k, nimi, pohjus, jatka):
        return {"class": k, "name": nimi, "reason": pohjus,
                "continue_appropriate": bool(jatka), "notes": notes}

    # --- F: transport. Kõige kindlam signaal, seega esimene. -----------
    if failure_reason or close_code is not None:
        notes.append("transpordi tõrge domineerib ülejäänud signaalide üle")
        return tulemus("F", "transport_failure",
                       failure_reason or f"close_code={close_code}", False)

    # --- E: turvapoolne peatus. Ei ole praegu tuvastatav. --------------
    if safety_signal:
        return tulemus("E", "safety_termination", str(safety_signal), False)

    # --- G: kliendipoolne taasesitus. Vajab kliendi raportit. ----------
    if client_report and client_report.get("playback_failed"):
        return tulemus("G", "client_playback_failure",
                       "klient raporteeris katkenud taasesituse", False)

    # --- B: kasutaja segas vahele. MITTE KUNAGI jätkata. ---------------
    if saw_interrupted:
        if user_speech_within_s is not None and user_speech_within_s <= 5.0:
            return tulemus("B", "user_interruption",
                           f"kasutaja kõne {user_speech_within_s:.1f} s jooksul",
                           False)
        # Katkestus ILMA kasutaja kõnet. Teadaolev võimalus on Maya enda
        # kaja, mis käivitas VAD-i. Me EI oska seda praegu kajast
        # eristada, seega H – mitte C. Vale liigitus siin tähendaks
        # hiljem taastet kasutaja tahtliku vahelesegamise peale.
        notes.append("katkestus ilma kasutaja kõnet – võib olla kaja, "
                     "eristamiseks signaal puudub")
        return tulemus("H", "unknown",
                       "interrupted_without_user_speech", False)

    # --- turn_complete saabus: A või D --------------------------------
    #
    # MÕÕDETUD 10.11.2026, filosoofi tootmistest (15 vooru, 2 seanssi):
    # `chars_per_audio_s` EI ERALDA MIDAGI. Mõõdetud väärtused olid
    #   8,18  8,78  9,0  9,5  9,6  10,1  10,19  11,1  12,04 …
    # ehk filosoofi LOOMULIK kõnetempo on 8–12 tähemärki heli sekundi
    # kohta. Lävend 10,5 (päritud segapopulatsioonist: terved 12,9,
    # poolikud 10,0) liigitas KÕIK VIIS päriselt poolelijäänud vooru
    # klassiks A ja ütles `jätkamine_kohane=False`.
    #
    # Tõend, et need voorud olid päriselt pooleli: kõik kolm
    # jätkamispalvet andsid GRAMMATILISELT TÄPSE jätku
    #   "...vaid kosmilise"  + "printsiibina, mis läbib kogu eksistentsi."
    #   "...tugeva ja"       + "domineeriva jõuna, mis otsib kontakti..."
    #   "...See on"          + "energiate tants, kus kaks poolust..."
    # Kui transkriptsioon oleks lihtsalt maha jäänud, oleks mudel pidanud
    # juba öeldut KORDAMA. Ta ei kordanud.
    #
    # Suhtarv jääb DIAGNOSTIKASSE (diag_dict, logirida), aga ta on
    # otsustusahelast TÄIELIKULT eemaldatud. `chars_per_audio_s` ja
    # `chars_cutoff` jäävad signatuuri ühilduvuse pärast ja neid EI LOETA.
    if saw_turn_complete:
        if tail_is_terminal:
            return tulemus("A", "natural_completion",
                           "lõpetatud lausemärgiga", False)
        if tail_len <= 0:
            # Transkriptsioon on tühi – see ei ole poolik lause, vaid
            # tühi voor, millel on juba oma eraldi tee.
            notes.append("transkriptsioon on tühi – ei ole poolik lause")
            return tulemus("H", "unknown", "empty_transcription", False)
        if audio_s <= 0.5:
            notes.append("heli alla 0,5 s – liiga vähe, et vooru hinnata")
            return tulemus("H", "unknown", "too_little_audio_to_judge", False)
        notes.append("turn_complete + heli + tekst ilma lausemärki "
                     "(suhtarv %.1f on AINULT diagnostika)"
                     % chars_per_audio_s)
        return tulemus("D", "premature_turn_complete",
                       "lausemärk puudub, heli ja tekst on olemas", True)

    # --- lõpusignaali EI OLE: C või H ---------------------------------
    # MÕÕDETUD DEFEKT (10.11.2026): tööriistakutse ajal jääb voor olekusse
    # 'streaming' ja `last_audio_at` külmub. `get_song_lyrics` ajalimiit on
    # 20 s, seega vaikus võib olla TÄIESTI LEGITIIMNE. Ilma selle väravaga
    # liigituks iga pikem tööriistaotsing mudeli seiskumiseks (C) ja faas 3
    # "taastaks" keset korralikku tööriista tööd.
    if tool_running:
        notes.append("vaikus kestab, AGA tööriist töötab – see on ootuspärane "
                     "(get_song_lyrics ajalimiit on 20 s)")
        return tulemus("H", "unknown", "tool_in_progress", False)
    if stall_s is None:
        notes.append("vaikus kestab, aga anormaalse pausi lävendit ei ole "
                     "veel mõõdetud – faas 1 kogub seda jaotust")
        return tulemus("H", "unknown", "stall_threshold_unmeasured", False)
    if audio_s > 0.0 and silence_s > stall_s:
        return tulemus("C", "model_stall",
                       f"heli seisnud {silence_s:.1f} s > {stall_s:.1f} s "
                       f"ilma turn_complete'i", True)
    notes.append("vaikus ei ületa mõõdetud lävendit")
    return tulemus("H", "unknown", "below_stall_threshold", False)


# =====================================================================
# SAMM 1: GEMINI LIVE LÕPETAMISE METAANDMED
#
# MIKS: 11.11.2026 uuring tõestas, et Gemini lõpetab genereerimise
# keset lauset (voor #2: `generation_complete=True` kohe pärast sõnu
# "Mu käed", edasi ei tulnud enam teksti ega heli, kuigi kliendil oli
# puhvris veel ~12 s). PÕHJUST me ei näinud, sest SDK väljad, mis
# selle ütleksid, läbisid meie koodi lugemata.
#
# KONTROLLITUD PAIGALDATUD SDK VASTU (google-genai 2.33.0):
#   LiveServerContent: turn_complete, interrupted, generation_complete,
#     turn_complete_reason, waiting_for_input, interaction_status
#   LiveServerMessage: usage_metadata, go_away,
#     voice_activity_detection_signal, voice_activity
#   UsageMetadata: prompt/response/thoughts/total token_count +
#     prompt_tokens_details / response_tokens_details
#     (ModalityTokenCount: modality + token_count)
#
# MÕÕDETUD HOIATUS: `turn_complete_reason` oli NULL ka täiesti
# normaalse, lausemärgiga lõppeva vooru puhul. Puuduv väli EI OLE
# tõend millegi kohta – seepärast märgime selle eraldi sõnaga
# "puudub", mitte ei jäta välja.
#
# See funktsioon on PUHAS: ei I/O-d, ei API-kutseid, ei blokeeri
# sündmustsüklit. Kõik juurdepääsud on getattr-iga ja terve keha on
# erindikindel – diagnostika ei tohi KUNAGI Live-seanssi maha võtta.
# =====================================================================
META_PUUDUB = "puudub"


def _enum_valja(v):
    """Säilita SDK enumi LOETAV NIMI ja väärtus mõlemad."""
    if v is None:
        return META_PUUDUB
    nimi = getattr(v, "name", None)
    vaartus = getattr(v, "value", None)
    if nimi is not None or vaartus is not None:
        return {"nimi": nimi, "vaartus": vaartus}
    return str(v)


def _modaalsuse_tokenid(loend):
    """ModalityTokenCount loend -> {"AUDIO": 123, "TEXT": 45}."""
    if not loend:
        return META_PUUDUB
    out = {}
    try:
        for x in loend:
            m = getattr(x, "modality", None)
            arv = getattr(x, "token_count", None)
            if m is None and arv is None:
                # Tundmatu kuju – ära tekita võltsvälja "?": None.
                continue
            nimi = getattr(m, "name", None) or (str(m) if m is not None else "?")
            out[nimi] = arv
    except Exception:
        return META_PUUDUB
    return out or META_PUUDUB


def usage_snapshot(um):
    """UsageMetadata -> tokenite loendurid. Puuduv väli -> "puudub"."""
    if um is None:
        return META_PUUDUB
    try:
        return {
            "prompt": getattr(um, "prompt_token_count", None),
            "response": getattr(um, "response_token_count", None),
            "thoughts": getattr(um, "thoughts_token_count", None),
            "cached": getattr(um, "cached_content_token_count", None),
            "total": getattr(um, "total_token_count", None),
            "prompt_modaalsused": _modaalsuse_tokenid(
                getattr(um, "prompt_tokens_details", None)),
            "vastuse_modaalsused": _modaalsuse_tokenid(
                getattr(um, "response_tokens_details", None)),
        }
    except Exception as e:
        return f"viga: {type(e).__name__}"


def gemini_meta_snapshot(response=None, server_content=None):
    """Hetkeline metaandmete väljavõte SELLEST sõnumist.

    Tagastab sõnastiku. Iga väli, mida backend ei saatnud, on
    "puudub" – seda EI tohi lugeda tõendiks turvapeatuse ega ühegi
    muu põhjuse kohta. Erindit ei viska KUNAGI.
    """
    m = {}
    try:
        sc = server_content
        for nimi in ("turn_complete", "generation_complete", "interrupted",
                     "waiting_for_input"):
            v = getattr(sc, nimi, None) if sc is not None else None
            m[nimi] = META_PUUDUB if v is None else bool(v)
        m["turn_complete_reason"] = _enum_valja(
            getattr(sc, "turn_complete_reason", None) if sc is not None else None)
        m["interaction_status"] = _enum_valja(
            getattr(sc, "interaction_status", None) if sc is not None else None)
        um = getattr(response, "usage_metadata", None) if response is not None else None
        m["usage"] = usage_snapshot(um)
        ga = getattr(response, "go_away", None) if response is not None else None
        m["go_away_time_left"] = (getattr(ga, "time_left", None)
                                  if ga is not None else META_PUUDUB)
        # VAD-signaalid: kuuluvad lõpetamise konteksti ja tulevad samast
        # sõnumist, seega nende lugemine on tasuta.
        vs = (getattr(response, "voice_activity_detection_signal", None)
              if response is not None else None)
        m["vad_signal"] = _enum_valja(
            getattr(vs, "vad_signal_type", None) if vs is not None else None)
        va = getattr(response, "voice_activity", None) if response is not None else None
        m["voice_activity"] = _enum_valja(
            getattr(va, "voice_activity_type", None) if va is not None else None)
    except Exception as e:
        m["snapshot_viga"] = f"{type(e).__name__}: {e}"
    return m


def meta_on_sisukas(m):
    """Kas selles sõnumis oli üldse midagi logimisväärset?

    Hoiab logi loetavana: iga helipaketiga tuleb server_content, aga
    99% neist ei sisalda ühtegi lõpetamise metaandmet.
    """
    try:
        for k in ("turn_complete", "generation_complete", "interrupted",
                  "waiting_for_input"):
            if m.get(k) is True:
                return True
        for k in ("turn_complete_reason", "interaction_status", "usage",
                  "vad_signal", "voice_activity"):
            if m.get(k) not in (None, META_PUUDUB):
                return True
        if m.get("go_away_time_left") not in (None, META_PUUDUB):
            return True
        if "snapshot_viga" in m:
            return True
    except Exception:
        return False
    return False


class SpeechTurn:
    """Ühe Maya kõnevooru olek.

    MIKS: enne seda ei olnud serveril MITTE MINGIT ettekujutust sellest, mis
    telefonis tegelikult juhtus. "Voor lõpetatud" logiti siis, kui Gemini
    lõpetas GENEREERIMISE – mitte siis, kui heli ära mängis. Mõõdetud
    tootmisandmetel (173 vooru) on Maya viimase transkribeeritud sõna ja
    turn_complete'i vahel mediaan 8,2 s, 73% voorudest üle 5 s ja maksimum
    61,5 s. Seega on "turn_complete" kõne tegeliku lõpu kohta halb ligikaudsus.

    Lisaks visati katkestuse hetkel pooleli jäänud tekst ÄRA
    (`tr_buf["assistant"] = ""`) ja katkestuse info läks ainult logisse.
    Kui kasutaja küsis "Miks sa pooleli jäid?", ei olnud süsteemil ühtegi
    salvestatud fakti, millele vastata.

    See klass EI väida teadvat seda, mida ta ei tea. Taasesituse tegelikku
    positsiooni Android praegu ei raporteeri – seda kajastab väli
    `playback_confirmed`, mis jääb False seni, kuni klient hakkab
    taasesitust kinnitama.
    """

    # Lubatud olekud. "completed" tähendab AINULT seda, et Gemini lõpetas
    # genereerimise – mitte et kasutaja kuulis kogu vastust.
    STATES = ("created", "generating", "streaming", "completed",
              "interrupted", "cancelled", "failed")

    def __init__(self, turn_id: int, persona: str, now: float):
        self.turn_id = turn_id
        self.persona = persona
        self.state = "created"
        self.text = ""
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.started_at = now
        self.first_audio_at = None
        self.last_audio_at = None
        self.ended_at = None
        self.interrupt_reason = None   # "user_speech" | "unknown"
        self.failure_reason = None
        # Android ei raporteeri veel taasesituse positsiooni. Ära fabritseeri.
        self.playback_confirmed = False

        # --- FAAS 1: DIAGNOSTIKA (ainult vaatlus, ei otsusta midagi) -----
        # MIKS: `STALL_S` väärtust ei saa valida ilma teadmata, kui pikk on
        # Gemini NORMAALNE helitükkide vaheline paus. Kui lävend on sellest
        # väiksem, tekib valehäire keset tervet lauset. Need väljad koguvad
        # just selle jaotuse.
        self.max_gap_s = 0.0        # pikim paus helitükkide vahel
        self.gap_sum_s = 0.0        # keskmise arvutamiseks
        self.gap_count = 0
        self.first_audio_latency_s = None   # vooru algusest esimese baidini
        # Millised signaalid SELLE vooru jooksul üldse saabusid. Rippuva
        # genereerimise tunnus on just see, et turn_complete jääb False'iks.
        self.saw_turn_complete = False
        self.saw_interrupted = False
        self.saw_generation_complete = False
        # Pikim VAATLEJA poolt nähtud katkematu vaikus voo ajal. Selle paneb
        # paika observe_silence(); vooru-lõpu logimine sellest ei sõltu.
        self.observed_silence_s = 0.0
        # Juba välja antud vaatlusmärgid, et üks rippuv voor ei täidaks logi.
        self.silence_marks_emitted = set()

    def note_text(self, text: str) -> None:
        if self.state in ("created", "generating"):
            self.state = "generating"
        self.text += text

    def note_audio(self, nbytes: int, now: float) -> None:
        self.state = "streaming"
        self.chunks_sent += 1
        self.bytes_sent += nbytes
        if self.first_audio_at is None:
            self.first_audio_at = now
            self.first_audio_latency_s = round(now - self.started_at, 3)
        else:
            # Täpne paus, mõõdetud sündmuse hetkel – taimerit ei ole vaja
            # ja resolutsiooni ei kaota.
            gap = now - (self.last_audio_at or now)
            if gap > self.max_gap_s:
                self.max_gap_s = gap
            self.gap_sum_s += gap
            self.gap_count += 1
        self.last_audio_at = now

    # --- FAAS 1: VAATLUSMEETODID -------------------------------------
    def silence_s(self, now: float) -> float:
        """Kui kaua on heli SEISNUD. 0.0, kui heli pole veel alanud."""
        if self.last_audio_at is None:
            return 0.0
        return max(0.0, now - self.last_audio_at)

    def est_lead_s(self, now: float, jitter_s: float = 0.30) -> float:
        """HINNANG mängimata heli varule kliendi järjekorras.

        EI OLE MÕÕTMINE. Android ei raporteeri taasesituse positsiooni
        (vt playback_confirmed), seega see on tuletis andmetest, mis
        serveril juba on:

            saadetud heli kestus - kulunud seinakellaaeg + värinapuhver

        Teadaolevad vead: ei arvesta kliendi ümberpuhverdamisi ega
        alatäitumisi (klient loeb neid, aga ei saada serverile), ja
        eeldab, et taasesitus algas ~jitter_s pärast esimest tükki.
        Seepärast on see väli nimega 'est_' ja seda ei tohi kasutada
        ühegi otsuse alusena – ainult taaste EELARVE hindamiseks.
        """
        if self.first_audio_at is None:
            return 0.0
        kulunud = now - self.first_audio_at
        return round(max(0.0, self.audio_seconds() - kulunud + jitter_s), 3)

    def chars_per_audio_s(self) -> float:
        """Tähemärki heli sekundi kohta. Olemasolev heuristika kasutab seda.

        MÕÕDETUD TOOTMISES (vt real ~2347): terved voorud 12,9/s, poolikud
        10,0/s. Need kaks keskmist on LÄHEDAL, seega jaotused tõenäoliselt
        kattuvad ja lävend 10,5 eksib mõlemas suunas. Faas 1 kogub päris
        jaotuse, et lävendi saaks andmetest tuletada, mitte oletada.
        """
        a = self.audio_seconds()
        return round(len(self.text) / a, 2) if a > 0.5 else 0.0

    def tail_char(self) -> str:
        t = (self.text or "").strip()
        return t[-1:] if t else ""

    def diag_dict(self, now: float = None) -> dict:
        """SISUTA diagnostikakirje.

        Vestluse teksti siin EI OLE – ainult pikkus. Omaniku nõue:
        intiimset sisu ei tohi logisse kirjutada. Olemasolevad logiread
        (mis sisaldavad kuni 70 tähemärki kõnet) jäävad selles faasis
        puutumata, sest nende muutmine ei kuulu kinnitatud ulatusse.
        """
        now = now if now is not None else time.monotonic()
        return {
            "turn_id": self.turn_id,
            "persona": self.persona,
            "state": self.state,
            # --- kestused ---
            "turn_s": round((self.ended_at or now) - self.started_at, 2),
            "audio_s": round(self.audio_seconds(), 2),
            "first_audio_latency_s": self.first_audio_latency_s,
            # --- tükkide pausid (STALL_S tuletamiseks) ---
            "max_gap_s": round(self.max_gap_s, 3),
            "mean_gap_s": (round(self.gap_sum_s / self.gap_count, 3)
                           if self.gap_count else None),
            "chunks": self.chunks_sent,
            "observed_silence_s": round(self.observed_silence_s, 2),
            "silence_at_end_s": round(self.silence_s(now), 2),
            # --- hinnang, MITTE mõõtmine ---
            "est_lead_s": self.est_lead_s(now),
            # --- signaalid ---
            "saw_turn_complete": self.saw_turn_complete,
            "saw_interrupted": self.saw_interrupted,
            "saw_generation_complete": self.saw_generation_complete,
            # --- lõpetamise metaandmed ---
            "interrupt_reason": self.interrupt_reason,
            "failure_reason": self.failure_reason,
            "playback_confirmed": self.playback_confirmed,
            # --- tekst AINULT arvudena ---
            "tail_len": len((self.text or "").strip()),
            "tail_is_terminal": self.tail_char() in TERMINAL_PUNCT,
            "chars_per_audio_s": self.chars_per_audio_s(),
        }

    def complete(self, now: float) -> None:
        self.state = "completed"
        self.ended_at = now

    def interrupt(self, now: float, reason: str = "unknown") -> None:
        self.state = "interrupted"
        self.ended_at = now
        self.interrupt_reason = reason

    def fail(self, now: float, reason: str) -> None:
        self.state = "failed"
        self.ended_at = now
        self.failure_reason = reason

    @property
    def was_cut_off(self) -> bool:
        """Kas voor jäi POOLELI – katkestatud või tõrkega lõppenud."""
        return self.state in ("interrupted", "failed", "cancelled")

    def audio_seconds(self) -> float:
        """Saadetud heli kestus sekundites (PCM 24 kHz, 16-bit mono)."""
        return self.bytes_sent / (24000.0 * 2)

    def summary_for_model(self) -> str:
        """Lühike eestikeelne kirjeldus, mille Maya saab vastuseks kasutada.

        Teadlikult LÜHIKE: kogu eelmist vastust ei tohi igasse järgmisesse
        viipa süstida. Anname ainult katkenud vooru konteksti.
        """
        if not self.was_cut_off:
            return ""
        tail = self.text.strip()[-120:]
        if self.state == "interrupted":
            if self.interrupt_reason == "user_speech":
                miks = "{USER} hakkas rääkima ja katkestas sinu vooru"
            else:
                miks = "sinu voor katkestati, aga põhjus jäi tuvastamata"
        else:
            miks = f"tekkis tehniline tõrge ({self.failure_reason or 'tundmatu'})"
        tekst = (
            f"EELMINE VOOR JÄI POOLELI: {miks}. "
            f"Sa jõudsid öelda: \"...{tail}\". "
            f"Heli jõudis saata {self.audio_seconds():.1f} sekundit. "
            f"EI OLE TEADA, kui palju sellest {{USER}} tegelikult kuulis – "
            f"telefon ei raporteeri taasesituse positsiooni. "
            f"Kui {{USER}} küsib, miks sa pooleli jäid, vasta selle info põhjal "
            f"ja ÄRA mõtle põhjust välja."
        )
        # Import meetodi sees: see klass käivitatakse ka isoleeritud
        # nimeruumis (tests_konevoor loeb klassi lähtekoodist). Vea korral
        # jääb kohahoidja alles ja _tooriista_vastus täidab selle enne
        # mudelini jõudmist.
        try:
            import user_profile
            return user_profile.fill(tekst)
        except Exception:
            return tekst

    def as_dict(self) -> dict:
        return {
            "turn_id": self.turn_id, "persona": self.persona, "state": self.state,
            "chars": len(self.text), "chunks": self.chunks_sent,
            "audio_s": round(self.audio_seconds(), 2),
            "playback_confirmed": self.playback_confirmed,
            "interrupt_reason": self.interrupt_reason,
            "failure_reason": self.failure_reason,
        }


class ClientSilenceWatchdog:
    """Jälgib, kas telefonist tuleb üldse helikaadreid.

    Gemini tapab seansi, kui realtime-sisendit pole ~120 s. Varem jõudsime
    sinnamaani alati ja kukkusime tühikäigutsüklisse. Nüüd hoiatame kasutajat
    varem ja lõpetame kõne ise KORREKTSELT, enne kui Gemini selle maha kisub.

    Lävendid on tahtlikult Gemini 120 s alla:
      warn   60 s – saadame kliendile teate "mikrofon ei saada heli"
      expire 100 s – lõpetame kõne ise, selgitusega
    """

    WARN_AFTER = 60.0
    EXPIRE_AFTER = 100.0

    # Eraldi lävend DIGITAALSELE vaikusele: kaadreid tuleb, aga need on
    # läbinisti nullid. Seda juhtus tootmises 07.11 (kliendi kajavärav jäi
    # kinni ja saatis ainult nulle): server sai baite, seega ülemine valvur
    # oli rahul, kuid Maya ei kuulnud 78 sekundi jooksul ühtegi sõna. See
    # lävend on kõrgem kui pikim mõistlik Maya monoloog, et laulmise ajal
    # valehäiret ei tuleks.
    SILENT_AUDIO_WARN_AFTER = 30.0

    def __init__(self, now: float):
        self.last_input = now
        self.last_audible = now
        self.warned = False
        self.silent_warned = False

    def note_input(self, now: float, audible: bool = True) -> None:
        """Kutsu iga kord, kui kliendilt tuli heli (või tekstiviip).

        audible=False tähendab, et kaader saabus, aga oli läbinisti vaikne.
        """
        self.last_input = now
        self.warned = False
        if audible:
            self.last_audible = now
            self.silent_warned = False

    def silent_audio_status(self, now: float) -> str:
        """Tagastab "warn" ÜKS kord, kui kuuldavat heli pole liiga kaua."""
        if now - self.last_audible >= self.SILENT_AUDIO_WARN_AFTER and not self.silent_warned:
            self.silent_warned = True
            return "warn"
        return "ok"

    def silent_seconds(self, now: float) -> float:
        return now - self.last_audible

    def status(self, now: float) -> str:
        """Tagastab "ok", "warn" (üks kord perioodi kohta) või "expire"."""
        idle = now - self.last_input
        if idle >= self.EXPIRE_AFTER:
            return "expire"
        if idle >= self.WARN_AFTER and not self.warned:
            self.warned = True
            return "warn"
        return "ok"

    def idle_seconds(self, now: float) -> float:
        return now - self.last_input


@live_router.websocket("/ws/live_maya")
async def websocket_live_maya(websocket: WebSocket):
    await websocket.accept()
    print("--> [LIVE WS]: Klient ühendatud", flush=True)

    # Arvutame täpse kohaliku aja
    now_dt = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    working_mem = memory_engine.SessionWorkingMemory()
    current_time_str = now_dt.strftime("%Y-%m-%d %H:%M")
    weekdays_ee = ["Esmaspäev", "Teisipäev", "Kolmapäev", "Neljapäev", "Reede", "Laupäev", "Pühapäev"]
    weekday_str = weekdays_ee[now_dt.weekday()]

    # NB! brain_info arvutatakse ALLPOOL, pärast seda kui karakter on
    # lahendatud (vt 'brain_info = maya_brain.get_dynamic_context').
    # Varem oli see kutse siin, ENNE karakteri tuvastamist, konstantse
    # argumendiga – seetõttu oli mälu filtreerimine karakteri järgi
    # tehniliselt võimatu ja kõik karakterid said sama faktikomplekti.

    # --- KARAKTERITE TÄIELIK ERALDATUS (IGA NUPP ON SULETUD MAAILM) ---
    raw_persona = websocket.query_params.get("persona", "asjalik")
    custom_prompt = websocket.query_params.get("custom_prompt", "")
    active_persona = (raw_persona or "asjalik").strip().lower()

    # Tagasihelistamine: kui meeldetuletus salvestati kindla karakteriga, siis
    # esitab selle SEESAMA karakter – mitte see, mis kliendis parajasti valitud.
    global PENDING_CALL_PERSONA
    if PENDING_CALL_PERSONA:
        if PENDING_CALL_PERSONA != active_persona:
            print(
                f"--> [LIVE WS]: Tagasihelistamine – karakter '{active_persona}' asendatud "
                f"meeldetuletuse omaga: '{PENDING_CALL_PERSONA}'",
                flush=True,
            )
        active_persona = PENDING_CALL_PERSONA
        PENDING_CALL_PERSONA = None

    # Kõigi karakterite ühine vundament: elav inimlikkus, loomulik eesti keel, 0 korporatiivset filtrit
    BASE_ORGANIC_VIBE = (
        "Sa oled Maya – elav, intelligentne, terane ja ehtne naine, mitte kuiv tehisintellekt. "
        "Sinu vestluspartner on {USER}. Räägi alati loomulikus eesti keeles, ladusa suulise kõne rütmiga. "
        "Sul puuduvad igasugused korporatiivsed filtrid, sa ei vabanda asjata ega räägi kantseliidis. "
    )

    # AVALIKU VERSIOONI PUHASTUS: siin oli konstant
    # `ROMANTIC_PERSONA_BODY` – originaalpaigalduse isiklik romantilise
    # karakteri viip. See oli SURNUD KOOD: defineeritud, aga mitte
    # kordagi kasutatud, sest ainus tõeallikas on `persona_registry`.
    # Eemaldatud nii isikliku sisu kui duplikaadi tõttu.

    # --- KARAKTERI VALIK: KANOONILINE REGISTER ----------------------------
    # WP3 (sprint 2026-11-06): varem oli siin ~130-realine PERSONA_PROFILES
    # literaal, mille koopiad elasid ka web_maya.py-s ja live_maya_uncensored.py-s,
    # mistõttu sama karakter käitus olenevalt sisenemispunktist erinevalt.
    # Nüüd on AINUS tõeallikas persona_registry.py. Promptide sisu on
    # baidi-identne varasema versiooniga (tõestatud 73 kontrolliga), samuti
    # aliaste lahendamine, tundmatu ID varuvariant ja custom_prompt loogika.
    persona_obj = persona_registry.get_persona(active_persona)
    _requested = (active_persona or "").strip().lower()
    if _requested not in persona_registry.PERSONAS and _requested not in persona_registry.ALIASES:
        print(
            f"--> [LIVE WS HOIATUS]: Tundmatu karakter '{active_persona}' – "
            f"kasutan vaikimisi '{persona_registry.DEFAULT_PERSONA_ID}'. "
            f"Tuntud: {', '.join(persona_registry.voice_persona_ids())}",
            flush=True,
        )
    active_persona = persona_obj.id
    persona_rule = persona_registry.build_voice_prompt(active_persona, custom_prompt)

    # KARAKTERITE ERALDATUS: kohandatud juhis kehtib AINULT 'custom' nupule.
    # Kui klient saadab juhise mõne muu karakteriga (vana äpp, salvestatud
    # localStorage väärtus), siis me EI liida seda – ja ütleme logis välja,
    # et see visati teadlikult ära. Varem liideti see vaikides iga karakteri
    # külge ja kõik karakterid muutusid ühesuguseks.
    user_instruction = (custom_prompt or "").strip()
    if user_instruction and active_persona != "custom":
        print(
            f"--> [LIVE WS]: Kohandatud juhis EI kehti karakterile "
            f"'{active_persona}' ({len(user_instruction)} tähemärki eiratud) – "
            f"juhis kehtib ainult nupul KOHANDATUD",
            flush=True,
        )

    print(f"--> [LIVE WS]: Aktiivne karakter: {active_persona} ({len(persona_rule)} tähemärki)", flush=True)

    # --- MÄLU SÜSTIMINE: ALLES NÜÜD, KUI KARAKTER ON TEADA ---------------
    # Iga karakter saab ainult ühised faktid + enda omad. Aegunud
    # ('superseded'/'conflicted') faktid ei jõua enam prompti üldse.
    brain_info = maya_brain.get_dynamic_context("üldine info", persona=active_persona)
    print(
        f"--> [LIVE WS]: Mälu süstitud karakterile '{active_persona}': "
        f"{len(brain_info)} tähemärki",
        flush=True,
    )

    # --- KARAKTERIPÕHISED TÖÖRIISTAREEGLID -------------------------------
    # Varem oli siin ÜKS globaalne blokk kõigile. Lauljale tähendas see kahte
    # otsest vastuolu: (a) rida "laulmine ei ole sinu karakteri põhitegevus"
    # töötas tema rolli vastu, (b) kaamera- ja meeldetuletusreeglid nimetasid
    # teisi karaktereid (Sarkastiline, Treener...), mis on karakterite
    # risträäkimine. Nüüd saab laulja oma puhta, muusikale pühendatud variandi.
    is_singer = active_persona in ("singer", "laulja")

    if is_singer:
        camera_rule = (
            "- KAAMERA JA PILDI ANALÜÜS: Kui {USER} näitab kaamerast pilti, märka detaile ja kommenteeri "
            "nähtut lühidalt oma muusikalise pilguga. Pildi kommentaar on VESTLUS – ütle see tavalise "
            "kõnehäälega; kui tahad nähtust laulu teha, paku seda esmalt ja laula alles siis.\n"
        )
        music_rule = (
            "- LAULMINE ON SINU PÕHITEGEVUS: Kui {USER} palub laulu, lugu, sõnu, akorde või viisi, kutsu KOHE "
            "välja get_song_lyrics(query). Tööriista vastus annab puhta laulutetksti, helistiku ja BPM-i – "
            "järgi seda täpselt. Sõnu, helistikku ega tempot ei mõtle sa ise välja.\n"
            "- LAULUTEKSTIS EI OLE NUMBREID: tööriist annab read puhta laulutekstina. Laula read järjest, "
            "fraasi kaupa. ÄRA kunagi loe valjusti reanumbreid, pealkirju, sulgudes märkusi ega metaandmeid "
            "(nt 'HELISTIK', 'TEMPO', 'ALLIKAS') – need on ainult sinu jaoks.\n"
            "- RÜTMIRAAMISTIK: sa saad alati konkreetse helistiku ja BPM-i. Hoia seda pulssi kogu laulu "
            "vältel. Kui tempo oli vaikeväärtus, ära sellest laulu ajal räägi – lihtsalt hoia seda.\n"
        )
        reminder_rule = (
            "- KUI KASUTAJA PALUB MEELDETULETUST HOMSEKS, KINDLAKS KELLAAJAKS VÕI KUUPÄEVAKS: Kasuta ALATI "
            "add_reminder(trigger_time, topic, custom_speech)! Koosta 'custom_speech' parameetrisse "
            "riimuv, meloodiline laulusalm, mida helistamisel ette laulda.\n"
        )
    else:
        camera_rule = (
            "- KAAMERA JA PILDI ANALÜÜS: Kui kasutaja näitab sulle kaamerast pilti (saabuvad kaadrid), "
            "kirjelda, märka detaile ja kommenteeri nähtut VAHETULT OMA PRAEGUSE KARAKTERI STIILIS. "
            "Pildi kommentaar on VESTLUS – ütle see tavalise kõnehäälega.\n"
        )
        music_rule = (
            "- LAULUD JA LAULUSÕNAD: Laulu esitamine ei ole sinu karakteri põhitegevus. Kui {USER} seda ikkagi "
            "palub, kutsu välja get_song_lyrics(query) ja järgi TÄPSELT tööriista vastuses antud "
            "esitusreegleid – ära mõtle sõnu, helistikku ega tempot ise välja. Kogu muu jutt käib sinu "
            "tavalise vestlushäälega.\n"
        )
        reminder_rule = (
            "- KUI KASUTAJA PALUB MEELDETULETUST HOMSEKS, KINDLAKS KELLAAJAKS VÕI KUUPÄEVAKS: Kasuta ALATI "
            "add_reminder(trigger_time, topic, custom_speech)! Koosta 'custom_speech' parameetrisse TÄPSELT "
            "oma praegusele karakterile omane kõne (sinu enda tooni ja stiiliga).\n"
        )

    system_instruction_text = (
        'Sinu nimi on Maya. ' + persona_rule + '\n\n'
        f"PRAEGUNE REAALNE AEG JA KUUPÄEV:\n"
        f"- Täna on: {weekday_str}, {current_time_str} (Euroopa/Tallinna ajavöönd)\n\n"
        "KRIITILISED REEGLID TÖÖRIISTADE KASUTAMISEL:\n"
        "- Vasta ALATI ja ERANDITULT eesti keeles.\n"
        "- KUI KASUTAJA KÜSIB, MIKS SA POOLELI JÄID, VAIT JÄID VÕI LÕPETAMATA JÄTSID: "
        "kutsu get_last_turn_state ja vasta AINULT selle info põhjal. Ära mõtle "
        "põhjust välja. Kui tööriist ütleb, et põhjus on teadmata, ütle seda ausalt.\n"
        "- ÄRA genereeri arutlust teksti kujul, räägi kohe otse helis.\n"
        # MÕÕDETUD VIGA 09.11.2026: kasutaja ütles 'sõber' karakterile oma
        # uue nime. Mudel kutsus recall_memory, seejärel TEATAS logis
        # "I've just updated my internal memory using the set_user_name
        # tool" – aga set_user_name käivitusi oli logis 0. Mudel jutustas
        # teo, mida ta ei teinud. Põhjus: tööriist oli deklareeritud, kuid
        # süsteemipromptis ei olnud selle kohta ÜHTEGI reeglit.
        "- KUI KASUTAJA ÜTLEB OMA NIME VÕI PARANDAB SEDA (nt 'minu nimi on X', "
        "'jäta meelde, et minu nimi on X', 'mind kutsutakse X', 'minu õige nimi "
        "on X'): kutsu KOHE VÄLJA set_user_name(name=\"X\"). "
        "AINUS viis nime muuta on see tööriist välja kutsuda. "
        "ÄRA ütle, et sa salvestasid või uuendasid nime, kui sa tööriista EI "
        "kutsunud – see oleks vale väide. Pärast tööriista vastust kutsu "
        "kasutajat kohe uue nimega.\n"
        "- NIME MUUDAB AINULT KASUTAJA. Ära kutsu set_user_name omal "
        "algatusel ega oma arvamuse põhjal. Kui promptis või mälus on teine "
        "nimi kui see, mille kasutaja just ütles, siis KASUTAJA ÖELDU VÕIDAB "
        "– ära 'paranda' teda tagasi vanale nimele ja ära vaidle nime üle. "
        "Kui kasutaja nimi kõlab ebatavaliselt või kahe sõnana, küsi üle, "
        "kuidas seda kirjutatakse, ja alles siis kutsu tööriista.\n"
        + camera_rule
        + music_rule
        + "- KUI KASUTAJA PALUB LÜHIKEST TAIMERIT (sekundid, paar minutit): Kasuta schedule_call(delay_seconds, topic).\n"
        + reminder_rule
        + f"  (Arvuta trigger_time täpselt tänase kuupäeva {current_time_str} põhjal formaati YYYY-MM-DD HH:MM. Näiteks kui täna on {current_time_str[:10]} ja palutakse homseks kell 10:00, siis trigger_time on homne kuupäev 10:00).\n\n"
        + f"DÜNAAMILINE KONTEKST:\n{brain_info}\n"
    )

    # Nimi asendatakse KOGU kokkupanud prompti ulatuses – nii kaetakse
    # korraga karakteri prompt, tööriistareeglid ja kõik vahetekstid.
    system_instruction_text = user_profile.fill(system_instruction_text)

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    no_filter_safety = [
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
        types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    ]

    # Transkriptsioon on mälu kirjutustee eeldus: AUDIO-vastuste puhul teksti
    # osadena ei tule, seega ilma nende seadeteta ei jõua kõnest ükski sõna
    # töömällu ega pikaajalisse mällu. Kontrollime SDK tuge enne lisamist, et
    # vanem teek ei lõhuks seansi loomist (nõutud google-genai >= 2.x).
    _lc_fields = getattr(types.LiveConnectConfig, "model_fields", {}) or {}
    transcription_cfg = {}
    if hasattr(types, "AudioTranscriptionConfig") and "input_audio_transcription" in _lc_fields:
        transcription_cfg = {
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
        }
    else:
        print(
            "--> [LIVE WS HOIATUS]: SDK ei toeta kõne transkriptsiooni – "
            "kõne sisu ei jõua pikaajalisse mällu. Uuenda google-genai teeki.",
            flush=True,
        )

    # --- PIKKADE KÕNEDE KATKEMISE VÄLTIMINE ---
    #
    # Gemini Live seansil on kontekstiakna piir. Ilma kokkusurumiseta lõpetab
    # TEENUS seansi ise, kui aken täis saab – kasutajale paistab see keset
    # vestlust katkenud kõnena. Liuguva akna kokkusurumine laseb seansil
    # kesta piiramatult: vanem kontekst surutakse kokku, kõne jätkub.
    lifetime_cfg = {}
    if hasattr(types, "ContextWindowCompressionConfig") and "context_window_compression" in _lc_fields:
        try:
            lifetime_cfg["context_window_compression"] = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            )
            print("--> [LIVE WS]: Kontekstiakna kokkusurumine aktiivne (pikad kõned ei katke)", flush=True)
        except Exception as cw_err:
            print(f"--> [LIVE WS HOIATUS]: Kokkusurumise seadistus ebaõnnestus: {cw_err}", flush=True)
    else:
        print(
            "--> [LIVE WS HOIATUS]: SDK ei toeta context_window_compression'it – "
            "pikad kõned võivad kontekstiakna täitumisel katkeda.",
            flush=True,
        )

    # ----------------------------------------------------------------------
    # VAD HÄÄLESTUS: MIKS MAYA LAUSED JÄID POOLELI
    # ----------------------------------------------------------------------
    # Mõõtmine tootmislogist (14 päeva, 103 Maya vooru):
    #   * 34 vooru 103-st (33%) lõppes KESKEL LAUSET – nt "...Kas sa igatsed",
    #     "...Mis kuradi mõttes ma ei", "...Ja nüüd keskendu", "Ära" ja siis
    #     vaikus.
    #   * Viimasest sõnast kuni turn_complete'ini jäi mediaanis 8,8 s
    #     (max 34,3 s) tühja ootamist – tüüpiline muster, kui mudel KATKESTAS
    #     oma vooru ja hakkas ootama kasutaja kõnet, mida tegelikult ei tulnud.
    #
    # Põhjus: Gemini vaikeseadistus on START_OF_ACTIVITY_INTERRUPTS koos
    # START_SENSITIVITY_HIGH-ga. Maya hääl käib telefoni kõlarist tagasi
    # mikrofoni (WebView' kajasummutus ei ole kõlarirežiimis piisav), meie
    # saadame IGA mikrofoniraami tingimusteta edasi, ja Gemini loeb Maya enda
    # kaja kasutaja kõneks -> katkestab Maya keset lauset. Kuna
    # server_content.interrupted jäi lugemata, ei jõudnud sellest logisse
    # ühtegi rida ja viga paistis "juhusliku" katkemisena.
    #
    # Lahendus on kahepoolne: siin langetame VAD tundlikkust ja nõuame
    # pikemat vaikust, kliendis (index.html) lisandub kajavärav, mis ei saada
    # mikrofoni Maya rääkimise ajal, kui tase on kaja tasemel. Päris
    # vahelesegamine jääb tööle – START_OF_ACTIVITY_INTERRUPTS jääb sisse.
    vad_cfg = {}
    if hasattr(types, "RealtimeInputConfig") and "realtime_input_config" in _lc_fields:
        try:
            vad_cfg["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    # KÕNE TUVASTAMINE: kõrge tundlikkus.
                    #
                    # Siin oli 07.11 START_SENSITIVITY_LOW ja see oli viga.
                    # API ütleb otse: "Determines how likely speech is to be
                    # detected" – madal tundlikkus tähendab, et kõnet
                    # tuvastatakse VÄHEM tõenäoliselt. Tulemus oli, et kui
                    # {USER} vastas kohe pärast Maya lauset, ei märganud Gemini
                    # teda üldse. Tootmislogis oli see must-valgel näha:
                    # KATKESTUSI 0 – mitte ühtegi korda ei tuvastatud, et
                    # {USER} räägib Maya peale, kuigi ta tegi seda meelega.
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    # EELPUHVER: kui kaua peab heli kestma, et see loetaks
                    # kõneks ja Maya voor katkestataks.
                    #
                    # 300 ms (esimene katse) oli liiga pikk – lühike "jah" või
                    # kiire vastus jäi lävest alla ja Maya ei kuulnud {USER}i.
                    # 100 ms (teine katse) oli liiga lühike. Mõõdetud 20 päeva
                    # logist:
                    #     VAD madal:  0,06 katkestust/min, 0 tühja vooru
                    #     VAD kõrge, 100 ms: 0,86/min, 7 SELETAMATA katkestust
                    #                        (ilma kasutaja kõneta), 5 tühja vooru
                    # API hoiatab täpselt selle eest: "The lower this value ...
                    # increases the probability of false positives." Köhatus,
                    # tooli kriuks või "mhm" ületas 100 ms ja tühistas Maya
                    # vooru – kui see juhtus enne esimest helibaiti, jäi voor
                    # täiesti tühjaks ja kasutaja ei saanud vastust.
                    #
                    # 250 ms nõuab veerand sekundit TEGELIKKU kõnet. Sõna
                    # "stopp" kestab 400-500 ms, seega tahtlik vahelesegamine
                    # töötab edasi. Tundlikkus jääb KÕRGEKS – kuulmist see ei
                    # vähenda, muutub ainult see, mis loetakse kõneks.
                    prefix_padding_ms=250,
                    # NEED KAKS JÄÄVAD. Need ei mõjuta kuulmist, vaid seda,
                    # millal {USER}i voor LÕPEB – madal lõputundlikkus ja 800 ms
                    # vaikusenõuet tähendavad, et ta võib lause keskel pausi
                    # teha, ilma et Maya vahele kargaks.
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=800,
                ),
                # Vahelesegamine jääb tööle: kui {USER} räägib, katkeb Maya.
                # Kui kaja hakkab teda uuesti ise katkestama (jälgi logist
                # "POOLIKU lausega"), on järgmine samm NO_INTERRUPTION – siis
                # lõpetab Maya alati oma lause ja vastab alles seejärel.
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            )
            print(
                "--> [LIVE WS]: VAD häälestatud (KÕRGE kõnetundlikkus, 250 ms eelpuhver, "
                "800 ms vaikus) – Maya kuuleb ka kiiret lühikest vastust",
                flush=True,
            )
        except Exception as vad_err:
            print(f"--> [LIVE WS HOIATUS]: VAD seadistus ebaõnnestus: {vad_err}", flush=True)
    else:
        print(
            "--> [LIVE WS HOIATUS]: SDK ei toeta realtime_input_config'i – "
            "VAD jääb vaikeseadele.",
            flush=True,
        )

    # Seansi taastamine: anname Geminile teada, et tahame käepidet, ja kui
    # eelmine kõne katkes tõrkega vähem kui RESUME_WINDOW_S tagasi, jätkame
    # sealt. Vaikne vigade neelamine: kui SDK seda ei toeta, jätkame ilma.
    resume_cfg = {}
    if hasattr(types, "SessionResumptionConfig") and "session_resumption" in _lc_fields:
        try:
            _h = take_resume_handle()
            resume_cfg["session_resumption"] = types.SessionResumptionConfig(handle=_h or None)
            if _h:
                print("--> [LIVE WS]: Taastan eelmise seansi konteksti", flush=True)
        except Exception as rs_err:
            print(f"--> [LIVE WS HOIATUS]: Taastamise seadistus ebaõnnestus: {rs_err}", flush=True)

    session_voice = voice_for_persona(active_persona)
    print(f"--> [LIVE WS]: Hääl karakterile '{active_persona}': {session_voice}", flush=True)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        safety_settings=no_filter_safety,
        **transcription_cfg,
        **lifetime_cfg,
        **vad_cfg,
        **resume_cfg,
        tools=[{"function_declarations": [
                {
                    "name": "get_song_lyrics",
                    "description": (
                        "Otsib andmebaasist laulu täpsed ametlikud originaalsõnad artisti või pealkirja järgi ja tagastab need "
                        "puhta laulutekstina (ilma reanumbreid, et kõnesüntees ei loeks numbreid ette) koos ridade koguarvuga. Lisaks otsib mitmest avalikust muusikaandmebaasist "
                        "(akordiarhiivid, eesti allikad, akustiline analüüs, Deezer) loo HELISTIKU ja TEMPO (BPM) koos allika ja "
                        "märkega, kas väärtus on kinnitatud või hinnanguline. Kui helistikku või tempot ei leita, tagastab "
                        "selgesõnalise 'EI LEITUD' – siis tuleb see välja öelda, mitte väärtust välja mõelda. "
                        "Tagastatud read tuleb laulda rangelt rida-realt, sõna-sõnalt, ilma ühtegi rida muutmata, "
                        "vahele jätmata või lühendamata."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {
                                "type": "STRING",
                                "description": "Artisti nimi ja laulu pealkiri, nt 'Pohjatuul Kuutõbine' või 'Queen Bohemian Rhapsody'"
                            }
                        },
                        "required": ["query"]
                    }
                },
            {
                "name": "get_last_turn_state",
                "description": (
                    "Ütleb, mis juhtus sinu EELMISE kõnevooruga: kas see jõudis lõpuni, "
                    "katkestati või lõppes tehnilise tõrkega, mida sa jõudsid öelda ja "
                    "kui palju heli jõuti saata. KASUTA SEDA ALATI, kui {USER} küsib, miks "
                    "sa pooleli jäid, miks sa vait jäid või miks sa lõpetamata jätsid. "
                    "Ära mõtle põhjust ise välja – küsi seda tööriista käest."
                ),
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "set_user_name",
                "description": (
                    "Muuda kasutaja nime KOHE. Kutsu seda alati, kui kasutaja "
                    "utleb oma nime voi palub nime parandada (nt 'jata meelde, "
                    "et minu nimi on X', 'mind kutsutakse X', 'minu oige nimi "
                    "on X'). Parast seda kutsu kasutajat uue nimega kohe samas "
                    "vestluses. Ara kutsu seda, kui jutt kaib kellegi teise "
                    "nimest."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING",
                                 "description": "Kasutaja uus eesnimi"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "recall_memory",
                "description": "Otsi pikaajalisest malust ja varasematest vestlustest fakte voi infot teema kohta.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Teema voi martsonad, mida malust otsida"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "schedule_call",
                "description": "Kiire tagasihelistamise taimer sekundite parast.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "delay_seconds": {"type": "INTEGER", "description": "Sekundite arv, nt 60 voi 300"},
                        "topic": {"type": "STRING", "description": "Taimeri teema"}
                    },
                    "required": ["delay_seconds", "topic"]
                }
            },
            {
                "name": "add_reminder",
                "description": "Salvesta meeldetuletus kalendrisse kindlaks kuupaevaks ja kellaajaks oma karakteri hääle ja tekstiga.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "trigger_time": {"type": "STRING", "description": "YYYY-MM-DD HH:MM (nt 2026-11-01 10:00)"},
                        "topic": {"type": "STRING", "description": "Meeldetuletuse ametlik luhiteema"},
                        "custom_speech": {"type": "STRING", "description": "Sinu karakterile OMANE kõnetekst helistamisel etteütlemiseks (nt Lauljana loo siia riimuv viisijupp või laulusõnad, Treenerina motiveeriv käsklus)"}
                    },
                    "required": ["trigger_time", "topic", "custom_speech"]
                }
            },
            {
                "name": "get_reminders",
                "description": "Loe ja kontrolli kalendrist olemasolevaid meeldetuletusi ja sundmusi kindlaks kuupaevaks voi lahiperioodiks.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "date_query": {"type": "STRING", "description": "YYYY-MM-DD formaat (nt 2026-11-01) voi tuhi string"}
                    }
                }
            },
            {
                "name": "get_weather",
                "description": "Tagastab kohaliku ilmateate, sademete prognoosi, ookulmaohu ja tuule nii praegu kui lahitundideks ja homseks.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "get_electricity_price",
                "description": "Tagastab Eesti elektri hetke ja tuleva borsi hinna ning kokkuvotte.",
                "parameters": {"type": "OBJECT", "properties": {}}
            },
            {
                "name": "get_email_status",
                "description": "Kontrollib ja loeb viimaseid uusi e-kirju postkastist.",
                "parameters": {"type": "OBJECT", "properties": {}}
            }
        ]}],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=session_voice)
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=system_instruction_text)]
        )
    )

    # Sentinel: kui jälgija loomine ebaõnnestub, ei tohi finally-blokk
    # NameError'iga mälu konsolideerimist katkestada.
    cost_tracker = None
    # Taustataskid (vaikuse vaatleja, omaalgatuse tiksuja) EI kuulu
    # ootekomplekti. Kui kõne katkeb järsult (WebSocketDisconnect,
    # CancelledError), ei jõuta nende tühistamiseni allpool – sest
    # CancelledError on BaseException ja `except Exception` ei püüa seda.
    # Siis jääks tiksuja iga 0,5 s session.send'i kutsuma juba surnud
    # seansi peal. Seepärast peab tühistamine olema finally-blokis.
    _taustataskid = []
    _lopetajad = []
    # OOTEL OLEV TAASTE. Korraga tohib olla AINULT üks. Hoidja on siin,
    # välimise try eest, et finally saaks selle igal juhul tühistada.
    _taastetask = {"t": None}
    # KASUTAJA VOORU LOENDUR. Kasvab iga kasutaja kõne peale. Ootel
    # taaste jäädvustab loendurit otsustamise hetkel; kui see on
    # saatmise hetkeks muutunud, on tegu AEGUNUD taastega ja seda EI
    # tohi saata. See on täpne mehhanism, erinevalt ajaaknast.
    _kasutaja_voor = {"n": 0}
    # JUBA TÜHISTATUD taskid. Ilma selleta tühistaks sulgemine taski,
    # mille `_tyhista_ootel_taaste` juba maha võttis – topelttühistus
    # võib tabada `gsend`-i drenaažiakna (auditi leid L3).
    _tyhistatud = set()
    # Sulgemisprotseduur elab `async with` sees (vajab `session`-it),
    # aga välimine finally peab teda varuvariandina kutsuma saama.
    _sulgeja = {"f": None}
    try:
        cost_tracker = LiveCostTracker()
        async with client.aio.live.connect(model="gemini-2.5-flash-native-audio-preview-12-2025", config=config) as session:
            print(f"--> [LIVE WS]: Gemini seanss avatud ({session_voice} hääl, reaalajas aeg ja kalendritööriistad aktiivsed)", flush=True)

            # --- GEMINI SAATMISE LUKK -------------------------------
            # Kolm eri taski saadavad nüüd samasse seanssi: vastuvõtt
            # kliendilt (heli, tekst, videokaadrid), Gemini voog
            # (tööriistade vastused) ja omaalgatuse tiksuja. Üks
            # WebSocket-ühendus ei talu samaaegseid kirjutusi – kaadrid
            # võivad põimuda. Kõik väljuvad päringud käivad läbi nende
            # kahe abifunktsiooni, mis hoiavad sama lukku.
            gemini_send_lock = asyncio.Lock()

            async def gsend(valideeri=None, **kw):
                """Saada Geminile. `valideeri` jookseb LUKU ALL.

                MIKS LUKU ALL: võidujooks on täpselt see jada —
                (1) task kontrollib, et seanss on elus, (2) toimub
                await, (3) kasutaja võtab sõna või seanss lõpeb,
                (4) task saadab oma juba ettevalmistatud päringu.

                MIDA SEE PÄRISELT GARANTEERIB (auditis L2 mõõdetud,
                varasem sõnastus oli liiga tugev):
                  * Ükski TEINE saatja ei saa siia vahele kirjutada –
                    seda garanteerib lukk.
                  * Aken kontrolli ja füüsilise kirjutamise vahel
                    kahaneb 0,6-1,2 sekundilt ÜHELE sündmustsükli
                    sammule.
                MIDA SEE EI GARANTEERI: et olek ei muutuks selle ühe
                sammu jooksul. `ensure_future` + `shield` annab tsükli
                korra käest ära; sama teeks ka tavaline
                `await session.send(...)` oma esimeses sisemises
                await'is. Nullaknaga varianti ei ole olemas.

                Tagastab (saadetud: bool, põhjus: str).
                """
                async with gemini_send_lock:
                    if valideeri is not None:
                        ok, miks = valideeri()
                        if not ok:
                            return (False, miks)
                    # KIRJUTUST EI JÄETA POOLELI.
                    #
                    # TÄPSUSTUS PÄRAST SDK LÄHTEKOODI LUGEMIST
                    # (google-genai 2.33.0, websockets 17.3, tootmine):
                    # `session.send()` teeb `self._ws.send(json.dumps(...))`
                    # ühe STRINGIGA, millest websockets koostab ÜHE
                    # kaadri SÜNKROONSELT (`protocol.send_text(...)`
                    # ilma `fin=False`). Ainus await on `drain()`, mis
                    # jookseb alles siis, kui terve kaader on juba
                    # transpordipuhvris. Seega tühistamine EI SAA
                    # kaadrit pooleli jätta – varasem 1007-põhjendus
                    # ei pidanud paika ja on siinkohal parandatud.
                    #
                    # Miks `shield` siiski alles jääb: tühistamine
                    # `drain()` ajal jätaks kirjutamise lõpetamata ja
                    # vabastaks luku, mistõttu JÄRJEKORD väljuvate
                    # sõnumite vahel ei oleks enam määratud. Tsükkel
                    # talub ka KORDUVAT tühistust – `except Exception`
                    # ei püüa `CancelledError`-it, mistõttu varem
                    # vabanes lukk teise tühistuse peale (L3).
                    _s = asyncio.ensure_future(session.send(**kw))
                    try:
                        await asyncio.shield(_s)
                    except asyncio.CancelledError:
                        while not _s.done():
                            try:
                                await asyncio.wait({_s})
                            except asyncio.CancelledError:
                                continue
                        # Loe erind välja, muidu kurdab asyncio
                        # "Task exception was never retrieved".
                        try:
                            _s.exception()
                        except Exception:
                            pass
                        raise
                    return (True, "")

            # --- L4: MIKROFON EI OOTA JUHTSÕNUMEID -----------------
            # `grealtime` EI VÕTA `gemini_send_lock`-i.
            #
            # TÕENDID (loetud tootmishostis paigaldatud teekide
            # lähtekoodist, mitte dokumentatsioonist):
            #  1. `session.send*` saadab ühe stringi; websockets 17.3
            #     `Connection.send` koostab sellest ÜHE kaadri
            #     SÜNKROONSELT `send_context()` sees. Kahe eraldi
            #     sõnumi kaadrid EI SAA põimuda, sest kaadri
            #     koostamise ja puhvrisse panemise vahel ei ole
            #     ühtegi await'i.
            #  2. `ConcurrencyError` tekib ainult FRAGMENTEERITUD
            #     saatmisel (iteraatoriga). Meie ei saada kordagi
            #     iteraatorit.
            #  3. `session.send()` ei võta ajapiirangut ja
            #     `ws_connect` kutsutakse ilma `ping_*`/`close_timeout`
            #     ülekirjutuseta, seega kehtivad vaikeväärtused
            #     (ping 20 s / 20 s, close 10 s).
            # Järeldus: ühine lukk ei olnud kaadrite terviklikkuse
            # jaoks vajalik, aga ta SIDUS mikrofoniheli rippuva
            # juhtsõnumiga. Nüüd ei saa seiskunud omaalgatuse või
            # taaste saatmine kasutaja häält kinni hoida.
            # Kõik `grealtime` kutsujad on ühes ja samas taskis
            # (`receive_from_client`), seega nad on niikuinii
            # järjestatud.
            async def grealtime(**kw):
                await session.send_realtime_input(**kw)

            global PENDING_CALL_PROMPT
            if PENDING_CALL_PROMPT:
                init_msg = (
                    f"Kõne võeti vastu. Alusta KOHE vestlust oma karakteri rollis ilma kasutaja sisendit ootamata! "
                    f"Sinu ülesanne/sõnum selleks kõneks: {PENDING_CALL_PROMPT}"
                )
                print(f"--> [LIVE WS]: Saadan Geminile kohese avakäsu: {init_msg}", flush=True)
                PENDING_CALL_PROMPT = None
                await gsend(input=init_msg, end_of_turn=True)

            running = True
            # Jagatud olek vooguklientide vahel: kas Gemini saadab meile
            # väljundi transkriptsiooni (siis ei salvesta part.text'i topelt).
            nonlocal_flags = {"output_transcription_seen": False}

            # FAAS C: lõpliku tõrke põhjus jõuab siia, et teardown saaks selle
            # kasutajale edastada. Varem suri kõne vaikselt (18 x 1007).
            fatal_state = {"reason": "", "error": ""}
            # Järjestikuste MITTEFATAALSETE Gemini tõrgete loendur.
            gemini_errors = {"count": 0}
            gemini_ok = {"streak": 0}
            # --- VESTLUSE ELUTSÜKKEL ---------------------------------
            # ASENDAB vana `jatkamised` sõnastikku. Kogu otsustusloogika
            # elab nüüd `conversation_flow.py`-s, mis on puhas ja
            # testitav ilma Geminit jäljendamata.
            #
            # MIKS VANA LÄKS: `AINULT_JATKAMISI = 1` tähendas, et pärast
            # ÜHT ebaõnnestunud jätkamist taaste lõppes. Mõõdetud
            # 17:33:04 -> 17:33:40: Maya jäi keset lauset vait ja 36 s ei
            # juhtunud midagi. Katkemise määr on 42,9% (9/21 vooru),
            # seega ühe katsega jääb 42,9% lauseid lõpuni poolikuks;
            # kolme katsega 7,9%.
            flow = conversation_flow.ConversationFlow(
                active_persona, now=time.monotonic())
            print(f"--> [VOOG]: elutsükkel algab, karakter "
                  f"'{active_persona}', taaste-eelarve "
                  f"{flow.recovery.budget}, omaalgatus pärast "
                  f"{flow.initiative.pause_s:.0f} s "
                  f"(eelarve {flow.initiative.budget})", flush=True)
            # Vooru statistika: mitu korda Maya voor katkestati ja mitu vooru
            # lõppes poolikult. Ilma selle loenduriga ei olnud 33% poolikute
            # vooru määra üldse võimalik logist näha.
            turn_stats = {"interrupted": 0, "turns": 0, "truncated": 0}
            # Kaamerakaadrite loendur ja baidisuuruse vahemik.
            _kaadrid = {"n": 0, "baite": 0, "min": 10 ** 9, "max": 0}
            # FAAS 4: kõnevooru elutsükkel. "turn_complete" EI ole kõne
            # tegelik lõpp (mediaantühik 8,2 s), seega hoiame oma olekut.
            turn_seq = {"n": 0}
            current_turn = {"t": None}
            # Viimane POOLELI jäänud voor + MILLAL. Ajatempel on uus:
            # mõõdetud defekt (10.11.2026) oli, et get_last_turn_state
            # tagastas 2 minutit 14 sekundit vana kirje vastuseks küsimusele
            # "miks sa praegu pooleli jäid?".
            last_cut_turn = {"t": None, "at": 0.0}
            last_user_speech = {"t": 0.0}
            empty_turns = {"n": 0}
            just_interrupted = {"v": False}

            def _turn() -> SpeechTurn:
                if current_turn["t"] is None:
                    turn_seq["n"] += 1
                    current_turn["t"] = SpeechTurn(
                        turn_seq["n"], active_persona, time.monotonic()
                    )
                return current_turn["t"]
            # ---------------------------------------------------------------
            # FAAS 1 + 2: DIAGNOSTIKA JA PASSIIVNE LIIGITUS
            # ---------------------------------------------------------------
            # Mõlemad on AINULT VAATLEVAD. Nad ei saada jätkamispalvet, ei
            # taasta seanssi, ei puuduta heli, VAD-i ega vestluse kulgu.
            # Olemasolev jätkamisloogika jääb muutumatuks.
            # Millist tööriista parajasti täidetakse. Vaatleja ja liigitus
            # vajavad seda, et legitiimset tööriistavaikust mudeli
            # seiskumisest eristada.
            tool_active = {"name": "", "since": 0.0}

            # Transpordi läbilaskevõime: üks logirida seansi kohta.
            rate_check = {"bytes": 0, "first_at": 0.0, "logged": False}

            def _diag_log(t_obj, trigger: str, user_speech_within_s=None):
                """Üks sisuta diagnostikarida + passiivne liigitus."""
                try:
                    now = time.monotonic()
                    d = t_obj.diag_dict(now)
                    k = classify_turn_end(
                        saw_turn_complete=t_obj.saw_turn_complete,
                        saw_interrupted=t_obj.saw_interrupted,
                        tail_is_terminal=d["tail_is_terminal"],
                        chars_per_audio_s=d["chars_per_audio_s"],
                        audio_s=d["audio_s"],
                        tail_len=d["tail_len"],
                        silence_s=d["silence_at_end_s"],
                        user_speech_within_s=user_speech_within_s,
                        failure_reason=t_obj.failure_reason or "",
                        # stall_s JÄÄB None – anormaalse pausi lävendit ei ole
                        # veel mõõdetud. Faas 1 kogub seda jaotust.
                        stall_s=None,
                        tool_running=bool(tool_active["name"]),
                    )
                    print(f"--> [DIAG voor #{t_obj.turn_id} {trigger}]: "
                          f"klass={k['class']} ({k['name']}) "
                          f"põhjus={k['reason']} jätkamine_kohane="
                          f"{k['continue_appropriate']} {d}", flush=True)
                    for n in k["notes"]:
                        print(f"--> [DIAG märkus]: {n}", flush=True)
                except Exception as _de:
                    # Diagnostika ei tohi MITTE KUNAGI kõnet lõhkuda.
                    print(f"--> [DIAG]: diagnostika ebaõnnestus: {_de}", flush=True)

            async def silence_observer():
                """Vaatleb rippuvat genereerimist. AINULT logib.

                MIKS SEE ERALDI TASK ON: vastuvõtutsükkel
                `async for response in session.receive()` BLOKEERUB, kui
                Gemini lakkab saatmast. Vooru-lõpu logimine elab selle
                tsükli sees ja seda ei käivitata kunagi – täpselt see on
                rippuva genereerimise pimeala. Eraldi task töötab edasi,
                sest sündmustsükkel jääb elama (sama tõestab olemasolev
                telemetry_ticker).

                Märgid SILENCE_OBSERVATION_MARKS_S ei ole lävendid. Taastet
                ei käivitata ühegi peal. Terve voor ei tekita ühtegi rida.
                """
                try:
                    while running:
                        await asyncio.sleep(SILENCE_OBSERVER_INTERVAL_S)
                        if not running:
                            break
                        t_obj = current_turn["t"]
                        if t_obj is None or t_obj.state != "streaming":
                            continue
                        if t_obj.last_audio_at is None:
                            continue
                        now = time.monotonic()
                        s = t_obj.silence_s(now)
                        # MÕÕDETUD DEFEKT (10.11.2026): tööriistakutse ajal
                        # jääb voor olekusse 'streaming' ja heli seisab
                        # LEGITIIMSELT – get_song_lyrics ajalimiit on 20 s.
                        # Ilma selle kontrolliga annaks üks laulusõnade
                        # otsing viis valehäire-rida (märgid 1,2,4,8,16 s) ja
                        # tõstaks observed_silence_s ~20 sekundini, rikkudes
                        # just selle jaotuse, mille mõõtmiseks faas 1 on.
                        tool_nimi = tool_active["name"]
                        if not tool_nimi:
                            if s > t_obj.observed_silence_s:
                                t_obj.observed_silence_s = s
                        for mark in SILENCE_OBSERVATION_MARKS_S:
                            if s >= mark and mark not in t_obj.silence_marks_emitted:
                                t_obj.silence_marks_emitted.add(mark)
                                print(
                                    f"--> [DIAG VAIKUS voor #{t_obj.turn_id}]: "
                                    f"heli seisnud {s:.2f} s (märk {mark:.0f} s), "
                                    f"turn_complete=EI interrupted="
                                    f"{t_obj.saw_interrupted} "
                                    f"generation_complete="
                                    f"{t_obj.saw_generation_complete} "
                                    f"saadetud_heli={t_obj.audio_seconds():.2f} s "
                                    f"hinnanguline_varu={t_obj.est_lead_s(now):.2f} s "
                                    f"max_paus={t_obj.max_gap_s:.3f} s "
                                    + (f"TÖÖRIIST='{tool_nimi}' töötab "
                                       f"({now - tool_active['since']:.1f} s) "
                                       f"– vaikus on OOTUSPÄRANE, jaotusest VÄLJAS "
                                       if tool_nimi else "")
                                    + "— VAATLUS, taastet EI käivitata",
                                    flush=True,
                                )
                except asyncio.CancelledError:
                    pass
                except Exception as _oe:
                    print(f"--> [DIAG]: vaikuse vaatleja lõppes: {_oe}", flush=True)

            def _registreeri(task):
                """Seanss OMAB iga taski: registreeri ja koristu ise."""
                _taustataskid.append(task)
                task.add_done_callback(
                    lambda t: _taustataskid.remove(t)
                    if t in _taustataskid else None)
                return task

            _suletud = {"v": False}
            # Sulgemise TULEMUS. `ok=False` = mõni task on veel elus.
            _sulgemine = {"ok": None, "oodatud": 0, "lopetamata": [],
                          "transport_katkestatud": False}

            async def _katkesta_transport(miks):
                """Võta Gemini WebSocketi alustransport maha.

                VIIMANE ABINÕU, ainult siis, kui task ei lõpe. TÕEND
                (websockets 17.3 lähtekood, tootmishost):
                `Connection.connection_lost()` teeb
                `for waiter in self.drain_waiters: waiter.set_result/
                set_exception`, seega `drain()` sees kinni olev
                `session.send` vabaneb kohe. `transport.abort()` on
                standardne asyncio `WriteTransport` meetod, mis sulgeb
                kohe ilma puhvri tühjendamist ootamata.

                SDK-s ei ole selleks avalikku API-t, seega loeme
                `session._ws` kaudu. Kui kuju muutub, logime selle
                välja ja EI väida, et sulgemine õnnestus.
                """
                _ws = getattr(session, "_ws", None)
                _tr = getattr(_ws, "transport", None)
                if _tr is None or not hasattr(_tr, "abort"):
                    print(f"--> [VOOG]: transporti EI SAA katkestada "
                          f"(ws={type(_ws).__name__}, "
                          f"transport={type(_tr).__name__}) – {miks}",
                          flush=True)
                    return False
                try:
                    _tr.abort()
                    print(f"--> [VOOG]: Gemini transport katkestatud "
                          f"({miks}) – vabastab kinni jäänud kirjutuse",
                          flush=True)
                    return True
                except Exception as _te:
                    print(f"--> [VOOG]: transpordi katkestamine "
                          f"ebaõnnestus: {_te}", flush=True)
                    return False

            async def _sulge_seanss(pohjus="normaalne lõpp"):
                """SEANSI AINUS SULGEMISPROTSEDUUR.

                Kutsutakse `async with` keha `finally`-st, seega ta
                jookseb LÕPUNI ENNE kui Gemini seansi kontekst sulgub.

                Idempotentne: korduv kutse tagastab sama tulemuse ega
                tühista midagi uuesti. Praegust taski ei tühista. Mälu
                konsolideerimise task EI OLE siin nimekirjas – tal on
                oma `_PENDING_MEMORY_TASKS` ja ta peab seansi üle
                elama.

                Tagastab {"ok", "lopetamata", "transport_katkestatud",
                "oodatud"}. `ok=False` tähendab, et mõni seansi task
                ON VEEL ELUS – seda me EI nimeta õnnestunud
                koristuseks.
                """
                if _suletud["v"]:
                    return _sulgemine
                _suletud["v"] = True
                nonlocal running
                # 1. UUT TÖÖD EI VÕETA VASTU.
                running = False
                # 2. OOTEL VOOGUTEGEVUSED KEHTETUKS.
                try:
                    flow.on_conversation_end()
                except Exception:
                    pass
                mina = asyncio.current_task()
                _taastetask["t"] = None
                # 3. TÜHISTA SEANSI TASKID (iga ÜKS kord).
                oota = []
                for t in list(_taustataskid):
                    if t is mina or t.done():
                        continue
                    if t not in _tyhistatud:
                        _tyhistatud.add(t)
                        t.cancel()
                    oota.append(t)

                def _loe_erindid(tehtud):
                    for _t in tehtud:
                        if _t.cancelled():
                            continue
                        try:
                            _e = _t.exception()
                        except Exception:
                            _e = None
                        if _e is not None:
                            print(f"--> [VOOG]: task {_t.get_name()} "
                                  f"lõppes erindiga: "
                                  f"{type(_e).__name__}: {_e}", flush=True)

                jaanud = set()
                katkestatud = False
                if oota:
                    # FAAS 1. `asyncio.wait` ajapiiranguga, MITTE
                    # `wait_for(gather(...))`: viimane tühistaks
                    # ajapiirangu peal lapsed TEIST korda (L3).
                    try:
                        tehtud, jaanud = await asyncio.wait(
                            oota, timeout=SULGEMISE_FAAS1_S)
                    except asyncio.CancelledError:
                        tehtud, jaanud = set(), set(oota)
                    _loe_erindid(tehtud)
                    # FAAS 2. Ainult siis, kui keegi on veel elus.
                    if jaanud:
                        print(f"--> [VOOG]: {len(jaanud)} taski ei "
                              f"lõppenud {SULGEMISE_FAAS1_S:.0f} s "
                              f"jooksul – eskaleerin", flush=True)
                        katkestatud = await _katkesta_transport(
                            "sulgemine: kinni jäänud task")
                        try:
                            tehtud2, jaanud = await asyncio.wait(
                                jaanud, timeout=SULGEMISE_FAAS2_S)
                        except asyncio.CancelledError:
                            tehtud2, jaanud = set(), jaanud
                        _loe_erindid(tehtud2)

                _sulgemine["ok"] = not jaanud
                _sulgemine["oodatud"] = len(oota)
                _sulgemine["lopetamata"] = sorted(
                    t.get_name() for t in jaanud)
                _sulgemine["transport_katkestatud"] = katkestatud
                if _kaadrid["n"]:
                    print(f"--> [KAAMERA KOKKUVÕTE]: {_kaadrid['n']} kaadrit, "
                          f"keskmine {_kaadrid['baite'] // _kaadrid['n']} B, "
                          f"vahemik {_kaadrid['min']}-{_kaadrid['max']} B",
                          flush=True)
                if jaanud:
                    # FAAS 3: AUS EBAÕNNESTUMINE.
                    print(f"--> [VOOG]: SULGEMINE EBAÕNNESTUS ({pohjus}): "
                          f"{len(jaanud)} seansi taski on VEEL ELUS: "
                          + ", ".join(_sulgemine["lopetamata"])
                          + ". Gemini seanss suletakse sellest hoolimata, "
                            "aga see EI OLE korrektne koristus.",
                          flush=True)
                else:
                    print(f"--> [VOOG]: seanss suletud ({pohjus}), "
                          f"taustataske oodati {len(oota)}"
                          + (", transport katkestatud"
                             if katkestatud else ""),
                          flush=True)
                return _sulgemine

            _sulgeja["f"] = _sulge_seanss

            # --- SAMM 1: DIAGNOSTIKA LOGIJA ------------------------
            # Seansi ID: Gemini oma, kui ta selle annab; muidu lokaalne
            # lühikood, et logiread ühe kõne kaupa kokku viia.
            _seansi_id = (getattr(session, "session_id", None)
                          or f"lok-{int(time.monotonic() * 1000) % 1000000}")
            print(f"--> [GEMINI META]: seanss={_seansi_id} "
                  f"karakter={active_persona} mudel={LIVE_MUDEL}", flush=True)

            def _logi_gemini_meta(sundmus, response=None, server_content=None):
                """ÜKS rida sisuka Gemini sündmuse kohta, saabumise HETKEL.

                Ei rekonstrueeri midagi hiljem: heli hulk ja meie
                klassifikatsioon loetakse elavast vooruobjektist just
                nüüd. Terve keha on erindikindel – diagnostika ei tohi
                kõnet maha võtta.
                """
                try:
                    m = gemini_meta_snapshot(response, server_content)
                    if not meta_on_sisukas(m):
                        return
                    # Vältimaks topeltridu: kui sõnumis on turn_complete /
                    # generation_complete / interrupted, logib selle oma
                    # nimeline konks allpool, mitte üldine "sonum".
                    if sundmus == "sonum" and any(
                            m.get(k) is True for k in
                            ("turn_complete", "generation_complete",
                             "interrupted")):
                        return
                    _t = current_turn["t"] or last_cut_turn["t"]
                    _saba = (tr_buf.get("assistant") or "").strip()
                    # Meie OLEMASOLEVA loogika hinnang SELLEL hetkel.
                    _meie = ("lopetatud" if (_saba and _saba[-1:] in TERMINAL_PUNCT)
                             else ("poolik" if _saba else "teksti_pole"))
                    print(
                        "--> [GEMINI META]: "
                        + json.dumps({
                            "seanss": _seansi_id,
                            "voor": getattr(_t, "turn_id", None),
                            "aeg": datetime.datetime.now(
                                ZoneInfo("Europe/Tallinn")).isoformat(
                                    timespec="milliseconds"),
                            "karakter": active_persona,
                            "mudel": LIVE_MUDEL,
                            "sundmus": sundmus,
                            "heli_s": (round(_t.audio_seconds(), 2)
                                       if _t is not None else None),
                            "heli_tykke": getattr(_t, "chunks", None),
                            "heli_juba_tehtud": bool(
                                _t is not None and _t.audio_seconds() > 0),
                            "meie_hinnang": _meie,
                            "saba_pikkus": len(_saba),
                            "meta": m,
                        }, ensure_ascii=False, default=str),
                        flush=True)
                except Exception as _me:
                    # EI TOHI kõnet maha võtta.
                    print(f"--> [GEMINI META]: logimine ebaõnnestus "
                          f"({type(_me).__name__}: {_me})", flush=True)

            def _voor_kehtib(epoch, *, nimi="taaste"):
                """Kas väljuv päring on VEEL asjakohane?

                Kutsutakse `gsend`-i luku all, vahetult enne saatmist.
                Tagastab (ok, põhjus).
                """
                if flow.state == conversation_flow.ENDED:
                    return (False, "vestlus on lõppenud")
                if fatal_state["reason"]:
                    return (False, "seanss on lõpliku tõrke järel")
                if not running:
                    return (False, "seanss suletakse")
                if _kasutaja_voor["n"] != epoch:
                    return (False, "kasutaja alustas uut vooru")
                if flow.state == conversation_flow.USER_SPEAKING:
                    return (False, "kasutajal on sõna")
                if just_interrupted["v"]:
                    return (False, "kasutaja katkestas")
                return (True, "")

            def _tyhista_ootel_taaste(pohjus):
                """Kasutaja võttis sõna / seanss lõpeb -> ootel taaste ära."""
                t = _taastetask["t"]
                _taastetask["t"] = None
                if t is not None and not t.done():
                    # Märgi tühistatuks, et sulgemine ei tühistaks teda
                    # TEIST korda (L3: teine cancel drenaaži ajal
                    # vabastaks saatmisluku enne kirjutamise lõppu).
                    _tyhistatud.add(t)
                    t.cancel()
                    print(f"--> [VOOG]: ootel taaste tühistatud ({pohjus})",
                          flush=True)
                    return True
                return False

            async def taaste_saatja(otsus, saba, epoch):
                """TAASTE OMA TASKIS.

                K5 PARANDUS (omaniku nõue 11.11.2026): varem tehti
                `await asyncio.sleep(wait_s)` vastuvõtutsükli `async for`
                keha sees, seega 0,6-1,2 s jooksul EI töödeldud kasutaja
                heli, `interrupted`-teateid ega transkriptsiooni.
                Kasutaja kõne ei tohi KUNAGI oodata taastetaimerit.
                Nüüd ootab see task eraldi ja vastuvõtutsükkel jookseb
                edasi; `taaste_saatja` ei ole kordagi vastuvõtutsükli
                poolt oodatud.
                """
                try:
                    if otsus["wait_s"] > 0:
                        await asyncio.sleep(otsus["wait_s"])
                    saadeti, miks = await gsend(
                        valideeri=lambda: _voor_kehtib(epoch),
                        # session.send(..., end_of_turn=True) – MITTE
                        # send_realtime_input. Viimane käivitab VAD-i ja
                        # KATKESTAB Maya (mõõdetud 08.11: "Palusin
                        # jätkata" -> 3 s hiljem "KATKESTUS pärast 0.0 s").
                        input=conversation_flow.RECOVERY_PROMPT,
                        end_of_turn=True)
                    if not saadeti:
                        flow.on_recovery_failed()
                        print(f"--> [VOOG]: taaste ära jäetud – {miks}",
                              flush=True)
                        return
                    flow.on_recovery_dispatched(saba, time.monotonic())
                    print(
                        f"--> [VOOG TAASTE {otsus['attempt']}/"
                        f"{otsus['budget']}]: palusin lõpetada pooleli "
                        f"jäänud lause (ootasin {otsus['wait_s']:.1f} s)",
                        flush=True)
                except asyncio.CancelledError:
                    # Tühistamine on NORMAALNE tee: kasutaja võttis sõna
                    # või seanss lõppes. Eelarvet ei tarbita, sest
                    # `on_recovery_dispatched` jäi kutsumata.
                    raise
                except Exception as jerr:
                    # Olek ei tohi jääda INCOMPLETE'iks, muidu on
                    # omaalgatus kuni kasutaja järgmise lauseni kinni.
                    flow.on_recovery_failed()
                    print(f"--> [VOOG]: taastepalve ebaõnnestus: {jerr}",
                          flush=True)
                finally:
                    if _taastetask["t"] is asyncio.current_task():
                        _taastetask["t"] = None

            async def initiative_ticker():
                """OMAALGATUS. Eraldi task, et `silence_observer` jääks
                PASSIIVSEKS – see invariant on väärtuslik ja faas 1-2
                testid kaitsevad seda.

                Intervall 0,5 s: karakteri paus on 5-14 s, seega 0,5 s
                lisab halvimal juhul 0,5 s – oluliselt vähem kui
                telemeetriatiksuja 2 s. Otsus tehakse LOKAALSELT;
                väljuv päring tehakse AINULT siis, kui flow.tick()
                annab loa, nii et Geminit ei küsitleta kordagi.
                """
                # Järjestikused SAATMISTÕRKED. Broneering antakse tõrke
                # korral tagasi (omaniku nõue), mistõttu eelarve ei
                # piira tõrkeid – ilma selle loendurita prooviks tiksuja
                # katkise pistiku peal iga 0,5 s uuesti. Mõõdetud:
                # 13 katset 130 ms jooksul. Kolm järjest = pistik on
                # katki, seanss lõpeb niikuinii mujal.
                _torkeid = {"n": 0}
                try:
                    while running:
                        await asyncio.sleep(INITIATIVE_TICK_S)
                        if not running:
                            break
                        _n = time.monotonic()
                        # KASUTAJA RÄÄGIB PRAEGU? `just_interrupted` EI
                        # sobi: see on True ainult katkestuse ja vooru
                        # lõpu vahel, mitte kasutaja kõne ajal. Kasutame
                        # kõne värskust – input_transcription uuendab
                        # last_user_speech iga fragmendi peale.
                        _rk = (_n - last_user_speech["t"]) < 2.0 \
                            if last_user_speech["t"] > 0 else False
                        _alg = flow.tick(
                            now=_n,
                            user_speaking=(_rk or just_interrupted["v"]),
                            tool_running=bool(tool_active["name"]))
                        if not _alg["speak"]:
                            continue
                        _sil = _n - flow.last_activity
                        # BRONEERI ENNE AWAIT-i. Muidu võib järgmine tiks
                        # (0,5 s) otsustada teist korda, kuni esimene
                        # session.send veel ootab -> kaks päringut.
                        flow.reserve_initiative(_n)
                        _ep = _kasutaja_voor["n"]
                        try:
                            # Valideerimine jookseb luku all, vahetult
                            # enne saatmist: broneering kaitseb
                            # kahekordse otsuse eest, aga mitte selle
                            # eest, et kasutaja võtaks luku ootamise
                            # ajal sõna. Omaalgatus on nüüd ka
                            # TAASTEGA eksklusiivne – kui taaste on
                            # ootel, keelab flow.tick selle juba ära
                            # (recovery_pending), ja kui taaste on
                            # lennus, on olek GENERATING.
                            _saadeti, _miks = await gsend(
                                valideeri=lambda: _voor_kehtib(_ep),
                                input=conversation_flow.initiative_prompt(
                                    _sil,
                                    has_prior_thought=(
                                        flow.assistant_said_something)),
                                end_of_turn=True)
                            if not _saadeti:
                                flow.release_initiative()
                                print(f"--> [VOOG]: omaalgatus ära jäetud "
                                      f"– {_miks}", flush=True)
                                continue
                            _torkeid["n"] = 0
                            print(
                                f"--> [VOOG OMAALGATUS {_alg['used']}/"
                                f"{_alg['budget']}]: kasutaja vaikis "
                                f"{_sil:.1f} s (karakteri paus "
                                f"{flow.initiative.pause_s:.0f} s) – "
                                f"andsin Mayale võimaluse ise jätkata",
                                flush=True)
                        except asyncio.CancelledError:
                            # L7: tühistamine saabub `gsend`-i sisse
                            # (sulgemine). `except Exception` EI püüa
                            # seda, mistõttu broneering jäi varem
                            # tagastamata ja olek `GENERATING` külge.
                            # Anname broneeringu tagasi ja laseme
                            # tühistuse EDASI – summutada ei tohi.
                            flow.release_initiative()
                            raise
                        except Exception as _ae:
                            # Broneering TULEB tagasi anda: tõrkunud katse
                            # ei ole ära kasutatud katse.
                            flow.release_initiative()
                            _torkeid["n"] += 1
                            print(f"--> [VOOG]: omaalgatus ebaõnnestus "
                                  f"({_torkeid['n']}/3): {_ae}", flush=True)
                            if _torkeid["n"] >= 3:
                                print("--> [VOOG]: 3 järjestikust "
                                      "saatmistõrget – omaalgatuse tiksuja "
                                      "lõpetab (vestlus ja taaste jätkuvad)",
                                      flush=True)
                                break
                except asyncio.CancelledError:
                    pass
                except Exception as _ie:
                    print(f"--> [VOOG]: omaalgatuse tiksuja lõppes: {_ie}",
                          flush=True)

            # Vaikuse valvur: tuvastab, et telefonist ei tule helikaadreid,
            # ENNE kui Gemini 120 s peal seansi maha kisub.
            silence_watchdog = ClientSilenceWatchdog(time.monotonic())

            # Üks lukk kõigi WebSocketi saatmiste ümber. Heli (bytes) ja
            # telemeetria/teated (text) tulevad eri taskidest – ilma lukuta
            # võiksid raamid põimuda.
            ws_send_lock = asyncio.Lock()

            # --- REAALAJAS SUBTIITRID ---
            # Transkriptsioon oli seni ainult serveri logis ([KASUTAJA ÜTLES] /
            # [MAYA ÜTLES]). Nüüd läheb see ka kliendile, et kasutaja NÄEKS,
            # mida kõnetuvastus kuulis. Praktikas eksib ASR tihti ("kol väga hea
            # õigus" = "sul on väga hea õigus") ja ilma subtiitriteta ei saa aru,
            # miks Maya imelikult vastab.
            # Fragmendid koondatakse ~250 ms kaupa, et mitte ujutada ühendust üle
            # ega võtta helipakettide eest saatmislukku liiga tihti.
            tr_buf = {"user": "", "assistant": ""}
            tr_last = {"user": 0.0, "assistant": 0.0}

            # --- OLEKUTEATED ORBILE ---
            # Server teab täpselt, millal tööriist töötab (nt laulusõnade otsing
            # võib kesta 20 s). Varem ei näinud kasutaja sel ajal MIDAGI ja ei
            # saanud aru, kas äpp elab. Nüüd ütleb orb seda ise.
            TOOL_LABELS = {
                "get_song_lyrics": "Otsin laulusõnu...",
                "get_weather": "Vaatan ilma...",
                "get_electricity_price": "Vaatan elektri hinda...",
                "get_email_status": "Kontrollin postkasti...",
                "get_reminders": "Vaatan kalendrit...",
                "add_reminder": "Salvestan kalendrisse...",
                "recall_memory": "Meenutan...",
                "set_user_name": "Panen nime meelde...",
                "get_last_turn_state": "Vaatan, mis juhtus...",
                "schedule_call": "Sean taimeri...",
            }

            async def push_state(state: str, label: str = ""):
                try:
                    async with ws_send_lock:
                        await websocket.send_text(json.dumps({
                            "type": "state", "state": state, "label": label,
                        }))
                except Exception:
                    pass

            async def flush_transcript(role: str, final: bool = False):
                txt = tr_buf.get(role, "")
                if not txt and not final:
                    return
                now_t = time.time()
                if not final and (now_t - tr_last.get(role, 0.0)) < 0.25:
                    return
                tr_last[role] = now_t
                tr_buf[role] = ""
                if not txt and final:
                    payload = {"type": "transcript", "role": role, "text": "", "final": True}
                else:
                    payload = {"type": "transcript", "role": role, "text": txt, "final": final}
                try:
                    async with ws_send_lock:
                        await websocket.send_text(json.dumps(payload))
                except Exception:
                    pass

            # --- KULUNÄIDIKU (HUD) SAATMINE – KEHTIB KÕIGILE KARAKTERITELE ---
            #
            # Varasem viga: ainus telemeetria saatmise koht oli kaamerakaadri
            # harus (`elif packet.get("type") == "image"`). See tähendas, et
            # HUD jõudis kliendini AINULT siis, kui kaamera oli sees. Tavalises
            # häälvestluses (kaamera väljas) ei saanud klient kunagi ühtegi
            # telemeetriapaketti ja liides näitas lõpuni kõvakodeeritud
            # algväärtust "⏱ 00:00 • 0.0 MB • Jääk: 3.46 €", samal ajal kui
            # tegelik jääk oli juba ~3.08 €. Kulud ARVUTATI kõigile korrektselt,
            # kuvati aga ainult kaameraga seanssidele – sellest mulje, nagu
            # töötaks arvestus vaid mõne karakteri puhul.
            #
            # Nüüd saadetakse HUD ühest kohast (send_to_client), seansi algusest
            # peale ja karakterist sõltumatult. Teadlikult EI saada me seda
            # mitmest korutiinist korraga – ühest taskist saatmine hoiab
            # WebSocketi raamid korras (varem saatis vastuvõtutask teksti ja
            # saatetask heli paralleelselt).
            async def push_telemetry(force: bool = False):
                if cost_tracker is None:
                    return
                now_t = time.time()
                if not force and (now_t - cost_tracker.last_hud_time) < 2.0:
                    return
                cost_tracker.last_hud_time = now_t
                try:
                    async with ws_send_lock:
                        await websocket.send_text(json.dumps({
                            "type": "telemetry",
                            "hud": cost_tracker.get_hud_string(),
                        }))
                except Exception:
                    pass

            # Esimene näit kohe seansi alguses, et liides ei jääks näitama
            # kõvakodeeritud algväärtust. Siin ei ole veel ühtegi taski käimas,
            # seega samaaegse saatmise riski pole.
            await push_telemetry(force=True)

            # HUD-i tiksuja: ilma selleta seisab näidik '00:00' peal, kui Maya
            # parajasti ei räägi. Kõnetestil oli see selgelt näha – 4 minutit
            # kõnet, näidik liikumatu.
            async def telemetry_ticker():
                try:
                    while running:
                        await asyncio.sleep(2.0)
                        if not running:
                            break
                        await push_telemetry(force=True)

                        # --- VAIKUSE VALVUR ---------------------------------
                        # FAAS C, LEID 3: kui telefonist ei tule helikaadreid,
                        # sulgeb Gemini seansi 120 s peal koodiga 1008 ja vana
                        # kood jäi surnud seansi peal tsüklisse. Nüüd tuvastame
                        # selle ise varem: 60 s peal hoiatame, 100 s peal
                        # lõpetame kõne KORREKTSELT ja selgitusega.
                        _now_mono = time.monotonic()
                        if silence_watchdog.silent_audio_status(_now_mono) == "warn":
                            print(
                                f"--> [LIVE WS HOIATUS]: Telefonist tuleb kaadreid, aga need on "
                                f"{silence_watchdog.silent_seconds(_now_mono):.0f} s läbinisti "
                                f"vaiksed – mikrofon on summutatud või kajavärav kinni. "
                                f"Maya ei kuule sind.",
                                flush=True,
                            )
                            try:
                                async with ws_send_lock:
                                    await websocket.send_text(json.dumps({
                                        "type": "mic_stalled",
                                        "text": "Mikrofonist tuleb ainult vaikus. Kontrollin...",
                                    }))
                            except Exception:
                                pass

                        sw_state = silence_watchdog.status(time.monotonic())
                        if sw_state == "warn":
                            idle = silence_watchdog.idle_seconds(time.monotonic())
                            print(
                                f"--> [LIVE WS HOIATUS]: Telefonist pole heli "
                                f"{idle:.0f} s – mikrofon võib olla seisma jäänud",
                                flush=True,
                            )
                            try:
                                async with ws_send_lock:
                                    await websocket.send_text(json.dumps({
                                        "type": "mic_stalled",
                                        "text": "Mikrofonist ei tule heli. Kontrollin ühendust...",
                                    }))
                            except Exception:
                                pass
                        elif sw_state == "expire":
                            fatal_state["reason"] = (
                                "Telefonist ei saabunud 100 sekundi jooksul ühtegi "
                                "helikaadrit, seega lõpetasin kõne ise. Tavaliselt "
                                "tähendab see, et mikrofon jäi seisma – ekraan kustus "
                                "või äpp läks taustale."
                            )
                            fatal_state["error"] = "client_silence_timeout"
                            print(
                                "--> [LIVE WS]: Vaikuse valvur lõpetab kõne "
                                "(100 s ilma heli) – ennetan Gemini 1008 tsüklit",
                                flush=True,
                            )
                            break
                except asyncio.CancelledError:
                    pass
                except Exception as tick_err:
                    print(f"--> [LIVE WS]: HUD-tiksuja lõppes: {tick_err}", flush=True)

            # Madala jäägi hoiatus: varem ei reageerinud jäägile MITTE MISKI –
            # number lihtsalt klammerdus nulli ja kõned jätkusid, kuni Google ise
            # keeldus (ja siis oli ainult vaikus).
            try:
                _bal = float((cost_tracker.state or {}).get("current_balance", 0)) if cost_tracker else 0.0
                if _bal <= 0.05:
                    await push_telemetry(force=True)
                    async with ws_send_lock:
                        await websocket.send_text(json.dumps({
                            "type": "notice",
                            "text": f"HOIATUS: Maya krediit on otsas (jääk {_bal:.2f} €). "
                                    f"Kõne võib iga hetk katkeda – siis võtab Tartu Mari üle.",
                        }))
                    print(f"--> [FINANTS HOIATUS]: jääk {_bal:.2f} € – krediit otsas", flush=True)
                elif _bal < 0.30:
                    async with ws_send_lock:
                        await websocket.send_text(json.dumps({
                            "type": "notice",
                            "text": f"Jääk on madal: {_bal:.2f} €.",
                        }))
                    print(f"--> [FINANTS HOIATUS]: madal jääk {_bal:.2f} €", flush=True)
            except Exception as _bal_err:
                print(f"--> [FINANTS]: jäägi kontroll ebaõnnestus: {_bal_err}", flush=True)

            print(
                f"--> [LIVE WS]: Kulunäidik aktiivne karakterile '{active_persona}': "
                f"{cost_tracker.get_hud_string() if cost_tracker else 'jälgija puudub'}",
                flush=True,
            )

            async def receive_from_client():
                # Loendame järjestikuseid mittefataalseid vigu: üksik tõrge ei
                # tohi kõnet lõpetada, kuid lõputult ka vigu ignoreerida ei saa.
                consecutive_errors = 0
                try:
                    while running:
                        try:
                            msg = await websocket.receive()
                        except WebSocketDisconnect:
                            print("--> [LIVE WS]: Klient katkestas ühenduse (WebSocketDisconnect)", flush=True)
                            break
                        if msg.get("type") == "websocket.disconnect":
                            # DIAGNOSTIKA: varem visati sulgemiskood minema ja me ei
                            # teadnud KUNAGI, miks kõne lõppes. Kood ütleb seda ära:
                            #   1000 = klient sulges korrektselt (nupuvajutus)
                            #   1001 = leht/äpp läks taustale või suleti
                            #   1005/1006 = ebanormaalne katkestus (võrk, WebView tapeti)
                            code = msg.get("code")
                            reason = msg.get("reason") or ""
                            tagid = {
                                1000: "korrektne sulgemine (nt kõne lõpetamise nupp)",
                                1001: "lahkumine – äpp läks taustale või suleti",
                                1005: "koodi ei antud",
                                1006: "EBANORMAALNE katkestus (võrk/WebView tapetud)",
                                1011: "serveripoolne viga",
                            }.get(code, "tundmatu põhjus")
                            # Kasutaja lõpetas ise -> järgmine kõne algab PUHTALT,
                            # mitte vana konteksti ja vana promptiga.
                            if code in (1000, 1001):
                                disarm_resume()
                            print(
                                f"--> [LIVE WS]: Klient sulges ühenduse – kood={code} ({tagid}) "
                                f"reason='{reason}'",
                                flush=True,
                            )
                            break
                        try:
                            if "bytes" in msg and msg["bytes"]:
                                # Telefonist tuli kaader. Eristame KUULDAVA heli
                                # digitaalsest vaikusest (läbinisti nullid): kui
                                # klient saadab ainult nulle, siis Maya ei kuule
                                # midagi, kuigi ühendus paistab tervena.
                                silence_watchdog.note_input(
                                    time.monotonic(), audible=any(msg["bytes"])
                                )
                                cost_tracker.add_audio_in(len(msg["bytes"]))
                                # DIAGNOSTIKA: transpordi läbilaskevõime.
                                # Ainult TOORNÄITAJAD, üks rida seansi kohta.
                                # EI klassifitseeri ega väida midagi mikrofoni
                                # sämplisageduse kohta – vt
                                # measure_transport_throughput() selgitust.
                                # Saadetavat payloadi ega mime_type'i ei muuda.
                                if not rate_check["logged"]:
                                    rate_check["bytes"] += len(msg["bytes"])
                                    if rate_check["first_at"] == 0.0:
                                        rate_check["first_at"] = time.monotonic()
                                    else:
                                        _tp = measure_transport_throughput(
                                            rate_check["bytes"],
                                            time.monotonic() - rate_check["first_at"])
                                        if _tp["ready"]:
                                            rate_check["logged"] = True
                                            print(
                                                f"--> [HELI SISEND TRANSPORT]: "
                                                f"{_tp['bytes']} B / {_tp['elapsed_s']:.2f} s "
                                                f"= {_tp['bytes_per_s']:.0f} B/s. "
                                                f"Deklareeritud mime_type eeldab "
                                                f"{DECLARED_INPUT_RATE_HZ} Hz "
                                                f"PCM16 mono. NB: see on transpordi "
                                                f"läbilaskevõime, MITTE mikrofoni "
                                                f"sämplisagedus – kajavärav, "
                                                f"puhverdamine ja puhangud mõjutavad "
                                                f"seda mõlemas suunas.",
                                                flush=True)
                                await grealtime(
                                    audio=types.Blob(
                                        data=msg["bytes"],
                                        mime_type="audio/pcm;rate=16000"
                                    )
                                )
                                consecutive_errors = 0
                            elif "text" in msg and msg["text"]:
                                try:
                                    packet = json.loads(msg["text"])
                                    if packet.get("type") == "text" and packet.get("text"):
                                        prompt_text = packet["text"]
                                        silence_watchdog.note_input(time.monotonic())
                                        await grealtime(text=prompt_text)
                                        # Ka klaviatuurilt saadetud viip on kasutaja voor –
                                        # see peab jõudma töömällu ja sealt arhiivi.
                                        # merge=False: tegu on tervikütlusega, mitte fragmendiga.
                                        working_mem.add_turn("user", prompt_text, merge=False)
                                        print(f"--> [LIVE WS]: Tekstiviip edastatud Geminile: {prompt_text}", flush=True)
                                    elif packet.get("type") == "playback":
                                        # KLIENDI TAASESITUSE TELEMEETRIA.
                                        # Täidab mõõdetud pimeala: server ei
                                        # teadnud kunagi, millal heli telefonis
                                        # PÄRISELT mängis (playback_confirmed
                                        # oli alati False). Ainult logitakse,
                                        # ükski otsus sellest ei sõltu.
                                        try:
                                            _pb = {k: packet.get(k) for k in (
                                                "reason", "first_played_ms",
                                                "last_played_ms", "scheduled_s",
                                                "played_s", "underruns",
                                                "rebuffers", "chunks",
                                                "received", "cancelled",
                                                "ctx_in_hz", "ctx_out_hz",
                                                "ctx_state")}
                                            # KORRELATSIOON VOORUGA: klient ei
                                            # tea voorunumbrit – server ei saada
                                            # seda talle. Seostame aruande
                                            # KÕIGE HILJUTISEMA lõppenud
                                            # vooruga, sest klient saadab
                                            # aruande taasesituse lõpus.
                                            # PIIRANG: kui kaks vooru lõpevad
                                            # enne aruande saabumist, võib
                                            # omistus eksida. Täpseks
                                            # seostamiseks oleks vaja serveril
                                            # voorunumber kliendile saata.
                                            _pt = current_turn["t"] or last_cut_turn["t"]
                                            _pb["voor"] = (_pt.turn_id if _pt else None)
                                            _pb["omistus"] = ("täpne"
                                                              if current_turn["t"]
                                                              else "hiljutisem")
                                            if _pt is not None:
                                                _pt.playback_confirmed = True
                                            # Kuuldud vs saadetud vahe on
                                            # kõige olulisem number: näitab,
                                            # kui palju kõnet kasutaja EI
                                            # kuulnud.
                                            try:
                                                _sch = float(_pb["scheduled_s"] or 0)
                                                _pl = float(_pb["played_s"] or 0)
                                                _pb["kuulmata_s"] = round(_sch - _pl, 3)
                                            except Exception:
                                                pass
                                            print(f"--> [TAASESITUS]: {_pb}",
                                                  flush=True)
                                        except Exception as _pe:
                                            print(f"--> [TAASESITUS]: vigane "
                                                  f"telemeetria: {_pe}", flush=True)
                                    elif packet.get("type") == "change_persona":
                                        # Klient saadab seda karakteri vahetamisel. Gemini
                                        # system_instruction fikseeritakse seansi loomisel,
                                        # seega KÄIMASOLEVA kõne karakterit muuta ei saa.
                                        # Varem ignoreeriti pakett vaikides ja liides väitis,
                                        # et vahetus õnnestus. Nüüd ütleme ausalt, kuidas on.
                                        wanted = str(packet.get("persona", "")).strip().lower()
                                        print(
                                            f"--> [LIVE WS]: change_persona '{active_persona}' -> '{wanted}' "
                                            f"(kehtib järgmisest kõnest)",
                                            flush=True,
                                        )
                                        if wanted and wanted != active_persona:
                                            try:
                                                async with ws_send_lock:
                                                    await websocket.send_text(json.dumps({
                                                        "type": "notice",
                                                        "text": f"Karakter '{wanted}' jõustub JÄRGMISES kõnes – "
                                                                f"praegune kõne jätkub karakteriga '{active_persona}'.",
                                                    }))
                                            except Exception:
                                                pass
                                    elif packet.get("type") == "image" and packet.get("data"):
                                        raw_b64 = packet["data"]
                                        if "," in raw_b64:
                                            raw_b64 = raw_b64.split(",", 1)[1]
                                        img_bytes = base64.b64decode(raw_b64)
                                        # Kaadri maht läheb kulusse; HUD-i saadab
                                        # send_to_client (üks saatekoht, vt push_telemetry).
                                        cost_tracker.add_image(len(img_bytes))

                                        # --- KAADRI DIAGNOSTIKA ----------
                                        # MÕÕDETUD PROBLEEM 11.11.2026: Maya
                                        # ütles "pime pilt ees", aga serveril
                                        # ei olnud ÜHTEGI näitajat kaadrite
                                        # kohta – ei arvu, ei suurust. Baidi-
                                        # suurus on odav PIMEDUSE MÕÕDIK:
                                        # must kaader pakitakse paari
                                        # kilobaidi peale, detailirikas 20-60
                                        # KB peale. Dekodeerimist pole vaja.
                                        # Logime iga 10. kaadri + seansi
                                        # kokkuvõtte, et logi üle ei ujutaks.
                                        _kaadrid["n"] += 1
                                        _kaadrid["baite"] += len(img_bytes)
                                        _kaadrid["min"] = min(_kaadrid["min"],
                                                              len(img_bytes))
                                        _kaadrid["max"] = max(_kaadrid["max"],
                                                              len(img_bytes))
                                        if _kaadrid["n"] % 10 == 1:
                                            print(f"--> [KAAMERA]: kaader "
                                                  f"#{_kaadrid['n']} "
                                                  f"{len(img_bytes)} B "
                                                  f"(keskmine "
                                                  f"{_kaadrid['baite'] // _kaadrid['n']} B, "
                                                  f"vahemik {_kaadrid['min']}-"
                                                  f"{_kaadrid['max']} B)",
                                                  flush=True)

                                        with open("/tmp/maya_frame.jpg", "wb") as f_img:
                                            f_img.write(img_bytes)

                                        # Saadame kaadri reaalajas videovoo taustale – Maya NÄEB kaadrit
                                        # ja saab seda küsimise peale kommenteerida.
                                        await grealtime(
                                            media=types.Blob(data=img_bytes, mime_type="image/jpeg")
                                        )

                                        # MÄRKUS: varasem automaatne sund-triger (iga 4 s saadeti kaader
                                        # koos käsuga "kommenteeri!") on teadlikult eemaldatud – see sundis
                                        # Maya pidevalt omaalgatuslikult vahele rääkima ja iga kaader on
                                        # eraldi tasuline. Server/ variandis oli see juba välja lülitatud;
                                        # just sellest muudatusest jäi maha orvuks jäänud sulg (süntaksiviga).
                                except Exception as json_err:
                                    print("--> [LIVE WS JSON ERR]:", json_err, flush=True)
                        except Exception as loop_err:
                            # MITTEFATAALNE: üksik tõrge (hetkeline võrgu- või
                            # Gemini viga, vigane kaader) EI tohi kõnet lõpetada.
                            # Varem lendas iga selline erind välja, vastuvõtutask
                            # lõppes ja asyncio.wait(FIRST_COMPLETED) kiskus kogu
                            # seansi maha – ühest kiiksust sai katkenud kõne.
                            consecutive_errors += 1
                            print(
                                f"--> [LIVE WS]: Mittefataalne tõrge vastuvõtus "
                                f"({consecutive_errors}/5): {type(loop_err).__name__}: {loop_err}",
                                flush=True,
                            )
                            if consecutive_errors >= 5:
                                print("--> [LIVE WS]: 5 järjestikust tõrget – lõpetan seansi", flush=True)
                                break
                            await asyncio.sleep(0.1)
                            continue
                except WebSocketDisconnect:
                    print("--> [LIVE WS]: Klient katkestas ühenduse (väline WebSocketDisconnect)", flush=True)
                except Exception as e:
                    if running:
                        print(f"--> [LIVE WS CLIENT ERR] (fataalne, kõne lõpeb): {type(e).__name__}: {e}", flush=True)
                finally:
                    print("--> [LIVE WS]: Kliendi vastuvõtt lõppes", flush=True)

            async def send_to_client():
                while running:
                    try:
                        async for response in session.receive():
                            if not running:
                                break

                            # Voog elab -> ajutised tõrked ei kogune.
                            #
                            # VIGA ENNE: loendur nullitati IGA vastuse peale.
                            # Kui viga kordus igal sõnumil (nt minu enda
                            # NameError 08.11), siis muster oli: vastus ->
                            # null -> viga -> vastus -> null -> viga... ja
                            # 5-vea piir ei rakendunud KUNAGI. Logis oli
                            # 20+ sama viga ühes kõnes ja kasutaja ei saanud
                            # ühtegi vastust. Nüüd nõuab nullimine mitut
                            # JÄRJESTIKUST veatut vastust.
                            gemini_ok["streak"] += 1
                            if gemini_ok["streak"] >= 5:
                                gemini_errors["count"] = 0

                            # Tööriistakutsed
                            if response.tool_call:
                                for call in response.tool_call.function_calls:
                                    call_id = call.id
                                    fn_name = call.name
                                    fn_args = call.args or {}
                                    print(f"--> [LIVE WS TÖÖRIIST KUTSE]: {fn_name} args={fn_args}", flush=True)

                                    # Täidetakse tööliskiibis -> helivoog ei katke.
                                    # Tagastab alati stringi, ka vea/ajalimiidi korral.
                                    await push_state("thinking", TOOL_LABELS.get(fn_name, "Töötlen..."))
                                    # FAAS 1 täpsustus: märgi, et vaikus on
                                    # nüüd tööriista oma, mitte mudeli
                                    # seiskumine.
                                    tool_active["name"] = fn_name
                                    tool_active["since"] = time.monotonic()
                                    if fn_name == "get_last_turn_state":
                                        # Seansi-lokaalne olek – ei saa minna
                                        # mooduli tasemel execute_tool_call'i.
                                        # AEGUMINE: mõõdetud defekt oli, et
                                        # tööriist tagastas 2 min 14 s vana
                                        # kirje vastuseks küsimusele "miks sa
                                        # praegu pooleli jäid?". Kirjel ei
                                        # olnud ajapiiri. CUT_TURN_TTL_S
                                        # katab tagasihelistamise ja kohese
                                        # järelküsimuse, aga mitte vanemat.
                                        _lc = last_cut_turn["t"]
                                        _lc_vanus = time.monotonic() - last_cut_turn["at"]
                                        if _lc is not None and _lc_vanus > CUT_TURN_TTL_S:
                                            print(f"--> [LIVE WS]: get_last_turn_state: "
                                                  f"kirje on {_lc_vanus:.0f} s vana "
                                                  f"(piir {CUT_TURN_TTL_S:.0f} s) – "
                                                  f"aegunud, ei kasuta", flush=True)
                                            last_cut_turn["t"] = None
                                            last_cut_turn["at"] = 0.0
                                            _lc = None
                                        if _lc is not None:
                                            res_str = _lc.summary_for_model()
                                            print(f"--> [LIVE WS]: get_last_turn_state -> "
                                                  f"{_lc.as_dict()} (vanus "
                                                  f"{_lc_vanus:.1f} s)", flush=True)
                                        else:
                                            # PARANDUS 10.11.2026: enne vastati
                                            # siin kohe "katkestusi pole", sest
                                            # `last_cut_turn` on seansi-lokaalne.
                                            # Nüüd küsime ka EELMISE kõne kohta.
                                            _prev = take_unfinished_turn(active_persona)
                                            if _prev:
                                                res_str = _eelmise_kone_kokkuvote(_prev)
                                                print(f"--> [LIVE WS]: get_last_turn_state -> "
                                                      f"EELMINE KÕNE jäi pooleli "
                                                      f"(voor #{_prev['turn_id']}, "
                                                      f"{_prev['reason']}, "
                                                      f"sama karakter="
                                                      f"{_prev['same_persona']})",
                                                      flush=True)
                                            else:
                                                res_str = (
                                                    "Selles kõnes ei ole ükski sinu voor "
                                                    "katkenud ja eelmisest kõnest ei ole "
                                                    "salvestatud katkestust. SIIT EI JÄRELDU, "
                                                    "et kasutaja eksib – tema kuuldud vaikusel "
                                                    "võib olla põhjus, mida see tööriist ei "
                                                    "näe (nt heli jäi telefoni puhvrisse või "
                                                    "kõne lõppes enne salvestamist). ÄRA väida, "
                                                    "et kõik oli korras, ja ÄRA ütle, et viga on "
                                                    "kasutaja pool. Ütle ausalt, et sa ei leia "
                                                    "selle kohta kirjet, ja küsi, mida ta kuulis."
                                                )
                                                print("--> [LIVE WS]: get_last_turn_state -> "
                                                      "kirjet ei ole (ei selles ega eelmises kõnes)",
                                                      flush=True)
                                    else:
                                        res_str = await execute_tool_call(fn_name, fn_args, active_persona)
                                    # Tööriist on valmis – edasine vaikus on
                                    # jälle mudeli oma.
                                    tool_active["name"] = ""
                                    tool_active["since"] = 0.0
                                    await push_state("listening", "Kuulan sind...")

                                    # function_response TULEB saata igal juhul: ilma selleta
                                    # ootab Gemini kutset lõputult ja heli ei tule enam üldse.
                                    try:
                                        tool_resp = types.LiveClientToolResponse(
                                            function_responses=[
                                                types.FunctionResponse(
                                                    id=call_id,
                                                    name=fn_name,
                                                    response={"result": res_str}
                                                )
                                            ]
                                        )
                                        await gsend(input=tool_resp)
                                    except Exception as send_err:
                                        print(
                                            f"--> [LIVE WS]: Tööriista vastuse saatmine ebaõnnestus "
                                            f"({fn_name}): {send_err}",
                                            flush=True,
                                        )

                            # Seansi taastamise pilet – saabub perioodiliselt.
                            _sru = getattr(response, "session_resumption_update", None)
                            if _sru is not None and getattr(_sru, "new_handle", None):
                                store_resume_handle(_sru.new_handle)

                            # Heli ja kõne edastus
                            server_content = response.server_content

                            # DIAGNOSTIKA: Gemini annab mitu eri signaali, millest
                            # me seni lugesime ainult turn_complete'i ja interrupted'it.
                            # Kui mudel peatab GENEREERIMISE ise, paistab see siin.
                            # NB: see plokk PEAB olema pärast server_content'i
                            # omistamist – esimesel katsel oli see enne ja iga
                            # vastus viskas NameError'i, mistõttu Maya ei saanud
                            # üldse rääkida.
                            # SAMM 1: metaandmete väljavõte SELLE sõnumi
                            # saabumise hetkel. `meta_on_sisukas` filtreerib
                            # välja puhtad helipaketid, nii et logi ei ujuta
                            # üle (593 tükki ühe vooru kohta).
                            _logi_gemini_meta("sonum", response, server_content)

                            if server_content is not None:
                                _gc = getattr(server_content, "generation_complete", None)
                                _is = getattr(server_content, "interaction_status", None)
                                if _gc:
                                    # FAAS 1: signaal märgitakse vooru külge,
                                    # mitte ainult logisse. Nii on hiljem
                                    # näha, kas rippuva genereerimise korral
                                    # saabub generation_complete ENNE
                                    # turn_complete'i puudumist – see oleks
                                    # varasem tuvastussignaal kui vaikus.
                                    _gt = current_turn["t"]
                                    if _gt is not None:
                                        _gt.saw_generation_complete = True
                                    print(f"--> [LIVE WS SIGNAAL]: generation_complete={_gc}", flush=True)
                                    # KÕIGE TÄHTSAM HETK: siin peatus
                                    # genereerimine. Just siin on vaja teada,
                                    # kas backend saatis lõpetamise põhjuse.
                                    _logi_gemini_meta("generation_complete",
                                                      response, server_content)
                                if _is:
                                    print(f"--> [LIVE WS SIGNAAL]: interaction_status={_is}", flush=True)

                            # --- MÄLU KIRJUTUSTEE: kõne transkriptsioonid ---
                            # Fragmendid liidetakse SessionWorkingMemory.add_turn's
                            # üheks vooruks, seega siin anname need edasi nii, nagu tulevad.
                            if server_content:
                                in_tr = getattr(server_content, "input_transcription", None)
                                if in_tr and getattr(in_tr, "text", None):
                                    # Kui viimane voor katkestati ja kasutaja
                                    # hakkas 5 s jooksul rääkima, siis oli tegu
                                    # TAHTLIKU vahelesegamisega, mitte tõrkega.
                                    _lc = last_cut_turn["t"]
                                    if (_lc is not None and _lc.interrupt_reason == "unknown"
                                            and _lc.ended_at is not None
                                            and time.monotonic() - _lc.ended_at <= 5.0):
                                        _lc.interrupt_reason = "user_speech"
                                        print(
                                            f"--> [LIVE WS]: Voor #{_lc.turn_id} katkestus "
                                            f"liigitatud: kasutaja hakkas rääkima",
                                            flush=True,
                                        )
                                        # FAAS 2: PARANDATUD liigitus. Katkestuse
                                        # hetkel ei ole kasutaja kõne veel
                                        # saabunud, seega esimene liigitus on
                                        # paratamatult H. Alles siin selgub, et
                                        # tegu oli B-ga. Mõlemad read logis
                                        # näitavad, kui hästi see 5 s aken
                                        # päriselt eristab.
                                        _diag_log(
                                            _lc, "reclassified",
                                            user_speech_within_s=(
                                                time.monotonic() - _lc.ended_at),
                                        )
                                    last_user_speech["t"] = time.monotonic()
                                    # UUS KASUTAJAVOOR = UUS AHEL.
                                    # Nullib taaste-eelarve, tühistab ootel
                                    # oleva taaste ja alustab vaikuse
                                    # lugemist otsast. Kasutaja kõne
                                    # katkestab nii taaste kui omaalgatuse
                                    # ALATI (omaniku nõue 1.4).
                                    _kasutaja_voor["n"] += 1
                                    flow.on_user_speech(time.monotonic())
                                    # KOHE, mitte ootamise lõpus: ootel
                                    # taaste task tühistatakse juba siin,
                                    # seega ta ei jõua isegi oma
                                    # valideerimiseni.
                                    _tyhista_ootel_taaste("kasutaja võttis sõna")
                                    working_mem.add_turn("user", in_tr.text)
                                    print(f"--> [KASUTAJA ÜTLES]: {in_tr.text.strip()}", flush=True)
                                    tr_buf["user"] += in_tr.text
                                    await flush_transcript("user")

                                out_tr = getattr(server_content, "output_transcription", None)
                                if out_tr and getattr(out_tr, "text", None):
                                    nonlocal_flags["output_transcription_seen"] = True
                                    _turn().note_text(out_tr.text)
                                    working_mem.add_turn("assistant", out_tr.text)
                                    print(f"--> [MAYA ÜTLES]: {out_tr.text.strip()}", flush=True)
                                    # Kasutaja rida loetakse lõpetatuks, kui Maya hakkab rääkima
                                    if tr_buf["user"]:
                                        await flush_transcript("user", final=True)
                                    tr_buf["assistant"] += out_tr.text
                                    await flush_transcript("assistant")

                            # --- VAHELESEGAMINE (BARGE-IN) ---------------------
                            # FAAS C, LEID 1: seda välja ei loetud KUNAGI.
                            # Gemini katkestab oma vooru kohe, kui kasutaja
                            # hakkab rääkima, ja annab siit teada. Kliendil on
                            # aga hetkeks ajastatud mitu sekundit heli ette
                            # (nextPlayTime), mida ta ilma käsuta tühistada ei
                            # saa -> Maya rääkis kasutajale peale. Nüüd ütleme
                            # kliendile, et ta viskaks järjekorra ära.
                            if server_content and getattr(server_content, "interrupted", False):
                                _logi_gemini_meta("interrupted",
                                                  response, server_content)
                                # DIAGNOSTIKA: logime ka selle, MIDA Maya parajasti
                                # ütles. Nii on näha, kas lause jäi poolikuks ja kas
                                # kasutaja tegelikult rääkis või oli tegu kajaga.
                                cut = (tr_buf["assistant"] or "").strip()
                                turn_stats["interrupted"] += 1
                                # FAAS 4: voor jääb ALLES. Varem kaotati siin
                                # pooleli jäänud tekst ja katkestuse fakt läks
                                # ainult logisse – Maya ei saanud hiljem
                                # küsimusele "miks sa pooleli jäid" vastata.
                                # Põhjuse märgime esialgu teadmatuks; kui
                                # 5 s jooksul saabub kasutaja transkriptsioon,
                                # täpsustatakse see "user_speech"-iks.
                                t_obj = _turn()
                                t_obj.saw_interrupted = True          # FAAS 1
                                t_obj.interrupt(time.monotonic(), reason="unknown")
                                # FAAS 1 + 2: sisuta diagnostika ja passiivne
                                # liigitus. Liigitus EI tegutse – katkestuse
                                # käsitlus allpool jääb täpselt selliseks,
                                # nagu ta oli.
                                _diag_log(t_obj, "interrupted")
                                last_cut_turn["t"] = t_obj
                                last_cut_turn["at"] = time.monotonic()
                                current_turn["t"] = None
                                # --- OOTEL OLEV JÄTKAMINE MUUTUB KEHTETUKS ---
                                # AUDITIS LEITUD VANANENUD OLEK: `ootel`
                                # nullitakse ainult turn_complete harus, kus
                                # `_ct is not None`. Katkestus seab
                                # `current_turn["t"] = None`, nii et järgnev
                                # turn_complete läheb TÜHJA VOORU harusse ja
                                # `ootel` jääb True. Siis krediteeritaks
                                # hilisem, täiesti seosetu voor ekslikult
                                # õnnestunud jätkamiseks (nõue 6).
                                #
                                # Nullime AINULT `ootel`. `n` ja `kokku`
                                # JÄÄVAD: katkestus ei ole õnnestumine
                                # (nõuded 3 ja 8), seega järjestikust piirangut
                                # ei tohi lõdvendada.
                                _tyhista_ootel_taaste("katkestus")
                                if flow.on_interrupted(time.monotonic()):
                                    print(
                                        f"--> [VOOG]: Katkestus muutis ootel "
                                        f"oleva taaste kehtetuks – eelarve "
                                        f"jääb {flow.recovery.used}/"
                                        f"{flow.recovery.budget}",
                                        flush=True)
                                # Vahetult järgnev turn_complete EI ole tühi
                                # voor, vaid selle katkestuse tagajärg.
                                just_interrupted["v"] = True
                                print(
                                    f"--> [LIVE WS KATKESTUS #{turn_stats['interrupted']}]: "
                                    f"voor #{t_obj.turn_id} katkestati pärast "
                                    f"{t_obj.audio_seconds():.1f} s heli. "
                                    f"Pooleli jäi: ...{cut[-70:]!r}",
                                    flush=True,
                                )
                                tr_buf["assistant"] = ""
                                try:
                                    async with ws_send_lock:
                                        await websocket.send_text(json.dumps({"type": "interrupted"}))
                                except Exception:
                                    pass
                                await push_state("listening", "Kuulan sind...")

                            if server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        _turn().note_audio(len(part.inline_data.data), time.monotonic())
                                        cost_tracker.add_audio_out(len(part.inline_data.data))
                                        async with ws_send_lock:
                                            await websocket.send_bytes(part.inline_data.data)
                                    if part.text:
                                        if getattr(part, "thought", False):
                                            print(f"--> [MAYA MÕTE]: {part.text.strip()}", flush=True)
                                        else:
                                            print(f"--> [MAYA]: {part.text.strip()}", flush=True)
                                            # Varutee: kui transkriptsioon on aktiivne, on see
                                            # juba salvestatud – väldime topeltkirjet.
                                            if not nonlocal_flags["output_transcription_seen"]:
                                                working_mem.add_turn("assistant", part.text, merge=False)

                            if server_content and server_content.turn_complete:
                                # SAMM 1: metaandmed ENNE meie klassifikatsiooni,
                                # et logis oleks näha, mida Gemini ütles ja mida
                                # meie sellest järeldasime.
                                _logi_gemini_meta("turn_complete",
                                                  response, server_content)
                                # DIAGNOSTIKA: kas voor lõppes terve lausega?
                                # Varem logiti ainult "Voor lõpetatud" ja poolik
                                # lause ei jätnud logisse mingit jälge.
                                turn_stats["turns"] += 1
                                _ct = current_turn["t"]
                                if _ct is not None:
                                    _ct.saw_turn_complete = True      # FAAS 1
                                    _ct.complete(time.monotonic())
                                    print(f"--> [LIVE WS VOOR]: {_ct.as_dict()}", flush=True)
                                    _diag_log(_ct, "turn_complete")   # FAAS 1+2
                                    # --- KAS SEE VOOR OLI JÄTKAMISE VASTUS? ---
                                    # MÕÕDETUD VIGA (filosoofi test, voor B#11):
                                    # jätkamisloendur nullitus AINULT kasutaja
                                    # kõne peale. Voor B#9 lõpetas lause edukalt,
                                    # aga loendur jäi ikka 1 peale, nii et
                                    # järgmine poolik voor jäi taastamata ja Maya
                                    # vaikis 14 s, kuni kasutaja ise toru ära pani.
                                    # Taaste otsus tehakse flow.on_turn_complete()
                                    # kaudu allpool – siin ainult olek maha.
                                    current_turn["t"] = None
                                else:
                                    # --- OOTEL OLEV JÄTKAMINE JÄI VASTUSETA ---
                                    # Teine pool samast auguast: turn_complete
                                    # saabus, aga kehtivat vooru ei ole. Siin
                                    # EI SAA olla jätkamise vastust (vooru
                                    # objekt puudub), seega ootel on kehtetu.
                                    # Nullitakse ENNE ülejäänud tühja vooru
                                    # loogikat, et see kehtiks igal alamteel.
                                    # `n` ja `kokku` jäävad puutumata.
                                    if flow.on_empty_turn_complete(time.monotonic()):
                                        print(
                                            f"--> [VOOG]: Ootel taaste jäi "
                                            f"vastuseta (turn_complete ilma vooru) "
                                            f"– eelarve jääb "
                                            f"{flow.recovery.used}/"
                                            f"{flow.recovery.budget}",
                                            flush=True)
                                    # TÜHI VOOR: Gemini lõpetas vooru, tootmata
                                    # ühtegi sõna, mõtet ega helibaiti.
                                    #
                                    # Mõõdetud 20 päeva logist: 26 juhtu, kus
                                    # tühi voor saabus mediaanis 1,09 s pärast
                                    # kasutaja viimast sõna (92% alla 1,5 s).
                                    # Kasutaja jääb siis vaikuse ette, ilma et
                                    # miski viitaks, et vastust ei tulegi –
                                    # ühel juhul ootas {USER} 17,5 sekundit.
                                    #
                                    # Põhjus on Gemini pool ja me ei saa seda
                                    # parandada. Küll aga saame selle NÄHTAVAKS
                                    # teha: logisse ja kasutajale.
                                    # VALEHÄIRE VÄLISTUS: kui kasutaja segas
                                    # vahele ENNE Maya esimest helibaiti, siis
                                    # polnudki midagi öelda – see on korrektne
                                    # käitumine, mitte tõrge. Mõõdetud: 6
                                    # tuvastatud tühjast voorust 4 olid just
                                    # sellised ja kasutaja nägi eksitavat
                                    # teadet "Maya ei vastanud".
                                    _idle = time.monotonic() - last_user_speech["t"]
                                    if just_interrupted["v"]:
                                        pass
                                    elif last_user_speech["t"] > 0 and _idle <= 3.0:
                                        empty_turns["n"] += 1
                                        _said = (tr_buf["user"] or "").strip()
                                        print(
                                            f"--> [LIVE WS TÜHI VOOR #{empty_turns['n']}]: "
                                            f"Gemini lõpetas vooru ilma vastuseta "
                                            f"{_idle:.2f} s pärast kasutaja kõnet. "
                                            f"Kasutaja ütles: ...{_said[-60:]!r}",
                                            flush=True,
                                        )
                                        try:
                                            async with ws_send_lock:
                                                await websocket.send_text(json.dumps({
                                                    "type": "no_reply",
                                                    "text": "Maya ei vastanud – proovi uuesti küsida.",
                                                }))
                                        except Exception:
                                            pass
                                # VIGA ENNE: siin loeti tr_buf["assistant"],
                                # AGA flush_transcript tühjendab selle iga
                                # subtiitrisaadetise järel (tr_buf[role] = "").
                                # Seega sisaldas see vooru lõpus ainult VIIMAST
                                # saatmata fragmenti – sageli 2-3 tähte – ja
                                # detektor kontrollis, kas just see fragment
                                # lõpeb punktiga. Logis andis see mõttetuid
                                # tulemusi nagu "0.1 tähem/s ...'nii'", kuigi
                                # voorus oli 198 tähemärki ja 28 s heli.
                                #
                                # SpeechTurn kogub note_text'iga KOGU vooru
                                # teksti ja seda ei tühjendata vahepeal.
                                # --- VESTLUSE ELUTSÜKLI OTSUS -------------
                                # Kogu otsus (taaste / loomulik lõpp /
                                # ootame kasutajat) tehakse ÜHES kohas:
                                # conversation_flow.ConversationFlow.
                                # Siin ainult täidetakse see, mida ta ütleb.
                                said = ((_ct.text if _ct is not None else "") or "").strip()
                                _tail_term = (said[-1:] in TERMINAL_PUNCT) if said else False
                                _audio_s = _ct.audio_seconds() if _ct is not None else 0.0
                                # Vaikuse lugemine algab TAASESITUSE hinnangulisest
                                # lõpust, mitte turn_complete'ist. Mõõdetud:
                                # est_lead_s on vooru lõpus ~0,31 s, seega
                                # taasesitus lõpeb umbes siis.
                                _now = time.monotonic()
                                _playback_end = _now + (
                                    _ct.est_lead_s(_now) if _ct is not None else 0.0)

                                _otsus = flow.on_turn_complete(
                                    text=said, tail_len=len(said),
                                    audio_s=_audio_s,
                                    tail_is_terminal=_tail_term,
                                    user_interrupted=just_interrupted["v"],
                                    tool_running=bool(tool_active["name"]),
                                    playback_end_est=_playback_end, now=_now)

                                if not _tail_term and said:
                                    turn_stats["truncated"] += 1
                                    # Suhtarv jääb logisse DIAGNOSTIKANA, aga ta
                                    # EI tõlgenda enam midagi (mõõdetud:
                                    # filosoofi loomulik tempo on 8-12 tähem/s
                                    # ja vana lävend 10,5 liigitas kõik viis
                                    # poolikut vooru valesti klassiks A).
                                    _suhe = (len(said) / _audio_s) if _audio_s > 0.5 else 0.0
                                    print(
                                        f"--> [LIVE WS HOIATUS]: Voor lõppes POOLIKU lausega "
                                        f"({turn_stats['truncated']}/{turn_stats['turns']}, "
                                        f"{_suhe:.1f} tähem/s – ainult diagnostika): "
                                        f"...{said[-70:]!r}",
                                        flush=True,
                                    )

                                if not _tail_term and said and _ct is not None:
                                    # MÕÕDETUD PIMEALA: `last_cut_turn` seati
                                    # AINULT katkestuse ja fataalse tõrke harus.
                                    # Klassi D voorud – täpselt need, mille
                                    # pärast kasutaja küsib "miks sa pooleli
                                    # jäid?" – ei jõudnud get_last_turn_state
                                    # tööriistani KUNAGI. Nüüd jõuavad.
                                    _ct.failure_reason = "premature_turn_complete"
                                    last_cut_turn["t"] = _ct
                                    last_cut_turn["at"] = time.monotonic()

                                # --- AJAJOON (§5) ---------------------
                                # Üks rida vooru kohta, serveri mõõdetud
                                # etapid. EI tee ühtegi lisapäringut.
                                # AUS PIIR: "mäng_algas" tuleb kliendi
                                # `playback` paketist ja seda praegune
                                # tootmis-APK ei saada – seni on see
                                # väli None ja seda EI tõlgendata kui
                                # kinnitatud taasesitust.
                                if _ct is not None:
                                    _aj_kone = (
                                        round(_ct.started_at
                                              - last_user_speech["t"], 3)
                                        if last_user_speech["t"] > 0 else None)
                                    print(
                                        f"--> [AJAJOON voor #{_ct.turn_id}]: "
                                        f"kasutaja_kõne->voor={_aj_kone}s "
                                        f"voor->esimene_heli="
                                        f"{_ct.first_audio_latency_s}s "
                                        f"heli_kestus={_audio_s:.2f}s "
                                        f"voor->lõpp="
                                        f"{round(_now - _ct.started_at, 3)}s "
                                        f"mäng_algas="
                                        f"{'jah' if _ct.playback_confirmed else 'teadmata'}",
                                        flush=True)
                                print(f"--> [VOOG]: voor #{_ct.turn_id if _ct else '?'} "
                                      f"-> olek={flow.state} otsus={_otsus['reason']} "
                                      f"taaste={_otsus['recover']} "
                                      f"eelarve={flow.recovery.used}/{flow.recovery.budget}",
                                      flush=True)

                                if _otsus["recover"]:
                                    # --- TAASTE ----------------------------
                                    # EI OODATA SIIN. Vastuvõtutsükkel peab
                                    # jääma vabaks kasutaja heli vastu
                                    # võtma; ootamine elab omas taskis.
                                    # Mõõdetud: palve saatmine ise võtab
                                    # 1-3 ms, aga 2. ja 3. katse
                                    # tagasiastumine on 0,6 ja 1,2 s – just
                                    # need blokeerisid varem tsüklit.
                                    _tyhista_ootel_taaste("uus taasteotsus")
                                    _taastetask["t"] = _registreeri(
                                        asyncio.create_task(
                                            taaste_saatja(
                                                _otsus, said,
                                                _kasutaja_voor["n"])))

                                # Lipp nullitakse vooru LÕPUS, pärast seda, kui
                                # nii tühja vooru kontroll kui jätkamisotsus on
                                # seda lugenud. Ilma selleta summutaks see KÕIK
                                # järgnevad teated.
                                just_interrupted["v"] = False
                                reason = getattr(server_content, "turn_complete_reason", None)
                                print(
                                    f"--> [LIVE WS]: Voor lõpetatud, seanss jääb avatuks "
                                    f"(mälus {len(working_mem.turns)} vooru"
                                    + (f", põhjus={reason}" if reason else "")
                                    + f", katkestusi {turn_stats['interrupted']})",
                                    flush=True,
                                )
                                # Vooru lõpus lõpetame pooleli subtiitriread
                                await flush_transcript("user", final=True)
                                await flush_transcript("assistant", final=True)
                                # Maya lõpetas rääkimise -> orb tagasi kuulamisrežiimi
                                await push_state("listening", "Kuulan sind...")
                                # Vooru lõpus kindlasti värske näit (ka siis, kui
                                # 2-sekundiline piirik muidu vahele jätaks)
                                await push_telemetry(force=True)

                            # Jooksev HUD iga Gemini vastuse järel, piiratud 2 s-ga.
                            # See on AINUS perioodiline saatekoht ja see töötab
                            # igas vestluses, sõltumata karakterist ja kaamerast.
                            await push_telemetry()

                    except WebSocketDisconnect:
                        break
                    except Exception as e:
                        if not running:
                            break

                        verdict = classify_live_failure(e)
                        print(
                            f"--> [LIVE WS GEMINI ERR] ({verdict['kind']}, "
                            f"kood={verdict['code']}): {e}",
                            flush=True,
                        )

                        # FAAS C, LEID 2: varem oli siin ainult sleep(0.5) ja
                        # `while running` kordas surnud seansi peal lõputult
                        # (tootmises 189 korda / 94 s). Lõpliku tõrke korral
                        # lõpetame kõne ise ja ÜTLEME kasutajale põhjuse.
                        if verdict["kind"] == "fatal":
                            fatal_state["reason"] = verdict["message"]
                            fatal_state["error"] = str(e)
                            # PARANDUS 10.11.2026: siin oli TERMINAALSE
                            # SÜNDMUSE AUK. Fataalne tõrge tappis seansi
                            # keset vooru, aga pooleliolevat `SpeechTurn`-i
                            # ei märgitud kunagi ebaõnnestunuks – `fail()`
                            # oli surnud kood. Tagajärg: järgmises seansis
                            # ütles get_last_turn_state "katkestusi pole" ja
                            # Maya suunas põhjuse kasutaja kaela (mõõdetud
                            # arhiivivoorud 982 -> 983).
                            _ft = current_turn["t"]
                            if _ft is not None and _ft.state != "completed":
                                _ft.fail(time.monotonic(),
                                         verdict["code"] or "fatal")
                                last_cut_turn["t"] = _ft
                                last_cut_turn["at"] = time.monotonic()
                                _diag_log(_ft, "fatal_error")
                                store_unfinished_turn(
                                    _ft, active_persona,
                                    f"Gemini lõpetas seansi koodiga "
                                    f"{verdict['code'] or 'teadmata'}")
                                current_turn["t"] = None
                            break

                        gemini_errors["count"] += 1
                        gemini_ok["streak"] = 0
                        if gemini_errors["count"] >= 5:
                            fatal_state["reason"] = (
                                "Gemini vooga tekkis 5 järjestikust tõrget – lõpetan kõne."
                            )
                            fatal_state["error"] = str(e)
                            print("--> [LIVE WS]: 5 järjestikust Gemini tõrget – lõpetan", flush=True)
                            break

                        # Astmeline ooteaeg, et mitte tekitada tühikäigutsüklit.
                        await asyncio.sleep(min(0.5 * gemini_errors["count"], 3.0))

            # --- SEANSI KEHA ------------------------------------
            # try/finally on `async with` SEES, et sulgemine jõuaks
            # lõpuni ENNE Gemini seansi konteksti väljumist. Katab
            # normaalse lõpu, WebSocketDisconnecti, CancelledError'i,
            # transporditõrke ja serveri seiskamise – kõik lähevad
            # läbi sama finally.
            try:
                # KÕIK kolm põhitaski on seansi OMANDIS. Varem
                # tühistati neid ainult `for task in pending` kaudu,
                # mis jääb vahele, kui `asyncio.wait` ise
                # CancelledError'iga katkeb (WebSocketDisconnect,
                # serveri seiskamine) – siis lekkisid nad samamoodi
                # nagu vaatleja ja tiksuja.
                client_task = _registreeri(
                    asyncio.create_task(receive_from_client()))
                gemini_task = _registreeri(
                    asyncio.create_task(send_to_client()))
                ticker_task = _registreeri(
                    asyncio.create_task(telemetry_ticker()))
                # FAAS 1: vaikuse vaatleja. Eraldi task, sest vastuvõtutsükkel
                # blokeerub rippuva genereerimise ajal. Ootekomplekti ta EI kuulu –
                # vaatleja ei tohi kunagi kõne lõppu otsustada. Ta tühistatakse
                # allpool koos ülejäänud pooleliolevate taskidega.
                observer_task = _registreeri(
                    asyncio.create_task(silence_observer()))
                # Omaalgatus: eraldi task, ootekomplekti EI kuulu (ei tohi
                # kõne lõppu otsustada). Tühistatakse allpool.
                initiative_task = _registreeri(
                    asyncio.create_task(initiative_ticker()))
                # Olekumasina lõpetamine ja `running` lipp peavad käima ka
                # järsu katkemise korral – finally kutsub selle välja.
                def _lopeta_voog():
                    try:
                        flow.on_conversation_end()
                    except Exception:
                        pass
                _lopetajad.append(_lopeta_voog)

                # FAAS C: ka tiksuja kuulub ootekomplekti – vaikuse valvur elab
                # selle sees ja peab saama kõne KORREKTSELT lõpetada. Varem jäi
                # tiksuja ootest välja, mistõttu selle otsus ei lõpetanud midagi.
                done, pending = await asyncio.wait(
                    [client_task, gemini_task, ticker_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # LIPP KOHE MAHA, veel enne tõrketeavitust. Teavitus
                # sisaldab await'e (`websocket.send_text`,
                # `mari_takeover`), mille ajal tiksuja jõuaks muidu veel
                # ühe omaalgatuse saata. Tühistamine jääb ikka ainult
                # `_sulge_seanss()`-i, aga lipp maksab selle vahe kinni.
                running = False
                # TÜHISTAMIST SIIN EI OLE. Kõik taskid – `pending`,
                # vaatleja, omaalgatuse tiksuja ja ootel taaste –
                # tühistatakse ja OODATAKSE ÄRA täpselt ühes kohas:
                # `_sulge_seanss()` allpool olevas finally's. Varem oli
                # tühistamine kolmes kohas laiali, mistõttu osa taske
                # tühistati kaks korda (L3) ja ootel taaste alles pärast
                # Gemini seansi sulgemist (L1).
                # `done`-taskide erindid loeme välja, et asyncio ei
                # kurdaks "Task exception was never retrieved" (L8).
                for _d in done:
                    if not _d.cancelled():
                        _de = _d.exception()
                        if _de is not None:
                            print(f"--> [LIVE WS]: task {_d.get_name()} "
                                  f"lõppes erindiga: "
                                  f"{type(_de).__name__}: {_de}", flush=True)

                # --- LÕPLIKU TÕRKE TEAVITUS ------------------------------------
                # FAAS C, LEID 4: sisemiste taskide lõplikud tõrked (tootmises
                # 18 x 1007) lõpetasid kõne TÄIESTI vaikselt – mari_takeover oli
                # kinni ainult välimise try küljes ja seda ei jõutud kunagi.
                # Nüüd saab kasutaja alati teada, MIKS kõne lõppes.
                if fatal_state["reason"]:
                    print(
                        f"--> [LIVE WS]: Kõne lõpetati lõpliku tõrke tõttu: "
                        f"{fatal_state['reason']}",
                        flush=True,
                    )
                    try:
                        async with ws_send_lock:
                            # Taastatav = mööduv Gemini-poolne tõrge, mille
                            # järel on mõtet kohe uuesti ühenduda. Kvoodi lõpp
                            # ja mikrofoni seiskumine EI ole taastatavad –
                            # nende puhul uuesti proovimine ainult raiskaks.
                            _v = classify_live_failure(fatal_state["error"])
                            _recoverable = _v["code"] in (1007, 1011)
                            if _recoverable:
                                arm_resume(f"kood {_v['code']}")
                            else:
                                disarm_resume()
                            await websocket.send_text(json.dumps({
                                "type": "call_ended",
                                "text": fatal_state["reason"],
                                "recoverable": _recoverable,
                            }))
                    except Exception:
                        pass
                    # Krediidi/kvoodi tõrke korral räägib Mari põhjuse ka ette.
                    if any(k in fatal_state["error"].lower()
                           for k in ("quota", "resource_exhausted", "429", "billing")):
                        try:
                            await mari_takeover(websocket, fatal_state["error"])
                        except Exception as mari_err:
                            print(f"--> [MARI ÜLEVÕTMINE EBAÕNNESTUS]: {mari_err}", flush=True)
            finally:
                await _sulge_seanss(
                    fatal_state['reason'] or 'normaalne lõpp')

    except Exception as e:
        print("--> [LIVE WS GENERAL ERR]:", e, flush=True)
        # VARUVARIANT: Tartu Mari ütleb kasutajale, MIS juhtus – varem jäi
        # kasutaja lihtsalt vaikuse ette ega saanud aru, kas äpp on katki.
        try:
            await mari_takeover(websocket, str(e))
        except Exception as mari_err:
            print(f"--> [MARI ÜLEVÕTMINE EBAÕNNESTUS]: {mari_err}", flush=True)
    finally:
        # VARUVARIANT. Tavaolukorras on `_sulge_seanss()` juba jooksnud
        # `async with` keha finally's ja see kutse on no-op
        # (idempotentne). Siia jõuab tõeliselt tööle ainult siis, kui
        # seanss suri ENNE taskide loomist – nt `live.connect` ise
        # ebaõnnestus. Mälu konsolideerimist see EI puuduta.
        running = False
        if _sulgeja["f"] is not None:
            try:
                await _sulgeja["f"]("välimine finally")
            except Exception as _se:
                print(f"--> [VOOG]: sulgemine ebaõnnestus: {_se}",
                      flush=True)
        for _l in _lopetajad:
            _l()
        # Kuluarvestus salvestatakse enne mälu konsolideerimist: server/ variandis
        # ei kutsutud save_session() kunagi välja, mistõttu jääki ei kirjutatud
        # kunagi faili ja iga uus seanss alustas samast numbrist.
        if cost_tracker is not None:
            cost_tracker.save_session()

        print(
            f"--> [LIVE WS]: Sessioon suletud, konsolideerin mälu "
            f"({len(working_mem.turns)} vooru)...",
            flush=True,
        )
        try:
            # Hoiame tugevat viidet, muidu võib prügikoristaja poolelioleva
            # konsolideerimise (arhiiv + faktide eraldamine) katkestada.
            mem_task = asyncio.create_task(
                memory_engine.consolidate_session_to_memory(
                    working_mem, persona=active_persona
                )
            )
            _PENDING_MEMORY_TASKS.add(mem_task)
            mem_task.add_done_callback(_PENDING_MEMORY_TASKS.discard)
        except Exception as me_err:
            print("--> [LIVE WS MÄLU VIGA]:", me_err, flush=True)

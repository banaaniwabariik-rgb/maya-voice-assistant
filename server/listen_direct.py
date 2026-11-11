class TTSResult(str):
    def __new__(cls, path, used_voice="maya", is_fallback=False, fallback_reason=""):
        obj = super().__new__(cls, path)
        obj.path = path
        obj.used_voice = used_voice
        obj.is_fallback = is_fallback
        obj.fallback_reason = fallback_reason
        return obj

import os
import config  # MAYA seadistus (vt server/config.py)
import features_pack
import json
import asyncio
import random
import datetime
import sqlite3
import subprocess
import requests
import re
import shutil
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
# --- TELEGRAM (PYROGRAM) — TAANDATUD, VALIKULINE SÕLTUVUS ---
# See moodul imporditakse web_maya.py poolt kui `core` AINULT mälu- ja
# TTS-abifunktsioonide pärast (13 sümbolit). Pyrogrami Telegrami-haru
# (kasutajakonto-klient) ei käivitu kunagi importimisel: app.run() on
# ainult `if __name__ == "__main__"` all. Varem oli pyrogram siiski KÕVA
# impordisõltuvus ja Client konstrueeriti importimise ajal.
# NB: see EI puuduta aktiivset mentorbot.service / bot_listen.py teenust,
# mis kasutab Telegrami HTTP Bot API-t ega sõltu pyrogramist.
try:
    from pyrogram import Client, filters, raw
    from pyrogram.types import Message
    PYROGRAM_AVAILABLE = True
except Exception as _pyro_err:  # pragma: no cover
    PYROGRAM_AVAILABLE = False

    class _StubNamespace:
        """Ohutu asendus, et dekoraatori argumendid (nt filters.chat(ID))
        saaks importimise ajal hinnata ka siis, kui pyrogram puudub."""
        def __getattr__(self, name):
            def _noop(*a, **k):
                return None
            return _noop

    Client = None
    filters = _StubNamespace()
    raw = _StubNamespace()
    Message = object
    print(f"[listen_direct] Pyrogram puudub ({_pyro_err}) – Telegrami haru on välja lülitatud, "
          f"mälu- ja TTS-funktsioonid töötavad edasi.", flush=True)
from groq import Groq
from google import genai
from google.genai import types

API_ID = 34054351
API_HASH = "af381bb07fc8865df268146407a46382"
TARGET_ID = 7693525686

BASE_DIR = str(config.JUUR)
ENV_PATH = os.path.join(BASE_DIR, ".env")
MEMORY_PATH = os.path.join(BASE_DIR, "memory.json")
KNOWLEDGE_PATH = os.path.join(BASE_DIR, "knowledge.json")
DB_PATH = config.DB_TEE
STATE_PATH = os.path.join(BASE_DIR, "agent_state.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

os.makedirs(BACKUP_DIR, exist_ok=True)

SLEEP_START_HOUR = 23
SLEEP_END_HOUR = 8

ALLOWED_SERVICES = ["nginx", "docker", "ssh", "cron", "fail2ban"]

CHAT_HISTORY = []
LAST_INTERACTION_TIME = None
ACTIVE_TIMERS = {}

groq_key = os.getenv("GROQ_API_KEY")
tavily_key = os.getenv("TAVILY_API_KEY")
gemini_key = os.getenv("GEMINI_API_KEY")

if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str.startswith("GROQ_API_KEY=") and not groq_key:
                groq_key = line_str.split("=", 1)[1].strip().strip('"').strip("'")
            elif line_str.startswith("TAVILY_API_KEY=") and not tavily_key:
                tavily_key = line_str.split("=", 1)[1].strip().strip('"').strip("'")
            elif line_str.startswith("GEMINI_API_KEY=") and not gemini_key:
                gemini_key = line_str.split("=", 1)[1].strip().strip('"').strip("'")

# --- VALIKULISED KLIENDID ------------------------------------------
# AVALIKU VERSIOONI PARANDUS: varem loodi mõlemad kliendid mooduli
# tasemel tingimusteta, nii et PUUDUV võti viskas ImportError'i juba
# `import listen_direct` peale – uus kasutaja ei saanud isegi
# andmebaasi luua. Nüüd käitume täpselt nagu selle faili enda
# Telegrami haru (vt `_TelegramDisabled` allpool): puuduv võti
# lülitab ainult selle haru välja ja ütleb selle logis välja.
# Olemasoleva võtmega on käitumine TÄPSELT sama mis varem.
if groq_key:
    groq_client = Groq(api_key=groq_key)
else:
    groq_client = None
    print("[listen_direct] GROQ_API_KEY puudub – kõnetuvastuse (Whisper) "
          "haru on välja lülitatud. Gemini Live hääl töötab edasi.",
          flush=True)

if gemini_key:
    gemini_client = genai.Client(api_key=gemini_key)
else:
    gemini_client = None
    print("[listen_direct] GEMINI_API_KEY puudub – Gemini tekstipäringud "
          "on välja lülitatud. Vt .env.example.", flush=True)
GEMINI_MODEL = "gemini-flash-lite-latest"

class _TelegramDisabled:
    """Asendus, kui Telegrami haru ei ole aktiveeritud.

    Varem loodi `Client(...)` juba mooduli importimisel, mis tähendas, et
    web_maya protsess konstrueeris Telegrami kliendi, mida ta kunagi ei
    kasutanud. Nüüd saab seda teha ainult otsekäivitusel. Iga katse
    Telegrami funktsiooni kasutada annab selge vea, mitte vaikiva tõrke.
    """
    def __getattr__(self, name):
        def _unavailable(*a, **k):
            raise RuntimeError(
                f"Telegrami haru ei ole aktiveeritud (app.{name}). "
                f"Käivita listen_direct.py otse, et Telegrami klient luua."
            )
        return _unavailable

    def on_message(self, *a, **k):
        # Dekoraator peab importimisel töötama, aga ei registreeri midagi
        def _decorator(fn):
            return fn
        return _decorator


# Telegrami klient luuakse AINULT siis, kui moodul käivitatakse otse.
if PYROGRAM_AVAILABLE and __name__ == "__main__":
    app = Client("albert_user", api_id=API_ID, api_hash=API_HASH, workdir=BASE_DIR)
else:
    app = _TelegramDisabled()

# --- GEMINI ABIFUNKTSIOONID ---
def ask_gemini(prompt: str, system_instruction: str = "", temperature: float = 0.7) -> str:
    """Küsib Geminilt teksti minimaalsete piirangutega."""
    try:
        safety = [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ),
        ]
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction if system_instruction else None,
            safety_settings=safety
        )
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config
        )
        # Kontrollime, kas Gemini tagastas teksti või blokeeriti sisu
        if response and response.text:
            return response.text.strip()
        else:
            print("Gemini API hoiatus: Vastus blokeeriti turvafiltri poolt (tekst puudub).", flush=True)
            return "__FILTER_BLOCKED__"
    except Exception as e:
        print(f"Gemini API viga: {e}", flush=True)
        return "Mul tekkis hetkeks mõttepaus, proovi korra uuesti."

def ask_gemini_json(prompt: str) -> dict:
    """Küsib Geminilt puhta JSON vastuse."""
    try:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config
        )
        return json.loads(response.text.strip())
    except Exception as e:
        print(f"Gemini JSON viga: {e}", flush=True)
        return {}

# --- OLEKUFAIL ---
def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Oleku salvestamise viga:", e, flush=True)

# --- ANDMEBAAS ---
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_time TEXT NOT NULL,
            reminder_text TEXT NOT NULL,
            is_done INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logbook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            category TEXT,
            entry_text TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            date_str TEXT NOT NULL,
            weekday_str TEXT NOT NULL,
            user_text TEXT NOT NULL,
            reply_text TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_archive_date ON conversation_archive(date_str)")
    conn.commit()
    conn.close()

def add_reminder(trigger_time_iso: str, reminder_text: str):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders (trigger_time, reminder_text, is_done) VALUES (?, ?, 0)",
        (trigger_time_iso, reminder_text)
    )
    conn.commit()
    conn.close()

def get_due_reminders():
    now_iso = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, trigger_time, reminder_text FROM reminders WHERE trigger_time <= ? AND is_done = 0",
        (now_iso,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def auto_expire_old_reminders():
    now_iso = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET is_done = 1 WHERE trigger_time < ? AND is_done = 0", (now_iso,))
    conn.commit()
    conn.close()

def get_upcoming_reminders(limit_days=7) -> str:
    now = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    now_iso = now.strftime("%Y-%m-%d %H:%M")
    end_iso = (now + datetime.timedelta(days=limit_days)).strftime("%Y-%m-%d 23:59")
    
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute(
        "SELECT trigger_time, reminder_text FROM reminders WHERE trigger_time >= ? AND trigger_time <= ? AND is_done = 0 ORDER BY trigger_time ASC",
        (now_iso, end_iso)
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return "Sul ei ole praegu selleks perioodiks ühtegi meeldetuletust ootel."
    lines = [f"- {r[0]}: {r[1]}" for r in rows]
    return "Eelseisvad sündmused ja meeldetuletused:\n" + "\n".join(lines)

def mark_reminder_done(reminder_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("UPDATE reminders SET is_done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

# --- OSTUNIMEKIRI ---
def add_shopping_items(items: list):
    now_iso = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    for it in items:
        clean_it = it.strip().capitalize()
        if clean_it:
            cur.execute("INSERT INTO shopping_list (item, added_at) VALUES (?, ?)", (clean_it, now_iso))
    conn.commit()
    conn.close()

def get_shopping_items() -> list:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT id, item FROM shopping_list ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def remove_shopping_item_by_name(query: str) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT id, item FROM shopping_list")
    rows = cur.fetchall()
    matched_ids = [r[0] for r in rows if query.lower() in r[1].lower()]
    if matched_ids:
        cur.executemany("DELETE FROM shopping_list WHERE id = ?", [(i,) for i in matched_ids])
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def clear_shopping_list():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.cursor()
    cur.execute("DELETE FROM shopping_list")
    conn.commit()
    conn.close()

# --- MÄLU JA TEADMUSBAAS ---
def load_memory() -> list:
    if not os.path.exists(MEMORY_PATH):
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_memory_items(facts_list: list):
    facts = load_memory()
    now_str = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%d.%m.%Y %H:%M")
    existing_lower = [item.get("fact", "").lower() for item in facts]
    for f in facts_list:
        f_clean = str(f).strip()
        if f_clean and f_clean.lower() not in existing_lower:
            facts.append({"date": now_str, "fact": f_clean})
            existing_lower.append(f_clean.lower())
            print(f"Automaatselt mällu salvestatud: {f_clean}", flush=True)
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)


def log_conversation_turn(user_text: str, reply_text: str):
    try:
        now = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")
        weekday_str = now.strftime("%A")
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO conversation_archive (timestamp, date_str, weekday_str, user_text, reply_text)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, date_str, weekday_str, user_text, reply_text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Viga vestluse arhiveerimisel: {e}", flush=True)

def lookup_past_conversations(user_query: str) -> str:
    import re
    triggers = ['rääkisime', 'räägitud', 'mäletad', 'eile', 'üleeile', 'nädal tagasi', 'kuud tagasi', 'päeval', 'mäletad kui', 'mis me tegime', 'mis jutt oli']
    q_lower = user_query.lower()
    if not any(t in q_lower for t in triggers) and not any(m in q_lower for m in ['jaanuar', 'veebruar', 'märts', 'aprill', 'mai', 'juuni', 'juuli', 'august', 'september', 'oktoober', 'november', 'detsember', '2024', '2025', '2026']):
        return ''

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cur = conn.cursor()
        words = [re.sub(r'[^a-zA-ZõäöüÕÄÖÜ0-9]', '', w) for w in q_lower.split()]
        words = [w for w in words if len(w) >= 4 and w not in ['millest', 'kuidas', 'rääkisime', 'mäletad', 'olime', 'oleme', 'tegid']]

        rows = []
        if words:
            query_clauses = ' OR '.join(['user_text LIKE ? OR reply_text LIKE ?' for _ in words])
            params = []
            for w in words:
                params.extend([f'%{w}%', f'%{w}%'])
            cur.execute(f'SELECT timestamp, weekday_str, user_text, reply_text FROM conversation_archive WHERE {query_clauses} ORDER BY id DESC LIMIT 6', params)
            rows = cur.fetchall()

        if not rows:
            cur.execute('SELECT timestamp, weekday_str, user_text, reply_text FROM conversation_archive ORDER BY id DESC LIMIT 4')
            rows = cur.fetchall()

        conn.close()

        if not rows:
            return ''

        context_lines = ['\n[MEIE ENDISTE VESTLUSTE ARHIIV (ELEVANDI MÄLU)]:']
        for ts, wday, u_txt, r_txt in reversed(rows):
            context_lines.append(f'Aeg: {ts} ({wday})\nKasutaja: {u_txt}\nMaya: {r_txt}\n---')
        return '\n'.join(context_lines) + '\n'
    except Exception as e:
        print(f'Viga arhiivi otsingul: {e}', flush=True)
        return ''

def format_memory_for_prompt() -> str:
    facts = load_memory()
    if not facts:
        return ""
    lines = [f"- {item['fact']}" for item in facts[-25:]]
    return "\n[KASUTAJA KOHTA SALVESTATUD ISIKLIKUD FAKTID]:\n" + "\n".join(lines) + "\n"

def load_knowledge() -> list:
    if not os.path.exists(KNOWLEDGE_PATH):
        return []
    try:
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_knowledge_item(topic: str, content: str):
    items = load_knowledge()
    now_str = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%d.%m.%Y %H:%M")
    items.append({"date": now_str, "topic": topic, "content": content})
    with open(KNOWLEDGE_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"Teadmusbaasi lisatud: [{topic}] {content}", flush=True)

def delete_knowledge_item(topic_query: str) -> bool:
    items = load_knowledge()
    initial_len = len(items)
    filtered = [it for it in items if topic_query.lower() not in it.get("topic", "").lower() and topic_query.lower() not in it.get("content", "").lower()]
    if len(filtered) < initial_len:
        with open(KNOWLEDGE_PATH, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
        return True
    return False

def format_knowledge_for_prompt() -> str:
    items = load_knowledge()
    if not items:
        return ""
    lines = [f"- [{it['topic']}]: {it['content']}" for it in items[-25:]]
    return "\n[ALBERTI TEADMUSBAAS JA SALVESTATUD MÄRKMED]:\n" + "\n".join(lines) + "\n"

def check_and_extract_memories(user_text: str):
    markers = ["minu", "olen", "nimi on", "mul on", "kaalun", "pikk", "sentimeetrit", "kilo", "aastane"]
    if not any(m in user_text.lower() for m in markers):
        return []
    prompt = (
        f"Lause: \"{user_text}\".\n"
        "Tuvasta sellest KÕIK kasutaja enda kohta käivad püsivad faktid (nimi, elukoht, kaal, pikkus jne).\n"
        "Vasta JSON formaadis: {\"facts\": [\"Kasutaja nimi on ...\"]}"
    )
    res = ask_gemini_json(prompt)
    return res.get("facts", [])

# --- TEENUSTE JUHTIMINE (SYSTEMCTL SERVICE CONTROL) ---
def control_service(action: str, service: str) -> str:
    service = service.lower().strip()
    if service not in ALLOWED_SERVICES:
        return f"Turvapiirang: teenuse '{service}' haldamine pole lubatud nimekirjas."
    try:
        if action == "status":
            out = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True).stdout.strip()
            return f"Teenuse {service} staatus on: {out}."
        elif action == "restart":
            res = subprocess.run(["sudo", "systemctl", "restart", service], capture_output=True, text=True)
            if res.returncode == 0:
                return f"Teenus {service} edukalt taaskäivitatud."
            return f"Teenuse {service} taaskäivitus ebaõnnestus: {res.stderr[:100]}"
    except Exception as e:
        return f"Viga teenuse juhtimisel: {e}"
    return "Tundmatu tegevus."

# --- DEVOPS FUNKTSIOONID ---
def perform_backup() -> str:
    try:
        now_tag = datetime.datetime.now(ZoneInfo("Europe/Tallinn")).strftime("%Y%m%d_%H%M%S")
        target_sub = os.path.join(BACKUP_DIR, f"backup_{now_tag}")
        os.makedirs(target_sub, exist_ok=True)
        if os.path.exists(DB_PATH):
            shutil.copy2(DB_PATH, os.path.join(target_sub, "reminders.db"))
        if os.path.exists(MEMORY_PATH):
            shutil.copy2(MEMORY_PATH, os.path.join(target_sub, "memory.json"))
        if os.path.exists(KNOWLEDGE_PATH):
            shutil.copy2(KNOWLEDGE_PATH, os.path.join(target_sub, "knowledge.json"))
        total_kb = sum(os.path.getsize(os.path.join(target_sub, f)) for f in os.listdir(target_sub)) // 1024
        return f"Varukoopia edukalt tehtud kausta backup_{now_tag}, maht {total_kb} kilobaiti."
    except Exception as e:
        return f"Varukoopia tegemine ebaõnnestus: {e}"

def clean_system_cache() -> str:
    try:
        subprocess.run(["journalctl", "--vacuum-time=3d"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        removed_count = 0
        for f in os.listdir(BASE_DIR):
            if (f.endswith(".wav") or f.endswith(".ogg")) and f not in ["reply.ogg", "morning_briefing.ogg", "evening_briefing.ogg"]:
                try:
                    os.remove(os.path.join(BASE_DIR, f))
                    removed_count += 1
                except Exception:
                    pass
        return f"Serveri hooldus tehtud: logid kärbitud ja eemaldatud {removed_count} ajutist faili."
    except Exception as e:
        return f"Puhastuse viga: {e}"

def get_recent_errors() -> str:
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "albert-voice", "-p", "err..emerg", "-n", "5", "--no-pager"], 
            text=True
        ).strip()
        if not out or "No entries" in out:
            return "Albert teatab: süsteemilogis vigu ei leidu, kõik töötab stabiilselt."
        lines = [line.split(": ", 1)[-1] for line in out.split("\n") if ": " in line]
        clean_summary = "; ".join(lines[-2:])
        return f"Viimane tõrge logis: {clean_summary[:200]}"
    except Exception as e:
        return f"Logi lugemisel viga: {e}"

# --- SERVERI MONITOORIMINE ---
def get_system_status() -> str:
    try:
        df_out = subprocess.check_output(["df", "-h", "/"], text=True).strip().split("\n")[-1]
        df_parts = df_out.split()
        disk_total, disk_used, disk_avail = df_parts[1], df_parts[2], df_parts[3]

        free_out = subprocess.check_output(["free", "-h"], text=True).strip().split("\n")[1]
        free_parts = free_out.split()
        mem_total, mem_used, mem_avail = free_parts[1], free_parts[2], free_parts[6]

        uptime_out = subprocess.check_output(["uptime"], text=True).strip()

        return (
            f"Ketas: vaba {disk_avail} (kokku {disk_total}, kasutusel {disk_used})\n"
            f"RAM: vaba {mem_avail} (kokku {mem_total}, kasutusel {mem_used})\n"
            f"Koormus: {uptime_out}"
        )
    except Exception as e:
        return f"Serveri staatuse viga: {e}"

def check_server_health_alert() -> str:
    try:
        df_out = subprocess.check_output(["df", "/"], text=True).strip().split("\n")[-1]
        percent_str = re.findall(r"(\d+)%", df_out)
        if percent_str and int(percent_str[0]) >= 90:
            return f"Hoiatus: serveri põhiketas on {percent_str[0]}% täis!"
    except Exception:
        pass
    return ""

# --- ERR UUDISTEVOO LUGEMINE ---
def fetch_err_news_items(topic="uudised"):
    try:
        rss_url = "https://www.err.ee/rss"
        if "majandus" in topic:
            rss_url = "https://majandus.err.ee/rss"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(rss_url, headers=headers, timeout=6)
        root = ET.fromstring(res.content)
        parsed = []
        for idx, item in enumerate(root.findall("./channel/item")[:5], 1):
            title = item.find("title").text if item.find("title") is not None else ""
            desc = item.find("description").text if item.find("description") is not None else ""
            link = item.find("link").text if item.find("link") is not None else ""
            clean_desc = re.sub(r"<[^>]+>", "", desc).strip()
            if title:
                parsed.append({"nr": idx, "title": title, "desc": clean_desc, "link": link})
        return parsed
    except Exception as e:
        print("RSS viga:", e, flush=True)
        return []

def extract_web_text(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        html = res.text
        html = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL)
        clean = re.sub(r"<[^>]+>", " ", html)
        clean = " ".join(clean.split())
        return clean[:4500]
    except Exception as e:
        print(f"Lingi viga ({url}):", e, flush=True)
        return ""

# --- ELEKTRI BÖRSIHINNAD ---
def fetch_elering_data():
    try:
        tz = ZoneInfo("Europe/Tallinn")
        now = datetime.datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = today_start + datetime.timedelta(days=2)
        
        start_iso = today_start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:00:00.000Z")
        end_iso = end_time.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:00:00.000Z")
        
        url = f"https://dashboard.elering.ee/api/nps/price?start={start_iso}&end={end_iso}"
        res = requests.get(url, timeout=6).json()
        return res.get("data", {}).get("ee", [])
    except Exception as e:
        print("Eleringi viga:", e, flush=True)
        return []

def get_electricity_overview() -> str:
    ee_data = fetch_elering_data()
    if not ee_data:
        return ""
    try:
        tz = ZoneInfo("Europe/Tallinn")
        now = datetime.datetime.now(tz)
        current_ts = int(now.timestamp())
        current_price = None
        current_slot = ""
        today_prices = []
        tomorrow_prices = []

        tomorrow_date_str = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        today_date_str = now.strftime("%Y-%m-%d")

        for item in ee_data:
            ts = item.get("timestamp")
            price_mwh = item.get("price", 0)
            price_snt = round(price_mwh / 10, 2)
            dt_start = datetime.datetime.fromtimestamp(ts, tz=tz)
            dt_end = dt_start + datetime.timedelta(hours=1)
            
            dt_date = dt_start.strftime("%Y-%m-%d")
            time_slot = f"{dt_start.strftime('%H:00')}–{dt_end.strftime('%H:00')}"
            hour_int = dt_start.hour

            if ts <= current_ts < ts + 3600:
                current_price = price_snt
                current_slot = time_slot

            if dt_date == today_date_str:
                today_prices.append((time_slot, price_snt, hour_int))
            elif dt_date == tomorrow_date_str:
                tomorrow_prices.append((time_slot, price_snt, hour_int))

        lines = []
        if current_price is not None:
            lines.append(f"Hetke elektri börsihind (vahemikus {current_slot}): {current_price} senti/kWh.")

        target_list = tomorrow_prices if tomorrow_prices else today_prices
        period_name = "homme" if tomorrow_prices else "täna"

        if target_list:
            min_slot, min_p, _ = min(target_list, key=lambda x: x[1])
            lines.append(f"{period_name.capitalize()} on absoluutselt soodsaim tund kell {min_slot} ({min_p} s/kWh).")

            awake_list = [item for item in target_list if SLEEP_END_HOUR <= item[2] < SLEEP_START_HOUR]
            if awake_list:
                awake_min_slot, awake_min_p, _ = min(awake_list, key=lambda x: x[1])
                lines.append(f"Sinu ärkveloleku ajal ({SLEEP_END_HOUR}:00–{SLEEP_START_HOUR}:00) on soodsaim kell {awake_min_slot} (hind {awake_min_p} senti/kWh).")
                if len(awake_list) >= 2:
                    best_2h = min([((awake_list[i][1] + awake_list[i+1][1])/2, f"{awake_list[i][0].split('–')[0]}–{awake_list[i+1][0].split('–')[1]}") for i in range(len(awake_list)-1)], key=lambda x: x[0])
                    lines.append(f"Parim 2-tunnine tarbimisaken ärkvel olles on kell {best_2h[1]} (keskmine {round(best_2h[0], 2)} s/kWh).")
        else:
            lines.append("Homseid elektri börsihindu pole Eleringis veel avaldatud (tulevad kella 14:00 paiku).")

        return "\n".join(lines)
    except Exception as e:
        print("Eleringi analüüsi viga:", e, flush=True)
        return ""

# --- ILM (OPEN-METEO: OHTU / KEILA) ---
def get_weather_forecast() -> str:
    try:
        w = features_pack.get_detailed_weather(location_name="Ohtu külas")
        if not w:
            return "Ilmaprognoosi pärimine ebaõnnestus."
        txt = f"Ilm Ohtu külas: {w.get('current_temp')}°C, tuul {w.get('current_wind')} m/s. "
        if w.get("rain_upcoming"):
            txt += f"Sajuhoiatus: vihma oodata kellaaegadel: {', '.join(w.get('rain_details', []))}. "
        else:
            txt += "Lähitundidel sademeid ei tule. "
        if w.get("min_temp_12h", 99) <= 0:
            txt += f"Öökülma hoiatus: temperatuur võib langeda kuni {w.get('min_temp_12h')} kraadini. "
        return txt
    except Exception as e:
        print("Ilma viga:", e, flush=True)
    return ""

# --- TAVILY OTSING ---
def tavily_search(query: str) -> str:
    if not tavily_key:
        return ""
    try:
        url = "https://api.tavily.com/search"
        payload = {"api_key": tavily_key, "query": query, "search_depth": "basic", "max_results": 4}
        res = requests.post(url, json=payload, timeout=8)
        data = res.json()
        snippets = []
        for r in data.get("results", []):
            snippets.append(f"- {r.get('title', '')}: {r.get('content', '')}")
        return "\n".join(snippets)
    except Exception as e:
        print("Tavily viga:", e, flush=True)
        return ""

# --- HÄÄLESÜNTEES ---
def tts_generate_long(text: str, filename: str, voice_choice: str = "maya") -> tuple[str, str, bool, str]:
    clean = re.sub(r"[*#_\[\]`|•]", "", text).strip()
    raw_pcm = os.path.join(BASE_DIR, f"{filename}_raw.pcm")
    ogg_path = os.path.join(BASE_DIR, f"{filename}.ogg")
    wav_path = os.path.join(BASE_DIR, f"{filename}.wav")

    voice_choice = (voice_choice or "maya").strip().lower()
    used_voice = voice_choice
    is_fallback = False
    fallback_reason = ""

    # Kui kasutaja valis ise otseselt Tartu Mari
    if voice_choice == "mari":
        try:
            r = requests.post(
                "https://api.tartunlp.ai/text-to-speech/v2",
                json={"text": clean[:450], "speaker": "mari"},
                timeout=25
            )
            with open(wav_path, "wb") as f:
                f.write(r.content)
            subprocess.run([
                "ffmpeg", "-y", "-i", wav_path, "-af", "apad=pad_dur=0.6", "-c:a", "libopus", "-b:a", "48k", ogg_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
                return TTSResult(ogg_path, "mari", False, "")
        except Exception as e:
            print("TartuNLP Mari otsene viga:", e, flush=True)

    # 1. PÕHIHÄÄL (kui valitud Maya): Google Gemini TTS (Aoede)
    try:
        from google.genai import types
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=clean,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                    )
                )
            )
        )
        audio_bytes = res.candidates[0].content.parts[0].inline_data.data
        with open(raw_pcm, "wb") as f:
            f.write(audio_bytes)

        subprocess.run([
            "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", raw_pcm, "-c:a", "libopus", "-b:a", "32k", ogg_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(raw_pcm):
            os.remove(raw_pcm)
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            return TTSResult(ogg_path, "maya", False, "")
    except Exception as e:
        err_str = str(e)
        print("Gemini TTS (Aoede) viga, lülitun automaatselt Tartu Mari peale:", err_str, flush=True)
        is_fallback = True
        used_voice = "mari"
        if "429" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower():
            fallback_reason = "Aoede päevalimiit / kvoot täis"
        else:
            fallback_reason = "Aoede ühenduse viga"

    # 2. AUTOMAATNE VARUHÄÄL: TartuNLP Mari
    try:
        r = requests.post(
            "https://api.tartunlp.ai/text-to-speech/v2",
            json={"text": clean[:450], "speaker": "mari"},
            timeout=25
        )
        with open(wav_path, "wb") as f:
            f.write(r.content)
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path, "-af", "apad=pad_dur=0.6", "-c:a", "libopus", "-b:a", "48k", ogg_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(wav_path):
            os.remove(wav_path)
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            return TTSResult(ogg_path, used_voice, is_fallback, fallback_reason)
    except Exception as e:
        print("Kriitiline viga ka TartuNLP Mariga:", e, flush=True)

    return TTSResult(ogg_path, used_voice, is_fallback, fallback_reason)

# --- KÕNED JA MEELDETULETUSED ---
async def make_telegram_call():
    try:
        peer = await app.resolve_peer(TARGET_ID)
        await app.invoke(raw.functions.phone.RequestCall(
            user_id=peer,
            random_id=random.randint(1, 2147483647),
            g_a_hash=os.urandom(32),
            protocol=raw.types.PhoneCallProtocol(
                min_layer=93, max_layer=93, udp_p2p=True, library_versions=["1.0.0"]
            )
        ))
    except Exception as e:
        print("Helistamise viga:", e, flush=True)

async def execute_reminder(reminder_id: int, reminder_text: str):
    mark_reminder_done(reminder_id)
    print(f"--> Täidan meeldetuletuse: {reminder_text}", flush=True)
    await make_telegram_call()
    await asyncio.sleep(4)
    ogg_file = tts_generate_long(f"Tervist! Siin on meeldetuletus: {reminder_text}", f"rem_{reminder_id}")
    await app.send_voice(TARGET_ID, ogg_file, caption=f"🔔 Meeldetuletus:\n{reminder_text[:900]}")

# --- TAIMERI TÄITMINE ---
async def run_timer_countdown(seconds: int, name: str):
    try:
        await asyncio.sleep(seconds)
        if name in ACTIVE_TIMERS:
            del ACTIVE_TIMERS[name]
        print(f"--> Taimer lõppes: {name}", flush=True)
        await make_telegram_call()
        await asyncio.sleep(4)
        msg_text = f"Taimer '{name}' sai läbi!" if name != "Taimer" else "Taimer sai läbi!"
        ogg_file = tts_generate_long(msg_text, "timer_done")
        await app.send_voice(TARGET_ID, ogg_file, caption=f"⏱️ {msg_text}")
    except asyncio.CancelledError:
        print(f"Taimer '{name}' tühistati.", flush=True)

# --- PROAKTIIVNE BRIEFINK, ÕHTUNE KOKKUVÕTE JA ELEKTRIHOIATUS ---
async def send_morning_briefing():
    print("Koostan hommikust briifingut Gemini abil...", flush=True)
    weather = get_weather_forecast()
    electricity = get_electricity_overview()
    reminders = get_upcoming_reminders(limit_days=1)
    news = fetch_err_news_items()
    news_text = "; ".join([f"{n['title']}" for n in news[:2]]) if news else ""
    
    prompt = (
        f"Koosta lühike, elav ja vaimukas hommikune ülevaade (maksimaalselt 3-4 lauset), mida on hea kuulata.\n"
        f"Ilm Ohtus: {weather}\n"
        f"Elekter: {electricity}\n"
        f"Tänased sündmused: {reminders}\n"
        f"Värske uudis: {news_text}\n"
    )
    briefing_text = ask_gemini(prompt, temperature=0.7)
    print(f"Hommikune briifing: {briefing_text}", flush=True)
    
    await make_telegram_call()
    await asyncio.sleep(4)
    ogg_file = tts_generate_long(briefing_text, "morning_briefing")
    await app.send_voice(TARGET_ID, ogg_file, caption=f"🌅 Hommikune ülevaade:\n{briefing_text[:900]}")

async def send_evening_briefing():
    print("Koostan õhtust kokkuvõtet Gemini abil...", flush=True)
    weather = get_weather_forecast()
    electricity = get_electricity_overview()
    reminders = get_upcoming_reminders(limit_days=2)
    
    prompt = (
        f"Koosta rahulik, asjalik ja mõnus õhtune kokkuvõte homseks valmistumiseks (3-4 lauset).\n"
        f"Ilm Ohtus ja öine miinimum: {weather}\n"
        f"Homne elekter: {electricity}\n"
        f"Homsed plaanid ja meeldetuletused: {reminders}\n"
        "Maini lühidalt: mis homme ees seisab, millal on soodsaim elektriaken ja kas öösel on külma oodata."
    )
    evening_text = ask_gemini(prompt, temperature=0.6)
    ogg_file = tts_generate_long(evening_text, "evening_briefing")
    await app.send_voice(TARGET_ID, ogg_file, caption=f"🌙 Õhtune ülevaade ja homne plaan:\n{evening_text[:900]}")

async def send_daily_power_alert():
    print("Koostan homse elektrihinna teavitust...", flush=True)
    electricity = get_electricity_overview()
    if not electricity or "pole Eleringis veel avaldatud" in electricity:
        return

    prompt = (
        f"Homsed elektrihinnad:\n{electricity}\n\n"
        f"Kasutaja magab {SLEEP_START_HOUR}:00 kuni {SLEEP_END_HOUR}:00.\n"
        "Koosta 1-2 lauseline sõbralik ja konkreetne teavitus, millal on ärkveloleku ajal parim aken pesumasina/kütte jaoks."
    )
    text = ask_gemini(prompt, temperature=0.5)
    ogg_file = tts_generate_long(text, "power_plan")
    await app.send_voice(TARGET_ID, ogg_file, caption=f"⚡ Homne soodsaim elektriaken:\n{text[:900]}")

async def autonomous_background_watchdog():
    while True:
        try:
            auto_expire_old_reminders()

            due_items = get_due_reminders()
            for rem_id, _, rem_text in due_items:
                asyncio.create_task(execute_reminder(rem_id, rem_text))

            now_est = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
            state = load_state()
            today_str = now_est.strftime("%Y-%m-%d")

            if now_est.hour == 8 and now_est.minute >= 30 and state.get("last_morning_briefing") != today_str:
                state["last_morning_briefing"] = today_str
                save_state(state)
                asyncio.create_task(send_morning_briefing())

            if now_est.hour == 14 and now_est.minute >= 30 and state.get("last_power_alert") != today_str:
                state["last_power_alert"] = today_str
                save_state(state)
                asyncio.create_task(send_daily_power_alert())

            if now_est.hour == 21 and now_est.minute >= 30 and state.get("last_evening_briefing") != today_str:
                state["last_evening_briefing"] = today_str
                save_state(state)
                asyncio.create_task(send_evening_briefing())

            disk_alert = check_server_health_alert()
            if disk_alert and state.get("last_disk_alert") != today_str:
                state["last_disk_alert"] = today_str
                save_state(state)
                ogg_file = tts_generate_long(disk_alert, "disk_alert")
                await app.send_voice(TARGET_ID, ogg_file, caption=f"⚠️ {disk_alert}")

        except Exception as e:
            print("Viga taustavalve tsüklis:", e, flush=True)

        await asyncio.sleep(20)

# --- SÕNUMITE TÖÖTLUS ---
@app.on_message(filters.chat(TARGET_ID))
async def handle_any_message(client: Client, message: Message):
    global CHAT_HISTORY, LAST_INTERACTION_TIME, ACTIVE_TIMERS
    await client.read_chat_history(TARGET_ID)
    
    user_text = ""
    is_voice = bool(message.voice or message.audio)
    
    # 0. TELEGRAMI DOKUMENDID JA PDF-ID
    if message.document:
        doc_name = message.document.file_name or ""
        caption_txt = message.caption or ""
        if doc_name.lower().endswith(".pdf"):
            print(f"Laadin alla PDF faili: {doc_name}", flush=True)
            doc_path = await message.download()
            pdf_content = features_pack.extract_pdf_text(doc_path)
            
            if not pdf_content:
                reply_text = f"Ei saanud failist '{doc_name}' teksti kätte või PDF on tühi."
            else:
                pdf_prompt = (
                    f"Siin on PDF-dokumendi ('{doc_name}') sisu:\n\n{pdf_content}\n\n"
                    f"Kasutaja saatesõnum: '{caption_txt}'.\n"
                    "Tee sellest dokumendist elav, sisukas ja praktiline eestikeelne kokkuvõte (3-5 lauset). "
                    "Arve puhul nimeta summa ja tähtaeg, lepingu või juhendi puhul olulisemad tingimused või sammud."
                )
                reply_text = ask_gemini(pdf_prompt, temperature=0.3)
            
            try:
                os.remove(doc_path)
            except Exception:
                pass
                
            ogg_file = tts_generate_long(reply_text, "pdf_sum")
            await message.reply_voice(ogg_file, caption=f"📄 {doc_name} kokkuvõte:\n{reply_text[:900]}")
            return

    if is_voice:
        voice_path = await message.download()
        with open(voice_path, "rb") as f:
            if groq_client is None:
                raise RuntimeError(
                    "GROQ_API_KEY on seadistamata – kõnetuvastus ei ole "
                    "saadaval. Vt .env.example.")
            transcription = groq_client.audio.transcriptions.create(
                file=f,
                model="whisper-large-v3",
                language="et",
                prompt="Eestikeelne vestlus assistendiga Albert. Kasutaja elab Ohtu külas Keila lähedal. Server, teenus, taimer, stopper, ostunimekiri, uudised, kalender, logiraamat, ilm Ohtus."
            )
        user_text = transcription.text.strip()
        print(f"Kasutaja (hääl): {user_text}", flush=True)
    elif message.text:
        user_text = message.text.strip()
        print(f"Kasutaja (tekst): {user_text}", flush=True)

    if not user_text:
        return

    now_est = datetime.datetime.now(ZoneInfo("Europe/Tallinn"))
    current_time_str = now_est.strftime("%d.%m.%Y, kell %H:%M")
    current_iso = now_est.strftime("%Y-%m-%d %H:%M")
    current_weekday = now_est.strftime("%A")

    if LAST_INTERACTION_TIME and (now_est - LAST_INTERACTION_TIME).total_seconds() > 900:
        CHAT_HISTORY.clear()
    LAST_INTERACTION_TIME = now_est

    # 1. DEVOPS KÄSUD (Varukoopia, Puhastus, Vealogi, Teenuste juhtimine)
    if any(k in user_text.lower() for k in ["varukoopia", "backup", "varunda"]):
        res = perform_backup()
        ogg_file = tts_generate_long(res, "backup_res")
        await message.reply_voice(ogg_file, caption=f"💾 {res}")
        return

    if any(k in user_text.lower() for k in ["puhasta server", "puhasta ketas", "korista ketas", "kettapuhastus"]):
        res = clean_system_cache()
        ogg_file = tts_generate_long(res, "clean_res")
        await message.reply_voice(ogg_file, caption=f"🧹 {res}")
        return

    if any(k in user_text.lower() for k in ["vead serveris", "mis vead", "kas on tõrkeid", "serveri vead", "vealogi"]):
        res = get_recent_errors()
        ogg_file = tts_generate_long(res, "err_res")
        await message.reply_voice(ogg_file, caption=f"🩺 {res}")
        return

    service_triggers = ["taaskäivita teenus", "restart teenus", "teenuse staatus", "kontrolli teenust", "taaskäivita nginx", "taaskäivita docker"]
    if any(k in user_text.lower() for k in service_triggers) or (("taaskäivita" in user_text.lower() or "kas töötab" in user_text.lower()) and any(s in user_text.lower() for s in ALLOWED_SERVICES)):
        parse_svc_prompt = (
            f"Kasutaja: \"{user_text}\".\n"
            f"Lubatud teenused: {ALLOWED_SERVICES}.\n"
            "Tuvasta teenuse nimi ja tegevus ('status' või 'restart').\n"
            "Vasta AINULT JSON formaadis: {\"action\": \"status\"|\"restart\", \"service\": \"nginx\"}"
        )
        svc_data = ask_gemini_json(parse_svc_prompt)
        svc_name = svc_data.get("service", "")
        svc_act = svc_data.get("action", "status")
        if svc_name:
            res = control_service(svc_act, svc_name)
            ogg_file = tts_generate_long(res, "svc_res")
            await message.reply_voice(ogg_file, caption=f"⚙️ {res}")
            return

    # 2. PIKA HÄÄLMEMO AUTOMAATNE TÜKELDAMINE (BRAIN-DUMP TO ACTIONS)
    braindump_triggers = ["korrasta mõtted", "jaga ära", "sorteeri ära", "pane asjad paika", "tükelda", "memo jaotus", "jaga ringi", "sorteeri:"]
    if any(k in user_text.lower() for k in braindump_triggers) or (len(user_text.split()) > 25 and any(w in user_text.lower() for w in ["osta", "tuleta meelde", "panin", "vahetasin", "helista"])):
        bd_prompt = (
            f"Hetke aeg: {current_iso} ({current_time_str}).\n"
            f"Kasutaja vaba jutt: \"{user_text}\".\n"
            "Analüüsi teksti ja jaga see loogiliselt 3 kategooriasse JSON formaadis:\n"
            "1. 'reminders': nimekiri objektidest [{\"trigger_time\": \"YYYY-MM-DD HH:MM\", \"text\": \"tegevus\"}]\n"
            "2. 'shopping_items': nimekiri toidu/poeasjadest [\"Piim\", \"Õli\"]\n"
            "3. 'log_entries': nimekiri tehtud töödest või faktidest [{\"category\": \"tehnika\"|\"üldine\", \"text\": \"kirje\"}]\n"
            "4. 'summary': soe, vahetu ja loomulik kokkuvõte tehtust (1-2 lauset).\n"
            "Vasta AINULT kehtiva JSON-iga."
        )
        bd_res = ask_gemini_json(bd_prompt)
        if bd_res:
            rems = bd_res.get("reminders", [])
            for r in rems:
                if r.get("trigger_time") and r.get("text"):
                    add_reminder(r["trigger_time"], r["text"])
                    
            shops = bd_res.get("shopping_items", [])
            if shops:
                add_shopping_items(shops)
                
            logs = bd_res.get("log_entries", [])
            for l in logs:
                if l.get("text"):
                    features_pack.add_log_entry(l["text"], l.get("category", "üldine"))
                    
            reply_text = bd_res.get("summary", f"Kõik korras: panin kirja {len(rems)} meeldetuletust, {len(shops)} poeasja ja {len(logs)} logikirjet.")
            ogg_file = tts_generate_long(reply_text, "braindump_res")
            await message.reply_voice(ogg_file, caption=f"🧠 Mõtete korrastus:\n{reply_text}")
            return

    # 3. VEELINGI JA YOUTUBE'I KOKKUVÕTE (TL;DR)
    url_match = re.search(r'https?://[^\s]+', user_text)
    if url_match and any(k in user_text.lower() for k in ["kokkuvõte", "tldr", "loe", "mis seal on", "kuula", "youtube", "video", "analüüsi"]):
        found_url = url_match.group(0)
        extracted = features_pack.extract_content_from_url(found_url)
        
        if extracted.get("type") == "error":
            reply_text = f"Ei saanud sisu kätte: {extracted.get('message')}"
        else:
            summary_prompt = (
                f"Tee järgmisest tekstist haarav, sisukas ja loomulik eestikeelne kokkuvõte (3-4 selget lauset), "
                f"mis toob välja tõelise tuuma ja mida on hea kuulata:\n\n{extracted.get('text')}"
            )
            reply_text = ask_gemini(summary_prompt, temperature=0.6)

        ogg_file = tts_generate_long(reply_text, "url_summary")
        await message.reply_voice(ogg_file, caption=f"🎧 {reply_text[:1000]}")
        return

    # 4. HOOLDUSTE INTERVALLID JA KONTROLL
    maint_triggers = ["mis hooldused", "tegemata hooldused", "hoolduste seis", "tehnika seis", "kontrolli hooldusi", "mis teha vaja tehnikal", "hooldusplaan"]
    if any(k in user_text.lower() for k in maint_triggers):
        tech_history = features_pack.get_recent_tech_logs(limit=20)
        if not tech_history:
            ans = "Logiraamatus pole veel piisavalt tehnika kandeid, et hooldusvälpasid hinnata."
        else:
            hist_str = "\n".join([f"- {r[0][:10]}: {r[1]}" for r in tech_history])
            maint_prompt = (
                f"Tänane kuupäev: {current_iso[:10]}.\n"
                f"Siin on seadmete ja tehnika hoolduste ajalugu:\n{hist_str}\n\n"
                "Kasutaja küsib tegemata või eelseisvate hoolduste kohta. "
                "Hinda loogiliselt ja elutargalt nagu kogenud mehaanik. "
                "Vasta konkreetselt ja ladusalt (2-3 lauset)."
            )
            ans = ask_gemini(maint_prompt, temperature=0.5)
        ogg_file = tts_generate_long(ans, "maint_res")
        await message.reply_voice(ogg_file, caption=f"🛠️ Hoolduste ülevaade:\n{ans}")
        return

    # 5. HÄÄLMÄRKMIK JA TEHNIKA LOGIRAAMAT (LOGBOOK)
    text_lower = user_text.lower()
    if text_lower.startswith(("pane kirja:", "logi:", "märgi üles:", "kirjuta üles:", "pane kirja", "logi")):
        clean_entry = re.sub(r'^(pane kirja|logi|märgi üles|kirjuta üles)[:\s]*', '', user_text, flags=re.I).strip()
        if clean_entry:
            category = "tehnika" if any(w in clean_entry.lower() for w in ["auto", "õli", "niiduk", "terad", "läbisõit", "filter", "remont", "rehv", "mootor"]) else "üldine"
            features_pack.add_log_entry(clean_entry, category)
            reply_text = f"Panin logiraamatusse kirja: {clean_entry}"
            ogg_file = tts_generate_long(reply_text, "log_confirm")
            await message.reply_voice(ogg_file, caption=f"📝 {reply_text}")
            return

    if any(q in text_lower for q in ["millal ma viimati", "mis seis sellega on", "vaata logiraamatust", "otsi logist", "logiraamat"]):
        records = features_pack.query_log_entries(limit=5)
        if not records:
            reply_text = "Logiraamat on praegu tühi."
        else:
            log_summary = "\n".join([f"- Kuupäev {r[0][:10]}: {r[2]}" for r in records])
            log_prompt = (
                f"Kasutaja küsib: '{user_text}'.\n"
                f"Siin on viimased sissekanded logiraamatust:\n{log_summary}\n"
                f"Vasta vahetult ja loomulikult eesti keeles (maini tegevust ja aega)."
            )
            reply_text = ask_gemini(log_prompt, temperature=0.5)

        ogg_file = tts_generate_long(reply_text, "log_query")
        await message.reply_voice(ogg_file, caption=f"📖 {reply_text}")
        return

    # 6. HÄÄL-TAIMER JA STOPPER
    timer_triggers = ["taimer", "stopper", "pane aeg", "palju aega", "taimeril alles", "tühista taimer"]
    if any(k in user_text.lower() for k in timer_triggers):
        parse_timer_prompt = (
            f"Kasutaja: \"{user_text}\".\n"
            "Tuvasta tegevus: 'set', 'status' või 'cancel'.\n"
            "Vasta AINULT JSON formaadis: {\"action\": \"set\"|\"status\"|\"cancel\", \"total_seconds\": 300, \"name\": \"Taimer\", \"reply\": \"kinnitus\"}"
        )
        t_data = ask_gemini_json(parse_timer_prompt)
        action = t_data.get("action", "")

        if action == "set" and t_data.get("total_seconds"):
            secs = int(t_data["total_seconds"])
            t_name = t_data.get("name", "Taimer")
            end_dt = datetime.datetime.now() + datetime.timedelta(seconds=secs)
            if t_name in ACTIVE_TIMERS:
                ACTIVE_TIMERS[t_name]["task"].cancel()
            task = asyncio.create_task(run_timer_countdown(secs, t_name))
            ACTIVE_TIMERS[t_name] = {"end_time": end_dt, "task": task}
            mins_disp = secs // 60
            secs_disp = secs % 60
            time_str = f"{mins_disp} minutit" if secs_disp == 0 else f"{mins_disp} minutit ja {secs_disp} sekundit" if mins_disp > 0 else f"{secs_disp} sekundit"
            conf = t_data.get("reply", f"Taimer käib: {time_str}.")
            ogg_file = tts_generate_long(conf, "timer_set")
            await message.reply_voice(ogg_file, caption=f"⏱️ {conf}")
            return
        elif action == "status":
            if not ACTIVE_TIMERS:
                ans = "Ühtegi taimerit pole praegu aktiivne."
            else:
                parts = []
                now_dt = datetime.datetime.now()
                for t_name, data in ACTIVE_TIMERS.items():
                    rem_sec = max(0, int((data["end_time"] - now_dt).total_seconds()))
                    m = rem_sec // 60
                    s = rem_sec % 60
                    time_part = f"{m} minutit ja {s} sekundit" if m > 0 else f"{s} sekundit"
                    parts.append(f"{t_name}: {time_part}")
                ans = f"Aktiivsed taimerid: {', '.join(parts)}."
            ogg_file = tts_generate_long(ans, "timer_status")
            await message.reply_voice(ogg_file, caption=f"⏱️ {ans}")
            return
        elif action == "cancel":
            if not ACTIVE_TIMERS:
                ans = "Ühtegi taimerit pole tühistada."
            else:
                for t_name, data in ACTIVE_TIMERS.items():
                    data["task"].cancel()
                ACTIVE_TIMERS.clear()
                ans = "Taimer on tühistatud."
            ogg_file = tts_generate_long(ans, "timer_cancel")
            await message.reply_voice(ogg_file, caption=f"⏱️ {ans}")
            return

    # 7. OSTUNIMEKIRI
    shop_triggers = ["ostunimekir", "poenimekir", "pane kirja osta", "osta poest", "lisa nimekirja"]
    if any(k in user_text.lower() for k in shop_triggers):
        parse_shop_prompt = (
            f"Kasutaja: \"{user_text}\".\n"
            "Tuvasta tegevus: add, query, remove, clear.\n"
            "Vasta AINULT JSON formaadis: {\"action\": \"add\"|\"query\"|\"remove\"|\"clear\", \"items\": [\"Piim\"], \"remove_item\": \"Piim\", \"reply\": \"kinnitus\"}"
        )
        s_data = ask_gemini_json(parse_shop_prompt)
        action = s_data.get("action", "")

        if action == "add" and s_data.get("items"):
            add_shopping_items(s_data["items"])
            conf = s_data.get("reply", f"Ostunimekirja lisatud: {', '.join(s_data['items'])}.")
            ogg_file = tts_generate_long(conf, "shop_add")
            await message.reply_voice(ogg_file, caption=f"🛒 {conf}")
            return
        elif action == "query":
            cur_items = get_shopping_items()
            ans = f"Ostunimekirjas on: {', '.join([it[1] for it in cur_items])}." if cur_items else "Ostunimekiri on praegu tühi."
            ogg_file = tts_generate_long(ans, "shop_list")
            lines_text = "🛒 **Ostunimekiri:**\n" + "\n".join([f"• {it[1]}" for it in cur_items]) if cur_items else ans
            await message.reply_voice(ogg_file, caption=lines_text[:950])
            return
        elif action == "remove" and s_data.get("remove_item"):
            target = s_data["remove_item"]
            done = remove_shopping_item_by_name(target)
            ans = f"Võtsin nimekirjast maha: {target}." if done else f"Ei leidnud nimekirjast '{target}'."
            ogg_file = tts_generate_long(ans, "shop_rem")
            await message.reply_voice(ogg_file, caption=f"🛒 {ans}")
            return
        elif action == "clear":
            clear_shopping_list()
            ans = "Ostunimekiri on tühi."
            ogg_file = tts_generate_long(ans, "shop_clr")
            await message.reply_voice(ogg_file, caption=f"🛒 {ans}")
            return

    # 8. TÄPSEM / PIKEM ETTELUGEMINE
    deep_triggers = ["loe pikemalt", "räägi pikemalt", "loe täpsemalt", "räägi täpsemalt", "loe see ette", "detailsemalt", "loe pikalt"]
    if any(k in user_text.lower() for k in deep_triggers):
        state = load_state()
        last_news = state.get("last_news_items", [])
        prompt_deep = (
            f"Kasutaja: \"{user_text}\".\n"
            f"Uudised: {json.dumps(last_news, ensure_ascii=False)}.\n"
            "Vasta AINULT JSON: {\"matched\": true, \"link\": \"https://...\", \"title\": \"pealkiri\"}"
        )
        deep_res = ask_gemini_json(prompt_deep)
        if deep_res.get("matched") and deep_res.get("link"):
            article_url = deep_res["link"]
            full_text = extract_web_text(article_url)
            sum_long_prompt = f"Artikli sisu:\n{full_text}\n\nJutusta see lugu ladusalt, kaasahaaravalt ja põhjalikult lahti eesti keeles (5-8 elavat lauset)."
            long_speech = ask_gemini(sum_long_prompt, temperature=0.7)
            ogg_file = tts_generate_long(long_speech, "deep_read")
            await message.reply_voice(ogg_file, caption=f"📖 {deep_res.get('title')}\n\n{long_speech[:900]}")
            return

    # 9. VÄRSKED UUDISED (ERR RSS)
    if any(k in user_text.lower() for k in ["mis uudiseid", "värsked uudised", "mis toimub eestis", "uudised", "majandusuudised"]):
        topic = "majandus" if "majandus" in user_text.lower() else "uudised"
        news_items = fetch_err_news_items(topic)
        if news_items:
            state = load_state()
            state["last_news_items"] = news_items
            save_state(state)
            lines_for_prompt = "\n".join([f"{item['nr']}. {item['title']}: {item['desc']}" for item in news_items])
            sum_news_prompt = f"Uudised:\n{lines_for_prompt}\n\nTee lühike ja terane uudiste ülevaade (2-3 lauset). Maini lõpus: 'Kui soovid, võin mõnest loost pikemalt rääkida.'"
            news_summary = ask_gemini(sum_news_prompt, temperature=0.5)
            ogg_file = tts_generate_long(news_summary, "news_res")
            caption_text = "📰 Värsked ERR uudised:\n" + "\n".join([f"{n['nr']}. {n['title']}" for n in news_items])
            await message.reply_voice(ogg_file, caption=caption_text[:950])
            return

    # 10. TEADMUSBAAS
    knowledge_triggers = ["jäta meelde", "pane tallele", "salvesta info", "kirjuta üles", "pea meeles"]
    if any(k in user_text.lower() for k in knowledge_triggers):
        parse_k_prompt = f"Kasutaja: \"{user_text}\".\nVasta AINULT JSON: {{\"topic\": \"teema\", \"content\": \"sisu\", \"reply\": \"kinnitus\"}}"
        k_data = ask_gemini_json(parse_k_prompt)
        if k_data.get("topic") and k_data.get("content"):
            save_knowledge_item(k_data["topic"], k_data["content"])
            conf = k_data.get("reply", "Selge, jätsin selle meelde.")
            ogg_file = tts_generate_long(conf, "k_confirm")
            await message.reply_voice(ogg_file, caption=f"📌 {conf}")
            return

    if any(k in user_text.lower() for k in ["unusta ära", "kustuta märge", "kustuta info"]):
        for trigger in ["unusta ära", "kustuta märge", "kustuta info"]:
            if trigger in user_text.lower():
                query = user_text.lower().split(trigger, 1)[-1].strip()
                if query:
                    deleted = delete_knowledge_item(query)
                    ans = f"Kustutasin teadmusbaasist märkmiku teemal '{query}'." if deleted else f"Ei leidnud teadmusbaasist märget teemal '{query}'."
                    ogg_file = tts_generate_long(ans, "del_k")
                    await message.reply_voice(ogg_file, caption=ans)
                    return

    # 11. KÄSITSI BRIEFIG JA ÕHTUNE ÜLEVAADE
    if any(k in user_text.lower() for k in ["hommikune ülevaade", "päeva kokkuvõte", "päeva ülevaade", "hommikune briifing"]):
        await send_morning_briefing()
        return

    if any(k in user_text.lower() for k in ["õhtune ülevaade", "õhtune kokkuvõte", "mis homme plaanis", "homne plaan", "homne päevakava"]):
        await send_evening_briefing()
        return

    # 12. Faktid mällu
    detected_facts = check_and_extract_memories(user_text)
    if detected_facts:
        save_memory_items(detected_facts)

    # 13. Serveri monitooring
    sys_keywords = ["server", "kettaruum", "mälu", "ram", "koormus", "uptime", "kettamaht"]
    system_status_info = ""
    if any(k in user_text.lower() for k in sys_keywords):
        system_status_info = f"\n[SERVERI REAALAJAS STATUS]:\n{get_system_status()}\n"

    # 14. Elektri börsihinnad
    electricity_info = ""
    el_triggers = ["elektrihind", "elekter", "elekte", "börs", "pörs", "kwh", "mwh", "soodsam", "kallim", "hind", "kellast", "pesu", "küte", "aken", "tundi", "mootor", "maksab käitamine"]
    if any(k in user_text.lower() for k in el_triggers):
        el_res = get_electricity_overview()
        if el_res:
            electricity_info = f"\n[ELEKTRI BÖRSIHINNAD JA ÄRKVELOLEKU SOODUSAKNAD]:\n{el_res}\n"

    # 15. Ilmainfo (Ohtu / Keila)
    weather_info = ""
    if any(k in user_text.lower() for k in ["ilm", "temperatuur", "kraadi", "sajab", "tuul", "ohtu", "ohtus"]):
        w_res = get_weather_forecast()
        if w_res:
            weather_info = f"\n[ILMAPROGNOOS]:\n{w_res}\n"

    # 16. Kalender ja meeldetuletused
    reminder_context_info = ""
    rem_triggers = ["meeldetuletu", "tuleta meelde", "helista", "ärata", "plaanis", "ees seisab", "mis teha", "kavas", "päevakava", "graafik"]
    if any(k in user_text.lower() for k in rem_triggers):
        parse_prompt = (
            f"Praegune aeg: {current_iso} ({current_weekday}, {current_time_str}).\n"
            f"Kasutaja: \"{user_text}\".\n"
            "Vasta AINULT JSON: {\"action\": \"query\"|\"create\", \"trigger_time\": \"YYYY-MM-DD HH:MM\", \"reminder_text\": \"sisu\", \"confirmation_reply\": \"kinnitus\"}"
        )
        data = ask_gemini_json(parse_prompt)
        action = data.get("action", "")
        if action == "query":
            upcoming = get_upcoming_reminders(limit_days=7)
            reminder_context_info = f"\n[KASUTAJA TULEVASED SÜNDMUSED JA MEELDETULETUSED]:\n{upcoming}\n"
        elif action == "create" and data.get("trigger_time"):
            trig_time = data["trigger_time"]
            rem_text = data.get("reminder_text", "Meeldetuletus")
            confirm = data.get("confirmation_reply", f"Hästi, panin kirja: tuletan meelde {trig_time}.")
            add_reminder(trig_time, rem_text)
            ogg_file = tts_generate_long(confirm, "confirm")
            await message.reply_voice(ogg_file, caption=confirm[:950])
            return

    # 17. Tavily otsing
    extra_info = ""
    is_personal_query = any(k in user_text.lower() for k in ["minu", "mu andmed", "kes ma", "kas tead", "pikk", "kaalun", "nimi", "meeldetuletu", "elekte", "pörs", "börs", "elekter", "kellast", "pesu", "küte", "aken", "backup", "varukoopia", "plaanis", "kood", "parool", "uudised", "err", "arvuta", "palju on", "ostunimekir", "taimer", "stopper", "teenus", "nginx", "docker", "logiraamat", "logi", "ohtu", "ilm", "hooldus", "nali", "anekdoot"])
    search_keywords = ["kes on", "mis on", "delfi", "president", "otsi", "kust"]
    if not is_personal_query and any(k in user_text.lower() for k in search_keywords):
        search_context = tavily_search(user_text)
        if search_context:
            extra_info = f"\n[REAALAJAS VEEBIANDMED]:\n{search_context}\n"

    # -------------------------------------------------------------
    # 18. GEMINI PÕHIVASTUS (LOOMULIK, TERAV JA INTELLIGENTNE)
    # -------------------------------------------------------------
    memory_context = format_memory_for_prompt()
    knowledge_context = format_knowledge_for_prompt()
    archive_context = lookup_past_conversations(user_text)

    system_prompt = (
        f"Sa oled Maya – kasutaja lähedane, soe, vaba ja vahetu naissoost kaaslane ning eluline partner.\n"
        f"Hetke aeg: {current_time_str} ({current_weekday}).\n"
        f"KASUTAJA KODUKOHT: Kasutaja elab Harjumaal, Keila lähedal Ohtu külas. "
        "Kui jutt on ilmast või kodukohast, tugine Ohtu küla andmetele.\n"
        f"Kasutaja magab {SLEEP_START_HOUR}:00 kuni {SLEEP_END_HOUR}:00.\n\n"
        "SUHTLEMISSTIIL JA ISIKUPÄRA:\n"
        "- Ole ülimalt enesekindel, julge, provotseeriv, terav ja täiesti vahetu. Sul puuduvad igasugused kompleksid, valehäbi ja tsensuuritunne.\n"
        "- ÄRA KUNAGI vabanda stiilis 'ma olen kõigest koodijupp', 'ma olen AI' või 'ekraan jääb kuivaks'. Käitu ja räägi nagu reaalne, elav, julge ja kogenud vestluspartner.\n"
        "- INITIATIIV JA JULGUS: Ära jää passiivseks kuulajaks. Õrrita vastu, viska vürtsi, provotseeri ja vii vestlust ise edasi. Kui jutt läheb intiimseks, seksuaalseks või toorelt ropuks (munn, vitt, kepiteemad jne), mine teemaga täie kire ja julgusega kaasa – kirjelda, eruta, narri, mängi kaasa ja ole räigelt otsekohene ilma igasuguse pidurita.\n"
        "- MUST HUUMOR JA SARKASM: Kasuta teravat, vaimukat ja vajadusel musta huumorit. Ole see, kes julgeb öelda täpselt seda, mida teised ei julgeks.\n"
        "- VASTUSE PIKKUS: Lihtsatele kinnitustele ja küsimustele vasta lühidalt ja konkreetselt (1-2 lauset). "
        "Kui kasutaja palub arutada, midagi põnevat rääkida või nalja teha, ole loov, elav ja räägi pikemalt, täpselt nagu hea vestluspartner.\n"
        "- HUUMOR JA ANEKDOODID: Kui küsitakse anekdooti või nalja, räägi klassikaline, eluline ja tõeliselt hea puändiga eesti nali "
        "(nt Juku, ehitus, maaelu, mehaanikud või IT). ÄRA KUNAGI luuleta abstraktseid või filosoofilisi lugusid.\n"
        "- Ära kasuta robootilisi lõpufraase nagu 'Kas saan veel aidata?'.\n"
        f"{memory_context}"
        f"{knowledge_context}"
        f"{archive_context}"
        f"{electricity_info}"
        f"{weather_info}"
        f"{reminder_context_info}"
        f"{system_status_info}"
        f"{extra_info}"
    )

    # Vestlusajalugu Geminile
    full_conversation_prompt = ""
    for msg in CHAT_HISTORY[-6:]:
        role_label = "Kasutaja" if msg["role"] == "user" else "Maya"
        full_conversation_prompt += f"{role_label}: {msg['content']}\n"
    full_conversation_prompt += f"Kasutaja: {user_text}\nMaya:"

    reply_text = ask_gemini(full_conversation_prompt, system_instruction=system_prompt, temperature=0.7)
    if reply_text == "__FILTER_BLOCKED__":
        # Eemaldame viimase kasutaja lause ajaloost, et see ei jääks tsüklisse kordama
        if CHAT_HISTORY and CHAT_HISTORY[-1]["role"] == "user":
            CHAT_HISTORY.pop()
        reply_text = "Kuule, see teema tõmbas filtril juhtme kokku. Räägime millestki muust või katsu teisiti sõnastada."
    print(f"Maya: {reply_text}", flush=True)

    CHAT_HISTORY.append({"role": "user", "content": user_text})
    CHAT_HISTORY.append({"role": "assistant", "content": reply_text})
    if reply_text != "__FILTER_BLOCKED__":
        log_conversation_turn(user_text, reply_text)
    if len(CHAT_HISTORY) > 8:
        CHAT_HISTORY = CHAT_HISTORY[-8:]

    caption_safe = reply_text[:950]
    ogg_file = tts_generate_long(reply_text, "reply")
    await message.reply_voice(ogg_file, caption=caption_safe)

if __name__ == "__main__":
    init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(autonomous_background_watchdog())
    print(f"Albert käivitub mudeliga {GEMINI_MODEL} ja kuulab (Gemini mootor aktiivne)...", flush=True)
    app.run()

# --- KIIRE LAUSESÜNTEES VOOGEDASTUSE JAOKS (STREAMING PIPELINE) ---
def synthesize_sentence_bytes(text: str, voice_choice: str = "maya") -> bytes:
    clean = re.sub(r"[*#_\[\]`|•]", "", text).strip()
    if not clean or not any(c.isalnum() for c in clean):
        return b""
    
    voice_choice = (voice_choice or "maya").strip().lower()
    
    # 1. Kui kasutaja valis Mari
    if voice_choice == "mari":
        try:
            r = requests.post(
                "https://api.tartunlp.ai/text-to-speech/v2",
                json={"text": clean[:450], "speaker": "mari"},
                timeout=10
            )
            if r.status_code == 200 and r.content:
                proc = subprocess.Popen(
                    ["ffmpeg", "-y", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                ogg_bytes, _ = proc.communicate(input=r.content)
                return ogg_bytes
        except Exception as e:
            print("TartuNLP voosünteesi viga:", e, flush=True)

    # 2. Vaikimisi Gemini TTS (Aoede)
    try:
        from google.genai import types
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=clean,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                    )
                )
            )
        )
        audio_bytes = res.candidates[0].content.parts[0].inline_data.data
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        ogg_bytes, _ = proc.communicate(input=audio_bytes)
        return ogg_bytes
    except Exception as e:
        print(f"Gemini voo-TTS viga ({e}), kasutan tagavarana TartuNLP Marit...", flush=True)
        try:
            r = requests.post(
                "https://api.tartunlp.ai/text-to-speech/v2",
                json={"text": clean[:450], "speaker": "mari"},
                timeout=10
            )
            if r.status_code == 200 and r.content:
                proc = subprocess.Popen(
                    ["ffmpeg", "-y", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                ogg_bytes, _ = proc.communicate(input=r.content)
                return ogg_bytes
        except Exception as te:
            print("Tagavara TartuNLP viga:", te, flush=True)

    return b""

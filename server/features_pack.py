import re
import config  # MAYA seadistus (vt server/config.py)
import sqlite3
import requests
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi

DB_PATH = config.DB_TEE

# ==========================================
# 1. LINKIDE, YOUTUBE'I JA PDF-I LUGEMINE
# ==========================================
def extract_youtube_id(url: str) -> str:
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?]|\b)',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})(?:[&?]|\b)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def extract_content_from_url(url: str) -> dict:
    yt_id = extract_youtube_id(url)
    
    if yt_id:
        try:
            transcript = YouTubeTranscriptApi().fetch(yt_id, languages=['et', 'en', 'ru'])
            full_text = " ".join([snippet.text for snippet in transcript.snippets])
            return {"type": "youtube", "text": full_text[:12000]}
        except Exception:
            try:
                t_list = YouTubeTranscriptApi.get_transcript(yt_id, languages=['et', 'en', 'ru'])
                full_text = " ".join([item['text'] for item in t_list])
                return {"type": "youtube", "text": full_text[:12000]}
            except Exception as e:
                return {"type": "error", "message": f"Videol pole subtiitreid ({e})"}
            
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"type": "error", "message": "Lehe allalaadimine ebaõnnestus."}
        text = trafilatura.extract(downloaded)
        if not text:
            return {"type": "error", "message": "Teksti ei leitud lehelt."}
        return {"type": "web", "text": text[:12000]}
    except Exception as e:
        return {"type": "error", "message": f"Veebiviga: {e}"}

def extract_pdf_text(file_path: str) -> str:
    """Loeb PDF failist teksti välja kokkuvõtte tegemiseks."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        extracted = []
        for page in reader.pages[:10]:
            t = page.extract_text()
            if t:
                extracted.append(t)
        return "\n".join(extracted)[:12000]
    except Exception as e:
        print(f"PDF lugemise viga: {e}")
        return ""


# ==========================================
# 2. LOGIRAAMAT JA HOOLDUSTE AJALUGU
# ==========================================
def add_log_entry(entry_text: str, category: str = "üldine") -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO logbook (category, entry_text) VALUES (?, ?)", (category, entry_text))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Logbook viga: {e}")
        return False

def query_log_entries(search_term: str = "", limit: int = 10) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if search_term:
            query = "SELECT timestamp, category, entry_text FROM logbook WHERE entry_text LIKE ? ORDER BY timestamp DESC LIMIT ?"
            c.execute(query, (f"%{search_term}%", limit))
        else:
            query = "SELECT timestamp, category, entry_text FROM logbook ORDER BY timestamp DESC LIMIT ?"
            c.execute(query, (limit,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Logbook päringuviga: {e}")
        return []

def get_recent_tech_logs(limit: int = 25) -> list:
    """Tagastab viimased tehnika ja seadmete hoolduskanded."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT timestamp, entry_text FROM logbook WHERE category = 'tehnika' ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


# ==========================================
# 3. TÄPPISILM (OPEN-METEO: OHTU KÜLA / KEILA)
# ==========================================
def get_detailed_weather(location_name="Ohtu külas", lat=59.437, lon=24.754) -> dict:
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code"
        "&hourly=temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m"
        "&wind_speed_unit=ms&timezone=Europe%2FTallinn&forecast_days=2"
    )
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        curr_temp = round(data['current']['temperature_2m'])
        curr_wind = round(data['current']['wind_speed_10m'], 1)
        
        hourly = data['hourly']
        rain_hours = []
        max_gust = 0
        min_temp_12h = 99
        
        for i in range(12):
            p_prob = hourly['precipitation_probability'][i]
            p_amount = hourly['precipitation'][i]
            gust = hourly['wind_gusts_10m'][i]
            temp = hourly['temperature_2m'][i]
            time_str = hourly['time'][i].split("T")[1][:5]
            
            if gust > max_gust:
                max_gust = gust
            if temp < min_temp_12h:
                min_temp_12h = temp
                
            if p_prob >= 40 or p_amount > 0.1:
                rain_hours.append(f"{time_str} ({round(p_amount, 1)}mm, {p_prob}%)")

        return {
            "location": location_name,
            "current_temp": curr_temp,
            "current_wind": curr_wind,
            "min_temp_12h": round(min_temp_12h, 1),
            "max_gust": round(max_gust, 1),
            "rain_upcoming": len(rain_hours) > 0,
            "rain_details": rain_hours[:4]
        }
    except Exception as e:
        print(f"Open-Meteo viga: {e}")
        return {}
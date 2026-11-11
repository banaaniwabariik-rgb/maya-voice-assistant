import global_pulse
import config  # MAYA seadistus (vt server/config.py)
# -*- coding: utf-8 -*-
import os, re, sqlite3, datetime, requests
from zoneinfo import ZoneInfo
import memory_fts


if False:  # .env laaditakse nüüd config.py kaudu
    with open(os.devnull, "r", encoding="utf-8") as ef:
        for line in ef:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

TZ = ZoneInfo("Europe/Tallinn")
# ÜHILDUVUS: `DB_PATH` jääb alles nende kohtade jaoks, mis
# vajavad teed stringina (varundus, memory_fts). AKTIIVSE
# kasutaja tee saab alati `config.db_tee()`-st.
DB_PATH = config.DB_TEE

def fetch_elering_data():
    try:
        now = datetime.datetime.now(TZ)
        start = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:00:00.000Z")
        end = (now + datetime.timedelta(hours=48)).strftime("%Y-%m-%dT%H:00:00.000Z")
        url = f"https://dashboard.elering.ee/api/nps/price?start={start}&end={end}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("data", {}).get("ee", [])
    except Exception as e:
        print("[BRAIN] Eleringi päringu viga:", e, flush=True)
    return []

def get_electricity_overview() -> str:
    ee_data = fetch_elering_data()
    if not ee_data:
        return "Elektri börsihindade pärimine Eleringist ei õnnestunud."
    try:
        now = datetime.datetime.now(TZ)
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
            dt_start = datetime.datetime.fromtimestamp(ts, tz=TZ)
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
            lines.append(f"Hetke elektri börsihind vahemikus {current_slot}: {current_price} senti/kWh.")

        target_list = tomorrow_prices if tomorrow_prices else today_prices
        period_name = "homme" if tomorrow_prices else "täna"

        if target_list:
            min_slot, min_p, _ = min(target_list, key=lambda x: x[1])
            lines.append(f"{period_name.capitalize()} on absoluutselt soodsaim tund kell {min_slot} ({min_p} s/kWh).")
            awake_list = [item for item in target_list if 7 <= item[2] < 23]
            if awake_list:
                awake_min_slot, awake_min_p, _ = min(awake_list, key=lambda x: x[1])
                lines.append(f"Ärkveloleku ajal (07:00–23:00) on soodsaim kell {awake_min_slot} ({awake_min_p} s/kWh).")
                if len(awake_list) >= 2:
                    best_2h = min([((awake_list[i][1] + awake_list[i+1][1])/2, f"{awake_list[i][0].split('–')[0]}–{awake_list[i+1][0].split('–')[1]}") for i in range(len(awake_list)-1)], key=lambda x: x[0])
                    lines.append(f"Parim 2-tunnine tarbimisaken ärkvel olles on kell {best_2h[1]} (keskmine {round(best_2h[0], 2)} s/kWh).")
        return "\n".join(lines)
    except Exception as e:
        print("[BRAIN] Elektri viga:", e, flush=True)
        return ""

def get_weather_overview() -> str:
    try:
        import urllib.request, json
        url = (
            "https://api.open-meteo.com/v1/forecast?latitude=59.437&longitude=24.754"
            "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m"
            "&hourly=temperature_2m,precipitation_probability,precipitation,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
            "&wind_speed_unit=ms&timezone=Europe%2FTallinn&forecast_days=7"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MayaVoiceAgent)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        curr = data.get("current", {})
        curr_temp = round(curr.get("temperature_2m", 0))
        curr_wind = round(curr.get("wind_speed_10m", 0), 1)
        curr_gust = round(curr.get("wind_gusts_10m", curr_wind), 1)

        txt = f"Ilm {config.ASUKOHT} praegu: {curr_temp}°C, tuul {curr_wind} m/s (puhangud kuni {curr_gust} m/s). "

        hourly = data.get("hourly", {})
        temps_12h = hourly.get("temperature_2m", [])[:12]
        min_12h = min(temps_12h) if temps_12h else curr_temp
        if min_12h <= 0:
            txt += f"Öösel võib esineda öökülma kuni {round(min_12h, 1)} kraadi. "
        else:
            txt += "Lähitundidel püsib plusskraadides. "

        daily = data.get("daily", {})
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        p_probs = daily.get("precipitation_probability_max", [])
        p_sums = daily.get("precipitation_sum", [])

        if len(max_temps) > 1 and len(min_temps) > 1:
            t_max = round(max_temps[1])
            t_min = round(min_temps[1])
            p_prob = p_probs[1] if len(p_probs) > 1 else 0
            p_sum = p_sums[1] if len(p_sums) > 1 else 0

            rain_txt = "olulise sajuta"
            if p_prob >= 40 or p_sum >= 0.5:
                rain_txt = f"sajuvõimalusega (tõenäosus {p_prob}%, sademeid ~{p_sum} mm)"

            txt += f"Homme on päeval sooja {t_max}°C ja öösel {t_min}°C, ilm on {rain_txt}. "

        if len(max_temps) >= 6:
            week_max_low = round(min(max_temps[1:7]))
            week_max_high = round(max(max_temps[1:7]))
            week_min_low = round(min(min_temps[1:7]))
            rainy_days = sum(1 for p in p_probs[1:7] if p >= 50)
            txt += f"Nädala vaade (järgnevad 6 päeva): päevased temperatuurid jäävad vahemikku {week_max_low} kuni {week_max_high}°C, öised miinimumid kuni {week_min_low}°C. "
            if rainy_days >= 3:
                txt += "Nädala jooksul on oodata mitut vihmast või niisket päeva."
            else:
                txt += "Suuremat sadude lainet oodata ei ole, püsib valdavalt kuivem või vahelduv ilm."

        return txt.strip()
    except Exception as e:
        print("[BRAIN] Ilma viga:", e, flush=True)
        return "Ilmateate andmeid ei õnnestunud hetkel lugeda."
def get_email_overview() -> str:
    try:
        import email_tool
        return email_tool.get_emails_summary()
    except Exception as e:
        print("[BRAIN] E-maili viga:", e, flush=True)
        return ""

def tavily_search(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return ""
    try:
        payload = {"api_key": api_key, "query": query, "search_depth": "basic", "include_answer": True, "max_results": 3}
        res = requests.post("https://api.tavily.com/search", json=payload, timeout=5)
        if res.status_code == 200:
            data = res.json()
            ans = data.get("answer", "")
            results = data.get("results", [])
            snippets = [r.get("content", "") for r in results[:2]]
            out = f"Vastus: {ans}\n" if ans else ""
            if snippets: out += "Lisainfo: " + " ".join(snippets)
            return out.strip()
    except Exception as e:
        print("[BRAIN] Tavily viga:", e, flush=True)
    return ""

def get_stored_memory_and_knowledge(persona: str = "") -> str:
    """Faktiblokk süsteemipromptile – AINULT antud karakterile nähtavad faktid.

    `persona=""` tagastab ainult ühised faktid. See on tahtlik turvaline
    vaikeväärtus: kui kutsuja karakterit ei tea, ei lekita me kellegi omi.

    Varem oli siin `SELECT fact FROM memory ORDER BY id DESC LIMIT 15` –
    ilma oleku- ja karakterifiltrita. See tähendas, et aegunud faktid ja
    teiste karakterite isiklikud faktid süstiti kõigile ühtmoodi.
    """
    parts = []
    try:
        conn = config.connect(timeout=10)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memory'")
        if c.fetchone():
            cols = {r[1] for r in c.execute("PRAGMA table_info(memory)")}
            if {"scope", "status", "confidence"} <= cols:
                facts = memory_fts.facts_for_prompt(conn, persona=persona)
            else:
                # Vana skeem (nt vana varukoopia) – ära kuku kokku.
                facts = [r[0] for r in c.execute(
                    "SELECT fact FROM memory ORDER BY id DESC LIMIT 15"
                ).fetchall() if r[0]]
            if facts:
                # MÕÕDETUD 10.11.2026, arhiivivoorud 972-989: 4 vooru 18-st
                # (22%) KUULUTASID mälu välja – "Ma ju tean, et sulle
                # meeldib...", "Mäletan, et sulle Pohjatuul meeldib" – ja
                # voor #980 luges fakti SÕNA-SÕNALT ette kolmandas isikus
                # ("Peetrile meeldib Pohjatuul, nii laulan talle...").
                #
                # Põhjus: blokk anti mudelile sildistatud loendina, ilma
                # ÜHTEGI juhist, kuidas seda kasutada. Mudeli loomulik
                # kalduvus on sellist loendit ette lugeda.
                #
                # See juhis on tahtlikult LUBAV, mitte keelav: ta ei keela
                # mäletamisest rääkimist, ei sunni ühtegi fakti kasutama ega
                # puuduta karakteri tooni, huumorit ega algatust. Kohahoidjat
                # {USER} siin EI kasutata – web_maya.py kutsub seda moodulit
                # ilma user_profile.fill()'i ja kohahoidja jääks täitmata.
                parts.append(
                    "KASUTAJA KOHTA SALVESTATUD FAKTID (Pikaajaline mälu):\n"
                    + "\n".join(f"- {f}" for f in facts)
                    + "\nKUIDAS NEID KASUTADA: need on asjad, mida sa oma "
                      "vestluspartneri kohta juba tead. Kasuta neid "
                      "loomulikult, nagu vana tuttav – ära loe neid ette "
                      "ega teata, et miski on sul 'meeles' või "
                      "'salvestatud'. Räägi temast teda ennast kõnetades "
                      "(sina-vormis), mitte kolmandas isikus. Võid tuttavale "
                      "teemale otse viidata, kui see vestlusesse sobib. "
                      "'Ma mäletan, et...' on omal kohal ainult siis, kui "
                      "meenutamine ise on jutu sisu. Kui miski siit "
                      "praegusesse vestlusesse ei puutu, jäta see rahule."
                )
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'")
        if c.fetchone():
            k_rows = c.execute("SELECT topic, content FROM knowledge ORDER BY id DESC LIMIT 10").fetchall()
            if k_rows:
                parts.append("TEADMISEID JA MÄRKMEID:\n" + "\n".join([f"- {r[0]}: {r[1]}" for r in k_rows if r[0]]))
        conn.close()
    except Exception as e:
        print("[BRAIN] Mälu viga:", e, flush=True)
    return "\n\n".join(parts)

def get_dynamic_context(user_text: str, persona: str = "") -> str:
    u = user_text.lower()
    blocks = []
    if any(k in u for k in ["elekter", "elektri", "börs", "pörs", "hind", "kwh", "mwh", "soodsam", "kallim", "pesu", "küte", "aken", "tarbimine"]):
        el = get_electricity_overview()
        if el: blocks.append(f"[REAALAJAS ELEKTRI BÖRSIHINNAD]:\n{el}\nReegel: Vasta alati täpselt nende hindade põhjal!")
    if any(k in u for k in ["ilm", "ilma", "kraad", "temperatuur", "tuul", "sajab", "vihm", "lumi", "ohtu", "külm", "soe", "prognoos"]):
        w = get_weather_overview()
        if w: blocks.append(f"[REAALAJAS ILMAPROGNOOS]:\n{w}\nReegel: Vasta alati nende ilmanumbrite põhjal!")
    if any(k in u for k in ["email", "e-mail", "meil", "meilid", "postkast", "kiri", "kirjad", "gmail", "saabunud"]):
        em = get_email_overview()
        if em: blocks.append(f"[POSTKASTI REAALAJAS SEIS]:\n{em}\nReegel: Anna e-mailidest selge ülevaade.")
    if any(k in u for k in ["kes on", "mis on", "uudis", "uudised", "err", "delfi", "postimees", "otsi", "mis juhtus"]) and not any(k in u for k in ["minu", "mu", "auto", "kodu", "elekter", "ilm"]):
        s = tavily_search(user_text)
        if s: blocks.append(f"[REAALAJAS VEEBI OTSINGUTULEMUSED]:\n{s}")
    mem = get_stored_memory_and_knowledge(persona)
    if mem: blocks.append(mem)
    return "\n\n".join(blocks)


# --- LISATÖÖRIISTAD: ERR UUDISED JA KRÜPTOTURG ---
import urllib.request
import json
import re
import xml.etree.ElementTree as ET

def get_news_overview(topic: str = "uudised") -> str:
    try:
        return global_pulse.get_pulse_summary(topic)
    except Exception as e:
        print("[BRAIN] global_pulse viga:", e, flush=True)
    """Loeb reaalajas ERR ametlikust RSS-voost viimased pealkirjad."""
    feeds = {
        "uudised": "https://www.err.ee/rss",
        "majandus": "https://www.err.ee/k/majandus/rss",
        "valismaa": "https://www.err.ee/k/valismaa/rss",
        "sport": "https://sport.err.ee/rss"
    }
    url = feeds.get(topic.lower(), feeds["uudised"])
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MayaVoiceAgent)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        items = root.findall("./channel/item")[:5]
        if not items:
            return "Värskeid uudiseid ei õnnestunud hetkel lugeda."
        news_list = []
        for i, it in enumerate(items, 1):
            title = (it.findtext("title") or "").strip()
            desc = (it.findtext("description") or "").strip()
            desc = re.sub(r"<[^>]+>", "", desc)
            news_list.append(f"{i}. {title}" + (f" - {desc[:120]}..." if desc else ""))
        return "Viimased ERR uudised:\n" + "\n".join(news_list)
    except Exception as e:
        print(f"--> [ERR UUDISED VIGA]: {e}", flush=True)
        return "Uudistevoo pärimisel tekkis tõrge."

def get_crypto_overview(coins: str = "bitcoin,ethereum,solana") -> str:
    """Pärib reaalajas krüptoturu hinnad eurodes ja 24h muutuse."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,ripple&vs_currencies=eur&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MayaVoiceAgent)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        mapping = {
            "bitcoin": "Bitcoin (BTC)",
            "ethereum": "Ethereum (ETH)",
            "solana": "Solana (SOL)",
            "ripple": "XRP"
        }
        lines = ["Hetke krüptoturu hinnad:"]
        for cid, name in mapping.items():
            if cid in data:
                price = data[cid].get("eur", 0)
                change = data[cid].get("eur_24h_change", 0.0)
                ch_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
                lines.append(f"- {name}: {price:,.2f} € (24h: {ch_str})")
        return "\n".join(lines)
    except Exception as e:
        print(f"--> [KRÜPTO VIGA]: {e}", flush=True)
        return "Krüptoturu andmeid ei õnnestunud hetkel pärida."

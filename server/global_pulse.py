import time
import urllib.request
import xml.etree.ElementTree as ET
import re
from typing import List, Dict

FEEDS = {
    # Alternatiivsed ja konservatiivsed Eesti allikad
    'Objektiiv': {'url': 'https://objektiiv.ee/feed/', 'category': 'alt_ee'},
    'Uued Uudised': {'url': 'https://uueduudised.ee/feed/', 'category': 'alt_ee'},
    'Makroskoop': {'url': 'https://makroskoop.ee/feed/', 'category': 'alt_ee'},

    # Rahvusvaheline alternatiivne ja majanduslik vaade
    'ZeroHedge': {'url': 'https://feeds.feedburner.com/zerohedge/feed', 'category': 'alt_global'},

    # UFO, UAP ja anomaaliate värsked raportid
    'The Debrief (UAP)': {'url': 'https://thedebrief.org/feed/', 'category': 'ufo_uap'},
    'Latest UFO Sightings': {'url': 'https://www.latest-ufo-sightings.net/feed/', 'category': 'ufo_uap'},
    'The Black Vault': {'url': 'https://www.theblackvault.com/feed/', 'category': 'ufo_uap'},

    # Peavool ja ametlikud teated (võrdluseks)
    'ERR Uudised': {'url': 'https://www.err.ee/rss', 'category': 'mainstream_ee'},
    'ERR Välismaa': {'url': 'https://www.err.ee/k/valismaa/rss', 'category': 'mainstream_ee'},
}

_cached_news: List[Dict] = []
_last_fetch = 0

def clean_html(raw_html: str) -> str:
    clean = re.sub(r'<.*?>', '', raw_html or '')
    clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&#039;', "'")
    return ' '.join(clean.split())[:180]

def parse_rss_feed(url: str, timeout: int = 5) -> List[Dict]:
    items = []
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MayaNewsBot/2.0'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        
        channel = root.find('channel')
        entries = channel.findall('item') if channel is not None else root.findall('{http://www.w3.org/2005/Atom}entry')
        
        for item in entries[:4]:
            title = ''
            desc = ''
            if channel is not None:
                t_el = item.find('title')
                d_el = item.find('description')
                if t_el is not None and t_el.text:
                    title = t_el.text.strip()
                if d_el is not None and d_el.text:
                    desc = clean_html(d_el.text)
            else:
                t_el = item.find('{http://www.w3.org/2005/Atom}title')
                s_el = item.find('{http://www.w3.org/2005/Atom}summary')
                if t_el is not None and t_el.text:
                    title = t_el.text.strip()
                if s_el is not None and s_el.text:
                    desc = clean_html(s_el.text)
            
            if title:
                items.append({'title': title, 'desc': desc})
    except Exception:
        pass
    return items

def refresh_pulse_feeds(force: bool = False) -> List[Dict]:
    global _cached_news, _last_fetch
    now = time.time()
    
    if not force and _cached_news and (now - _last_fetch < 900):
        return _cached_news

    collected = []
    for source_name, cfg in FEEDS.items():
        parsed = parse_rss_feed(cfg['url'])
        for item in parsed:
            collected.append({
                'source': source_name,
                'category': cfg['category'],
                'title': item['title'],
                'desc': item['desc']
            })

    if collected:
        _cached_news = collected
        _last_fetch = now

    return _cached_news

def get_pulse_summary(topic_query: str = '') -> str:
    news = refresh_pulse_feeds()
    if not news:
        return 'Värskeid uudiseid ei õnnestunud hetkel laadida.'

    q = (topic_query or '').strip().lower()
    is_ufo_query = any(k in q for k in ['ufo', 'uap', 'tulnuk', 'anomaal', 'lendav', 'tulnukad'])

    if is_ufo_query:
        ufo_items = [f"- [{n['source']}]: {n['title']}" for n in news if n['category'] == 'ufo_uap']
        if ufo_items:
            return 'VÄRSKED GLOBAALSED UFO / UAP VAATLUSED JA ANOMAALIAD:\n' + '\n'.join(ufo_items[:6])

    if q and q not in ['kõik', 'uudised', 'üldine']:
        filtered = [n for n in news if q in n['title'].lower() or q in n['desc'].lower()]
        if filtered:
            news = filtered

    alt_ee = [f"- [{n['source']}]: {n['title']}" for n in news if n['category'] == 'alt_ee'][:3]
    alt_global = [f"- [{n['source']}]: {n['title']}" for n in news if n['category'] == 'alt_global'][:3]
    ufo = [f"- [{n['source']}]: {n['title']}" for n in news if n['category'] == 'ufo_uap'][:3]
    mainstream = [f"- [{n['source']}]: {n['title']}" for n in news if n['category'] == 'mainstream_ee'][:2]

    res = []
    if alt_ee:
        res.append('Alternatiiv- ja konservatiivne Eesti meedia:\n' + '\n'.join(alt_ee))
    if alt_global:
        res.append('Sõltumatu välismeedia (ZeroHedge):\n' + '\n'.join(alt_global))
    if ufo:
        res.append('Värsked UFO ja UAP nähtused maailmas:\n' + '\n'.join(ufo))
    if mainstream:
        res.append('Peavoolu ametlikud teated (ERR võrdluseks):\n' + '\n'.join(mainstream))

    return '\n\n'.join(res)

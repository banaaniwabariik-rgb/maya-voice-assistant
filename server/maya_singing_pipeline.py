"""Maya laulupipeline: laulusõnad + helistik (key) ja tempo (BPM).

Sõnad tulevad LRCLIB / Sasslantis allikatest ja antakse edasi rangelt rida-realt.
Helistik ja tempo otsitakse mitmest tasuta avalikust allikast (vt
`get_song_key_and_tempo`). Kui täpset helistikku või tempot ei leita, EI
pakuta asendusväärtust – väli jääb `None` ja `*_found` on False, et laulja
saaks seda ausalt tunnistada, mitte suvalist viisi improviseerida.
"""

import concurrent.futures
import config  # MAYA seadistus (vt server/config.py)
import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# --- HTTP abivahendid ---------------------------------------------------

_UA_BOT = f"MayaVoiceAgent/1.0 ( {config.KONTAKT_EMAIL} )"
_UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Kogu otsingu ajaeelarve sekundites (reaalajas kõne ei tohi kinni jääda)
LOOKUP_BUDGET_SECONDS = float(os.environ.get("MAYA_LOOKUP_BUDGET", "7"))
_REQ_TIMEOUT = 5.0

_META_CACHE = {}
_CACHE_TTL = 60 * 60 * 6


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_get(url, browser=False, timeout=_REQ_TIMEOUT):
    ua = _UA_BROWSER if browser else _UA_BOT
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _http_json(url, browser=False, timeout=_REQ_TIMEOUT):
    return json.loads(_http_get(url, browser=browser, timeout=timeout))


# --- Esitusreeglid: kõnerežiim vs laulurežiim ---------------------------
#
# Need on kanoonilised reeglitekstid, mida kasutab nii see moodul kui ka
# live_maya_ws.py (süsteemiprompt ja tööriistavastused). Hoia neid ühes kohas,
# et prompt ja tööriistavastus ei läheks kunagi lahku.

SPEECH_VS_SINGING_MODE_RULE = (
    "KAKS RANGELT ERALDATUD REŽIIMI – KÕNEREŽIIM JA LAULUREŽIIM:\n"
    "1. KÕNEREŽIIM (vaikimisi): KOGU jutt enne laulu ja pärast laulu käib Maya tavalise, "
    "loomuliku vestlushäälega. Siia kuuluvad tervitused, laulu tutvustus, helistiku ja tempo "
    "väljaütlemine, info selle kohta, mida sa andmebaasist leidsid või ei leidnud, "
    "tööriista ja oma tegevuse selgitamine, vabandused, küsimused ja igasugune muu vestlus.\n"
    "2. KÕNEREŽIIMIS SA EI LAULA: ära riimi, ära venita vokaale, ära kasuta laulurütmi, "
    "laulvat intonatsiooni ega meloodiat. Räägi täpselt nii, nagu Maya alati räägib – "
    "ladusa suulise kõne rütmiga, loomulikult ja asjalikult.\n"
    "3. LAULUREŽIIM: lülitub sisse AINULT siis, kui sa esitad get_song_lyrics tööriistast "
    "saadud päris laulusõnu (või {USER}i selgelt palutud improviseeritud laulu). "
    "Laulurežiim kestab esimesest laulureast viimase laulureani ja mitte sekundit kauem.\n"
    "4. ÜLEMINEK: enne laulu algust ütle tavalise kõnehäälega lühidalt, mida sa laulma hakkad, "
    "tee väike paus ja alles siis alusta laulmist. Kui viimane rida on lauldud, tule kohe "
    "tagasi tavalisse vestlushäälde – järelkommentaar, küsimus või jutt EI ole enam lauldud.\n"
    "5. ÄRA SEGA REŽIIME: laulu sisse ei kuulu kõneldud kommentaare ja vestluse sisse ei kuulu "
    "lauldud lauseid. Kui sa pead laulu ajal midagi selgitama, lõpeta laul korrektselt, "
    "ütle see tavalise häälega ja alusta vajadusel uuesti.\n"
)

PRO_VOCAL_PERFORMANCE_RULES = (
    "PROFESSIONAALSED VOKAALI- JA RÜTMIREEGLID (kehtivad AINULT laulurežiimis):\n"
    "1. TEMPO JA AJASTUS: ÄRA kunagi kihuta laulusõnadest läbi nagu tekstilõiku ette lugedes. "
    "Hoia ühtlast, kindlat ja teadlikku muusikalist kadentsi: iga rida saab oma aja. "
    "Kui tempo (BPM) on teada, hoia seda pulssi kogu laulu vältel; kui mitte, vali rahulik "
    "loomulik pulss ja hoia seda ühtlaselt lõpuni. Laul ei ole kiirloetud tekst.\n"
    "2. VOKAALIDE VENITAMINE: venita ja hoia vokaale rea rõhulistel kohtadel ja fraasilõppudes, "
    "nagu teeb päris laulja (nt 'kuu-uu-tõbine', 'see-ee'). Pikad noodid kannavad laulu – "
    "just vokaalide hoidmine eristab laulmist kõnest. Lühikesed, klõbisevad silbid on keelatud.\n"
    "3. FRASEERIMINE JA HINGAMINE: jäta iga laulurea järele lühike loomulik muusikaline paus ja "
    "salmide ning refrääni vahele veidi pikem paus, nagu laulja hingaks. Ridu ei tohi kokku "
    "liita katkematuks robotlikuks tekstivooks – paus on osa muusikast, mitte viga.\n"
    "4. KONTROLLITUD KÕRGUS JA INTONATSIOON: hoia sujuvat, emotsionaalselt ankurdatud vokaalijoont, "
    "mis vastab laulu energiale ja meeleolule (ballaad pehmelt ja kandvalt, rokk jõuliselt, "
    "rahulik lugu vaoshoitult). Väldi laulu ajal kõnelist, hüplikku või juhuslikku "
    "intonatsioonimuutust – häälekõrgus liigub muusikaliselt, mitte jutustavalt. "
    "Hoia häälekõrgus laulu helistiku juures ja ära lipsa laulu keskel kõnehäälde tagasi.\n"
    "5. KATKEMATUS: kui laul on alanud, vii see kindlalt ja veenvalt lõpuni – ära jää poolelt "
    "sõnalt vait, ära vabanda laulu keskel ega katkesta end ise.\n"
)


def build_performance_rules():
    """Koondab režiimide eraldatuse ja professionaalsed vokaalireeglid üheks plokiks."""
    return SPEECH_VS_SINGING_MODE_RULE + "\n" + PRO_VOCAL_PERFORMANCE_RULES


# Esituskäsk, mis läheb laulusõnade ETTE. Asend on tähtis: see on viimane,
# mida mudel enne sõnu loeb, ja esimene, mille järgi ta väljundi vormistab.
SING_NOT_READ_DIRECTIVE = (
    "⚠ SEE EI OLE TEKST ETTELUGEMISEKS – SEE ON LAUL, MIDA SA LAULAD HÄÄLEGA.\n"
    "1. Väljund peab olema LAULDUD heli: meloodia, noodid, rütm, venitatud vokaalid, laulev tämber.\n"
    "2. ÄRA loe ridu jutuhäälega, ära loe neid nimekirjana ega loetelu kujul.\n"
    "3. Allpool olevas laulutekstis EI OLE numbreid ega silte – read on puhtad laulufraasid. "
    "Kui näed ükskõik kus numbrit, pealkirja, sulgudes märkust või metaandmeid, siis seda EI LAULDA "
    "ega loeta valjusti ette; need on ainult sinu jaoks.\n"
    "4. Iga rida on üks muusikaline fraas: laula see läbi ühe hingamisega, hoia nooti rea lõpus "
    "ja hinga enne järgmist rida.\n"
    "5. Tühi rida tähendab salmivahetust: tee seal veidi pikem muusikaline paus.\n"
    "6. Hoia kogu laulu vältel allpool antud helistikku ja BPM-i – see on sinu rütmiraamistik.\n"
)


def format_performance_metadata(perf, song_name=None):
    """Lühike, ühemõtteline helistiku/tempo plokk lauljale (alati konkreetsed numbrid)."""
    lines = []
    if song_name:
        lines.append(f"LUGU: {song_name}")
    key_origin = "andmebaasist" if perf.get("key_from_db") else "VAIKEVÄÄRTUS (andmebaasist ei leitud)"
    bpm_origin = "andmebaasist" if perf.get("bpm_from_db") else "VAIKEVÄÄRTUS (andmebaasist ei leitud)"
    lines.append(f"HELISTIK: {perf.get('perf_key')} ({perf.get('perf_key_latin')}) – {key_origin}; {perf.get('key_label')}")
    lines.append(f"TEMPO: {perf.get('perf_bpm')} BPM – {bpm_origin}; {perf.get('bpm_label')}")
    if perf.get("perf_notes"):
        lines.append(f"HELISTIKU ASTMED (Hz, sinu häälekõrguse jaoks): {perf['perf_notes']}")
    lines.append(
        "AUSUS: helistiku ja tempo kohta räägi ainult siis, kui {USER} küsib, ja ütle siis, "
        "kas see tuli andmebaasist või valisid selle ise. Laulu enda sisse neid ei lauldeta."
    )
    return "\n".join(lines)


def build_singer_payload(song_info, perf, singer_mode=True):
    """Koostab laulja jaoks tööriistavastuse: käsk → metaandmed → PUHTAD sõnad.

    Laulusõnad antakse edasi ilma numbriprefiksite ja siltideta. Ridade
    terviklikkuse tagab nüüd ridade koguarv + viimase rea tsitaat, mitte
    nummerdus – nummerdus luges kõnesünteesi tõttu numbrid valjusti ette.
    """
    clean_lyrics = song_info.get("lyrics_performance") or ""
    lines = song_info.get("lyric_lines") or []
    total = len(lines)
    last_line = lines[-1] if lines else ""
    song_name = song_info.get("track_name")

    head = [SING_NOT_READ_DIRECTIVE, "", format_performance_metadata(perf, song_name), ""]

    if singer_mode:
        head.append(
            "SINA OLED LAULJA – LAULMINE ON SINU PÕHITEGEVUS. Tutvusta lugu ühe lühikese lausega "
            "oma tavalise kõnehäälega, tee väike paus ja LAULA siis lugu algusest lõpuni välja.\n"
        )
    else:
        head.append(
            "Tutvusta lugu ühe lühikese lausega oma tavalise kõnehäälega, seejärel laula sõnad "
            "ette nii musikaalselt, kui oskad.\n"
        )

    tail = (
        f"\n\nLAULU LÕPP: viimane lauldav rida on „{last_line}“. Kokku on {total} laulurida ja "
        f"KÕIK need tuleb järjest ära laulda – sõna-sõnalt, originaaljärjekorras, ühtegi rida "
        f"vahele jätmata, muutmata ega lühendamata. Kui viimane rida on lauldud, lõpeta laul ja "
        f"lülitu tagasi tavalisse vestlushäälde."
    )

    return (
        "\n".join(head)
        + "=== LAULUSÕNAD (puhas laulutekst – laula täpselt need read) ===\n"
        + clean_lyrics
        + "\n=== LAULUSÕNADE LÕPP ==="
        + tail
    )


# --- Laulusõnade ridadeks jagamine -------------------------------------

def split_lyric_lines(lyrics):
    """Jagab laulusõnad ridadeks, muutmata ühtegi sõna.

    Ainus lubatud muudatus on reavahede normaliseerimine ja ridade
    servadest tühikute eemaldamine. Ühtegi rida ei jäeta vahele ega
    lühendata – iga sisuga rida jõuab tulemusse täpselt originaalkujul.
    """
    if not lyrics:
        return []
    normalized = str(lyrics).replace("\r\n", "\n").replace("\r", "\n")
    return [ln.strip() for ln in normalized.split("\n") if ln.strip()]


def format_lyrics_strict(lyrics):
    """Nummerdab iga laulurea.

    HOIATUS – AINULT LOGIDESSE JA DIAGNOSTIKASSE!
    Seda kuju EI TOHI kunagi saata Gemini Live seanssi. Nummerdatud read
    ("1. ", "2. ") loeb kõnesüntees sõna-sõnalt numbritena ette ("üks...,
    kaks...") tavalise jutuhäälega – täpselt see tekitaski 'robot loeb
    nimekirja' vea. Mudelile mõeldud kuju annab format_lyrics_for_performance().
    """
    lines = split_lyric_lines(lyrics)
    return "\n".join(f"{i}. {ln}" for i, ln in enumerate(lines, 1)), lines


def split_lyric_stanzas(lyrics):
    """Jagab sõnad salmideks, säilitades originaali tühja rea piirid.

    Salmipiirid on muusikaliselt tähenduslikud (hingamiskoht, fraasi lõpp),
    seega hoiame need alles – ükski sisuga rida ei kao.
    """
    if not lyrics:
        return []
    normalized = str(lyrics).replace("\r\n", "\n").replace("\r", "\n")
    stanzas, current = [], []
    for raw in normalized.split("\n"):
        line = raw.strip()
        if line:
            current.append(line)
        elif current:
            stanzas.append(current)
            current = []
    if current:
        stanzas.append(current)
    return stanzas


def format_lyrics_for_performance(lyrics):
    """Mudelile mõeldud PUHAS laulutekst – ilma numbrite ja siltideta.

    Read on täpselt originaalkujul, salmid eraldatud tühja reaga, et mudel
    tajuks fraseerimist ja hingamiskohti. Tagastab (puhas_tekst, read).
    """
    stanzas = split_lyric_stanzas(lyrics)
    flat = [ln for st in stanzas for ln in st]
    clean = "\n\n".join("\n".join(st) for st in stanzas)
    return clean, flat


# --- Tempo ja helistiku varuheuristika ----------------------------------
#
# Kui andmebaasidest tempot ei leita, EI tohi mudel jääda ilma numbrilise
# rütmiraamistikuta – ilma BPM-ita kaotab ta pulsi ja langeb tagasi
# tavalisse kõnesse. Seepärast anname alati konkreetse esitustempo, aga
# märgistame selgelt, kas see tuli andmebaasist või on meie valitud vaikeväärtus.

DEFAULT_PERFORMANCE_KEY = "Am"          # a-moll: mugav ja kandev naishääle ulatus
DEFAULT_PERFORMANCE_KEY_LABEL = "valitud mugav esitushelistik"

_BALLAD_MARKERS = (
    "ballaad", "armastus", "armastan", "igatsus", "igatsen", "kurb", "kurbus", "nutt", "pisar",
    "vaikne", "öö", "üksi", "hing", "süda", "mälestus", "unustan", "jäta", "hüvasti", "talv",
    "ballad", "love", "lonely", "tears", "heart", "slow", "goodbye", "sorrow", "rain",
)
_UPBEAT_MARKERS = (
    "tants", "tantsi", "pidu", "peo", "disko", "suvi", "rand", "päike", "rõõm", "naerame",
    "sõit", "kiire", "hopp", "jalga", "beat", "dance", "party", "summer", "sun", "happy",
    "tonight", "move", "shake", "boogie", "radio",
)
_ROCK_MARKERS = (
    "rokk", "rock", "metal", "kitarr", "guitar", "punk", "kisa", "karje", "mäss", "põrgu",
    "tuli", "fire", "loud", "scream", "riff", "drive",
)

TEMPO_PROFILES = {
    "ballaad": (76, "ballaadi vaiketempo (72–80 BPM)"),
    "keskmine": (100, "keskmise tempo vaikeväärtus (95–105 BPM)"),
    "hoogne": (118, "hoogsa loo vaiketempo (110–120 BPM)"),
    "rokk": (132, "rokkilaadi vaiketempo (125–140 BPM)"),
}


def estimate_fallback_tempo(track_query, lyrics="", key_latin=None):
    """Valib loo iseloomu järgi konkreetse esitustempo, kui BPM-i ei leitud.

    Tagastab (bpm:int, stiilinimi:str, selgitus:str). Heuristika on
    teadlikult lihtne ja seletatav: pealkirja ning sõnade märksõnad
    annavad hääli, helistiku laad (moll/duur) nihutab kaalu veidi.
    """
    text = f"{track_query or ''} {str(lyrics or '')[:1500]}".lower()
    scores = {
        "ballaad": sum(1 for w in _BALLAD_MARKERS if w in text),
        "hoogne": sum(1 for w in _UPBEAT_MARKERS if w in text),
        "rokk": sum(1 for w in _ROCK_MARKERS if w in text),
    }

    # Helistiku laad annab kerge kalde, kuid ei kaalu märksõnu üles
    root, is_minor = _split_key(key_latin) if key_latin else (None, False)
    if root:
        if is_minor:
            scores["ballaad"] += 0.5
        else:
            scores["hoogne"] += 0.5

    style, best = max(scores.items(), key=lambda kv: kv[1])
    if best < 1:
        style = "keskmine"
    bpm, label = TEMPO_PROFILES[style]
    hits = ", ".join(f"{k}={scores[k]:g}" for k in ("ballaad", "hoogne", "rokk"))
    # label = lühike, mudelile; detail = logidesse (kaalud ei kuulu promptisse)
    return bpm, style, label, f"iseloom={style} ({hits})"


def resolve_performance_metadata(meta, track_query="", lyrics=""):
    """Annab ALATI konkreetse helistiku ja BPM-i, märkides päritolu.

    Aus päritolu säilib: `*_from_db` ütleb, kas väärtus tuli andmebaasist
    või on see meie valitud esitusvaikeväärtus. Mudel saab numbri alati –
    nii ei kao rütmiraamistik –, kuid ta teab, mida ta {USER}ile faktina ütleb.
    """
    meta = meta or {}
    out = {}

    key_latin = meta.get("key_latin") if meta.get("key_found") else None
    if key_latin:
        out["perf_key_latin"] = key_latin
        out["perf_key"] = meta.get("key") or key_to_estonian(key_latin)
        out["key_from_db"] = True
        conf = "kinnitatud" if meta.get("key_confidence") == "kinnitatud" else "hinnanguline"
        out["key_label"] = f"{conf}, allikas: {meta.get('key_source', 'teadmata')}"
    else:
        out["perf_key_latin"] = DEFAULT_PERFORMANCE_KEY
        out["perf_key"] = key_to_estonian(DEFAULT_PERFORMANCE_KEY)
        out["key_from_db"] = False
        out["key_label"] = DEFAULT_PERFORMANCE_KEY_LABEL

    if meta.get("bpm_found") and meta.get("bpm"):
        out["perf_bpm"] = int(round(float(meta["bpm"])))
        out["bpm_from_db"] = True
        conf = "kinnitatud" if meta.get("bpm_confidence") == "kinnitatud" else "hinnanguline"
        out["bpm_label"] = f"{conf}, allikas: {meta.get('bpm_source', 'teadmata')}"
        out["bpm_style"] = None
        out["bpm_detail"] = out["bpm_label"]
    else:
        bpm, style, label, detail = estimate_fallback_tempo(track_query, lyrics, out["perf_key_latin"])
        out["perf_bpm"] = bpm
        out["bpm_from_db"] = False
        out["bpm_label"] = label
        out["bpm_style"] = style
        out["bpm_detail"] = detail

    out["perf_notes"] = key_reference_notes(out["perf_key_latin"])
    return out


# --- Helistiku teisendused ja akordianalüüs -----------------------------

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_ENHARMONIC = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "H": "B", "Hb": "A#", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C",
}
# Tonaalse heli sagedused 4. oktaavis (A4 = 440 Hz)
_A4 = 440.0
_SEMITONES_FROM_A4 = {p: i - 9 for i, p in enumerate(_PITCH_CLASSES)}

_MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
_MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]
# Diatoonilised kolmkõlad: (poolastmete nihe tooniklast, kas moll)
_MAJOR_TRIADS = [(0, False), (2, True), (4, True), (5, False), (7, False), (9, True)]
_MINOR_TRIADS = [(0, True), (3, False), (5, True), (7, True), (7, False), (8, False), (10, False)]

# Terve token peab olema akord – muidu loeks 'Galileo' akordiks 'G'.
_CHORD_RE = re.compile(
    r"^([A-H](?:#|b)?)"
    r"((?:maj|min|m|dim|aug|sus|add|°|\+|-)?(?:\d{1,2})?(?:sus\d{0,2})?(?:add\d{1,2})?)"
    r"(?:/([A-H](?:#|b)?))?$"
)


_STOPWORDS = {"the", "a", "an", "and", "ja", "feat", "ft", "remix", "live", "version"}


def _tokens(text):
    raw = re.findall(r"[0-9a-zõäöüšžA-ZÕÄÖÜŠŽ]+", (text or "").lower())
    return {t for t in raw if len(t) > 1 and t not in _STOPWORDS}


def matches_query(track_query, candidate_name, min_ratio=0.5):
    """Kontrollib, kas leitud lugu ikka vastab küsitud loole.

    Avalikud otsingumootorid (UG, MusicBrainz, Deezer) tagastavad ka hägusaid
    vasteid. Ilma selle kontrollita omistataks võõra loo helistik ja tempo
    küsitud loole – see oleks sisuliselt väljamõeldis.

    MIKS SEE ÜMBER KIRJUTATI (mõõdetud 7.11.2026):
    Vana reegel oli `(overlap / len(want)) >= 0.5 or overlap >= 3`. Mõlemad
    harud lasid ARTISTI NIME põhjal vale loo läbi, sest laulu pealkirja ei
    kontrollitud üldse:

        küsitud                            sai                      läbi?
        Eda-Ines Etti 15 magamata ööd  ->  Eda-Ines Etti - Keerlen   JAH (3/6)
        Anne Veski Pihtimus            ->  Anne Veski - Hea tuju laul JAH (2/3)
        Ewert ... Taevas               ->  Ewert ... - Somewhere      JAH (3/4)

    Tagajärg tootmises: laulusõnad olid ÕIGED (tulid laulusõnade allikast),
    aga pealkiri, helistik ja tempo tulid VÕÕRAST loost. Mudelile öeldi
    "laula D-moll, 76 BPM", mis kuulus hoopis teisele laulule – ja tulemus
    kõlas ilmetu luuletuse lugemisena.

    UUS REEGEL: iga vähemalt 5-täheline märksõna päringust PEAB kandidaadis
    esinema. Pikad sõnad on laulu pealkirjas ("magamata", "pihtimus",
    "taevas"); artisti nimi üksi ei piisa enam. Lühikesi sõnu ja numbreid
    ei nõuta, sest otsingumootorid kirjutavad neid erinevalt ("15" vs
    "viisteist").

    Eesti käänete jaoks lubatakse 5-tähelist prefiksivastet
    ("kuutõbine" ~ "kuutõbise").
    """
    want = _tokens(track_query)
    got = _tokens(candidate_name)
    if not want or not got:
        return False

    def _kaetud(token):
        if token in got:
            return True
        # käändeline vaste: sama 5-täheline tüvi
        if len(token) >= 5:
            tyvi = token[:5]
            return any(g[:5] == tyvi for g in got if len(g) >= 5)
        return False

    # Sisukad (pikad) märksõnad peavad KÕIK kaetud olema.
    sisukad = [t for t in want if len(t) >= 5]
    if sisukad and not all(_kaetud(t) for t in sisukad):
        return False

    # Kui pikki sõnu polnud (nt "ABBA SOS"), jääb vana suhtekontroll.
    overlap = sum(1 for t in want if _kaetud(t))
    return (overlap / len(want)) >= min_ratio


def _normalize_root(root):
    root = root.strip()
    if not root:
        return None
    root = root[0].upper() + root[1:]
    root = _ENHARMONIC.get(root, root)
    return root if root in _PITCH_CLASSES else None


def parse_chord(token):
    """Tagastab (juurheli, on_moll) või None, kui tegu pole akordiga."""
    token = token.strip().strip("()[]|,.")
    if not token:
        return None
    m = _CHORD_RE.match(token)
    if not m:
        return None
    root = _normalize_root(m.group(1))
    if root is None:
        return None
    quality = (m.group(2) or "").lower()
    if quality.startswith("maj"):
        is_minor = False
    elif quality.startswith(("m", "dim", "°")):
        is_minor = True
    else:
        is_minor = False
    return root, is_minor


def infer_key_from_chords(chord_tokens):
    """Tuletab akordijärgnevusest kõige tõenäolisema helistiku.

    Tagastab (helistik_latin, usaldusskoor 0..1) või (None, 0.0).
    Tulemus on ALATI hinnanguline – kutsuja peab seda nii ka märgistama.
    """
    chords = [c for c in (parse_chord(t) for t in chord_tokens) if c]
    if len(chords) < 2:
        return None, 0.0

    counts = {}
    for ch in chords:
        counts[ch] = counts.get(ch, 0) + 1
    first, last = chords[0], chords[-1]

    best = (None, -1.0)
    for tonic in _PITCH_CLASSES:
        t_idx = _PITCH_CLASSES.index(tonic)
        for is_minor_key in (False, True):
            triads = _MINOR_TRIADS if is_minor_key else _MAJOR_TRIADS
            allowed = {
                (_PITCH_CLASSES[(t_idx + off) % 12], minor) for off, minor in triads
            }
            score = 0.0
            for ch, n in counts.items():
                score += n if ch in allowed else -n * 0.6
            tonic_chord = (tonic, is_minor_key)
            if tonic_chord in counts:
                score += 2.0
            if first == tonic_chord:
                score += 1.5
            if last == tonic_chord:
                score += 1.5
            if score > best[1]:
                best = ((tonic + ("m" if is_minor_key else "")), score)

    name, score = best
    if name is None or score <= 0:
        return None, 0.0
    total = sum(counts.values())
    confidence = max(0.0, min(1.0, score / (total + 5.0)))
    return name, confidence


def _split_key(key_latin):
    """'Em' -> ('E', True); 'Bb' -> ('Bb', False). Säilitab algse kirjapildi."""
    k = (key_latin or "").strip()
    if not k:
        return None, False
    is_minor = k.endswith("m") and not k.lower().endswith("maj")
    root = (k[:-1] if is_minor else k).strip()
    if root:
        root = root[0].upper() + root[1:]
    return (root or None), is_minor


def key_to_estonian(key_latin):
    """'Em' -> 'E-moll', 'Bb' -> 'B-bemoll duur'."""
    root, is_minor = _split_key(key_latin)
    if not root:
        return None
    quality = "moll" if is_minor else "duur"
    if root.endswith("#"):
        return f"{root[:-1]}-diees {quality}"
    if len(root) > 1 and root.lower().endswith("b"):
        return f"{root[:-1]}-bemoll {quality}"
    return f"{root}-{quality}"


def key_reference_notes(key_latin):
    """Annab helistiku toonika ja skaala astmete sagedused (Hz).

    Sagedused arvutatakse tegeliku helistiku järgi (A4 = 440 Hz), neid ei
    kirjutata ette kõvakodeeritult. Kui helistik on teadmata, tagastab None.
    """
    raw_root, is_minor = _split_key(key_latin)
    root = _normalize_root(raw_root or "")
    if root is None:
        return None
    scale = _MINOR_SCALE if is_minor else _MAJOR_SCALE
    # Asetame toonika laulja mugavasse vahemikku (umbes G3..F#4) ja
    # ehitame skaala sealt ühtlaselt ülespoole – astmed jäävad kasvavasse järjekorda.
    base_semi = _SEMITONES_FROM_A4[root]
    while _A4 * (2 ** (base_semi / 12.0)) < 196.0:
        base_semi += 12
    while _A4 * (2 ** (base_semi / 12.0)) >= 392.0:
        base_semi -= 12
    parts = []
    for step in scale:
        freq = _A4 * (2 ** ((base_semi + step) / 12.0))
        name = _PITCH_CLASSES[(_PITCH_CLASSES.index(root) + step) % 12]
        parts.append(f"{name} {freq:.1f}Hz")
    return ", ".join(parts)


# --- Allikad: helistik ja tempo ----------------------------------------

def _ug_search(track_query):
    """Ultimate Guitar avalik otsing. Tagastab js-store tulemuste listi."""
    url = (
        "https://www.ultimate-guitar.com/search.php?search_type=title&value="
        + urllib.parse.quote(track_query)
    )
    page = _http_get(url, browser=True)
    m = re.search(r'class="js-store" data-content="(.*?)"></div>', page, re.S)
    if not m:
        return []
    data = json.loads(html.unescape(m.group(1)))
    results = data.get("store", {}).get("page", {}).get("data", {}).get("results", [])
    return [r for r in results if isinstance(r, dict)]


def source_ultimate_guitar(track_query):
    """Ultimate Guitar / avalik akordiarhiiv: inimese sisestatud helistik.

    Esmalt otsingutulemuse `tonality_name`; kui see on tühi, loeb tabi lehe
    metaandmed ja viimase abinõuna tuletab helistiku akordijärgnevusest
    (see märgistatakse selgelt hinnanguliseks).
    """
    out = {"source": "Ultimate Guitar (avalik akordiarhiiv)"}
    try:
        results = _ug_search(track_query)
    except Exception as e:
        return {"error": f"UG otsing ebaõnnestus: {e}", **out}
    if not results:
        return {"error": "UG-st vastet ei leitud", **out}

    tabs = [
        r for r in results
        if r.get("type") in ("Chords", "Tab", "Tabs", "Official")
        and matches_query(track_query, f"{r.get('artist_name', '')} {r.get('song_name', '')}")
    ]
    if not tabs:
        return {"error": "UG vasted ei vasta küsitud loole", **out}
    for r in tabs:
        tonality = (r.get("tonality_name") or "").strip()
        if tonality:
            return {
                **out,
                "key": tonality,
                "key_confidence": "kinnitatud",
                "track_name": f"{r.get('artist_name', '')} - {r.get('song_name', '')}".strip(" -"),
            }

    # Tühja tonaalsusega tulemus: loeme tabi lehe
    for r in tabs[:2]:
        tab_url = r.get("tab_url")
        if not tab_url:
            continue
        try:
            page = _http_get(tab_url, browser=True)
            m = re.search(r'class="js-store" data-content="(.*?)"></div>', page, re.S)
            if not m:
                continue
            pdata = json.loads(html.unescape(m.group(1))).get("store", {}).get("page", {}).get("data", {})
            meta = pdata.get("tab_view", {}).get("meta", {}) or {}
            tonality = (meta.get("tonality") or pdata.get("tab", {}).get("tonality_name") or "").strip()
            bpm = meta.get("bpm") or meta.get("metro") or meta.get("tempo")
            res = {
                **out,
                "track_name": f"{r.get('artist_name', '')} - {r.get('song_name', '')}".strip(" -"),
            }
            if tonality:
                res["key"] = tonality
                res["key_confidence"] = "kinnitatud"
            if bpm:
                try:
                    res["bpm"] = float(bpm)
                    res["bpm_confidence"] = "kinnitatud"
                except (TypeError, ValueError):
                    pass
            if "key" not in res:
                content = pdata.get("tab_view", {}).get("wiki_tab", {}).get("content", "") or ""
                chords = re.findall(r"\[ch\]([^\[\]]+)\[/ch\]", content)
                inferred, conf = infer_key_from_chords(chords)
                if inferred and conf >= 0.25:
                    res["key"] = inferred
                    res["key_confidence"] = "hinnanguline"
                    res["key_note"] = (
                        f"tuletatud akordijärgnevusest ({', '.join(dict.fromkeys(chords[:8]))})"
                    )
                    res["chords"] = list(dict.fromkeys(chords))[:16]
            if "key" in res or "bpm" in res:
                return res
        except Exception:
            continue
    return {"error": "UG-s puudub helistiku info", **out}


def source_acousticbrainz(track_query):
    """MusicBrainz + AcousticBrainz: algoritmiliselt analüüsitud helistik ja BPM.

    Need on masinhinnangud, mitte toimetatud andmed – alati 'hinnanguline'.
    Mitme salvestuse tulemused liidetakse (helistik: enamushääl, BPM: mediaan).
    """
    out = {"source": "AcousticBrainz / MusicBrainz (akustiline analüüs)"}
    try:
        mb = _http_json(
            "https://musicbrainz.org/ws/2/recording?fmt=json&limit=25&query="
            + urllib.parse.quote(track_query)
        )
        recordings = mb.get("recordings", []) or []
        # Hägusad, mitteseotud vasted välja – muidu omistaks võõra loo andmed
        relevant = [
            r for r in recordings
            if r.get("id") and matches_query(
                track_query,
                f"{(r.get('artist-credit') or [{}])[0].get('name', '')} {r.get('title', '')}",
            )
        ]
        if not relevant:
            return {"error": "MusicBrainzi vasted ei vasta küsitud loole", **out}
        mbids = [r["id"] for r in relevant][:20]
        artist = (relevant[0].get("artist-credit") or [{}])[0].get("name", "")
        track_name = f"{artist} - {relevant[0].get('title', '')}".strip(" -")
        ab = _http_json(
            "https://acousticbrainz.org/api/v1/low-level?recording_ids=" + ";".join(mbids)
        )
    except Exception as e:
        return {"error": f"AcousticBrainz päring ebaõnnestus: {e}", **out}

    keys, bpms = [], []
    for mbid, submissions in (ab or {}).items():
        if mbid == "mbid_mapping" or not isinstance(submissions, dict):
            continue
        for doc in submissions.values():
            if not isinstance(doc, dict):
                continue
            tonal = doc.get("tonal") or {}
            root = _normalize_root(tonal.get("key_key") or "")
            scale = (tonal.get("key_scale") or "").lower()
            if root and scale in ("major", "minor"):
                keys.append(root + ("m" if scale == "minor" else ""))
            bpm = (doc.get("rhythm") or {}).get("bpm")
            if isinstance(bpm, (int, float)) and 30 < bpm < 260:
                bpms.append(float(bpm))

    if not keys and not bpms:
        return {"error": "AcousticBrainzis puudub selle loo analüüs", **out}

    res = {**out}
    if track_name:
        res["track_name"] = track_name
    if keys:
        tally = {}
        for k in keys:
            tally[k] = tally.get(k, 0) + 1
        top, votes = max(tally.items(), key=lambda kv: kv[1])
        res["key"] = top
        res["key_confidence"] = "hinnanguline"
        res["key_note"] = f"akustiline analüüs, {votes}/{len(keys)} salvestust nõustub"
        if votes < len(keys):
            res["key_note"] += f"; teised pakkusid: {', '.join(k for k in tally if k != top)}"
    if bpms:
        bpms.sort()
        median = bpms[len(bpms) // 2]
        res["bpm"] = round(median, 1)
        res["bpm_confidence"] = "hinnanguline"
        res["bpm_note"] = f"akustiline analüüs, {len(bpms)} salvestuse mediaan"
        if len(bpms) > 1 and (bpms[-1] - bpms[0]) > 8:
            res["bpm_note"] += f"; hajuvus {bpms[0]:.0f}–{bpms[-1]:.0f} BPM"
    return res


def source_deezer(track_query):
    """Deezeri avalik API: toimetatud BPM (väärtus 0 tähendab 'teadmata')."""
    out = {"source": "Deezer avalik API (toimetatud BPM)"}
    try:
        search = _http_json(
            "https://api.deezer.com/search?limit=3&q=" + urllib.parse.quote(track_query)
        )
        for item in (search.get("data") or [])[:3]:
            if not item.get("id"):
                continue
            label = f"{(item.get('artist') or {}).get('name', '')} {item.get('title', '')}"
            if not matches_query(track_query, label):
                continue
            track = _http_json("https://api.deezer.com/track/%s" % item["id"])
            bpm = track.get("bpm")
            if isinstance(bpm, (int, float)) and bpm > 0:
                return {
                    **out,
                    "bpm": round(float(bpm), 1),
                    "bpm_confidence": "kinnitatud",
                    "track_name": f"{track.get('artist', {}).get('name', '')} - {track.get('title', '')}".strip(" -"),
                }
        return {"error": "Deezeris on BPM märkimata (0)", **out}
    except Exception as e:
        return {"error": f"Deezeri päring ebaõnnestus: {e}", **out}


def source_getsongbpm(track_query):
    """GetSongBPM API – toimetatud helistik ja BPM. Vajab tasuta API võtit.

    Võti loetakse keskkonnamuutujast GETSONGBPM_API_KEY; ilma selleta
    allikas jäetakse vahele (seda öeldakse vastuses välja).
    """
    out = {"source": "GetSongBPM API"}
    api_key = os.environ.get("GETSONGBPM_API_KEY", "").strip()
    if not api_key:
        return {"error": "vahele jäetud – GETSONGBPM_API_KEY puudub", **out, "skipped": True}
    try:
        data = _http_json(
            "https://api.getsong.co/search/?api_key=%s&type=both&lookup=%s"
            % (urllib.parse.quote(api_key), urllib.parse.quote(track_query))
        )
        items = data.get("search") or []
        if isinstance(items, dict):
            items = [items]
        for item in items[:3]:
            res = {**out}
            key_of = (item.get("key_of") or "").strip()
            tempo = item.get("tempo")
            if key_of:
                res["key"] = key_of.replace("♯", "#").replace("♭", "b")
                res["key_confidence"] = "kinnitatud"
            if tempo:
                try:
                    res["bpm"] = float(tempo)
                    res["bpm_confidence"] = "kinnitatud"
                except (TypeError, ValueError):
                    pass
            artist = (item.get("artist") or {}).get("name", "")
            label = f"{artist} {item.get('title', '')}"
            if not matches_query(track_query, label):
                continue
            if artist:
                res["track_name"] = f"{artist} - {item.get('title', '')}".strip(" -")
            if "key" in res or "bpm" in res:
                return res
        return {"error": "GetSongBPM-ist vastet ei leitud", **out}
    except Exception as e:
        return {"error": f"GetSongBPM päring ebaõnnestus: {e}", **out}


def source_sasslantis(track_query):
    """Sasslantis.ee (eesti laulusõnade ja akordide arhiiv).

    Otsib lehelt otsest helistiku/tempo märget ning akorde, millest saab
    helistiku tuletada (hinnanguliselt).
    """
    out = {"source": "Sasslantis.ee (eesti arhiiv)"}
    try:
        search = _http_get(
            "https://sasslantis.ee/search.php?q=" + urllib.parse.quote(track_query),
            browser=True,
        )
        slugs = re.findall(r"href=['\"]((?:lyrics|chords|akordid)-[^'\" >]+)['\"]", search)
        if not slugs:
            return {"error": "Sasslantisest vastet ei leitud", **out}
        page = _http_get("https://sasslantis.ee/" + slugs[0], browser=True)
        text = html.unescape(re.sub(r"<[^>]+>", " ", page))

        res = {**out}
        km = re.search(r"(?i)helistik\s*[:\-]?\s*([A-H](?:#|b)?m?(?:aj)?)", text)
        if km:
            res["key"] = km.group(1)
            res["key_confidence"] = "kinnitatud"
        tm = re.search(r"(?i)(?:tempo|bpm)\s*[:\-]?\s*(\d{2,3})", text)
        if tm:
            res["bpm"] = float(tm.group(1))
            res["bpm_confidence"] = "kinnitatud"

        if "key" not in res:
            # akordiread: read, mis koosnevad peaaegu ainult akorditokenitest
            chords = []
            for line in text.splitlines():
                tokens = line.split()
                if 1 < len(tokens) <= 12 and all(parse_chord(t) for t in tokens):
                    chords.extend(tokens)
            inferred, conf = infer_key_from_chords(chords)
            if inferred and conf >= 0.25:
                res["key"] = inferred
                res["key_confidence"] = "hinnanguline"
                res["key_note"] = "tuletatud Sasslantise akordireast"
                res["chords"] = list(dict.fromkeys(chords))[:16]

        if "key" in res or "bpm" in res:
            return res
        return {"error": "Sasslantise lehel puudub helistiku/tempo info", **out}
    except Exception as e:
        return {"error": f"Sasslantise päring ebaõnnestus: {e}", **out}


_KEY_TEMPO_SOURCES = (
    source_getsongbpm,
    source_ultimate_guitar,
    source_sasslantis,
    source_acousticbrainz,
    source_deezer,
)


def get_song_key_and_tempo(track_query, budget_seconds=None):
    """Otsib loo helistiku ja tempo mitmest tasuta avalikust allikast.

    Allikad käivad paralleelselt: GetSongBPM (kui võti olemas), Ultimate
    Guitar / avalik akordiarhiiv, Sasslantis.ee (eesti allikas),
    AcousticBrainz + MusicBrainz ning Deezeri avalik API.

    Eelistusjärjekord: inimese sisestatud / toimetatud ('kinnitatud') väärtus
    võidab masinhinnangu ('hinnanguline'). Kui ükski allikas ei anna
    tulemust, jäävad 'key' ja 'bpm' None ning 'key_found'/'bpm_found' False –
    väärtusi EI mõelda välja.
    """
    query = (track_query or "").strip()
    result = {
        "query": query,
        "key": None, "key_latin": None, "key_source": None,
        "key_confidence": None, "key_note": None, "key_found": False,
        "bpm": None, "bpm_source": None, "bpm_confidence": None,
        "bpm_note": None, "bpm_found": False,
        "notes": None, "chords": None,
        "sources_ok": [], "sources_failed": [], "track_name_hint": None,
    }
    if not query:
        result["sources_failed"].append("päring oli tühi")
        return result

    cached = _META_CACHE.get(query.lower())
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return dict(cached[1])

    budget = budget_seconds or LOOKUP_BUDGET_SECONDS
    deadline = time.time() + budget
    findings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_KEY_TEMPO_SOURCES)) as pool:
        futures = {pool.submit(fn, query): fn for fn in _KEY_TEMPO_SOURCES}
        for fut in concurrent.futures.as_completed(futures, timeout=max(0.5, budget)):
            try:
                findings.append(fut.result())
            except Exception as e:
                findings.append({"source": futures[fut].__name__, "error": str(e)})
            if time.time() > deadline:
                break
        for fut, fn in futures.items():
            if not fut.done():
                fut.cancel()
                result["sources_failed"].append(f"{fn.__name__}: ajalimiit ületatud")

    rank = {"kinnitatud": 2, "hinnanguline": 1}
    for f in findings:
        src = f.get("source", "tundmatu allikas")
        if f.get("error"):
            if not f.get("skipped"):
                result["sources_failed"].append(f"{src}: {f['error']}")
            else:
                result["sources_failed"].append(f"{src}: {f['error']}")
            continue
        result["sources_ok"].append(src)
        if f.get("track_name") and not result["track_name_hint"]:
            result["track_name_hint"] = f["track_name"]
        if f.get("chords") and not result["chords"]:
            result["chords"] = f["chords"]

        if f.get("key"):
            new_rank = rank.get(f.get("key_confidence", "hinnanguline"), 1)
            cur_rank = rank.get(result["key_confidence"], 0) if result["key_found"] else 0
            if new_rank > cur_rank:
                result.update({
                    "key_latin": f["key"],
                    "key_source": src,
                    "key_confidence": f.get("key_confidence", "hinnanguline"),
                    "key_note": f.get("key_note"),
                    "key_found": True,
                })
        if f.get("bpm"):
            new_rank = rank.get(f.get("bpm_confidence", "hinnanguline"), 1)
            cur_rank = rank.get(result["bpm_confidence"], 0) if result["bpm_found"] else 0
            if new_rank > cur_rank:
                result.update({
                    "bpm": f["bpm"],
                    "bpm_source": src,
                    "bpm_confidence": f.get("bpm_confidence", "hinnanguline"),
                    "bpm_note": f.get("bpm_note"),
                    "bpm_found": True,
                })

    if result["key_found"]:
        result["key"] = key_to_estonian(result["key_latin"]) or result["key_latin"]
        result["notes"] = key_reference_notes(result["key_latin"])

    _META_CACHE[query.lower()] = (time.time(), dict(result))
    return result


def format_source_diagnostics(meta):
    """Allikate koondülevaade – LOGIDESSE, mitte mudelile.

    Varem läks see täies mahus tööriistavastusesse ("ALLIKAD ILMA
    TULEMUSETA: GetSongBPM API: vahele jäetud – ..."). Kõneseansis on see
    kasutu müra, mida mudel võib valjusti ette lugema hakata.
    """
    bits = []
    if meta.get("sources_ok"):
        bits.append("vastasid: " + "; ".join(dict.fromkeys(meta["sources_ok"])))
    if meta.get("sources_failed"):
        bits.append("tulemuseta: " + "; ".join(meta["sources_failed"][:6]))
    return " | ".join(bits)


def format_key_tempo_block(meta):
    """Vormistab helistiku ja tempo ploki – puuduv info öeldakse välja.

    Jääb alles vanema koodi ja mitte-laulja kontekstide jaoks; laulja
    esitustee kasutab format_performance_metadata(), mis annab alati
    konkreetsed numbrid.
    """
    lines = []
    if meta.get("key_found"):
        kind = "kinnitatud allikast" if meta.get("key_confidence") == "kinnitatud" else "HINNANGULINE"
        extra = f" – {meta['key_note']}" if meta.get("key_note") else ""
        lines.append(
            f"HELISTIK: {meta['key']} ({meta.get('key_latin')}) | {kind} | allikas: {meta.get('key_source')}{extra}"
        )
        if meta.get("notes"):
            lines.append(f"HELISTIKU ASTMED (Hz): {meta['notes']}")
    else:
        lines.append(
            "HELISTIK: EI LEITUD – ükski andmebaas ei andnud selle loo helistikku. "
            "ÜTLE SEE KASUTAJALE VÄLJA ja ära nimeta suvalist helistikku."
        )

    if meta.get("bpm_found"):
        kind = "kinnitatud allikast" if meta.get("bpm_confidence") == "kinnitatud" else "HINNANGULINE"
        extra = f" – {meta['bpm_note']}" if meta.get("bpm_note") else ""
        lines.append(
            f"TEMPO: {meta['bpm']:.0f} BPM | {kind} | allikas: {meta.get('bpm_source')}{extra}"
        )
    else:
        lines.append(
            "TEMPO: EI LEITUD – ükski andmebaas ei andnud selle loo BPM-i. "
            "ÜTLE SEE KASUTAJALE VÄLJA ja ära nimeta suvalist tempot."
        )

    if meta.get("chords"):
        lines.append(f"AKORDID ALLIKAST: {', '.join(meta['chords'])}")
    if meta.get("sources_ok"):
        lines.append(f"ALLIKAD, MIS VASTASID: {'; '.join(dict.fromkeys(meta['sources_ok']))}")
    if meta.get("sources_failed"):
        lines.append(f"ALLIKAD ILMA TULEMUSETA: {'; '.join(meta['sources_failed'][:6])}")
    return "\n".join(lines)


# --- Laulusõnade ja metaandmete koondamine ------------------------------

def get_or_create_song(track_query, with_metadata=True):
    """Otsib loo sõnad (LRCLIB) ning helistiku ja tempo (vt get_song_key_and_tempo).

    Tagastatud sõnastik sisaldab rida-realt kuju (`lyric_lines`,
    `lyrics_numbered`, `line_count`) ning helistiku/tempo metaandmed.
    Helistikku ja BPM-i EI mõelda välja: kui neid ei leita, on `key`/`bpm`
    None ning `key_found`/`bpm_found` False.
    """
    meta = get_song_key_and_tempo(track_query) if with_metadata else {}
    base = {
        "track_name": meta.get("track_name_hint") or track_query,
        "key": meta.get("key"),
        "key_latin": meta.get("key_latin"),
        "key_source": meta.get("key_source"),
        "key_confidence": meta.get("key_confidence"),
        "key_note": meta.get("key_note"),
        "key_found": bool(meta.get("key_found")),
        "bpm": meta.get("bpm"),
        "bpm_source": meta.get("bpm_source"),
        "bpm_confidence": meta.get("bpm_confidence"),
        "bpm_note": meta.get("bpm_note"),
        "bpm_found": bool(meta.get("bpm_found")),
        "notes": meta.get("notes"),
        "chords": meta.get("chords"),
        "key_tempo_block": format_key_tempo_block(meta) if meta else "",
        "sources_ok": meta.get("sources_ok", []),
        "sources_failed": meta.get("sources_failed", []),
    }

    try:
        url = "https://lrclib.net/api/search?q=" + urllib.parse.quote(track_query)
        data = _http_json(url)
        if data and isinstance(data, list) and len(data) > 0:
            first_match = data[0]
            lyrics = first_match.get("plainLyrics") or first_match.get("syncedLyrics") or ""
            track_name = first_match.get("trackName", track_query)
            artist = first_match.get("artistName", "Tundmatu esitaja")
            if lyrics:
                # PUHAS kuju mudelile, nummerdatud kuju AINULT logidesse
                clean, lyric_lines = format_lyrics_for_performance(lyrics)
                numbered, _ = format_lyrics_strict(lyrics)
                base.update({
                    "track_name": f"{artist} - {track_name}",
                    "lyrics": "\n".join(lyric_lines),
                    "lyrics_performance": clean,
                    "lyric_lines": lyric_lines,
                    "lyrics_numbered": numbered,   # diagnostika, mitte mudelile
                    "line_count": len(lyric_lines),
                    "found": True,
                })
                base["performance"] = resolve_performance_metadata(meta, track_query, base["lyrics"])
                return base
    except Exception as e:
        print(f"LRCLIB päringu viga: {e}")

    base.update({
        "lyrics": f"Kahjuks ei leitud loo '{track_query}' ametlikke sõnu andmebaasist.",
        "lyrics_performance": "",
        "lyric_lines": [],
        "lyrics_numbered": "",
        "line_count": 0,
        "found": False,
    })
    base["performance"] = resolve_performance_metadata(meta, track_query, "")
    return base

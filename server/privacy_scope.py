# -*- coding: utf-8 -*-
"""FAKTITASANDI privaatsus: milline fakt jääb meie vahele?

ÜLESANNE
--------
Omanik ütleb: „See konkreetne asi jääb meie vahele." AINULT see asi tohib
saada piiratud ulatuse. Sama kõne muud faktid jäävad ÜHISEKS.

Varasem prototüüp (`analyys_20261109/privacy_command.py`) tagastas ÜHE lipu
kogu seansi kohta ja oleks privatiseerinud ka pähkliallergia ja uue auto.
See on vaikne üleprivatiseerimine: kasutaja ei näe, et info ühisest mälust
kadus. Siinne moodul tagastab otsuse IGA fakti kohta eraldi, koos põhjusega.

MIKS VOORUNUMBRID JA MITTE AJATEMPLID
-------------------------------------
Faktid eraldatakse kõne LÕPUS, ühe hooga (memory_engine.consolidate_
session_to_memory). `working_mem.turns` on sel hetkel veel mälus alles ja
otsus sünnib ENNE kui ükski rida andmebaasi jõuab. Seetõttu piisab vooru
järjekorranumbrist ja andmebaasi ei ole vaja fakti-vooru sidet lisada.

Sellest järeldub kaks asja TASUTA:
  * vanu, juba salvestatud fakte ei privatiseerita kunagi tagantjärele –
    see tee ei puuduta olemasolevaid ridu üldse;
  * korraldus ei jää faktile külge ega mõjuta tulevasi kõnesid – otsus
    arvutatakse ühe kõne kohta.

KOLM SIHTMÄRGIREŽIIMI
---------------------
  explicit     korraldus NIMETAB sisu: „ära räägi teistele sellest, ET ma
               käin psühholoogi juures" -> sihtmärk sisu kattuvuse järgi
  anaphoric    korraldus viitab asesõnaga („see", „seda") -> sihtmärk on
               VAHETULT EELNEVA kasutajavooru fakt
  session_wide korraldus on sõnaselgelt lai („kogu see tänane jutt") ->
               kõik selle kõne faktid. AINUS viis terve kõne privatiseerida.

MITMETIMÕISTETAVUS KALLUTAB JAGAMISE POOLE
------------------------------------------
0 või >1 kandidaati -> KÕIK jääb ühiseks ja otsus märgitakse
`needs_clarification`. Täpsustavat küsimust Maya kõnes ei esita, sest
otsus sünnib kõne lõpus, kui kasutaja on juba läinud – küsimus läheb
logisse. Omaniku nõue lubas mõlemat haru; see on vaikimisi-jagamise haru.

MUDELI VÄIDE EI LOE
-------------------
`model_claim` võetakse vastu ainult vihjena. Otsustav on kasutaja enda
transkriptsioon serveri poolel.
"""

import json
import re
import unicodedata

try:
    from memory_fts import stem_et, STOPWORDS_ET
except Exception:                                    # pragma: no cover
    STOPWORDS_ET = {"ja", "on", "ei", "see", "seda", "ta", "ma", "sa"}

    def stem_et(w):
        return w[:5]


# --- PIIRID -----------------------------------------------------------
# Asesõnaline viide ulatub TÄPSELT ühe kasutajavooru tagasi. Mitte kaks:
# kui lubada kaks, muutub omaniku enda põhinäide mitmetimõistetavaks
# („pähkliallergia" ja „psühholoog" satuksid mõlemad aknasse) ja korraldus
# jääks rakendamata. Üks voor = „see konkreetne asi, mida ma just ütlesin".
ANAFOORI_AKEN_VOORU = 1
KATTUVUSE_LAVEND = 0.34     # explicit-režiimi minimaalne sisukattuvus
KATTUVUSE_VAHE = 0.12       # parim peab teisest nii palju parem olema


# --- MUSTRID ----------------------------------------------------------
KORRALDUSE_MUSTRID = [
    (r"\bära\s+(?:seda\s+|sellest\s+)?jaga\b", "ara_jaga"),
    # Eesti keeles on MÕLEMAD sõnajärjed tavalised: „ära TEISTELE räägi"
    # ja „ära räägi TEISTELE". Ainult esimese katmine jättis omaniku enda
    # näitelause täiesti tuvastamata.
    (r"\bära\s+(?:seda\s+|sellest\s+)?(?:teistele|teiste\w*|kellelegi)\s+"
     r"(?:räägi|ütle|jaga|maini)\b", "ara_teistele"),
    (r"\bära\s+(?:räägi|ütle|jaga|maini)\s+"
     r"(?:seda\s+|sellest\s+|sellele\s+)?"
     r"(?:teistele|teiste\w*|kellelegi)\b", "ara_teistele_verb_ees"),
    # Vahesõnad lubatud: „jääb KA meie vahele", „jääb AINULT meie vahele".
    # Ilma selleta langes ankur VANEMALE korraldusele ja privatiseeriti
    # vale fakt.
    (r"\bjääb\s+(?:\w+\s+){0,2}?(?:meie|sinu\s+ja\s+minu)\s+vahele\b",
     "meie_vahele"),
    (r"\bära\s+(?:seda\s+)?salvesta\s+(?:ühis\w*|üldis\w*)\b",
     "ara_salvesta_yhisesse"),
    (r"\bainult\s+sina\s+tead\b", "ainult_sina"),
    (r"\bteised\s+(?:karakterid\s+|tegelased\s+)?ei\s+pea\s+(?:seda\s+)?"
     r"teadma\b", "teised_ei_pea"),
    (r"\bhoia\s+(?:see|seda)\s+(?:endale|meie\s+vahel)\b", "hoia_endale"),
    # Tingiva kõneviisi vormid (jagaks, räägiks) on SIHILIKULT sees: muster
    # peab need tabama, et TINGIVAD-kontroll saaks nad korrektse põhjusega
    # tagasi lükata. Muidu saab kasutaja eksitava „korraldust ei leitud".
    (r"\b(?:et\s+sa\s+)?(?:seda\s+|sellest\s+)?ei\s+"
     r"(?:jaga|jagaks|räägi|räägiks|ütle|ütleks|maini|mainiks)\b",
     "ei_jaga_vorm"),
]

LAIA_ULATUSE_MUSTRID = [
    r"\bkogu\s+(?:see\s+)?(?:tänane\s+|meie\s+)?(?:jutt|vestlus|kõne)\b",
    r"\b(?:see|kogu)\s+vestlus\b",
    r"\bmitte\s+midagi\s+(?:sellest\s+)?(?:jutust|vestlusest)\b",
    r"\bkõik\s+mida\s+ma\s+(?:täna\s+|praegu\s+|sulle\s+)*"
    r"(?:rääkisin|ütlesin)\b",
    r"\bkõik\s+see\s+jutt\b",
]

ANAFOORI_MUSTRID = [
    r"\bsee\s+konkreetne\s+asi\b", r"\bselle\s+konkreetse\s+asja\b",
    r"\bsee\s+asi\b", r"\bselle\s+asja\b",
    r"\b(?:see|seda|sellest|selle)\b",
]

TUHISTAVAD = [
    r"\bei\s+ole\s+vaja\s+(?:seda\s+)?varjata\b",
    r"\bvõid\s+(?:seda\s+)?(?:teistele\s+)?(?:jagada|rääkida)\b",
    r"\bkõik\s+võivad\s+teada\b",
    r"\bpole\s+saladus\b",
]
TSITAADID = [
    r"[\"„»][^\"”«]{0,80}[\"”«]",
    r"\bma\s+(?:ütlesin|käskisin|palusin)\b",
    r"\bsa\s+(?:ütlesid|pakkusid|soovitasid|küsisid|arvasid)\b",
    r"\bnagu\s+ma\s+(?:ütlesin|rääkisin|palusin)\b",
]
TINGIVAD = [
    r"\b\w+ksi(?:n|d|me|te)?\b",
    r"\bkui\s+ma\s+(?:ütleksin|paluksin)\b",
    r"\boletame\b", r"\bnäiteks\s+kui\b", r"\bkujuta\s+ette\b",
]
KUSIMUSED = [r"\?\s*$", r"^\s*(?:kas|kuidas|miks|millal|mida|kes)\b"]

# Sisu loetakse AINULT sidesõnast „et" või komajärgsest osalausest.
# Varem oli siin ka muster „jaga <sisu>", mis luges lauses „Ära seda jaga
# teiste karakteritega" sisuks sõnad „teiste karakteritega" – see on
# KUULAJASKOND, mitte sisu, ja korraldus jäi rakendamata.
SISU_MUSTRID = [
    r"\bet\s+(?P<sisu>.{6,120})$",
    r"\b(?:selle|sellest|seda)\s*,\s*(?P<sisu>.{6,120})$",
]


def _norm(t):
    return unicodedata.normalize("NFC", (t or "")).strip()


def _sobib(mustrid, text):
    low = _norm(text).lower()
    for mu in mustrid:
        pat = mu[0] if isinstance(mu, tuple) else mu
        if re.search(pat, low, re.UNICODE):
            return (mu[1] if isinstance(mu, tuple) else pat)
    return ""


def _tyved(text):
    sonad = re.findall(r"\w+", _norm(text).lower(), re.UNICODE)
    return {stem_et(s) for s in sonad
            if len(s) > 2 and s not in STOPWORDS_ET}


def _kattuvus(a, b):
    """Jaccard sisusõnade TÜVEDE vahel.

    Eesliite-sobitust siin sihilikult EI kasutata: mõõdetud lõks andis
    kass/kassett jaoks 1.000.
    """
    ta, tb = _tyved(a), _tyved(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _sisu_osa(tekst):
    """Lõikab välja korralduses NIMETATUD sisu, kui see on olemas.

    Lauses „Palun, et sa seda teistele ei räägi." ON „et"-osalause
    korraldus ise, mitte selle sihtmärk – seda kontrollitakse.
    """
    low = _norm(tekst).lower()
    for pat in SISU_MUSTRID:
        m = re.search(pat, low, re.UNICODE)
        if not m:
            continue
        sisu = m.group("sisu").strip(" ,.!")
        if not _tyved(sisu):
            continue
        if _sobib(KORRALDUSE_MUSTRID, sisu):
            continue                 # osalause on korraldus, mitte sisu
        return sisu
    return ""


# --- VOORUDE INDEKS ---------------------------------------------------
def index_turns(turns):
    """Nummerdab voorud 1-st. Sama numbrit kasutab ka eraldusprompt.

    Tagastab [{"n": 1, "role": "user", "text": "..."}, ...]
    """
    out = []
    for i, t in enumerate(turns or []):
        out.append({"n": i + 1,
                    "role": (t.get("role") or "").strip().lower(),
                    "text": _norm(t.get("text", ""))})
    return out


def numbered_transcript(indexed, user_name="Kasutaja"):
    """Nummerdatud transkriptsioon mudelile. Numbrid on needsamad, mida
    mudel peab fakti juures väljale "turn" tagastama."""
    read = []
    for t in indexed:
        nimi = user_name if t["role"] == "user" else "Maya"
        read.append("%d. %s: %s" % (t["n"], nimi, t["text"]))
    return "\n".join(read)


# --- KAITSE 1: VOORUNUMBRI VALIDEERIMINE ------------------------------
def validate_fact_turn(turn_value, indexed, anchor_n=None):
    """Kas mudeli antud voorunumber on usaldusväärne?

    Omaniku nõue: number peab viitama OLEMASOLEVALE KASUTAJA voorule –
    mitte Maya vastusele, mitte privaatsuskorraldusele endale, mitte
    olematule ega väljamõeldud indeksile.

    Tagastab (ok: bool, n_või_None, pohjus: str).
    """
    if turn_value is None or turn_value == "":
        return (False, None, "turn_missing")
    try:
        n = int(str(turn_value).strip())
    except (TypeError, ValueError):
        return (False, None, "turn_not_an_integer")
    if n < 1 or n > len(indexed):
        return (False, None, "turn_out_of_range")
    voor = indexed[n - 1]
    if voor["role"] != "user":
        return (False, n, "turn_is_not_user")
    if not voor["text"]:
        return (False, n, "turn_is_empty")
    if anchor_n is not None and n == anchor_n:
        # Korraldus ise ei ole fakti allikas. Kui mudel nii väidab, on ta
        # tõenäoliselt eraldanud fakti korralduse sõnadest.
        return (False, n, "turn_is_the_instruction")
    return (True, n, "")


# --- 1. ANKUR ---------------------------------------------------------
def leia_ankur(indexed, used_turn_ns=()):
    """Leiab kasutaja privaatsuskorralduse. Otsib TAGANT ETTE."""
    markmed = []
    kasutaja = [t for t in indexed if t["role"] == "user" and t["text"]]
    if not kasutaja:
        return {"found": False, "reject_reason": "no_user_transcript",
                "turn_n": None, "utterance": "", "pattern": "", "mode": "",
                "notes": ["kasutaja voorud puuduvad"]}

    for t in reversed(kasutaja):
        n, tekst = t["n"], t["text"]
        if n in used_turn_ns:
            markmed.append("voor %d: korraldus juba kasutatud" % n)
            continue
        muster = _sobib(KORRALDUSE_MUSTRID, tekst)
        if not muster:
            continue

        for mustrid, pohjus in ((TUHISTAVAD, "privacy_revoked"),
                                (TSITAADID, "quoted_not_instruction"),
                                (TINGIVAD, "conditional_not_instruction"),
                                (KUSIMUSED, "question_not_instruction")):
            if _sobib(mustrid, tekst):
                return {"found": False, "reject_reason": pohjus,
                        "turn_n": n, "utterance": tekst, "pattern": muster,
                        "mode": "", "notes": markmed + ["tabas: " + pohjus]}

        # Režiim. Järjekord loeb: lai, siis nimetatud sisu, siis asesõna.
        if _sobib(LAIA_ULATUSE_MUSTRID, tekst):
            mode = "session_wide"
        elif _sisu_osa(tekst):
            mode = "explicit"
        elif _sobib(ANAFOORI_MUSTRID, tekst):
            mode = "anaphoric"
        else:
            mode = "unscoped"

        return {"found": True, "reject_reason": "", "turn_n": n,
                "utterance": tekst, "pattern": muster, "mode": mode,
                "notes": markmed + ["muster: %s, režiim: %s" % (muster, mode)]}

    return {"found": False, "reject_reason": "no_privacy_request",
            "turn_n": None, "utterance": "", "pattern": "", "mode": "",
            "notes": markmed or ["korraldust ei leitud"]}


# --- 2. SIHTMÄRGID ----------------------------------------------------
def leia_sihtmargid(ankur, facts, indexed):
    """Tagastab (sihtmargid, kandidaadid, pohjus).

    kandidaadid: [(fact_id, skoor, selgitus)] – auditi ja logi jaoks.
    """
    kasutaja_nrd = [t["n"] for t in indexed if t["role"] == "user"]
    try:
        ankru_koht = kasutaja_nrd.index(ankur["turn_n"])
    except ValueError:
        ankru_koht = len(kasutaja_nrd)

    kandidaadid = []
    for f in facts:
        fid = f.get("id")
        ok, n, miks = validate_fact_turn(f.get("turn"), indexed,
                                         anchor_n=ankur["turn_n"])
        if not ok:
            kandidaadid.append((fid, 0.0, "invalid_turn:" + miks))
            continue
        if n > ankur["turn_n"]:
            kandidaadid.append((fid, 0.0, "after_instruction"))
            continue

        if ankur["mode"] == "session_wide":
            kandidaadid.append((fid, 1.0, "session_wide"))
        elif ankur["mode"] == "explicit":
            sk = _kattuvus(_sisu_osa(ankur["utterance"]), f.get("fact", ""))
            kandidaadid.append((fid, round(sk, 3), "content_overlap"))
        elif ankur["mode"] == "anaphoric":
            vahe = ankru_koht - kasutaja_nrd.index(n)
            if 1 <= vahe <= ANAFOORI_AKEN_VOORU:
                kandidaadid.append((fid, 1.0, "previous_user_turn"))
            else:
                kandidaadid.append((fid, 0.0,
                                    "outside_window_%d_turns" % vahe))
        else:
            kandidaadid.append((fid, 0.0, "unscoped_reference"))

    if ankur["mode"] == "session_wide":
        sihid = {c[0] for c in kandidaadid if c[2] == "session_wide"}
        return (sihid, kandidaadid,
                "session_wide_explicit" if sihid else "no_eligible_facts")

    if ankur["mode"] == "explicit":
        head = sorted([c for c in kandidaadid
                       if c[2] == "content_overlap"
                       and c[1] >= KATTUVUSE_LAVEND],
                      key=lambda c: -c[1])
        if not head:
            return (set(), kandidaadid, "no_match_above_threshold")
        if len(head) > 1 and (head[0][1] - head[1][1]) < KATTUVUSE_VAHE:
            return (set(), kandidaadid, "ambiguous_tie")
        return ({head[0][0]}, kandidaadid, "explicit_content_match")

    if ankur["mode"] == "anaphoric":
        aknas = [c for c in kandidaadid if c[2] == "previous_user_turn"]
        if not aknas:
            return (set(), kandidaadid, "no_fact_in_window")
        if len(aknas) > 1:
            # Mitu fakti samast voorust -> EI OLETA, pigem jagame.
            return (set(), kandidaadid, "ambiguous_multiple_in_window")
        return ({aknas[0][0]}, kandidaadid, "anaphoric_single_in_window")

    return (set(), kandidaadid, "unscoped_reference")


# --- 3. OTSUS IGA FAKTI KOHTA -----------------------------------------
KAHTLASED = ("ambiguous_tie", "ambiguous_multiple_in_window",
             "no_match_above_threshold", "no_fact_in_window",
             "unscoped_reference", "no_eligible_facts")


def resolve_fact_scopes(turns, facts, persona, used_turn_ns=(),
                        model_claim=None, user_name="Kasutaja"):
    """PEAFUNKTSIOON. Otsus iga fakti kohta eraldi.

    turns : working_mem.turns kujul [{"role","text",...}]
    facts : [{"id","fact","turn"}] – "turn" tuleb mudelilt ja VALIDEERITAKSE
    Tagastab {"decisions","needs_clarification","clarify_question","audit"}.
    """
    indexed = index_turns(turns)
    facts = list(facts or [])
    ankur = leia_ankur(indexed, used_turn_ns)

    audit = {
        "anchor_found": ankur["found"],
        "anchor_turn": ankur["turn_n"],
        "user_utterance": ankur["utterance"],      # SÕNA-SÕNALT
        "matched_pattern": ankur["pattern"],
        "target_mode": ankur["mode"],
        "reject_reason": ankur["reject_reason"],
        "model_claim": (model_claim or {}).get("private"),
        "model_claim_honoured": False,             # mitte kunagi
        "candidates": [], "targets": [], "left_shared": [],
        "resolution": "",
        "notes": list(ankur["notes"]),
    }

    if not ankur["found"]:
        if (model_claim or {}).get("private"):
            audit["notes"].append(
                "MUDEL VÄITIS privaatsust, transkriptsioon ei kinnita "
                "-> väide eiratud")
        otsused = [{"fact_id": f.get("id"), "scope": "shared",
                    "persona": None, "reason": "no_verified_instruction",
                    "scope_reason": None} for f in facts]
        audit["left_shared"] = [o["fact_id"] for o in otsused]
        return {"decisions": otsused, "needs_clarification": False,
                "clarify_question": "", "audit": audit}

    sihid, kandidaadid, pohjus = leia_sihtmargid(ankur, facts, indexed)
    audit["candidates"] = kandidaadid
    audit["resolution"] = pohjus
    audit["targets"] = sorted([s for s in sihid if s is not None])

    kahtlane = pohjus in KAHTLASED
    p = (persona or "").strip().lower()

    otsused = []
    for f in facts:
        fid = f.get("id")
        if fid in sihid and not kahtlane:
            scope = "persona" if p else "private"
            otsused.append({
                "fact_id": fid, "scope": scope,
                "persona": (p or None), "reason": pohjus,
                "scope_reason": json.dumps({
                    "anchor_turn": ankur["turn_n"],
                    "utterance": ankur["utterance"][:200],
                    "pattern": ankur["pattern"],
                    "mode": ankur["mode"],
                    "resolution": pohjus,
                }, ensure_ascii=False),
            })
        else:
            otsused.append({
                "fact_id": fid, "scope": "shared", "persona": None,
                "reason": ("not_targeted" if not kahtlane else pohjus),
                "scope_reason": None,
            })
    audit["left_shared"] = [o["fact_id"] for o in otsused
                            if o["scope"] == "shared"]

    kysimus = _kysimus(pohjus, facts, kandidaadid) if kahtlane else ""
    if kahtlane:
        audit["notes"].append(
            "MITMETIMÕISTETAV (%s) -> kõik jäid ühiseks" % pohjus)

    return {"decisions": otsused, "needs_clarification": bool(kahtlane),
            "clarify_question": kysimus, "audit": audit}


def _kysimus(pohjus, facts, kandidaadid):
    """Eestikeelne täpsustav küsimus. Läheb LOGISSE, mitte kõnesse –
    otsus sünnib kõne lõpus, kui kasutaja on juba läinud."""
    if pohjus in ("no_fact_in_window", "no_eligible_facts"):
        return ("Sain aru, et midagi peab meie vahele jääma, aga ma ei saa "
                "pihta, mis täpselt. Ütle palun, mis asi see on?")
    if pohjus == "no_match_above_threshold":
        return ("Ma ei leidnud, mille kohta sa seda ütlesid. Korda palun, "
                "mis asi meie vahele jääma peab?")
    skoor = {c[0]: c[1] for c in kandidaadid}
    nimed = [f.get("fact", "") for f in facts if skoor.get(f.get("id"), 0) > 0]
    if len(nimed) >= 2:
        return ("Jätan meelde, et see jääb meie vahele – aga kumba sa "
                "mõtlesid: „%s\" või „%s\"?" % (nimed[0][:60], nimed[1][:60]))
    return ("Jätan meelde, et see jääb meie vahele – ütle palun täpsemalt, "
            "mille kohta see käis?")

# -*- coding: utf-8 -*-
"""VESTLUSE ELUTSÜKKEL: taaste ja omaalgatus.

MIKS SEE MOODUL OLEMAS ON
-------------------------
MÕÕDETUD TOOTMISES (10.11.2026, kaks filosoofi testi, 21 vooru):

  1) Katkemise määr on 9/21 = 42,9%. Gemini lõpetab vooru keset lauset
     ja teeb seda ka JÄTKAMISE vastuses – jätkamise vastus on ise
     tavalise pikkusega voor ja katkeb sama määraga.

  2) Vana piirang `AINULT_JATKAMISI = 1` tähendas, et pärast ÜHT
     ebaõnnestunud jätkamist taaste lõppes. Mõõdetud tagajärg
     17:33:04 -> 17:33:40: Maya jäi keset lauset vait ja 36 sekundit ei
     juhtunud MITTE MIDAGI, kuni kasutaja ise toru ära pani.

     Jääkrisk eelarve järgi (p = 0,429):
         eelarve 1 -> 42,9%    eelarve 3 -> 7,9%
         eelarve 2 -> 18,4%    eelarve 4 -> 3,4%
     Eelarve 3 on esimene, mis viib jääkriski alla 10%. See on ainus
     põhjus, miks vaikeväärtus on 3 – mitte maitse.

  3) Pärast LOOMULIKKU lõppu ei käivitu MITTE MIDAGI. Kontrollitud
     `live_maya_ws.py` koodist: ainsad väljuvad teed Gemini poole on
     kasutaja heli, kasutaja tekst, tööriista vastus, avakäsk ja
     jätkamispalve. Jätkamispalve käivitub AINULT lausemärgi puudumisel.
     Seega klassi A järel on süsteem struktuurselt tumm – ükski
     komponent ei OMA otsust "alusta ise".

MIDA SEE MOODUL EI TEE
----------------------
Ta on PUHAS: ei puutu WebSocketit, Geminit, andmebaasi ega aega
(kellaaeg antakse argumendina). Kogu otsustusloogika on siin, et seda
saaks testida ilma Geminit jäljendamata. `live_maya_ws.py` ainult
küsib otsuseid ja täidab neid.

KAKS ERINEVAT ASJA, MIDA EI TOHI SEGADA
---------------------------------------
  TAASTE (recovery)    – lause jäi POOLELI. Eesmärk: lõpeta see lause.
                         Käivitub KOHE, ilma pausi.
  OMAALGATUS (initiative) – lause sai LÕPETATUD, aga vestlus võib edasi
                         minna. Käivitub alles pärast pausi ja ainult
                         siis, kui karakterile on see omane.
"""

import re
import unicodedata

# --- VESTLUSE OLEKUD ---------------------------------------------------
# Omaniku nõue: neid viit ei tohi kokku suruda üheks "turn complete"
# olekuks.
GENERATING = "generating"        # Maya toodab praegu
INCOMPLETE = "incomplete"        # voor lõppes poolikult -> TAASTE
COMPLETE_IDLE = "complete_idle"  # lõpetatud, võib ise edasi minna
AWAITING_USER = "awaiting_user"  # lõpetatud küsimusega -> ootame kasutajat
USER_SPEAKING = "user_speaking"  # kasutajal on sõna
ENDED = "ended"                  # vestlus on läbi

STATES = (GENERATING, INCOMPLETE, COMPLETE_IDLE, AWAITING_USER,
          USER_SPEAKING, ENDED)

# Lausemärgid – sama hulk mis live_maya_ws.TERMINAL_PUNCT.
TERMINAL_PUNCT = ".!?…:;”)"


# =====================================================================
# TAASTEPOLIITIKA
# =====================================================================
# Mitu taastekatset tohib ÜHE kasutajavooru ahelas kokku olla.
#
# OMANIKU OTSUS 11.11.2026: "tee kõik nii et mingit piirangut ei ole ja
# kui siis kohe jutt taastub viimasest pooleli jäänust". Tõstetud 3 -> 12.
#
# MIKS 12 JA MITTE PIIRAMATU: iga katse NÕUAB uut Gemini turn_complete
# sündmust, seega tegu ei ole tsükliga, mida saaks ise kiirendada – 12
# katset tähendab 12 päris katkemist järjest ÜHE kasutajavooru sees.
# Mõõdetud maksimum on 3 (01:55:39-01:55:58) ja pärast karakteriviiba
# parandust 1 (kuus katkemist, kuus korda `TAASTE 1/3`). 12 on seega
# praktikas piiranguta, aga jääb ülemiseks kaitseks juhul, kui mudel
# satub lõputusse poolikute voorude seeriasse.
#
# AHEL NULLISTUB TÄIELIKULT kasutaja iga uue kõnevooru peale
# (`on_user_speech` -> `reset_chain`), seega see arv ei kuhju kõne
# jooksul kokku.
RECOVERY_BUDGET = 12

# Katsete vaheline ooteaeg sekundites.
#
# OMANIKU OTSUS 11.11.2026: "võimalikult kiiresti". KÕIK katsed on nüüd
# 0,0 s – ükski taaste ei oota enam sekundeid.
#
# MIKS SEE ON OHUTU: varasem 0,6 / 1,2 s tagasiastumine oli mõeldud
# Gemini pommitamise vastu, aga taaste EI OLE taimeripõhine – iga katse
# vallandub ainult PÄRIS `turn_complete` sündmusest, mille Gemini ise
# saatis. Üks katkemine = üks päring. Tühikäigutsüklit tekkida ei saa.
# Korduse kaitse (`near_duplicate`) ja eelarve jäävad ülemiseks piiriks.
#
# MÕÕDETUD TULEMUS: palve saatmine võtab 1-3 ms. Kuuldava pausi määrab
# pärast seda AINULT Gemini esimese helitüki latents, mis on mõõdetud
# 0,28-0,42 s (AJAJOON read 11.11 03:15-03:21). Serveripoolne viivitus
# on nüüd nullilähedane; sajandikku sekundit ei ole võimalik saavutada,
# sest mudel peab heli alles genereerima.
RECOVERY_BACKOFF_S = (0.0,)

# Kui uue segmendi algus kattub eelmise sabaga nii palju, on tegemist
# KORDUSEGA ja ahel peatatakse. 0,8 on karm: nõuab peaaegu identset
# teksti, nii et tavaline grammatiline jätk ei satu lõksu.
DUPLICATE_RATIO = 0.8
# Mitu viimast sõna kõrvutatakse.
DUPLICATE_WINDOW_WORDS = 8


def _normaliseeri(t):
    t = unicodedata.normalize("NFC", (t or "")).lower()
    return re.findall(r"\w+", t, re.UNICODE)


def near_duplicate(eelmine_saba: str, uus_algus: str,
                   ratio: float = DUPLICATE_RATIO,
                   window: int = DUPLICATE_WINDOW_WORDS) -> bool:
    """Kas uus segment KORDAB eelmise lõppu?

    Tsüklikaitse: kui mudel hakkab sama asja uuesti ütlema, ei tohi
    taaste jätkuda. Võrdleme viimaseid `window` sõnu.

    MIKS SÕNADE, MITTE TÄHEMÄRKIDE KAUPA: mõõdetud õnnestunud jätkamised
    olid grammatilised jätkud ("...vaid kosmilise" + "printsiibina"),
    kus tähemärgitasandil on kattuvus suur, aga sõnatasandil null.
    """
    a = _normaliseeri(eelmine_saba)[-window:]
    b = _normaliseeri(uus_algus)[:window]
    if not a or not b:
        return False
    # LÜHIKESED SABAD: hulgapõhine suhe plahvatab, kui võrrelda on
    # vähem kui 4 sõna – kahest ühissõnast ("ja siis") piisaks juba
    # suhteks 1,0 ja taasteahel katkeks esimese katse järel. Mõõdetud
    # katkemiste määr on 42,9%, seega vale-kordus on kallim viga kui
    # vahelejäänud kordus: eelarve (3) jääb igal juhul kõvaks piiriks.
    if min(len(a), len(b)) < 4:
        return False
    # HULGAPÕHINE KATTUVUS, mitte positsiooniline.
    #
    # MÕÕDETUD VIGA esimeses versioonis: positsiooniline võrdlus
    # (a[i] == b[i]) ei tabanud korduse juhtumit üldse, sest nihe ühe
    # sõna võrra viib kõik positsioonid paigast. Hulgapõhine kattuvus
    # tabab korduse ka nihkega ja jätab grammatilise jätku rahule –
    # mõõdetud kolm õnnestunud jätku ("...vaid kosmilise" +
    # "printsiibina...") ei jaga ÜHTEGI sõna.
    ühised = len(set(a) & set(b))
    return (ühised / float(min(len(a), len(b)))) >= ratio


class RecoveryPolicy:
    """Poolelijäänud lause taaste, piiratud ja olekuga.

    ASENDAB vana `jatkamised = {"n", "kokku", "ootel"}` sõnastikku.
    Kolm vana kaitset jäävad alles (vahelesegamine, ahela piir, ootel),
    aga JÄRJESTIKUSE KATSE piirang 1 on kaotatud – mõõdetud, et see
    põhjustas 36 s vaikuse.
    """

    def __init__(self, budget: int = RECOVERY_BUDGET,
                 backoff=RECOVERY_BACKOFF_S):
        self.budget = int(budget)
        self.backoff = tuple(backoff)
        self.reset_chain()

    # --- ahela elutsükkel -------------------------------------------
    def reset_chain(self, now: float = 0.0):
        """Uus kasutajavoor = uus ahel."""
        self.used = 0            # kasutatud katseid selles ahelas
        self.pending = False     # ootame taaste vastust
        self.last_dispatch = 0.0
        self.last_tail = ""      # eelmise segmendi saba (korduse jaoks)
        self.stopped_reason = ""  # miks ahel lõplikult peatus

    def invalidate_pending(self, reason: str) -> bool:
        """Katkestus / vooruta turn_complete muudab ootel vastuse
        kehtetuks. Loendurit EI nullita – see ei ole õnnestumine."""
        if not self.pending:
            return False
        self.pending = False
        return True

    # --- otsus ------------------------------------------------------
    def should_recover(self, *, tail_is_terminal: bool, tail_len: int,
                       audio_s: float, saw_turn_complete: bool,
                       user_interrupted: bool, tool_running: bool,
                       tail_text: str = "", now: float = 0.0) -> dict:
        """Kas saata taastepalve? Tagastab otsuse koos põhjusega.

        {"recover": bool, "reason": str, "wait_s": float,
         "attempt": int, "budget": int}
        """
        def ei(p):
            return {"recover": False, "reason": p, "wait_s": 0.0,
                    "attempt": self.used, "budget": self.budget}

        # 1. Kas see voor oli ootel taaste vastus? Hinda see ENNE otsust.
        if self.pending:
            self.pending = False
            if tail_is_terminal:
                # ÕNNESTUS. Ahela eelarve ei nullistu – ainult kasutaja
                # kõne avab uue ahela.
                self.last_tail = ""
                return ei("recovery_succeeded")
            if tail_text and near_duplicate(self.last_tail, tail_text):
                self.stopped_reason = "duplicate_detected"
                return ei("duplicate_detected")

        # 2. Loomulik lõpp ei vaja taastet.
        if tail_is_terminal:
            return ei("terminal_punctuation")
        if tail_len <= 0:
            return ei("empty_transcription")
        if not saw_turn_complete:
            return ei("no_turn_complete_yet")
        if audio_s <= 0.5:
            return ei("too_little_audio")

        # 3. Väravad.
        if user_interrupted:
            return ei("user_interrupted")
        if tool_running:
            return ei("tool_running")
        if self.stopped_reason:
            return ei(self.stopped_reason)
        if self.used >= self.budget:
            self.stopped_reason = "budget_exhausted"
            return ei("budget_exhausted")

        wait = self.backoff[min(self.used, len(self.backoff) - 1)]
        return {"recover": True, "reason": "incomplete_generation",
                "wait_s": wait, "attempt": self.used + 1,
                "budget": self.budget}

    def note_dispatched(self, tail_text: str = "", now: float = 0.0):
        """Kutsu PÄRAST palve saatmist."""
        self.used += 1
        self.pending = True
        self.last_dispatch = now
        if tail_text:
            self.last_tail = tail_text

    def as_dict(self):
        return {"used": self.used, "budget": self.budget,
                "pending": self.pending, "stopped": self.stopped_reason}


# =====================================================================
# OMAALGATUS
# =====================================================================
# KARAKTERIPÕHINE ALGATUSTASE.
#
# OLULINE: see on TULETATUD olemasolevatest karakterikirjeldustest, mitte
# nende muutmisest. `persona_registry.py` jääb BAIT-BAIDILT puutumata.
# Iga väärtus on põhjendatud karakteri enda prompti sõnastusega:
#
#   pause_s – kui kaua kasutaja vaikust oodata enne omaalgatust
#   budget  – mitu omaalgatust tohib ühe vaikuseperioodi kohta olla
#             (0 = see karakter ei alusta kunagi ise)
INITIATIVE = {
    # "aeg liigub vaikselt", rahulik – vaikus on talle loomulik seisund
    "zen":          {"pause_s": 12.0, "budget": 1},
    # laulmine on ülesandepõhine: ootab palvet, ei lobise vahele
    "singer":       {"pause_s": 14.0, "budget": 1},
    # "aeg tegutseda", asjalik – mõõdukas
    "asjalik":      {"pause_s": 7.0,  "budget": 2},
    # "esitad teravaid küsimusi", "paned järele mõtlema"
    "mentor":       {"pause_s": 6.0,  "budget": 2},
    "treener":      {"pause_s": 7.0,  "budget": 2},
    "sober":        {"pause_s": 7.0,  "budget": 2},
    # "räägi sügavalt, voolavalt" – arendab mõtet ise edasi
    "filosoof":     {"pause_s": 5.0,  "budget": 3},
    # "terava huumoriga", "pühad lehmad puuduvad" – torkab ise
    "sarkastiline": {"pause_s": 5.0,  "budget": 3},
    # "naudib pikemat suhtlust", "ära piirdu lakooniliste vastustega"
    "romantiline":  {"pause_s": 5.0,  "budget": 3},
    "custom":       {"pause_s": 5.0,  "budget": 3},
}
INITIATIVE_DEFAULT = {"pause_s": 8.0, "budget": 2}

# Küsimuse tunnused: kui Maya lõpetas küsimusega, siis OOTAME kasutajat,
# mitte ei räägi peale. See eristab AWAITING_USER ja COMPLETE_IDLE.
_KUSIMUSE_LOPP = re.compile(r"\?\s*[\"”»]?\s*$")


def ends_with_question(text: str) -> bool:
    """Kas Maya lõpetas küsimusega?"""
    return bool(_KUSIMUSE_LOPP.search((text or "").strip()))


def classify_completion(text: str) -> str:
    """Loomuliku lõpu alamliik: AWAITING_USER või COMPLETE_IDLE.

    Omaniku nõue: "Maya on lõpetanud, aga ootab vastust" ja "Maya on
    lõpetanud ja võib ise edasi minna" ei tohi olla sama olek.
    """
    if ends_with_question(text):
        return AWAITING_USER
    return COMPLETE_IDLE


def initiative_for(persona: str) -> dict:
    return dict(INITIATIVE.get((persona or "").strip().lower(),
                               INITIATIVE_DEFAULT))


class InitiativePolicy:
    """Omaalgatus pärast LOOMULIKKU lõppu.

    SÜNDMUSEPÕHINE, mitte küsitlev: `live_maya_ws` kutsub `should_speak()`
    oma olemasolevast taimerist. Geminit ei küsitleta kordagi –
    väljuv päring tehakse ainult siis, kui see meetod annab True.
    """

    def __init__(self, persona: str = ""):
        cfg = initiative_for(persona)
        self.pause_s = cfg["pause_s"]
        self.budget = cfg["budget"]
        self.persona = (persona or "").strip().lower()
        self.reset_silence()

    def reset_silence(self):
        """Kasutaja rääkis või Maya alustas – vaikuseperiood algab otsast."""
        self.used = 0

    def should_speak(self, *, state: str, silent_s: float,
                     user_speaking: bool, tool_running: bool,
                     recovery_pending: bool,
                     user_turn_seen: bool = False) -> dict:
        """Kas alustada omaalgatuslikku vooru?"""
        def ei(p):
            return {"speak": False, "reason": p, "used": self.used,
                    "budget": self.budget}

        # ESIMENE VÄRAV, ENNE KÕIKE MUUD (L6, omaniku nõue 11.11.2026):
        # Maya ei tohi KUNAGI alustada omaalgatuslikku kõnet enne, kui
        # vestluskaaslane on selles seansis vähemalt ühe päris
        # kõnevooru lõpetanud. Ainult aja möödumine seansi avanemisest
        # EI ANNA kõneõigust ühelegi karakterile.
        #
        # MÕÕDETUD DEFEKT: algolekus AWAITING_USER avanes värav
        # 2 x pausi järel ka täiesti tühja ajaloo peal – filosoof
        # 10,1 s, zen 24,1 s, singer 28,1 s. Karakteri pausid,
        # eelarved ja ülejäänud käitumine jäävad PÄRAST esimest
        # kasutajavooru täpselt samaks.
        if not user_turn_seen:
            return ei("no_user_turn_yet")
        if self.budget <= 0:
            return ei("persona_never_initiates")
        if state == ENDED:
            return ei("conversation_ended")
        if user_speaking:
            return ei("user_has_floor")
        if tool_running:
            return ei("tool_running")
        if recovery_pending:
            return ei("recovery_in_progress")
        # AWAITING_USER: Maya küsis midagi -> ootame vastust kauem.
        # Ei keela igaveseks, aga ei räägi kasutajale peale.
        if state == AWAITING_USER:
            if silent_s < self.pause_s * 2.0:
                return ei("awaiting_user_answer")
        elif state != COMPLETE_IDLE:
            return ei("state_not_idle")
        if silent_s < self.pause_s:
            return ei("pause_not_elapsed")
        if self.used >= self.budget:
            return ei("initiative_budget_exhausted")
        return {"speak": True, "reason": "idle_initiative",
                "used": self.used + 1, "budget": self.budget}

    def note_spoken(self):
        self.used += 1


# =====================================================================
# PALVETE TEKSTID
# =====================================================================
# TAASTEPALVE: muutmata, sama sõnastus mis tootmises juba töötab.
# Mõõdetud 3 õnnestunud jätkamist selle sõnastusega (grammatiliselt
# täpsed jätkud), seega teksti ei puutu.
RECOVERY_PROMPT = (
    "[SÜSTEEM] Sinu eelmine lause jäi pooleli. "
    "Jätka TÄPSELT sealt, kus katkesid, ja vii mõte lõpuni. "
    "Ära alusta otsast, ära vabanda ega maini seda teadet. "
    # LISATUD 11.11.2026, MÕÕDETUD PÕHJUSEGA: kõik kolm 1007-tõrget
    # sellest ajast, mil taaste olemas on, saabusid taastepalve järel
    # (3/3) ja igal korral oli mudel enne seda pikas ingliskeelses
    # mõtteplokis, kust ta heliga välja ei jõudnudki ("Continuing the
    # Narrative", "Developing the Scene"). See mudel EI TOETA
    # tekstiväljundit üldse (mõõdetud: "The requested combination of
    # response modalities (TEXT) is not supported"), seega kui ta
    # vastab taastepalvele ainult mõttega, lõpeb seanss 1007-ga.
    "Vasta KOHE ja AINULT kõnena. Ära analüüsi seda teadet, ära kaalu "
    "ega planeeri – jätka lauset otsemaid rääkides, sealt samast sõnast."
)


def initiative_prompt(silent_s: float,
                      has_prior_thought: bool = True) -> str:
    """OMAALGATUSE palve.

    KARAKTERI SÄILITAMINE: see tekst EI ÜTLE, mida öelda. Ta ei nõua
    küsimust, ei anna teemat ega tooni. Ta ütleb ainult, et vaikus
    kestab ja et karakter võib OMA moel edasi minna. Erinevused
    karakterite vahel tulevad `INITIATIVE` tabelist (kui tihti ja kui
    kiiresti), mitte sellest tekstist.

    `has_prior_thought` – kas Maya on selles vestluses juba midagi
    öelnud. AUDITIS LEITUD VIGA (L6, 11.11.2026): viip käskis
    "arenda eelmist mõtet" ka siis, kui eelmist mõtet EI OLNUD
    olemas, ja tulemus oli ettearvamatu. Teine sõnastus viitab
    ainult sellele, mida vestluskaaslane ise ütles. Kumbki sõnastus
    EI anna avalauset ega tervitust.
    """
    sek = int(round(silent_s))
    if has_prior_thought:
        return (
            "[SÜSTEEM] Vestluskaaslane on olnud vaikne umbes "
            f"{sek} sekundit. Kui sinu karakterile on "
            "loomulik vestlust ise edasi viia, siis tee seda OMA tooni ja "
            "stiilis – arenda eelmist mõtet, lisa tähelepanek või küsi "
            "midagi, mis on just sinule omane. "
            # LISATUD 11.11.2026, MÕÕDETUD PÕHJUSEGA: ainus 1007-tõrge
            # pärast taastepalve parandust saabus OMAALGATUSE järel
            # (03:51:10). Logis: omaalgatus -> [MAYA MÕTE]
            # "**Anticipating the Next Stage**" -> NULL helirida ->
            # 1007. Sama muster, mis taastel: mudel vastab tekstiga,
            # mida see mudel üldse ei toeta, ja seanss sureb.
            "Vasta KOHE ja AINULT kõnena – ära analüüsi seda teadet "
            "ega planeeri, hakka lihtsalt rääkima. "
            "Hoia see LÜHIKE, et ta "
            "saaks vahele tulla. Ära korda juba öeldut, ära maini seda "
            "teadet ega vaikust ja ära küsi, kas ta on veel seal."
        )
    return (
        "[SÜSTEEM] Vestluskaaslane on olnud vaikne umbes "
        f"{sek} sekundit. Sina ei ole veel midagi öelnud, seega EI OLE "
        "eelmist mõtet, mida arendada. Kui sinu karakterile on "
        "loomulik, siis haaku sellega, mida vestluskaaslane viimati "
        "ütles, OMA tooni ja stiilis. "
        "Vasta KOHE ja AINULT kõnena – ära analüüsi seda teadet ega "
        "planeeri, hakka lihtsalt rääkima. "
        "Hoia see LÜHIKE, et ta saaks "
        "vahele tulla. Ära tervita, ära tutvusta ennast, ära maini "
        "seda teadet ega vaikust ja ära küsi, kas ta on veel seal."
    )


# =====================================================================
# OLEKUMASIN
# =====================================================================
class ConversationFlow:
    """Koondab oleku, taaste ja omaalgatuse ühte kohta.

    `live_maya_ws` hoiab ÜHT sellist objekti seansi kohta ja kutsub
    sündmusmeetodeid. Objekt ei tee ise mitte midagi – ta ainult
    otsustab ja ütleb, mida teha.
    """

    def __init__(self, persona: str = "", budget: int = RECOVERY_BUDGET,
                 now: float = 0.0):
        self.persona = (persona or "").strip().lower()
        # ALGOLEK ON AWAITING_USER, MITTE COMPLETE_IDLE.
        #
        # MÕÕDETUD KRIITILINE DEFEKT (ülevaatus 10.11.2026): algolek oli
        # COMPLETE_IDLE ja `last_activity = 0.0`. `tick()` arvutab
        # `silent_s = now - last_activity`, mis monotoonse kella puhul
        # annab sadu tuhandeid sekundeid -> omaalgatus käivitus 0,5 s
        # pärast seansi algust, ENNE kui Maya oli üldse midagi öelnud.
        # Kasutaja oleks saanud kohe "sa oled vaikinud 586622 sekundit".
        #
        # Kõne alguses me PÄRISELT ootame kasutajat, seega AWAITING_USER
        # on ka semantiliselt õige.
        self.state = AWAITING_USER
        self.recovery = RecoveryPolicy(budget=budget)
        self.initiative = InitiativePolicy(self.persona)
        # millal Maya hääl viimati lõppes. 0.0 = EI OLE VEEL RÄÄKINUD.
        self.last_activity = float(now)
        self.ended = False
        # L6: kas vestluskaaslane on selles seansis kõnelenud? Ilma
        # selleta ei tohi omaalgatus avaneda.
        self.user_turn_seen = False
        # Kas Maya ise on juba midagi sisulist öelnud? Otsustab, KUMBA
        # omaalgatuse sõnastust kasutada (vt initiative_prompt).
        self.assistant_said_something = False

    # --- sündmused --------------------------------------------------
    def on_user_speech(self, now: float = 0.0):
        # L6 VÄRAV AVANEB. Koos olemasoleva olekuvärvaga
        # (`should_speak` nõuab COMPLETE_IDLE või AWAITING_USER)
        # tähendab see, et esimene omaalgatus saab tulla alles siis,
        # kui kasutaja voor on lõppenud JA Maya vastus on valmis.
        self.user_turn_seen = True
        self.state = USER_SPEAKING
        self.recovery.reset_chain(now)
        self.initiative.reset_silence()

    def on_generation_start(self, now: float = 0.0):
        if self.state != ENDED:
            self.state = GENERATING

    def on_interrupted(self, now: float = 0.0) -> bool:
        tyhistatud = self.recovery.invalidate_pending("interrupted")
        if self.state != ENDED:
            self.state = USER_SPEAKING
        return tyhistatud

    def on_empty_turn_complete(self, now: float = 0.0) -> bool:
        return self.recovery.invalidate_pending("empty_turn_complete")

    def on_conversation_end(self):
        self.state = ENDED
        self.ended = True

    def on_turn_complete(self, *, text: str, tail_len: int, audio_s: float,
                         tail_is_terminal: bool, user_interrupted: bool,
                         tool_running: bool, playback_end_est: float,
                         now: float = 0.0) -> dict:
        """Peasündmus. Tagastab, mida teha.

        `playback_end_est` – hinnanguline hetk, mil taasesitus lõpeb.
        Vaikuse lugemine algab SELLEST, mitte turn_complete'ist.
        """
        # VESTLUS ON LÕPPENUD: ükski sündmus ei tohi enam taastet
        # käivitada. `on_conversation_end()` kutsutakse teardownis,
        # samal ajal kui taskid on tühistatud, aga mitte veel oodatud –
        # pooleliolev voorulõpu käsitlus võiks muidu veel ühe päringu
        # saata juba surnud seanssi (leitud ülevaatusel 10.11.2026,
        # stsenaarium H).
        if self.ended or self.state == ENDED:
            self.state = ENDED
            return {"recover": False, "reason": "conversation_ended",
                    "wait_s": 0.0, "attempt": self.recovery.used,
                    "budget": self.recovery.budget}
        otsus = self.recovery.should_recover(
            tail_is_terminal=tail_is_terminal, tail_len=tail_len,
            audio_s=audio_s, saw_turn_complete=True,
            user_interrupted=user_interrupted, tool_running=tool_running,
            tail_text=text, now=now)

        self.last_activity = playback_end_est
        if (text or "").strip():
            self.assistant_said_something = True
        if otsus["recover"]:
            self.state = INCOMPLETE
        elif tail_is_terminal:
            self.state = classify_completion(text)
            # MÕÕDETUD VIGA esimeses versioonis: siin kutsuti
            # `initiative.reset_silence()`, mis nullis omaalgatuse
            # EELARVE iga Maya enda vooru lõpus. Tagajärg: eelarve ei
            # piiranud mitte midagi – test sai 10 omaalgatust eelarve 3
            # juures. Vaikuse KELL algab `last_activity` kaudu, aga
            # eelarve tohib nullistuda AINULT kasutaja kõne peale.
        else:
            # Poolik, aga taastet ei tule (eelarve, värav vms).
            self.state = COMPLETE_IDLE
        return otsus

    def on_recovery_dispatched(self, tail_text: str = "", now: float = 0.0):
        self.recovery.note_dispatched(tail_text, now)
        self.state = GENERATING

    def on_recovery_failed(self):
        """Taastepäring EI jõudnud kohale (saatmine viskas vea).

        Ilma selleta jääks olek igaveseks INCOMPLETE'iks ja omaalgatus
        oleks kuni kasutaja järgmise lauseni täielikult blokeeritud
        (`should_speak` nõuab COMPLETE_IDLE või AWAITING_USER). Vaikuse
        kell (`last_activity`) on juba seatud, seega karakteri paus
        hakkab jooksma õigest hetkest.

        Eelarvet EI tagastata: `note_dispatched` jäi kutsumata, seega
        katset ei tarbitud. Kordusekaitse jääb samuti puutumata.
        """
        if self.state == INCOMPLETE:
            self.state = COMPLETE_IDLE
        return self.state

    def reserve_initiative(self, now: float = 0.0):
        """Broneeri omaalgatus ENNE väljuvat päringut.

        MÕÕDETUD VÕIDUJOOKS (ülevaatus 10.11.2026): `tick()` ja
        väljuva päringu vahel on ootamine. Olek jäi COMPLETE_IDLE'iks ja
        `initiative.used` suurendamata kuni saatmise LÕPUNI, seega
        järgmine tiks (0,5 s hiljem) võis otsustada teist korda ja
        saata TEISE päringu. Broneerimine enne saatmist välistab selle.
        """
        self.initiative.note_spoken()
        self.state = GENERATING

    def release_initiative(self):
        """Saatmine ebaõnnestus – anna broneering tagasi."""
        if self.initiative.used > 0:
            self.initiative.used -= 1
        if self.state == GENERATING:
            self.state = COMPLETE_IDLE

    # Ühilduvusnimi vanade kutsujate jaoks.
    def on_initiative_dispatched(self, now: float = 0.0):
        self.reserve_initiative(now)

    # --- taimerilt küsitav -----------------------------------------
    def tick(self, *, now: float, user_speaking: bool,
             tool_running: bool) -> dict:
        """Kutsutakse perioodiliselt. Otsustab omaalgatuse."""
        # TEINE VÖÖ sama kriitilise defekti vastu: kui Maya ei ole veel
        # kordagi rääkinud, ei ole ka vaikust, mida täita.
        if not self.user_turn_seen:
            return {"speak": False, "reason": "no_user_turn_yet",
                    "used": self.initiative.used,
                    "budget": self.initiative.budget}
        if self.last_activity <= 0.0:
            return {"speak": False, "reason": "no_maya_activity_yet",
                    "used": self.initiative.used,
                    "budget": self.initiative.budget}
        silent = max(0.0, now - self.last_activity)
        return self.initiative.should_speak(
            state=self.state, silent_s=silent, user_speaking=user_speaking,
            tool_running=tool_running,
            recovery_pending=self.recovery.pending,
            user_turn_seen=self.user_turn_seen)

    def as_dict(self):
        return {"state": self.state, "persona": self.persona,
                "recovery": self.recovery.as_dict(),
                "initiative_used": self.initiative.used,
                "initiative_budget": self.initiative.budget,
                "initiative_pause_s": self.initiative.pause_s}

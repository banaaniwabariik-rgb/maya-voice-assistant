#!/usr/bin/env python3
"""FAAS 6: kõnevooru elutsükli automaattestid.

Keskne nõue: NORMAALNE LÕPETAMINE, KATKESTUS ja TÕRGE peavad olema
ERISTATAVAD seisundid. Varem oli ainult "Voor lõpetatud" – sama logirida
nii õnnestumise kui katkestuse korral.

Kõik testid on automaatsed (ei vaja Android-seadet). Seadet vajavad testid
on loetletud raportis eraldi.
"""

import re


def _cfg_nimi():
    """Seadistatud kasutajanimi (vaikimisi "Kasutaja")."""
    import sys as _s2, pathlib as _p2
    _s2.path.insert(0, str(_p2.Path(__file__).resolve().parent.parent / "server"))
    import config
    return config.KASUTAJA_NIMI

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS_PATH = ROOT / "server" / "live_maya_ws.py"
HTML_PATH = ROOT / "android" / "app" / "src" / "main" / "assets" / "index.html"
WS = WS_PATH.read_text(encoding="utf-8")
HTML = HTML_PATH.read_text(encoding="utf-8")

results = []


def test(name):
    def deco(fn):
        try:
            fn()
            results.append((True, name, ""))
        except AssertionError as e:
            results.append((False, name, str(e) or "kinnitus ebaõnnestus"))
        except Exception as e:
            results.append((False, name, f"{type(e).__name__}: {e}"))
        return fn
    return deco


def load_helpers():
    """Laeb SpeechTurn ja ClientSilenceWatchdog ilma fastapi'ta."""
    start = WS.find("FATAL_LIVE_CLOSE_CODES")
    end = WS.find("@live_router.websocket", start)
    ns = {"re": re, "time": time}
    exec(compile(WS[start:end], str(WS_PATH), "exec"), ns)
    return ns.get("SpeechTurn"), ns.get("ClientSilenceWatchdog")


SpeechTurn, Watchdog = load_helpers()


def _fn_body(src, name):
    """Tagastab ÜHE funktsiooni keha sulgusid lugedes, mitte järgmise
    funktsiooni järgi – muidu haarab test kaasa naaberfunktsioonid."""
    a = src.index("function " + name)
    i = src.index("{", a)
    d = 0
    j = i
    while True:
        if src[j] == "{":
            d += 1
        elif src[j] == "}":
            d -= 1
            if d == 0:
                break
        j += 1
    return src[a:j + 1]


def turn(tid=1, persona="asjalik", t0=0.0):
    return SpeechTurn(tid, persona, t0)


# ---------------------------------------------------------------------------
# 1-2: normaalne lõpetamine ja pikk mitmetükiline vastus
# ---------------------------------------------------------------------------

@test("1. normaalne kõnevoor lõpeb olekus 'completed'")
def t1():
    assert SpeechTurn is not None, "SpeechTurn puudub"
    t = turn()
    t.note_text("Tere Peeter.")
    t.note_audio(4800, 1.0)
    t.complete(2.0)
    assert t.state == "completed", t.state
    assert not t.was_cut_off, "terviklik voor märgiti poolelijäänuks"
    assert t.summary_for_model() == "", "terviklikust voorust tekitati katkestuse selgitus"


@test("2. pikk mitmetükiline vastus loendab tükid ja heli kestuse")
def t2():
    t = turn()
    # 200 tükki a 4800 baiti = 960 000 B = 20 s heli (24 kHz, 16-bit mono)
    for i in range(200):
        t.note_audio(4800, 1.0 + i * 0.1)
    t.complete(25.0)
    assert t.chunks_sent == 200, t.chunks_sent
    assert abs(t.audio_seconds() - 20.0) < 0.01, t.audio_seconds()
    assert t.state == "completed"


# ---------------------------------------------------------------------------
# 3-5: puuduvad, hilinenud ja katkenud voog
# ---------------------------------------------------------------------------

@test("3. tekst ilma helita EI ole lõpetatud kõne (heli ei jõudnud kuhugi)")
def t3():
    t = turn()
    t.note_text("Ma räägiksin, aga heli ei tulnud.")
    assert t.state == "generating", t.state
    assert t.chunks_sent == 0 and t.audio_seconds() == 0.0
    # Mudeli jaoks ei tohi see paista eduka kõnena
    t.fail(5.0, "no_audio")
    assert t.was_cut_off


@test("4. hilinenud tükid ei riku järjestust ega kestust")
def t4():
    t = turn()
    t.note_audio(4800, 1.0)
    t.note_audio(4800, 9.0)     # suur viide
    t.complete(10.0)
    assert t.first_audio_at == 1.0 and t.last_audio_at == 9.0
    assert t.chunks_sent == 2


@test("5. voo ootamatu lõpp annab oleku 'failed' koos põhjusega")
def t5():
    t = turn()
    t.note_audio(4800, 1.0)
    t.fail(2.0, "1007")
    assert t.state == "failed", t.state
    assert t.failure_reason == "1007"
    assert t.was_cut_off
    s = t.summary_for_model()
    assert "tehniline tõrge" in s and "1007" in s, s


# ---------------------------------------------------------------------------
# 6-8: ühenduse, helikonteksti ja taasesituse tõrked
# ---------------------------------------------------------------------------

@test("6. WebSocketi katkemine on TÕRGE, mitte edukas lõpetamine")
def t6():
    t = turn()
    t.note_audio(4800, 1.0)
    t.fail(3.0, "websocket_1006")
    assert t.state == "failed" and t.state != "completed"


@test("7. taasesitust EI väideta kinnitatuks, kui klient seda ei raporteeri")
def t7():
    t = turn()
    t.note_audio(48000, 1.0)
    t.complete(3.0)
    assert t.playback_confirmed is False, \
        "taasesitus märgiti kinnitatuks, kuigi Android ei raporteeri positsiooni"
    d = t.as_dict()
    assert d["playback_confirmed"] is False
    # Piirang peab olema sõnastatud, mitte vaikides eeldatud
    t2 = turn(2)
    t2.note_text("pool lauset")
    t2.note_audio(24000, 1.0)
    t2.interrupt(2.0, "user_speech")
    assert "EI OLE TEADA" in t2.summary_for_model(), \
        "piirangut ei öelda välja – mudel võib fabritseerida, kui palju kuuldi"


@test("8. helikonteksti peatumine on eristatav lõpetamisest")
def t8():
    a, b = turn(1), turn(2)
    a.note_audio(4800, 1.0); a.complete(2.0)
    b.note_audio(4800, 1.0); b.fail(2.0, "audiocontext_suspended")
    assert a.state != b.state
    assert not a.was_cut_off and b.was_cut_off


# ---------------------------------------------------------------------------
# 9-11: tahtlik vs ootamatu katkestus
# ---------------------------------------------------------------------------

@test("9. tahtlik vahelesegamine märgitakse 'user_speech'-iks")
def t9():
    t = turn()
    t.note_text("Kevad algab Eestis")
    t.note_audio(48000, 1.0)
    t.interrupt(2.0, "user_speech")
    assert t.state == "interrupted" and t.interrupt_reason == "user_speech"
    s = t.summary_for_model()
    # AVALIK VERSIOON: nimi tuleb seadistusest ({USER} kohahoidja),
    # seega kontrollime kohahoidjat, mitte ühe inimese nime.
    assert "hakkas rääkima" in s, s
    assert ("{USER}" in s) or (_cfg_nimi() in s), s


@test("10. ootamatu katkestus EI väida teadvat põhjust")
def t10():
    t = turn()
    t.note_text("Midagi jäi pooleli")
    t.interrupt(2.0, "unknown")
    s = t.summary_for_model()
    assert "põhjus jäi tuvastamata" in s, s
    assert "Peeter hakkas rääkima" not in s, "teadmata põhjus esitati kasutaja süüna"


@test("11. neli lõppseisundit on üksteisest eristatavad")
def t11():
    a, b, c, d = turn(1), turn(2), turn(3), turn(4)
    a.complete(1.0)
    b.interrupt(1.0, "user_speech")
    c.interrupt(1.0, "unknown")
    d.fail(1.0, "network")
    seisud = {a.state, b.state, d.state}
    assert len(seisud) == 3, seisud
    assert b.interrupt_reason != c.interrupt_reason, "tahtlik ja ootamatu ei erine"
    assert all(x in SpeechTurn.STATES for x in (a.state, b.state, c.state, d.state))


# ---------------------------------------------------------------------------
# 12-14: oleku säilimine, järelküsimus, koristus
# ---------------------------------------------------------------------------

@test("12. katkenud vooru tekst SÄILIB (varem visati ära)")
def t12():
    t = turn()
    t.note_text("Ma tahtsin öelda, et kevad algab Eestis alati ootamatu sulaga")
    t.interrupt(2.0, "user_speech")
    assert t.text, "pooleli jäänud tekst kadus"
    assert "ootamatu sulaga" in t.summary_for_model(), \
        "lõpuosa ei jõua mudelini – järelküsimusele ei saa vastata"
    # Serveripoolne kood peab katkenud vooru SALVESTAMA enne tr_buf nullimist.
    i = WS.find('getattr(server_content, "interrupted"')
    assert i != -1, "katkestuse käsitlust ei leitud"
    blokk = WS[i:WS.find("if server_content and server_content.model_turn", i)]
    assert 'last_cut_turn["t"] = t_obj' in blokk, "katkenud vooru ei salvestata kuhugi"
    assert blokk.index('last_cut_turn["t"] = t_obj') < blokk.index('tr_buf["assistant"] = ""'), \
        "voor salvestatakse ALLES pärast teksti nullimist – tekst oleks kadunud"


@test("13. järelküsimusele vastamiseks on tööriist olemas ja ühendatud")
def t13():
    assert '"name": "get_last_turn_state"' in WS, "tööriista pole deklareeritud"
    assert 'fn_name == "get_last_turn_state"' in WS, "tööriista ei dispetšita"
    assert "summary_for_model()" in WS, "tööriist ei tagasta vooru kokkuvõtet"
    # Süsteemiprompt peab mudelile ütlema, MILLAL seda kutsuda
    assert "MIKS SA POOLELI JÄID" in WS, "mudelile ei öelda, millal tööriista kutsuda"
    assert "Ära mõtle" in WS, "mudelit ei keelata põhjust välja mõtlemast"


@test("14. kui katkestusi pole, ei fabritseerita katkestuse juttu")
def t14():
    t = turn()
    t.complete(1.0)
    assert t.summary_for_model() == ""
    # Haru kasvas 10.11.2026 parandusega (seansipiiri valenegatiiv), seega
    # aken on nüüd kogu tööriistaplokk, mitte esimesed 600 märki.
    i = WS.find('fn_name == "get_last_turn_state"')
    blokk = WS[i:i + 4200]   # haru kasvas aegumiskontrolliga (CUT_TURN_TTL_S)
    assert "ei ole ükski sinu voor" in blokk, \
        "katkestuste puudumisel ei anta mudelile selget eitust"
    # UUS NÕUE samast parandusest: eituse puudumine EI TOHI tähendada, et
    # mudel väidab 'kõik oli korras' või süüdistab kasutajat. Mõõdetud
    # tootmises (voorud 982 -> 983): Maya ütles "Võib-olla oli mingi
    # tehniline tõrge SINU POOL?", kuigi seanss suri 1007-ga.
    assert "SIIT EI JÄRELDU" in blokk, \
        "kirje puudumisest lastakse järeldada, et kasutaja eksib"
    assert "ÄRA väida" in blokk, "mudelit ei keelata 'kõik oli korras' väitest"
    # Ja eelmise KÕNE kirjet peab ikkagi küsitama, enne kui eitada.
    assert "take_unfinished_turn(active_persona)" in blokk, \
        "eelmise kõne katkestust ei küsita – seansipiiri valenegatiiv on tagasi"


@test("15. kogu eelmist vastust EI süstita konteksti (ainult saba)")
def t15():
    t = turn()
    t.note_text("x" * 5000)
    t.interrupt(2.0, "user_speech")
    s = t.summary_for_model()
    assert len(s) < 600, f"kokkuvõte on {len(s)} märki – liiga pikk, paisutab iga viipa"


@test("16. vooru olek logitakse struktuurselt (as_dict)")
def t16():
    t = turn()
    t.note_audio(4800, 1.0)
    t.complete(2.0)
    d = t.as_dict()
    for k in ("turn_id", "persona", "state", "chars", "chunks", "audio_s",
              "playback_confirmed", "interrupt_reason", "failure_reason"):
        assert k in d, f"võti puudub: {k}"
    assert "[LIVE WS VOOR]" in WS, "vooru olekut ei logita"


# ---------------------------------------------------------------------------
# 17-18: seansi koristus ja taastumine (olemasolev funktsionaalsus)
# ---------------------------------------------------------------------------

@test("17. vaikuse valvur eristab vaikust ja digitaalset vaikust")
def t17():
    w = Watchdog(0.0)
    for i in range(1, 40):
        w.note_input(float(i), audible=False)
    assert w.status(39.0) == "ok"
    assert w.silent_audio_status(39.0) == "warn"


@test("18. seansi lõpus käivitub koristus ja mälu konsolideerimine")
def t18():
    assert "cost_tracker.save_session()" in WS, "kulu ei salvestata"
    assert "consolidate_session_to_memory" in WS, "mälu ei konsolideerita"
    # Tühistamine on nüüd ÜHES kohas (_sulge_seanss), mitte kolmes
    # laiali, ja taskid OODATAKSE ära enne Gemini seansi sulgemist.
    assert "ticker_task" in WS, "tiksujat ei looda"
    assert "async def _sulge_seanss(" in WS, "ühtne sulgemine puudub"
    assert "t.cancel()" in WS, "taske ei tühistata"
    assert "await asyncio.wait(\n" in WS or "await asyncio.wait(" in WS, \
        "taske ei oodata ära"


# ---------------------------------------------------------------------------
# 19-20: Androidi taustamikrofon (Test B juurpõhjus)
# ---------------------------------------------------------------------------

MANIFEST = (ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
SERVICE = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "maya" / "live"
           / "CallWatcherService.kt").read_text(encoding="utf-8")


@test("19. foreground-teenus on deklareeritud mikrofonitüübiga")
def t19():
    """Test B 7.11: ilma selleta annab Android taustal mikrofonist vaikuse.
    Mõõdetud: 1367 kaadrit, tase 0,0000, AudioContext jäi 'running'."""
    assert 'android:foregroundServiceType="microphone"' in MANIFEST, \
        "teenusel puudub foregroundServiceType – taustal tuleb mikrofonist vaikus"
    assert "FOREGROUND_SERVICE_MICROPHONE" in MANIFEST, \
        "targetSdk 34 nõuab tüübipõhist luba eraldi"


@test("20. startForeground annab tüübi kaasa ka käivitamisel")
def t20():
    assert "ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE" in SERVICE, \
        "tüüpi ei anta startForeground'ile – manifestist üksi ei piisa"
    assert "import android.content.pm.ServiceInfo" in SERVICE, "import puudub"
    # vanemad seadmed peavad endiselt tööle jääma
    assert "Build.VERSION_CODES.Q" in SERVICE, "puudub API-versiooni kaitse"


@test("21. tühi voor tuvastatakse ja kasutajale teatatakse")
def t21():
    """Mõõdetud: 26 juhtu, kus Gemini lõpetas vooru ilma vastuseta mediaanis
    1,09 s pärast kasutaja kõnet. Varem jäi kasutaja vaikuse ette."""
    assert "TÜHI VOOR" in WS, "tühja vooru ei logita"
    assert "last_user_speech" in WS, "kasutaja kõne aega ei jälgita"
    assert '"type": "no_reply"' in WS, "kasutajale ei teatata"
    assert "_idle <= 3.0" in WS, "puudub ajaaken – teade tuleks ka ilma kasutaja kõneta"
    assert 'pkt.type === "no_reply"' in HTML, "klient ei kuva teadet"


@test("22. heli vaibub pehmelt, mitte järsu lõikega")
def t22():
    assert "FADE_OUT_MS" in HTML, "vaibumise kestus puudub"
    assert "linearRampToValueAtTime" in HTML, "helitugevust ei rambita"
    stop = HTML[HTML.find("function stopLiveAudio"):]
    stop = stop[:stop.find("function playLiveChunk")]
    assert "s.stop(stopAt)" in stop, "allikad peatatakse enne vaibumise lõppu"
    assert "fadeEndsAt = stopAt" in stop, "vaibumise lõppu ei jäeta meelde"


@test("23. saabuv kaader EI tühista pooleliolevat vaibumist")
def t23():
    # Ajastamise loogika elab nüüd scheduleBuffer'is (tükid liidetakse enne).
    play = HTML[HTML.find("function scheduleBuffer"):]
    play = play[:play.find("function playLiveChunk")]
    assert "currentTime >= fadeEndsAt" in play, \
        "helitugevus lähtestatakse igal kaadril – vaibumine katkeks ja hääl hüppaks valjuks"


# ---------------------------------------------------------------------------
# 24-25: kõik parandused kehtivad KÕIGILE karakteritele
# ---------------------------------------------------------------------------

@test("24. ükski parandus ei ole karakteripõhine")
def t24():
    """Kasutaja arvas 7.11, et parandused kehtivad ainult ASJALIKULE.
    Logi tõestas vastupidist (sober sai sama VAD-i ja hääle), kuid see test
    lukustab selle, et keegi ei saaks hiljem kogemata mõnda neist mõne
    karakteri taha peita."""
    personad = ("asjalik", "sober", "singer", "zen", "mentor", "filosoof",
                "treener", "romantiline", "sarkastiline", "custom")
    tunnused = {
        "VAD seadistus": 'vad_cfg["realtime_input_config"]',
        "SpeechTurn": "SpeechTurn(",
        "tühja vooru tuvastus": "TÜHI VOOR",
        "get_last_turn_state": '"name": "get_last_turn_state"',
        "interrupted edastus": '"type": "interrupted"',
        "no_reply teade": '"type": "no_reply"',
    }
    vead = []
    for nimi, muster in tunnused.items():
        i = WS.find(muster)
        assert i != -1, f"{nimi} puudub koodist"
        ees = WS[max(0, i - 1500):i]
        # Kas mõni karakteri-tingimus on vahetult enne?
        for pid in personad:
            if f'== "{pid}"' in ees[-400:]:
                vead.append(f"{nimi} on '{pid}' tingimuse sees")
    assert not vead, "; ".join(vead)


@test("25. tööriista reegel lisatakse persona_rule JÄRELE, mitte selle sisse")
def t25():
    i = WS.find("KUI KASUTAJA KÜSIB, MIKS SA POOLELI JÄID")
    assert i != -1, "tööriista reegel puudub süsteemipromptist"
    algus = WS.rfind("system_instruction_text = (", 0, i)
    assert algus != -1, "reegel ei ole system_instruction_text sees"
    # persona_rule peab olema ENNE ühiseid reegleid
    plokk = WS[algus:i]
    assert "persona_rule" in plokk, \
        "ühised reeglid ei järgne karakteri promptile – mõni karakter jääks ilma"
    # Karakterite endi promptid EI tohi neid reegleid sisaldada
    import sys as _s
    _s.path.insert(0, str(ROOT / "server"))
    import persona_registry as R
    for pp in R.get_all_personas():
        t = R.build_voice_prompt(pp.id, "")
        assert "get_last_turn_state" not in t, \
            f"{pp.id} prompti on tööriista reegel sisse kirjutatud – peaks olema ühine"


@test("26. vahelesegamine EI anna valehäiret 'Maya ei vastanud'")
def t26():
    """Mõõdetud: 6 tuvastatud tühjast voorust 4 olid vahelesegamise tagajärg
    – kasutaja katkestas enne Maya esimest helibaiti. Neil juhtudel polnudki
    midagi öelda ja teade oli eksitav."""
    assert 'just_interrupted' in WS, "katkestuse lippu ei hoita"
    # Ankurdame TEGELIKU kontrolli külge, mitte kommentaari – muidu kukub
    # test iga kord, kui selgitust juurde kirjutatakse.
    i = WS.find("_idle = time.monotonic() - last_user_speech")
    assert i != -1, "tühja vooru kontrolli ei leitud"
    blokk = WS[i:i + 400]
    assert 'if just_interrupted["v"]:' in blokk, \
        "tühja vooru teadet ei summutata katkestuse järel – tekib valehäire"
    assert blokk.index('if just_interrupted["v"]:') < blokk.index('elif last_user_speech'), \
        "summutus ei ole enne teate loogikat"
    # lippu peab ka nullitama, muidu summutaks see KÕIK järgnevad teated
    assert 'just_interrupted["v"] = False' in WS, "lippu ei nullita kunagi"
    assert 'just_interrupted["v"] = True' in WS, "lippu ei seata katkestusel"


# ---------------------------------------------------------------------------
# 27-28: laulja ragin ja vale loo metaandmed
# ---------------------------------------------------------------------------

@test("27. helil on värinapuhver (ragina juurpõhjus)")
def t27():
    """Mõõdetud: tükk on 43 ms, ~23 ajastatud sõlme sekundis, ohutusvaru oli
    null. Laulmises (pidev toon, ~1200 tükki voorus) kuuldub iga auk raginana."""
    assert "JITTER_BUFFER_S" in HTML, "värinapuhver puudub"
    play = HTML[HTML.find("function scheduleBuffer"):]
    play = play[:play.find("function playLiveChunk")]
    kood = "\n".join(r for r in HTML.split("\n") if not r.strip().startswith("//"))
    assert "nextPlayTime = Math.max(nextPlayTime, now)" not in kood, \
        "vana ohutusvaruta ajastamine on alles"
    assert "nextPlayTime < now + MIN_LEAD_S" in play, "varu ei kontrollita"
    assert "nextPlayTime = now + JITTER_BUFFER_S" in HTML, "puhvrit ei taastata"
    assert "audioStats.underruns" in HTML, "alatäitumisi ei loendata"


@test("29. helitükid liidetakse ja ajastatakse sämplitäpselt")
def t29():
    """Mõõdetud pärast värinapuhvrit: 1312 tükki, 1 alatäitumine (0,1%) –
    ajastamine oli korras, aga ragin jäi. Põhjus: 1311 liitekohta, igaüks
    ümardatakse lähima sämplini. 150 ms liitmine vähendab liitekohti ~3,5x
    ja sämplitäpne algus kaotab ümardamise."""
    assert "MERGE_MS" in HTML, "tükke ei liideta"
    assert "function flushPending" in HTML, "ootejärjekorda ei tühjendata"
    sched = HTML[HTML.find("function scheduleBuffer"):]
    sched = sched[:sched.find("function playLiveChunk")]
    assert "Math.round(nextPlayTime * sr)" in sched, \
        "algusaega ei kvantita sämplitäpselt"
    assert "nextPlayTime = (startSample + buffer.length) / sr" in sched, \
        "järgmist algust ei arvutata sämplitest – ujukomaviga kuhjub"
    # saba peab alati valmis saama, ka kui lävend ei täitu
    assert "pendingTimer = setTimeout(flushPending" in HTML, \
        "voo lõpus jääks saba ajastamata"
    # katkestusel ei tohi ootel tükid hiljem mängima hakata
    stop = HTML[HTML.find("function stopLiveAudio"):]
    stop = stop[:stop.find("function scheduleBuffer")]
    assert "pendingChunks = []" in stop, "katkestusel jäävad ootel tükid alles"
    # disconnect läks puhvrite ümberkirjutamisel kaduma; ilma selleta võis
    # tulevikku ajastatud heli vahelesegamise järel edasi mängida.
    assert "s.disconnect()" in stop, "allikaid ei lahutata – ajastatud heli võib jätkuda"


@test("28. vale loo metaandmed ei pääse enam läbi")
def t28():
    """Mõõdetud tootmises: laulusõnad olid õiged, aga pealkiri/helistik/tempo
    tulid VÕÕRAST loost, sest värav lubas artisti nime põhjal läbi."""
    import sys as _s
    _s.path.insert(0, str(ROOT / "server"))
    import maya_singing_pipeline as P
    valed = [
        ("Eda-Ines Etti 15 magamata ööd", "Eda-Ines Etti - Keerlen"),
        ("Anne Veski Pihtimus", "Anne Veski - Hea tuju laul"),
        ("Ewert and The Two Dragons Taevas", "Ewert and The Two Dragons - Somewhere"),
        ("Metallica Nothing Else Matters", "Metallica - Enter Sandman"),
    ]
    for q, k in valed:
        assert not P.matches_query(q, k), f"vale lugu pääses läbi: {q!r} -> {k!r}"
    õiged = [
        ("Pohjatuul Kuutõbine", "Pohjatuul - Kuutõbine"),
        ("Pohjatuul Kuutõbine", "Pohjatuul - Kuutõbise lugu"),   # kääne
        ("Anne Veski Roosiaia kuninganna", "Martin Loik - Roosiaia kuninganna - Anne Veski"),
        ("Eda-Ines Etti 15 magamata ööd", "Eda-Ines Etti - 15 magamata ööd"),
    ]
    for q, k in õiged:
        assert P.matches_query(q, k), f"õige lugu lükati tagasi: {q!r} -> {k!r}"


@test("30. liitmine ei söö värinapuhvrit (kohanev tühjendus)")
def t30():
    """Mõõdetud: 150 ms liitmine vähendas liitekohti 75%, AGA tõstis
    alatäitumisi 0,1% -> 0,63%, sest ootamine sõi varu. Nüüd tühjendatakse
    kohe, kui varu napib."""
    assert "LOW_LEAD_S" in HTML, "madala varu lävend puudub"
    play = HTML[HTML.find("function playLiveChunk"):]
    play = play[:play.find("function startRecording")]
    assert "lead < LOW_LEAD_S" in play, \
        "varu napides ei ajastata kohe – liitmine sööb värinapuhvri ära"
    assert "nextPlayTime - audioCtxOut.currentTime" in play, "varu ei arvutata"
    import re as _re
    m = _re.search(r"const JITTER_BUFFER_S = ([\d.]+)", HTML)
    assert m and float(m.group(1)) >= 0.25, "värinapuhver on liiga väike"


@test("31. subtiitrid ei sunni paigutust iga fragmendi peale")
def t31():
    """Mõõdetud: 388 fragmenti 90 minutiga, igaüks tegi innerText + scrollHeight
    = kaks paigutust sundivat operatsiooni samal põhilõimel, kus ajastatakse
    heli. See sõi värinapuhvrit ja tootis alatäitumisi."""
    rt = _fn_body(HTML, "renderTranscript")
    assert "innerText" not in rt, "innerText sunnib paigutust – kasuta textContent"
    assert "scrollHeight" not in rt, \
        "scrollHeight loetakse iga fragmendi peale – see sunnib sünkroonse reflow"
    assert "requestAnimationFrame(flushSubtitles)" in rt, "uuendusi ei koondata"
    flush = _fn_body(HTML, "flushSubtitles")
    assert "textContent" in flush, "tekstid ei kasuta odavat textContent'i"
    assert "clientHeight" in flush, "ei kontrollita, kas kasutaja on juba all"


@test("32. subtiitreid saab välja lülitada")
def t32():
    assert "subtitlesOn" in HTML, "lülitit pole"
    assert "maya_subtitles" in HTML, "valik ei säili localStorage's"
    rt = _fn_body(HTML, "renderTranscript")
    assert "if (!subtitlesOn) return;" in rt, \
        "väljas olekus tehakse ikka tööd"
    assert 'id="subtitleToggle"' in HTML, "nuppu pole liideses"


@test("33. seansi taastamine 1007/1011 järel")
def t33():
    """1007 tabas 20 päeva jooksul 21 korda, kõigil karakteritel. Põhjus on
    Gemini pool; meie saame teha selle üleelatavaks."""
    assert "session_resumption" in WS, "taastamist ei küsita"
    assert "store_resume_handle" in WS and "take_resume_handle" in WS, \
        "käepidet ei salvestata/kasutata"
    assert "session_resumption_update" in WS, "käepidet ei loeta vastusest"
    assert '"recoverable"' in WS, "kliendile ei öelda, kas tõrge on taastatav"
    assert "_v[\"code\"] in (1007, 1011)" in WS, "taastatavus pole koodipõhine"
    # klient: ainult ÜKS automaatne katse
    assert "autoResumeUsed" in HTML, "kliendil pole taasühenduse piirajat"
    assert "ev.isTrusted" in HTML, \
        "loendurit nullitakse ka programmilisel vajutusel – tekiks lõputu tsükkel"


@test("34. ükski oluline JS-funktsioon pole kaduma läinud")
def t34():
    """8.11: asendasin renderTranscript'i vahemiku järgi (algus -> järgmine
    funktsioon) ja kustutasin kogemata 13 600 tähemärki, sh appendLog ja
    streamMayaSubtitles. Tagajärg: kõnenupp viskas ReferenceError'i ja äpp
    ei reageerinud ühelegi vajutusele. See test püüab sellise kaotuse kinni."""
    import re as _re
    kohustuslikud = [
        "appendLog", "renderTranscript", "streamMayaSubtitles",
        "saveToPersistentLog", "getTime", "setUIState", "playLiveChunk",
        "scheduleBuffer", "flushPending", "flushSubtitles",
        "stopLiveAudio", "reviveAudioContexts", "initAudio",
    ]
    puudu = []
    for fn in kohustuslikud:
        if not _re.search(r"(function\s+%s\s*\(|window\.%s\s*=)" % (fn, fn), HTML):
            puudu.append(fn)
    assert not puudu, "deklaratsioon puudub: " + ", ".join(puudu)

    # Kaitsmata kutsed funktsioonidele, mida pole olemas, tapavad käitleja.
    kutsutud = set(_re.findall(r"(?<![.\w])([a-zA-Z_]\w{3,})\s*\(", HTML))
    deklareeritud = set(_re.findall(r"function\s+(\w+)\s*\(", HTML))
    deklareeritud |= set(_re.findall(r"window\.(\w+)\s*=", HTML))
    deklareeritud |= set(_re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", HTML))
    # Need on brauseri/standardi omad, mitte meie
    for fn in kohustuslikud:
        assert fn in deklareeritud, f"{fn} pole deklareeritud"


@test("35. poolikuse tuvastus loeb KOGU vooru teksti, mitte fragmenti")
def t35():
    """08.11: detektor luges tr_buf['assistant'], mille flush_transcript
    tühjendab iga subtiitrisaadetise järel. Vooru lõpus oli seal ainult
    viimane saatmata fragment (nt 'nii'), mitte kogu 198-täheline voor.
    Logi andis mõttetuid tulemusi: '0.1 tähem/s'."""
    i = WS.find('turn_stats["truncated"] += 1')
    assert i != -1, "poolikuse loendurit ei leitud"
    eelnev = WS[max(0, i - 1400):i]
    assert "_ct.text" in eelnev, \
        "poolikust hinnatakse fragmendi, mitte kogu vooru teksti järgi"
    assert 'said = (tr_buf["assistant"]' not in WS, \
        "vana fragmendipõhine lugemine on alles"
    # SpeechTurn peab teksti koguma ja seda ei tohi vahepeal tühjendada
    body = _fn_body(WS.replace("def note_text", "function note_text"), "note_text")
    assert "self.text +=" in body, "SpeechTurn ei kogu teksti kumulatiivselt"


@test("36. poolikut lauset jätkatakse automaatselt, piiratult ja korduvalt")
def t36():
    """MUUDETUD (hilisem ring 10.11.2026): jätkamisloogika liikus
    `conversation_flow.py`-sse ja vana `AINULT_JATKAMISI = 1` kaotati.

    MÕÕDETUD PÕHJUS: kaks jätkamist tootmises (17:30 ja 17:32) olid
    MÕLEMAD ise poolikud ja piirang 1 blokeeris kõik edasised katsed –
    Maya jäi 17:33:04 keset lauset vait ja 36 sekundit ei juhtunud
    midagi, kuni kasutaja ise toru ära pani. Katkemise määr on
    9/21 = 42,9%, seega ühe katsega jääb 42,9% lauseid pooleli.

    Kaitsed peavad siiski kõik alles olema."""
    import sys as _s, pathlib as _pl
    _s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "server"))
    import conversation_flow as cf

    # eelarve on suurem kui 1, aga piiratud
    assert cf.RECOVERY_BUDGET > 1, "eelarve 1 jättis 42,9% lauseid pooleli"
    # OMANIKU OTSUS 11.11.2026: "mingit piirangut ei ole". Tsükli ohu
    # vastu ei kaitse enam väike eelarve, vaid see, et iga katse NÕUAB
    # uut Gemini turn_complete sündmust + korduse tuvastus. Eelarve on
    # ülemine kaitse lõputu poolikute voorude seeria vastu.
    assert cf.RECOVERY_BUDGET <= 20, "eelarve on piiritu"
    assert cf.RECOVERY_BUDGET >= 12, "piirangut langetati ilma otsust"
    # esimene katse EI OOTA
    assert cf.RECOVERY_BACKOFF_S[0] == 0.0, "esimene taaste ootab – keelatud"

    # ahel peab LÕPLIKULT peatuma
    f = cf.ConversationFlow("asjalik")
    katseid = 0
    for i in range(30):
        o = f.on_turn_complete(text="ikka jäi pooleli %d" % i, tail_len=20,
                               audio_s=10.0, tail_is_terminal=False,
                               user_interrupted=False, tool_running=False,
                               playback_end_est=i * 10.0, now=i * 10.0)
        if o["recover"]:
            katseid += 1
            f.on_recovery_dispatched("ikka jäi pooleli %d" % i, now=i * 10.0)
    assert katseid == cf.RECOVERY_BUDGET, \
        "ahel ei peatunud eelarve peal (%d katset)" % katseid
    assert f.recovery.stopped_reason == "budget_exhausted"

    # vahelesegamine blokeerib
    f2 = cf.ConversationFlow("asjalik")
    o = f2.on_turn_complete(text="jäi pooleli", tail_len=11, audio_s=10.0,
                            tail_is_terminal=False, user_interrupted=True,
                            tool_running=False, playback_end_est=0.0, now=0.0)
    assert not o["recover"], "jätkaks ka siis, kui kasutaja ise vahele segas"

    # tootmiskood: palve läheb session.send'iga, MITTE send_realtime_input'iga
    i = WS.index("conversation_flow.RECOVERY_PROMPT")
    # KOMMENTAARID VÄLJA: selgitus mainib `send_realtime_input`'i just
    # selleks, et öelda, miks seda EI kasutata.
    kontekst = "\n".join(r for r in WS[max(0, i - 600):i + 200].splitlines()
                         if not r.strip().startswith("#"))
    # gsend = session.send Gemini saatmisluku all (kolm taski saadavad
    # nüüd samasse seanssi). Sisu peab endiselt minema Geminile, mitte
    # kliendile, ja MITTE send_realtime_input'iga (see käivitaks VAD-i).
    assert "await gsend(" in kontekst, "taastepalvet ei saadeta kliendisisuna"
    assert "realtime" not in kontekst, "taastepalve käivitaks VAD-i"
    assert "send_realtime_input" not in kontekst, \
        "taastepalve läheb reaalajas sisendina – VAD katkestab Maya"
    # jätkamispalve ei tohi minna töömällu kasutaja vooruna
    assert 'working_mem.add_turn("user", "[SÜSTEEM]' not in WS


@test("37. seanss taastatakse AINULT tõrke järel, mitte uuel kõnel")
def t37():
    """08.11: taastamine käivitus iga uue ühenduse peal, kui pilet oli
    värske. Kasutaja pani toru hargile ja helistas 7 s hiljem – taastati
    eelmine seanss KOOS VANA SÜSTEEMIPROMPTIGA, ja kohandatud karakter
    rääkis ammu muudetud juhiste järgi."""
    assert "arm_resume" in WS and "disarm_resume" in WS, "lubamise lülitit pole"
    # Pilet ei tohi olla kasutatav ilma selgesõnalise lubamiseta
    i = WS.find("def take_resume_handle")
    body = WS[i:i + 700]
    assert 'if not _RESUME_HANDLE["armed"]' in body, \
        "pilet antakse välja ka ilma lubamiseta – vana kontekst lekib uude kõnesse"
    # Lubatakse ainult taastatava tõrke korral
    j = WS.find("_recoverable = ")
    assert "arm_resume(" in WS[j:j + 300], "taastamist ei lubata tõrke korral"
    # Kasutaja enda sulgemine peab taastamise KEELAMA
    k = WS.find("if code in (1000, 1001):")
    assert k != -1 and "disarm_resume()" in WS[k:k + 120], \
        "kasutaja korrektne sulgemine ei keela taastamist"
    import re as _re
    m = _re.search(r"RESUME_WINDOW_S = ([\d.]+)", WS)
    assert m and float(m.group(1)) <= 60, "taastamisaken on liiga pikk"


if __name__ == "__main__":
    print("FAAS 6: KÕNEVOORU ELUTSÜKLI AUTOMAATTESTID")
    print("=" * 70)
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, err in results:
        print(f"  {'LÄBITUD' if ok else 'KUKKUS '}  {name}")
        if not ok:
            print(f"            -> {err}")
    print("=" * 70)
    print(f"{passed}/{len(results)} läbitud")
    sys.exit(0 if passed == len(results) else 1)

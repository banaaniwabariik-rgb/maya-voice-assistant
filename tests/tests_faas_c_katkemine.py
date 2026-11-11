#!/usr/bin/env python3
"""FAAS C: kõne katkemise taastootmistestid.

Iga test vastab ÜHELE tootmislogist tõendatud tõrkele. Testid on kirjutatud
nii, et nad KUKUVAD LÄBI refaktoorimise-eelse koodi vastu (backups_sprint_
20261106/live_maya_ws.py) ja LÄBIVAD paranduste järel. Nii on tõestatud, et
nad püüavad päris vea, mitte ei kinnita lihtsalt olemasolevat käitumist.

Käivita:
    python3 tests_faas_c_katkemine.py            # parandatud kood
    python3 tests_faas_c_katkemine.py --vana      # varukoopia (peab kukkuma)
"""

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VANA = "--vana" in sys.argv

WS_PATH = (ROOT / "backups_sprint_20261106" / "live_maya_ws.py") if VANA else (ROOT / "server" / "live_maya_ws.py")
HTML_PATH = (
    (ROOT / "backups_sprint_20261106" / "android_app_src_main_assets_index.html")
    if VANA
    else (ROOT / "android" / "app" / "src" / "main" / "assets" / "index.html")
)

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


# Parandatud moodulit saab importida ainult siis, kui fastapi on olemas.
# Testid 1-3 kasutavad puhtaid abifunktsioone, mille kopeerime siit sisse
# ilma moodulit importimata (fastapi pole lokaalselt paigaldatud).
def load_helpers():
    """Laeb classify_live_failure ja ClientSilenceWatchdog ilma fastapi'ta."""
    src = WS
    start = src.find("FATAL_LIVE_CLOSE_CODES")
    if start == -1:
        return None, None
    end = src.find("@live_router.websocket", start)
    block = src[start:end]
    ns = {"re": re, "time": time}
    exec(compile(block, str(WS_PATH), "exec"), ns)
    return ns.get("classify_live_failure"), ns.get("ClientSilenceWatchdog")


classify, Watchdog = load_helpers()


# ---------------------------------------------------------------------------
# 1008 — kliendi tegevusetus ja tühikäigutsükkel (189 x / 94 s tootmises)
# ---------------------------------------------------------------------------

@test("1. 1008 'client inactivity' liigitub LÕPLIKUKS (ei korrata)")
def t1():
    assert classify is not None, "classify_live_failure puudub täielikult"
    v = classify("1008 None. Session closed due to client inactivity.")
    assert v["kind"] == "fatal", f"liigitati {v['kind']}, oodati fatal"
    assert v["code"] == 1008, v["code"]
    assert "mikrofon" in v["message"].lower(), v["message"]


@test("2. 1007 'content type not supported' liigitub LÕPLIKUKS")
def t2():
    assert classify is not None, "classify_live_failure puudub täielikult"
    v = classify(
        "1007 None. The audio content type (CONTENT_TYPE_AUDIO) is not "
        "supported for this model configuration."
    )
    assert v["kind"] == "fatal", f"liigitati {v['kind']}"
    assert v["code"] == 1007, v["code"]


@test("3. ajutine võrgutõrge jääb AJUTISEKS (kõnet ei tapeta ühe kiiksu pärast)")
def t3():
    assert classify is not None, "classify_live_failure puudub täielikult"
    for msg in ["Temporary failure in name resolution",
                "ConnectionResetError: [Errno 104] Connection reset by peer",
                "timed out"]:
        v = classify(msg)
        assert v["kind"] == "transient", f"{msg!r} -> {v['kind']}"


@test("4. Gemini tsükkel EI korda lõpliku tõrke peal lõputult")
def t4():
    # Vana kood: `except Exception: print(...); await asyncio.sleep(0.5)`
    # ilma ühegi väljumistingimuseta -> `while running` kordas igavesti.
    block = WS[WS.find("async def send_to_client"):]
    block = block[:block.find("client_task = asyncio.create_task")]
    assert "classify_live_failure" in block, \
        "send_to_client ei liigita tõrkeid – surnud seansi peal tekib tühikäigutsükkel"
    assert re.search(r'if verdict\["kind"\] == "fatal"', block), \
        "lõpliku tõrke korral puudub väljumine (break)"
    assert "0.5 * gemini_errors" in block or "min(0.5" in block, \
        "puudub astmeline ooteaeg – kordused jäävad 0,5 s sammuga"


@test("5. järjestikuste Gemini tõrgete ülempiir toimib ka püsiva vea korral")
def t5():
    block = WS[WS.find("async def send_to_client"):]
    block = block[:block.find("client_task = asyncio.create_task")]
    assert 'gemini_errors["count"] >= 5' in block, "puudub järjestikuste tõrgete piir"
    assert 'gemini_errors["count"] = 0' in block, "loendurit ei nullita õnnestumisel"
    # 08.11: loendur nullitati IGA vastuse peale, seega püsiv per-sõnumi viga
    # (minu NameError) ei jõudnud kunagi 5-ni – logis 20+ sama viga ühes kõnes.
    assert "gemini_ok" in block, "puudub järjestikuste ÕNNESTUMISTE loendur"
    assert 'gemini_ok["streak"] >= 5' in block, \
        "loendur nullitakse ühe vastuse peale – püsiv viga ei peata tsüklit"
    assert 'gemini_ok["streak"] = 0' in block, "veal ei nullita õnnestumiste seeriat"


@test("5b. uued signaalid loetakse PÄRAST server_content omistamist")
def t5b():
    """08.11: lisasin generation_complete/interaction_status lugemise ENNE
    server_content'i omistamist. Iga vastus viskas NameError'i ja Maya ei
    saanud üldse rääkida."""
    # PIIRITLETUD `send_to_client` KEHAGA. Naiivne üle kogu faili
    # otsimine tabas ära nii mooduli päise kommentaari kui eraldi
    # puhta abifunktsiooni `gemini_meta_snapshot(response,
    # server_content)`, kus `server_content` on PARAMEETER. Test
    # kontrollib ainult seda, mida ta tegelikult kaitseb: vastuste
    # tsüklis ei tohi neid välju lugeda enne omistamist.
    import ast as _ast
    fn = None
    for n in _ast.walk(_ast.parse(WS)):
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "send_to_client":
            fn = n
    assert fn is not None, "send_to_client puudub"
    kood = _ast.unparse(fn)
    i = kood.find("server_content = response.server_content")
    assert i != -1, "server_content omistamist ei leitud"
    for v in ("generation_complete", "interaction_status"):
        j = kood.find(v)
        assert j > i, f"{v} loetakse enne server_content omistamist"


# ---------------------------------------------------------------------------
# Vaikuse valvur — tuvastab seisnud mikrofoni ENNE Gemini 120 s piiri
# ---------------------------------------------------------------------------

@test("6. vaikuse valvur hoiatab 60 s ja lõpetab 100 s peal (enne Gemini 120 s)")
def t6():
    assert Watchdog is not None, "ClientSilenceWatchdog puudub täielikult"
    w = Watchdog(0.0)
    assert w.status(10.0) == "ok"
    assert w.status(59.0) == "ok"
    assert w.status(61.0) == "warn", "60 s peal ei hoiatatud"
    assert w.status(70.0) == "ok", "hoiatus kordub (teateujutus)"
    assert w.status(101.0) == "expire", "100 s peal ei lõpetatud kõnet"
    assert Watchdog.EXPIRE_AFTER < 120.0, \
        "lävend pole Gemini 120 s piirist allpool – 1008 jõuab ikka ette"


@test("7. heli saabumine nullib vaikuse valvuri")
def t7():
    assert Watchdog is not None, "ClientSilenceWatchdog puudub täielikult"
    w = Watchdog(0.0)
    assert w.status(61.0) == "warn"
    w.note_input(62.0)
    assert w.status(70.0) == "ok", "valvur ei nullistunud heli saabumisel"
    assert w.status(123.0) == "warn", "nullimise järel ei hoiata uuesti"


@test("8. valvur osaleb kõne lõpetamises (tiksuja on ootekomplektis)")
def t8():
    # Vana kood: asyncio.wait([client_task, gemini_task]) – tiksuja jäi välja,
    # seega tema otsus ei lõpetanud midagi.
    assert "silence_watchdog" in WS, "vaikuse valvurit ei kasutata handleris"
    assert re.search(r"asyncio\.wait\(\s*\[client_task,\s*gemini_task,\s*ticker_task\]", WS), \
        "ticker_task pole asyncio.wait komplektis – valvur ei saa kõnet lõpetada"
    assert "silence_watchdog.note_input" in WS, "valvurit ei toideta kliendi helist"


@test("15. mikrofoni kaadrit EI muudeta kunagi (kajavärav eemaldatud)")
def t15():
    """Kajavärav oli RMS-lävendil põhinev ja mõõtmine lükkas selle ümber:
    Peetri päris kõnes oli kaja 95. protsentiil 0,0092 ja kõne mediaan 0,0139 –
    jaotused kattuvad, eraldavat lävendit pole olemas. Värav sõi ~10 s kõnest
    ja Gemini ei saanud 46 s jooksul ühtegi sõna. Nüüd läheb iga kaader
    muutmata kujul edasi."""
    gate = HTML[HTML.find("liveProcessor.onaudioprocess"):]
    gate = gate[:gate.find("function runAudioVisualizer")]
    assert "echoSilence.buffer" not in gate, \
        "nullitud kaadrit saadetakse endiselt – kajavärav pole eemaldatud"
    assert "const gated" not in gate and "let gated" not in gate, \
        "väravaloogika on alles"
    assert "ECHO_GATE_RMS" not in gate, "lävendit rakendatakse endiselt"
    # ainus send peab olema tegelik mikrofoniheli
    assert gate.count("liveWs.send(") == 1, \
        f"mikrofonitees on {gate.count('liveWs.send(')} saatmiskohta, oodati 1"
    assert "liveWs.send(int16.buffer)" in gate, "päris heli ei saadeta"


@test("18. kajavastane töö jääb Gemini VAD-ile (server), mitte kliendile")
def t18():
    assert "realtime_input_config" in WS, "serveri VAD häälestus on kadunud"
    assert "START_SENSITIVITY_LOW" in WS, "madal kõnetundlikkus on kadunud"
    assert "silence_duration_ms" in WS, "vaikuse kestus on kadunud"
    # Klient ei tohi enam ise otsustada, mis on kaja ja mis kõne.
    assert "ECHO_ONSET_FACTOR" not in HTML, "kliendis on alles kaja heuristika"
    assert "echoFloor" not in HTML, "kliendis hinnatakse endiselt kajataset"


@test("19. helitasemete mõõtmine jääb alles (häälestuseks)")
def t19():
    gate = HTML[HTML.find("liveProcessor.onaudioprocess"):]
    gate = gate[:gate.find("function runAudioVisualizer")]
    assert "Math.sqrt" in gate, "RMS-i ei arvutata – tasemeid ei saa enam mõõta"
    assert "echoGateStats.rms.push" in gate, "kaja taset ei koguta"
    assert "echoGateStats.speech.push" in gate, "kõne taset ei koguta"
    assert "kaja mediaan" in HTML, "tasemete kokkuvõtet ei logita"


# ---------------------------------------------------------------------------
# Vahelesegamine (barge-in)
# ---------------------------------------------------------------------------

@test("9. server edastab Gemini 'interrupted' signaali kliendile")
def t9():
    assert 'getattr(server_content, "interrupted"' in WS, \
        "server_content.interrupted jääb lugemata – vahelesegamist ei tuvastata"
    idx = WS.find('getattr(server_content, "interrupted"')
    # Aken peab katma kogu käsitlusploki (logi + saatmine + oleku muutus),
    # mitte ainult esimesi ridu – muidu kukub test diagnostika lisamisel.
    nearby = WS[idx:WS.find("if server_content and server_content.model_turn", idx)]
    assert '"type": "interrupted"' in nearby, \
        "vahelesegamist ei edastata kliendile"
    assert "push_state" in nearby, "orb ei lähe vahelesegamisel kuulamisrežiimi"


@test("10. klient saab ajastatud heli tühistada (barge-in tegelikult vaigistab)")
def t10():
    assert "let liveSources" in HTML, \
        "ajastatud BufferSource'i viiteid ei hoita – heli ei saa peatada"
    assert "function stopLiveAudio" in HTML, "stopLiveAudio puudub"
    assert "liveSources.push(src)" in HTML, "allikaid ei lisata nimekirja"
    stop = HTML[HTML.find("function stopLiveAudio"):]
    stop = stop[:stop.find("function playLiveChunk")]
    assert ".stop()" in stop, "stopLiveAudio ei peata allikaid"
    # nextPlayTime tuleb kerida tagasi, et järgmine heli ei ajastuks vana
    # puhvri taha. Pehme vaibumise korral on sihtaeg vaibumise LÕPP (stopAt),
    # mitte praegune hetk – muidu kattuks uus heli vaibuva häälega.
    assert ("nextPlayTime = stopAt" in stop
            or "nextPlayTime = ctx.currentTime" in stop
            or "nextPlayTime = audioCtxOut.currentTime" in stop), \
        "nextPlayTime't ei kerita tagasi – järgmine heli ajastatakse vana puhvri taha"
    assert 'pkt.type === "interrupted"' in HTML, \
        "klient ei reageeri serveri interrupted-teatele"


@test("11. helikonteksti elustamine (ekraani kustumise juurpõhjus)")
def t11():
    assert "function reviveAudioContexts" in HTML, \
        "puudub AudioContexti elustamine – ekraani kustudes jääb mikrofon seisma"
    assert "startAudioWatchdog" in HTML, "puudub perioodiline helivalvur"
    assert 'visibilitychange' in HTML, "visibilitychange't ei kuulata"
    assert HTML.count("reviveAudioContexts()") >= 2, \
        "elustamist ei kutsuta mitmest kohast (valvur + nähtavus)"


@test("12. lõplik tõrge jõuab kasutajani (ei sure enam vaikselt)")
def t12():
    assert 'fatal_state' in WS, "lõpliku tõrke põhjust ei koguta"
    assert '"type": "call_ended"' in WS, "kasutajale ei öelda, miks kõne lõppes"
    assert 'pkt.type === "call_ended"' in HTML, "klient ei kuva kõne lõpetamise põhjust"


# ---------------------------------------------------------------------------
# POOLIKUD LAUSED — Maya katkestab iseenda kaja tõttu (33% voorudest)
# ---------------------------------------------------------------------------

@test("13. VAD kuuleb kiiret lühikest vastust (tundlikkus KÕRGE)")
def t13():
    assert "realtime_input_config" in WS, "realtime_input_config puudub"
    # LOW tundlikkus tegi Maya kurdiks: 07.11 logis oli KATKESTUSI 0, st
    # Peetri pealerääkimist ei tuvastatud kordagi.
    # Kontrollime OMISTUST, mitte paljast teksti – sõna LOW võib esineda
    # selgitavas kommentaaris.
    m = re.search(r"start_of_speech_sensitivity=types\.StartSensitivity\.(\w+)", WS)
    assert m, "start_of_speech_sensitivity't ei seata"
    assert m.group(1) == "START_SENSITIVITY_HIGH", \
        f"kõnetundlikkus on {m.group(1)} – Maya ei kuule kiiret vastust"
    # Eelpuhver peab olema piisavalt lühike, et lühike ütlus kuuldaks, kuid
    # piisavalt pikk, et köhatus ei tühistaks Maya vooru. Mõõdetud: 100 ms
    # andis 7 seletamata katkestust ja 5 tühja vooru; 300 ms tegi kurdiks.
    m = re.search(r"prefix_padding_ms=(\d+)", WS)
    assert m, "eelpuhvrit ei seata"
    v = int(m.group(1))
    assert 150 <= v <= 300, f"eelpuhver {v} ms on väljaspool mõõdetud töövahemikku"
    # Vooru LÕPU seaded jäävad: Peeter võib lause keskel pausi teha.
    assert "END_SENSITIVITY_LOW" in WS, "lõputundlikkus pole madal"
    assert "silence_duration_ms=800" in WS, "vaikusenõue on muutunud"
    assert "START_OF_ACTIVITY_INTERRUPTS" in WS, "vahelesegamine on keelatud"


@test("14. VAD seadistus on SDK puudumise suhtes turvaline")
def t14():
    idx = WS.find("vad_cfg = {}")
    assert idx != -1, "vad_cfg puudub"
    # Aken piiritletakse JÄRGMISE koodilõiguga, mitte fikseeritud pikkusega –
    # muidu kukub test iga kord, kui kommentaari juurde kirjutatakse.
    block = WS[idx:WS.find("session_voice = voice_for_persona", idx)]
    assert 'hasattr(types, "RealtimeInputConfig")' in block, \
        "puudub SDK kontroll – vanem google-genai kukub importimisel läbi"
    assert "_lc_fields" in block, "ei kontrollita, kas LiveConnectConfig võtab selle välja vastu"
    assert "except Exception" in block, "seadistus pole try/except'iga kaitstud"
    assert "**vad_cfg," in WS, "vad_cfg't ei anta LiveConnectConfig'ile üldse edasi"


@test("16. poolik lause jõuab logisse (varem ei jätnud jälge)")
def t16():
    assert "turn_stats" in WS, "vooru statistika puudub"
    assert "POOLIKU lausega" in WS, "poolikut lauset ei logita"
    assert "turn_complete_reason" in WS, "vooru lõpetamise põhjust ei logita"
    assert "LIVE WS KATKESTUS" in WS, "katkestust ei logita koos pooleli jäänud tekstiga"


@test("17. poolikuse tuvastus loeb lausemärke õigesti")
def t17():
    # Kordab serveri loogikat: tail not in ".!?…:;")
    enders = ".!?…:;”)"
    for ok_text in ["Mine perse!", "Kas sa ei saa aru?", "Ma tahan, et sa austaksid mind.",
                    "Aga samas…"]:
        assert ok_text[-1] in enders, f"terve lause loeti poolikuks: {ok_text!r}"
    for bad_text in ["Kas sa igatsed", "Mis kuradi mõttes ma ei", "Ja nüüd keskendu", "Ära",
                     "See oleks", "Siis võtaksin"]:
        assert bad_text[-1] not in enders, f"poolik lause loeti terveks: {bad_text!r}"


# ---------------------------------------------------------------------------
# REGRESSIOON 07.11: kajavärav jäi kinni ja Maya jäi kurdiks
# Tootmises 13:09:21-13:10:39 (78 s) ei jõudnud serverisse ühtegi sõna,
# kuigi baite tuli – klient saatis ainult nullitud kaadreid.
# ---------------------------------------------------------------------------

@test("20. serveri olek 'listening' nullib kõnelemise lipu")
def t20():
    # Värav on eemaldatud, kuid isSpeaking juhib endiselt liidese olekut.
    # Lipp peab vooru lõpus kindlasti nullistuma.
    assert 'pkt.state === "listening"' in HTML, \
        "serveri kuulamisolekut ei käsitleta"
    blokk = HTML[HTML.find('pkt.state === "listening"'):][:200]
    assert "isSpeaking = false" in blokk, blokk


@test("21. server tuvastab DIGITAALSE vaikuse (nullitud kaadrid)")
def t21():
    assert "SILENT_AUDIO_WARN_AFTER" in WS, "serveril puudub digitaalse vaikuse lävend"
    assert "audible=any(msg[" in WS, "vaikseid kaadreid ei eristata kuuldavatest"
    assert "läbinisti" in WS, "digitaalse vaikuse hoiatus puudub"


@test("22. vaikuse valvur eristab vaikset kaadrit kuuldavast")
def t22():
    assert Watchdog is not None, "ClientSilenceWatchdog puudub"
    w = Watchdog(0.0)
    # kaadreid tuleb, aga kõik vaiksed -> ülemine valvur rahul, vaikuse oma hoiatab
    for t in range(1, 40):
        w.note_input(float(t), audible=False)
    assert w.status(39.0) == "ok", "ühenduse valvur andis valehäire (baite ju tuli)"
    assert w.silent_audio_status(39.0) == "warn", \
        "digitaalset vaikust ei tuvastatud – täpselt see jäi 07.11 märkamata"
    assert w.silent_audio_status(40.0) == "ok", "hoiatus kordub (teateujutus)"
    # kuuldav kaader nullib
    w.note_input(41.0, audible=True)
    assert w.silent_audio_status(50.0) == "ok", "kuuldav heli ei nullinud loendurit"
    assert w.silent_audio_status(75.0) == "warn", "pärast nullimist ei hoiata uuesti"


# ---------------------------------------------------------------------------
# REGRESSIOON 07.11 (2): küsimusi pidi kordama + helinivoo seisis
# ---------------------------------------------------------------------------

@test("23. helinivoo tsükkel ei sure enne isSessionActive seadmist")
def t23():
    draw = HTML[HTML.find("function runAudioVisualizer"):]
    draw = draw[:draw.find("runAudioVisualizer();")]
    # Varem: `if (!isSessionActive) { ...; return; }` ENNE rAF-i -> tsükkel suri,
    # sest kõnenupp seab isSessionActive alles pärast await initAudio().
    i_raf = draw.find("requestAnimationFrame(draw)")
    i_sess = draw.find("if (!isSessionActive)")
    assert i_raf != -1 and i_sess != -1, "joonistustsüklit ei leitud"
    assert i_raf < i_sess, \
        "isSessionActive kontroll on enne requestAnimationFrame'i – tsükkel sureb"
    assert 'audioCtxIn.state === "closed"' in draw, \
        "tsükkel ei lõpe heliahela sulgemisel (jääb igavesti jooksma)"


@test("24. orbi tase käib CSS-muutuja kaudu (animatsioon ei kirjuta üle)")
def t24():
    assert "orbElem.style.transform" not in HTML, \
        "orbi tase seatakse inline transform'iga, mille CSS-animatsioon üle kirjutab"
    assert 'setProperty("--lvl"' in HTML, "taset ei anta CSS-muutujana"
    assert HTML.count("var(--lvl") >= 3, "keyframe'id ei kasuta taseme muutujat"


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    label = "VANA (refaktoorimise-eelne)" if VANA else "PARANDATUD"
    print(f"FAAS C TAASTOOTMISTESTID – {label}")
    print(f"  {WS_PATH.name}")
    print(f"  {HTML_PATH.name}")
    print("=" * 72)
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, err in results:
        print(f"  {'LÄBITUD' if ok else 'KUKKUS '}  {name}")
        if not ok:
            print(f"            -> {err}")
    print("=" * 72)
    print(f"{passed}/{len(results)} läbitud")
    sys.exit(0 if passed == len(results) else 1)

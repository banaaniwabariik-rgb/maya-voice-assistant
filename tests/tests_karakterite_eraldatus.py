#!/usr/bin/env python3
"""Karakterite eraldatus ja hääletoonid.

Taust: 2026-11-07 teatas Jaan, et kõigil karakteritel on tekkinud ühine
iseloom. Tootmislogi kinnitas: tema KOHANDATUD juhis liideti iga karakteri
prompti lõppu (asjalik 702 -> 1087, filosoof 902 -> 1287, zen 1147 -> 1532).

Need testid lukustavad reegli: iga karakter kannab AINULT oma iseloomu ja
oma naishäält. Kohandatud juhis kuulub ainult nupule KOHANDATUD.
"""

import re
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "server"))
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import persona_registry as R  # noqa: E402

HTML = (ROOT / "android" / "app" / "src" / "main" / "assets" / "index.html").read_text(encoding="utf-8")
WS = (ROOT / "server" / "live_maya_ws.py").read_text(encoding="utf-8")

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


# Peetri päris juhis logist (lühendatud) – just see levis kõigile karakteritele.
NAIDIS_JUHIS = ("Sa OLED väga emotsionaalne ja sa võid ka vihastada kui midagi ei meeldi, "
               "eriti kui jutt kordub. Sa OLED entusiastlik ja OLED jutukas")


@test("1. kohandatud juhis EI muuda ühtegi teist karakterit")
def t1():
    rikutud = []
    for p in R.get_all_personas():
        if p.id == "custom":
            continue
        puhas = R.build_voice_prompt(p.id, "")
        juhisega = R.build_voice_prompt(p.id, NAIDIS_JUHIS)
        if puhas != juhisega:
            rikutud.append(f"{p.id} ({len(puhas)} -> {len(juhisega)})")
    assert not rikutud, "juhis lekkis karakteritesse: " + ", ".join(rikutud)


@test("2. KOHANDATUD karakter saab juhise endiselt kätte")
def t2():
    out = R.build_voice_prompt("custom", NAIDIS_JUHIS)
    assert "KASUTAJA KOHANDATUD ROLL JA JUHEND:" in out, "custom ei saa juhist"
    assert NAIDIS_JUHIS in out, "juhise sisu puudub"
    tyhi = R.build_voice_prompt("custom", "")
    assert tyhi.endswith("Ole vaba, kohalolev ja avatud vestluspartner."), \
        "tühja juhise varutekst puudub"


@test("3. iga karakteri prompt on unikaalne (ükski ei kattu teisega)")
def t3():
    nahtud = {}
    for p in R.get_all_personas():
        t = R.build_voice_prompt(p.id, "")
        if t in nahtud:
            raise AssertionError(f"'{p.id}' ja '{nahtud[t]}' on identsed promptid")
        nahtud[t] = p.id
    assert len(nahtud) == 10, f"unikaalseid promptte {len(nahtud)}, oodati 10"


@test("4. kohandatud juhis EI paisuta ühtegi teist karakterit")
def t4():
    """AVALIKU VERSIOONI KOHANDUS.

    Algne test lukustas ÜHEKSA karakteri prompti pikkused absoluutsete
    numbritega (nt asjalik = 702). Need numbrid kirjeldasid
    originaalpaigalduse ISIKLIKKE viipasid, mida avalikus koopias ei
    ole. Pikkuse asemel kontrollime nüüd seda OMADUST, mille pärast
    test üldse kirjutati: 2026-11-07 regressioonis liideti kasutaja
    kohandatud juhis IGA karakteri prompti lõppu ja kõik karakterid
    hakkasid kandma sama iseloomu.

    See kontroll on sisust sõltumatu ja töötab ka siis, kui paigaldaja
    kirjutab oma karakterid täiesti ümber.
    """
    vead = []
    for pid in R.voice_persona_ids():
        ilma = R.build_voice_prompt(pid, "")
        juhisega = R.build_voice_prompt(pid, NAIDIS_JUHIS)
        if pid == "custom":
            # AINUS karakter, kes juhise külge VÕTABKI.
            if juhisega == ilma:
                vead.append(f"{pid}: kohandatud juhis EI jõudnud kohale")
            if NAIDIS_JUHIS not in juhisega:
                vead.append(f"{pid}: juhise tekst puudub")
        else:
            if juhisega != ilma:
                vead.append(f"{pid}: juhis paisutas prompti "
                            f"{len(ilma)} -> {len(juhisega)}")
            if NAIDIS_JUHIS in juhisega:
                vead.append(f"{pid}: KOHANDATUD JUHIS LEKKIS SISSE")
    assert not vead, "; ".join(vead)


@test("5. iga karakter on naishääl ja hääled on karakteripõhised")
def t5():
    oodatud = {
        "asjalik": "Kore", "sober": "Aoede", "sarkastiline": "Zephyr",
        "mentor": "Kore", "filosoof": "Leda", "treener": "Zephyr",
        "zen": "Leda", "romantiline": "Aoede", "custom": "Aoede",
        "singer": "Aoede",
    }
    for pid, haal in oodatud.items():
        tegelik = R.resolve_voice(pid)
        assert tegelik == haal, f"{pid}: hääl {tegelik}, oodati {haal}"
        assert tegelik in R.FEMALE_VOICES, f"{pid}: {tegelik} pole naishääl"
    # Aliased pärivad sihtkarakteri hääle.
    for alias, sihtmark in R.ALIASES.items():
        assert R.resolve_voice(alias) == R.resolve_voice(sihtmark), \
            f"alias {alias} annab muu hääle kui {sihtmark}"


@test("6. hääled ei ole kõik ühesugused (toonid on eristatavad)")
def t6():
    haaled = {R.resolve_voice(p.id) for p in R.get_all_personas()}
    assert len(haaled) >= 3, f"kasutusel ainult {len(haaled)} hääletooni: {haaled}"
    assert haaled <= R.FEMALE_VOICES, f"mõni hääl pole naishääl: {haaled - R.FEMALE_VOICES}"


@test("7. laulureeglid jäävad AINULT lauljale")
def t7():
    laulja = R.build_voice_prompt("singer", "")
    assert "LAUL" in laulja.upper(), "lauljal puuduvad laulureeglid"
    for p in R.get_all_personas():
        if p.id == "singer":
            continue
        t = R.build_voice_prompt(p.id, "")
        assert "SILBI VENITAMINE" not in t.upper(), f"{p.id} sai laulureeglid"


@test("8. klient saadab kohandatud juhise AINULT custom karakteriga")
def t8():
    assert 'selectedPersona === "custom"' in HTML, \
        "klient ei kontrolli karakterit enne juhise saatmist (WS)"
    ws_blokk = HTML[HTML.find("const personaParam"):HTML.find("liveWs.binaryType")]
    assert "customParam" in ws_blokk and '? encodeURIComponent' in ws_blokk, \
        "WS URL-is puudub tingimuslik juhis"
    assert ': ""' in ws_blokk, "mitte-custom karakteri puhul ei saadeta tühja"
    # HTTP rada sama reegel, mõlemas kohas.
    assert HTML.count("selectedPersona === 'custom' ? customPromptVal : ''") == 2, \
        "HTTP rada saadab juhist endiselt tingimusteta"


@test("9. server logib eiratud juhise (ei vaiki maha)")
def t9():
    assert "EI kehti karakterile" in WS, \
        "server ei logi, et juhis eirati – viga jääks jälle nähtamatuks"
    assert "Kasutaja kohandatud juhis lisatud karakterile" not in WS, \
        "vana eksitav logirida on alles (väitis liitmist)"


@test("10. tekstirada ja häälerada käituvad nüüd ühtemoodi")
def t10():
    wm = (ROOT / "server" / "web_maya.py").read_text(encoding="utf-8")
    assert wm.count('if active_persona == "custom" and custom_prompt') == 2, \
        "tekstiraja reegel on muutunud"
    # Hääl: mitte-custom ei saa juhist; tekst: sama.
    assert R.build_voice_prompt("asjalik", NAIDIS_JUHIS) == R.build_voice_prompt("asjalik", ""), \
        "häälerada erineb tekstirajast"


if __name__ == "__main__":
    print("KARAKTERITE ERALDATUS JA HÄÄLETOONID")
    print("=" * 70)
    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, err in results:
        print(f"  {'LÄBITUD' if ok else 'KUKKUS '}  {name}")
        if not ok:
            print(f"            -> {err}")
    print("=" * 70)
    print(f"{passed}/{len(results)} läbitud")
    sys.exit(0 if passed == len(results) else 1)

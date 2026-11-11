## Mida see muudab

<!-- Üks-kaks lauset. Mis probleemi see lahendab? -->

Seotud issue: #

## Mõõdetud tõend

<!-- See projekt on ehitatud mõõtmiste peale. Kui väidad, et midagi
     oli katki või aeglane, lisa NUMBER: logirida, ajatempel,
     testitulemus, enne/pärast võrdlus. -->

## Kontroll-nimekiri

- [ ] Testid jooksevad läbi: `for f in tests/tests_*.py; do python3 "$f"; done`
- [ ] Uus funktsionaalsus on testiga kaetud
- [ ] `scripts/kontrolli_privaatsust.sh` ei leia midagi
- [ ] Ei ühtegi API võtit, parooli, tokenit, IP-aadressi, isikuandmeid
      ega andmebaasifaili
- [ ] Kasutajale nähtav tekst on eesti keeles
- [ ] Kommentaarid ütlevad **MIKS**, mitte ainult mis
- [ ] Ei nõrgendanud ühtegi olemasolevat testi

## Kui puudutasin tundlikke kohti, siis põhjendan eraldi

- [ ] **Gemini Live konfiguratsioon** (mudel, VAD, MIME, turvaseaded,
      helivorming) — need on meelega lukus
- [ ] **Autentimine või kasutajate eraldatus** (`server/auth.py`,
      `config.db_tee()`) — vt docs/TURVALISUS.md
- [ ] **Vestluse elutsükkel** (`conversation_flow.py`) — taaste,
      omaalgatus, kasutaja prioriteet
- [ ] **Karakteri algatatud kõne** (SSE, `CallWatcherService`)
- [ ] **Karakterite definitsioonid** (`persona_registry.py`)

Põhjendus:

<!-- Miks oli muudatus vajalik ja mis tõend seda toetab? -->

## Testitud

- [ ] Backend (Python versioon: ___ )
- [ ] Androidi APK ehitatud
- [ ] Päris seadmes testitud (seade ja Androidi versioon: ___ )
- [ ] Päris Gemini Live kõne tehtud

<!-- Kui mõni on testimata, ütle see välja. Ära väida, et
     integratsioonitest läbis, kui jooksutasid jäljendit. -->

# Arendus ja testimine

## Keskkond

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
cp .env.example .env
python3 server/init_db.py
```

## Testide jooksutamine

```bash
# kõik
for f in tests/tests_*.py; do echo "== $f"; python3 "$f"; done

# üksik
python3 tests/tests_vestluse_elutsykkel.py

# üks testiklass või -meetod (unittest-põhistes)
python3 tests/tests_asunkroonne_elutsykkel.py TestSulgemine
```

Mõned failid kasutavad `unittest`-i, mõned oma kerget `@test`
dekoraatorit. Mõlemad käivituvad otse `python3`-ga ja tagastavad
veakoodi.

## Testide liigid — ära aja neid segi

| Liik | Mida tõestab | Mida EI tõesta |
|---|---|---|
| **Ühiktest** | puhas loogika: `conversation_flow`, mälu, privaatsus | et tootmiskood seda loogikat kasutab |
| **Staatiline kontroll** | AST/tekst: tootmisfailis ON kaitse olemas | et see käitusajal töötab |
| **Jäljendatud asünkroonne** | taskide elutsükkel, võidujooksud, tühistamine, lukud | **Gemini tegelikku käitumist** |
| **Päris Gemini Live** | — | **neid ei ole.** Vajab võtit ja maksab raha |

> Kui jooksutasid jäljendit, **ära kirjuta**, et integratsioonitest
> läbis. Jäljendatud testide päises on see hoiatus eraldi kirjas.

## Sõltuvuste kontroll

Mis on tegelikult kohustuslik (imporditakse mooduli tasemel):

```bash
python3 - <<'PY'
import ast, pathlib
VALISED = {"requests","trafilatura","pypdf","youtube_transcript_api",
           "groq","pyrogram","certifi","fastapi","uvicorn","google"}
for f in sorted(pathlib.Path("server").glob("*.py")):
    puu = ast.parse(f.read_text(encoding="utf-8"))
    tase0 = set()
    for n in ast.walk(puu):
        if isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset == 0:
            nimed = ([a.name.split(".")[0] for a in n.names]
                     if isinstance(n, ast.Import)
                     else [(n.module or "").split(".")[0]])
            tase0 |= {x for x in nimed if x in VALISED}
    if tase0:
        print(f.name, sorted(tase0))
PY
```

## Autentimise testid

```bash
python3 tests/tests_autentimine.py                    # kõik 43
python3 tests/tests_autentimine.py TestEraldatus      # ainult eraldatus
```

Need katavad: paroolide räsimise, tokenite elutsükli, kasutajate
eraldatuse (üks ei näe teise andmeid), HTTP-kihi (FastAPI
`TestClient`), AST-kontrolli selle kohta, et **iga** `/api` otspunkt
nõuab autentimist, ja kiiruspiirangu.

`tests_autentimine.py::test_40` on kõige olulisem: see käib AST-iga
üle `web_maya.py` ja kukub läbi, kui mõni otspunkt jääb ilma
`noua_kasutaja`/`noua_admin` sõltuvust. **Uue otspunkti lisamisel
jookseb see test automaatselt läbi kukkuma, kuni lisad autentimise.**

## Privaatsuse kontroll enne commit'i

```bash
scripts/kontrolli_privaatsust.sh
```

Otsib API võtmete mustreid, IP-aadresse, andmebaasifaile, `.env`
faile ja sessioonifaile. **Jooksuta see enne iga pull request'i.**

## Kodeerimistavad

1. **Kommentaar ütleb MIKS, mitte MIS.** Koodis on palju
   „MÕÕDETUD VIGA: …" selgitusi — need on tahtlikud ja väärtuslikud.
   Ära koristata neid ära.
2. **Mõõda, ära oleta.** Kui väidad, et midagi on katki, lisa number.
3. **Eesti keel** kasutajale nähtavas tekstis ja uutes kommentaarides.
   Vanem kood on osaliselt inglise keeles — seda ei pea tõlkima.
4. **Ära nõrgenda testi**, et roheline saada.
5. **Gemini Live konfiguratsioon on lukus.** Mudel, VAD, MIME,
   turvaseaded — nende muutmine nõuab eraldi põhjendust.

## Vooru diagnostika logis

| Rida | Mida ütleb |
|---|---|
| `[AJAJOON voor #N]` | etapiviisiline latents: kasutaja kõne → voor → esimene heli |
| `[VOOG]` | olekumasina otsus: taaste, omaalgatus, eelarve |
| `[VOOG TAASTE n/12]` | taastekatse number |
| `[VOOG OMAALGATUS n/m]` | omaalgatus ja eelarve |
| `[GEMINI META]` | Gemini lõpetamise metaandmed (`turn_complete_reason`, tokenid) |
| `[KAAMERA]` | kaadrite arv ja baidisuurus (pimeduse mõõdik) |
| `[TAASESITUS]` | kliendi taasesituse telemeetria: `kuulmata_s`, `underruns` |
| `[DIAG voor #N]` | vooru täielik seisund |

## Teadaolevad lahtised kohad

Head esimesed panused:

- **Pöördproksi oma autentimine.** Klient saadab juba
  `Authorization: Bearer <token>` MAYA enda autentimise jaoks, nii et
  pöördproksi Basic-autentimine satuks sellega vastuollu. Kui tahad
  proksi tasandil lisakaitset, kasuta mTLS-i või IP-piirangut.
- **Kulumudel ja püstkaadrid.** `LiveCostTracker` eeldab 258 tokenit
  kaadri kohta, aga püstpaigutuses kaader (768×1024) läheb kahe
  768×768 ploki eest.
- **Kliendi taasesituse telemeetria** on olemas, aga `[AJAJOON]` rida
  trükitakse enne aruande saabumist, nii et väli on alati „teadmata".
- **Seadmehaldus puudub.** Kõneteade jõuab fan-out'i kaudu kõigi sama
  konto seadmeteni (vt [MITU_SEADET.md](MITU_SEADET.md)), aga seadmete
  nimekirja, nimetamist ega valikulist väljalülitamist ei ole.
- **`agent_memory.db`** oli originaalis olemas, aga ükski moodul seda ei
  kasuta (pärand vanemast Telegrami-botist). Avalikus koopias ei ole.
- **HTTPS puudub.** Autentimine kaitseb volitamata kasutaja eest,
  mitte pealtkuulamise eest. Pöördproksi juhend on
  [TURVALISUS.md](TURVALISUS.md)-s, aga sisseehitatud TLS-i ei ole.
- **FCM / APNs puudub.** Kõneteated käivad SSE kaudu. Analüüs ja
  juhend, kui keegi tahab FCM-i lisada: [KONEALGATUS.md](KONEALGATUS.md).
- **Kiiruspiirang on protsessipõhine.** `workers > 1` korrutab piirangu.

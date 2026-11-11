# MAYA — eestikeelne häälassistent, kes helistab ise

MAYA on eestikeelne reaalajas häälassistent. Ta ei ole nupuvajutusega
küsimuste-vastuste masin: ta räägib loomuliku kõne rütmis, võtab
vaikuse järel ise sõna, jätkab automaatselt lauset, mis pooleli jäi,
ja **helistab sulle ise telefonile**, kui tal on midagi öelda.

Häälemootor on **Google Gemini Live API** (natiivne heli, mitte
kõnesüntees teksti pealt). Backend on Python/FastAPI, klient on
Androidi rakendus.

> **See on avalik koopia.** Projekt sündis ühe inimese isikliku
> assistendina ja on siia üle toodud nii, et kogu isiklik sisu,
> võtmed, serveriaadressid ja vestlusajalugu on välja jäetud. Sa
> paigaldad oma eksemplari, oma võtmetega ja oma karakteritega.

---

## Mida MAYA teeb

| | |
|---|---|
| **Reaalajas häälvestlus** | Gemini Live natiivheli, eesti keel, katkestamine igal hetkel |
| **Karakterid** | 10 eraldi iseloomu oma hääle ja temperamendiga; igaühel oma algatustase |
| **Kohandatud karakter** | kirjutad ise juhise ja Maya võtab selle rolli |
| **Autonoomne jätkamine** | pärast loomulikku pausi võtab Maya ise sõna, karakteripõhise ajastusega |
| **Automaatne taaste** | kui lause jääb pooleli, jätkab ta samast kohast ilma, et peaksid küsima |
| **Kasutaja prioriteet** | sinu kõne katkestab kõik — omaalgatuse, taaste, pooleliolevad päringud |
| **Pikaajaline mälu** | faktide eraldamine vestlusest, FTS5-otsing, eesti keele morfoloogia |
| **Karakteri algatatud kõne** | Maya helistab telefonile ja alustab vestlust ise |
| **Meeldetuletused ja kalender** | korduvad meeldetuletused, mis saabuvad kõnena |
| **Kaamera** | Maya näeb kaamerapilti ja kommenteerib seda |
| **Laulmine** | laulusõnade otsing, helistik ja tempo, rida-realt esitus |
| **Igapäevased tööriistad** | veebiotsing, lehtede ja PDF-ide lugemine, YouTube'i subtiitrid, e-post |

---

## Kiire algus

```bash
git clone <sinu-repo-aadress> maya
cd maya

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt

cp .env.example .env                 # täida GEMINI_API_KEY
python3 server/init_db.py            # loo tühi andmebaas

cd server && python3 web_maya.py     # server käivitub pordil 8000
```

Seejärel ehita Androidi rakendus — vt **[docs/ANDROID.md](docs/ANDROID.md)**.

Täielik juhend: **[docs/PAIGALDUS.md](docs/PAIGALDUS.md)**

---

## Mida sul on vaja

| | |
|---|---|
| **Google Gemini API võti** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Live API on tasuline — vt [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) |
| **Python 3.11+** | testitud 3.13 ja 3.14 peal |
| **Androidi telefon** | Android 8.0+ (API 26). Kõnefunktsioon vajab päris seadet |
| **Server** | võib olla sinu arvuti, koduserver või pilv. Vt turvahoiatust allpool |

Valikuline: Groqi võti (tekstivestlus), Tavily (veebiotsing), Gmaili
rakenduse parool (e-post).

---

## Dokumentatsioon

| Fail | Sisu |
|---|---|
| [docs/PAIGALDUS.md](docs/PAIGALDUS.md) | samm-sammult paigaldus nullist |
| [docs/SEADISTAMINE.md](docs/SEADISTAMINE.md) | kõik keskkonnamuutujad ja seaded |
| [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) | Gemini Live seadistus, mudel, hinnad |
| [docs/ANDROID.md](docs/ANDROID.md) | Androidi rakenduse ehitamine ja ühendamine |
| [docs/KONEALGATUS.md](docs/KONEALGATUS.md) | kuidas karakteri algatatud kõne töötab |
| [docs/KARAKTERID.md](docs/KARAKTERID.md) | oma karakterite kirjutamine |
| [docs/ARHITEKTUUR.md](docs/ARHITEKTUUR.md) | moodulid, vestluse elutsükkel, mälu |
| [docs/ARENDUS.md](docs/ARENDUS.md) | testid, kodeerimistavad, panustamine |
| [CONTRIBUTING.md](CONTRIBUTING.md) | kuidas panustada |
| [SECURITY.md](SECURITY.md) | turvaaukude teatamine |

---

## ⚠️ Turvahoiatus — loe see läbi

MAYA backendil **ei ole autentimist**. See on teadlik disainivalik:
originaalpaigaldus elas privaatvõrgus (Tailscale), kus serverini
pääses ainult omaniku enda telefon.

**Ära pane seda serverit avalikku internetti ilma kaitset.** Kui teed
seda, saab igaüks sinu Gemini võtmega kõnesid teha, sinu mälu lugeda
ja sulle helistada.

Soovitatud variandid:

1. **Privaatvõrk** (Tailscale, WireGuard, ZeroTier) — lihtsaim ja
   ühtlasi see, mida originaalpaigaldus kasutab.
2. **Pöördproksi** (nginx/Caddy) HTTPS-i ja autentimisega.
3. **Ainult kohtvõrk** (`MAYA_HOST=127.0.0.1` + SSH-tunnel).

Vt [docs/SEADISTAMINE.md](docs/SEADISTAMINE.md) jaotist „Turvalisus".

---

## Mis siin EI ole

Aususe huvides — avalik koopia **ei sisalda**:

- ühtegi API võtit, parooli ega pääsutõendit;
- ühtegi andmebaasi: mälufaktid, meeldetuletused ja vestlusarhiiv on tühjad;
- originaalpaigalduse isiklikke karakteriviipasid — karakterid on
  **üldised näited**, mille sa ise üle kirjutad;
- serveriaadresse, kasutajanimesid ega teid;
- Androidi allkirjastamisvõtmeid;
- algse projekti Git-ajalugu.

Samuti ei ole kaasas päris seadmes kontrollitud Androidi APK-d — sa
ehitad selle ise.

---

## Litsents

MIT — vt [LICENSE](LICENSE).

MIT litsents katab selle projekti koodi. Gemini Live kasutamisel
kehtivad Google'i enda tingimused ja hinnakiri.

---

## Panustamine

Paranduste ja ettepanekute jaoks on pull request'id teretulnud —
vt [CONTRIBUTING.md](CONTRIBUTING.md).

**Oluline märkus:** see avalik projekt on sõltumatu. Ükski avalik
panus ei jõua automaatselt ühegi eraparalduse sisse. Iga MAYA
paigaldaja otsustab ise, mida ta oma eksemplari üle kannab.

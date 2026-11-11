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
| **Mitu kasutajat** | igal kasutajal oma konto ja oma eraldi andmebaas |

---

## Kiire algus

```bash
git clone <sinu-repo-aadress> maya
cd maya

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt

cp .env.example .env                 # täida GEMINI_API_KEY

./kaivita.sh                         # kontrollib eeldused, loob
                                     # andmebaasi ja käivitab serveri
```

`kaivita.sh` ütleb ka välja aadressi, mille Androidi APK-sse panna.
Ainult aadressi küsimiseks: `./kaivita.sh --ip`

Seejärel loo esimene konto — **esimene konto saab admin-õigused**:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"sinu_nimi","password":"vahemalt_10_margi_pikk_parool"}'
```

Või tee seda Androidi rakenduse sisselogimisekraanil („Loo uus konto").

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
| [docs/TURVALISUS.md](docs/TURVALISUS.md) | autentimine, kasutajate eraldatus, mida kaitse katab |
| [docs/MITU_SEADET.md](docs/MITU_SEADET.md) | mitu telefoni ja mitu kontot – oodatav käitumine |
| [valjalase/PAIGALDA.md](valjalase/PAIGALDA.md) | **testimine päris telefonis: APK, käivitus, kontroll-nimekiri** |
| [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md) | sõltuvused ja nende litsentsid |
| [docs/IOS.md](docs/IOS.md) | iOS kui tuleviku platvorm – arhitektuursed kaalutlused |
| [docs/ARENDUS.md](docs/ARENDUS.md) | testid, kodeerimistavad, panustamine |
| [CONTRIBUTING.md](CONTRIBUTING.md) | kuidas panustada |
| [SECURITY.md](SECURITY.md) | turvaaukude teatamine |

---

## Kohalik testimine vs avalik juurutus

Need kaks on **täiesti erinevad olukorrad** ja neil on erinevad
nõuded. Ära aja segi.

| | **Kohalik testimine** | **Avalik internet** |
|---|---|---|
| Kus server on | sinu arvuti või koduserver | VPS, pilv, avalik IP |
| Võrk | sama Wi-Fi või privaatvõrk (Tailscale/WireGuard) | avatud internet |
| Protokoll | **HTTP on OK** | **HTTPS/WSS on KOHUSTUSLIK** |
| Autentimine | piisab | piisab, aga HTTPS peab olema peal |
| Registreerimine | `MAYA_ALLOW_REGISTRATION=1` | **`=0` või kutsekood** |
| Pöördproksi | ei vaja | **nginx/Caddy TLS-iga** |
| Käivitus | `./kaivita.sh` | systemd + pöördproksi |
| Juhend | [valjalase/PAIGALDA.md](valjalase/PAIGALDA.md) | [docs/TURVALISUS.md](docs/TURVALISUS.md) |

**Alusta kohalikust testimisest.** Avalikku internetti mine alles
siis, kui HTTPS on paigas — vastasel juhul liigub sinu kõne, mälu ja
autentimistoken avatekstina.

---

## ⚠️ Turvahoiatus — loe see läbi

MAYA backendil **ON autentimine**: kõik `/api` otspunktid, SSE-vool
ja Gemini Live WebSocket nõuavad kehtivat tokenit. Iga kasutaja andmed
(mälu, meeldetuletused, vestlused, seaded) elavad **eraldi
andmebaasis**, nii et üks kasutaja ei saa teise andmeid näha ega talle
helistada.

**Aga liiklus on endiselt HTTP, mitte HTTPS.** Autentimine kaitseb
volitamata kasutaja eest, mitte pealtkuulamise eest. Seega:

1. **Privaatvõrk** (Tailscale, WireGuard, ZeroTier) — lihtsaim ja
   soovitatud.
2. **Pöördproksi** (nginx/Caddy) HTTPS-iga, kui server on avalik.
3. **Ainult kohtvõrk** (`MAYA_HOST=127.0.0.1` + SSH-tunnel).

Täielik ülevaade: **[docs/TURVALISUS.md](docs/TURVALISUS.md)**.

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

## ⚠️ Litsents on valimata

Sellel väljalaskekandidaadil **ei ole veel litsentsi** — vt
[LITSENTS_OOTEL.md](LITSENTS_OOTEL.md). Ilma litsentsifailita kehtib
vaikimisi „kõik õigused kaitstud", seega **hoidlat ei tohi veel
avaldada** ja keegi ei saa koodi seaduslikult kasutada.

Sõltuvused ei piira valikut: kõik kohustuslikud on lubavate
litsentside all (MIT/BSD/Apache-2.0), ühtegi GPL/AGPL sõltuvust ei ole
— vt [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

Gemini Live kasutamisel kehtivad alati Google'i enda tingimused ja
hinnakiri, sõltumata sellest, millise litsentsi sa valid.

---

## Panustamine

Paranduste ja ettepanekute jaoks on pull request'id teretulnud —
vt [CONTRIBUTING.md](CONTRIBUTING.md).

**Oluline märkus:** see avalik projekt on sõltumatu. Ükski avalik
panus ei jõua automaatselt ühegi eraparalduse sisse. Iga MAYA
paigaldaja otsustab ise, mida ta oma eksemplari üle kannab.

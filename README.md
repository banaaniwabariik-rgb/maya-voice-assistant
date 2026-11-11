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
>
> **MAYA ei ole teenus.** GitHubis on ainult lähtekood ja Androidi
> APK – ükski MAYA server siin ei jookse. Sina käivitad backendi oma
> arvutis või serveris, oma Gemini API võtmega, ja telefon ühendub
> SINU serveriga. Rakendus küsib selle aadressi esimesel käivitusel.

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

**1. Backend tööle:**

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

`kaivita.sh` ütleb välja aadressi, mille telefonis sisestad.
Ainult aadressi küsimiseks: `./kaivita.sh --ip`

**2. Androidi rakendus telefoni** — võta `maya-universal.apk`
**Releases** lehelt või ehita ise (`cd android && ./gradlew
assembleDebug`). APK-s **ei ole ühtegi serveriaadressi** ega võtit,
seega töötab see iga MAYA paigaldusega.

**3. Serveri aadress rakenduses:** esimesel käivitusel tuleb
seadistusekraan ette. Sisesta oma backendi aadress (nt
`http://192.168.1.50:8000` – pane sinna OMA IP), vajuta **„Testi
ühendust"** ja siis **„Salvesta ja jätka"**. Hiljem saab muuta:
seaded → „Minu MAYA server".

**4. Esimene konto** — **esimene konto saab admin-õigused**. Kõige
lihtsam on seda teha telefonis („Loo uus konto"). Käsurealt:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"sinu_nimi","password":"vahemalt_10_margi_pikk_parool"}'
```

Täielik juhend: **[docs/PAIGALDUS.md](docs/PAIGALDUS.md)** ·
Androidi detailid: **[docs/ANDROID.md](docs/ANDROID.md)**

---

## Mida sul on vaja

| | |
|---|---|
| **Google Gemini API võti** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Live API on tasuline — vt [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) |
| **Python 3.11+** | testitud 3.13 ja 3.14 peal |
| **Androidi telefon** | Android 8.0+ (API 26). Kõnefunktsioon vajab päris seadet |
| **Server** | võib olla sinu arvuti, koduserver või pilv. Vt turvahoiatust allpool |

**Gemini API võti jääb ainult serverisse.** Androidi rakendus ei näe
seda kunagi: telefon räägib sinu backendiga, backend räägib
Google'iga. Iga paigaldaja kasutab oma võtit ja maksab oma kasutuse
eest.

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
| [CONTRIBUTING.md](CONTRIBUTING.md) | kuidas panustada ja mis litsentsi all panus sisse tuleb |
| [SECURITY.md](SECURITY.md) | turvaaukude teatamine, olemasolev kaitse ja teadaolevad piirangud |
| [LICENSE](LICENSE) | Apache License 2.0 täistekst |
| [NOTICE](NOTICE) | autoriõiguse ja omistamise teade (Apache-2.0 §4d) |

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

Androidi APK on kaasas (**Releases** leht), aga **seda ei ole päris
seadmes kontrollitud** – see on ehitatud ja sisu poolest üle
kontrollitud, mitte telefonis läbi testitud. Soovi korral ehita ise.

---

## Litsents

MAYA on **Apache License 2.0** all — täistekst failis
[LICENSE](LICENSE), autoriõiguse ja omistamise teade failis
[NOTICE](NOTICE).

Lühidalt, mida see lubab ja nõuab:

| | |
|---|---|
| Kasutamine, muutmine, levitamine | lubatud, ka ärilisel otstarbel |
| Suletud lähtekoodiga toode | lubatud |
| Muudatuste avaldamine | **ei ole** kohustuslik |
| `LICENSE` ja `NOTICE` kaasa andmine | **kohustuslik** (§4a, §4d) |
| Muudetud failide märkimine | **kohustuslik** (§4b) |
| Patendiluba panustajatelt | **antakse** (§3) |
| Nime „MAYA" kasutamine kaubamärgina | **ei anta** (§6) |
| Garantii | **puudub** (§7, §8) |

**Sõltuvused on eraldi.** MAYA ei sisalda ühtegi kolmanda osapoole
lähtekoodi — sõltuvused paigaldatakse eraldi PyPI-st ja Maven
Centralist ning nende peal kehtivad nende enda litsentsid. Täielik
nimekiri ja üks tähelepanu vajav juht (`tld`, kaudne sõltuvus) on
failis [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

**Gemini Live ei kuulu selle litsentsi alla.** Hääle annab Google'i
API ja selle kasutamisel kehtivad alati Google'i enda tingimused ning
hinnakiri. MAYA ei ole Google'iga seotud ega tema poolt heaks
kiidetud.

---

## Panustamine

Paranduste ja ettepanekute jaoks on pull request'id teretulnud —
vt [CONTRIBUTING.md](CONTRIBUTING.md).

Panus tuleb sisse **Apache-2.0 all** (§5) ja **sina jääd oma koodi
autoriõiguse omanikuks** — allkirjastatavat lepingut (CLA) ei nõuta.
Täpsemalt: [CONTRIBUTING.md](CONTRIBUTING.md).

**Oluline märkus:** see avalik projekt on sõltumatu ja siin ei jookse
ühtegi MAYA teenust. Ükski avalik panus **ei jõua automaatselt** ühegi
töötava paigalduse sisse — ei hoidla haldaja omasse ega kellegi teise
omasse. Iga MAYA paigaldaja otsustab ise, mida ta oma eksemplari üle
kannab.

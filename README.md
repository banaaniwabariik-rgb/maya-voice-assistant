# MAYA — eestikeelne häälassistent, kes helistab ise

**🇪🇪 Eesti keeles (see fail)** · **[🇬🇧 In English](README_EN.md)**

MAYA on eestikeelne reaalajas häälassistent. Ta ei ole nupuvajutusega
küsimuste-vastuste masin: ta räägib loomuliku kõne rütmis, võtab
vaikuse järel ise sõna, jätkab automaatselt lauset, mis pooleli jäi,
ja **helistab sulle ise telefonile**, kui tal on midagi öelda.

Häälemootor on **Google Gemini Live API** (natiivne heli, mitte
kõnesüntees teksti pealt). Backend on Python/FastAPI, klient on
Androidi rakendus.

> ### 🚀 Tahad kohe alustada?
> **[→ ALUSTA SIIT: paigaldusjuhend](docs/PAIGALDAMINE.md)** —
> või jooksuta `./paigalda.sh` ja skript juhendab sind samm-sammult.
>
> Kolm teed on kirjeldatud allpool jaotises
> [Paigaldamine](#paigaldamine).

> **MAYA ei ole teenus.** Siin hoidlas on ainult lähtekood ja Androidi
> rakendus — **ükski MAYA server siin ei jookse ja registreeruda ei
> ole kuhugi**. Sina käivitad backendi oma arvutis või serveris, oma
> Gemini API võtmega, ja telefon ühendub SINU serveriga. Rakendus küsib
> selle aadressi esimesel käivitusel.
>
> **See on avalik koopia.** Projekt sündis ühe inimese isikliku
> assistendina ja on siia üle toodud nii, et kogu isiklik sisu,
> võtmed, serveriaadressid ja vestlusajalugu on välja jäetud. Sa
> paigaldad oma eksemplari, oma võtmetega ja oma karakteritega.

---

## Kuidas see töötab

```
   ANDROIDI TELEFON                      SINU SERVER                    GOOGLE
┌────────────────────┐            ┌────────────────────────┐        ┌───────────┐
│  MAYA rakendus     │            │  web_maya.py (FastAPI) │        │  Gemini   │
│                    │  HTTP(S)   │                        │        │  Live API │
│  mikrofon ────────────────────► │  /api/...   autentimine│        │  (natiiv- │
│  kõlar    ◄──────────────────── │                        │        │   ne heli)│
│                    │ WebSocket  │  /ws/live_maya ────────────────► │           │
│  kaamera ─────────────────────► │     (hääl mõlemas suunas)       │           │
│                    │            │                        │ ◄──────┤           │
│  kõneteade ◄─────────────────── │  /api/call_events (SSE)│        └───────────┘
└────────────────────┘            │                        │
                                  │  SQLite: iga kasutajal │
                                  │  OMA andmebaas         │
                                  └────────────────────────┘
```

**Kogu liiklus käib ühe pordi (8000) kaudu** ja telefon räägib ainult
sinu serveriga — mitte kunagi otse Google'iga. Sinu API võti ei lahku
serverist.

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

## Paigaldamine

**Vali endale sobiv tee.** Kõik kolm viivad sama tulemuseni.

| | Kellele | Kui kaua | Juhend |
|---|---|---|---|
| 🟢 **1. Lihtne** | kõigile, ka esimest korda | ~15 min | allpool + [docs/PAIGALDAMINE.md](docs/PAIGALDAMINE.md) |
| 🤖 **2. AI abiga** | kui tahad, et keegi selgitaks ja vigu lahendaks | ~20 min | [docs/AI_ABIGA_PAIGALDAMINE.md](docs/AI_ABIGA_PAIGALDAMINE.md) |
| 🔧 **3. Käsitsi** | kui tahad igast sammust aru saada | ~30 min | [docs/PAIGALDAMINE.md](docs/PAIGALDAMINE.md) |

### 🟢 1. Lihtne paigaldus

Vaja on **Python 3.11+** ([python.org](https://www.python.org/downloads/))
ja **Gemini API võtit**
([aistudio.google.com/apikey](https://aistudio.google.com/apikey)).

```bash
git clone <hoidla-aadress> maya
cd maya
./paigalda.sh
```

`paigalda.sh` teeb ülejäänu ise ja küsib sinult kolme asja: kas
jätkata, sinu API võti (**ekraanil seda ei kuvata**) ja kuidas telefon
serverini jõuab. Ta **ei kirjuta üle** olemasolevat paigaldust, ei ava
tulemüüri porte ega vii MAYA-t avalikku internetti.

Seejärel:

```bash
./tervisekontroll.sh     # kontrolli, kas kõik on korras
./kaivita.sh             # käivita MAYA
./kaivita.sh --ip        # näita aadressi, mille telefonis sisestad
```

**Telefonis:** paigalda Androidi rakendus → rakendus küsib esimesel
käivitusel serveri aadressi → **„Testi ühendust"** → **„Loo uus
konto"** (esimene konto saab admin-õigused) → räägi.

> Androidi rakenduse ehitamine ja paigaldamine:
> [docs/ANDROID.md](docs/ANDROID.md). APK-s **ei ole ühtegi
> serveriaadressi ega võtit** — sama fail töötab iga MAYA
> paigaldusega.

### 🤖 2. Paigaldus AI-assistendi abiga

Kui sa ei ole programmeerija, võib AI-kodeerimisassistent (nt
[Claude Code](https://code.claude.com/docs/en/overview) või
[VS Code](https://code.visualstudio.com/) AI-laiendusega) paigalduse
sinu eest ära teha ja iga sammu lahti seletada.

**[→ docs/AI_ABIGA_PAIGALDAMINE.md](docs/AI_ABIGA_PAIGALDAMINE.md)** —
sisaldab valmis viipa, mille saad assistendile kleepida. Viip piirab
teda nii, et ta ei lekita sinu võtit, ei ava tulemüüri ega juuruta
midagi võõrasse serverisse.

### 🔧 3. Käsitsi paigaldus

Iga käsk lahti seletatud, koos võrgu-, turvalisuse- ja
tõrkeotsingupeatükkidega:
**[→ docs/PAIGALDAMINE.md](docs/PAIGALDAMINE.md)**
(🇬🇧 [in English](docs/PAIGALDAMINE_EN.md))

### Haldamine

```bash
./peata.sh               # peata server
./uuenda.sh              # tõmba uus versioon + uuenda teegid ja skeem
./tervisekontroll.sh     # diagnostika: paigaldus, seadistus, andmebaas, server, võrk
```

---

## Mida sul on vaja

| | |
|---|---|
| **Google Gemini API võti** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Live API on tasuline — vt [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) |
| **Python 3.11+** | kontrollitud 3.13 ja 3.14 peal |
| **Androidi telefon** | Android 8.0+ (API 26). Kõnefunktsioon vajab päris seadet |
| **Server** | sinu arvuti, koduserver või VPS. **Linux ja macOS on toetatud**; Windowsis kasuta [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) (kontrollimata) |

Riistvara: **2 GB RAM ja 2 GB vaba ketast on piisav.** Graafikakaarti
ega kiiret protsessorit vaja ei ole — raske töö teeb Google'i pool.

Valikuline: Groqi võti (tekstivestlus), Tavily (veebiotsing), Gmaili
rakenduse parool (e-post). **Dockerit ei ole vaja** — vt
[miks](docs/PAIGALDAMINE.md#miks-ei-ole-dockerit).

### 💳 Gemini API võti ja kulud

MAYA hääl tuleb **Google Gemini Live API-st** ja selleks on vaja SINU
enda API võtit:

1. Ava [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   ja loo võti.
2. **Gemini Live API on tasuline** ja nõuab tavaliselt arvelduse
   sisselülitamist. Hinnakiri:
   [aistudio.google.com/docs/pricing](https://aistudio.google.com/docs/pricing).
3. **Arve läheb SINULE, mitte MAYA projektile.** Hinnad, tasuta
   kvoodid ja arvelduse nõuded määrab Google ning need võivad muutuda —
   selles hoidlas ei ole ühtegi hinnanumbrit, sest see vananeks.
4. **Sea eelarveteade enne esimest vestlust:**
   [console.cloud.google.com/billing/budgets](https://console.cloud.google.com/billing/budgets).

**Võti jääb ainult serverisse.** Androidi rakendus ei näe seda kunagi:
telefon räägib sinu backendiga, backend räägib Google'iga. Võti elab
failis `.env`, mis on `.gitignore`-is.

Dokumentatsioon: [ai.google.dev/gemini-api/docs](https://ai.google.dev/gemini-api/docs)
· MAYA pool: [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md)

---

## Dokumentatsioon

**[→ docs/README.md](docs/README.md)** on täielik dokumentatsiooni
indeks. Kõige olulisem:

| Fail | Sisu |
|---|---|
| **[docs/PAIGALDAMINE.md](docs/PAIGALDAMINE.md)** | **täielik paigaldusjuhend algajale** (🇬🇧 [EN](docs/PAIGALDAMINE_EN.md)) |
| **[docs/AI_ABIGA_PAIGALDAMINE.md](docs/AI_ABIGA_PAIGALDAMINE.md)** | paigaldus AI-assistendi abiga (🇬🇧 [EN](docs/AI_ASSISTED_INSTALLATION.md)) |
| [docs/SEADISTAMINE.md](docs/SEADISTAMINE.md) | kõik keskkonnamuutujad ja seaded |
| [docs/ANDROID.md](docs/ANDROID.md) | Androidi rakenduse ehitamine ja ühendamine |
| [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) | Gemini Live seadistus, mudel, kulud |
| [docs/TURVALISUS.md](docs/TURVALISUS.md) | autentimine, kasutajate eraldatus, mida kaitse katab |
| [docs/ARHITEKTUUR.md](docs/ARHITEKTUUR.md) | moodulid, vestluse elutsükkel, mälu |
| [docs/KARAKTERID.md](docs/KARAKTERID.md) | oma karakterite kirjutamine |
| [docs/KONEALGATUS.md](docs/KONEALGATUS.md) | kuidas karakteri algatatud kõne töötab |
| [docs/MITU_SEADET.md](docs/MITU_SEADET.md) | mitu telefoni ja mitu kontot |
| [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md) | sõltuvused ja nende litsentsid |
| [docs/ARENDUS.md](docs/ARENDUS.md) | testid, kodeerimistavad, lahtised kohad |
| [docs/IOS.md](docs/IOS.md) | iOS kui tuleviku platvorm |
| [CONTRIBUTING.md](CONTRIBUTING.md) | kuidas panustada ja mis litsentsi all panus sisse tuleb |
| [SECURITY.md](SECURITY.md) | turvaaukude teatamine, olemasolev kaitse ja piirangud |
| [LICENSE](LICENSE) · [NOTICE](NOTICE) | Apache License 2.0 |

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
| Juhend | [docs/PAIGALDAMINE.md](docs/PAIGALDAMINE.md) | [docs/PAIGALDAMINE.md §5](docs/PAIGALDAMINE.md#variant-3--avalik-internet-domeen--https) |

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

**Valmis APK-d selles hoidlas ei ole** – binaarid ei kuulu
versioonihaldusesse. Androidi rakenduse ehitad ise ühe käsuga
(`cd android && ./gradlew assembleDebug`, vt
[docs/ANDROID.md](docs/ANDROID.md)). Kui väljalase kunagi avaldatakse,
tuleb APK **Releases** lehele koos SHA-256 summaga.

**Ükski funktsioon ei ole selle avaliku koopiaga päris telefonis läbi
testitud.** Kood on üle vaadatud ja automaattestid jooksevad, aga
füüsilise seadme kontrolli ei ole tehtud – ära pea seda tõestatuks.

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

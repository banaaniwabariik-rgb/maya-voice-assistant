# MAYA paigaldamine — täielik juhend

**See juhend eeldab, et sa ei ole kunagi varem serverit paigaldanud.**
Iga käsk on lahti seletatud. Kui mõni samm ei tööta, on peatükis
[9. Tõrkeotsing](#9-tõrkeotsing) kirjas, mida teha.

🇬🇧 In English: **[PAIGALDAMINE_EN.md](PAIGALDAMINE_EN.md)**

> **Kiirem tee?** Kui tahad lihtsalt alustada, kasuta juhendatud
> paigaldust: `./paigalda.sh`. See juhend selgitab sama asja
> põhjalikult ja käsitsi.
>
> **Veel lihtsam?** Lase AI-assistendil ennast juhtida:
> [AI_ABIGA_PAIGALDAMINE.md](AI_ABIGA_PAIGALDAMINE.md).

---

## Sisukord

1. [Mis MAYA on ja mida ta teeb](#1-mis-maya-on-ja-mida-ta-teeb)
2. [Mida sul on vaja](#2-mida-sul-on-vaja)
3. [Gemini API võti ja kulud](#3-gemini-api-võti-ja-kulud)
4. [Backendi paigaldamine](#4-backendi-paigaldamine)
5. [Võrk, pordid ja kaugligipääs](#5-võrk-pordid-ja-kaugligipääs)
6. [Turvalisus ja kontod](#6-turvalisus-ja-kontod)
7. [Androidi rakendus](#7-androidi-rakendus)
8. [Esimene häälvestlus](#8-esimene-häälvestlus)
9. [Tõrkeotsing](#9-tõrkeotsing)
10. [Peatamine, taaskäivitamine, uuendamine](#10-peatamine-taaskäivitamine-uuendamine)

---

## 1. Mis MAYA on ja mida ta teeb

MAYA on **eestikeelne häälassistent**, kellega räägid telefoniga nagu
inimesega. Ta ei ole nupuvajutusega küsimuste-vastuste masin:

- räägib loomuliku kõne rütmis ja sa saad ta igal hetkel katkestada;
- võtab vaikuse järel **ise sõna**, karakteripõhise ajastusega;
- kui tema lause jääb pooleli, **jätkab ise** samast kohast;
- **helistab sulle ise telefonile**, kui tal on midagi öelda;
- mäletab varasemat (pikaajaline mälu, eesti keele morfoloogiaga otsing);
- näeb kaamerapilti ja kommenteerib seda;
- oskab veebi otsida, lehti ja PDF-e lugeda, YouTube'i subtiitreid lugeda;
- 10 erineva iseloomuga karakterit + üks, mille juhise kirjutad ise.

### Kuidas osad kokku käivad

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

| Osa | Mida teeb |
|---|---|
| **Androidi rakendus** | mikrofon, kõlar, kaamera, kõneekraan. Ei räägi Google'iga otse. |
| **Backend** (`server/web_maya.py`) | autentimine, mälu, meeldetuletused, tööriistad; vahendab heli Gemini Live'i |
| **Gemini Live API** | tekitab hääle (natiivne heli, mitte kõnesüntees teksti pealt) |
| **SQLite** | mälu, meeldetuletused, kontod. Iga kasutajal **eraldi andmebaas** |
| **WebSocket** | kahesuunaline heli reaalajas (`/ws/live_maya`) |
| **SSE** | serveri algatatud kõneteated telefonile (`/api/call_events`) |

### Mis on valmis ja mis mitte

| Olek | Mida see tähendab |
|---|---|
| ✅ **Töötab** | häälvestlus, karakterid, mälu, meeldetuletused, kaamera, autentimine, kasutajate eraldatus, karakteri algatatud kõne |
| ⚠️ **Nõuab sinu seadistust** | HTTPS (avalikus internetis kohustuslik), varukoopiad, tulemüür |
| ⚠️ **Piiratud** | laulmine on katseline; kõnealgatus käib SSE kaudu (ei kasuta FCM-i, seega vajab akusäästu erandit) |
| ❌ **Puudub** | iOS-i rakendus; veebiliides ilma Androidita; keskne teenus |
| ❓ **Kontrollimata** | ükski funktsioon ei ole selle avaliku koopia APK-ga **päris telefonis** läbi testitud |

### MAYA on self-hosted

**Keskset MAYA teenust ei ole olemas.** Ei ole serverit, kuhu
registreeruda. GitHubis on ainult lähtekood ja Androidi APK.

Iga kasutaja:
- jooksutab **oma** backendi oma arvutis või serveris;
- kasutab **oma** Gemini API võtit ja maksab oma kasutuse eest Google'ile;
- hoiab **oma** andmeid oma masinas.

MAYA projekt ei näe sinu vestlusi, ei halda sinu serverit ega saa
sinu andmetele ligi.

---

## 2. Mida sul on vaja

### Riistvara

| | Miinimum | Soovitatav |
|---|---|---|
| **Server** (arvuti, kus MAYA jookseb) | 2 GB RAM, 2 tuuma, 2 GB vaba ketast | 4 GB RAM, püsivalt sees olev masin |
| **Võrk** | püsiv internetiühendus | juhtmega võrk serveril |
| **Telefon** | Android 8.0 (API 26) | Android 10+ |

MAYA ei vaja graafikakaarti ega kiiret protsessorit — raske töö teeb
Google'i pool. Server peamiselt vahendab heli.

**Kas Raspberry Pi sobib?** Tõenäoliselt jah (Pi 4, 4 GB), aga **me ei
ole seda kontrollinud**. Ära pea seda tõestatuks.

### Operatsioonisüsteem

| | Olek |
|---|---|
| **Linux** (Debian, Ubuntu, Fedora) | ✅ toetatud |
| **macOS** | ✅ toetatud |
| **Windows** | ⚠️ **kontrollimata**. Kasuta [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) (Ubuntu) ja järgi Linuxi juhiseid. Paigaldusskriptid on bash-skriptid. |

**VPS sobib hästi** (Hetzner, DigitalOcean, Contabo jne) — kõige odavam
klass on tavaliselt piisav. Kui server on avalikus internetis, loe
kindlasti peatükki [5](#5-võrk-pordid-ja-kaugligipääs) ja
[6](#6-turvalisus-ja-kontod).

### Tarkvara

**Kohustuslik:**

| Mida | Miks | Kust |
|---|---|---|
| **Python 3.11 või uuem** | backend on Pythonis | https://www.python.org/downloads/ |
| **Pythoni venv moodul** | teekide eraldamiseks | Debian/Ubuntu: `sudo apt install python3-venv` |
| **Gemini API võti** | hääl | [peatükk 3](#3-gemini-api-võti-ja-kulud) |

**Soovitatav:**

| Mida | Miks | Kust |
|---|---|---|
| **Git** | projekti allalaadimine ja uuendamine | https://git-scm.com/downloads/ |
| **curl** | kontrollkäsud selles juhendis | tavaliselt juba olemas |

**Androidi rakenduse ise ehitamiseks** (valikuline, APK saab ka valmis
kujul):

| Mida | Kust |
|---|---|
| **JDK 17** | https://adoptium.net/ |
| **Android SDK (API 34)** | [Android Studio](https://developer.android.com/studio) või `cmdline-tools` |

**Valikulised lisavõtmed** (MAYA töötab ka ilma):

| Võti | Mida annab |
|---|---|
| `GROQ_API_KEY` | tekstivestlus ja Whisperi transkriptsioon |
| `TAVILY_API_KEY` | veebiotsing |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` | e-posti lugemine |

> **Dockerit MAYA ei vaja.** Vt [miks mitte](#miks-ei-ole-dockerit).

---

## 3. Gemini API võti ja kulud

### Mis see on ja miks MAYA seda vajab

MAYA hääl **ei** sünni sinu arvutis. Heli tekitab Google'i **Gemini
Live API**, mis teeb natiivset heli (mitte kõnesünteesi teksti pealt —
sellepärast kõlab MAYA elava inimese moodi ja saab sõna sekka öelda).

**API võti** on pikk salajane string, millega Google teab, kes päringu
tegi ja kellele arve läheb. Ilma selleta MAYA **ei räägi**.

### Kuidas võtme saada

1. Ava **[Google AI Studio](https://aistudio.google.com/)** ja logi
   sisse Google'i kontoga.
2. Mine lehele **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**.
3. Vajuta **„Create API key"** ja vali (või loo) Google Cloudi projekt.
4. Kopeeri võti. See algab tavaliselt tähtedega `AIza`.

Dokumentatsioon: **https://ai.google.dev/gemini-api/docs**

### Arveldus

**Gemini Live API on tasuline** ja selle kasutamine nõuab tavaliselt,
et Google Cloudi projektis oleks arveldus sisse lülitatud.

- Hinnakiri: **https://aistudio.google.com/docs/pricing**
- **Hinnad, tasuta kvoodid ja arvelduse nõuded määrab Google ning need
  võivad muutuda.** Selles juhendis ei ole ühtegi hinnanumbrit, sest iga
  siia kirjutatud number vananeks. **Vaata alati Google'i enda lehelt.**
- **Arve läheb SINULE.** MAYA projekt ei vahenda makseid, ei saa sinu
  kasutusest osa ega vastuta kulude eest.

### Kulude piiramine

Google Cloudi konsoolis saab seada **eelarveteateid** ja kvoodipiiranguid:

- Eelarve ja teated: https://console.cloud.google.com/billing/budgets
- Kvoodid: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

**Soovitus algajale:** sea eelarveteade juba enne esimest vestlust.
Nii saad kirja, kui kulu ületab sinu valitud summa. Täpsed sammud ja
võimalused on Google'i poolel ning võivad muutuda — järgi nende juhendit.

MAYA-l on sisseehitatud **kulujälgija**, mis näitab seansi hinnangulist
maksumust serveri logis. See on **hinnang MAYA enda arvutuse järgi**,
mitte Google'i arve. Usalda arveldust ainult Google'i konsoolis.

### Võtme kaitsmine

| Reegel | Miks |
|---|---|
| Võti elab **ainult** failis `.env` | see fail on `.gitignore`-is |
| `.env` õigused **600** | loeb ainult sinu kasutaja |
| Võti **ei ole kunagi** Androidi APK-s | telefon räägib ainult sinu serveriga |
| Ära pane võtit issue'sse, PR-i ega ekraanipilti | sealt korjatakse neid automaatselt |
| Kui võti lekib: **tühista see kohe** AI Studios ja tee uus | lekkinud võti jääb lekkinuks ka pärast kustutamist |

Kes sinu serverile ligi pääseb, saab sinu võtit kasutada. Seepärast on
peatükk [6](#6-turvalisus-ja-kontod) oluline.

---

## 4. Backendi paigaldamine

### 4.0 Terminali põhitõed

Kõik käsud käivad **terminalis** (macOS: Terminal; Linux: Terminal;
Windows: WSL2 aken).

| Käsk | Mida teeb |
|---|---|
| `pwd` | näitab, millises kaustas sa oled |
| `ls` | näitab kaustas olevaid faile |
| `cd maya` | läheb kausta `maya` |
| `cd ..` | läheb ühe kausta võrra tagasi |
| Ctrl+C | peatab praegu jooksva programmi |

Käsud käivitatakse **ühekaupa**: kopeeri rida, kleebi terminali, vajuta
Enter, oota kuni käsk lõpeb. `$` märki ära kopeeri — see tähistab
lihtsalt käsurea algust.

### 4.1 Paigalda Python

Kontrolli, kas Python on juba olemas:

```bash
python3 --version
```

Kui vastus on `Python 3.11.x` või uuem, oled valmis. Kui ei:

```bash
# macOS (Homebrew'ga: https://brew.sh/)
brew install python@3.13

# Debian / Ubuntu
sudo apt update
sudo apt install python3 python3-venv python3-pip

# Fedora
sudo dnf install python3 python3-pip
```

### 4.2 Laadi MAYA alla

**Variant A — Gitiga (soovitatud, lihtne uuendada):**

```bash
git clone <hoidla-aadress> maya
cd maya
```

`<hoidla-aadress>` on selle projekti Giti aadress. Git teeb kaustast
`maya` koopia ja hoiab seost, nii et hiljem saad uuendada käsuga
`./uuenda.sh`.

**Variant B — ZIP-failina (Giti pole vaja):**

Laadi hoidlast ZIP alla, paki lahti ja mine kausta:

```bash
cd ~/Downloads/maya-main
```

> ZIP-iga paigaldust **ei saa** käsuga `./uuenda.sh` uuendada — tuleb
> uus ZIP alla laadida ja `.env` ning andmebaas üle kopeerida.

### 4.3 Juhendatud paigaldus (lihtsaim)

```bash
./paigalda.sh
```

See skript:

1. kontrollib Pythoni versiooni, `venv` moodulit, kettaruumi ja
   internetiühendust ning **ütleb täpselt, mis puudu on**;
2. hoiatab, kui selles kaustas on juba paigaldus (**ei kirjuta üle**);
3. loob Pythoni keskkonna `.venv`;
4. paigaldab teegid failist `server/requirements.txt`;
5. loob `.env` faili ja küsib sinu Gemini API võtme **nii, et seda
   ekraanil ei kuvata** ning paneb failile õigused 600;
6. küsib, kuidas telefon serverini jõuab, ja seab `MAYA_HOST`-i;
7. loob tühja andmebaasi.

Kui eelistad kõike käsitsi teha, jätka punktist 4.4. Muidu hüppa
punkti 4.8.

### 4.4 Loo Pythoni keskkond

```bash
python3 -m venv .venv
```

**Mida see teeb:** loob kausta `.venv`, kuhu lähevad ainult MAYA
teegid. Nii ei sega MAYA sinu süsteemi muid Pythoni programme.

### 4.5 Paigalda teegid

```bash
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r server/requirements.txt
```

**Mida see teeb:** laeb PyPI-st alla failis `server/requirements.txt`
loetletud teegid (FastAPI, uvicorn, google-genai jt). Võtab 1–3 minutit.

> Siin on kasutatud `./.venv/bin/pip`, et sa ei pea `activate`-mist
> meeles pidama. Kõik järgnevad käsud kasutavad sama loogikat.

### 4.6 Loo seadistusfail ja lisa API võti

```bash
cp .env.example .env
chmod 600 .env
```

**Mida see teeb:** `.env.example` on näidis **ilma ühegi võtmeta**.
`cp` teeb sellest sinu päris seadistusfaili `.env`. `chmod 600` lubab
faili lugeda ainult sinule.

Ava `.env` tekstiredaktoriga (`nano .env`, `vim .env` või ükskõik
millisega) ja täida vähemalt:

```
GEMINI_API_KEY=sinu_võti_siia
MAYA_USER_NAME=SinuNimi
```

`MAYA_USER_NAME` on nimi, millega karakterid sind kõnetavad.

Kontrolli, kas seadistus loeti (**päris väärtusi ei trükita kunagi**):

```bash
./.venv/bin/python server/config.py
```

### 4.7 Loo andmebaas

```bash
./.venv/bin/python server/init_db.py
```

**Mida see teeb:** loob **tühja** andmebaasi õige skeemiga —
meeldetuletused, ostunimekiri, päevik, vestlusarhiiv, mälufaktid,
FTS5-otsinguindeksid ja kasutajate register. Isiklikke andmeid kaasas
ei ole.

Andmebaas tekib vaikimisi kausta **`server/data/`**:

| Fail | Sisu |
|---|---|
| `server/data/reminders.db` | meeldetuletused, mälu, vestlusarhiiv |
| `server/data/users.db` | kontod ja tokenid (ei kuulu ühelegi kasutajale) |

Teise asukoha saab anda muutujaga `MAYA_DATA_DIR`.

Kontroll (ei muuda midagi):

```bash
./.venv/bin/python server/init_db.py --check
```

### 4.8 Käivita MAYA

```bash
./kaivita.sh
```

See kontrollib eeldused üle, loob andmebaasi kui puudub, hoiatab
macOS-i tulemüüri eest, **trükib välja aadressi, mille telefonis
sisestad**, ja käivitab serveri.

Ainult aadressi küsimiseks (server ei käivitu):

```bash
./kaivita.sh --ip
```

Edukas käivitus näeb välja nii:

```
--> [MÄLUMOOTOR]: SQLite journal_mode=wal
--> [MAYA]: kuulan aadressil 0.0.0.0:8000
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

> Rida `GROQ_API_KEY puudub` on **ootuspärane**, kui sa seda võtit ei
> andnud. Hääl töötab sellest hoolimata.

Server jookseb seni, kuni see aken on lahti. Peatamiseks Ctrl+C või
teisest aknast `./peata.sh`.

### 4.9 Kontrolli, kas kõik on korras

```bash
./tervisekontroll.sh
```

See käib läbi viis plokki — paigaldus, seadistus, andmebaas, kas server
vastab, võrguaadressid — ja ütleb iga rea kohta ✓, ! või ✗. **Võtme
väärtust see ei trüki**, ainult seda, kas kuju sobib.

Käsitsi kontroll:

```bash
curl http://127.0.0.1:8000/api/auth/status
```

Ootuspärane vastus (JSON):

```json
{"seadistatud":false,"registreerimine_lubatud":true,"kutsekood_noutud":false}
```

`"seadistatud":false` tähendab „kontosid ei ole veel" — see on värske
paigalduse puhul õige.

Brauseris saab API dokumentatsiooni vaadata aadressil
`http://127.0.0.1:8000/docs`.

### 4.10 Loo esimene konto

**Esimene konto saab admin-õigused.** Kõige lihtsam on see teha
Androidi rakenduses („Loo uus konto"), aga saab ka käsurealt:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"sinu_nimi","password":"vahemalt_10_margi_pikk_parool"}'
```

Vastuses on `token`. Kontrolli, kas see töötab:

```bash
TOKEN=<kleebi token siia>
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/auth/me
```

Nõuded: kasutajanimi 3–32 märki (tähed, numbrid, `_ . -`), parool
**vähemalt 10 märki**.

### Miks ei ole Dockerit

Kaalusime Docker Compose'i ja otsustasime selle **mitte** lisada:

| | |
|---|---|
| **Pythoni paigaldus** (praegune valik) | üks eeldus (Python 3.11+), mis on Linuxis ja macOS-is tavaliselt juba olemas. Andmebaas on tavaline fail, logid lähevad otse ekraanile, tõrkeotsing on läbinähtav. |
| **Docker** | lisab algajale **uue suure eelduse** (Docker Desktop / Engine), teeb failiõigused ja SQLite'i andmete püsivuse keerukamaks ning peidab vead konteinerisse. Reaalset võitu selle projekti puhul ei anna: MAYA-l ei ole andmebaasiserverit, sõnumijärjekorda ega mitut teenust, mida orkestreerida. |

MAYA on **üks Pythoni protsess + üks SQLite fail**. Docker lahendaks
probleemi, mida siin ei ole. Kui tahad MAYA-t ikkagi konteineris
jooksutada, on see täiesti võimalik — aga see on sinu valik ja me ei
paku selleks ametlikku `Dockerfile`-i, mida me ei testi.

---

## 5. Võrk, pordid ja kaugligipääs

**See on kõige olulisem peatükk.** Enamik „ei tööta" juhtumeid on
võrguprobleemid, mitte MAYA vead.

### 5.1 Pordid — mis on päriselt vaja

| Port | Mis seal on | Kes peab ligi pääsema |
|---|---|---|
| **8000** | kogu MAYA: `/api/...`, SSE (`/api/call_events`), WebSocket (`/ws/live_maya`) | **telefon** |

**See on kõik.** Üks port. Kontrollitud tõsiasjad:

- HTTP API, SSE ja WebSocket **käivad kõik sama pordi kaudu** —
  WebSocket on lihtsalt HTTP-ühenduse uuendus (`Upgrade`).
- Porti saab muuta muutujaga `MAYA_PORT`.
- **SSH-i ega ükskõik millist muud porti MAYA jaoks avada ei ole vaja.**

> **Pordid 8001 ja 8002** esinevad koodis ajaloolistel põhjustel
> (originaalpaigalduses jooksid seal eraldi abiteenused). **Avalikus
> MAYA-s neid teenuseid ei ole** ja neid ei pea avama ega käivitama.
> Androidi klient tuletab need aadressid, aga kui teenust ei vasta,
> jääb vastav valikuline funktsioon lihtsalt vaikseks.

### 5.2 Kuulamisaadress (`MAYA_HOST`)

```
MAYA_HOST=127.0.0.1   ->  server kuulab AINULT selles arvutis.
                          Telefon EI PÄÄSE ligi. Kõige turvalisem.

MAYA_HOST=0.0.0.0     ->  server kuulab kõigil võrguliidestel.
                          Telefon samas võrgus pääseb ligi.
```

Sea see faili `.env`. **Muutuja mõjub päriselt** — server loeb selle
käivitamisel ja trükib logisse, kus ta kuulab.

### 5.3 Kolm paigaldusviisi

#### Variant 1 — Kodune võrk (lihtsaim algus)

Server ja telefon samas WiFis.

```
.env:  MAYA_HOST=0.0.0.0
```

Telefonis sisestad serveri kohtvõrgu aadressi. Selle ütleb välja:

```bash
./kaivita.sh --ip
```

| Plussid | Miinused |
|---|---|
| ei vaja domeeni, sertifikaati ega ruuteri seadistust | töötab **ainult kodus** |
| ükski port ei ole internetist nähtav | liiklus on **krüpteerimata HTTP** |
| | ruuteri antud IP võib muutuda |

**Tulemüür.** Server peab lubama sissetulevaid ühendusi pordil 8000:

```bash
# Ubuntu / Debian (ufw) – ainult kohtvõrgust, mitte kogu internetist
sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp

# Fedora (firewalld)
sudo firewall-cmd --add-port=8000/tcp --permanent
sudo firewall-cmd --reload
```

macOS küsib esimesel käivitusel luba — vasta **„Luba"**. Kui jäi
keelatuks: `Süsteemi sätted → Võrk → Tulemüür → Valikud…` ja lisa
`<projektikaust>/.venv/bin/python3`.

> `192.168.0.0/16` on näide tüüpilise koduse võrgu kohta. Sinu võrk
> võib olla teine (nt `10.0.0.0/8`). Kontrolli oma IP-d käsuga
> `./kaivita.sh --ip`.

**Kõige olulisem kontroll:** ava **telefoni brauseris**
`http://<serveri-ip>:8000/api/auth/status`. Kui JSON tuleb, on võrk
korras. Kui ei tule, ei aita ka rakenduse paigaldamine.

#### Variant 2 — Privaatvõrk / VPN (**soovitatud**)

Tailscale (või WireGuard, ZeroTier) ühendab sinu arvuti ja telefoni
omaette krüpteeritud võrku. **Ühtegi porti ei ole vaja avada ja ruuterit
ei pea puutuma.**

1. Paigalda Tailscale **nii serverisse kui telefoni**:
   **https://tailscale.com/kb/**
2. Logi mõlemas samasse kontosse.
3. Serveris jäta `MAYA_HOST=0.0.0.0`.
4. Küsi Tailscale'i aadress: `./kaivita.sh --ip` (näitab seda eraldi real).
5. Sisesta see aadress MAYA rakenduses.

| Plussid | Miinused |
|---|---|
| **töötab ka väljaspool kodu** (mobiilne andmeside) | vajab kolmanda osapoole teenust |
| liiklus on VPN-i tasemel krüpteeritud | tasuta plaan on isiklikuks kasutuseks piiratud |
| **ükski port ei ole avalikus internetis** | |
| aadress ei muutu | |

See on enamikule kasutajatele parim valik: saad kaugligipääsu ilma
avalikku internetti minemata.

#### Variant 3 — Avalik internet (domeen + HTTPS)

Vajalik ainult siis, kui tahad ligi pääseda ilma VPN-i, või jagada
MAYA-t mitme inimesega üle interneti.

> **ÄRA ava porti 8000 otse internetti.** Ilma HTTPS-ita liiguvad sinu
> kõne, mälu ja autentimistoken avatekstina. Avalikku internetti käib
> MAYA **alati pöördproksi taga**.

Mida on vaja:

1. **Domeen**, mis osutab sinu serveri avalikule IP-le (nt
   `maya.example.com` — see on näide, kasuta oma domeeni).
2. **Pöördproksi**, mis lõpetab HTTPS-i ja saadab liikluse edasi
   `127.0.0.1:8000`-le.
3. **Sertifikaat** — tasuta [Let's Encrypt](https://letsencrypt.org/getting-started/).
4. `.env`: **`MAYA_HOST=127.0.0.1`** — nii kuulab backend ainult
   serveri sees ja ainult proksi pääseb ligi.
5. `.env`: **`MAYA_ALLOW_REGISTRATION=0`** pärast oma kontode loomist
   (või `MAYA_INVITE_CODE=<pikk juhuslik sõna>`).

**Soovitatud pöördproksi: [Caddy](https://caddyserver.com/docs/)** —
ta hangib ja uuendab sertifikaadi ise ning toetab WebSocketi ja SSE-d
ilma lisaseadistuseta. Terve `Caddyfile`:

```caddyfile
maya.example.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

`flush_interval -1` lülitab puhverdamise välja — **see on SSE jaoks
vajalik**, muidu ei jõua kõneteated telefonini.

Kui eelistad [nginx](https://nginx.org/en/docs/)-i:

```nginx
server {
    listen 443 ssl http2;
    server_name maya.example.com;

    ssl_certificate     /etc/letsencrypt/live/maya.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/maya.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # WebSocketi (/ws/live_maya) jaoks KOHUSTUSLIK:
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE (/api/call_events) jaoks KOHUSTUSLIK:
        proxy_buffering off;
        proxy_cache     off;

        # Häälvestlus kestab kaua – ära katkesta ühendust:
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;
    }
}
```

Rakenduses sisestad siis `https://maya.example.com` (ilma pordita).
MAYA tuletab sellest ise **`wss://`** WebSocketi aadressi.

**Ruuteri pordisuunamine.** Kui server on kodus, peab ruuter suunama
internetist tulevad ühendused serverisse. Näide (**kõik numbrid on
näited, sinu omad on teised**):

```
Väline port 443  ->  serveri sisevõrgu IP, port 443   (pöördproksi)
```

Pane tähele: **ruuteri väline port ja backendi sisemine port ei pea
olema samad.** Tüüpiliselt on väljas 443 (HTTPS) ja MAYA kuulab sees
8000 — nende vahel on pöördproksi. **Porti 8000 ei suunata kunagi
otse välja.**

### 5.4 Kokkuvõte

| | Kodune võrk | VPN (Tailscale) | Avalik internet |
|---|---|---|---|
| Kaugligipääs | ei | **jah** | jah |
| Avatud port internetis | ei | **ei** | 443 (proksi) |
| HTTPS | ei (HTTP) | VPN krüpteerib | **kohustuslik** |
| Ruuteri seadistus | ei | **ei** | jah |
| Domeen | ei | ei | jah |
| Keerukus | madal | madal | kõrge |
| `MAYA_HOST` | `0.0.0.0` | `0.0.0.0` | `127.0.0.1` |

---

## 6. Turvalisus ja kontod

### 6.1 Mis on juba sisse ehitatud

| Kaitse | Kuidas töötab |
|---|---|
| **Autentimine kõikjal** | iga `/api` otspunkt, SSE-vool ja Gemini Live WebSocket nõuavad kehtivat tokenit |
| **Paroolid** | soolatud `scrypt`-räsi; paroole ei salvestata ega logita |
| **Tokenid** | andmebaasis on ainult SHA-256 räsi; vaikimisi eluiga 30 päeva (`MAYA_TOKEN_TTL_S`) |
| **Ühekordne WebSocketi pilet** | pikaealine token ei jõua kunagi URL-i: WS jaoks väljastatakse eraldi pilet, mis kehtib 60 s ja **ainult ühe ühenduse** jaoks |
| **Kasutajate eraldatus** | iga kasutaja mälu, meeldetuletused, vestlused ja seaded on **eraldi andmebaasis** — üks kasutaja ei näe teise andmeid ega saa talle helistada |
| **Kiiruspiirang** | sisselogimisel ja API-l (`MAYA_LOGIN_RATE_LIMIT`, `MAYA_RATE_LIMIT`) |
| **Esimene konto = admin** | ülejäänud on tavakasutajad |

### 6.2 Mida pead ise seadistama

| Asi | Mida teha |
|---|---|
| **HTTPS** | avalikus internetis kohustuslik — pöördproksi, vt [5.3 variant 3](#variant-3--avalik-internet-domeen--https) |
| **Registreerimise sulgemine** | `MAYA_ALLOW_REGISTRATION=0` või `MAYA_INVITE_CODE=<pikk juhuslik sõna>` pärast oma kontode loomist |
| **Andmebaasi varukoopia** | MAYA ei tee varukoopiaid ise (vt allpool) |
| **Andmebaasi krüpteerimine** | SQLite on **tavatekstina**; kui see on oluline, kasuta krüpteeritud ketast |
| **API võtme kaitse** | `.env` õigused 600, serveri ligipääsu piiramine |
| **Serveri enda turvalisus** | süsteemiuuendused, tugev SSH-parool/võti, tulemüür |

### 6.3 Varukoopia

Kogu sinu sisu on kahes failis. Peata server ja kopeeri:

```bash
./peata.sh
cp -r server/data ~/maya-varukoopia-$(date +%Y%m%d)
./kaivita.sh
```

Taastamine: kopeeri `server/data` tagasi (server peatatud).

> Kopeeri **seisva** serveriga. Jooksva SQLite'i kopeerimine võib anda
> poolik faili.

### 6.4 Kiiruspiirangu piirid

Kiiruspiirang on **protsessipõhine** ja hoitakse mälus. See tähendab:
mitme töölõime (`workers > 1`) korral korrutub piirang, ja serveri
taaskäivitus nullib loenduri. See kaitseb juhusliku jõuga murdmise eest,
**mitte** sihipärase hajusa rünnaku eest.

### 6.5 Mis läheb Google'ile

Gemini Live on **pilveteenus**. Häälvestluse ajal saadetakse Google'ile:

- sinu **kõne heli** (reaalajas);
- **kaamerakaadrid**, kui kaamera on sees;
- **karakteri juhis** ja vestluse kontekst;
- **mälufaktid**, mis sellesse vestlusesse kaasa pannakse;
- tekstisõnumid, kui kasutad tekstirada.

MAYA **ei saa seda vältida** — see on Gemini Live'i olemus. Kehtivad
Google'i tingimused ja privaatsuspoliitika. Kui mingi teema ei tohi
pilve jõuda, **ära räägi sellest MAYA-ga.**

Mis **ei** lähe Google'ile: sinu parool, tokenid, andmebaasifailid
tervikuna.

---

## 7. Androidi rakendus

### 7.1 Kust APK saada

| Variant | Kuidas |
|---|---|
| **Ise ehitada** | `cd android && ./gradlew assembleDebug` → `android/app/build/outputs/apk/debug/app-debug.apk` |
| **Valmis fail** | kui hoidlas on avaldatud väljalase, on APK selle **Releases** lehel. Kontrolli alati SHA-256 summat. |

**APK-s ei ole ühtegi serveriaadressi ega võtit.** Sama fail töötab iga
MAYA paigaldusega — aadressi sisestad rakenduses. Rakendus **ei ole**
seotud ühegi arendaja serveriga ega võta ühendust kuhugi mujale kui
sinu enda backendisse.

> **Päris telefonis kontrollimata.** Selle avaliku koopia APK on
> ehitatud ja sisu poolest üle kontrollitud, aga **ükski funktsioon ei
> ole päris seadmes läbi testitud**. Ära pea seda tõestatuks.

### 7.2 Paigaldus

```bash
# Telefonis: Seaded → Teave telefonist → vajuta 7× „Järgu number"
#            → tagasi → Arendaja valikud → USB silumine SISSE
adb install -r app-debug.apk
```

Ilma arvutita: kopeeri APK telefoni, ava failihalduris ja luba
„paigalda tundmatutest allikatest".

Kui tuleb `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, on telefonis juba teise
allkirjaga MAYA: `adb uninstall com.maya.live`, siis paigalda uuesti.
**See kustutab ainult telefoni andmed — serveris olev konto ja mälu
jäävad alles.**

### 7.3 Load

| Luba | Milleks | Kohustuslik? |
|---|---|---|
| Mikrofon (`RECORD_AUDIO`) | häälvestlus | **jah** |
| Kaamera (`CAMERA`) | MAYA näeb kaamerapilti | ainult kaamera jaoks |
| Teated (`POST_NOTIFICATIONS`) | sissetulev kõne | jah, kui tahad, et MAYA helistaks |
| Galerii (`READ_MEDIA_IMAGES`) | pildi näitamine | ei |
| Taustateenus (`FOREGROUND_SERVICE_MICROPHONE`) | kõnevalve taustal | automaatne |
| Täisekraanteade (`USE_FULL_SCREEN_INTENT`) | kõneekraan lukustuskuva peal | automaatne |

**Akusäästu erand on KOHUSTUSLIK**, et MAYA saaks ise helistada:

```
Seaded → Rakendused → MAYA → Aku → Piiranguteta
```

Xiaomi/Redmi, Huawei, OnePlus ja Samsung vajavad lisaks „Autostart" ja
„Lukusta rakendus" sätteid — vt [ANDROID.md](ANDROID.md).

### 7.4 Serveri aadress

Esimesel käivitusel näitab MAYA **serveri seadistuse ekraani**. Sisesta
oma backendi aadress, näiteks:

```
http://192.168.1.50:8000      (kodune WiFi – pane OMA IP)
http://100.64.0.5:8000        (Tailscale – pane OMA IP)
https://maya.example.com      (oma domeen, HTTPS, ilma pordita)
```

**Kõik kolm on näited.** Oma aadressi küsi käsuga `./kaivita.sh --ip`.

Lühivormid töötavad: `192.168.1.50` muutub ise
`http://192.168.1.50:8000`-ks (MAYA vaikeport lisatakse IP-aadressile
ja `localhost`-ile, nimega hostile mitte — seal on pöördproksi taga 443).

Vajuta **„Testi ühendust"**. Ekraan ütleb otse, mis juhtus: kas server
vastas, kas tegemist on MAYA backendiga, kas kontod on olemas. Kui
ühendus ei õnnestu, **ära salvesta** — paranda enne võrk või aadress.

Aadressi saab hiljem muuta: seaded → **„Minu MAYA server"**, või
sisselogimisekraanilt „Muuda serveri aadressi".

### 7.5 Konto loomine

Pärast serveri salvestamist tuleb sisselogimisekraan. Vajuta **„Loo uus
konto"** — esimene konto saab admin-õigused. Parool vähemalt 10 märki.

Token salvestub Androidi `SharedPreferences`-isse (rakenduse privaatne
ala), **mitte** veebikihi `localStorage`-isse — nii saab ka taustal
töötav kõnevalve selle kätte.

---

## 8. Esimene häälvestlus

Käi see nimekiri läbi järjekorras. Iga rida eeldab, et eelmine töötas.

| # | Kontroll | Kuidas | Ootad |
|---|---|---|---|
| 1 | Server jookseb | `./tervisekontroll.sh` | „Server vastab aadressil…" |
| 2 | API võti on seatud | sama käsk | „GEMINI_API_KEY on seatud (kuju sobib)" |
| 3 | Server on võrgust nähtav | **telefoni brauseris** `http://<serveri-ip>:8000/api/auth/status` | JSON tuleb ära |
| 4 | Rakendus ühendub | seadistusekraanil „Testi ühendust" | „✓ MAYA server vastas" |
| 5 | Konto töötab | „Loo uus konto" | kate kaob, jõuad MAYA ekraanile |
| 6 | Mikrofon | vajuta kõnenuppu | Android küsib luba → anna |
| 7 | **Hääl töötab** | ütle midagi | MAYA vastab häälega |
| 8 | Gemini võti on päriselt õige | serveri logi | `[LIVE WS]: Klient ühendatud` ja **ei ole** autentimisviga |
| 9 | Katkestamine | räägi MAYA peale | ta jääb kohe vait |
| 10 | Omaalgatus | vaiki 5–15 s | MAYA võtab ise sõna |

Kui rida 7 ei õnnestu, vaata **serveri logi** — seal on põhjus kirjas.

---

## 9. Tõrkeotsing

### Server ei käivitu

| Sümptom | Põhjus ja lahendus |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | teegid paigaldamata või vale Python. Jooksuta `./.venv/bin/pip install -r server/requirements.txt` |
| `RuntimeError: Form data requires "python-multipart"` | sama – `python-multipart` on nõuete sees, paigalda uuesti |
| `GEMINI_API_KEY on seadistamata` | `.env` puudub või on vales kaustas. Kontrolli: `./.venv/bin/python server/config.py` |
| `Address already in use` | port 8000 on juba hõivatud. Peata vana server (`./peata.sh`) või muuda `MAYA_PORT` |
| `NameError` / `SyntaxError` | sul on vana versioon. Jooksuta `./uuenda.sh` |
| `no such table: reminders` käivitamisel | andmebaas on loomata: `./.venv/bin/python server/init_db.py` |

### Telefon ei saa serveriga ühendust

Kontrolli **selles järjekorras**:

1. **Kas server üldse jookseb?** `./tervisekontroll.sh`
2. **Kas server kuulab õigel liidesel?** Kui `MAYA_HOST=127.0.0.1`,
   siis telefon **ei saagi** ligi. Pane `0.0.0.0`.
3. **Kas telefon on samas võrgus?** Mobiilse andmesidega kodune IP ei
   tööta. Lülita WiFi sisse või kasuta VPN-i.
4. **Kas telefoni brauser jõuab kohale?** Ava
   `http://<serveri-ip>:8000/api/auth/status`. Kui brauser ei jõua, ei
   jõua ka rakendus — probleem on võrgus, mitte MAYA-s.
5. **Tulemüür.** Vt [5.3](#variant-1--kodune-võrk-lihtsaim-algus).
6. **Ruuteri „client isolation" / „AP isolation"** (sage
   külalisvõrkudes) blokeerib seadmete omavahelise suhtluse. Lülita
   välja või kasuta põhivõrku.

| Veateade rakenduses | Tähendus |
|---|---|
| „Ühendust ei saadud" | server ei jookse, vale port, või tulemüür blokeerib |
| „Serveri nime ei leitud" | kirjaviga hostinimes – proovi IP-aadressiga |
| „Server vastas, aga see ei ole MAYA backend" | aadress viitab mõnele muule teenusele – kontrolli porti |
| „Server ei vastanud 8 sekundi jooksul" | vale võrk või tulemüür |
| „HTTPS/TLS viga" | ise allkirjastatud sertifikaat ei tööta – kasuta Let's Encrypti |

### HTTP vs HTTPS

| Olukord | Mida rakenduses sisestada |
|---|---|
| Kodune võrk / VPN | `http://...:8000` |
| Pöördproksi taga | `https://domeen` (**ilma pordita**) |

**Ära pane `https://` aadressi, kui pöördproksi puudub** — backend ise
ei räägi HTTPS-i ja ühendus kukub läbi. Ja vastupidi: kui proksi on
olemas, ei tohi `http://` kasutada, muidu liigub token avatekstina.

### WebSocket ei ühendu (hääl ei tööta, aga muu töötab)

| Põhjus | Lahendus |
|---|---|
| Pöördproksi ei edasta `Upgrade` päist | lisa nginxi `proxy_set_header Upgrade/Connection` (vt 5.3) |
| Vale skeem | `https://` peab andma `wss://` — MAYA tuletab selle ise; kontrolli, et aadress algaks `https` |
| Token aegunud | logi rakenduses välja ja uuesti sisse |
| Server sulgeb kohe koodiga **1008** | autentimine nurjus – pilet või token ei jõudnud kohale |
| Server sulgeb koodiga **1007** | Gemini lükkas seansi tagasi – vt serveri logi |

### SSE katkeb (MAYA ei helista)

| Põhjus | Lahendus |
|---|---|
| Pöördproksi puhverdab | Caddy: `flush_interval -1`; nginx: `proxy_buffering off` |
| Proksi aegumine | tõsta `proxy_read_timeout` (nt 3600s) |
| Androidi akusääst tappis taustateenuse | anna akusäästu erand (vt 7.3) |
| Telefon ei ole sisse logitud | logis on „Token puudub – ootan sisselogimist" |

### Autentimisvead

| Teade | Tähendus |
|---|---|
| `401 Autentimine nurjus` | token puudub või aegunud – logi uuesti sisse |
| `403` | konto ei ole admin, aga otspunkt nõuab seda |
| `429 Liiga palju päringuid` | kiiruspiirang – oota minut või tõsta `MAYA_RATE_LIMIT` |
| „Sisselogimine nurjus" | vale parool, või server ei jookse |
| Sisselogimisekraan tuleb iga kord | token ei salvestu – kontrolli, et kasutad APK-d, mitte brauserit |

### Gemini API vead

| Sümptom | Põhjus |
|---|---|
| Hääl ei tule üldse, logis autentimisviga | vale või tühistatud API võti |
| `429` / kvoodi viga Google'i poolelt | kvoot täis või arveldus puudu – kontrolli [AI Studios](https://aistudio.google.com/) |
| Seanss katkeb kohe koodiga 1007 | mudel või seadistus ei sobi – vt [GEMINI_LIVE.md](GEMINI_LIVE.md) |
| „Arve on suurem kui ootasin" | Live API on kõneminutipõhine. Sea eelarveteade (vt [3](#kulude-piiramine)) |

**Arveldusprobleemid lahendab Google, mitte MAYA.** Kui võti ei tööta,
kontrolli AI Studios, kas projektil on arveldus sees ja kas Live API on
lubatud.

### Mikrofon ja Android

| Sümptom | Põhjus |
|---|---|
| Luba ei küsita | anna käsitsi: Seaded → Rakendused → MAYA → Load → Mikrofon |
| Mikrofon vaikib taustal | puudub `FOREGROUND_SERVICE_MICROPHONE` – kasuta ametlikku APK-d |
| MAYA kuuleb iseennast | kajavärav – vt `JITTER_BUFFER_S` ja RMS-lävend `index.html`-is |
| MAYA ei helista, kui ekraan on kustunud | **akusäästu erand puudub** (vt 7.3) |

### Serveri taaskäivitus ja taastumine

Rakendus ühendub ise uuesti, kui server vahepeal taaskäivitub — SSE
proovib iga mõne sekundi järel uuesti. Käsitsi midagi teha ei pea.

Kui server jooksis kokku, vaata viimaseid ridu enne krahhi. Logi läheb
otse ekraanile; püsivaks salvestamiseks suuna see faili:

```bash
./kaivita.sh 2>&1 | tee ~/maya.log
```

---

## 10. Peatamine, taaskäivitamine, uuendamine

```bash
./peata.sh            # peata server viisakalt
./peata.sh --joud     # peata jõuga, kui ei peatunud
./kaivita.sh          # käivita
./tervisekontroll.sh  # kontrolli, kas kõik on korras
./uuenda.sh           # tõmba uus versioon + uuenda teegid ja skeem
```

`./peata.sh` leiab serveri failist `.maya.pid` ja peatab **ainult selle
projektikausta** protsessi. Teiste programmide kallale ta ei lähe.

### Uuendamine

`./uuenda.sh` teeb järjekorras: kontrollib, kas server jookseb (ja
pakub peatamist) → **keeldub, kui sul on salvestamata muudatusi** →
`git pull` → teegid → andmebaasi skeem. **Sinu `.env` ja andmeid ei
puudutata.**

> Kui Androidi pool muutus, tuleb APK uuesti ehitada — serveri uuendus
> üksi telefoni ei muuda.

### Automaatne käivitumine (Linux, valikuline)

```ini
# /etc/systemd/system/maya.service
[Unit]
Description=MAYA Voice Agent
After=network.target

[Service]
Type=simple
User=maya
WorkingDirectory=/opt/maya/server
EnvironmentFile=/opt/maya/.env
ExecStart=/opt/maya/.venv/bin/python /opt/maya/server/web_maya.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now maya.service
journalctl -u maya.service -f     # logi vaatamine
```

Teed `/opt/maya` asenda oma paigalduskaustaga.

---

## Edasi

| Dokument | Sisu |
|---|---|
| [SEADISTAMINE.md](SEADISTAMINE.md) | kõik keskkonnamuutujad |
| [TURVALISUS.md](TURVALISUS.md) | autentimine ja kasutajate eraldatus põhjalikult |
| [ANDROID.md](ANDROID.md) | Androidi ehitamine ja tõrkeotsing |
| [GEMINI_LIVE.md](GEMINI_LIVE.md) | mudel, hääl, VAD, kulud |
| [KARAKTERID.md](KARAKTERID.md) | oma karakterite kirjutamine |
| [KONEALGATUS.md](KONEALGATUS.md) | kuidas MAYA ise helistab |
| [MITU_SEADET.md](MITU_SEADET.md) | mitu telefoni ja mitu kontot |
| [ARHITEKTUUR.md](ARHITEKTUUR.md) | moodulid ja vestluse elutsükkel |
| [AI_ABIGA_PAIGALDAMINE.md](AI_ABIGA_PAIGALDAMINE.md) | paigaldus AI-assistendi abiga |

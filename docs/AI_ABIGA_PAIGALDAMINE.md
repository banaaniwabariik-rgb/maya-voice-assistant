# MAYA paigaldamine AI-assistendi abiga

**Sa ei pea olema programmeerija.** See juhend näitab, kuidas lasta
AI-kodeerimisassistendil MAYA sinu arvutisse paigaldada ja samal ajal
igat sammu sulle selgitada.

🇬🇧 In English: **[AI_ASSISTED_INSTALLATION.md](AI_ASSISTED_INSTALLATION.md)**

> Kui eelistad ise käske sisestada, on olemas
> [juhendatud paigaldus](#kas-see-on-ikka-vajalik) (`./paigalda.sh`) ja
> [täielik käsitsi juhend](PAIGALDAMINE.md).

---

## Kõigepealt kõige tähtsam: kaks eri liiki AI-abi

Need ei ole sama asi ja see vahe määrab, kui palju sina ise teed.

| | **Agentne assistent** | **Vestlusrobot** |
|---|---|---|
| Näited | Claude Code, Cursor, GitHub Copilot agendirežiimis, Gemini CLI | claude.ai, ChatGPT, Gemini veebis |
| Näeb sinu faile | **jah** (annad talle kausta) | ei — ainult selle, mida ise kleebid |
| Käivitab käske | **jah, sinu loal** | **ei** |
| Loeb veateateid ise | **jah** | ei — pead ise kopeerima |
| Mida sina teed | kinnitad samme ja vastad küsimustele | kopeerid käske terminali ja vastused tagasi |

**Agentne assistent teeb töö ära. Vestlusrobot ütleb, mida teha.**
Mõlemad toimivad — teine lihtsalt nõuab sinult rohkem kopeerimist.

> ⚠️ **Ükski AI ei pääse sinu arvutisse ise.** Agentne assistent saab
> ligi ainult sellele kaustale, mille sa talle avad, ja ainult nendele
> käskudele, mille sa lubad. Kui mõni teenus väidab vastupidist, ära
> usu.

---

## Osa 1 — Agentse assistendiga (soovitatud)

### Samm 1. Paigalda tööriistad

Vajalik:

| Tööriist | Milleks | Link |
|---|---|---|
| **Terminal** | käskude jooksutamiseks | macOS/Linux: juba olemas. Windows: [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) |
| **Git** | MAYA allalaadimiseks | https://git-scm.com/downloads/ |
| **Python 3.11+** | MAYA backend | https://www.python.org/downloads/ |
| **AI-assistent** | töö tegemiseks | vt allpool |

AI-assistendi valikud:

| | Paigaldus | Märkus |
|---|---|---|
| **Claude Code** | https://code.claude.com/docs/en/overview | Käsurea tööriist. Töötab terminalis, näeb projektikausta, küsib enne käskude jooksutamist luba. |
| **Visual Studio Code** + AI-laiendus | https://code.visualstudio.com/ | Graafiline redaktor. Paigalda sellesse AI-laiendus (nt Claude Code laiendus või GitHub Copilot). |
| **Mõni muu agentne assistent** | — | Kõlbab, kui ta oskab faile lugeda ja sinu loal käske jooksutada. |

GitHubi konto (https://github.com/) on vaja ainult siis, kui tahad
projekti kloonida privaatsest hoidlast või ise panustada. Avaliku
hoidla allalaadimiseks kontot vaja ei ole.

**Dockerit MAYA ei vaja** — vt [PAIGALDAMINE.md](PAIGALDAMINE.md#miks-ei-ole-dockerit).

### Samm 2. Laadi MAYA alla

```bash
git clone https://github.com/banaaniwabariik-rgb/maya-voice-assistant.git maya
cd maya
```

Kui Giti ei ole paigaldatud, laadi
[hoidlast](https://github.com/banaaniwabariik-rgb/maya-voice-assistant)
ZIP alla ja paki lahti.

### Samm 3. Ava projekt assistendis

**Claude Code:**

```bash
cd maya
claude
```

**VS Code:**

```bash
cd maya
code .
```

Seejärel ava AI-paneel. **Tähtis: ava täpselt see kaust, kus MAYA
asub** — nii näeb assistent projekti, aga mitte ülejäänud arvutit.

### Samm 4. Anna talle paigaldusviip

Kopeeri allolev viip tervikuna ja kleebi assistendile. **Ära muuda
piiranguid** — need hoiavad sinu võtme ja arvuti turvalisena.

```text
Aita mul paigaldada MAYA häälassistent sellesse arvutisse. Ma ei ole
programmeerija – selgita iga sammu lihtsas keeles ja eesti keeles.

ENNE KUI MIDAGI MUUDAD:
1. Loe läbi README.md, docs/PAIGALDAMINE.md, server/requirements.txt,
   .env.example ja paigalda.sh. Ütle mulle oma sõnadega, mida see
   projekt teeb ja mida paigaldus nõuab.
2. Kontrolli, mis mu arvutis juba olemas on (Pythoni versioon,
   olemasolev .venv, .env, andmebaas) ja ütle, mis on puudu.
3. Alles siis tee plaan ja küsi minult luba.

KUIDAS TÖÖTADA:
- Tee AINULT neid samme, mis on MAYA paigaldamiseks vajalikud.
- Kasuta projekti ENDA skripte (./paigalda.sh, ./kaivita.sh,
  ./tervisekontroll.sh, ./peata.sh) – ära kirjuta uusi, kui olemasolev
  juba teeb seda tööd.
- Selgita iga käsku enne jooksutamist ühe lausega: mida ta teeb ja
  miks.
- Testi iga etapi järel, et see päriselt töötab, ja ütle tulemus
  välja.
- Kui midagi ebaõnnestub, selgita viga lihtsas keeles ja paku turvalist
  lahendust. Ära proovi juhuslikke parandusi järjest.

MIDA SA EI TOHI TEHA:
- Ära kunagi trüki, logi ega commit'i minu Gemini API võtit. Võti
  kuulub AINULT faili .env (õigused 600), mis on .gitignore'is.
- Ära muuda midagi väljaspool seda projektikausta ilma luba küsimata.
- Ära ava tulemüüri porte, ära muuda ruuteri seadeid ega ava MAYA-t
  avalikku internetti ilma, et oleksid mulle riskid selgitanud ja minult
  selgesõnalise loa saanud.
- Ära kustuta ega kirjuta üle olemasolevat .env faili ega andmebaasi
  ilma hoiatuse ja minu loata.
- Ära juuruta midagi ühelegi kaugserverisse ega võõrasse masinasse.
  See paigaldus käib AINULT minu arvutisse.
- Ära laadi alla ega jooksuta skripte juhuslikest internetiallikatest.
  Kasuta ainult selle projekti faile, ametlikku paketihaldurit (apt,
  brew, dnf) ja PyPI-d.
- Ära muuda Gemini Live mudelit, hääleseadistust ega vestluskäitumist.
- Ära nõrgenda teste ega turvakontrolle selleks, et miski „läheks
  läbi".

MIDA KÜSI MINULT:
- Gemini API võti (ja sisesta see nii, et see ei jää ekraanile ega
  ajalukku).
- Kuidas telefon serverini jõuab: ainult see arvuti, kodune võrk,
  VPN (Tailscale) või avalik internet.
- Luba enne iga muutust, mida ei saa lihtsalt tagasi võtta.

LÕPETUSEKS:
Anna selge aruanne: mis töötab (tõendatud kontrolliga), mis jäi
pooleli, mida pean ise veel tegema (nt telefoni load, akusäästu
erand), ja millised järgmised sammud on.
```

### Samm 5. Lase tal projekti uurida

Hea assistent **loeb enne muutmist**. Kui ta hakkab kohe faile
kirjutama ilma projekti vaatamata, peata ta ja ütle: *„Loe kõigepealt
README.md ja docs/PAIGALDAMINE.md läbi ning ütle mulle, mida kavatsed
teha."*

### Samm 6. Vasta tema küsimustele

Ta küsib sinult kaht asja:

**1. Gemini API võti.** Hangi see enne:
[aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Loe kuluosa: [PAIGALDAMINE.md peatükk 3](PAIGALDAMINE.md#3-gemini-api-võti-ja-kulud).
**Google arveldab selle sinule, mitte MAYA projektile.**

**2. Kuidas telefon serverini jõuab.** Kui sa ei tea, vali **kodune
võrk** (lihtsaim) või **Tailscale** (töötab ka väljaspool kodu, ilma
porte avamata).

### Samm 7. Millal assistent PEAB luba küsima

Need sammud on pöördumatud või turvalisust puudutavad. **Kui assistent
teeb neid küsimata, peata ta.**

| Toiming | Miks luba vaja |
|---|---|
| olemasoleva `.env` või andmebaasi ülekirjutamine | sinu võti ja mälu kaovad |
| failide kustutamine | pöördumatu |
| tulemüüri reeglite muutmine (`ufw`, `firewall-cmd`, `pfctl`) | avab arvuti võrgule |
| ruuteri pordisuunamine | avab arvuti internetile |
| `MAYA_ALLOW_REGISTRATION=1` avalikus internetis | igaüks saab konto teha |
| `sudo` ükskõik mille jaoks | süsteemiülene mõju |
| miski väljaspool projektikausta | ei puuduta MAYA-t |
| `git push`, uue hoidla loomine, avaldamine | sinu kood läheb välja |

### Samm 8. Kontrolli, kas paigaldus õnnestus

**Ära usu ainult assistendi sõna.** Jooksuta ise:

```bash
./tervisekontroll.sh
```

See käib läbi paigalduse, seadistuse, andmebaasi, serveri vastuse ja
võrguaadressid ning ütleb iga rea kohta ✓, ! või ✗. Oodatav tulemus
pärast õnnestunud paigaldust on **„KÕIK KORRAS"** või „TÖÖKORRAS, aga
hoiatus(t)".

Seejärel:

```bash
./kaivita.sh
```

ja kontrolli **telefoni brauserist**, kas server on nähtav:
`http://<serveri-ip>:8000/api/auth/status` → peab tulema JSON.

Täielik kontroll-nimekiri:
[PAIGALDAMINE.md peatükk 8](PAIGALDAMINE.md#8-esimene-häälvestlus).

### Samm 9. Mida assistent sinu eest teha EI SAA

| Asi | Miks |
|---|---|
| APK telefoni paigaldamine | vajab füüsilist telefoni |
| Mikrofoni/kaamera lubade andmine | puudutad ise telefoni ekraanil |
| Akusäästu erand | Androidi seadetes, käsitsi |
| Serveri aadressi sisestamine rakenduses | telefoni ekraanil |
| Gemini võtme loomine | sinu Google'i konto |
| Arvelduse seadistamine | sinu Google Cloudi konto |

Need sammud on kirjas
[PAIGALDAMINE.md peatükis 7](PAIGALDAMINE.md#7-androidi-rakendus).

---

## Osa 2 — Vestlusrobotiga (kui agentset assistenti ei ole)

Töötab ka, lihtsalt kopeerid rohkem.

1. Ava mõni AI-vestlus (claude.ai, ChatGPT, Gemini veebis).
2. Kleebi sinna **sama viip**, mis ülal, ja lisa ette:

   ```text
   Sul EI OLE ligipääsu minu arvutile ega failidele. Anna mulle käsud
   ükshaaval, et ma saaksin need terminalis jooksutada, ja oota iga
   kord minu vastust. Küsi minult projekti faile, kui neid vaja on.
   ```

3. Kleebi talle vajalikud failid: `README.md`,
   `docs/PAIGALDAMINE.md`, `server/requirements.txt`, `.env.example`.
   **Faili `.env` ära kunagi kleebi — seal on sinu võti.**
4. Jooksuta tema antud käske ükshaaval ja kleebi väljund tagasi.
5. Vea korral kleebi **täielik veateade** — mitte ainult „ei tööta".

> ⚠️ **Ära kleebi vestlusrobotile kunagi oma API võtit, paroole ega
> `.env` faili sisu.** Kui mõni assistent küsib võtit „kontrollimiseks",
> keeldu. Võtit on vaja ainult failis `.env` sinu arvutis.

---

## Kas see on ikka vajalik?

Ausalt: **MAYA-l on olemas juhendatud paigaldusskript**, mis teeb sama
töö ilma AI-ta:

```bash
./paigalda.sh
```

See kontrollib eeldused, selgitab puuduolevat, loob keskkonna,
paigaldab teegid, küsib võtme varjatult, seab võrgu ja loob andmebaasi.

**AI-assistent on kasulik siis, kui:**

- miski läheb viltu ja sa ei saa veateatest aru;
- tahad, et keegi selgitaks, mida iga samm teeb;
- sinu süsteem on ebatavaline (vana Linux, WSL, mõni erisus);
- tahad seadistada pöördproksit, HTTPS-i või systemd-teenust;
- tahad MAYA-t kohandada (oma karakterid, oma seaded).

**AI-assistent ei ole võluvits.** Ta võib eksida, välja mõelda käske,
mida ei ole, või teha rohkem kui vaja. Sellepärast on ülal olev viip
kirjutatud nii piiravalt — ja sellepärast kontrolli lõpus alati ise
`./tervisekontroll.sh`-ga.

---

## Turvareeglid kokkuvõttes

1. **Võti kuulub ainult faili `.env`.** Mitte vestlusesse, mitte
   Giti, mitte ekraanipilti.
2. **Ükski AI ei tohi sinu eest avada tulemüüri ega ruuterit.** Need
   otsused teed sina, pärast seda kui riskid on sulle selgitatud.
3. **Ükski AI ei juuruta midagi võõrasse serverisse.** MAYA paigaldus
   käib ainult sinu enda masinasse.
4. **Ära jooksuta käske, mida sa ei mõista.** Küsi: *„mida see täpselt
   teeb ja mis juhtub, kui see on vale?"*
5. **Kontrolli tulemust ise.** `./tervisekontroll.sh` on tõend,
   assistendi jutt ei ole.

---

## Kui jääd kinni

| | |
|---|---|
| Veateated ja lahendused | [PAIGALDAMINE.md peatükk 9](PAIGALDAMINE.md#9-tõrkeotsing) |
| Võrk, pordid, HTTPS | [PAIGALDAMINE.md peatükk 5](PAIGALDAMINE.md#5-võrk-pordid-ja-kaugligipääs) |
| Androidi probleemid | [ANDROID.md](ANDROID.md) |
| Kõik seaded | [SEADISTAMINE.md](SEADISTAMINE.md) |
| Turvalisus | [TURVALISUS.md](TURVALISUS.md) |

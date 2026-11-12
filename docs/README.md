# MAYA dokumentatsioon

🇬🇧 **English speakers:** the installation guides are available in
English — [PAIGALDAMINE_EN.md](PAIGALDAMINE_EN.md) and
[AI_ASSISTED_INSTALLATION.md](AI_ASSISTED_INSTALLATION.md). The rest of
the documentation, and MAYA's own user interface, are in Estonian.

> **MAYA ei ole teenus.** Siin hoidlas ei jookse ükski MAYA server ja
> registreeruda ei ole kuhugi. Igaüks paigaldab oma eksemplari oma
> masinasse ja kasutab oma Gemini API võtit.

---

## Alusta siit

| | Kellele | Dokument |
|---|---|---|
| 🟢 **Lihtne paigaldus** | kõigile | juurkaustas `./paigalda.sh`, siis [PAIGALDAMINE.md](PAIGALDAMINE.md) |
| 🤖 **AI abiga** | kui tahad, et keegi selgitaks | [AI_ABIGA_PAIGALDAMINE.md](AI_ABIGA_PAIGALDAMINE.md) |
| 🔧 **Käsitsi** | kui tahad kõigest aru saada | [PAIGALDAMINE.md](PAIGALDAMINE.md) |

---

## Kõik dokumendid

### Paigaldus ja seadistus

| Dokument | Sisu |
|---|---|
| [PAIGALDAMINE.md](PAIGALDAMINE.md) | **täielik paigaldusjuhend algajale** — eeldused, Gemini võti ja kulud, backend, võrk, turvalisus, Android, tõrkeotsing |
| [PAIGALDAMINE_EN.md](PAIGALDAMINE_EN.md) | the same guide in English |
| [AI_ABIGA_PAIGALDAMINE.md](AI_ABIGA_PAIGALDAMINE.md) | paigaldus AI-kodeerimisassistendi abiga + valmis viip |
| [AI_ASSISTED_INSTALLATION.md](AI_ASSISTED_INSTALLATION.md) | the same, in English |
| [SEADISTAMINE.md](SEADISTAMINE.md) | kõik keskkonnamuutujad ja nende vaikeväärtused |
| [ANDROID.md](ANDROID.md) | Androidi rakenduse ehitamine, load, akusääst, tõrkeotsing |

### Kuidas MAYA töötab

| Dokument | Sisu |
|---|---|
| [ARHITEKTUUR.md](ARHITEKTUUR.md) | moodulid, vestluse elutsükkel, mälu |
| [GEMINI_LIVE.md](GEMINI_LIVE.md) | Gemini Live mudel, hääl, VAD, kulud |
| [KARAKTERID.md](KARAKTERID.md) | karakterite süsteem ja oma karakterite kirjutamine |
| [KONEALGATUS.md](KONEALGATUS.md) | kuidas MAYA ise telefonile helistab (SSE, miks mitte FCM) |
| [MITU_SEADET.md](MITU_SEADET.md) | mitu telefoni ja mitu kontot — oodatav käitumine |

### Turvalisus ja juriidika

| Dokument | Sisu |
|---|---|
| [TURVALISUS.md](TURVALISUS.md) | autentimine, kasutajate eraldatus, mida kaitse katab ja mida mitte |
| [../SECURITY.md](../SECURITY.md) | turvaaukude teatamine |
| [SOLTUVUSED.md](SOLTUVUSED.md) | sõltuvused ja nende litsentsid (sh `tld` erijuht) |
| [../LICENSE](../LICENSE) | Apache License 2.0 |
| [../NOTICE](../NOTICE) | autoriõiguse ja omistamise teade |

### Arendus

| Dokument | Sisu |
|---|---|
| [ARENDUS.md](ARENDUS.md) | testid, kodeerimistavad, logiread, teadaolevad lahtised kohad |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | kuidas panustada ja mis litsentsi all panus sisse tuleb |
| [GITHUB_ESITLUS.md](GITHUB_ESITLUS.md) | valmis tekstid GitHubi hoidla kirjelduse, loosungi ja teemade jaoks |
| [../tests/README.md](../tests/README.md) | testikomplekti ülevaade |
| [IOS.md](IOS.md) | iOS kui tuleviku platvorm — arhitektuursed kaalutlused |

---

## Skriptid juurkaustas

| Käsk | Mida teeb |
|---|---|
| `./paigalda.sh` | juhendatud paigaldus (kontrollib eeldused, loob keskkonna, küsib võtme) |
| `./paigalda.sh --kontroll` | ainult eelduste kontroll, ei muuda midagi |
| `./kaivita.sh` | käivitab serveri |
| `./kaivita.sh --ip` | näitab aadressi, mille telefonis sisestada |
| `./tervisekontroll.sh` | kontrollib paigaldust, seadistust, andmebaasi ja serveri vastust |
| `./peata.sh` | peatab serveri |
| `./uuenda.sh` | tõmbab uue versiooni ja uuendab teegid + andmebaasi skeemi |
| `./scripts/kontrolli_privaatsust.sh` | kontrollib, et saladusi ega isikuandmeid ei satuks Giti |

---

## Kui jääd kinni

1. **Jooksuta `./tervisekontroll.sh`** — enamik probleeme tuleb sealt
   välja koos lahendusega.
2. **Vaata [PAIGALDAMINE.md peatükk 9](PAIGALDAMINE.md#9-tõrkeotsing)** —
   seal on veateated ja nende põhjused tabelitena.
3. **Võrguprobleemid** on kõige sagedasemad:
   [peatükk 5](PAIGALDAMINE.md#5-võrk-pordid-ja-kaugligipääs).
4. Ava issue, kui dokumentatsioon on puudulik või eksitav — see on
   samaväärne veateatega.

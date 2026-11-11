# Sõltuvused ja litsentsid

MAYA ise on **Apache License 2.0** all (vt [../LICENSE](../LICENSE),
[../NOTICE](../NOTICE)).

**MAYA ei sisalda ühtegi kolmanda osapoole lähtekoodi.** Ükski
sõltuvus ei ole hoidlasse kopeeritud ega „vendor'itud" – kõik
paigaldatakse eraldi PyPI-st ja Maven Centralist ning nende peal
kehtivad **nende enda litsentsid**, mitte MAYA oma. See on oluline:
Apache-2.0 valimine MAYA jaoks ei muuda ühegi sõltuvuse litsentsi.

Samuti ei ole kaasas ühtegi **fonti, pilti ega helifaili**: Androidi
ikoonid on käsitsi kirjutatud vektor-XML-id ja veebikiht kasutab
ainult süsteemifonte (`system-ui`, `-apple-system`, `monospace`).
Ühtegi välist skripti ega stiililehte veebikiht ei lae.

---

## Pythoni sõltuvused

Loetud **paigaldatud pakettide metaandmetest**
(`License-Expression`, `License`, klassifikaatorid), seisuga
2026-11-11, 59 paketti venv'is.

### Otsesed (`server/requirements.txt`)

| Pakett | Versioon | Litsents |
|---|---|---|
| `fastapi` | 0.162.4 | MIT |
| `uvicorn[standard]` | 0.54.0 | BSD-3-Clause |
| `google-genai` | 3.1.0 | Apache-2.0 |
| `websockets` | 17.4 | BSD-3-Clause |
| `requests` | 2.34.2 | Apache-2.0 |
| `python-multipart` | 0.0.33 | Apache-2.0 |
| `trafilatura` | 2.3.1 | Apache-2.0 |
| `youtube-transcript-api` | 1.2.5 | MIT |
| `groq` | 1.7.0 | Apache-2.0 |
| `certifi` | 2026.10.23 | **MPL-2.0** |
| `pypdf` | 7.0.1 | BSD-3-Clause |

### Kaudsed (tulevad ülalolevatega kaasa)

| Pakett | Litsents | |
|---|---|---|
| `starlette`, `click`, `httpx`, `httpcore`, `httpx2`, `httpcore2`, `idna`, `pycparser`, `python-dateutil`, `python-dotenv`, `pyasn1` (BSD-2), `dateparser`, `babel`, `lxml`, `lxml_html_clean` | BSD | |
| `pydantic`, `pydantic_core`, `anyio`, `h11`, `httptools`, `charset-normalizer`, `urllib3`, `PyYAML`, `pytz`, `tzlocal`, `truststore`, `watchfiles`, `uvloop`, `annotated-types`, `annotated-doc`, `typing-inspection` | MIT | |
| `courlan`, `htmldate`, `tzdata`, `opentelemetry-api`, `tenacity`, `distro`, `google-auth` | Apache-2.0 | |
| `sniffio` | MIT **OR** Apache-2.0 | kahene, vali ise |
| `cryptography` | Apache-2.0 **OR** BSD-3-Clause | kahene |
| `cffi` | MIT-0 | |
| `jusText` | BSD-2-Clause | |
| `typing_extensions` | PSF-2.0 | Pythoni enda litsents, lubav |
| `defusedxml` | PSFL | Pythoni enda litsents, lubav |
| `regex` | Apache-2.0 **AND** CNRI-Python | mõlemad lubavad |
| **`tld`** | **MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later** | **vt allpool** |

---

## ⚠️ `tld` — ainus tähelepanu vajav sõltuvus

**Varasem väide „ühtegi GPL-sõltuvust ei ole" oli ebatäpne.** Paketi
`tld` 0.13.2 metaandmed ütlevad:

```
MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later
```

**Kust ta tuleb:** `trafilatura` → `courlan` → `tld`. See on
**kaudne** sõltuvus; MAYA kood ei impordi `tld`-d kordagi
(kontrollitud).

**Miks see MAYA litsentsi ei muuda:**

1. `tld` on **eraldi PyPI pakett**, mida kasutaja paigaldab ise. Teda
   ei ole hoidlasse kopeeritud ega binaarisse lingitud, seega MAYA ei
   ole `tld`-st tuletatud teos.
2. Tegemist on **kolmese litsentsiga** („OR"): kasutaja võib valida
   MPL-1.1 **või** LGPL-2.1-or-later, kui GPL-2.0 talle ei sobi.
   LGPL lubab teegi kasutamist ilma ülejäänud programmi litsentsi
   muutmata.
3. MAYA-t levitatakse **lähtekoodina**, mitte ühe pakendatud
   binaarina, kuhu sõltuvused sisse pannakse.

**Mida see siiski tähendab:**

- Kui keegi tahab MAYA-st teha **ühe paketi, kuhu sõltuvused on sisse
  pakitud** (PyInstaller, Docker-image üheainsa litsentsiga, vms), siis
  tuleb `tld` litsentsivalik läbi mõelda ja valitud variant kirja
  panna.
- Kui tahad `tld`-d täielikult vältida, tuleb loobuda
  `trafilatura`-st (veebilehtede lugemine) – see on
  funktsionaalsuse kaotus, mida me siin **ei tee**.

**See on teadlikult lahtiseks jäetud ja siin välja öeldud, mitte
vaikides ära peidetud.** Kui projektile on vaja juriidiliselt
siduvat hinnangut, peab selle andma jurist, mitte see dokument.

---

## Muud märkimist väärivad juhud

**`certifi` on MPL-2.0** – nõrgalt copyleft, **failipõhine**. MPL-2.0
nõuab, et kui sa muudad `certifi` enda faile, siis need muudatused
jäävad MPL-2.0 alla. MAYA ei muuda `certifi`-t, seega MAYA koodile see
ei laiene. MPL-2.0 on Apache-2.0-ga ühilduv.

**Kahesed litsentsid** (`sniffio`, `cryptography`) tähendavad, et
kasutaja **valib** – mõlemal juhul on Apache-2.0 valik olemas, seega
probleemi ei teki.

**`defusedxml` ja `typing_extensions`** on Pythoni enda (PSF)
litsentsi all, mis on lubav ja Apache-2.0-ga ühilduv.

---

## Androidi sõltuvused

Loetud **Gradle vahemälus olevatest POM-failidest**, mitte oletatud.

Need, mis päriselt APK-sse jõuavad (`debugRuntimeClasspath`):

| Teek | Versioon | Litsents (POM-ist) |
|---|---|---|
| `androidx.core:core-ktx` | 1.12.0 | Apache-2.0 |
| `androidx.appcompat:appcompat` | 1.6.1 | Apache-2.0 |
| `androidx.webkit:webkit` | 1.10.0 | Apache-2.0 |
| ülejäänud `androidx.*` (activity, annotation, collection, concurrent, emoji2, fragment, lifecycle, savedstate, startup, tracing, vectordrawable, viewpager jt) | transitiivsed | Apache-2.0 |
| `org.jetbrains.kotlin:kotlin-stdlib*` | 1.9.22 | Apache-2.0 |
| `org.jetbrains.kotlinx:kotlinx-coroutines-*` | 1.6.1 | Apache-2.0 |
| `org.jetbrains:annotations` | 13.0 | Apache-2.0 |
| `com.google.guava:listenablefuture` | 1.0 | **POM-is litsentsiplokk puudub** |

**`listenablefuture:1.0`** on Guava projekti artefakt, mis sisaldab
ainsa klassina liidest `ListenableFuture` (358 baiti). Guava enda
projekt on Apache-2.0 all, aga **selle konkreetse artefakti POM ei
deklareeri litsentsi** – see on Guava poolel puudujääk, mitte MAYA
valik. Ta tuleb kaasa `androidx.concurrent:concurrent-futures`-iga.
Praktilist riski ei ole, aga aususe huvides on see siin kirjas.

**Testisõltuvused** on `testImplementation` all ja **ei satu
APK-sse** – kontrollitud testiga `tests_serveri_seadistus.py::test_61`:

| Teek | Litsents (POM-ist) | |
|---|---|---|
| `junit:junit:4.13.2` | **EPL-1.0** | nõrgalt copyleft, aga ei levitata rakendusega |
| `org.hamcrest:hamcrest-core:1.3` | POM-is puudub; projekt on BSD-3-Clause | juniti transitiivne |
| `org.json:json:20231013` | **Public Domain** | asendab Androidi sisseehitatud `org.json`-i JVM-testides |

`org.json` vanematel versioonidel (enne 2022) oli kurikuulus „JSON
License" lause *„The Software shall be used for Good, not Evil"*, mida
Apache Foundation ja Debian pidasid vastuvõetamatuks. Versioon
**20231013 on Public Domain** – klausel on eemaldatud. See on
kontrollitud POM-ist, mitte eeldatud.

### Ainus hoidlas olev kolmanda osapoole binaar

`android/gradle/wrapper/gradle-wrapper.jar` (48 749 B) on **ainus
binaarfail versioonihalduses**. See on Gradle'i ametlik wrapper ja
selle kaasa panemine on Gradle'i enda soovitatud tava – ilma selleta ei
saa projekti ilma eelpaigaldatud Gradle'ita ehitada.

Kontrollitud jar-i enda sisust (mitte oletatud):

```
Implementation-Title:     Gradle Wrapper
Implementation-Vendor:    Gradle, Inc.
SPDX-License-Identifier:  Apache-2.0
META-INF/LICENSE          10 174 B  (Apache-2.0 tekst jar-i sees)
```

Wrapper laeb Gradle 8.5 `services.gradle.org`-ist
(`validateDistributionUrl=true`). SHA-256:
`3b8a25775a69158b5ad2b1d17a80a88dc7b40a352a73eb27d06c612a7ce68e98`.

**Ehitustööriistad ei ole sõltuvused.** Gradle vahemälus on ka Android
Gradle Plugini **enda** sõltuvusi (netty, protobuf, guava, JAXB,
tensorflow-lite-metadata jt), mille hulgas on CDDL+GPLv2-CE ja
LGPL-2.1 litsentse. Need on **ehitusaegsed tööriistad**, mis ei lähe
APK-sse ega MAYA levitatavasse koosseisu – samamoodi nagu kompilaatori
litsents ei mõjuta kompileeritud programmi.

---

## Ühilduvus

| | Kontrollitud |
|---|---|
| Python | 3.13 (tootmine), 3.14 (avalik koopia) |
| `google-genai` | **2.33.0** ja **3.1.0** – mõlemas on olemas `turn_complete_reason`, `session_resumption`, `context_window_compression`, `send_realtime_input(media=/video=)` |
| `websockets` | 14.x–17.x |
| Android | `minSdk 26` (8.0), `targetSdk 34`; võrdlusseade OnePlus 6 (Android 11) |
| JDK | 17 |

## Miks versioone ei lukustatud

Gemini Live on **preview**-API ja selle SDK muutub kiiresti. Kõva
lukustamine jätaks projekti vana vigase SDK peale kinni. Põrandad
(`>=`) on seatud sinna, kus funktsioon päriselt nõuab miinimumi.

`google-genai` on ainus, mille puhul tasub ettevaatlik olla: kui mõni
Live-väli kaob, ütleb `tests_gemini_meta.py` selle kohe välja (puuduv
väli logitakse „puudub", mitte ei kuku kokku).

## Uue sõltuvuse lisamine

Enne lisamist **ütle litsents välja** ja kontrolli, et see ei ole
GPL/AGPL. Vt [../CONTRIBUTING.md](../CONTRIBUTING.md).

Litsentside ülevaate saab uuesti genereerida:

```bash
.venv/bin/python3 - <<'PY'
from importlib.metadata import distributions
for d in sorted(distributions(), key=lambda x: (x.metadata.get('Name') or '').lower()):
    m = d.metadata
    lic = (m.get('License-Expression') or m.get('License') or '').strip()
    cls = [c.split(' :: ')[-1] for c in (m.get_all('Classifier') or [])
           if c.startswith('License ::')]
    print(f"{m.get('Name'):30} {d.version:14} {lic or '/'.join(cls) or 'TEADMATA'}")
PY
```

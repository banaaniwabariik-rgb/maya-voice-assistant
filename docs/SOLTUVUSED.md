# Sõltuvused ja litsentsid

## Pythoni sõltuvused

Kontrollitud paigaldatud pakettide metaandmetest
(`importlib.metadata`), seisuga 2026-11-11.

| Pakett | Versioon | Litsents |
|---|---|---|
| `fastapi` | 0.162.4 | MIT |
| `uvicorn` | 0.54.0 | BSD-3-Clause |
| `google-genai` | 3.1.0 | Apache-2.0 |
| `websockets` | 17.4 | BSD-3-Clause |
| `requests` | 2.34.2 | Apache-2.0 |
| `python-multipart` | 0.0.33 | Apache-2.0 |
| `trafilatura` | 2.3.1 | Apache-2.0 |
| `youtube-transcript-api` | 1.2.5 | MIT |
| `groq` | 1.7.0 | Apache-2.0 |
| `certifi` | 2026.10.23 | MPL-2.0 |
| `pypdf` | 7.0.1 | BSD-3-Clause |
| `starlette` | 1.10.0 | BSD-3-Clause |
| `pydantic` | 2.14.3 | MIT |
| `anyio` | 4.16.0 | MIT |
| `h11` | 0.16.0 | MIT |
| `click` | 8.5.1 | BSD-3-Clause |

**Kokkuvõte:** kõik kohustuslikud sõltuvused on **lubavate**
litsentside all (MIT, BSD, Apache-2.0). `certifi` on MPL-2.0, mis on
nõrgalt copyleft, aga puudutab ainult seda paketti ennast – MPL-2.0
on failipõhine ja ei nakata projekti koodi.

**Ühtegi GPL/AGPL sõltuvust ei ole.** See on oluline, sest AGPL
sõltuvus piiraks seda, millise litsentsi all MAYA ise saab olla.

## Androidi sõltuvused

| Teek | Versioon | Litsents |
|---|---|---|
| `androidx.core:core-ktx` | 1.12.0 | Apache-2.0 |
| `androidx.appcompat:appcompat` | 1.6.1 | Apache-2.0 |
| `androidx.webkit:webkit` | 1.10.0 | Apache-2.0 |
| Kotlin standardteek | gradle plugin'ist | Apache-2.0 |

Kõik Apache-2.0 – lubav, nõuab ainult teate säilitamist.

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

`google-genai` on ainus, mille puhul tasub ettevaatlik olla: kui
mõni Live-väli kaob, siis `tests_gemini_meta.py` ütleb selle kohe
välja (puuduv väli logitakse „puudub", mitte ei kuku kokku).

## Litsentsiotsus EI OLE veel tehtud

Vt [../LITSENTS_OOTEL.md](../LITSENTS_OOTEL.md). Seni, kuni omanik ei
ole litsentsi valinud, **ei ole sellel koodil avalikku litsentsi** ja
seda ei tohi avaldada.

# Gemini Live seadistus

MAYA häälemootor on **Google Gemini Live API** natiivheli režiimis.
See ei ole kõnesüntees teksti pealt: mudel genereerib heli otse, mis
annab loomuliku intonatsiooni, naeru, ohked ja laulmise.

## Võtme hankimine

1. Ava [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Loo API võti
3. Pane see `.env` faili:
   ```
   GEMINI_API_KEY=sinu_voti
   ```

Võti elab **ainult serveris**. Androidi rakendus ei näe seda kunagi —
telefon räägib ainult sinu enda backendiga.

## Kasutatav mudel ja seaded

Need on `server/live_maya_ws.py`-s ja **meelega lukus**. Kõik
olulised väärtused on mõõdetud ja neid ei tohi muuta ilma põhjust
näitamata (vt CONTRIBUTING.md).

| Seade | Väärtus | Miks |
|---|---|---|
| mudel | `gemini-2.5-flash-native-audio-preview-12-2025` | natiivheli, eesti keel |
| API versioon | `v1alpha` | Live API nõue |
| väljundmodaalsus | `AUDIO` | see mudel **ei toeta** `TEXT`-i – TEXT-i küsimine lõpetab seansi veaga 1007 |
| helivorming sisse | `audio/pcm;rate=16000` mono | |
| helivorming välja | 24 kHz PCM | |
| VAD kõne algus | `START_SENSITIVITY_HIGH`, `prefix_padding_ms=250` | kasutaja katkestus peab alati võitma |
| VAD kõne lõpp | `END_SENSITIVITY_LOW`, `silence_duration_ms=800` | ei katkesta mõttepausi peal |
| katkestamine | `START_OF_ACTIVITY_INTERRUPTS` | kasutaja prioriteet |
| kontekstiaken | `sliding_window` kokkusurumine | pikad kõned ei katke |
| seansi taastamine | `SessionResumptionConfig` | tõrke järel jätkub vestlus |
| turvaseaded | 4 × `BLOCK_NONE` | täiskasvanud kasutaja oma assistendis |

### Turvaseadete kohta

Kõik neli kategooriat on `BLOCK_NONE`. See on teadlik valik: MAYA on
isiklik assistent ühele täiskasvanud kasutajale ja filtrid rikkusid
tavalisi vestlusi. **Sina vastutad selle eest, mida sinu eksemplar
teeb**, ja Google'i kasutustingimused kehtivad sõltumata sellest, mida
sa siia seadistad.

## Hinnad

Live API on **tasuline**. Praegu kehtiv arvestus koodis
(`server/live_maya_ws.py`, klass `LiveCostTracker`):

| | |
|---|---|
| heli sisse | ~0,0046 $ / min |
| heli välja | ~0,022 $ / min |
| pilt (kaamerakaader) | 258 tokenit kaadri kohta ühe 768×768 ploki eest |

Praktikas: ~5-minutine aktiivne vestlus kulus mõõdetult **0,04–0,065 €**.
Kontrolli alati Google'i enda hinnakirja — need numbrid vananevad.

> **Püstpaigutuses kaamerakaader** (nt 768×1024) ei mahu ühte 768×768
> plokki ja läheb kahe eest kirja. Kulumudel koodis eeldab praegu ühte
> plokki, seega visiooni kulu on püstkaadrite puhul alahinnatud. Vt
> `LiveCostTracker.frames_count` kasutust.

## SDK versioon

```
google-genai>=2.33.0
```

Kontrollitud versioonidega **2.33.0** ja **3.1.0**. Vanemad ei pruugi
tunda välju `turn_complete_reason`, `session_resumption` ega
`context_window_compression`.

## Tõrkeotsing

### Hääl ei tule üldse

1. `python3 server/config.py` → kas `GEMINI_API_KEY : seatud`?
2. Logis `GEMINI ERR`? Loe veakood:

| Kood | Tähendus | Mida teha |
|---|---|---|
| 1007 | mudel keeldus voost | tavaliselt mööduv preview-mudeli tõrge; MAYA taastab seansi ise ~2 s jooksul |
| 1011 | serveripoolne viga | sama |
| 429 / `RESOURCE_EXHAUSTED` | kvoot täis | kontrolli arveldust Google Cloudis |

### Mudel jääb keset lauset vait

See on **teadaolev preview-mudeli käitumine** — mõõdetud katkemise
määr oli algselt 42,9%. MAYA tunneb selle ära (lause ei lõpe
lausemärgiga) ja palub automaatselt jätkata, kuni 12 katset ühe
kasutajavooru kohta, ooteajata. Vt [ARHITEKTUUR.md](ARHITEKTUUR.md),
jaotis „Taaste".

### 1007 kohe pärast taastet või omaalgatust

Taaste- ja omaalgatuse viip on **tekstisisend heliseanssi**. Kui mudel
vastab sellele ainult mõttega ilma heli, lõpeb seanss veaga 1007. Just
selle pärast on mõlemas viibas lause „Vasta KOHE ja AINULT kõnena —
ära analüüsi" (`server/conversation_flow.py`). **Ära eemalda seda.**

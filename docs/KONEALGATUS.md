# Karakteri algatatud kõne

MAYA eristuv funktsioon: karakter helistab **ise** telefonile ja
alustab vestlust. See ei ole teade „ava rakendus" — telefon heliseb,
sa vastad ja Maya räägib kohe esimese lausega oma asja.

## Kuidas see töötab

```
  SERVER (web_maya.py)                    TELEFON (Android)
  ─────────────────────                   ──────────────────
  1. käivitaja:                           CallWatcherService
     - meeldetuletus saabus                (foreground-teenus,
     - /api/trigger_call                    käib pidevalt)
     - Maya ise otsustas                          │
            │                                     │
            ▼                                     │
  2. set_pending_call_prompt(tekst)               │
     PENDING_CALL_PROMPT = tekst                  │
            │                                     │
            ▼                                     │
  3. call_event_queue.put(...)                    │
            │                                     │
            ▼                                     │
  4. GET /api/call_events  ◄── SSE püsiühendus ───┘
     (Server-Sent Events)
            │
            ▼
  5.                                      IncomingCallActivity
                                          (helistamise ekraan,
                                           helin, vibratsioon)
                                                  │
                                           kasutaja vastab
                                                  ▼
  6. WebSocket /ws/live_maya ◄──────────── Gemini Live seanss avaneb
            │
            ▼
  7. Esimene sõnum on PENDING_CALL_PROMPT:
     "Kõne võeti vastu. Alusta KOHE vestlust oma karakteri rollis
      ilma kasutaja sisendit ootamata! Sinu ülesanne: <tekst>"
            │
            ▼
  8. Maya räägib esimesena.
```

## Osad koodis

| Fail | Roll |
|---|---|
| `server/web_maya.py` | `/api/call_events` (SSE), `/api/trigger_call`, `schedule_delayed_call()`, `call_event_queue` |
| `server/live_maya_ws.py` | `set_pending_call_prompt()`, `PENDING_CALL_PROMPT`, avasõnumi saatmine Geminile |
| `android/.../CallWatcherService.kt` | foreground-teenus, mis hoiab SSE ühendust ja käivitab kõneekraani |
| `android/.../IncomingCallActivity.kt` | helistamise ekraan: helin, vibratsioon, vastamine |
| `android/.../MainActivity.kt` | WebView + `AndroidBridge` + Gemini Live WebSocket |

## Mis on avalikus koopias muudetud

**Ainult serveri aadress.** Varem oli see Kotlinis ja `index.html`-is
kõvakodeeritud ühe konkreetse privaatvõrgu IP peale. Nüüd:

```
android/gradle.properties:   mayaBaseUrl=http://10.0.2.2:8000
          ↓ (buildConfigField)
BuildConfig.MAYA_BASE_URL
          ↓
CallWatcherService.kt:  URL("${BuildConfig.MAYA_BASE_URL}/api/call_events")
MainActivity.kt:        AndroidBridge.getBaseUrls()  →  index.html MAYA_CFG
```

Mehhanism, SSE-protokoll, kõneekraan ja avasõnumi loogika on
**muutmata**.

## Kõne käivitamine käsitsi (testimiseks)

```bash
curl -X POST "http://127.0.0.1:8000/api/trigger_call" \
     -H "Content-Type: application/json" \
     -d '{"text": "Tere, see on test", "persona": "sober"}'
```

Täpne väljakutse kuju sõltub marsruudi definitsioonist — vaata
`http://127.0.0.1:8000/docs`.

## Nõuded, et see päriselt töötaks

1. **Päris Androidi seade.** Emulaator ei helista.
2. **Foreground-teenus peab töötama.** Android tapab tavateenused.
   `AndroidManifest.xml`-is on selleks `foregroundServiceType` ja
   vastavad load.
3. **Akusäästu erand.** Androidi agressiivne akuhaldus (eriti
   Xiaomi, Huawei, OnePlus) tapab teenuse. Luba rakendusel taustal
   töötada.
4. **Telefon peab serverini jõudma.** Sama võrk või privaatvõrk.
5. **SSE ühendus peab püsima.** Server saadab iga 20 s keepalive'i.

## Teadaolevad piirangud

- **Autentimist ei ole.** Igaüks, kes serverini pääseb, saab sulle
  helistada. Vt [SEADISTAMINE.md](SEADISTAMINE.md) turvajaotist.
- **Üks seade.** SSE jõuab kõigi ühendatud klientideni; mitme telefoni
  haldust ei ole.
- **Avalikus koopias EI OLE see päris seadmes läbi testitud.** Kood on
  originaaliga sama, aga sinu telefon, Androidi versioon ja võrk on
  erinevad. Vt README jaotist „Mis siin EI ole".

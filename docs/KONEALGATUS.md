# Karakteri algatatud kõne

> ### Praegune olek
> **Mõlemad kõneallikad töötavad ja on kontrollitud:**
>
> * **käsitsi** — `POST /api/trigger_call` → SSE → telefon;
> * **ajastatud meeldetuletus** (sh korduv) — taustavalvur käib läbi
>   kõik kasutajabaasid ja saadab kõneteate õigele kasutajale.
>
> Kontrollitud päris serveriga: kaks autenditud kasutajat,
> meeldetuletus samal ajal → kumbki sai AINULT oma kõneteate.
> Mitme kasutaja valvuri ehitus: [ARENDUS.md](ARENDUS.md#teadaolevad-lahtised-kohad).


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
ServerSetupActivity.kt   kasutaja sisestab oma serveri aadressi
          ↓
SharedPreferences "maya_server" / "base_url"
          ↓
ServerConfig.baasUrl()
          ↓
CallWatcherService.kt:  URL("${ServerConfig.sseAadress(base)}/api/call_events")
MainActivity.kt:        AndroidBridge.getBaseUrls()  →  index.html MAYA_CFG
```

Aadressi ei ole APK-s ette antud. Kuni kasutaja pole seadistanud, EI
võta valvur ühendust kuhugi – ta ootab ja logib
`Serveri aadress puudub – ootan seadistust`.

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

## Autentimine

SSE-vool **nõuab kehtivat tokenit** ja igal kasutajal on **oma
järjekord**:

```
GET /api/call_events
Authorization: Bearer <token>
```

`CallWatcherService` loeb tokeni Androidi `SharedPreferences`-ist
(sama hoidla, mida kasutab `MainActivity`). Kui token puudub või
server vastab 401/403, teenus **ei ürita tsüklis uuesti** – ta ootab
10–15 s ja kustutab aegunud tokeni, kuni kasutaja uuesti sisse logib.

Varem oli üks globaalne järjekord: igaüks, kes serverini jõudis, sai
helistada **igale** ühendatud telefonile ja iga telefon nägi **kõiki**
kõnesündmusi. Nüüd on see võimatu – vt
[TURVALISUS.md](TURVALISUS.md).

## SSE vs Firebase Cloud Messaging — uuritud ja otsustatud

**Otsus: jääme SSE juurde. FCM-i me EI lisa.**

### Mida mõõtsime ja vaatasime

Androidi klient on juba maksimaalselt karastatud:

| Mehhanism | Olemas |
|---|---|
| `foreground service` püsiva teatega | ✅ `startForeground(1001, …, FOREGROUND_SERVICE_TYPE_MICROPHONE)` |
| `PARTIAL_WAKE_LOCK` (CPU ei maga) | ✅ `MayaLive::CpuKeepAlive` |
| Ekraani äratamine kõne saabumisel | ✅ `MayaLive::ScreenWakeLock` |
| Taasühendumine katkestuse järel | ✅ `while (isRunning)` + 3 s paus |
| Serveripoolne keepalive | ✅ iga 20 s `: keepalive` |
| `USE_FULL_SCREEN_INTENT` kõneekraaniks | ✅ deklareeritud |

Foreground-teenus on **just see** Androidi mehhanism, mis tohib
taustal püsivat võrguühendust hoida. Võrdlusseadmel (OnePlus 6,
Android 11) töötab see koos akusäästu erandiga.

### Millal SSE EI OLE piisav

| Olukord | SSE | FCM kõrge prioriteediga |
|---|---|---|
| Rakendus taustal, ekraan kustunud, akusäästu erand **antud** | ✅ töötab | ✅ |
| Akusäästu erand **puudub** | ⚠️ OEM ROM (Xiaomi, Huawei, OnePlus) võib teenuse tappa | ✅ ärataks siiski |
| Seade sügavas Doze'is mitu tundi | ⚠️ ühendus võib katkeda, taasühendumine võtab kuni 3 s + võrgu aja | ✅ |
| Rakendus kasutaja poolt „force stop" | ❌ | ❌ (FCM samuti ei ärata) |

### Miks me FCM-i siiski ei lisa

1. **Iga paigaldaja peaks looma oma Firebase projekti** ja panema
   `google-services.json` faili – see on self-hosted projekti jaoks
   suur lisasamm ja uus väline sõltuvus Google'i konsoolile.
2. **Server vajaks FCM-i serverivõtit** ja saatjakoodi – veel üks
   saladus, mida hallata.
3. **Põhiomadus ei tohi muutuda.** FCM-teade üksi **ei ava**
   kõneekraani; selleks peab teade ikkagi käivitama
   `IncomingCallActivity`. Ehk FCM asendaks ainult *transpordi*, mitte
   loogika – ja transport töötab juba.
4. **Akusäästu erand lahendab 95% juhtudest** ja see on üks
   seadistus, mille paigaldaja teeb nagunii ära.

### Kui keegi tahab FCM-i siiski lisada

See on hea panus. Vajalik:

1. Firebase projekt + `google-services.json` → `android/app/`
2. `com.google.gms:google-services` plugin + `firebase-messaging`
3. `FirebaseMessagingService` alamklass, mis käivitab
   `IncomingCallActivity` (sama Intent, mis praegu SSE harus)
4. Seadmetokeni registreerimine: uus otspunkt
   `POST /api/push/register` (autenditud, salvestab tokeni kasutaja
   kirje juurde)
5. Serveripoolne saatja: `kone_jarjekord(uid)` kõrvale teine väljund,
   mis saadab FCM-i. Praegune struktuur toetab seda ilma
   ümberkirjutamist.
6. **SSE peab alles jääma** varuteena ja arenduse jaoks (`localhost`).

Sama muster teeks hiljem võimalikuks ka iOS-i APNs-i — vt
[IOS.md](IOS.md).

## Teadaolevad piirangud

- **Mitu seadet ühe konto kohta:** SSE jõuab kõigi ühendatud
  klientideni, kes on **selle kasutaja** tokeniga sisse loginud.
  Seadmehaldust (millisele telefonile helistada) ei ole.
- **Akusäästu erand on kohustuslik.** Ilma selleta tapab Android
  teenuse ja kõne ei jõua kohale.
- **Originaalis see töötab:** MAYA on käinud OnePlus 6-l mitu kuud ja
  kõnealgatus on seal igapäevaselt kasutuses. **Avaliku ehitusega ei ole
  seda päris seadmes üle kontrollitud.** Kood on originaaliga sama, aga
  sinu telefon, Androidi versioon ja võrk on erinevad. Vt README jaotist
  „Mis siin EI ole".
# iOS kui tuleviku platvorm

**iOS rakendust EI OLE ja seda praegu ei tehta.** See dokument
kirjeldab, mis on tehniliselt vaja ja mis on tõelised takistused, et
hilisem otsus oleks informeeritud.

## Mis töötaks suure tõenäosusega kohe

Backend on platvormist sõltumatu: HTTP + WebSocket + SSE. iOS klient
saaks kasutada **täpselt sama API-t**, sealhulgas sama autentimist ja
sama Gemini Live voogu.

| Osa | iOS-is |
|---|---|
| Autentimine (Bearer-token) | triviaalne, `URLSession` |
| Häälvestlus (WebSocket + PCM) | tehtav: `AVAudioEngine` 16 kHz sisse, 24 kHz välja |
| Kaamerakaadrid | `AVCaptureSession` → JPEG, sama protokoll |
| Meeldetuletused, mälu, karakterid | puhtalt API-päringud |

## Tõelised takistused

### 1. Karakteri algatatud kõne — kõige suurem probleem

Androidis hoiab kõneootet **foreground-teenus** püsiva SSE ühendusega.
**iOS-is ei ole sellist asja.** Taustal töötav app tapetakse ja püsiv
võrguühendus katkeb.

iOS-i ainsad töötavad teed:

| Tee | Mis see nõuab | Puudus |
|---|---|---|
| **PushKit + CallKit** | Apple Developer konto, VoIP push sertifikaat, APNs server | Apple **nõuab**, et VoIP push paneks kohe CallKit-kõne püsti. Väärkasutus = app lükatakse tagasi |
| Tavaline APNs push | sama sertifikaadiosa | ei ava kõneekraani, ainult teade – **see rikuks MAYA põhiomaduse** |
| Taustaheli režiim | `audio` background mode | hoiab appi elus ainult siis, kui heli juba mängib |

**Järeldus:** iOS-is on karakteri algatatud kõne tehtav AINULT
PushKit + CallKit kaudu, mis tähendab:
- tasuline Apple Developer konto (99 $/a),
- APNs VoIP sertifikaat ja selle uuendamine,
- serveripoolne APNs-saatja (uus sõltuvus),
- App Store'i ülevaatus, mis VoIP pushi väärkasutust kontrollib.

Self-hosted projekti jaoks on see märksa suurem koormus kui Androidi
`adb install`.

### 2. Levitamine

Androidis annab paigaldaja APK otse. iOS-is:

| Variant | Piirang |
|---|---|
| App Store | ülevaatus; „kasutaja toob oma API võtme" app-id on riskantsed |
| TestFlight | 90 päeva, 100 sisetestijat |
| Ad-hoc / sideload | 7-päevane sertifikaat tasuta kontoga, 1 aasta tasulisega |
| AltStore / sideloadly | kasutaja peab iga nädal uuendama |

### 3. WebView'i piirangud

Androidi klient on `WebView` + `AndroidBridge`. iOS-i `WKWebView`
töötaks, aga:
- mikrofoni ligipääs `WKWebView`-s on piiratum,
- `getUserMedia` käitub erinevalt,
- natiivne helitee (`AVAudioEngine`) on tõenäoliselt vajalik.

Realistlik hinnang: iOS klient oleks **natiivne Swift app**, mis
kasutab sama API-t, mitte sama WebView'i ümbertõstmine.

## Soovitatud järjekord, KUI iOS tehakse

1. **Backend ei vaja muudatusi** – alusta sellest, et kontrolli
   `/api/auth/*`, `/api/reminders` ja `/ws/live_maya` iOS-i
   `URLSession`-iga läbi.
2. **Häälvestlus ilma kõnefunktsiooni.** See annab 80% väärtust 20%
   vaevaga ja ei vaja Apple Developer kontot (sideload piisab).
3. **Alles siis PushKit/CallKit**, kui esimene osa töötab ja keegi on
   nõus Apple'i konto ja APNs-i haldama.

## Mida backend peaks arvestama juba praegu

| | Olukord |
|---|---|
| API on platvormineutraalne | ✅ juba nii |
| Autentimine ei eelda Androidi | ✅ Bearer-token |
| Kõnesündmused SSE kaudu | ⚠️ iOS vajab lisaks APNs-i väljundit |
| Helivorming (PCM 16/24 kHz) | ✅ iOS-sõbralik |

Ainus koht, kuhu iOS tugi backendis midagi lisaks, on **teine
kõneteavituse väljund** APNs-i jaoks `web_maya.py`-s – praegune
`kone_jarjekord(uid)` struktuur toetaks seda ilma ümberkirjutamist.

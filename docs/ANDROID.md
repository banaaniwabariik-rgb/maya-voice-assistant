# Androidi rakendus

## Eeldused

- JDK 17
- Android SDK (API 34) — Android Studio või `cmdline-tools`
- Päris seade Android 8.0+ (API 26). **Kõnefunktsioon ei tööta emulaatoris.**

## 1. Serveri aadress — kasutaja sisestab selle rakenduses

**APK-s ei ole ühtegi serveriaadressi.** Ei vaikeväärtust, ei
ehitusaegset konstanti. Rakendus küsib aadressi kasutajalt esimesel
käivitusel ja salvestab selle telefoni.

```
ServerSetupActivity  (esimene käivitus või seaded)
      │  kasutaja sisestab + „Testi ühendust"
      ▼
SharedPreferences  "maya_server" / "base_url"
      │
      ├──► ServerConfig.baasUrl()      →  CallWatcherService (SSE)
      ├──► ServerConfig.wsAadress()    →  ws:// või wss://
      └──► AndroidBridge.getBaseUrls() →  index.html  MAYA_CFG
                                          → HTTP API, autentimine, WebSocket
```

Kogu seadistus on ÜHES kohas (`ServerConfig.kt`), nii et HTTP, SSE ja
WebSocket ei saa eri serverite peale lahku minna. `https://` annab
automaatselt `wss://`, `http://` annab `ws://`.

### Mida kasutaja ekraanil sisestab

| Olukord | Näide |
|---|---|
| Päris telefon, sama WiFi | `http://192.168.1.50:8000` |
| Privaatvõrk (Tailscale/WireGuard) | `http://100.64.0.5:8000` |
| Oma domeen pöördproksi taga | `https://maya.example.com` |
| Emulaator, server samas arvutis | `http://10.0.2.2:8000` |

Need on **näited** – igaüks paneb sinna oma serveri aadressi.
Lühivormid on lubatud: `192.168.1.50` muutub ise
`http://192.168.1.50:8000`-ks (MAYA vaikeport). Nimega hostile porti
ei lisata, sest pöördproksi taga on see 443.

Nupp **„Testi ühendust"** pärib `/api/auth/status` ja ütleb ausalt,
mis juhtus: kas server vastas, kas tegemist on MAYA backendiga, kas
kontod on olemas. Kui ühendus ei õnnestu, EI salvestata aadressi
vaikselt „õnnestunuks" – salvestamiseks tuleb eraldi kinnitada.

Aadressi saab hiljem muuta kahest kohast:
- rakenduse seadetest → **„Minu MAYA server"** → MUUDA;
- sisselogimisekraanilt → **„Muuda serveri aadressi"** (kui aadress
  on vale, ei jää sa sisselogimise taha kinni).

Serveri vahetamisel kustutatakse vana token – token kuulub ühele
paigaldusele.

### Arendaja eeltäide (valikuline)

Kui ehitad ise ja ei taha aadressi iga paigalduse järel käsitsi
sisestada, saad seadistusvälja **eeltäita**:

```bash
./gradlew assembleDebug -PmayaDefaultBaseUrl=http://192.168.1.50:8000
```

See ainult täidab välja ette ära – rakendus ei ühenda ise kuhugi ja
kasutaja peab ikka salvestama. **Avalikuks levitamiseks ehita ILMA
selle liputa**, muidu läheb sinu aadress APK-sse.

## 2. Ehitamine ja paigaldamine

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`-r` hoiab olemasolevad andmed alles.

APK asub: `android/app/build/outputs/apk/debug/app-debug.apk`

**Valmis APK-d hoidlas ei ole** – binaarid ei kuulu
versioonihaldusesse. Kui väljalase on avaldatud, leiad APK hoidla
**Releases** lehelt koos SHA-256 summaga; kontrolli summa alati üle.
GitHub levitab ainult lähtekoodi ja APK-d – **ükski MAYA server
GitHubis ei jookse.**

### Testid

```bash
cd android
./gradlew testDebugUnitTest      # ServerConfig puhas loogika
```

### Allkirjastamine

Projektis **ei ole** allkirjastamisvõtmeid — `app/build.gradle`-is ei
ole `signingConfig`-i ja debug-ehitus kasutab Androidi
arendusvõtmeid. Poodi või püsipaigalduseks tee oma võti:

```bash
keytool -genkey -v -keystore minu.keystore -alias maya \
        -keyalg RSA -keysize 2048 -validity 10000
```

Hoia see **väljaspool hoidlat** (`.gitignore` blokeerib `*.keystore`,
`*.jks` ja `keystore.properties`).

## 3. Sisselogimine

Rakendus näitab käivitamisel **sisselogimisekraani**, kuni kehtiv
token puudub. Server nõuab autentimist kõigil otspunktidel.

- **Esimene kord:** vajuta „Loo uus konto". Esimene konto saab
  selles paigalduses admin-õigused.
- Parool peab olema vähemalt 10 märki.
- Token salvestub `SharedPreferences`-i (rakenduse privaatne ala) ja
  kehtib 30 päeva.

Tokeni voog:

```
Sisselogimisekraan (index.html)
      │  POST /api/auth/login
      ▼
MayaAuth.set(token)
      │  AndroidBridge.setAuthToken()
      ▼
SharedPreferences "maya_auth" / "token"
      ├──► fetch'i ümbris lisab: Authorization: Bearer <token>
      ├──► WebSocket URL: ?token=<token>   (käepigistus ei luba päist)
      └──► CallWatcherService: Authorization: Bearer <token>
```

**Token ei jõua kunagi `localStorage`-isse** – nii saab ka taustal
töötav `CallWatcherService` selle kätte.

Kui server vastab 401, kustutab teenus tokeni ja ootab uut
sisselogimist – ta ei pommi serverit tsüklis.

## 4. Load

`AndroidManifest.xml` küsib:

| Luba | Milleks |
|---|---|
| `RECORD_AUDIO` | mikrofon |
| `CAMERA` | kaamera (Maya näeb) |
| `INTERNET` | backend |
| `FOREGROUND_SERVICE` + `foregroundServiceType="microphone"` | taustal töötav kõnevalve |
| `POST_NOTIFICATIONS` | kõneteade |
| `VIBRATE`, `WAKE_LOCK`, `USE_FULL_SCREEN_INTENT` | helistamise ekraan |

Esimesel käivitamisel anna mikrofoni ja kaamera load.

## 5. Akusäästu erand — KOHUSTUSLIK kõnefunktsiooni jaoks

Androidi akuhaldus tapab taustateenused. Ilma erandita **Maya ei saa
sulle helistada**, kui ekraan on kustunud.

`Seaded → Rakendused → MAYA → Aku → Piiranguteta`

Xiaomi/Redmi, Huawei, OnePlus ja Samsung teevad seda eriti
agressiivselt — otsi ka „Autostart" ja „Lukusta rakendus" sätteid.

## 6. Kaamera kvaliteet

Kaadrid saadetakse Geminile seansi taustal. Väärtused on
`app/src/main/assets/index.html`-is:

```javascript
cvs.width = 768;                              // kaadri laius
cvs.toDataURL("image/jpeg", 0.85);            // JPEG kvaliteet
}, 1500);                                     // intervall ms
getUserMedia: width 1280, height 960          // 4:3, mitte ruut
```

Mõõdetud: kvaliteet 0,5 ja 480 px andis 0,069 baiti piksli kohta ja
mudel ütles „pime pilt". 768 px + 0,85 andis 0,169 B/px ja kirjeldas
pilti korrektselt. Kaamera tõstab vastamise latentsust ~0,5 s võrra.

## 7. Tõrkeotsing

| Sümptom | Põhjus |
|---|---|
| Käivitusel tuleb serveri seadistusekraan | nii peabki – aadress on seadistamata |
| „Ühendust ei saadud" seadistusekraanil | server ei jookse, vale port, või tulemüür blokeerib – vt `./kaivita.sh` |
| „Server vastas, aga see ei ole MAYA backend" | aadress viitab mõnele teisele teenusele; kontrolli porti |
| „Serveri nime ei leitud" | kirjaviga hostinimes; proovi IP-aadressiga |
| „Ei saa serveriga ühendust" hiljem | server kolis või IP muutus – seaded → „Minu MAYA server" |
| Sisselogimine: „Sisselogimine nurjus" | vale parool, või server ei jookse |
| Sisselogimisekraan tuleb iga kord | token ei salvestu – kontrolli, et `AndroidBridge` on olemas (ainult APK-s, mitte brauseris) |
| Kõne ei jõua kohale pärast sisselogimist | vt `adb logcat \| grep CallWatcher` – kui seal on „Token puudub", logi rakenduses uuesti sisse |
| Maya ei helista | akusäästu erand puudub või foreground-teenus tapetud |
| Mikrofon vaikib | luba puudub, või kajavärav saadab nulle (vt serveri logi „läbinisti vaiksed") |
| Heli kokutab | võrgu jitter; vt `JITTER_BUFFER_S` index.html-is |
| Kaamerat ei näe | luba puudub; kontrolli serveri logist, kas kaadrid saabuvad |

Logid: `adb logcat | grep -i maya`

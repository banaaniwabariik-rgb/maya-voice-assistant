# Androidi rakendus

## Eeldused

- JDK 17
- Android SDK (API 34) — Android Studio või `cmdline-tools`
- Päris seade Android 8.0+ (API 26). **Kõnefunktsioon ei tööta emulaatoris.**

## 1. Serveri aadress

Ava `android/gradle.properties` ja pane oma backendi aadress:

```properties
mayaBaseUrl=http://10.0.2.2:8000
```

| Olukord | Väärtus |
|---|---|
| Emulaator, server samas arvutis | `http://10.0.2.2:8000` |
| Päris telefon, sama WiFi | `http://192.168.1.50:8000` |
| Privaatvõrk (Tailscale/WireGuard) | `http://100.x.y.z:8000` |

Võib anda ka käsurealt: `./gradlew assembleDebug -PmayaBaseUrl=http://...`

Aadress jõuab koodi nii:

```
gradle.properties  →  BuildConfig.MAYA_BASE_URL  →  CallWatcherService.kt
                                                 →  AndroidBridge.getBaseUrls()
                                                 →  index.html  MAYA_CFG
```

**Ühtegi aadressi ei ole koodis kõvakodeeritud.**

## 2. Ehitamine ja paigaldamine

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`-r` hoiab olemasolevad andmed alles.

APK asub: `android/app/build/outputs/apk/debug/app-debug.apk`

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
| „Ei saa serveriga ühendust" | vale `mayaBaseUrl`; kontrolli `adb shell ping <ip>` |
| Sisselogimine: „Sisselogimine nurjus" | vale parool, või server ei jookse |
| Sisselogimisekraan tuleb iga kord | token ei salvestu – kontrolli, et `AndroidBridge` on olemas (ainult APK-s, mitte brauseris) |
| Kõne ei jõua kohale pärast sisselogimist | vt `adb logcat \| grep CallWatcher` – kui seal on „Token puudub", logi rakenduses uuesti sisse |
| Maya ei helista | akusäästu erand puudub või foreground-teenus tapetud |
| Mikrofon vaikib | luba puudub, või kajavärav saadab nulle (vt serveri logi „läbinisti vaiksed") |
| Heli kokutab | võrgu jitter; vt `JITTER_BUFFER_S` index.html-is |
| Kaamerat ei näe | luba puudub; kontrolli serveri logist, kas kaadrid saabuvad |

Logid: `adb logcat | grep -i maya`

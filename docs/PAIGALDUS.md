# Paigaldus nullist

> **MAYA ei ole teenus, millega liituda.** GitHubis on ainult
> lähtekood ja Androidi APK. **Ükski MAYA server ei jookse GitHubis
> ega kellegi teise arvutis** – sina paigaldad backendi ise, oma
> Gemini API võtmega, ja Androidi rakendus ühendub SINU serveriga.
>
> Järjekord on alati: **1)** backend tööle → **2)** APK telefoni →
> **3)** oma serveri aadress rakenduses → **4)** esimene konto.

## 1. Eeldused

| | Miinimum | Märkus |
|---|---|---|
| Python | 3.11 | testitud 3.13 ja 3.14 peal |
| Android | 8.0 (API 26) | kõnefunktsioon vajab PÄRIS seadet, emulaator ei helista |
| JDK | 17 | Androidi ehitamiseks |
| Gemini API võti | — | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

## 2. Backend

```bash
git clone <sinu-repo> maya && cd maya

python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r server/requirements.txt
```

### Seadistus

```bash
cp .env.example .env
```

Ava `.env` ja täida vähemalt:

```
GEMINI_API_KEY=sinu_voti_siia
MAYA_USER_NAME=SinuNimi
```

#### Oma Gemini API võtme hankimine

1. Ava [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   ja logi oma Google'i kontoga sisse.
2. **„Create API key"** → vali või loo Google Cloudi projekt.
3. Kopeeri võti ja kleebi see `.env` faili ritta `GEMINI_API_KEY=`.
4. **Live API on tasuline** – arveldus peab projektis sisse lülitatud
   olema. Hinnad ja kvoodid: [GEMINI_LIVE.md](GEMINI_LIVE.md).

**Võti jääb ainult serverisse.** Androidi rakendus ei näe seda kunagi:
telefon räägib ainult sinu backendiga ja backend räägib Google'iga.
`.env` on `.gitignore`-is, nii et võti ei satu versioonihaldusesse.
Iga MAYA paigaldaja kasutab oma võtit ja maksab oma kasutuse eest.

Kontrolli, et seadistus loeti:

```bash
python3 server/config.py
```

Väljund näitab teed ja seda, millised võtmed on **seatud** — päris
väärtusi ei trükita kunagi.

### Andmebaas

```bash
python3 server/init_db.py
```

See loob **tühja** andmebaasi (vaikimisi `data/reminders.db`) 17
tabeliga: meeldetuletused, ostunimekiri, päevik, vestlusarhiiv,
mälufaktid ja FTS5 otsinguindeksid. Isiklikke andmeid kaasas ei ole.

Kontroll: `python3 server/init_db.py --check`

### Käivitamine

```bash
cd server && python3 web_maya.py
```

Server kuulab pordil 8000. Kontroll: ava `http://127.0.0.1:8000/docs`.

### Esimene konto

Kõik `/api` otspunktid nõuavad autentimist. **Esimene konto saab
admin-õigused.**

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"sinu_nimi","password":"vahemalt_10_margi_pikk_parool"}'
```

Vastuses on `token`. Kontrolli, et see töötab:

```bash
TOKEN=<kleebi token siia>
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/auth/me
```

Androidi rakenduses saab konto luua ka sisselogimisekraanil
(„Loo uus konto") – siis salvestab rakendus tokeni ise.

Registreerimise sulgemiseks pane `.env`-i `MAYA_ALLOW_REGISTRATION=0`
või nõua kutsekoodi `MAYA_INVITE_CODE=...` – vt
[TURVALISUS.md](TURVALISUS.md).

Logis peaks olema:
```
--> [MÄLUMOOTOR]: SQLite journal_mode=wal
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Kui näed `GROQ_API_KEY puudub` — see on **ootuspärane**, kui sa seda
võtit ei andnud. Hääl töötab sellest hoolimata.

## 3. Androidi rakendus

Täielik juhend: **[ANDROID.md](ANDROID.md)**.

### 3.1. Kust APK saada

Kaks võimalust – mõlemad annavad **sama** rakenduse:

| | |
|---|---|
| **Valmis APK** | hoidla **Releases** leht → `maya-universal.apk`. Kontrolli SHA256 summat, mis on väljalaske juures kirjas. |
| **Ise ehitatud** | `cd android && ./gradlew assembleDebug` → `android/app/build/outputs/apk/debug/app-debug.apk` |

APK on **universaalne**: selles ei ole ühtegi serveriaadressi ega
võtit, seega töötab see iga MAYA paigaldusega.

### 3.2. Paigaldus telefoni

```bash
# Telefonis: Seaded → Teave → vajuta 7× „Järgu number"
#            → Arendaja valikud → USB silumine SISSE
adb install -r maya-universal.apk
```

Ilma arvutita: kopeeri APK telefoni, ava failihalduris ja luba
„Paigalda tundmatutest allikatest".

`-r` hoiab olemasolevad andmed alles. Kui tuleb
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`, siis
`adb uninstall com.maya.live` (see kustutab ainult telefoni andmed –
konto ja mälu on serveris).

### 3.3. Serveri aadress rakenduses

Esimesel käivitusel näitab MAYA **serveri seadistuse ekraani**. Sisesta
oma backendi aadress, näiteks:

```
http://192.168.1.50:8000         (sama WiFi – pane siia OMA IP)
http://100.64.0.5:8000           (Tailscale/WireGuard – OMA IP)
https://maya.example.com         (oma domeen pöördproksi taga)
```

Serveri IP leiad käsuga `./kaivita.sh --ip`. Vajuta **„Testi
ühendust"** – ekraan ütleb otse, kas server vastas ja kas tegemist on
MAYA backendiga. Alles siis **„Salvesta ja jätka"**.

Aadressi saab hiljem muuta: seaded → **„Minu MAYA server"**.

> **Tulemüür:** backend peab kuulama kohtvõrgu liidesel, mitte ainult
> `localhost`-il. `./kaivita.sh` teeb seda ise (`MAYA_HOST=0.0.0.0`).
> macOS küsib esimesel käivitusel tulemüüri luba – vasta „Luba".
> Kiire kontroll: ava telefoni brauseris
> `http://<serveri-ip>:8000/api/auth/status`.

### 3.4. Esimene konto telefonis

Pärast serveri salvestamist tuleb sisselogimisekraan. Vajuta **„Loo
uus konto"** – esimene konto selles paigalduses saab admin-õigused.
Parool peab olema vähemalt 10 märki.

### 3.5. Load ja akusäästu erand

| Mida | Milleks | Kohustuslik? |
|---|---|---|
| Mikrofon | häälvestlus | jah |
| Kaamera | Maya näeb kaamerapilti | ainult kaamera jaoks |
| Teated | sissetulev kõne | jah, kui tahad, et Maya helistaks |
| Galerii/meedia | pildi näitamine | ei |
| **Akusääst: „Piiranguteta"** | **Maya saab ise helistada ka siis, kui ekraan on kustunud** | **jah, kõnefunktsiooni jaoks** |

`Seaded → Rakendused → MAYA → Aku → Piiranguteta`. Xiaomi, Huawei,
OnePlus ja Samsung vajavad ka „Autostart" ja „Lukusta rakendus"
sätteid – vt [ANDROID.md](ANDROID.md).

## 4. Teenusena käivitamine (valikuline, Linux)

```ini
# /etc/systemd/system/maya.service
[Unit]
Description=MAYA Voice Agent
After=network.target

[Service]
Type=simple
User=maya
WorkingDirectory=/opt/maya/server
EnvironmentFile=/opt/maya/.env
ExecStart=/opt/maya/.venv/bin/python /opt/maya/server/web_maya.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now maya.service
journalctl -u maya.service -f
```

## 5. Kontroll-nimekiri

- [ ] `python3 server/config.py` näitab `GEMINI_API_KEY : seatud`
- [ ] `python3 server/init_db.py --check` ütleb `OLEMAS`
- [ ] `http://127.0.0.1:8000/docs` avaneb
- [ ] telefoni brauseris avaneb `http://<serveri-ip>:8000/api/auth/status`
- [ ] APK paigaldatud ja seadistusekraan tuli ette
- [ ] „Testi ühendust" ütleb „MAYA server vastas"
- [ ] Esimene konto loodud ja `/api/auth/me` vastab
- [ ] Androidi rakenduses sisselogimine õnnestub
- [ ] Häälkõne töötab (vt [GEMINI_LIVE.md](GEMINI_LIVE.md), kui ei)
- [ ] Akusäästu erand antud (kõnefunktsiooni jaoks)
- [ ] Testid: `for f in tests/tests_*.py; do python3 "$f"; done`
- [ ] Androidi testid: `cd android && ./gradlew testDebugUnitTest`

## 6. Kui midagi ei tööta

| Sümptom | Põhjus |
|---|---|
| `ModuleNotFoundError` | `pip install -r server/requirements.txt` jäi tegemata või vale venv |
| `RuntimeError: Form data requires "python-multipart"` | sama, `python-multipart` on nüüd nõuete sees |
| `GEMINI_API_KEY on seadistamata` | `.env` puudub või on vales kaustas — vt `python3 server/config.py` |
| Android ei ühendu | vale serveri aadress rakenduses (seaded → „Minu MAYA server"); telefon ja server peavad olema samas võrgus või sama VPN-is |
| Seadistusekraan: „Ühendust ei saadud" | server ei jookse, tulemüür blokeerib, või `MAYA_HOST=127.0.0.1` (kuulab ainult iseennast) |
| Hääl ei tule | vt [GEMINI_LIVE.md](GEMINI_LIVE.md) — kõige sagedam on kvoot või vale mudel |
| `401 Autentimine nurjus` | token puudub või aegunud – logi uuesti sisse |
| WebSocket sulgub kohe (kood 1008) | token ei jõudnud kaasa; kontrolli, et rakendus on sisse logitud |
| `429 Liiga palju päringuid` | kiiruspiirang; oota minut või tõsta `MAYA_RATE_LIMIT` |

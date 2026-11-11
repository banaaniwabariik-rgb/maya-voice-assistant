# Paigaldus nullist

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

Logis peaks olema:
```
--> [MÄLUMOOTOR]: SQLite journal_mode=wal
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Kui näed `GROQ_API_KEY puudub` — see on **ootuspärane**, kui sa seda
võtit ei andnud. Hääl töötab sellest hoolimata.

## 3. Androidi rakendus

Vt **[ANDROID.md](ANDROID.md)**.

Lühidalt:

```bash
# 1. Pane serveri aadress faili android/gradle.properties:
#    mayaBaseUrl=http://<serveri-ip>:8000
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

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
- [ ] Androidi rakendus avaneb ja ühendub
- [ ] Häälkõne töötab (vt [GEMINI_LIVE.md](GEMINI_LIVE.md), kui ei)
- [ ] Testid: `for f in tests/tests_*.py; do python3 "$f"; done`

## 6. Kui midagi ei tööta

| Sümptom | Põhjus |
|---|---|
| `ModuleNotFoundError` | `pip install -r server/requirements.txt` jäi tegemata või vale venv |
| `RuntimeError: Form data requires "python-multipart"` | sama, `python-multipart` on nüüd nõuete sees |
| `GEMINI_API_KEY on seadistamata` | `.env` puudub või on vales kaustas — vt `python3 server/config.py` |
| Android ei ühendu | vale `mayaBaseUrl`; telefon ja server peavad olema samas võrgus |
| Hääl ei tule | vt [GEMINI_LIVE.md](GEMINI_LIVE.md) — kõige sagedam on kvoot või vale mudel |

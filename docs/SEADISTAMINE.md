# Seadistamine

Kogu seadistus elab failis `.env` (vt `.env.example`) ja loetakse
sisse mooduli `server/config.py` kaudu. Süsteemi keskkonnamuutujad
**võidavad** `.env` faili — nii saab systemd või Docker alati peale
jääda.

## Kust .env-i otsitakse

Järjekorras:
1. `MAYA_ENV_FILE` (kui määratud)
2. `<juur>/.env`
3. `<juur>/../.env`

Kontroll: `python3 server/config.py`

## Muutujad

### Kohustuslik

| Muutuja | Selgitus |
|---|---|
| `GEMINI_API_KEY` | Gemini Live häälemootor. Ilma selleta hääl ei tööta. |

### Valikulised välised teenused

| Muutuja | Mis lülitub välja, kui puudub |
|---|---|
| `GROQ_API_KEY` | tekstivestlus ja Whisperi kõnetuvastus |
| `TAVILY_API_KEY` | veebiotsing |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | e-posti lugemine |
| `GMAIL_USER_2` / `GMAIL_APP_PASSWORD_2` | teine postkast |

Puuduv võti **ei tee serverit katki** — ta ütleb käivitamisel logis
välja, mis haru on välja lülitatud.

### Teed

| Muutuja | Vaikeväärtus |
|---|---|
| `MAYA_HOME` | kaust, kus `server/config.py` asub |
| `MAYA_DATA_DIR` | `<MAYA_HOME>/data` |
| `MAYA_DB_PATH` | `<MAYA_DATA_DIR>/reminders.db` |

### Võrk

| Muutuja | Vaikeväärtus | Selgitus |
|---|---|---|
| `MAYA_HOST` | `0.0.0.0` | pane `127.0.0.1`, kui kasutad SSH-tunnelit |
| `MAYA_PORT` | `8000` | |
| `MAYA_PUBLIC_URL` | `http://127.0.0.1:<port>` | ainult dokumentatsiooni ja logi jaoks |

Androidi pool loeb oma aadressi **mitte siit**, vaid failist
`android/gradle.properties` → `mayaBaseUrl`.

### Kasutaja

| Muutuja | Vaikeväärtus | Selgitus |
|---|---|---|
| `MAYA_USER_NAME` | `Kasutaja` | asendab karakteriviipades kohahoidja `{USER}` |
| `MAYA_TIMEZONE` | `Europe/Tallinn` | meeldetuletused ja kellaaeg |
| `MAYA_CONTACT_EMAIL` | `maya@example.org` | muusikaandmebaaside API-de nõutud User-Agent |

Kasutaja saab oma nime ka vestluses muuta („jäta meelde, et minu nimi
on …") — siis salvestub see andmebaasi ja võidab selle muutuja.

### Valikuline kohalik kõnesüntees

| Muutuja | Selgitus |
|---|---|
| `MAYA_PIPER_PYTHON` | Piperi venv'i Python |
| `MAYA_PIPER_HELPER` | `piper_helper.py` tee |

Kasutatakse ainult varuteena. Kui teed on tühjad, varuteed ei kasutata.

## Turvalisus

**MAYA backendil ei ole autentimist.** Kõik allolevad variandid
lahendavad sama probleemi; vali üks.

### 1. Privaatvõrk (soovitatud)

Tailscale, WireGuard või ZeroTier. Server ja telefon on samas
privaatvõrgus, avalikust internetist pääsu ei ole.

```
mayaBaseUrl=http://100.x.y.z:8000
```

### 2. Pöördproksi HTTPS-i ja autentimisega

```nginx
server {
    listen 443 ssl;
    server_name maya.sinu-domeen.ee;
    # ssl_certificate ...;

    location / {
        auth_basic "MAYA";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;   # WebSocket!
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;                 # pikad kõned
    }
}
```
Pane `MAYA_HOST=127.0.0.1`, et server ei kuulaks otse väljapoole.

> Androidi klient ei oska praegu ise Basic-autentimist saata. Kui
> kasutad varianti 2, tuleb see kliendile lisada — see on teadlik
> lahtine koht ja hea esimene panus.

### 3. Ainult kohtvõrk

`MAYA_HOST=127.0.0.1` + SSH-tunnel telefonist. Kõige turvalisem,
kõige ebamugavam.

### Mida mitte teha

- Ära ava porti 8000 avalikku internetti.
- Ära pane `GEMINI_API_KEY`-d Androidi rakendusse — ta elab AINULT serveris.
- Ära commit'i `.env` faili. Kontrolli: `scripts/kontrolli_privaatsust.sh`

# Turvalisus

## Mis on kaitstud

| Ressurss | Kaitse |
|---|---|
| Kõik `/api/*` otspunktid | Bearer-token kohustuslik (v.a 3 avalikku) |
| `GET /api/call_events` (SSE) | token kohustuslik, **kasutajapõhine järjekord** |
| `WS /ws/live_maya` (Gemini Live) | token kontrollitakse **enne** `accept()`; ilma tokenita `close(1008)` |
| `GET /api/billing_state`, `/api/voice_test` | token kohustuslik |
| `/stream_test` (arendusleht) | token kohustuslik |
| Meeldetuletused, mälu, vestlused, seaded | **eraldi andmebaas iga kasutaja kohta** |
| Kõne käivitamine | ainult oma kontole; teisele kasutajale helistada ei saa |

Avalikud on **ainult** `POST /api/auth/register`, `POST /api/auth/login`
ja `GET /api/auth/status` (viimane ütleb ainult, kas paigaldus on
seadistatud – kasutajanimesid ta ei avalda).

Automaatne test `tests/tests_autentimine.py::test_40` käib AST-iga üle
kogu `web_maya.py` ja kukub läbi, kui mõni `/api` otspunkt jääb ilma
autentimist. Nii ei saa uus otspunkt kogemata lahti jääda.

## Kuidas autentimine töötab

```
1. POST /api/auth/register   (esimene konto saab admin-õigused)
   või
   POST /api/auth/login      {"username": "...", "password": "..."}
        ↓
2. Server tagastab tokeni (30 päeva, muudetav MAYA_TOKEN_TTL_S)
        ↓
3. Android salvestab selle SharedPreferences'i (rakenduse privaatne ala)
        ↓
4. HTTP:      Authorization: Bearer <token>
   WS / SSE:  ?token=<token>   (käepigistus ei luba päist)
```

### Paroolid

- Räsitud **`hashlib.scrypt`**-iga (N=2¹⁴, r=8, p=1), iga parool oma
  16-baidise juhusliku soolaga.
- Võrdlus on ajakindel (`hmac.compare_digest`).
- Vale kasutajanimi ja vale parool annavad **sama veateate**, nii et
  kasutajanimesid ei saa loendada.
- Olematu kasutaja korral tehakse siiski scrypt-arvutus, et
  vastamisaeg ei paljastaks konto olemasolu.
- Miinimumpikkus 10 märki.

### Tokenid

- `secrets.token_urlsafe(32)` = 256 bitti entroopiat.
- Andmebaasis hoitakse **ainult SHA-256 räsi**. Lekkinud andmebaasist
  ei saa kehtivat tokenit tagasi arvutada.
- Aegunud token kustutatakse automaatselt.
- `POST /api/auth/logout` tühistab tokeni kohe.
- Konto peatamine (`is_active = 0`) tühistab kõik tokenid kohe.

### Kiiruspiirang

| | Vaikimisi | Muutuja |
|---|---|---|
| API päringud | 120 / min kasutaja või IP kohta | `MAYA_RATE_LIMIT` |
| Sisselogimised | 20 / min | `MAYA_LOGIN_RATE_LIMIT` |
| Ebaõnnestunud sisselogimised | 10 / 5 min **kasutajanime kohta** | koodis `LOGIN_MAX_KATSET` |

Loendurid on mälus. Teadlik kompromiss: protsessi taaskäivitus nullib
need, aga Redise sõltuvus ei ole isikliku paigalduse jaoks seda väärt.

## Kasutajate eraldatus

```
data/
├── users.db                      ← kontod ja tokenid (EI OLE kellegi oma)
└── users/
    ├── 1/reminders.db            ← kasutaja 1 KÕIK andmed
    └── 2/reminders.db            ← kasutaja 2 KÕIK andmed
```

**Miks failisüsteem ja mitte `WHERE user_id = ?`:** originaalkood on
13 000 rida kümnete SQL-päringutega. Kui eraldatus sõltuks sellest, et
iga päring mäletab filtrit, piisaks **ühest** puuduvast `WHERE`-ist, et
üks kasutaja näeks teise mälufakte. Eraldi failiga on see füüsiliselt
võimatu ja uus funktsioon ei pea `user_id`-d meeles pidama.

Tehniliselt: `config.sea_aktiivne_kasutaja(uid)` seab
`contextvars` muutuja ja `config.connect()` avab selle põhjal õige
faili. FastAPI iga päring jookseb omas kontekstis, seega samaaegsed
päringud ei näe üksteise konteksti.

**Kompromiss, mille me teadlikult võtame:** kasutajate vahel ei saa
andmeid jagada ega üleste päringuid teha. Isikliku assistendi puhul on
see pigem omadus.

## Sisendi valideerimine

| Mis | Kuidas |
|---|---|
| Kasutajanimi | `^[a-zA-Z0-9_.-]{3,32}$` – välistab tee- ja SQL-rünnakud |
| Tekstiväljad | pikkusepiirang + juhtmärkide (sh `NUL`) eemaldamine |
| Karakteri ID | peab olema registris olemas, muidu 400 |
| Täisarvud | vahemikukontroll |

SQL-päringud kasutavad parameetreid (`?`), mitte stringi liitmist.

## Mida see EI kaitse

Aus nimekiri – need on teadlikud piirangud, mitte unustatud augud:

1. **HTTP, mitte HTTPS.** Autentimine kaitseb volitamata kasutaja
   eest, **mitte pealtkuulamise eest**. Samas võrgus olev ründaja
   näeb tokenit ja heli. **Lahendus:** privaatvõrk (Tailscale/
   WireGuard) või pöördproksi HTTPS-iga.
2. **Token URL-is WS/SSE puhul.** Token võib jõuda pöördproksi
   juurdepääsulogidesse. Androidi SSE-klient kasutab `Authorization`
   päist; URL-i varianti vajab ainult WebSocket.
3. **Andmebaas on krüpteerimata SQLite.** Serveri failisüsteemile
   pääseja loeb kõike. Kasuta krüpteeritud ketast.
4. **Gemini API võti elab serveris.** Serverini pääseja saab seda
   kasutada. Võtit ei saadeta kunagi kliendile.
5. **Admin ei ole piiratud.** Admin näeb arveldust ja saab paigalduse
   seadeid muuta. Ta **ei näe** teiste kasutajate vestlusi ega mälu
   (eraldi andmebaasid), aga saab failisüsteemi kaudu kõike.
6. **Kiiruspiirang on protsessipõhine.** Mitme töölise (`workers > 1`)
   korral korrutub piirang tööliste arvuga.
7. **CSRF-i pole, sest küpsiseid pole.** Kui keegi lisab küpsispõhise
   sisselogimise, tuleb CSRF-kaitse eraldi lisada.

## Soovitatud paigaldus

```
Telefon ──Tailscale/WireGuard──► Server (MAYA_HOST=0.0.0.0, port 8000)
```

Avaliku serveri puhul:

```nginx
server {
    listen 443 ssl;
    server_name maya.sinu-domeen.ee;
    # ssl_certificate ...;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;     # WebSocket
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;                   # pikad kõned + SSE
        proxy_buffering off;                        # SSE vajab
    }
}
```
ja `MAYA_HOST=127.0.0.1`, et server ei kuulaks otse väljapoole.

## Registreerimise piiramine

```bash
MAYA_ALLOW_REGISTRATION=0        # keegi uus ei saa kontot luua
MAYA_INVITE_CODE=mingi-pikk-juhuslik-sõna   # kutsekood nõutud
```
Esimene konto saab alati luua, isegi kui registreerimine on suletud –
muidu ei saaks paigaldust kasutusele võtta.

## Turvaaugu teatamine

Vt [../SECURITY.md](../SECURITY.md). **Ära ava avalikku issue't.**

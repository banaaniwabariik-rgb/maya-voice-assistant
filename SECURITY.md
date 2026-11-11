# Turvapoliitika

## Turvaaugu teatamine

**Ära ava turvaaugu kohta avalikku issue't.**

Kasuta GitHubi privaatset teatamist:
**Security → Advisories → Report a vulnerability**

Kui see ei ole võimalik, kirjuta hoidla haldajale privaatselt.

> **Siin ei jookse ühtegi MAYA teenust.** Hoidla levitab lähtekoodi ja
> APK-d; iga kasutaja käivitab backendi ise oma masinas. Seega ei ole
> siin „tootmiskeskkonda", mille vastu testida — ja teade puudutab
> alati koodi, mitte mingit töötavat paigaldust.

Palun lisa:
- mida sa tegid ja mis juhtus;
- kas auk on kaugelt kasutatav;
- mõjutatud versioon või commit;
- kui võimalik, minimaalne näide.

Vastame nii kiiresti kui jõuame. See on vabatahtlik projekt, nii et
palun arvesta päevade, mitte tundidega.

## Mida me PALUME mitte teha

- Ära testi kellegi teise MAYA paigalduse vastu ilma selle omaniku loata.
- Ära lisa issue'sse ega pull request'i päris API võtmeid, logisid ega
  vestluste sisu. Kui vajad näidet, asenda väärtused kohahoidjatega.

## Mis kaitse ON olemas

1. **Autentimine kõigil otspunktidel.** Iga `/api` otspunkt, SSE-vool
   ja Gemini Live WebSocket nõuavad kehtivat tokenit. Paroolid on
   soolatud `scrypt`-räsid, tokenitest hoitakse ainult SHA-256 räsi.
2. **Kasutajate eraldatus failisüsteemi tasandil.** Iga kasutaja mälu,
   meeldetuletused, vestlused ja seaded elavad **eraldi andmebaasis** —
   üks kasutaja ei näe teise andmeid ega saa talle helistada.
3. **Ühekordne WebSocketi pilet.** Pikaealine token ei jõua kunagi
   URL-i: WebSocketi jaoks väljastatakse eraldi pilet, mis kehtib
   60 sekundit ja ainult ühe ühenduse jaoks.
4. **Kiiruspiirang** sisselogimisel, et paroole ei saaks jõuga murda.

Täielik ülevaade: [docs/TURVALISUS.md](docs/TURVALISUS.md).

## Teadaolevad piirangud (ei ole „augud", vaid disainivalikud)

Need on teadlikult sellised ja dokumenteeritud:

1. **HTTP ei ole krüpteeritud.** Vaikimisi räägib Androidi klient
   serveriga HTTP-s, sest kohtvõrgus ei ole sertifikaate.
   **Autentimine kaitseb volitamata kasutaja eest, mitte
   pealtkuulamise eest.** Avalikku internetti minnes on **HTTPS/WSS
   kohustuslik** — kasuta pöördproksit (nginx/Caddy). Rakendus ise
   hoiatab, kui aadress on `http://` ja host ei ole kohtvõrgus.
2. **Andmebaas on krüpteerimata SQLite.** Mälufaktid ja vestlusarhiiv
   on tavatekstina. Kui see on oluline, kasuta krüpteeritud
   failisüsteemi.
3. **Gemini API võti elab serveris.** Kes serverini pääseb, saab võtit
   kasutada. Võti ei ole kunagi APK-s ega jõua Androidi kliendini.
4. **Registreerimine on vaikimisi avatud**, et esimene konto saaks
   üldse tekkida. Pärast oma kontode loomist pane
   `MAYA_ALLOW_REGISTRATION=0` või nõua `MAYA_INVITE_CODE`-i.
5. **Vestluse sisu läheb Google'ile.** Hääle annab Gemini Live API —
   kõne ja kaamerapilt liiguvad Google'i serveritesse ning kehtivad
   Google'i tingimused. MAYA ei saa seda muuta.
6. **APK on allkirjastatud Androidi debug-võtmega.** Hoidlas ei ole
   ühtegi allkirjastamisvõtit. Püsipaigalduseks tee oma keystore —
   vt [docs/ANDROID.md](docs/ANDROID.md).

## Saladuste käsitlemine

- `.env` on `.gitignore`-is ja peab seal püsima.
- `.env.example` sisaldab AINULT kohahoidjaid.
- Enne commit'i jooksuta `scripts/kontrolli_privaatsust.sh` — see otsib
  võtmemustreid, IP-aadresse ja andmebaasifaile.
- Kui võti on kogemata commit'itud: **tühista võti kohe** (Google AI
  Studios / Groq konsoolis). Ajaloost kustutamine üksi ei aita — võti
  tuleb lugeda lekkinuks.

## ⚠️ Varajane eelvaade — loe enne paigaldamist

See APK on **eelvaade**, mitte valmis toode.

**Mida see APK EI tee:** ta ei tööta üksinda. MAYA aju elab **sinu enda
serveris** ja kasutab **sinu enda Gemini API võtit**. Ilma serverita
näitab rakendus ainult seadistusekraani.

### Mida sul on vaja

| | |
|---|---|
| **Android 8.0+** (API 26) | vanem ei tööta |
| **Oma MAYA backend** | vt [paigaldusjuhend](https://github.com/banaaniwabariik-rgb/maya-voice-assistant/blob/main/docs/PAIGALDAMINE.md) — arvuti, koduserver või VPS |
| **Oma Gemini API võti** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). **Google arveldab selle sinule**, mitte MAYA projektile |

Võti jääb **serverisse**. APK-s ei ole võtit ega ühtegi serveriaadressi.

### Paigaldamine

1. Lae `maya-*.apk` alla telefoni.
2. Android küsib luba „tundmatust allikast" paigaldamiseks — see on
   normaalne, sest APK ei tule Play poest. Luba ainult sellele brauserile
   või failihaldurile, millega sa faili avasid.
3. Ava APK ja paigalda.
4. Esimesel käivitusel küsib rakendus **sinu serveri aadressi**
   (nt `http://192.168.1.50:8000`). Sisesta see ja vajuta „Testi
   ühendust" — rakendus ütleb ausalt, kas ühendus õnnestus.

Aadressi saab hiljem muuta seadistusekraanilt; see salvestub telefoni,
mitte APK-sse.

### Aus seis

- **Originaal töötab:** MAYA on käinud OnePlus 6-l mitu kuud ja
  README demovideo on sellelt telefonilt.
- **Seda avalikku ehitust ei ole päris seadmes läbi testitud.** Ta on
  ehitatud ja baithaaval üle kontrollitud (aadresse ega võtmeid ei ole),
  aga keegi ei ole seda konkreetset APK-d telefonis läbi proovinud.
  Kui proovid — [ava issue](https://github.com/banaaniwabariik-rgb/maya-voice-assistant/issues)
  ja ütle, kas töötas. See on praegu kõige kasulikum panus.
- **Rakenduse keel on eesti keel.**

### Allkiri

APK on allkirjastatud projekti püsiva võtmega, nii et järgmised
väljalasked paigalduvad selle peale uuendusena. Sõrmejälge saad enne
uuendamist võrrelda:

```
apksigner verify --print-certs maya-*.apk
```

Võti ei ole hoidlas ega käi kunagi Gitist läbi.

### Turvalisus

Vaikimisi räägib rakendus serveriga **HTTP-s**, mis sobib kodusesse
võrku. Kui avad serveri avalikku internetti, on **HTTPS/WSS
kohustuslik** — vt
[TURVALISUS.md](https://github.com/banaaniwabariik-rgb/maya-voice-assistant/blob/main/docs/TURVALISUS.md).

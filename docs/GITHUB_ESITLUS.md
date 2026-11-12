# GitHubi esitlus — valmis tekstid

Siin on **kopeeri-ja-kleebi** tekstid GitHubi hoidla väljade jaoks.
Hoidla on avaldatud:
**https://github.com/banaaniwabariik-rgb/maya-voice-assistant**

Need tekstid on alles, et esitlus jääks ühtseks ja et ükski väide ei
läheks koodiga vastuollu — nii saab neid uuesti kasutada ka
postitustes, awesome-nimekirjades ja väljalaskemärkmetes.

Iga väide allpool on koodist üle kontrollitud. **Mitte ühtegi
funktsiooni ei reklaamita, mis ei tööta.**

---

## A. Hoidla kirjeldus (GitHubi „Description" väli)

GitHubi kirjelduse väli lõikab ~350 märgi pealt. Esimene variant mahub
kindlasti ära.

**Eelistatud (158 märki):**

```
Maya helistab sulle. Mitte vastupidi. Eestikeelne AI-häälkaaslane: ise algatatud kõned telefonile, loomulik häälvestlus, mälu ja meeldetuletused. Self-hosted.
```

**Lühem variant (118 märki),** kui tahad, et see mahuks ka mobiilivaates ühele reale:

```
Maya helistab sulle. Mitte vastupidi. Eestikeelne AI-häälkaaslane ise algatatud kõnedega. Self-hosted, Apache-2.0.
```

**Ingliskeelne variant,** kui eelistad rahvusvahelist leitavust (eesti
loosung jääb ikka README ja identiteedi keskmesse):

```
Maya helistab sulle. Mitte vastupidi. — Estonian-first AI voice companion with self-initiated calls, natural voice conversation, long-term memory and reminders. Self-hosted.
```

> **Miks mitte „kalender":** kalender on praegu vaade meeldetuletuste
> peal, ilma eraldi sündmusetabeli ja välise sünkroonimiseta. Kirjelduses
> seda eraldi funktsioonina ei nimetata.

---

## B. Loosung

**Projekti põhiidentiteet, eesti keeles:**

```
Maya helistab sulle. Mitte vastupidi.
```

Ingliskeelne tõlge (ainult selgituseks, mitte asendusena):
*„Maya calls you. Not the other way round."*

Pikem kandev kirjeldus README jaoks:

```
Eestikeelne tehisintellekti kaaslane, kes räägib sinuga loomulikult,
peab meeles sinu tegemisi ja tuletab olulisi asju meelde.
```

---

## C. GitHubi teemad (Topics)

GitHub lubab **kuni 20 teemat**; nad peavad olema väiketähtedega ja
sidekriipsudega. Allolev nimekiri on 20 pikk ja järjestatud tähtsuse
järgi — kui tahad vähem, lõika lõpust.

```
estonian
estonian-language
voice-assistant
ai-companion
gemini-live
gemini-api
self-hosted
android
fastapi
python
voice-ai
speech
realtime-audio
websocket
sqlite
personal-assistant
reminders
long-term-memory
estonian-nlp
kotlin
```

**Miks just need:**

| Teema | Põhjus |
|---|---|
| `estonian`, `estonian-language`, `estonian-nlp` | **tähtsaimad.** Just nende kaudu leiavad eestikeelset tehnoloogiat otsivad inimesed projekte ([github.com/topics/estonian](https://github.com/topics/estonian)) |
| `voice-assistant`, `voice-ai`, `ai-companion`, `speech` | kategooria, mida inimesed päriselt otsivad |
| `gemini-live`, `gemini-api` | Gemini Live häälrakendusi on vähe; need teemad toovad sihitud huvilisi |
| `self-hosted` | suur ja aktiivne kogukond, kellele „sinu enda server" on müügiargument |
| `android`, `kotlin` | klient on Androidi rakendus |
| `fastapi`, `python`, `websocket`, `sqlite`, `realtime-audio` | tehniline pind panustajatele |
| `personal-assistant`, `reminders`, `long-term-memory` | funktsioonipõhine leitavus |

---

## D. Lühike ingliskeelne kirjeldus (rahvusvahelistele arendajatele)

**Üks lõik (nt „About" jaotis, Hacker News / Reddit postituse algus,
awesome-nimekirja kirje):**

```
MAYA is a self-hosted, Estonian-first AI voice companion for Android.
Unlike a chatbot that waits for you to open it, MAYA pushes a call alert
to your phone and starts the conversation itself: the phone rings over
the lock screen and you talk to it in natural Estonian through the Gemini
Live API (native audio, interruptible mid-sentence). It keeps long-term
memory with Estonian-morphology search, has 10 characters with their own
voices, takes the initiative after a pause, and resumes a sentence that
got cut off. Everything runs on your own machine with your own Gemini API
key — there is no central service and the project cannot see your data.
Python/FastAPI backend, Kotlin/WebView Android client, SQLite, Apache-2.0.
```

**Kaks lauset (lühike tutvustus):**

```
MAYA is a self-hosted Estonian-first AI voice companion that calls your
Android phone and starts the conversation itself, instead of waiting for
you to open an app. Natural Estonian voice conversation via Gemini Live,
long-term memory, 10 characters, reminders — all on your own server with
your own API key.
```

**Üks rida (awesome-nimekirja stiilis):**

```
MAYA — self-hosted Estonian AI voice companion that calls your phone first. Gemini Live, long-term memory, 10 characters, Android. (Apache-2.0)
```

---

## E. Mida esitluses MITTE lubada

Need on koodist üle kontrollitud ja **ei tohi** kirjeldusse, loosungisse
ega postitustesse sattuda enne, kui nad päriselt töötavad:

| Ära ütle | Miks |
|---|---|
| „helistab nagu päris telefonikõne" | **ei ole mobiilikõne** — tõuketeade serverist, mis avab rakenduses kõneekraani. Ei kasuta SIM-i, numbrit ega kõnelogi |
| „eestikeelne mudel" | Gemini Live on **mitmekeelne** mudel; eesti keel tuleb eestikeelsetest viipadest |
| „kalender" iseseisva funktsioonina | kalender on vaade meeldetuletuste peal; eraldi sündmusetabelit ega välist sünkroonimist ei ole |
| „see avalik ehitus on päris telefonis testitud" | originaal on OnePlus 6-l mitu kuud käinud, aga **seda avalikku ehitust** ei ole päris seadmes läbi testitud. Ära aja neid kahte segi — ja ära ütle ka vastupidist, nagu poleks MAYA kunagi telefonis töötanud |
| „testitud Gemini Live'iga" | elutsükli testid kasutavad **jäljendatud** seanssi ja kella |
| ekraanipildid, kasutajate arv, kiirusnumbrid, kogukonna suurus, tagasiside | **ei ole olemas** — ära leiuta |
| „valmis APK allalaadimiseks" | binaare hoidlas ei ole; APK ehitatakse ise või tuleb Releases'i kaudu, kui väljalase tehakse |

---

## F. Enne avaldamist

- [x] ~~Asenda `<hoidla-aadress>` päris Giti aadressiga~~ — tehtud, kõik juhendid kasutavad päris kloonimise aadressi
- [ ] Lisa hoidlale ülalolev kirjeldus ja teemad
- [ ] Otsusta autoriõiguse rida failis [NOTICE](../NOTICE) (praegu projektipõhine)
- [ ] Jooksuta `./scripts/kontrolli_privaatsust.sh` ja testid
- [ ] Kui teed väljalaske: ehita APK, lisa SHA-256 summa

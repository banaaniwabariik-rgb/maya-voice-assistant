# Karakterid

## Kuidas see töötab

Kõik karakterid elavad **ühes failis**: `server/persona_registry.py`.
See on teadlik valik — varem olid definitsioonid kolmes kohas laiali
ja sama karakter käitus erinevalt sõltuvalt sellest, kust vestlus
algas.

```python
PERSONAS = {
    'sober': Persona(
        id='sober',
        display_name='SÕBER',
        aliases=(),
        prompt_voice='...',      # häälerada (Gemini Live)
        prompt_text='...',       # tekstirada (valikuline, võib olla None)
        voice='Aoede',           # Gemini hääl
        is_default=False,
        accepts_custom_prompt=False,
    ),
}
```

| Väli | Selgitus |
|---|---|
| `prompt_voice` | häälevestluse süsteemiviip |
| `prompt_text` | tekstivestluse viip. `None` = see karakter on ainult häälele |
| `voice` | Gemini hääl: `Aoede`, `Kore`, `Leda`, `Zephyr` |
| `accepts_custom_prompt` | kas kasutaja juhis liidetakse. **AINULT `custom`** |
| `{USER}` | kohahoidja, mis asendatakse kasutaja nimega |

## ⚠️ Avaliku versiooni karakterid on NÄIDISED

Selles hoidlas olevad karakteriviibad on **üldised näited**.
Originaalpaigalduse isiklikud viibad on teadlikult välja jäetud.

Kirjuta oma karakterid ise. Mehhanism, ID-d, hääled, algatustasemed ja
kohandatud karakteri loogika on originaaliga identsed.

## Oma karakteri lisamine

1. Lisa kirje `PERSONAS` sõnastikku.
2. Kui tahad algatustaset (kui kiiresti ja kui palju ta ise sõna
   võtab), lisa kirje `server/conversation_flow.py` tabelisse
   `INITIATIVE`:

```python
INITIATIVE = {
    "zen":      {"pause_s": 12.0, "budget": 1},   # rahulik, harva
    "sober":    {"pause_s":  7.0, "budget": 2},
    "filosoof": {"pause_s":  5.0, "budget": 3},   # jutukas
}
INITIATIVE_DEFAULT = {"pause_s": 8.0, "budget": 2}
```

| | |
|---|---|
| `pause_s` | mitu sekundit vaikust enne, kui karakter ise sõna võtab |
| `budget` | mitu korda järjest ta tohib sõna võtta ilma, et sina vahele räägiksid |

**Algatustase EI ELA karakteriviibas.** See on meelega eraldi, et
viibasid saaks muuta ilma ajastust puutumata.

3. Uuenda testi `tests/tests_vestluse_elutsykkel.py` →
   `test_20c_persona_registry_on_PUUTUMATA` räsi. See test kaitseb
   selle eest, et karakterid ei muutuks **kogemata**.

## Kohandatud karakter (`custom`)

Ainus karakter, kelle külge liidetakse kasutaja enda juhis:

```
<baasviip> + " KASUTAJA KOHANDATUD ROLL JA JUHEND: " + <sinu juhis>
```

Juhis tuleb WebSocketi parameetrina `custom_prompt`.

### Õppetund, mis maksis mitu seanssi

Baasviip **ei tohi dikteerida tooni**, mida kasutaja juhis võib
tahta muuta. Originaalis ütles baasviip „pehme, sametine, vaoshoitud"
ja kasutaja juhis „kuri, vulgaarne". Mudel kirjutas oma mõttekäigus
otse välja: *„I'm wrestling with these instructions… a bit
overwhelming"* — ja tema voorud katkesid **4/4 korral (100%)**, kui
samal ajal teine karakter katkes 0/8.

Pärast vastuolu eemaldamist langes katkemine **12,5%** peale.

Seega: kui karakter võtab kohandatud juhise, pane baasviipa
prioriteedireegel:

```
VASTUOLUDE REEGEL: kui miski ülaltoodust läheb vastuollu kasutaja
kohandatud juhisega, kehtib ALATI kohandatud juhis. Ära kaalu ega
analüüsi juhiseid omavahel – võta roll kohe omaks ja räägi.
```

## Vastutus sisu eest

Turvaseaded on `BLOCK_NONE` (vt [GEMINI_LIVE.md](GEMINI_LIVE.md)).
Mida sinu karakterid räägivad, on **sinu vastutus**, ja Google'i
kasutustingimused kehtivad sõltumata sellest, mida sa viipa kirjutad.

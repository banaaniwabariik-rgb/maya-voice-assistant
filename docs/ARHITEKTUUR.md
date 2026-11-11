# Arhitektuur

## Üldpilt

```
 Androidi rakendus                      Server (FastAPI)              Google
 ─────────────────                      ────────────────              ──────
 MainActivity                                                              
   └─ WebView (index.html)                                                 
        ├─ mikrofon ──PCM16 16kHz──┐                                       
        ├─ kaamera ──JPEG 768px────┤                                       
        └─ heli välja ◄─24kHz PCM──┤                                       
                                   │                                       
                        WebSocket  └──►  live_maya_ws.py  ──WebSocket──►  Gemini
                        /ws/live_maya      (vestluse voog)   (v1alpha)     Live
                                   ┌──►  web_maya.py                       
 CallWatcherService ──SSE──────────┘      (HTTP API, SSE)                  
   └─ IncomingCallActivity               │                                 
                                         ├─► memory_engine / memory_fts    
                                         ├─► listen_direct (meeldetuletused)
                                         └─► features_pack (veeb, PDF, YT) 
                                              SQLite (reminders.db)        
```

## Moodulid

| Moodul | Roll |
|---|---|
| `web_maya.py` | FastAPI rakendus: HTTP API, SSE kõnesündmused, tekstirada |
| `live_maya_ws.py` | **Gemini Live seanss**: heli sisse/välja, VAD, tööriistad, taaste, omaalgatus |
| `conversation_flow.py` | **puhas** olekumasin: vestluse elutsükkel, taaste- ja algatuspoliitika |
| `persona_registry.py` | karakterid: viibad, hääled, kohandatud juhise loogika |
| `memory_engine.py` | vestluse arhiveerimine, faktide eraldamine |
| `memory_fts.py` | FTS5 otsing, eesti keele morfoloogia, faktide ulatus |
| `privacy_scope.py` | privaatsusjuhiste rakendamine faktitasemel |
| `user_profile.py` | kasutaja nimi ja seaded |
| `listen_direct.py` | meeldetuletused, ostunimekiri, päevik |
| `features_pack.py` | veebiotsing, lehtede/PDF-ide lugemine, YouTube |
| `maya_brain.py` | tekstirada ja süsteemipromptide koostamine |
| `maya_singing_pipeline.py` | laulusõnad, helistik, tempo |
| `streaming_engine.py` | voogedastus tekstirajal |
| `mari_fallback.py` | varuhääl, kui Gemini ei vasta — kasutaja ei jää vaikuse ette |
| `email_tool.py` | Gmail IMAP |
| `global_pulse.py` | uudiste/konteksti kokkuvõtted |
| `billing_admin.py` | krediidi ja kulu haldus |
| `auth.py` | **autentimine, tokenid, kasutajate eraldatus** (avaliku versiooni lisa) |
| `config.py` | **kogu seadistus ühes kohas** (avaliku versiooni lisa) |
| `init_db.py` | tühja andmebaasi loomine (avaliku versiooni lisa) |

## Vestluse elutsükkel

`conversation_flow.py` on **puhas moodul**: ei võrku, ei andmebaasi,
ei `asyncio`-t, ei kellaaega. Kogu otsustusloogika on seal ja
testitav ilma Geminit jäljendamata. Staatiline test nõuab seda
puhtust.

### Olekud

```
AWAITING_USER ──kasutaja räägib──► USER_SPEAKING
      ▲                                  │
      │                                  ▼
      │                            GENERATING ──► Maya räägib
      │                                  │
      │                    ┌─────────────┴─────────────┐
      │                    ▼                           ▼
      └──küsimus──── COMPLETE_IDLE              INCOMPLETE
                     (loomulik lõpp)            (lause jäi pooleli)
                           │                           │
                    karakteri paus               taastepalve
                           ▼                           ▼
                     omaalgatus                 jätkab samast kohast
```

### Taaste (pooleli jäänud lause)

Gemini preview-mudel lõpetab genereerimise vahel keset lauset —
mõõdetud määr oli **42,9%** (9/21 vooru). MAYA tunneb selle ära
(viimane sõna ei lõpe lausemärgiga) ja palub automaatselt jätkata.

| | |
|---|---|
| eelarve | **12** katset ühe kasutajavooru kohta |
| ooteaeg | **0,0 s** kõigil katsetel |
| ahela nullimine | iga kasutaja kõnevoor |
| kordusekaitse | kui mudel hakkab sama lauset uuesti ütlema, ahel peatub |

Taaste jookseb **omas taskis** — vastuvõtutsükkel peab jääma vabaks
kasutaja heli vastu võtma. See oli varem viga: ootamine toimus
vastuvõtutsükli sees ja kasutaja kõne hilines.

### Omaalgatus

Pärast loomulikku lõppu võtab karakter ise sõna, kui vaikus kestab
kauem kui `pause_s`. Eelarve piirab monoloogi; eelarve nullistub
**ainult kasutaja kõne peale**.

**Esimese vooru värav:** Maya ei alusta vestlust KUNAGI enne, kui
kasutaja on vähemalt ühe vooru lõpetanud. Ainult aja möödumine seansi
avanemisest ei anna kõneõigust.

### Kasutaja prioriteet

Kolm sõltumatut kaitsekihti:

1. **Vooru loendur** (`_kasutaja_voor`) — kasvab iga kasutaja kõne
   peale; ootel taaste jäädvustab selle ja aegunud taastet ei saadeta.
2. **Kohene tühistamine** — kasutaja kõne, katkestus ja seansi lõpp
   tühistavad ootel taaste kohe.
3. **Valideerimine saatmisluku all** — vahetult enne kirjutamist
   kontrollitakse olekut uuesti, nii et teine saatja ei mahu vahele.

### Seansi sulgemine

Üks protseduur (`_sulge_seanss`), mis jookseb **`async with` sees**,
st Gemini seanss sulgub alles pärast taskide lõppu:

```
1. uut tööd ei võeta vastu (running = False)
2. ootel voogutegevused kehtetuks (flow.on_conversation_end())
3. tühista seansi taskid – iga ÜKS kord
4. FAAS 1: oota 2 s
5. FAAS 2: kui mõni elab → katkesta transport → oota 2 s
6. FAAS 3: kui ikka elab → raporteeri EBAÕNNESTUMINE (ei kuuluta edu)
```

Mälu konsolideerimise task **peab seansi üle elama** ja seda ei
tühistata.

## Mälu

| Kiht | Mis |
|---|---|
| Töömälu | käimasoleva kõne voorud mälus |
| Vestlusarhiiv | `conversation_archive` + `archive_fts` (FTS5) |
| Faktid | `memory` + `memory_fts`, eesti morfoloogiaga normaliseerimine |
| Ulatus | fakt on vaikimisi **jagatud** kõigi karakterite vahel; `scope='private'` piirab |
| Privaatsus | `privacy_scope.py` rakendab juhise **konkreetsele faktile**, mitte kogu seansile |

Eesti keele morfoloogia: `stem_et`, `normalize_fact`,
`derive_subject_key`, `subject_similarity` (lävend 0,50) — et
„Jaan sõidab BMW-ga" ja „Jaanil on BMW" ei tekitaks kahte fakti.

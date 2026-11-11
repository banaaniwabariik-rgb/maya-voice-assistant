# Mitu telefoni, mitu kontot

## Kaks võimalust

### A. Sama konto mitmes telefonis

```
Telefon 1 ─┐
           ├─► konto "jaan"  ─► data/users/1/reminders.db
Telefon 2 ─┘
```

| | Käitumine |
|---|---|
| Mälu, meeldetuletused, vestlusarhiiv | **jagatud** – mõlemas telefonis sama |
| Karakteri seaded, kasutaja nimi | **jagatud** |
| Kõneteade | **mõlemad telefonid helisevad korraga** |
| Vastamine | kumb iganes vastab, see saab vestluse; teine telefon jääb helisema kuni ajalõpuni |
| Häälvestlus | iga telefon avab **oma** Gemini Live seansi (= oma kulu) |
| Sisselogimine | kummalgi telefonil oma token; väljalogimine ühes ei mõjuta teist |

**Kus see on mõõdetud:** `tests/tests_autentimine.py::TestMituTelefoni::test_70`

> **Leitud ja parandatud 11.11.2026:** algselt oli üks `asyncio.Queue`
> kasutaja kohta ja `Queue.get()` annab iga elemendi **ainult ühele**
> tarbijale – kaks telefoni tähendas, et heliseb juhuslikult üks neist.
> Nüüd kopeeritakse sündmus kõigile ühendatud seadmetele.

### B. Eri kontod

```
Telefon 1 ─► konto "jaan"  ─► data/users/1/reminders.db
Telefon 2 ─► konto "mari"  ─► data/users/2/reminders.db
```

| | Käitumine |
|---|---|
| Mälu, meeldetuletused, vestlused, seaded | **täiesti eraldi** |
| Kõneteade | jõuab **ainult** selle konto seadmetele |
| Teise andmete nägemine | **võimatu** – eraldi andmebaasifailid |

**Kus see on mõõdetud:** `test_22` (meeldetuletused), `test_23`
(mälufaktid), `test_24` (seaded), `test_34` (HTTP kihil), `test_71`
(kõneteated).

## Mida server logib

```
--> [KÕNE]: seade ühendus kõneteadetele (kasutaja #1, seadmeid nüüd 2)
--> [KÕNE]: seade lahkus (kasutaja #1, seadmeid alles 1)
--> [KÕNE]: ükski seade ei ole ühendatud (kasutaja #1) – kõneteade jäi
            kohale toimetamata
```

Viimane rida on oluline tõrkeotsinguks: kui kõne ei tule, näitab see,
kas probleem on serveris (keegi ei ole ühendatud) või telefonis
(ühendatud, aga ei helise).

## Kulu mitme seadmega

Kõneteated on tasuta. **Iga avatud Gemini Live seanss on eraldi
tasuline.** Kui mõlemad telefonid vastavad samale kõnele, maksad kahe
seansi eest. Tavakasutuses juhtub seda harva, sest teine telefon
lõpetab helisemise, kui esimene vastab ja kõneteate aken sulgub.

## Mida EI OLE

- **Seadmehaldust ei ole.** Ei saa öelda „helista ainult autos olevale
  telefonile". Kõik sisse logitud seadmed helisevad.
- **Seadmete nimekirja ei ole.** Server teab ainult ühenduste arvu,
  mitte seda, milline telefon on milline.
- **Tokenite loendit kasutajale ei näidata.** Väljalogimine tühistab
  ainult selle seadme tokeni. Kõigi seadmete korraga välja logimiseks
  on funktsioon `auth.logi_valja_koik(uid)`, aga sellele ei ole veel
  otspunkti – hea esimene panus.

## Konto lisamine

Kui `MAYA_ALLOW_REGISTRATION=1` (vaikimisi), saab uue konto luua
sisselogimisekraanil „Loo uus konto".

Avalikus võrgus pane pärast oma kontode loomist:
```bash
MAYA_ALLOW_REGISTRATION=0
```
või nõua kutsekoodi:
```bash
MAYA_INVITE_CODE=pikk-juhuslik-sõna
```

**Esimene konto saab alati admin-õigused** ja seda saab luua ka siis,
kui registreerimine on suletud – muidu ei saaks paigaldust kasutusele
võtta.

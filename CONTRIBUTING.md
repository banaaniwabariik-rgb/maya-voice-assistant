# Panustamine

Aitäh, et tahad MAYA-t paremaks teha.

## Litsents ja panuse tingimused

MAYA on **Apache License 2.0** all (vt [LICENSE](LICENSE)).

Kui saadad pull request'i, tuleb **sinu panus sisse sama litsentsi
all** — nii ütleb Apache-2.0 §5:

> Unless You explicitly state otherwise, any Contribution
> intentionally submitted for inclusion in the Work … shall be under
> the terms and conditions of this License.

Praktikas tähendab see:

- **Sina jääd oma panuse autoriõiguse omanikuks.** Autoriõigust
  kellelegi üle ei anta ja allkirjastatavat lepingut (CLA) praegu ei
  nõuta.
- Panust saates annad Apache-2.0 §2 ja §3 järgi **autoriõiguse- ja
  patendiloa** kõigile, kes MAYA-t kasutavad.
- **Saada ainult koodi, mille saatmiseks sul on õigus.** Ära kopeeri
  teiste projektide koodi ilma litsentsi kontrollimata; eriti ära too
  sisse GPL/AGPL koodi — see ei ühildu Apache-2.0 projektiga.
- Kui tood sisse kolmanda osapoole koodi või varasid, **ütle PR-is
  selgelt, mis need on ja mis litsentsi all**. Nõutud teated tuleb
  alles hoida (`NOTICE`, failipäised).
- Kui muudad olemasolevat faili oluliselt, ootab Apache-2.0 §4b, et
  muudatus oleks tuvastatav. Git-ajalugu ja selge commit'i sõnum
  katavad selle.

Uue sõltuvuse lisamine on **eraldi arutelu teema**: ava enne issue ja
ütle sõltuvuse litsents välja — vt
[docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

## Enne kui alustad

1. **Ava issue** ja kirjelda, mida tahad muuta. Nii väldime olukorda,
   kus kaks inimest teevad sama tööd või kus valmis PR lükatakse tagasi
   suuna pärast.
2. Suurte muudatuste puhul küsi enne, kas suund sobib.

## Kuldreegel: mõõda, ära oleta

See projekt on ehitatud mõõtmiste peale. Kui väidad, et midagi on
katki või aeglane, lisa **tõend**: logirida, ajatempel, testitulemus
või number. Kommentaarides on soovitav kirjutada **MIKS** nii tehti,
mitte ainult mis tehti — koodis on palju selliseid selgitusi ja need
on tahtlikud.

## Töövoog

```bash
git checkout -b minu-parandus
# ... muudatused ...
python3 -m pytest tests/ -q          # või: for f in tests/tests_*.py; do python3 "$f"; done
scripts/kontrolli_privaatsust.sh     # saladuste kontroll
git commit -m "Lühike selge pealkiri"
```

Seejärel ava pull request.

## Nõuded pull request'ile

- [ ] Testid jooksevad läbi (`tests/`).
- [ ] Uus funktsionaalsus on testiga kaetud.
- [ ] `scripts/kontrolli_privaatsust.sh` ei leia midagi.
- [ ] Ei ühtegi API võtit, parooli, IP-aadressi, isikuandmeid ega
      andmebaasifaili.
- [ ] Kui muutsid Gemini Live konfiguratsiooni (mudel, VAD, helivorming,
      turvaseaded), **põhjenda eraldi** — need on meelega lukus ja
      nende muutmine rikub häälkäitumise.
- [ ] Kasutajale nähtav tekst on eesti keeles.

## Testid

Teste **ei tohi nõrgendada selleks, et tulemus roheliseks saada.** Kui
test on vale, paranda testi ja selgita commit'i sõnumis, miks vana
ootus oli vale.

Testid on nelja liiki ja neid ei tohi omavahel segi ajada:

| Liik | Mida tõestab |
|---|---|
| Ühiktest | puhas loogika (`conversation_flow`, mälu, privaatsus) |
| Staatiline kontroll | et tootmiskoodis ON vajalik kaitse olemas (AST + tekst) |
| Jäljendatud asünkroonne | taskide elutsükkel, võidujooksud, tühistamine |
| Päris Gemini Live | **puudub** — vajab võtit ja maksab. Ära väida, et selline test läbis, kui jooksutasid jäljendit |

## Mida me tõenäoliselt tagasi lükkame

- Gemini Live asendamine teise mudeli või kõnesünteesiga.
- Vestluse elutsükli „lihtsustamine", mis kaotab taaste või omaalgatuse.
- Karakterisüsteemi asendamine ühe üldise viibaga.
- Kasutaja prioriteedi nõrgendamine (sinu kõne peab alati võitma).
- Suured ümberkirjutused ilma eelneva arutelu ja mõõdetud põhjuseta.

## Avalik projekt vs sinu enda paigaldus

See hoidla on **sõltumatu avalik projekt** ja siin ei ole ühtegi
jooksvat MAYA teenust: hoidla levitab lähtekoodi ja APK-d, backendi
käivitab iga kasutaja ise.

Ükski siinne muudatus **ei jõua automaatselt** ühegi töötava
paigalduse sisse — ei hoidla haldaja omasse ega kellegi teise omasse.
Iga paigaldaja otsustab ise, millal ja mida ta oma eksemplari uuendab.
Vastupidine kehtib ka: eraparaldustes tehtud muudatusi siia
automaatselt ei tule.

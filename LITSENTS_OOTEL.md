# ⚠️ LITSENTS ON VALIMATA — ÄRA AVALDA VEEL

Sellel väljalaskekandidaadil **EI OLE litsentsi**. Varasem ajutine
MIT-litsents ja ajutine autoriõiguse teade on **teadlikult
eemaldatud**, sest litsentsi valik on omaniku otsus.

Ilma litsentsifailita kehtib vaikimisi **„kõik õigused kaitstud"**:
keegi teine ei tohi koodi seaduslikult kopeerida, muuta ega levitada.
Seega **avalikku hoidlat ei tohi veel luua.**

---

## MIT vs Apache-2.0 — võrdlus

Omanik on väljendanud eelistust **Apache-2.0** suunas. Allpool on
mõlema täpne võrdlus, et otsus oleks teadlik.

| | **MIT** | **Apache-2.0** |
|---|---|---|
| Pikkus | ~170 sõna, 1 lõik | ~2 500 sõna, 9 jaotist |
| Kommertskasutus | lubatud | lubatud |
| Suletud lähtekoodiga edasimüük | lubatud | lubatud |
| Muudatuste avaldamise kohustus | ei | ei |
| Autoriõiguse teate säilitamine | nõutud | nõutud |
| **Selgesõnaline patendiluba** | **puudub** | **on olemas (§3)** |
| **Patendi vastuhagi kaitse** | puudub | **on (§3: patendihagi → luba lõppeb)** |
| Muudatuste märkimise nõue | ei | **jah (§4b: tuleb märkida, mida muutsid)** |
| Kaubamärgiluba | ei anta (vaikimisi) | **selgesõnaliselt EI anta (§6)** |
| `NOTICE` faili edasikandmise nõue | ei | **jah, kui `NOTICE` on olemas (§4d)** |
| GPL-ühilduvus | GPLv2 ja GPLv3 | **ainult GPLv3** (GPLv2-ga mitte) |
| Levinud kasutus | väikesed teegid, skriptid | suuremad projektid, ettevõtted |

### Mida Apache-2.0 juurde annab

1. **Patendiluba (§3).** Iga panustaja annab oma panuse osas
   selgesõnalise patendiloa. MIT-i puhul on see juriidiliselt
   ebamäärane — osa juriste leiab, et patendiluba tuleb kaudselt,
   osa mitte. Apache teeb selle selgeks.

2. **Patendi vastuhagi klausel (§3).** Kui keegi esitab projekti
   vastu patendihagi, **kaotab ta ise litsentsi**. See on tegelik
   kaitse, mida MIT ei paku.

3. **Kaubamärgi selgus (§6).** Litsents ei anna õigust kasutada nime
   „MAYA" ega sinu kaubamärke. MIT-is ei ole selle kohta midagi
   kirjas.

4. **Ettevõtete õigusosakonnad eelistavad seda.** Kui tahad, et MAYA-t
   kasutataks ka tööl, on Apache-2.0 praktikas lihtsam läbi saada kui
   MIT.

### Mida see kulustab

1. **Pikem fail.** Peab olema täies pikkuses kaasas.
2. **§4b nõue:** oluliste muudatuste puhul tuleb lisada märge, et
   faili on muudetud. Praktikas on see tühine.
3. **GPLv2 projektid ei saa sinu koodi kasutada.** Kui soovid
   maksimaalset ühilduvust, on MIT vabam.

### Sõltuvused ei piira valikut

Kontrollisin paigaldatud pakettide metaandmetest: kõik kohustuslikud
sõltuvused on **MIT / BSD-3-Clause / Apache-2.0**, `certifi` on
MPL-2.0 (failipõhine, ei nakata). **Ühtegi GPL/AGPL sõltuvust ei ole.**
Androidi pool on täielikult Apache-2.0. Vt
[docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

Seega **mõlemad valikud on vabad** — ka AGPL, kui tahaksid, et keegi
ei teeks MAYA-st suletud SaaS-i.

### Soovitus

**Apache-2.0** on selle projekti jaoks parem valik, sest:

- MAYA on **rakendus**, mitte väike teek — Apache-2.0 on selles
  suurusklassis norm;
- projekt puudutab **häältuvastust ja -sünteesi**, kus patente on
  palju; patendiklausel on siin reaalse väärtusega;
- nimi „MAYA" jääb kaubamärgina selgelt sinu omaks;
- Apache-2.0 ei piira ühtegi kasutusviisi rohkem kui MIT (väljaarvatud
  GPLv2-ühilduvus, mis on siin ebatõenäoline).

Apache-2.0 kõrvale tasub lisada **`NOTICE` fail** projekti nimega ja
autoriõiguse reaga.

---

## Mida omanik peab otsustama

1. **Litsents.** Apache-2.0 (soovitatud), MIT, AGPL-3.0 või muu.
2. **Autoriõiguse rida.** Kelle nimi või pseudonüüm:
   `Copyright 2026 <nimi>`.
3. **Panustajate leping.** Kas nõuad DCO-d (`Signed-off-by:` igal
   commit'il, lihtne) või CLA-d (keerukam, aga annab õiguse litsentsi
   hiljem muuta).

## Pärast otsust — täpne sammude jada

```bash
cd ~/maya-avalik

# 1. Litsentsitekst (Apache-2.0 näitel)
curl -sL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE

# 2. NOTICE fail (Apache-2.0 tava)
cat > NOTICE <<'TXT'
MAYA
Copyright 2026 <SINU NIMI>

This product includes software developed as part of the MAYA project.
TXT

# 3. Uuenda README litsentsijaotis ja CONTRIBUTING (DCO/CLA)
# 4. Kustuta see fail
rm LITSENTS_OOTEL.md

# 5. Commit
git add -A && git commit -m "Lisa Apache-2.0 litsents ja NOTICE"
```

Alles **pärast seda** tohib avaliku hoidla luua.

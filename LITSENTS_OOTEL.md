# ⚠️ LITSENTS ON VALIMATA — ÄRA AVALDA VEEL

Sellel väljalaskekandidaadil **EI OLE litsentsi**.

Varem oli siin ajutine MIT-litsents koos ajutise autoriõiguse teatega.
See on **teadlikult eemaldatud**, sest litsentsi valik on
projekti omaniku otsus, mitte tehniline detail.

## Mida see tähendab

Ilma litsentsifailita kehtib vaikimisi **"kõik õigused kaitstud"**:
keegi teine ei tohi koodi seaduslikult kopeerida, muuta ega levitada.
Seega:

- **Avalikku hoidlat ei tohi veel luua.**
- Kui hoidla siiski avaldatakse, ei saa keegi sellesse seaduslikult
  panustada ega seda kasutada.

## Mida omanik peab otsustama

1. **Litsents.** Levinumad valikud selle projekti jaoks:

   | Litsents | Mida lubab | Millal valida |
   |---|---|---|
   | **MIT** | kõik, sh suletud lähtekoodiga ärikasutus | tahad maksimaalset levikut |
   | **Apache-2.0** | sama + selgesõnaline patendiluba | sama, aga patendikaitsega |
   | **AGPL-3.0** | kasutamine, aga muudatused tuleb avaldada ka teenusena | tahad, et keegi ei teeks sellest suletud SaaS-i |
   | **BSL / „source available"** | piiratud ärikasutus | tahad kommertsõigused endale |

   Sõltuvuste pool ei piira valikut: kõik kohustuslikud sõltuvused on
   lubavad (MIT/BSD/Apache-2.0), **ühtegi GPL/AGPL sõltuvust ei ole**
   — vt [docs/SOLTUVUSED.md](docs/SOLTUVUSED.md).

2. **Autoriõiguse teade.** Kelle nimi või pseudonüüm läheb
   `Copyright (c) 2026 ...` reale.

3. **Panustajate leping** (valikuline). Kui tahad õigust koodi
   hiljem teise litsentsi alla panna, on vaja CLA-d või DCO-d.

## Pärast otsust

1. Loo `LICENSE` fail valitud litsentsi tekstiga.
2. Pane autoriõiguse rida õigeks.
3. Uuenda `README.md` litsentsijaotis.
4. Uuenda `CONTRIBUTING.md` (kas DCO/CLA on nõutud).
5. **Kustuta see fail.**
6. Alles siis loo avalik hoidla.

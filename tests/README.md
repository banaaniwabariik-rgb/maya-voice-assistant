# Testid

```bash
for f in tests/tests_*.py; do echo "== $f"; python3 "$f"; done
```

Vt [../docs/ARENDUS.md](../docs/ARENDUS.md) testide liikide ja
reeglite kohta.

| Fail | Mida katab |
|---|---|
| `tests_vestluse_elutsykkel.py` | olekumasin: taaste, omaalgatus, väravad |
| `tests_asunkroonne_elutsykkel.py` | taskid, lukud, võidujooksud, sulgemine, stsenaariumid 1–20 |
| `tests_konevoor.py` | kõnevooru elutsükkel ja diagnostika |
| `tests_haale_taaste_faas12.py` | pooleli jäänud kõne tuvastus ja taaste |
| `tests_jatkamine_20261110.py` | taasteahela piirid |
| `tests_parandused_20261110.py` | konkreetsed parandused + regressioonikaitse |
| `tests_faas_c_katkemine.py` | katkemise käsitlus, kliendipoolne heli |
| `tests_gemini_meta.py` | Gemini lõpetamise metaandmed (erindikindlus) |
| `tests_malu_elutsykkel.py` | mälu: faktide eraldamine ja salvestus |
| `tests_malu_karakteri_eraldatus.py` | mälu ulatus karakterite vahel, kasutaja nimi |
| `tests_malu_kuldstandard.py` | mälu otsingu kvaliteedi võrdlus (ei ole pass/fail) |
| `tests_privaatsus_tootmine.py` | privaatsusjuhiste rakendamine faktitasemel |
| `tests_karakterite_eraldatus.py` | karakterid ei leki üksteisesse |
| `tests_krediidi_haldus.py` | kulu ja krediidi arvestus |

## Märkused avaliku koopia kohta

- **Kaust `isiklikud_naited/` on eemaldatud.** Seal olid testid, mis
  kontrollisid originaalpaigalduse ISIKLIKKE karakteriviipasid.
  Privaatsusaudit tuvastas, et need sisaldasid nende viipade
  sõnasõnalisi katkeid ja räsisid, mistõttu kaust on kustutatud ka
  Git-ajaloost. Kui kirjutad oma karakterid, kirjuta nende testid ise –
  eeskuju annab `tests_karakterite_eraldatus.py`.
- **Testide näiteisik on väljamõeldud.** Mälu- ja
  privaatsustestide „faktid" (nimed, auto, tervis, suhted) on
  SÜNTEETILISED ja ei kirjelda ühtegi päris inimest.

- **Päris Gemini Live teste ei ole.** Jäljendatud asünkroonsed testid
  kasutavad päris `conversation_flow` moodulit, aga jäljendatud seanssi
  ja kella.
- `tests_parandused_20261110.py` sisaldab ühte **vahele jäetud** klassi
  (`TestNimeMigratsioon`) — see testis originaalpaigalduse ühekordset
  isiklikku andmemigratsiooni, mida avalikus koopias ei ole.
- Mõned testid lukustavad **näidiskarakterite** räsid. Kui kirjutad
  oma karakterid, uuenda neid numbreid — test kaitseb kogemata
  muutmise, mitte teadliku muutmise eest.

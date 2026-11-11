# Turvapoliitika

## Turvaaugu teatamine

**Ära ava turvaaugu kohta avalikku issue't.**

Kasuta GitHubi privaatset teatamist:
**Security → Advisories → Report a vulnerability**

Kui see ei ole võimalik, kirjuta hoidla omanikule privaatselt.

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

## Teadaolevad piirangud (ei ole „augud", vaid disainivalikud)

Need on teadlikult sellised ja dokumenteeritud:

1. **Backendil ei ole autentimist.** Projekt eeldab, et server elab
   privaatvõrgus (Tailscale/WireGuard) või pöördproksi taga. Avalikku
   internetti pandud MAYA on sisuliselt lahtine uks — vt README
   turvahoiatust.
2. **HTTP, mitte HTTPS.** Androidi klient räägib serveriga HTTP-s, sest
   privaatvõrgus ei ole sertifikaate. HTTPS-i jaoks kasuta pöördproksit.
3. **Andmebaas on krüpteerimata SQLite.** Mälufaktid ja vestlusarhiiv on
   tavatekstina. Kui see on sulle oluline, kasuta krüpteeritud
   failisüsteemi.
4. **Gemini API võti elab serveris.** Kes serverini pääseb, saab võtit
   kasutada.

## Saladuste käsitlemine

- `.env` on `.gitignore`-is ja peab seal püsima.
- `.env.example` sisaldab AINULT kohahoidjaid.
- Enne commit'i jooksuta `scripts/kontrolli_privaatsust.sh` — see otsib
  võtmemustreid, IP-aadresse ja andmebaasifaile.
- Kui võti on kogemata commit'itud: **tühista võti kohe** (Google AI
  Studios / Groq konsoolis). Ajaloost kustutamine üksi ei aita — võti
  tuleb lugeda lekkinuks.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MAYA — ASÜNKROONSE ELUTSÜKLI TESTID (stsenaariumid D, E, F, H, I).

AUSUS SELLE FAILI KOHTA — LOE ENNE TULEMUSTE TÕLGENDAMIST:

1. SIIN EI OLE ÜHTEGI PÄRIS GEMINI LIVE API TESTI. Arendusmasinas
   puudub `google.genai`, seega `live_maya_ws.py` ei ole imporditav.
   Ükski allolev test ei tõesta, et Gemini käitub nii, nagu eeldame.

2. ASÜNKROONSED TESTID (klass TestAsunkroonneElutsykkel) käivitavad
   JÄRELEHITATUD tsükli, mis kasutab PÄRIS `conversation_flow`
   moodulit, aga JÄLJENDATUD seanssi ja kella. Need tõestavad
   otsustusloogika ja taskide elutsükli õigsust, MITTE seda, et
   tootmisfail on täpselt sama kujuga.

3. Punkti 2 auk kaetakse STAATILISTE kontrollidega (klass
   TestStaatilineVastavus), mis loevad tootmisfaili teksti ja
   nõuavad, et sealsamas on samad kaitsed olemas.

4. Taimeri roheline test EI tõesta päris reaalajas vooruvahetust.
   Jäljendatud kell liigub hüpetega; päris maailmas sekkub võrk,
   VAD ja kliendi puhver.
"""
import ast
import asyncio
import contextlib
import inspect
import pathlib
import sys
import unittest

JUUR = pathlib.Path(__file__).resolve().parent.parent
KOOD = JUUR / "server"
sys.path.insert(0, str(KOOD))

import conversation_flow as cf  # noqa: E402

WS = (KOOD / "live_maya_ws.py").read_text(encoding="utf-8")
_HTML_TEE = (JUUR / "android" / "app" / "src" / "main" / "assets"
             / "index.html")
HTML = _HTML_TEE.read_text(encoding="utf-8") if _HTML_TEE.exists() else ""


# =====================================================================
# JÄLJENDID
# =====================================================================
class FakeTransport:
    """Jäljendab asyncio WriteTransporti. `abort()` vabastab
    blokeerunud kirjutuse – täpselt nagu websocketsi
    `connection_lost()` vabastab `drain_waiters`-id."""

    def __init__(self):
        self.abort_kutsutud = False
        self.vabasta = asyncio.Event()

    def abort(self):
        self.abort_kutsutud = True
        self.vabasta.set()


class FakeSession:
    """Jäljendab Gemini seanssi. Tuvastab PÕIMUNUD kirjutused.

    `blokeeru=True` jäljendab PÜSIVALT kinni jäänud kirjutust
    (`drain()` TCP vastuvoolu taga): see lõpeb AINULT siis, kui
    transport katkestatakse.
    """

    def __init__(self, viide: float = 0.0, purune: bool = False,
                 blokeeru: bool = False, viide_heli: float = 0.0):
        self.saadetud = []        # (tüüp, sisu)
        self.poimunud = False     # kaks JUHTSÕNUMIT korraga = defekt
        self.poimunud_segatud = False   # heli + juhtsõnum = lubatud
        self._sees = 0
        self._sees_tyyp = {}
        self.viide = viide        # kunstlik JUHTSÕNUMI kestus
        # Heli saadetakse päriselt kiiresti; kui viide kehtiks ka
        # helile, varjaks see ära, kas mikrofon on juhtsõnumi taga
        # kinni või mitte.
        self.viide_heli = viide_heli
        self.purune = purune
        self.blokeeru = blokeeru
        # vastab tootmise `session._ws.transport`-ile
        self._ws = type("FakeWS", (), {"transport": FakeTransport()})()

    async def send(self, input=None, end_of_turn=False):
        await self._kirjuta("send", input)

    async def send_realtime_input(self, **kw):
        await self._kirjuta("realtime", kw)

    async def _kirjuta(self, tyyp, sisu):
        # KAHT SORTI PÕIMUMIST tuleb eristada (L4 tõend):
        #  * `poimunud`       = kaks JUHTSÕNUMIT korraga -> DEFEKT,
        #                       saatmislukk peab selle välistama.
        #  * `poimunud_segatud` = heli JA juhtsõnum korraga -> LUBATUD
        #    ja ohutu. Tõend: websockets 17.3 `Connection.send(str)`
        #    koostab ühe kaadri SÜNKROONSELT `send_context()` sees,
        #    seega kahe eri sõnumi kaadrid ei saa põimuda. Mikrofon ei
        #    tohi juhtsõnumi taga oodata.
        self._sees += 1
        self._sees_tyyp[tyyp] = self._sees_tyyp.get(tyyp, 0) + 1
        if self._sees_tyyp.get(tyyp, 0) > 1:
            self.poimunud = True
        elif self._sees > 1:
            self.poimunud_segatud = True
        try:
            if self.blokeeru:
                # Ootab igavesti, kuni transport katkestatakse.
                await self._ws.transport.vabasta.wait()
                raise ConnectionResetError("transport katkestatud")
            _v = self.viide_heli if tyyp == "realtime" else self.viide
            if _v:
                await asyncio.sleep(_v)
            else:
                await asyncio.sleep(0)
            if self.purune:
                raise RuntimeError("seanss suletud")
            self.saadetud.append((tyyp, sisu))
        finally:
            self._sees -= 1
            self._sees_tyyp[tyyp] = self._sees_tyyp.get(tyyp, 1) - 1


class Kell:
    """Jäljendatud monotoonne kell. Ei sõltu päris ajast."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def edasi(self, s):
        self.t += s


class Harness:
    """Tootmistsükli JÄRELEHITUS: sama kaitsete komplekt.

    Vastab `live_maya_ws.py` initiative_ticker + teardown kujule.
    """

    def __init__(self, persona="filosoof", session=None, kell=None,
                 tiks=0.01):
        self.kell = kell or Kell()
        self.session = session or FakeSession()
        self.flow = cf.ConversationFlow(persona, now=self.kell())
        self.running = True
        self.tiks = tiks
        self.lukk = asyncio.Lock()
        self.taustataskid = []
        self.lopetajad = []
        self.user_speaking = False
        self.tool_running = False
        self.viimane_kone = 0.0     # last_user_speech["t"]
        self.ticker_lopetas = False
        # --- K5 PARANDUSE OSAD ---------------------------------------
        self.epoch = 0              # _kasutaja_voor["n"]
        self.taastetask = None      # _taastetask["t"]
        self.transport_viga = ""    # fatal_state["reason"]
        self.jarjekord = asyncio.Queue()   # sissetulev kliendi liiklus
        self.vastuvoetud = 0        # mitu paketti tsükkel ära töötas
        self.taaste_tuhistusi = 0
        self.algatusi = 0           # õnnestunud omaalgatuslikud päringud
        self.saatmistorkeid = 0     # gsend viskas erindi
        self.viimane_torge = ""
        self.arajaetud = []         # valideerimisel ära jäetud päringud
        self.suletud = False        # _suletud["v"]
        self.tyhistatud = set()     # _tyhistatud
        self.oodatud = []           # millised taskid sulgemine ÄRA OOTAS
        self.lopetamata = []        # ja millised jäid lõpetamata
        self.transport_katkestatud = False
        self.sulgemine = None       # sulgemise TULEMUS

    # ---- vastuvõtutsükkel (vastab receive/send_to_client tsüklile) --
    async def receive_loop(self):
        """Peab jääma VABAKS kogu taaste ootamise ajaks."""
        try:
            while self.running:
                pakett = await self.jarjekord.get()
                self.vastuvoetud += 1
                if pakett[0] == "audio":
                    await self.grealtime(audio=pakett[1])
                elif pakett[0] == "user_speech":
                    self.kasutaja_vottis_sona()
        except asyncio.CancelledError:
            pass

    def kasutaja_vottis_sona(self):
        """Vastab tootmise input_transcription harule."""
        self.viimane_kone = self.kell()
        self.epoch += 1
        self.flow.on_user_speech(self.kell())
        self.tyhista_ootel_taaste("kasutaja võttis sõna")

    def tyhista_ootel_taaste(self, pohjus=""):
        t = self.taastetask
        self.taastetask = None
        if t is not None and not t.done():
            self.tyhistatud.add(t)
            t.cancel()
            self.taaste_tuhistusi += 1
            return True
        return False

    def voor_kehtib(self, epoch):
        if self.flow.state == cf.ENDED:
            return (False, "vestlus on lõppenud")
        if self.transport_viga:
            return (False, "seanss on lõpliku tõrke järel")
        if not self.running:
            return (False, "seanss suletakse")
        if self.epoch != epoch:
            return (False, "kasutaja alustas uut vooru")
        if self.flow.state == cf.USER_SPEAKING:
            return (False, "kasutajal on sõna")
        return (True, "")

    async def gsend(self, valideeri=None, **kw):
        """Kordab tootmise `gsend` kuju, SH shield + drenaažitsükkel.

        Ilma shieldita ei testiks test_05 seda, mida ta väidab:
        tühistamine jätaks kirjutamise pooleli ja harness erineks
        tootmisest täpselt selles kohas, mida kontrollime (L5 õppetund).
        """
        async with self.lukk:
            if valideeri is not None:
                ok, miks = valideeri()
                if not ok:
                    return (False, miks)
            _s = asyncio.ensure_future(self.session.send(**kw))
            try:
                await asyncio.shield(_s)
            except asyncio.CancelledError:
                while not _s.done():
                    try:
                        await asyncio.wait({_s})
                    except asyncio.CancelledError:
                        continue
                try:
                    _s.exception()
                except Exception:
                    pass
                raise
            return (True, "")

    async def grealtime(self, **kw):
        """L4: mikrofon EI võta juhtsõnumite lukku – täpselt nagu
        tootmises. Harness oli siin tootmisest maha jäänud ja varjas
        ära, et lukuga oleks kasutaja hääl juhtsaatmise taga kinni."""
        await self.session.send_realtime_input(**kw)

    def _rk(self):
        """Sama avaldis nagu tootmises: kas kasutaja kõne on värske."""
        if self.viimane_kone <= 0:
            return False
        return (self.kell() - self.viimane_kone) < 2.0

    async def initiative_ticker(self):
        torkeid = 0
        try:
            while self.running:
                await asyncio.sleep(self.tiks)
                n = self.kell()
                otsus = self.flow.tick(
                    now=n,
                    user_speaking=(self._rk() or self.user_speaking),
                    tool_running=self.tool_running)
                if not otsus["speak"]:
                    continue
                sil = n - self.flow.last_activity
                self.flow.reserve_initiative(n)
                ep = self.epoch
                # L5 PARANDUS: harnessil PUUDUS sisemine try/except,
                # mis tootmises on (`live_maya_ws.py`,
                # `except Exception as _ae: flow.release_initiative()`).
                # Seetõttu suri harnessi tiksuja saatmistõrke peale ja
                # broneering jäi tagastamata – test_I läbis ainult
                # teardowni kõrvalmõju tõttu. Nüüd on veatee SAMA.
                try:
                    saadeti, miks = await self.gsend(
                        valideeri=lambda: self.voor_kehtib(ep),
                        input=cf.initiative_prompt(
                            sil,
                            has_prior_thought=(
                                self.flow.assistant_said_something)),
                        end_of_turn=True)
                    if not saadeti:
                        self.flow.release_initiative()
                        self.arajaetud.append(miks)
                        continue
                    self.algatusi += 1
                    torkeid = 0
                except asyncio.CancelledError:
                    # L7: broneering tagasi ja tühistus EDASI
                    self.flow.release_initiative()
                    raise
                except Exception as e:
                    self.flow.release_initiative()
                    self.saatmistorkeid += 1
                    self.viimane_torge = repr(e)
                    torkeid += 1
                    if torkeid >= 3:
                        break
        finally:
            self.ticker_lopetas = True

    async def taaste(self, otsus, saba="", epoch=None):
        """TAASTE TASKI KEHA. Vastab tootmise `taaste_saatja`-le.

        Vastuvõtutsükkel ei oota seda KUNAGI – ainult testid.
        """
        ep = self.epoch if epoch is None else epoch
        try:
            if otsus["wait_s"] > 0:
                await asyncio.sleep(otsus["wait_s"])
            saadeti, miks = await self.gsend(
                valideeri=lambda: self.voor_kehtib(ep),
                input=cf.RECOVERY_PROMPT, end_of_turn=True)
            if not saadeti:
                self.flow.on_recovery_failed()
                return False
            self.flow.on_recovery_dispatched(saba, self.kell())
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            self.flow.on_recovery_failed()
            return False
        finally:
            if self.taastetask is asyncio.current_task():
                self.taastetask = None

    def kaivita_taaste(self, otsus, saba=""):
        """Vastab tootmise create_task-harule: EI OODATA siin."""
        self.tyhista_ootel_taaste("uus taasteotsus")
        t = asyncio.ensure_future(self.taaste(otsus, saba, self.epoch))
        self.taastetask = t
        self.registreeri(t)
        return t

    def registreeri(self, t):
        self.taustataskid.append(t)
        t.add_done_callback(
            lambda x: self.taustataskid.remove(x)
            if x in self.taustataskid else None)
        return t

    def kaivita(self, ka_vastuvott=False):
        t = self.registreeri(asyncio.ensure_future(self.initiative_ticker()))
        self.lopetajad.append(self.flow.on_conversation_end)
        if ka_vastuvott:
            self.registreeri(asyncio.ensure_future(self.receive_loop()))
        return t

    def katkesta_transport(self):
        """Vastab tootmise `_katkesta_transport()`-ile."""
        tr = getattr(getattr(self.session, "_ws", None), "transport", None)
        if tr is None or not hasattr(tr, "abort"):
            return False
        tr.abort()
        self.transport_katkestatud = True
        return True

    async def sulge_seanss(self, pohjus="normaalne lõpp",
                           faas1=0.4, faas2=0.4):
        """Vastab tootmise `_sulge_seanss()`-ile: idempotentne,
        tühistab ÜKS kord, OOTAB ära, eskaleerib transpordi
        katkestamisele ja raporteerib EBAÕNNESTUMISE ausalt.

        Ooteajad on testides lühemad kui tootmises (0,4 s vs 2 s),
        et komplekt jääks kiireks – loogika on sama.
        """
        if self.suletud:
            return self.sulgemine
        self.suletud = True
        self.running = False
        try:
            self.flow.on_conversation_end()
        except Exception:
            pass
        mina = asyncio.current_task()
        self.taastetask = None
        oota = []
        for t in list(self.taustataskid):
            if t is mina or t.done():
                continue
            if t not in self.tyhistatud:
                self.tyhistatud.add(t)
                t.cancel()
            oota.append(t)
        self.oodatud = list(oota)

        def loe(tehtud):
            for t in tehtud:
                if not t.cancelled():
                    try:
                        t.exception()
                    except Exception:
                        pass

        jaanud = set()
        if oota:
            try:
                tehtud, jaanud = await asyncio.wait(oota, timeout=faas1)
            except asyncio.CancelledError:
                tehtud, jaanud = set(), set(oota)
            loe(tehtud)
            if jaanud:
                self.katkesta_transport()
                try:
                    tehtud2, jaanud = await asyncio.wait(
                        jaanud, timeout=faas2)
                except asyncio.CancelledError:
                    tehtud2, jaanud = set(), jaanud
                loe(tehtud2)
        self.lopetamata = list(jaanud)
        self.sulgemine = {
            "ok": not jaanud,
            "oodatud": len(oota),
            "lopetamata": sorted(t.get_name() for t in jaanud),
            "transport_katkestatud": self.transport_katkestatud,
        }
        for l in self.lopetajad:
            l()
        return self.sulgemine

    def teardown(self):
        """SÜNKROONNE variant vanade testide jaoks: ei oota ära.
        Uued sulgemistestid kasutavad `sulge_seanss()`-i."""
        self.running = False
        t0 = self.taastetask
        self.taastetask = None
        if t0 is not None and not t0.done():
            self.tyhistatud.add(t0)
            t0.cancel()
        for t in list(self.taustataskid):
            if t not in self.tyhistatud:
                self.tyhistatud.add(t)
                t.cancel()
        for l in self.lopetajad:
            l()


def kone(h, tekst="Mida sa arvad?", terminal=True, audio_s=2.0):
    """Maya voor lõpuni."""
    h.flow.on_generation_start(now=h.kell())
    return h.flow.on_turn_complete(
        text=tekst, tail_len=len(tekst), audio_s=audio_s,
        tail_is_terminal=terminal, user_interrupted=False,
        tool_running=h.tool_running, playback_end_est=h.kell(),
        now=h.kell())


# Sisult ERINEVAD poolikud sabad: ükski ei ole teise kordus, seega
# ainus peatav tegur saab olla eelarve.
TAASTE_SABAD = [
    "ja siis ta ütles mulle, et tegelikult",
    "mu arvates on kõige olulisem hoopis see, kuidas",
    "kui me vaatame seda ajaloolisest vaatenurgast, siis",
    "üks asi, mida ma tahtsin veel mainida, oli",
    "teine pool sellest loost räägib hoopis sellest, miks",
    "lõpuks jõuame alati tagasi küsimuseni, kas üldse",
    "minu kehal on praegu niisugune tunne, nagu oleks",
    "tule lähemale ja pane oma käed sinna, kus ma",
    "see, mida sa eile õhtul tegid, pani mind täiesti",
    "kõige rohkem tahaksin ma praegu seda, et sa",
    "räägi mulle veel sellest, mis juhtus siis, kui",
    "ausalt öeldes ei ole ma kunagi varem nii väga",
    "nüüd ma tahan sulle öelda midagi hoopis muud ja",
    "viimane asi, mis mul veel meelde tuli, oli see, et",
]


def kasutaja(h, nüüd=None):
    if nüüd is not None:
        h.kell.t = nüüd
    h.kasutaja_vottis_sona()


# =====================================================================
# JÄLJENDATUD ASÜNKROONNE ELUTSÜKKEL
# =====================================================================
class TestAsunkroonneElutsykkel(unittest.IsolatedAsyncioTestCase):

    # ---- B: Maya lõpetas KÜSIMUSEGA -> ootab kasutaja vastust ----
    async def test_B_kusimuse_jarel_ootab_kasutaja_vastust(self):
        h = Harness("filosoof")          # paus 5 s, eelarve 3
        kone(h)
        kasutaja(h)
        kone(h, "Aga mida sina sellest arvad?", True)
        self.assertEqual(h.flow.state, cf.AWAITING_USER)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 0.5)   # 1 x paus
        await asyncio.sleep(0.05)
        self.assertEqual(h.session.saadetud, [],
                         "küsis ja hakkas ise kohe edasi rääkima")
        h.kell.edasi(h.flow.initiative.pause_s)         # 2 x paus
        await asyncio.sleep(0.05)
        h.teardown()
        self.assertEqual(len(h.session.saadetud), 1,
                         "jäi igaveseks vastust ootama")

    # ---- A: Maya lõpetas VÄITEGA -> algatab karakteri pausi järel -
    async def test_A_vaite_jarel_algatab_karakteri_pausi_jarel(self):
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Nii see minu meelest on.", True)
        self.assertEqual(h.flow.state, cf.COMPLETE_IDLE)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 0.5)
        await asyncio.sleep(0.05)
        h.teardown()
        self.assertEqual(len(h.session.saadetud), 1)
        self.assertIn("vaikne", h.session.saadetud[0][1].lower())

    async def test_B2_retooriline_kusimus_ei_jata_vestlust_seisma(self):
        """B ALAMJUHT, TEADLIK KÄITUMINE.

        Semantilist retoorilise küsimuse tuvastajat EI OLE ja ma ei
        väida, et oleks: `classify_completion` vaatab AINULT viimast
        kirjavahemärki. Retooriline küsimus läheb seega samuti
        AWAITING_USER-isse, aga see EI jäta vestlust seisma, sest
        AWAITING_USER avaneb 2 x pausi järel. Nii ei nõua mehhanism
        küsimuse tähenduse mõistmist.
        """
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Ja kes meist seda lõpuni teab?", True)
        self.assertEqual(h.flow.state, cf.AWAITING_USER)
        h.kaivita()
        # 1 x paus: vaikib (võib olla päris küsimus)
        h.kell.edasi(h.flow.initiative.pause_s + 0.5)
        await asyncio.sleep(0.05)
        self.assertEqual(h.session.saadetud, [])
        # 2 x paus: läheb ise edasi
        h.kell.edasi(h.flow.initiative.pause_s)
        await asyncio.sleep(0.05)
        h.teardown()
        self.assertEqual(len(h.session.saadetud), 1,
                         "retooriline küsimus jättis vestluse seisma")

    # ---- C: pooleli jäänud lause -> KOHENE taaste ----------------
    async def test_C_esimene_taaste_ei_oota(self):
        h = Harness("asjalik")
        kone(h)
        kasutaja(h)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text="ja siis ta ütles, et", tail_len=20, audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"])
        self.assertEqual(o["wait_s"], 0.0, "esimene katse ootab asjata")
        self.assertEqual(o["attempt"], 1)
        saadeti = await h.taaste(o, "ja siis ta ütles, et")
        self.assertTrue(saadeti)
        self.assertEqual(h.flow.state, cf.GENERATING)

    # ---- J: korduvad ebaõnnestumised -> eelarve, mitte lõputsükkel
    async def test_J_taaste_ahel_peatub_eelarve_peal(self):
        h = Harness("asjalik")
        kone(h)
        kasutaja(h)
        katseid = 0
        for i in range(cf.RECOVERY_BUDGET + 2):
            # 5 s > 2 s: kasutaja kõne ei ole enam värske, seega
            # ootamisjärgne ülekontroll ei tühista taastet.
            h.kell.edasi(5.0)
            h.flow.on_generation_start(now=h.kell())
            o = h.flow.on_turn_complete(
                text=TAASTE_SABAD[i % len(TAASTE_SABAD)], tail_len=25,
                audio_s=4.0, tail_is_terminal=False, user_interrupted=False,
                tool_running=False, playback_end_est=h.kell(), now=h.kell())
            if not o["recover"]:
                break
            if await h.taaste(o, TAASTE_SABAD[i % len(TAASTE_SABAD)]):
                katseid += 1
        h.teardown()
        self.assertEqual(katseid, cf.RECOVERY_BUDGET)
        self.assertEqual(h.flow.recovery.stopped_reason, "budget_exhausted")
        self.assertEqual(len(h.session.saadetud), cf.RECOVERY_BUDGET)

    async def test_J3_pärisKORDUS_peatab_ahela_enne_eelarvet(self):
        """Vastupidine kontroll J-le: kui Maya PÄRISELT kordab, peab
        ahel peatuma enne eelarve ammendumist."""
        h = Harness("asjalik")
        kone(h)
        kasutaja(h)
        saba = "ja siis ta ütles mulle, et tegelikult"
        h.kell.edasi(5.0)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text=saba, tail_len=len(saba), audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"])
        h.flow.on_recovery_dispatched(saba, h.kell())
        h.kell.edasi(5.0)
        h.flow.on_generation_start(now=h.kell())
        o2 = h.flow.on_turn_complete(
            text=saba, tail_len=len(saba), audio_s=4.0,     # SAMA tekst
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertFalse(o2["recover"], "kordus ei peatanud ahelat")
        self.assertEqual(o2["reason"], "duplicate_detected")

    async def test_J4_luhike_saba_ei_loe_valekordust(self):
        """Mõõdetud risk: lühikese saba puhul plahvatab hulgapõhine
        suhe ja taaste katkeks juba esimese katse järel."""
        import conversation_flow as m
        self.assertFalse(m.near_duplicate("ja siis", "ja siis ta ütles"),
                         "kaks ühissõna luges korduseks")
        self.assertTrue(
            m.near_duplicate(
                "kui me vaatame seda ajaloolisest vaatenurgast siis",
                "kui me vaatame seda ajaloolisest vaatenurgast siis"),
            "identset teksti ei tuvastatud korduseks")

    async def test_J2_kasutaja_kone_nullistab_taasteahela(self):
        h = Harness("asjalik")
        kone(h)
        kasutaja(h)
        for i in range(cf.RECOVERY_BUDGET):
            h.kell.edasi(1.0)
            h.flow.on_generation_start(now=h.kell())
            o = h.flow.on_turn_complete(
                text="poolik %d" % i, tail_len=9, audio_s=4.0,
                tail_is_terminal=False, user_interrupted=False,
                tool_running=False, playback_end_est=h.kell(), now=h.kell())
            if o["recover"]:
                h.flow.on_recovery_dispatched("poolik %d" % i, h.kell())
        h.kell.edasi(5.0)
        kasutaja(h)                       # uus kasutaja voor
        h.kell.edasi(1.0)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text="jälle pooleli", tail_len=13, audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"],
                        "uus kasutaja voor ei nullistanud taaste eelarvet")
        self.assertEqual(o["attempt"], 1)

    # ---- D: kasutaja räägib 1 ms enne taimerit --------------------
    async def test_D_kasutaja_vahetult_enne_taimerit(self):
        h = Harness("filosoof")          # paus 5 s
        kone(h)
        kasutaja(h)                      # kasutaja vastab
        h.kaivita()
        # Maya lõpetas; kasutaja räägib täpselt pausi lõpus
        kone(h, "Ma kuulan.", True)
        h.kell.edasi(h.flow.initiative.pause_s - 0.001)
        kasutaja(h)                      # 1 ms enne läve
        h.kell.edasi(0.002)              # lävi möödus
        await asyncio.sleep(0.05)
        h.teardown()
        await asyncio.sleep(0)
        self.assertEqual(
            h.session.saadetud, [],
            "omaalgatus rääkis kasutajale peale (stsenaarium D)")
        self.assertEqual(h.flow.state, cf.ENDED)

    async def test_D2_kasutaja_konest_moodunud_aeg_avab_taimeri(self):
        """Kontroll, et D ei ole lihtsalt kõike blokeeriv."""
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 3.0)   # kõne EI ole värske
        await asyncio.sleep(0.05)
        h.teardown()
        self.assertEqual(len(h.session.saadetud), 1,
                         "omaalgatus ei käivitunud ka siis, kui tohtis")

    # ---- E: kasutaja räägib omaalgatuse GENEREERIMISE ajal --------
    async def test_E_kasutaja_segab_omaalgatuse_genereerimist(self):
        h = Harness("filosoof", session=FakeSession(viide=0.05))
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.02)                 # saatmine käib
        self.assertEqual(h.flow.state, cf.GENERATING,
                          "broneering ei lukustanud olekut")
        kasutaja(h)                                # kasutaja sekkub
        self.assertEqual(h.flow.state, cf.USER_SPEAKING)
        await asyncio.sleep(0.15)
        h.teardown()
        # TÄPSELT üks päring – mitte kaks
        self.assertEqual(len(h.session.saadetud), 1)
        # kasutaja on sõna võtnud -> eelarve nullistus, aga TEIST
        # päringut ei tekkinud ka pärast olemasoleva lõppemist
        self.assertEqual(h.flow.initiative.used, 0)

    # ---- F: kasutaja segab omaalgatuse TAASESITUSE ajal ----------
    async def test_F_kasutaja_segab_omaalgatuse_taasesitust(self):
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.05)
        self.assertEqual(len(h.session.saadetud), 1)
        # omaalgatuse vastus tuleb ja katkestatakse kesk lauset
        o = h.flow.on_turn_complete(
            text="Ma mõtlesin just, et", tail_len=20, audio_s=1.5,
            tail_is_terminal=False, user_interrupted=True,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertFalse(o["recover"],
                         "kasutaja katkestust ei tohi taastada")
        h.teardown()

    # ---- Eelarve ei plahvata ------------------------------------
    async def test_eelarve_piirab_omaalgatust(self):
        h = Harness("filosoof", tiks=0.005)      # eelarve 3
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        for _ in range(12):
            h.kell.edasi(h.flow.initiative.pause_s + 1)
            await asyncio.sleep(0.02)
            # Gemini "vastas" ja jäi lõpetatud olekusse
            h.flow.on_turn_complete(
                text="Niisiis.", tail_len=8, audio_s=1.0,
                tail_is_terminal=True, user_interrupted=False,
                tool_running=False, playback_end_est=h.kell(), now=h.kell())
        h.teardown()
        self.assertLessEqual(len(h.session.saadetud),
                             h.flow.initiative.budget,
                             "omaalgatuse eelarve ei piiranud midagi")

    async def test_eelarve_nullistub_kasutaja_konega(self):
        h = Harness("filosoof", tiks=0.005)
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        for ring in range(2):
            for _ in range(5):
                h.kell.edasi(h.flow.initiative.pause_s + 1)
                await asyncio.sleep(0.02)
                h.flow.on_turn_complete(
                    text="Niisiis.", tail_len=8, audio_s=1.0,
                    tail_is_terminal=True, user_interrupted=False,
                    tool_running=False, playback_end_est=h.kell(),
                    now=h.kell())
            kasutaja(h)
            kone(h, "Ma kuulan.", True)
        h.teardown()
        self.assertGreater(len(h.session.saadetud),
                           h.flow.initiative.budget,
                           "kasutaja kõne ei nullistanud eelarvet")

    # ---- G: tööriist blokeerib ----------------------------------
    async def test_G_tooriist_blokeerib_omaalgatuse(self):
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Vaatan järele.", True)
        h.tool_running = True
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 10)
        await asyncio.sleep(0.05)
        h.teardown()
        self.assertEqual(h.session.saadetud, [])

    # ---- H: seanss lõpeb, taimer pooleli ------------------------
    async def test_H_teardown_tuhistab_taimeri(self):
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        t = h.kaivita()
        await asyncio.sleep(0.02)        # task jõuab esimese await'ini
        h.teardown()
        await asyncio.sleep(0.05)
        self.assertTrue(t.cancelled() or t.done(),
                        "taimer jäi rippuma")
        self.assertTrue(h.ticker_lopetas)
        self.assertEqual(h.flow.state, cf.ENDED)
        # pärast lõppu EI tohi ükski tiks enam saata
        enne = len(h.session.saadetud)
        h.kell.edasi(100.0)
        await asyncio.sleep(0.05)
        self.assertEqual(len(h.session.saadetud), enne)

    async def test_H2_ended_keelab_ka_taaste(self):
        h = Harness("filosoof")
        kone(h)
        kasutaja(h)
        h.flow.on_conversation_end()
        o = h.flow.on_turn_complete(
            text="jäi pooleli", tail_len=11, audio_s=5.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertFalse(o["recover"])

    # ---- I: Gemini tõrge saatmise ajal --------------------------
    async def test_I_saatmise_torge_annab_broneeringu_tagasi(self):
        """L5 PARANDATUD. Vana versioon kontrollis olekut PÄRAST
        teardowni, mis seadis ENDED ja peitis ära tõsiasja, et
        broneeringut ei tagastatud. Nüüd kontrollitakse kõike ENNE
        sulgemist ja harnessi veatee on tootmisega sama.
        """
        s = FakeSession(purune=True)
        # tiks 0,05 s: iga ooteaken annab TÄPSELT ühe tiksu, nii et
        # tõrkeid saab ükshaaval loendada
        h = Harness("filosoof", session=s, tiks=0.05)
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        tiksuja = h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.08)

        # --- KÕIK KONTROLLID ENNE TEARDOWNI ---
        self.assertGreaterEqual(h.saatmistorkeid, 1,
                                "saatmistõrget ei tekkinudki")
        self.assertIn("seanss suletud", h.viimane_torge)
        self.assertEqual(paringud(h), [], "tõrkega päring loeti saadetuks")
        # 1. broneering tagastati
        self.assertEqual(h.flow.initiative.used, 0,
                         "eelarvet ei taastatud")
        # 2. olek ei jäänud GENERATING'uks
        self.assertNotEqual(h.flow.state, cf.GENERATING)
        self.assertEqual(h.flow.state, cf.COMPLETE_IDLE)
        # 3. tiksuja jääb ELUSAKS, kuni tõrge on mööduv (alla 3 järjest)
        self.assertLess(h.saatmistorkeid, 3)
        self.assertFalse(tiksuja.done(), "tiksuja suri ÜHE tõrke peale")
        self.assertFalse(h.ticker_lopetas)
        # 4. hilisem kõlbulik omaalgatus proovitakse UUESTI
        torkeid_enne = h.saatmistorkeid
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.06)
        self.assertGreater(h.saatmistorkeid, torkeid_enne,
                           "järgmist omaalgatust ei proovitud")
        self.assertEqual(h.flow.initiative.used, 0)
        # 5. PÜSIV tõrge ei tohi tekitada tühikäigutsüklit: kolm
        # järjestikust tõrget lõpetab tiksuja. Broneeringu tagastamine
        # tähendab, et eelarve seda ei piira – piirab loendur.
        await asyncio.sleep(0.3)
        self.assertEqual(h.saatmistorkeid, 3,
                         f"tiksuja ei peatunud ({h.saatmistorkeid} katset)")
        self.assertTrue(h.ticker_lopetas)
        await h.sulge_seanss()
        self.assertEqual(h.flow.state, cf.ENDED)

    async def test_I2_tootmise_veatee_on_harnessis_sama(self):
        """Kaitseb L5 taasteket: kui harnessi sisemine try/except
        kaob, siis see test kukub läbi, mitte ei muutu sisutühjaks."""
        kehad = []
        for nimi in ("initiative_ticker",):
            fn = getattr(Harness, nimi)
            src = inspect.getsource(fn)
            kehad.append(src)
        src = kehad[0]
        self.assertIn("except asyncio.CancelledError:", src)
        self.assertIn("self.flow.release_initiative()", src)
        self.assertIn("except Exception as e:", src)
        self.assertIn("self.flow.release_initiative()", src)
        # ja tootmises on sama kuju
        i = WS.index("_alg = flow.tick(")
        keha = WS[i:i + 4200]
        self.assertIn("except Exception as _ae:", keha)
        self.assertIn("flow.release_initiative()", keha)
        # L7: CancelledError annab broneeringu tagasi ja LEVIB EDASI
        j = keha.index("except asyncio.CancelledError:")
        k = keha.index("except Exception as _ae:")
        self.assertLess(j, k, "CancelledError'i haru on Exceptioni järel")
        self.assertIn("flow.release_initiative()", keha[j:k])
        self.assertIn("raise", keha[j:k])

    # ---- Luku kontroll: põimunud kirjutused -----------------------
    async def test_lukk_valistab_poimunud_kirjutused(self):
        s = FakeSession(viide=0.03)
        h = Harness("filosoof", session=s)
        kone(h)
        kasutaja(h)
        kone(h, "Ma kuulan.", True)
        h.kaivita()
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        # samal hetkel saadab vastuvõtutsükkel heli ja tööriista vastust
        await asyncio.gather(
            h.grealtime(audio=b"x" * 320),
            h.gsend(input="tooriista vastus"),
            asyncio.sleep(0.12),
        )
        h.teardown()
        self.assertFalse(s.poimunud,
                         "kaks juhtsõnumit kirjutati seanssi korraga")

    async def test_ilma_lukuta_poimumine_ON_tuvastatav(self):
        """Kontrollkatse: jäljend tuvastaks probleemi, kui lukk kaoks."""
        s = FakeSession(viide=0.03)
        await asyncio.gather(s.send(input="a"), s.send(input="b"))
        self.assertTrue(s.poimunud, "jäljend ei tuvasta põimumist")

    # ---- Tagasiastumise ajal tuleb kasutaja kõne ----------------
    async def test_taaste_tuhistub_kui_kasutaja_raagib_saatmise_ajal(self):
        h = Harness("asjalik", session=FakeSession(viide=0.3))
        kone(h)
        kasutaja(h)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text="jäi pooleli", tail_len=11, audio_s=5.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"])
        h.flow.on_recovery_dispatched("jäi pooleli", h.kell())
        # teine katse -> wait_s > 0
        o2 = h.flow.on_turn_complete(
            text="ikka pooleli", tail_len=12, audio_s=5.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o2["recover"])
        self.assertEqual(o2["wait_s"], 0.0, "taaste ootab ikka veel")
        # Aken, mille jooksul kasutaja saab vahele tulla, on nüüd
        # saatmise enda kestus (viide=0,3 s), mitte tagasiastumine.
        # AUS PIIR: ooteaega ei ole enam (omaniku nõue "kohe"), seega
        # tühistusaken on üks sündmustsükli samm. Kaitse ei ole enam
        # ajaline, vaid VALIDEERIMINE: kui kasutaja voor on vahepeal
        # vahetunud, ei lähe taaste välja ükskõik kui vara.
        ep = h.epoch
        kasutaja(h)                     # kasutaja võtab sõna ENNE saatmist
        saadeti = await h.taaste(o2, "ikka pooleli", ep)
        self.assertFalse(saadeti, "aegunud taaste läks kasutajale peale")
        self.assertEqual(paringud(h), [])

    async def test_taaste_laheb_ara_kui_kasutaja_vaikib(self):
        h = Harness("asjalik")
        kone(h)
        kasutaja(h)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text="jäi pooleli", tail_len=11, audio_s=5.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        h.flow.on_recovery_dispatched("jäi pooleli", h.kell())
        h.kell.edasi(5.0)        # kasutaja kõne EI ole enam värske
        o2 = h.flow.on_turn_complete(
            text="ikka pooleli", tail_len=12, audio_s=5.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        saadeti = await h.taaste(o2, "ikka pooleli")
        self.assertTrue(saadeti)
        self.assertEqual(len(h.session.saadetud), 1)
        self.assertIn("[SÜSTEEM]", h.session.saadetud[0][1])

    # ---- Seansi algus: omaalgatus EI tohi kõnet alustada --------
    async def test_seansi_algus_ei_kaivita_OMAALGATUST_ULDSE(self):
        """L6, OMANIKU NÕUE 11.11.2026.

        Varem: algolek AWAITING_USER avanes 2 x pausi järel ka täiesti
        tühja ajaloo peal (filosoof 10,1 s, zen 24,1 s, singer 28,1 s).
        Nüüd EI TOHI aja möödumine seansi avanemisest anda ühelegi
        karakterile kõneõigust – värav avaneb alles pärast esimest
        kasutaja kõnevooru.
        """
        h = Harness("filosoof", tiks=0.005)
        h.kaivita()
        for kordaja in (0, 1, 2, 3, 10):
            h.kell.t = 1000.0 + kordaja * h.flow.initiative.pause_s
            await asyncio.sleep(0.03)
            self.assertEqual(
                paringud(h), [],
                f"Maya alustas ise kõnet {kordaja} x pausi järel, "
                f"ilma et kasutaja oleks midagi öelnud")
        self.assertEqual(
            h.flow.tick(now=h.kell(), user_speaking=False,
                        tool_running=False)["reason"],
            "no_user_turn_yet")
        await h.sulge_seanss()

# =====================================================================
# KASUTAJA PRIORITEET TAASTE OOTAMISE AJAL (K5)
#
# JÄLJENDATUD. Need testid tõestavad, et vastuvõtutsükkel jookseb
# taaste ootamise ajal edasi ja et aegunud taaste ei saadeta. Nad EI
# tõesta Gemini Live käitumist.
# =====================================================================
def taaste_otsus(h, katse):
    """Vii voog taastekatseni `katse` ja tagasta selle otsus."""
    otsus = None
    for i in range(katse):
        h.kell.edasi(5.0)
        h.flow.on_generation_start(now=h.kell())
        otsus = h.flow.on_turn_complete(
            text=TAASTE_SABAD[i], tail_len=len(TAASTE_SABAD[i]),
            audio_s=4.0, tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        if i < katse - 1:
            assert otsus["recover"], otsus
            h.flow.on_recovery_dispatched(TAASTE_SABAD[i], h.kell())
    return otsus


def paringud(h):
    """Ainult `send` (viibad) – helivoog ei ole päring."""
    return [x for x in h.session.saadetud if x[0] == "send"]


class TestKasutajaPrioriteet(unittest.IsolatedAsyncioTestCase):

    async def _h(self, session=None):
        h = Harness("asjalik", session=session or FakeSession())
        kone(h)
        kasutaja(h)
        h.kaivita(ka_vastuvott=True)
        await asyncio.sleep(0)
        return h

    async def test_vastuvotutsykkel_tootab_saatmise_ajal(self):
        """Kasutaja kõne ei tohi KUNAGI oodata taastet.

        OOTEAEGU EI OLE ENAM (kõik katsed 0,0 s). Aken, mille jooksul
        vastuvõtutsükkel peab vaba olema, on nüüd saatmise enda kestus.
        """
        h = await self._h(session=FakeSession(viide=0.3))
        o = taaste_otsus(h, 2)
        self.assertEqual(o["wait_s"], 0.0, "taaste ootab ikka veel")
        t = h.kaivita_taaste(o, TAASTE_SABAD[1])
        # ootamise ajal saabub 25 helipaketti
        for _ in range(25):
            h.jarjekord.put_nowait(("audio", b"x" * 320))
        await asyncio.sleep(0.1)          # saatmine alles käib
        self.assertEqual(h.vastuvoetud, 25,
                         "vastuvõtutsükkel blokeerus taaste saatmise ajal")
        self.assertFalse(t.done(), "saatmine lõppes liiga vara")
        await asyncio.sleep(0.4)
        self.assertTrue(await t)
        h.teardown()

    async def test_koik_taastekatsed_on_ooteajata(self):
        """OMANIKU NÕUE: võimalikult kiiresti. Mitte ükski katse ei
        tohi enam sekundeid oodata."""
        h = await self._h()
        for i in range(cf.RECOVERY_BUDGET):
            h.kell.edasi(3.0)
            h.flow.on_generation_start(now=h.kell())
            saba = TAASTE_SABAD[i % len(TAASTE_SABAD)]
            o = h.flow.on_turn_complete(
                text=saba, tail_len=len(saba), audio_s=4.0,
                tail_is_terminal=False, user_interrupted=False,
                tool_running=False, playback_end_est=h.kell(),
                now=h.kell())
            self.assertTrue(o["recover"], f"katse {i + 1}: {o}")
            self.assertEqual(o["wait_s"], 0.0,
                             f"katse {i + 1} ootab {o['wait_s']} s")
            h.flow.on_recovery_dispatched(saba, h.kell())
        self.assertEqual(cf.RECOVERY_BACKOFF_S, (0.0,))
        self.assertEqual(cf.RECOVERY_BUDGET, 12)
        await h.sulge_seanss()

    async def test_kasutaja_kone_saatmise_ajal_tyhistab(self):
        h = await self._h(session=FakeSession(viide=0.3))
        o = taaste_otsus(h, 2)
        t = h.kaivita_taaste(o, TAASTE_SABAD[1])
        await asyncio.sleep(0.05)
        for _ in range(10):
            h.jarjekord.put_nowait(("audio", b"y" * 320))
        h.jarjekord.put_nowait(("user_speech", None))
        await asyncio.sleep(0.1)
        self.assertEqual(h.vastuvoetud, 11,
                         "heli jäi taaste saatmise taha kinni")
        await asyncio.sleep(0.4)
        self.assertTrue(t.cancelled() or t.done())
        h.teardown()

    async def test_kasutaja_kone_VAHETULT_enne_saatmist(self):
        """Tühistamine EI jõua – ainus kaitse on valideerimine luku all."""
        h = await self._h(session=FakeSession(viide=0.3))
        o = taaste_otsus(h, 2)
        # TEADLIKULT ilma tühistamiseta: ainult loendur liigub, ja
        # liigub ENNE kui task jõuab valideerimiseni. 0 ooteajaga on
        # see ainus koht, kus aegunud taastet veel peatada saab.
        ep = h.epoch
        h.epoch += 1
        saadeti = await h.taaste(o, TAASTE_SABAD[1], ep)
        self.assertFalse(saadeti, "aegunud taaste jõudis kohale")
        self.assertEqual(paringud(h), [])
        h.teardown()

    async def test_uus_kasutaja_voor_vanema_taaste_ajal(self):
        """AUS PIIR 0 ooteajaga: kui saatmine on juba ALANUD, viib
        `shield` selle lõpuni (muidu jääks kirjutus pooleli). Kaitse
        kehtib saatmise EEL – seda kontrollib
        `test_kasutaja_kone_VAHETULT_enne_saatmist`."""
        h = await self._h(session=FakeSession(viide=0.3))
        o = taaste_otsus(h, 3)
        t_vana = h.kaivita_taaste(o, TAASTE_SABAD[2])
        await asyncio.sleep(0.05)          # saatmine on lennus
        kasutaja(h)                        # uus voor: loendur + tühistus
        self.assertEqual(h.taaste_tuhistusi, 1)
        await asyncio.sleep(0.4)
        self.assertTrue(t_vana.cancelled() or t_vana.done())
        # uus Maya voor jääb jälle pooleli -> ahel algab OTSAST
        h.kell.edasi(3.0)
        h.flow.on_generation_start(now=h.kell())
        o2 = h.flow.on_turn_complete(
            text="hoopis uus poolik mõte, mis jäi", tail_len=31,
            audio_s=4.0, tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o2["recover"])
        self.assertEqual(o2["attempt"], 1, "eelarve ei alanud otsast")
        self.assertEqual(o2["wait_s"], 0.0)
        self.assertTrue(await h.kaivita_taaste(o2, "hoopis uus poolik"))
        # KAKS päringut kokku: lennus olnud taaste viidi `shield`-iga
        # lõpuni (pooleli kirjutust ei jäeta) ja uus tuli peale.
        self.assertEqual(len(paringud(h)), 2)
        h.teardown()

    async def test_seanss_lopeb_taaste_saatmise_ajal(self):
        h = await self._h(session=FakeSession(viide=0.5))
        o = taaste_otsus(h, 3)
        t = h.kaivita_taaste(o, TAASTE_SABAD[2])
        await asyncio.sleep(0.05)          # saatmine on lennus
        h.teardown()                       # = tootmise finally
        await asyncio.sleep(0.6)
        self.assertTrue(t.cancelled() or t.done())
        # AUS PIIR: juba alanud kirjutus viiakse lõpuni (`shield`),
        # muidu jääks WebSocketi raam pooleli. Oluline on, et task
        # LÕPEB ja lukk vabaneb.
        self.assertFalse(h.lukk.locked(), "saatmislukk jäi kinni")
        self.assertEqual(h.flow.state, cf.ENDED)

    async def test_transpordi_torge_taaste_ajal(self):
        """Tühistamist ei toimu, aga seanss on surnud -> ei saadeta."""
        h = await self._h(session=FakeSession(viide=0.3))
        o = taaste_otsus(h, 2)
        # Tõrge saabub ENNE kui task jõuab valideerimiseni – 0
        # ooteajaga on see ainus punkt, kus saatmist veel ära jätta saab.
        ep = h.epoch
        h.transport_viga = "Gemini 1007"
        saadeti = await h.taaste(o, TAASTE_SABAD[1], ep)
        self.assertFalse(saadeti)
        self.assertEqual(paringud(h), [])
        h.teardown()

    async def test_omaalgatus_ja_taaste_ei_voistle(self):
        """Taaste ootamise ajal EI tohi omaalgatus vahele tulla."""
        h = Harness("filosoof", session=FakeSession(viide=0.4), tiks=0.005)
        kone(h)
        kasutaja(h)
        h.kaivita(ka_vastuvott=True)
        o = taaste_otsus(h, 3)             # olek jääb INCOMPLETE
        self.assertEqual(h.flow.state, cf.INCOMPLETE)
        t = h.kaivita_taaste(o, TAASTE_SABAD[2])
        # lase taimeril palju tiksuda ja aega hüpata
        h.kell.edasi(h.flow.initiative.pause_s * 5)
        await asyncio.sleep(0.2)
        self.assertEqual(paringud(h), [],
                         "omaalgatus tuli taaste ootamise ajal vahele")
        self.assertTrue(await t)
        self.assertEqual(len(paringud(h)), 1)
        # ja pärast taastet on olek GENERATING -> endiselt mitte idle
        self.assertEqual(h.flow.state, cf.GENERATING)
        await asyncio.sleep(0.05)
        self.assertEqual(len(paringud(h)), 1,
                         "kaks samaaegset autonoomset genereerimist")
        h.teardown()

    async def test_lukk_jaab_moodavaks_ka_kolme_saatjaga(self):
        s = FakeSession(viide=0.02)
        h = Harness("filosoof", session=s, tiks=0.005)
        kone(h)
        kasutaja(h)
        h.kaivita(ka_vastuvott=True)
        o = taaste_otsus(h, 2)
        h.kaivita_taaste(o, TAASTE_SABAD[1])
        for _ in range(6):
            h.jarjekord.put_nowait(("audio", b"z" * 320))
        h.kell.edasi(h.flow.initiative.pause_s * 3)
        await asyncio.sleep(0.9)
        h.teardown()
        self.assertFalse(s.poimunud, "juhtsõnumid põimusid")


# =====================================================================
# L6: ESIMESE KASUTAJAVOORU VÄRAV — KÕIK 10 KARAKTERIT
#
# JÄLJENDATUD. Käivitab päris `initiative_ticker`-i jäljendatud seansi
# ja kella peal. EI tõesta Gemini käitumist.
# =====================================================================
class TestEsimeseVooruVarav(unittest.IsolatedAsyncioTestCase):

    async def test_L6_ykski_karakter_ei_alusta_ise_0_1_2_3_pausi_jarel(self):
        """OMANIKU NÕUE: ainult aja möödumine seansi avanemisest ei
        anna ühelegi karakterile kõneõigust."""
        for persona in sorted(cf.INITIATIVE):
            with self.subTest(persona=persona):
                h = Harness(persona, tiks=0.005)
                h.kaivita()
                paus = h.flow.initiative.pause_s
                for kordaja in (0, 1, 2, 3):
                    h.kell.t = 1000.0 + kordaja * paus
                    await asyncio.sleep(0.03)
                    self.assertEqual(
                        paringud(h), [],
                        f"{persona} alustas ise kõnet {kordaja} x pausi "
                        f"({kordaja * paus:.0f} s) järel")
                d = h.flow.tick(now=h.kell(), user_speaking=False,
                                tool_running=False)
                self.assertFalse(d["speak"])
                self.assertEqual(d["reason"], "no_user_turn_yet")
                await h.sulge_seanss()

    async def test_L6_parast_esimest_kasutajavooru_omaalgatus_TOIMIB(self):
        """Väravat ei tohi jätta kinni ülejäänud seansiks."""
        for persona in sorted(cf.INITIATIVE):
            with self.subTest(persona=persona):
                h = Harness(persona, tiks=0.005)
                h.kaivita()
                # esimene PÄRIS kasutajavoor + Maya vastus
                kasutaja(h)
                kone(h, "Nii see minu meelest on.", True)
                paus = h.flow.initiative.pause_s
                h.kell.edasi(paus * 0.5)
                await asyncio.sleep(0.03)
                self.assertEqual(paringud(h), [],
                                 f"{persona} rääkis enne oma pausi")
                h.kell.edasi(paus)
                await asyncio.sleep(0.03)
                self.assertEqual(
                    len(paringud(h)), 1,
                    f"{persona} ei võtnud sõna ka pärast kasutajavooru")
                await h.sulge_seanss()

    async def test_L6_karakteri_pausid_ja_eelarved_on_MUUTUMATUD(self):
        oodatud = {"zen": (12.0, 1), "singer": (14.0, 1),
                   "asjalik": (7.0, 2), "mentor": (6.0, 2),
                   "treener": (7.0, 2), "sober": (7.0, 2),
                   "filosoof": (5.0, 3), "sarkastiline": (5.0, 3),
                   "romantiline": (5.0, 3), "custom": (5.0, 3)}
        tegelik = {k: (v["pause_s"], v["budget"])
                   for k, v in cf.INITIATIVE.items()}
        self.assertEqual(tegelik, oodatud)
        self.assertEqual(cf.INITIATIVE_DEFAULT,
                         {"pause_s": 8.0, "budget": 2})

    async def test_L6_viip_ei_viita_olematule_eelmisele_mottele(self):
        ilma = cf.initiative_prompt(7.0, has_prior_thought=False)
        self.assertNotIn("arenda eelmist mõtet", ilma)
        self.assertIn("EI OLE", ilma)
        # ei tervitust, ei avalauset
        self.assertIn("Ära tervita", ilma)
        self.assertIn("ära tutvusta ennast", ilma)
        self.assertNotIn("Tere", ilma)
        # olemasoleva sõnastus on MUUTUMATU
        on = cf.initiative_prompt(7.0, has_prior_thought=True)
        self.assertIn("arenda eelmist mõtet", on)
        self.assertEqual(on, cf.initiative_prompt(7.0))

    async def test_MOLEMAD_viibad_nouavad_KOHE_konet(self):
        """MÕÕDETUD 1007 PÕHJUS: nii taaste- kui omaalgatuse viip on
        TEKSTISISEND heliseanssi. Kui mudel vastab sellele ainult
        mõttega, lõpeb seanss 1007-ga – see mudel ei toeta
        tekstiväljundit üldse. Logitõend: 01:56:03, 01:56:48 (taaste
        järel) ja 03:51:10 (omaalgatuse järel), igal korral null
        helirida ja [MAYA MÕTE] plokk vahel."""
        nouded = ("kohe ja ainult kõnena", "ära analüüsi")
        for n in nouded:
            self.assertIn(n, cf.RECOVERY_PROMPT.lower(), f"taaste: {n}")
        for lipp in (True, False):
            t = cf.initiative_prompt(7.0, has_prior_thought=lipp).lower()
            for n in nouded:
                self.assertIn(n, t, f"omaalgatus(prior={lipp}): {n}")

    async def test_L6_viip_valitakse_maya_tegeliku_konest(self):
        h = Harness("filosoof")
        kasutaja(h)
        self.assertFalse(h.flow.assistant_said_something)
        # tühi voor EI loe Maya kõneks
        h.flow.on_generation_start(now=h.kell())
        h.flow.on_turn_complete(
            text="", tail_len=0, audio_s=0.0, tail_is_terminal=False,
            user_interrupted=False, tool_running=False,
            playback_end_est=h.kell(), now=h.kell())
        self.assertFalse(h.flow.assistant_said_something)
        kone(h, "Nüüd ütlesin midagi.", True)
        self.assertTrue(h.flow.assistant_said_something)


# =====================================================================
# SEANSI SULGEMINE — 10 ADVERSARIAALSET STSENAARIUMI (L1, L3)
#
# JÄLJENDATUD. Harness kordab tootmise `_sulge_seanss()` kuju;
# staatilised testid nõuavad, et tootmisfailis oleks sama.
# =====================================================================
class TestSulgemine(unittest.IsolatedAsyncioTestCase):

    async def _taisseanss(self, persona="asjalik", session=None, tiks=0.01):
        h = Harness(persona, session=session, tiks=tiks)
        kone(h)
        kasutaja(h)
        h.kaivita(ka_vastuvott=True)
        await asyncio.sleep(0)
        return h

    def _koik_lopetatud(self, h):
        return [t for t in h.oodatud if not t.done()]

    # 1
    async def test_01_normaalne_lopp(self):
        h = await self._taisseanss()
        await h.sulge_seanss("normaalne lõpp")
        self.assertEqual(self._koik_lopetatud(h), [],
                         "mõni task jäi pooleli")
        self.assertEqual(h.lopetamata, [])
        self.assertEqual(h.flow.state, cf.ENDED)
        self.assertFalse(h.lukk.locked(), "saatmislukk jäi kinni")

    # 2
    async def test_02_websocketdisconnect(self):
        class WSDisconnect(Exception):
            pass
        h = await self._taisseanss()
        try:
            raise WSDisconnect("klient kadus")
        except WSDisconnect:
            await h.sulge_seanss("WebSocketDisconnect")
        self.assertEqual(self._koik_lopetatud(h), [])
        self.assertFalse(h.lukk.locked())

    # 3
    async def test_03_valimine_CancelledError(self):
        h = await self._taisseanss()
        try:
            raise asyncio.CancelledError()
        except asyncio.CancelledError:
            await h.sulge_seanss("CancelledError")
        self.assertEqual(self._koik_lopetatud(h), [])
        self.assertTrue(h.suletud)

    # 4
    async def test_04_taaste_tuhistus_SAATMISE_ajal(self):
        h = await self._taisseanss(session=FakeSession(viide=0.5))
        o = taaste_otsus(h, 3)
        self.assertEqual(o["wait_s"], 0.0, "taaste ootab ikka veel")
        t = h.kaivita_taaste(o, TAASTE_SABAD[2])
        await asyncio.sleep(0.05)
        # faas1 peab mahutama lennus oleva kirjutuse (0,5 s), muidu
        # eskaleerub sulgemine transpordi katkestamisele.
        tulemus = await h.sulge_seanss("sulgemine saatmise ajal",
                                       faas1=0.9)
        self.assertTrue(t.done())
        # AUS PIIR: lennus olev kirjutus viiakse `shield`-iga lõpuni –
        # pooleli raam oleks hullem kui üks ülearune viip surevasse
        # seanssi. Nõuded on: task LÕPEB, lukk vabaneb, sulgemine
        # raporteerib edu ja transporti ei pidanud katkestama.
        self.assertTrue(tulemus["ok"], tulemus)
        self.assertFalse(tulemus["transport_katkestatud"])
        self.assertFalse(h.lukk.locked())

    # 5
    async def test_05_taaste_tuhistus_AKTIIVSE_saatmise_ajal(self):
        s = FakeSession(viide=0.25)       # pikk kirjutus
        h = await self._taisseanss(session=s)
        o = taaste_otsus(h, 1)
        self.assertEqual(o["wait_s"], 0.0)
        t = h.kaivita_taaste(o, TAASTE_SABAD[0])
        await asyncio.sleep(0.05)         # kirjutamine käib
        self.assertTrue(h.lukk.locked(), "kirjutamine ei jõudnud alata")
        await h.sulge_seanss("sulgemine keset kirjutamist")
        # SHIELD: kirjutus LÕPETATI ära, mitte ei jäetud pooleli
        self.assertEqual(len(paringud(h)), 1,
                         "kirjutamine jäeti pooleli")
        self.assertFalse(h.lukk.locked(),
                         "lukk jäi kinni pärast sulgemist")
        self.assertTrue(t.done())

    # 6
    async def test_06_korduvad_sulgemissignaalid(self):
        h = await self._taisseanss()
        await h.sulge_seanss("esimene")
        tyhistusi = len(h.tyhistatud)
        oodatud = list(h.oodatud)
        for _ in range(4):
            await h.sulge_seanss("kordus")
        self.assertEqual(len(h.tyhistatud), tyhistusi,
                         "korduv sulgemine tühistas uuesti")
        self.assertEqual(h.oodatud, oodatud)

    # 7
    async def test_07_aktiivne_realtime_saatmine_sulgemise_ajal(self):
        s = FakeSession(viide=0.15)
        h = await self._taisseanss(session=s)
        saatja = asyncio.ensure_future(h.grealtime(audio=b"q" * 320))
        await asyncio.sleep(0.02)
        await h.sulge_seanss("sulgemine keset helisaatmist")
        await asyncio.sleep(0.2)
        self.assertTrue(saatja.done())
        self.assertFalse(h.lukk.locked())

    # 8
    async def test_08_parast_koristust_ei_ole_ootel_taske(self):
        h = await self._taisseanss()
        o = taaste_otsus(h, 2)
        h.kaivita_taaste(o, TAASTE_SABAD[1])
        await asyncio.sleep(0.02)
        await h.sulge_seanss()
        await asyncio.sleep(0.05)
        rippuvad = [t for t in h.taustataskid if not t.done()]
        self.assertEqual(rippuvad, [], f"rippuvad taskid: {rippuvad}")
        self.assertIsNone(h.taastetask)

    # 9
    async def test_09_lukud_ei_jaa_kinni(self):
        s = FakeSession(viide=0.05)
        h = await self._taisseanss(session=s, tiks=0.005)
        o = taaste_otsus(h, 2)
        h.kaivita_taaste(o, TAASTE_SABAD[1])
        for _ in range(4):
            h.jarjekord.put_nowait(("audio", b"w" * 320))
        h.kell.edasi(h.flow.initiative.pause_s * 3)
        await asyncio.sleep(0.1)
        await h.sulge_seanss()
        await asyncio.sleep(0.2)
        self.assertFalse(h.lukk.locked())
        self.assertFalse(s.poimunud, "juhtsõnumid põimusid")

    # 10
    async def test_10_malu_konsolideerimine_jaab_puutumata(self):
        """Mälutask EI kuulu seansi omandisse ja peab üle elama."""
        valmis = []

        async def malu_konsolideerimine():
            await asyncio.sleep(0.25)      # kestab kauem kui seanss
            valmis.append("mälu salvestatud")

        h = await self._taisseanss()
        malu = asyncio.ensure_future(malu_konsolideerimine())
        # TEADLIKULT mitte registreeri: vastab _PENDING_MEMORY_TASKS-ile
        await h.sulge_seanss()
        self.assertNotIn(malu, h.oodatud)
        self.assertFalse(malu.done(), "mälutask tühistati seansi lõpus")
        await malu
        self.assertEqual(valmis, ["mälu salvestatud"])


# =====================================================================
# ELUTSÜKLI VASTUVÕTUKRITEERIUMID 1-20
#
# JÄLJENDATUD SERVERIPOOL. Androidi tegelikku taasesitust siin EI
# kontrollita – vt testid 10, 11 ja aruande punkt 8.
# =====================================================================
class TestVastuvotukriteeriumid(unittest.IsolatedAsyncioTestCase):

    async def _h(self, persona="asjalik", session=None, tiks=0.01):
        h = Harness(persona, session=session, tiks=tiks)
        h.kaivita(ka_vastuvott=True)
        await asyncio.sleep(0)
        return h

    # 1
    async def test_01_uus_seanss_vaikib_kuni_esimese_vooruni(self):
        h = await self._h("filosoof", tiks=0.005)
        h.kell.edasi(h.flow.initiative.pause_s * 4)
        await asyncio.sleep(0.05)
        self.assertEqual(paringud(h), [])
        self.assertEqual(h.flow.tick(now=h.kell(), user_speaking=False,
                                     tool_running=False)["reason"],
                         "no_user_turn_yet")
        await h.sulge_seanss()

    # 2 — serveripoolne viivitus ilma kunstlikke oodet
    async def test_02_esimene_vastus_ilma_lisaviivitust(self):
        """Server ei tohi kasutaja vooru ja vastuse vahele oma
        ooteaega lisada. Mõõdame ainult SERVERI osa."""
        h = await self._h()
        t0 = asyncio.get_running_loop().time()
        kasutaja(h)
        # Maya hakkab kohe genereerima; serveri otsustusloogika aeg
        h.flow.on_generation_start(now=h.kell())
        t1 = asyncio.get_running_loop().time()
        self.assertLess(t1 - t0, 0.01,
                        "serveri otsustusloogika lisab viivitust")
        self.assertEqual(h.flow.state, cf.GENERATING)
        await h.sulge_seanss()

    # 3
    async def test_03_loomulik_lopp_ei_kaivita_taastet(self):
        h = await self._h()
        kasutaja(h)
        o = kone(h, "See on täiesti valmis mõte.", True)
        self.assertFalse(o["recover"])
        self.assertEqual(h.flow.state, cf.COMPLETE_IDLE)
        await h.sulge_seanss()

    # 4
    async def test_04_poolik_vastus_kaivitab_taaste(self):
        h = await self._h()
        kasutaja(h)
        h.kell.edasi(3.0)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text=TAASTE_SABAD[0], tail_len=len(TAASTE_SABAD[0]),
            audio_s=4.0, tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"])
        self.assertEqual(o["wait_s"], 0.0, "esimene katse ootab asjata")
        self.assertTrue(await h.kaivita_taaste(o, TAASTE_SABAD[0]))
        self.assertEqual(len(paringud(h)), 1)
        await h.sulge_seanss()

    # 5
    async def test_05_taaste_ei_korda_juba_oeldut(self):
        h = await self._h()
        kasutaja(h)
        saba = TAASTE_SABAD[0]
        # viip käsib jätkata, MITTE otsast alustada
        self.assertIn("Jätka TÄPSELT sealt, kus katkesid", cf.RECOVERY_PROMPT)
        self.assertIn("Ära alusta otsast", cf.RECOVERY_PROMPT)
        h.kell.edasi(3.0)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text=saba, tail_len=len(saba), audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        await h.kaivita_taaste(o, saba)
        # ja kui Gemini KORDAB sama saba, ahel peatub
        h.kell.edasi(5.0)
        h.flow.on_generation_start(now=h.kell())
        o2 = h.flow.on_turn_complete(
            text=saba, tail_len=len(saba), audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertFalse(o2["recover"])
        self.assertEqual(o2["reason"], "duplicate_detected")
        await h.sulge_seanss()

    # 6 + 7
    async def test_06_07_omaalgatus_ja_karakteri_ajastus(self):
        for persona, paus in (("filosoof", 5.0), ("mentor", 6.0),
                              ("zen", 12.0), ("singer", 14.0)):
            with self.subTest(persona=persona):
                h = await self._h(persona, tiks=0.005)
                self.assertEqual(h.flow.initiative.pause_s, paus)
                kasutaja(h)
                kone(h, "Nii see minu meelest on.", True)
                h.kell.edasi(paus * 0.8)
                await asyncio.sleep(0.03)
                self.assertEqual(paringud(h), [])
                h.kell.edasi(paus * 0.3)
                await asyncio.sleep(0.03)
                self.assertEqual(len(paringud(h)), 1)
                await h.sulge_seanss()

    # 8
    async def test_08_omaalgatus_ei_saa_olla_lopmatu(self):
        h = await self._h("filosoof", tiks=0.005)
        kasutaja(h)
        kone(h, "Alustasin.", True)
        for _ in range(15):
            h.kell.edasi(h.flow.initiative.pause_s + 1)
            await asyncio.sleep(0.02)
            h.flow.on_turn_complete(
                text="Veel üks mõte.", tail_len=14, audio_s=1.0,
                tail_is_terminal=True, user_interrupted=False,
                tool_running=False, playback_end_est=h.kell(),
                now=h.kell())
        self.assertLessEqual(len(paringud(h)), h.flow.initiative.budget)
        await h.sulge_seanss()

    # 9
    async def test_09_kasutaja_kone_tyhistab_omaalgatuse_KOHE(self):
        s = FakeSession(viide=0.08)
        h = await self._h("filosoof", session=s, tiks=0.005)
        kasutaja(h)
        kone(h, "Nii see on.", True)
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.02)
        self.assertEqual(h.flow.state, cf.GENERATING)
        kasutaja(h)                        # kasutaja võtab sõna
        self.assertEqual(h.flow.state, cf.USER_SPEAKING)
        self.assertEqual(h.flow.initiative.used, 0, "eelarve ei nullistunud")
        # järgmine tiks EI tohi uut päringut saata, kuni kasutaja räägib
        enne = len(paringud(h))
        await asyncio.sleep(0.03)
        self.assertEqual(len(paringud(h)), enne)
        await h.sulge_seanss()

    # 10 + 11 — SERVERIPOOL. Seadmepool on KONTROLLIMATA.
    def test_10_11_server_saadab_katkestuse_ja_ei_saada_aegunut(self):
        """Mida server GARANTEERIB: `{"type":"interrupted"}` läheb
        kliendile ja aegunud taastet/omaalgatust ei saadeta.
        Mida server EI saa garanteerida: et Android taasesituse
        PÄRISELT katkestab – see nõuab APK-d, mida me ei ehita."""
        i = WS.index('"type": "interrupted"')
        keha = WS[max(0, i - 1800):i + 200]
        self.assertIn("async with ws_send_lock:", keha)
        self.assertIn("_tyhista_ootel_taaste(", keha)
        self.assertIn("flow.on_interrupted(", keha)
        # kliendi pool: käsitleja on olemas (aga ehitamata)
        self.assertIn("stopLiveAudio", HTML)
        self.assertIn("interrupted", HTML)

    # 12
    async def test_12_korduv_tyhistus_ei_vabasta_lukku(self):
        s = FakeSession(viide=0.2)
        h = await self._h(session=s)
        kasutaja(h)
        o = taaste_otsus(h, 1)
        t = h.kaivita_taaste(o, TAASTE_SABAD[0])
        await asyncio.sleep(0.05)
        self.assertTrue(h.lukk.locked())
        t.cancel()
        await asyncio.sleep(0.01)
        t.cancel()                          # TEINE tühistus drenaaži ajal
        await asyncio.sleep(0.01)
        self.assertTrue(h.lukk.locked(),
                        "lukk vabanes, kuigi kirjutamine käib veel")
        await asyncio.sleep(0.25)
        self.assertFalse(h.lukk.locked())
        self.assertEqual(len(paringud(h)), 1, "kirjutus jäi pooleli")
        await h.sulge_seanss()

    # 13
    async def test_13_sulgemine_aktiivse_realtime_operatsiooniga(self):
        s = FakeSession(viide=0.15)
        h = await self._h(session=s)
        saatja = asyncio.ensure_future(h.grealtime(audio=b"m" * 320))
        await asyncio.sleep(0.02)
        tulemus = await h.sulge_seanss("realtime aktiivne")
        self.assertTrue(tulemus["ok"], tulemus)
        await asyncio.sleep(0.2)
        self.assertTrue(saatja.done())

    # 14
    async def test_14_sulgemine_aktiivse_shieldiga_taastega(self):
        s = FakeSession(viide=0.3)
        h = await self._h(session=s)
        kasutaja(h)
        o = taaste_otsus(h, 1)
        t = h.kaivita_taaste(o, TAASTE_SABAD[0])
        await asyncio.sleep(0.05)
        tulemus = await h.sulge_seanss("taaste lennus", faas1=1.0)
        self.assertTrue(tulemus["ok"], tulemus)
        self.assertTrue(t.done())
        self.assertEqual(len(paringud(h)), 1,
                         "shielditud kirjutus jäeti pooleli")
        self.assertFalse(h.lukk.locked())

    # 15 + 16
    async def test_15_16_PUSIVALT_blokeerunud_saatmine(self):
        """Kirjutus, mis EI LÕPE kunagi ise. Ainus väljapääs on
        transpordi katkestamine – websockets 17.3 vabastab siis
        `drain_waiters`-id."""
        s = FakeSession(blokeeru=True)
        h = await self._h(session=s)
        kasutaja(h)
        o = taaste_otsus(h, 1)
        t = h.kaivita_taaste(o, TAASTE_SABAD[0])
        await asyncio.sleep(0.05)
        self.assertTrue(h.lukk.locked(), "kirjutus ei jõudnud kinni jääda")
        tulemus = await h.sulge_seanss("püsivalt blokeerunud")
        # 16: transport katkestati ja see VABASTAS kirjutuse
        self.assertTrue(tulemus["transport_katkestatud"])
        self.assertTrue(s._ws.transport.abort_kutsutud)
        self.assertTrue(t.done(), "task jäi igavesti kinni")
        # 15: ja sulgemine jõudis seetõttu lõpuni
        self.assertTrue(tulemus["ok"], tulemus)
        self.assertFalse(h.lukk.locked())

    # 17
    async def test_17_parast_sulgemist_ei_ole_seansi_taske(self):
        h = await self._h(tiks=0.005)
        kasutaja(h)
        o = taaste_otsus(h, 2)
        h.kaivita_taaste(o, TAASTE_SABAD[1])
        tulemus = await h.sulge_seanss()
        self.assertTrue(tulemus["ok"])
        self.assertEqual(tulemus["lopetamata"], [])
        rippuvad = [t for t in h.taustataskid if not t.done()]
        self.assertEqual(rippuvad, [])
        self.assertIsNone(h.taastetask)

    # 18
    async def test_18_ebaonnestunud_sulgemist_ei_nimetata_onnestunuks(self):
        """Task, mida tühistada EI SAA (summutab CancelledError'i).
        Sulgemine PEAB raporteerima ok=False."""
        h = await self._h()

        luba_surra = {"v": False}

        async def summutaja():
            while True:
                try:
                    await asyncio.sleep(0.02)
                except asyncio.CancelledError:
                    if luba_surra["v"]:
                        raise          # testi enda koristus
                    continue           # ei lase ennast tappa

        paha = h.registreeri(asyncio.ensure_future(summutaja()))
        paha.set_name("summutaja")
        await asyncio.sleep(0.02)
        tulemus = await h.sulge_seanss("summutaja elus", faas1=0.1, faas2=0.1)
        self.assertFalse(tulemus["ok"],
                         "sulgemine kuulutas edu, kuigi task elab")
        self.assertIn("summutaja", tulemus["lopetamata"])
        self.assertFalse(paha.done())
        # koristus: nüüd tohib surra, muidu ripub testiraamistik
        luba_surra["v"] = True
        paha.cancel()
        with contextlib.suppress(Exception):
            await asyncio.wait({paha}, timeout=0.2)

    # 19
    async def test_19_tyhistamine_ei_neela_broneeringut(self):
        """L7: tühistus TÄPSELT siis, kui broneering on tehtud."""
        s = FakeSession(viide=0.2)
        h = await self._h("filosoof", session=s, tiks=0.005)
        kasutaja(h)
        kone(h, "Nii see on.", True)
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.02)
        self.assertEqual(h.flow.initiative.used, 1, "broneering puudub")
        tiksuja = h.taustataskid[0]
        tiksuja.cancel()
        await asyncio.sleep(0.3)
        self.assertEqual(h.flow.initiative.used, 0,
                         "tühistamine neelas broneeringu ära")
        self.assertNotEqual(h.flow.state, cf.GENERATING)
        await h.sulge_seanss()

    # 20
    async def test_20_mooduv_torge_ei_lukusta_vestlust(self):
        class PoolPurune(FakeSession):
            def __init__(self):
                super().__init__()
                self.korgi = 1

            async def _kirjuta(self, tyyp, sisu):
                if self.korgi > 0:
                    self.korgi -= 1
                    raise RuntimeError("mööduv tõrge")
                await FakeSession._kirjuta(self, tyyp, sisu)

        s = PoolPurune()
        # tiks 0,05 s: iga ooteaken = TÄPSELT üks tiks, nii et
        # tõrke ja õnnestumise vahepealset olekut saab vaadata
        h = await self._h("filosoof", session=s, tiks=0.05)
        kasutaja(h)
        kone(h, "Nii see on.", True)
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.08)
        self.assertEqual(h.saatmistorkeid, 1)
        self.assertEqual(paringud(h), [], "tõrkega päring loeti saadetuks")
        self.assertEqual(h.flow.initiative.used, 0,
                         "broneeringut ei tagastatud")
        self.assertEqual(h.flow.state, cf.COMPLETE_IDLE)
        # ja järgmine katse ÕNNESTUB
        h.kell.edasi(h.flow.initiative.pause_s + 1)
        await asyncio.sleep(0.08)
        self.assertEqual(len(paringud(h)), 1,
                         "mööduv tõrge blokeeris vestluse jäädavalt")
        # taaste töötab samuti edasi
        h.kell.edasi(3.0)
        h.flow.on_generation_start(now=h.kell())
        o = h.flow.on_turn_complete(
            text=TAASTE_SABAD[3], tail_len=20, audio_s=4.0,
            tail_is_terminal=False, user_interrupted=False,
            tool_running=False, playback_end_est=h.kell(), now=h.kell())
        self.assertTrue(o["recover"])
        self.assertTrue(await h.kaivita_taaste(o, TAASTE_SABAD[3]))
        await h.sulge_seanss()


# =====================================================================
# STAATILINE VASTAVUS: tootmisfailis ON samad kaitsed
# =====================================================================
class TestStaatilineVastavus(unittest.TestCase):
    """Katab augu, mille jätab jäljendatud tsükkel: need kontrollid
    loevad PÄRIS tootmisfaili, mitte harnessi."""

    # ---- K5: ootamine EI tohi olla vastuvõtutsüklis --------------
    def test_K5_vastuvotutsyklis_ei_ole_uhtegi_sleep_i(self):
        """MASINLOETAV TÕEND. Varem oli `await asyncio.sleep(wait_s)`
        `send_to_client` `async for` keha sees, seega 0,6-1,2 s jooksul
        ei töödeldud kasutaja heli ega `interrupted` teateid."""
        puu = ast.parse(WS)
        leitud = None
        for n in ast.walk(puu):
            if isinstance(n, ast.AsyncFunctionDef) and \
                    n.name == "send_to_client":
                for x in ast.walk(n):
                    if isinstance(x, ast.AsyncFor):
                        leitud = x
                        break
                break
        self.assertIsNotNone(leitud, "send_to_client async for puudub")
        uinakud = [y.lineno for y in ast.walk(leitud)
                   if isinstance(y, ast.Call)
                   and isinstance(y.func, ast.Attribute)
                   and y.func.attr == "sleep"]
        self.assertEqual(uinakud, [],
                         f"vastuvõtutsükkel ootab endiselt (read {uinakud})")

    def test_K5_taaste_jookseb_omas_taskis(self):
        i = WS.index('if _otsus["recover"]:')
        keha = WS[i:i + 900]
        self.assertIn("asyncio.create_task(", keha)
        self.assertIn("taaste_saatja(", keha)
        # ja seda EI oodata siinsamas
        self.assertNotIn("await taaste_saatja", WS)
        self.assertNotIn("await asyncio.sleep", keha)

    def test_K5_ootamine_on_taaste_saatja_sees(self):
        puu = ast.parse(WS)
        fn = None
        for n in ast.walk(puu):
            if isinstance(n, ast.AsyncFunctionDef) and \
                    n.name == "taaste_saatja":
                fn = n
        self.assertIsNotNone(fn, "taaste_saatja puudub")
        uinakud = [y for y in ast.walk(fn)
                   if isinstance(y, ast.Call)
                   and isinstance(y.func, ast.Attribute)
                   and y.func.attr == "sleep"]
        self.assertEqual(len(uinakud), 1,
                         "ootamine ei ole taaste_saatja sees")

    def test_K5_taaste_saatjat_ei_oota_ykski_tsykkel(self):
        """`create_task` ainus kutsuja; mitte `await taaste_saatja(...)`."""
        puu = ast.parse(WS)
        for n in ast.walk(puu):
            if isinstance(n, ast.Await):
                v = n.value
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) \
                        and v.func.id == "taaste_saatja":
                    self.fail(f"taaste_saatjat oodatakse real {n.lineno}")

    # ---- Võidujooks: kontroll JA saatmine sama luku all ----------
    def test_valideerimine_jookseb_luku_all(self):
        i = WS.index("async def gsend(")
        keha = WS[i:i + 3200]
        j = keha.index("async with gemini_send_lock:")
        k = keha.index("ok, miks = valideeri()")
        m = keha.index("session.send(**kw)")
        self.assertLess(j, k, "valideerimine on luku väliselt")
        self.assertLess(k, m, "valideeritakse pärast saatmist")
        # kontrolli ja saatmise VAHEL ei tohi olla await'i.
        # KOMMENTAARID VÄLJA: selgitus räägib await'ist just selleks,
        # et öelda, mida kood garanteerib ja mida mitte.
        vahe = "\n".join(r for r in keha[k:m].splitlines()
                         if not r.strip().startswith("#"))
        self.assertNotIn("await", vahe,
                         "kontrolli ja saatmise vahele mahub await")

    def test_kirjutust_ei_katkestata_poole_pealt(self):
        """L3: KORDUV tühistus ei tohi lukku vabastada enne, kui
        füüsiline kirjutamine on lõppenud."""
        i = WS.index("async def gsend(")
        keha = WS[i:i + 4200]
        self.assertIn("asyncio.shield(", keha)
        # tsükkel, mis talub ka teist tühistust
        self.assertIn("while not _s.done():", keha)
        # tsükli sees peab korduv CancelledError viima `continue`-ni,
        # mitte luku vabastamiseni
        i2 = keha.index("while not _s.done():")
        self.assertIn("continue", keha[i2:i2 + 260])
        self.assertIn("except asyncio.CancelledError:", keha[i2:i2 + 260])
        # ja erind loetakse välja
        self.assertIn("_s.exception()", keha)

    def test_L4_mikrofon_ei_oota_juhtsonumite_lukku(self):
        """L4: `grealtime` EI tohi võtta `gemini_send_lock`-i, muidu
        seiskunud omaalgatus/taaste blokeerib kasutaja hääle."""
        i = WS.index("async def grealtime(")
        keha = WS[i:i + 220]
        self.assertNotIn("gemini_send_lock", keha,
                         "mikrofon ootab endiselt juhtsõnumite lukku")
        self.assertIn("await session.send_realtime_input(**kw)", keha)
        # ja gsend endiselt VÕTAB luku
        j = WS.index("async def gsend(")
        self.assertIn("async with gemini_send_lock:", WS[j:j + 3200])

    def test_koik_valjuvad_paringud_kaivad_luku_kaudu(self):
        puu = ast.parse(WS)
        otse = []
        for s2 in ast.walk(puu):
            if isinstance(s2, ast.Attribute) and s2.attr in (
                    "send", "send_realtime_input"):
                if isinstance(s2.value, ast.Name) and s2.value.id == "session":
                    otse.append(s2.lineno)
        self.assertEqual(len(otse), 2,
                         f"session.send'i otsekasutus ridadel {otse}")
        self.assertIn("gemini_send_lock = asyncio.Lock()", WS)
        self.assertIn("async with gemini_send_lock:", WS)

    # ---- Vooru loendur: aegunud taaste ei saada ------------------
    def test_kasutaja_voor_loendur_kasvab_kone_peale(self):
        i = WS.index('_kasutaja_voor["n"] += 1')
        keha = WS[i:i + 600]
        self.assertIn("flow.on_user_speech(", keha)
        self.assertIn("_tyhista_ootel_taaste(", keha)

    def test_valideerija_kontrollib_koiki_nelja_tingimust(self):
        i = WS.index("def _voor_kehtib(")
        keha = WS[i:i + 1200]
        for k in ("conversation_flow.ENDED", 'fatal_state["reason"]',
                  "not running", '_kasutaja_voor["n"] != epoch',
                  "conversation_flow.USER_SPEAKING",
                  'just_interrupted["v"]'):
            self.assertIn(k, keha, k)

    def test_taaste_tuhistatakse_ka_katkestuse_peale(self):
        i = WS.index("flow.on_interrupted(")
        self.assertIn("_tyhista_ootel_taaste(", WS[i - 200:i])

    # ---- Taskide omand ja lõpetamine ----------------------------
    def test_L1_uks_sulgemisprotseduur_mis_OOTAB_ara(self):
        """L1: varem ainult cancel() kolmes kohas, ilma ootamist."""
        self.assertIn("_taustataskid = []", WS)
        self.assertIn("_taustataskid.append(task)", WS)
        self.assertIn("observer_task = _registreeri(", WS)
        self.assertIn("initiative_task = _registreeri(", WS)
        i = WS.index("async def _sulge_seanss(")
        keha = WS[i:i + 6000]
        self.assertIn("if _suletud[\"v\"]:", keha)      # idempotentne
        self.assertIn("mina = asyncio.current_task()", keha)
        self.assertIn("if t is mina or t.done():", keha)  # ei tühista ennast
        self.assertIn("if t not in _tyhistatud:", keha)   # ei tühista 2x
        self.assertIn("t.cancel()", keha)
        self.assertIn("await asyncio.wait(", keha)        # OOTAB ÄRA
        self.assertIn("SULGEMISE_FAAS1_S", keha)
        self.assertIn("SULGEMISE_FAAS2_S", keha)
        # ja EBAÕNNESTUMIST ei nimetata õnnestumiseks
        self.assertIn("SULGEMINE EBAÕNNESTUS", keha)
        self.assertIn('_sulgemine["ok"] = not jaanud', keha)
        self.assertIn("flow.on_conversation_end()", keha)
        self.assertIn("_t.exception()", keha)             # loeb erindid

    def test_L1_running_lipp_maha_enne_torketeavitust(self):
        """Teavitus sisaldab await'e – tiksuja ei tohi sel ajal saata."""
        i = WS.index("done, pending = await asyncio.wait(")
        j = WS.index("LÕPLIKU TÕRKE TEAVITUS", i)
        self.assertIn("running = False", WS[i:j],
                      "lipp jääb teavituse ajaks püsti")

    def test_L1_sulgemine_on_async_with_SEES(self):
        """Gemini seanss tohib sulguda alles pärast taskide lõppu."""
        i = WS.index("async with client.aio.live.connect(")
        j = WS.index("await _sulge_seanss(", i)
        k = WS.rindex("    finally:")
        self.assertLess(j, k,
                        "sulgemine jookseb pärast Gemini seansi sulgemist")
        # ja välimine finally on AINULT varuvariant
        keha = WS[k:k + 900]
        self.assertIn('_sulgeja["f"]', keha)
        self.assertNotIn("for _t in list(_taustataskid):", keha)

    def test_L3_tuhistamine_on_TAPSELT_kahes_kohas(self):
        """Kolm laialipillutatud tühistuskohta tekitasid topelttühistusi."""
        puu = ast.parse(WS)
        kohad = []
        for n in ast.walk(puu):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "cancel":
                kohad.append(n.lineno)
        read = WS.splitlines()
        nimed = [read[x - 1].strip() for x in kohad]
        self.assertEqual(
            len(kohad), 2,
            f"cancel() on {len(kohad)} kohas: {list(zip(kohad, nimed))}")

    def test_L3_ootel_taaste_tuhistus_margitakse(self):
        i = WS.index("def _tyhista_ootel_taaste(")
        keha = WS[i:i + 800]
        self.assertIn("_tyhistatud.add(t)", keha)
        self.assertIn("t.cancel()", keha)

    def test_malutask_ei_kuulu_sulgemisse(self):
        i = WS.index("consolidate_session_to_memory")
        keha = WS[i - 500:i + 400]
        self.assertIn("_PENDING_MEMORY_TASKS.add(mem_task)", keha)
        self.assertNotIn("_registreeri(", keha)
        # ja sulgemine jookseb ENNE mälutaski loomist
        self.assertLess(WS.rindex("await _sulgeja[\"f\"]"),
                        WS.index("consolidate_session_to_memory"))

    def test_L6_esimese_kasutajavooru_varav_tootmises(self):
        src = (KOOD / "conversation_flow.py").read_text(encoding="utf-8")
        i = src.index("def should_speak(")
        keha = src[i:i + 2200]
        self.assertIn("user_turn_seen", keha)
        j = keha.index("if not user_turn_seen:")
        k = keha.index("if self.budget <= 0:")
        self.assertLess(j, k, "värav ei ole esimene")
        self.assertIn("self.user_turn_seen = True", src)
        # viip teab, kas eelmine mõte on olemas
        self.assertIn("has_prior_thought", src)
        self.assertIn("flow.assistant_said_something", WS)

    def test_taaste_task_on_registreeritud_ja_hoitud(self):
        i = WS.index('if _otsus["recover"]:')
        keha = WS[i:i + 900]
        self.assertIn('_taastetask["t"] = _registreeri(', keha)

    def test_koik_seansi_taskid_on_registreeritud(self):
        """INVENTUUR: iga create_task seansi sees peab olema seansi
        omandis. Ainus lubatud erand on mälu konsolideerimine, mis
        PEAB seansi üle elama (tal on oma _PENDING_MEMORY_TASKS)."""
        puu = ast.parse(WS)
        fn = None
        for n in ast.walk(puu):
            if isinstance(n, ast.AsyncFunctionDef) and \
                    n.name == "websocket_live_maya":
                fn = n
        self.assertIsNotNone(fn)
        read = WS.splitlines()
        registreerimata = []
        for x in ast.walk(fn):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                    and x.func.attr in ("create_task", "ensure_future"):
                # vaata 2 rida ülespoole: kas _registreeri ümbritseb
                akna = "\n".join(read[max(0, x.lineno - 3):x.lineno])
                if "_registreeri(" in akna:
                    continue
                if "consolidate_session_to_memory" in "\n".join(
                        read[x.lineno - 1:x.lineno + 3]):
                    continue        # lubatud erand
                if "session.send(**kw)" in read[x.lineno - 1]:
                    continue        # gsend'i sisemine kirjutus, drainitud
                registreerimata.append((x.lineno, read[x.lineno - 1].strip()))
        self.assertEqual(registreerimata, [],
                         f"registreerimata taskid: {registreerimata}")

    def test_malutask_EI_ole_seansi_omandis(self):
        """Mälu konsolideerimist ei tohi teardown tühistada."""
        i = WS.index("consolidate_session_to_memory")
        keha = WS[i - 400:i + 400]
        self.assertIn("_PENDING_MEMORY_TASKS.add(mem_task)", keha)
        self.assertNotIn("_registreeri(", keha)

    def test_registreerija_koristab_lopetatud_taskid(self):
        i = WS.index("def _registreeri(")
        keha = WS[i:i + 500]
        self.assertIn("add_done_callback", keha)
        self.assertIn("_taustataskid.remove(t)", keha)

    # ---- Omaalgatus -------------------------------------------
    def test_broneerimine_enne_awaiti_ja_valideerimine(self):
        i = WS.index("_alg = flow.tick(")
        keha = WS[i:i + 2400]
        j = keha.index("flow.reserve_initiative(")
        k = keha.index("await gsend(")
        self.assertLess(j, k, "broneering tehakse pärast saatmist")
        self.assertIn("valideeri=lambda: _voor_kehtib(_ep)", keha)
        self.assertIn("flow.release_initiative()", keha)

    def test_user_speaking_allikas_ei_ole_ainult_just_interrupted(self):
        i = WS.index("_alg = flow.tick(")
        keha = WS[i - 600:i + 300]
        self.assertIn("last_user_speech", keha,
                      "user_speaking tuleb ainult just_interrupted'ist")

    def test_voog_saab_loomise_hetke(self):
        self.assertIn("active_persona, now=time.monotonic()", WS)

    # ---- Kaitstud seaded --------------------------------------
    def test_kaitstud_seaded_endiselt_puutumata(self):
        self.assertIn("gemini-2.5-flash-native-audio-preview-12-2025", WS)
        self.assertIn("'api_version': 'v1alpha'", WS)
        self.assertEqual(WS.count("HarmBlockThreshold.BLOCK_NONE"), 4)
        self.assertIn('mime_type="audio/pcm;rate=16000"', WS)
        self.assertIn("START_SENSITIVITY_HIGH", WS)
        self.assertIn("prefix_padding_ms=250", WS)
        self.assertIn("silence_duration_ms=800", WS)
        self.assertIn("END_SENSITIVITY_LOW", WS)
        for k in ("enable_affective_dialog", "proactivity", "temperature="):
            self.assertNotIn(k, WS, k)

    def test_moodul_on_endiselt_puhas(self):
        src = (KOOD / "conversation_flow.py").read_text(encoding="utf-8")
        for k in ("session", "websocket", "sqlite3", "asyncio", "await ",
                  "genai", "time.time", "time.monotonic"):
            self.assertNotIn(k, src, k)


if __name__ == "__main__":
    print("=" * 70)
    print("ASÜNKROONSE ELUTSÜKLI TESTID (jäljendatud seanss ja kell)")
    print("PÄRIS GEMINI LIVE TESTE SIIN EI OLE.")
    print("=" * 70)
    unittest.main(verbosity=2)

"""MAYA — keskne seadistus (üks tõeallikas).

MIKS SEE FAIL OLEMAS ON
-----------------------
Algses erainstallatsioonis olid teed, andmebaasid ja .env-i asukoht
kõvakodeeritud ühe konkreetse serveri ja kasutaja külge
(nt ``/home/<kasutaja>/voice-agent/reminders.db``). See tegi projekti
teisele inimesele paigaldamatuks.

Siin on kõik need väärtused koondatud ja loetakse keskkonnamuutujatest.
Ükski vaikeväärtus EI VIITA ühelegi konkreetsele masinale: vaikimisi
elab kõik projekti enda kaustas.

KASUTAMINE
----------
    from config import JUUR, DB_TEE, env

    conn = sqlite3.connect(DB_TEE)
    votme = env("GEMINI_API_KEY")

KÕIK SEADISTATAV ON DOKUMENTEERITUD failis ``.env.example``.
"""

from __future__ import annotations

import os
import pathlib
from typing import Optional

# =====================================================================
# PROJEKTI JUUR
# =====================================================================
# Vaikimisi: see kaust, kus see fail asub (st ``server/``) üks tase üles.
# Ümberkirjutamiseks: MAYA_HOME=/mingi/muu/tee
_SIIN = pathlib.Path(__file__).resolve().parent

JUUR = pathlib.Path(os.environ.get("MAYA_HOME", str(_SIIN))).resolve()

# Andmekaust: andmebaasid, allalaaditud failid, ajutised helifailid.
# Hoitakse juurest eraldi, et seda saaks lihtsalt varundada ja
# .gitignore'iga välja jätta.
ANDMED = pathlib.Path(
    os.environ.get("MAYA_DATA_DIR", str(JUUR / "data"))).resolve()
ANDMED.mkdir(parents=True, exist_ok=True)


# =====================================================================
# .env LAADIMINE
# =====================================================================
# Otsime .env-i kolmest kohast selles järjekorras. Ükski neist ei ole
# kohustuslik – keskkonnamuutujad võivad tulla ka otse süsteemist
# (nt systemd EnvironmentFile või Docker).
ENV_TEED = [
    pathlib.Path(p) for p in (
        os.environ.get("MAYA_ENV_FILE", ""),
        str(JUUR / ".env"),
        str(JUUR.parent / ".env"),
    ) if p
]


def laadi_env(teed=None) -> int:
    """Loe .env failist muutujad protsessi keskkonda.

    EI KIRJUTA ÜLE juba olemasolevaid keskkonnamuutujaid – nii saab
    süsteemne seadistus (systemd, Docker, CI) alati .env-i võita.
    Tagastab laaditud muutujate arvu.
    """
    n = 0
    for tee in (teed or ENV_TEED):
        try:
            if not tee.exists():
                continue
            for rida in tee.read_text(encoding="utf-8").splitlines():
                rida = rida.strip()
                if not rida or rida.startswith("#") or "=" not in rida:
                    continue
                if rida.startswith("export "):
                    rida = rida[len("export "):]
                k, _, v = rida.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
                    n += 1
        except Exception:
            # Vigane .env ei tohi rakendust maha võtta.
            continue
    return n


laadi_env()


def env(nimi: str, vaikimisi: Optional[str] = None) -> Optional[str]:
    """Loe keskkonnamuutuja. Tühi string loetakse puuduvaks."""
    v = os.environ.get(nimi)
    return v if v not in (None, "") else vaikimisi


def env_noutud(nimi: str) -> str:
    """Loe KOHUSTUSLIK keskkonnamuutuja või viska selge veateade.

    Veateade EI SISALDA väärtust – ainult muutuja nime.
    """
    v = env(nimi)
    if not v:
        raise RuntimeError(
            f"Keskkonnamuutuja {nimi} on seadistamata. "
            f"Vaata .env.example ja docs/SEADISTAMINE.md."
        )
    return v


# =====================================================================
# ANDMEBAASID
# =====================================================================
# ÜKS andmebaas kõige jaoks: meeldetuletused, ostunimekiri, päevik,
# vestlusarhiiv, mälufaktid ja FTS5 indeksid. Originaalpaigalduses oli
# kaustas ka `agent_memory.db`, aga ükski tootmismoodul seda ei kasuta
# (pärand vanemast Telegrami-botist), seega avalikus versioonis seda ei
# ole.
DB_TEE = str(pathlib.Path(
    env("MAYA_DB_PATH", str(ANDMED / "reminders.db"))))

# =====================================================================
# VÕRK
# =====================================================================
HOST = env("MAYA_HOST", "0.0.0.0")
PORT = int(env("MAYA_PORT", "8000"))

# Avalik baas-URL, mille kaudu Androidi rakendus serverini jõuab.
# Androidi emulaatoris on arvuti ``10.0.2.2``. Päris telefoni puhul
# pane siia oma serveri aadress (soovitatavalt privaatvõrgus,
# nt Tailscale/WireGuard – vt docs/SEADISTAMINE.md).
AVALIK_URL = env("MAYA_PUBLIC_URL", f"http://127.0.0.1:{PORT}")

# =====================================================================
# KASUTAJA
# =====================================================================
# Nimi, millega karakterid kasutajat kõnetavad. Karakteriviipades on
# kohahoidja {USER}, mis asendatakse selle väärtusega (või
# andmebaasis salvestatud nimega, kui kasutaja on selle muutnud).
KASUTAJA_NIMI = env("MAYA_USER_NAME", "Kasutaja")
AJAVOOND = env("MAYA_TIMEZONE", "Europe/Tallinn")

# =====================================================================
# VALIKULISED VÄLISED TEENUSED
# =====================================================================
# Ükski neist ei ole kõnefunktsiooni jaoks kohustuslik. Kui võti
# puudub, lülitub vastav funktsioon vaikselt välja.
GEMINI_API_KEY = env("GEMINI_API_KEY")          # KOHUSTUSLIK häälele
GROQ_API_KEY = env("GROQ_API_KEY")              # valikuline: tekstirada
TAVILY_API_KEY = env("TAVILY_API_KEY")          # valikuline: veebiotsing
GMAIL_USER = env("GMAIL_USER")                  # valikuline: e-post
GMAIL_APP_PASSWORD = env("GMAIL_APP_PASSWORD")
GMAIL_USER_2 = env("GMAIL_USER_2")
GMAIL_APP_PASSWORD_2 = env("GMAIL_APP_PASSWORD_2")

# Kontakt-e-post, mille muusikaandmebaaside API-d nõuavad
# User-Agent päises. Pane siia OMA aadress või jäta vaikeväärtus.
KONTAKT_EMAIL = env("MAYA_CONTACT_EMAIL", "maya@example.org")

# =====================================================================
# VALIKULINE KOHALIK KÕNESÜNTEES (Piper)
# =====================================================================
# Kasutatakse ainult varuteel, kui Gemini Live ei ole kättesaadav.
# Kui need teed ei eksisteeri, jäetakse varutee lihtsalt kasutamata.
PIPER_PYTHON = env("MAYA_PIPER_PYTHON", "")
PIPER_HELPER = env("MAYA_PIPER_HELPER", "")


def kokkuvote() -> str:
    """Inimloetav kokkuvõte seadistusest. EI TRÜKI ühtegi saladust."""
    def on(v):
        return "seatud" if v else "PUUDUB"
    return "\n".join([
        f"  juur            : {JUUR}",
        f"  andmed          : {ANDMED}",
        f"  reminders.db    : {DB_TEE}",
        f"  host:port       : {HOST}:{PORT}",
        f"  avalik URL      : {AVALIK_URL}",
        f"  kasutaja nimi   : {KASUTAJA_NIMI}",
        f"  ajavöönd        : {AJAVOOND}",
        f"  GEMINI_API_KEY  : {on(GEMINI_API_KEY)}",
        f"  GROQ_API_KEY    : {on(GROQ_API_KEY)}",
        f"  TAVILY_API_KEY  : {on(TAVILY_API_KEY)}",
        f"  GMAIL_USER      : {on(GMAIL_USER)}",
    ])


if __name__ == "__main__":
    print("MAYA seadistus:")
    print(kokkuvote())

#!/usr/bin/env bash
# =====================================================================
# MAYA — JUHENDATUD PAIGALDUS
# =====================================================================
# See skript paigaldab MAYA backendi SINU arvutisse. Ta küsib iga
# olulise sammu kohta nõusolekut ja selgitab, mida teeb.
#
#   ./paigalda.sh              # juhendatud paigaldus
#   ./paigalda.sh --kontroll   # ainult kontrolli eeldusi, ära muuda midagi
#
# MIDA SEE SKRIPT **EI** TEE:
#   * ei muuda süsteemi seadistust väljaspool seda kausta;
#   * ei ava tulemüüri porte ega muuda ruuteri seadeid;
#   * ei ava MAYA-t avalikku internetti;
#   * ei võta ühendust ühegi võõra serveriga (ainult PyPI, kust tulevad
#     Pythoni teegid);
#   * ei kirjuta olemasolevat paigaldust üle ilma eraldi küsimata;
#   * ei pane sinu API võtit Giti ega logidesse.
#
# Paigaldus toimub TERVIKUNA selles kaustas. Eemaldamiseks kustuta kaust.
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
JUUR="$(pwd)"

# --- värvid ja abifunktsioonid ---------------------------------------
if [ -t 1 ]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
    R=""; G=""; Y=""; B=""; N=""
fi
ok()      { printf '%s✓%s %s\n' "$G" "$N" "$1"; }
viga()    { printf '%s✗%s %s\n' "$R" "$N" "$1"; }
hoiatus() { printf '%s!%s %s\n' "$Y" "$N" "$1"; }
samm()    { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
info()    { printf '   %s\n' "$1"; }

kysi_jah() {
    # kysi_jah "küsimus" [vaikimisi j|e]
    local v="${2:-j}" vastus
    local vihje="[J/e]"; [ "$v" = "e" ] && vihje="[j/E]"
    while true; do
        printf '   %s %s ' "$1" "$vihje"
        read -r vastus || vastus=""
        vastus="${vastus:-$v}"
        case "$vastus" in
            [jJyY]*) return 0 ;;
            [eEnN]*) return 1 ;;
            *) info "Vasta j (jah) või e (ei)." ;;
        esac
    done
}

katkesta() {
    echo
    viga "Paigaldus katkestatud: $1"
    echo
    info "Midagi ei ole pooleli jäänud – võid skripti uuesti käivitada."
    exit 1
}

echo "====================================================================="
echo " MAYA — juhendatud paigaldus"
echo "====================================================================="
echo
info "MAYA on eestikeelne häälassistent, mis töötab SINU arvutis."
info "Hääle annab Google Gemini Live API SINU enda API võtmega."
info "Keskset MAYA teenust ei ole – sina oled ainus operaator."
echo
info "Paigalduskaust: $JUUR"

AINULT_KONTROLL=0
[ "${1:-}" = "--kontroll" ] && AINULT_KONTROLL=1

# =====================================================================
# 1. EELDUSED
# =====================================================================
samm "1/7  Kontrollin eeldusi"

PUUDU=0

# -- Python ----------------------------------------------------------
PY=""
for kandidaat in python3.13 python3.12 python3.11 python3; do
    if command -v "$kandidaat" >/dev/null 2>&1; then
        v=$("$kandidaat" -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")
        maj=${v%%.*}; min=${v##*.}
        if [ "$maj" -eq 3 ] && [ "$min" -ge 11 ] 2>/dev/null; then
            PY="$kandidaat"; PYV="$v"; break
        fi
    fi
done
if [ -n "$PY" ]; then
    ok "Python $PYV ($PY)"
else
    viga "Python 3.11 või uuem puudub"
    info "Paigalda: https://www.python.org/downloads/"
    info "  macOS  : brew install python@3.13"
    info "  Debian/Ubuntu : sudo apt install python3 python3-venv python3-pip"
    info "  Fedora : sudo dnf install python3 python3-pip"
    PUUDU=1
fi

# -- venv moodul ------------------------------------------------------
if [ -n "$PY" ]; then
    if "$PY" -c "import venv" >/dev/null 2>&1; then
        ok "Pythoni venv moodul olemas"
    else
        viga "Pythoni venv moodul puudub"
        info "Debian/Ubuntu: sudo apt install python3-venv"
        PUUDU=1
    fi
fi

# -- operatsioonisüsteem ---------------------------------------------
case "$(uname -s)" in
    Darwin) ok "Operatsioonisüsteem: macOS (toetatud)" ;;
    Linux)  ok "Operatsioonisüsteem: Linux (toetatud)" ;;
    *)      hoiatus "Operatsioonisüsteem: $(uname -s) — EI OLE kontrollitud."
            info "Windowsis kasuta WSL2 (Ubuntu). Vt docs/PAIGALDAMINE.md." ;;
esac

# -- kettaruum --------------------------------------------------------
if command -v df >/dev/null 2>&1; then
    VABA=$(df -m . 2>/dev/null | awk 'NR==2{print $4}')
    if [ -n "${VABA:-}" ] && [ "$VABA" -lt 500 ] 2>/dev/null; then
        hoiatus "Vaba kettaruumi ainult ${VABA} MB (soovitatav vähemalt 500 MB)"
    else
        ok "Kettaruumi jagub (${VABA:-?} MB vaba)"
    fi
fi

# -- internet ---------------------------------------------------------
if command -v curl >/dev/null 2>&1; then
    if curl -sS -o /dev/null --max-time 10 https://pypi.org/simple/ 2>/dev/null; then
        ok "Internetiühendus PyPI-ni töötab (teegid saab alla laadida)"
    else
        hoiatus "PyPI-ni ei saanud ühendust – teekide paigaldus võib nurjuda"
    fi
else
    hoiatus "curl puudub – ei saanud internetiühendust kontrollida"
fi

# -- projekti terviklikkus -------------------------------------------
for f in server/web_maya.py server/requirements.txt server/init_db.py .env.example; do
    if [ -f "$f" ]; then ok "Projektifail olemas: $f"
    else viga "Projektifail PUUDUB: $f"; PUUDU=1; fi
done

if [ "$PUUDU" = "1" ]; then
    echo
    katkesta "mõni eeldus on puudu (vt ✗ märgitud read)"
fi

if [ "$AINULT_KONTROLL" = "1" ]; then
    echo
    ok "Eeldused on korras. Paigalduse alustamiseks: ./paigalda.sh"
    exit 0
fi

# =====================================================================
# 2. OLEMASOLEVA PAIGALDUSE KONTROLL
# =====================================================================
samm "2/7  Kontrollin, kas paigaldus on juba olemas"

# Andmebaas elab vaikimisi kaustas server/data/ (config.py asub server/
# kaustas ja ANDMED arvutatakse selle suhtes). MAYA_DATA_DIR saab selle
# ümber suunata, seega kontrollime mõlemat võimalikku kohta.
ANDMEBAAS=""
for kandidaat in server/data/reminders.db data/reminders.db; do
    [ -f "$kandidaat" ] && ANDMEBAAS="$kandidaat" && break
done

OLEMAS=0
[ -d .venv ] && OLEMAS=1
[ -f .env ] && OLEMAS=1
[ -n "$ANDMEBAAS" ] && OLEMAS=1

if [ "$OLEMAS" = "1" ]; then
    hoiatus "Selles kaustas on juba MAYA paigaldus:"
    [ -d .venv ]        && info "  .venv            – Pythoni keskkond"
    [ -f .env ]         && info "  .env             – SINU seadistus ja API võti"
    [ -n "$ANDMEBAAS" ] && info "  $ANDMEBAAS – SINU andmebaas (mälu, meeldetuletused)"
    echo
    info "Skript EI KIRJUTA neid üle. Ta täiendab ainult puuduvat."
    info "Kui tahad nullist alustada, kustuta need käsitsi ja käivita uuesti."
    echo
    kysi_jah "Jätkan olemasolevat paigaldust täiendades?" || katkesta "kasutaja soovil"
else
    ok "Varasemat paigaldust ei ole – teen puhta paigalduse"
fi

# =====================================================================
# 3. PYTHONI KESKKOND
# =====================================================================
samm "3/7  Pythoni keskkond (.venv)"
info "Virtuaalkeskkond hoiab MAYA teegid eraldi, et nad ei segaks"
info "sinu süsteemi muid Pythoni programme."

if [ -d .venv ] && [ -x .venv/bin/python ]; then
    ok ".venv on juba olemas"
else
    info "Loon .venv kausta…"
    "$PY" -m venv .venv || katkesta "virtuaalkeskkonna loomine nurjus"
    ok ".venv loodud"
fi
VENV_PY="$JUUR/.venv/bin/python"
[ -x "$VENV_PY" ] || katkesta ".venv/bin/python puudub"

# =====================================================================
# 4. TEEGID
# =====================================================================
samm "4/7  Pythoni teegid"
info "Paigaldan failis server/requirements.txt loetletud teegid."
info "See võtab tavaliselt 1–3 minutit."

if kysi_jah "Paigaldan teegid nüüd?"; then
    "$VENV_PY" -m pip install --quiet --upgrade pip || hoiatus "pip'i uuendamine nurjus (ei ole kriitiline)"
    if "$VENV_PY" -m pip install --quiet -r server/requirements.txt; then
        ok "Teegid paigaldatud"
    else
        viga "Teekide paigaldus nurjus"
        info "Proovi käsitsi, et näha täielikku viga:"
        info "  .venv/bin/pip install -r server/requirements.txt"
        katkesta "teekide paigaldus nurjus"
    fi
else
    hoiatus "Teegid jäid paigaldamata – server ei käivitu enne seda"
fi

# =====================================================================
# 5. SEADISTUS JA GEMINI API VÕTI
# =====================================================================
samm "5/7  Seadistus ja Gemini API võti"

if [ ! -f .env ]; then
    cp .env.example .env || katkesta ".env loomine nurjus"
    chmod 600 .env 2>/dev/null || true
    ok ".env loodud .env.example põhjal (õigused 600 – loeb ainult sina)"
else
    ok ".env on juba olemas"
    chmod 600 .env 2>/dev/null || true
fi

VOTI_OLEMAS=0
if grep -qE '^GEMINI_API_KEY=.+' .env && ! grep -qE '^GEMINI_API_KEY=pane_siia' .env; then
    VOTI_OLEMAS=1
    ok "GEMINI_API_KEY on .env failis juba seatud"
fi

if [ "$VOTI_OLEMAS" = "0" ]; then
    echo
    info "MAYA hääl tuleb Google Gemini Live API-st. Selleks on vaja SINU"
    info "enda API võtit. Võti jääb ainult sinu arvutisse faili .env,"
    info "mis on .gitignore'is – Giti see ei satu."
    echo
    info "Võtme saad tasuta siit (vajab Google'i kontot):"
    info "  https://aistudio.google.com/apikey"
    echo
    info "NB: Gemini Live API KASUTAMINE ON TASULINE ja Google arveldab"
    info "    selle SINULE, mitte MAYA projektile. Hinnad ja tingimused"
    info "    määrab Google: https://aistudio.google.com/docs/pricing"
    echo
    if kysi_jah "Kas sisestan API võtme nüüd?"; then
        printf '   Kleebi võti (seda ei kuvata ekraanil): '
        # -s: ei kuva sisestatut. Võti ei jõua ka ajalukku ega logidesse.
        read -rs VOTI || VOTI=""
        echo
        # Eemalda tühikud/reavahetused bashi enda vahenditega – nii ei
        # lähe võti läbi ühestki välisest käsust (ps ei näe teda kunagi).
        VOTI="${VOTI//[$' \t\r\n']/}"
        if [ -z "$VOTI" ]; then
            hoiatus "Võtit ei sisestatud – saad selle hiljem .env faili lisada"
        else
            # Kontrolli kuju, aga ÄRA trüki väärtust.
            # Kuju kontroll bashi enda regexiga: võti ei lähe läbi
            # ühestki välisest käsust ega jõua protsessiloendisse.
            if [[ ! "$VOTI" =~ ^AIza[0-9A-Za-z_-]{20,}$ ]]; then
                hoiatus "Võti ei näe välja nagu Google'i API võti (algab tavaliselt 'AIza')."
                kysi_jah "Salvestan siiski?" "e" || VOTI=""
            fi
        fi
        if [ -n "$VOTI" ]; then
            # Kirjutame Pythoniga, et erimärgid ei lagundaks faili.
            VOTI="$VOTI" "$VENV_PY" - <<'PY'
import os, pathlib, re
voti = os.environ["VOTI"]
p = pathlib.Path(".env")
read = p.read_text(encoding="utf-8").splitlines()
uus, leitud = [], False
for r in read:
    if re.match(r"^\s*GEMINI_API_KEY\s*=", r):
        uus.append(f"GEMINI_API_KEY={voti}"); leitud = True
    else:
        uus.append(r)
if not leitud:
    uus.append(f"GEMINI_API_KEY={voti}")
p.write_text("\n".join(uus) + "\n", encoding="utf-8")
PY
            unset VOTI
            chmod 600 .env 2>/dev/null || true
            ok "Võti salvestatud faili .env (ekraanile ega logidesse ei jõudnud)"
        fi
    else
        hoiatus "Võti jäi sisestamata. Lisa see hiljem faili .env ritta"
        info "  GEMINI_API_KEY=sinu_voti"
    fi
fi

# =====================================================================
# 6. LIGIPÄÄSUVIIS (MAYA_HOST)
# =====================================================================
samm "6/7  Kuidas telefon serverini jõuab?"
info "Server peab kuulama õigel võrguliidesel. Vali endale sobiv:"
echo
info "  1) AINULT SEE ARVUTI (127.0.0.1) – kõige turvalisem."
info "     Telefon EI PÄÄSE ligi. Sobib proovimiseks brauseris."
info "  2) KODUNE VÕRK (0.0.0.0) – telefon samas WiFis pääseb ligi."
info "     Soovitatud algus. Liiklus on krüpteerimata HTTP."
info "  3) PRIVAATVÕRK, nt Tailscale (0.0.0.0) – telefon pääseb ligi"
info "     ka väljaspool kodu, ilma ühtegi porti avamata. Soovitatud."
echo
info "  Avalik internet (domeen + HTTPS) seadistatakse eraldi ja see"
info "  skript seda EI TEE – vt docs/PAIGALDAMINE.md peatükk „Võrk“."
echo
VALIK=""
while [ -z "$VALIK" ]; do
    printf '   Vali 1, 2 või 3 [2]: '
    read -r VALIK || VALIK=""
    VALIK="${VALIK:-2}"
    case "$VALIK" in
        1) UUS_HOST="127.0.0.1" ;;
        2|3) UUS_HOST="0.0.0.0" ;;
        *) info "Vasta 1, 2 või 3."; VALIK="" ;;
    esac
done

MAYA_HOST="$UUS_HOST" "$VENV_PY" - <<'PY'
import os, pathlib, re
host = os.environ["MAYA_HOST"]
p = pathlib.Path(".env")
read = p.read_text(encoding="utf-8").splitlines()
uus, leitud = [], False
for r in read:
    if re.match(r"^\s*MAYA_HOST\s*=", r):
        uus.append(f"MAYA_HOST={host}"); leitud = True
    else:
        uus.append(r)
if not leitud:
    uus.append(f"MAYA_HOST={host}")
p.write_text("\n".join(uus) + "\n", encoding="utf-8")
print(f"   MAYA_HOST={host}")
PY
ok "Kuulamisaadress salvestatud"
if [ "$VALIK" = "3" ]; then
    echo
    info "Privaatvõrgu jaoks paigalda Tailscale (tasuta isiklikuks kasutuseks):"
    info "  https://tailscale.com/kb/"
    info "Paigalda see NII arvutisse KUI telefoni ja logi mõlemas sama"
    info "kontoga sisse. Seejärel kasuta telefonis Tailscale'i aadressi."
fi

# =====================================================================
# 7. ANDMEBAAS
# =====================================================================
samm "7/7  Andmebaas"
info "Loon tühja andmebaasi (meeldetuletused, mälu, kasutajad)."
info "Isiklikke andmeid kaasas ei ole – kõik algab tühjalt."

if "$VENV_PY" server/init_db.py --check >/dev/null 2>&1; then
    ok "Andmebaas on juba olemas (olemasolevat ei puudutata)"
else
    if "$VENV_PY" server/init_db.py >/dev/null 2>&1; then
        ok "Andmebaas loodud"
    else
        viga "Andmebaasi loomine nurjus"
        info "Proovi käsitsi, et näha viga:  .venv/bin/python server/init_db.py"
    fi
fi

# =====================================================================
# VALMIS
# =====================================================================
echo
echo "====================================================================="
ok "PAIGALDUS ON VALMIS"
echo "====================================================================="
echo
info "Kontrolli, kas kõik on korras:"
echo "     ./tervisekontroll.sh"
echo
info "Käivita MAYA:"
echo "     ./kaivita.sh"
echo
info "Peata MAYA:"
echo "     ./peata.sh          (või Ctrl+C selles aknas)"
echo
info "Järgmised sammud telefonis:"
info "  1. Paigalda Androidi rakendus (vt docs/ANDROID.md)"
info "  2. Rakendus küsib esimesel käivitusel serveri aadressi –"
info "     selle ütleb välja käsk ./kaivita.sh --ip"
info "  3. Loo rakenduses konto („Loo uus konto“). ESIMENE konto"
info "     saab admin-õigused."
echo
info "Täielik juhend: docs/PAIGALDAMINE.md"
echo

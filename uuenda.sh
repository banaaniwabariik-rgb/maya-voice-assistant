#!/usr/bin/env bash
# =====================================================================
# MAYA — UUENDAMINE
# =====================================================================
# Tõmbab uue versiooni, uuendab teegid ja viib andmebaasi skeemi uuele
# versioonile. SINU andmeid (.env, data/) ei puudutata.
#
#   ./uuenda.sh
#
# MIDA SEE EI TEE:
#   * ei kustuta ega kirjuta üle sinu .env faili;
#   * ei kustuta ega tühjenda andmebaasi;
#   * ei muuda midagi, kui sul on kohalikke salvestamata muudatusi;
#   * ei võta ühendust ühegi võõra serveriga peale selle, kust sa
#     projekti kloonisid, ja PyPI.
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
    R=""; G=""; Y=""; B=""; N=""
fi
ok()      { printf '%s✓%s %s\n' "$G" "$N" "$1"; }
viga()    { printf '%s✗%s %s\n' "$R" "$N" "$1"; }
hoiatus() { printf '%s!%s %s\n' "$Y" "$N" "$1"; }
info()    { printf '   %s\n' "$1"; }
samm()    { printf '\n%s%s%s\n' "$B" "$1" "$N"; }

echo "====================================================================="
echo " MAYA uuendamine"
echo "====================================================================="

# --- 1. Kas server jookseb? -----------------------------------------
samm "1/5  Kontrollin, kas server jookseb"
JOOKSEB=0
if ps -eo command= 2>/dev/null | grep -F "$(pwd)" | grep -qF "web_maya.py"; then
    JOOKSEB=1
    hoiatus "MAYA jookseb praegu"
    info "Uuendamise ajal peaks server olema peatatud."
    printf '   Peatan serveri nüüd? [J/e] '
    read -r v || v="j"
    case "${v:-j}" in
        [jJyY]*) ./peata.sh || hoiatus "Peatamine ei õnnestunud täielikult" ;;
        *) viga "Uuendamine katkestatud – peata server käsuga ./peata.sh"; exit 1 ;;
    esac
else
    ok "Server ei jookse"
fi

# --- 2. Kohalikud muudatused ----------------------------------------
samm "2/5  Kontrollin kohalikke muudatusi"
if [ ! -d .git ]; then
    hoiatus "See ei ole Git-hoidla (projekt laaditi ilmselt ZIP-ina)"
    info "Automaatne uuendus ei ole võimalik. Laadi uus versioon alla ja"
    info "kopeeri oma .env ning data/ kaust uude kausta."
    exit 1
fi
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    viga "Sul on salvestamata kohalikke muudatusi:"
    git status --short | sed 's/^/     /'
    echo
    info "Uuendus võiks need üle kirjutada, seega peatun siin."
    info "Valikud:"
    info "  git stash            – pane muudatused kõrvale"
    info "  git checkout -- .    – VISKA muudatused ära (ei saa tagasi)"
    exit 1
fi
ok "Kohalikke muudatusi ei ole"

# --- 3. Tõmba uus versioon ------------------------------------------
samm "3/5  Tõmban uue versiooni"
if ! git remote | grep -q .; then
    hoiatus "Ükski Git-kaugharu ei ole seadistatud – ei tea, kust tõmmata"
    info "Vahele jäetud. Lisa kaughoidla või laadi uus versioon käsitsi."
else
    VANA=$(git rev-parse --short HEAD)
    if git pull --ff-only; then
        UUS=$(git rev-parse --short HEAD)
        if [ "$VANA" = "$UUS" ]; then
            ok "Juba uusim versioon ($UUS)"
        else
            ok "Uuendatud: $VANA -> $UUS"
        fi
    else
        viga "git pull nurjus (võib-olla on ajalugu lahknenud)"
        info "Vaata käsitsi:  git status  ja  git log --oneline -5"
        exit 1
    fi
fi

# --- 4. Teegid -------------------------------------------------------
samm "4/5  Uuendan Pythoni teegid"
if [ -x .venv/bin/python ]; then
    if .venv/bin/python -m pip install --quiet -r server/requirements.txt; then
        ok "Teegid on uuenduskuupäeval"
    else
        viga "Teekide uuendamine nurjus"
        info "Proovi:  .venv/bin/pip install -r server/requirements.txt"
    fi
else
    hoiatus ".venv puudub – jooksuta ./paigalda.sh"
fi

# --- 5. Andmebaasi skeem --------------------------------------------
samm "5/5  Uuendan andmebaasi skeemi"
info "See lisab uued veerud/tabelid. Olemasolevaid andmeid ei kustutata."
if [ -x .venv/bin/python ]; then
    if .venv/bin/python server/init_db.py >/dev/null 2>&1; then
        ok "Andmebaasi skeem on ajakohane"
    else
        viga "Skeemi uuendamine nurjus"
        info "Proovi:  .venv/bin/python server/init_db.py"
    fi
fi

echo
echo "====================================================================="
ok "UUENDAMINE VALMIS"
echo "====================================================================="
echo
info "Kontrolli:  ./tervisekontroll.sh"
[ "$JOOKSEB" = "1" ] && info "Käivita uuesti:  ./kaivita.sh"
echo
info "NB: kui Androidi rakenduses midagi muutus, ehita APK uuesti —"
info "    vt docs/ANDROID.md. Serveri uuendus üksi APK-d ei muuda."
echo

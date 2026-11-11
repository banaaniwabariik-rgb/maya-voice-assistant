#!/usr/bin/env bash
# =====================================================================
# MAYA — KOHALIKU TESTIMISE KÄIVITAJA
# =====================================================================
# Käivitab backendi nii, et telefonid samas WiFis saavad ühenduda.
#
#   ./kaivita.sh              # käivita
#   ./kaivita.sh --ip         # näita ainult aadressi, mida APK-sse panna
#   ./kaivita.sh --kontroll   # kontrolli eeldusi ja välju
#
# SEE SKRIPT EI SISALDA ÜHTEGI VÕTIT. Võtmed loetakse .env failist,
# mis on .gitignore'is.
set -uo pipefail
cd "$(dirname "$0")"

roheline() { printf '\033[32m%s\033[0m\n' "$1"; }
kollane()  { printf '\033[33m%s\033[0m\n' "$1"; }
punane()   { printf '\033[31m%s\033[0m\n' "$1"; }

# --- Leia LAN IP -----------------------------------------------------
leia_ip() {
    if [ "$(uname)" = "Darwin" ]; then
        local dev
        dev=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
        [ -n "${dev:-}" ] && ipconfig getifaddr "$dev" 2>/dev/null && return
        for d in en0 en1 en2; do
            ipconfig getifaddr "$d" 2>/dev/null && return
        done
    else
        hostname -I 2>/dev/null | awk '{print $1}' && return
    fi
    echo ""
}

leia_tailscale() {
    command -v tailscale >/dev/null 2>&1 || return
    tailscale ip -4 2>/dev/null | head -1
}

IP="$(leia_ip)"
TS="$(leia_tailscale)"

if [ "${1:-}" = "--ip" ]; then
    [ -n "$IP" ] && echo "LAN:       http://$IP:${MAYA_PORT:-8000}"
    [ -n "$TS" ] && echo "Tailscale: http://$TS:${MAYA_PORT:-8000}"
    exit 0
fi

echo "====================================================="
echo " MAYA kohalik testiserver"
echo "====================================================="

# --- Eeldused --------------------------------------------------------
PUUDU=0

if [ ! -d .venv ]; then
    punane "✗ .venv puudub"
    echo "    python3 -m venv .venv && source .venv/bin/activate"
    echo "    pip install -r server/requirements.txt"
    PUUDU=1
else
    roheline "✓ .venv olemas"
fi

if [ ! -f .env ]; then
    punane "✗ .env puudub"
    echo "    cp .env.example .env    ja pane sisse GEMINI_API_KEY"
    PUUDU=1
else
    if grep -qE '^GEMINI_API_KEY=.+' .env && \
       ! grep -qE '^GEMINI_API_KEY=pane_siia' .env; then
        roheline "✓ .env olemas, GEMINI_API_KEY seatud"
    else
        punane "✗ .env-is puudub GEMINI_API_KEY (või on veel kohahoidja)"
        echo "    Hangi: https://aistudio.google.com/apikey"
        PUUDU=1
    fi
fi

if [ -z "$IP" ]; then
    kollane "⚠ LAN IP-d ei leitud – kas oled võrgus?"
else
    roheline "✓ LAN IP: $IP"
fi
[ -n "$TS" ] && roheline "✓ Tailscale IP: $TS"

[ "$PUUDU" = "1" ] && { echo; punane "Paranda ülaltoodu ja proovi uuesti."; exit 1; }

# --- Andmebaas -------------------------------------------------------
if ! ./.venv/bin/python server/init_db.py --check >/dev/null 2>&1; then
    kollane "→ Andmebaas puudub, loon…"
    ./.venv/bin/python server/init_db.py || exit 1
else
    roheline "✓ Andmebaas olemas"
fi

KONTOD=$(./.venv/bin/python - <<'PY' 2>/dev/null
import sys; sys.path.insert(0, "server")
import auth
try:
    auth.ensure_schema(); print(auth.kasutajaid_kokku())
except Exception: print("?")
PY
)
if [ "$KONTOD" = "0" ]; then
    kollane "⚠ Kontosid ei ole. Esimene registreeruja saab admin-õigused."
    echo "    Loo konto telefonis sisselogimisekraanil („Loo uus konto")"
    echo "    või käsurealt pärast serveri käivitumist:"
    echo
    echo "    curl -X POST http://127.0.0.1:${MAYA_PORT:-8000}/api/auth/register \\"
    echo "         -H 'Content-Type: application/json' \\"
    echo "         -d '{\"username\":\"sinu_nimi\",\"password\":\"vahemalt_10_margi_pikk_parool\"}'"
else
    roheline "✓ Kontosid: $KONTOD"
fi

[ "${1:-}" = "--kontroll" ] && { echo; roheline "Eeldused korras."; exit 0; }

# --- Tulemüür (macOS) ------------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
    TM=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null || echo "")
    case "$TM" in
        *enabled*)
            kollane "⚠ macOS tulemüür on SEES."
            echo "    Kui telefon ei saa ühendust, luba Pythonile sissetulev"
            echo "    ühendus: Süsteemi sätted → Võrk → Tulemüür → Valikud"
            echo "    → lisa $(pwd)/.venv/bin/python3"
            echo "    Esimesel käivitusel küsib macOS seda ka ise."
            ;;
        *) roheline "✓ macOS tulemüür ei blokeeri" ;;
    esac
fi

# --- Käivita ---------------------------------------------------------
echo
echo "====================================================="
echo " APK AADRESS (pane see gradle.properties-i või -P lipuga):"
[ -n "$IP" ] && echo "   mayaBaseUrl=http://$IP:${MAYA_PORT:-8000}"
[ -n "$TS" ] && echo "   mayaBaseUrl=http://$TS:${MAYA_PORT:-8000}   (Tailscale, töötab ka väljaspool WiFit)"
echo "====================================================="
echo
roheline "Käivitan serveri (Ctrl+C lõpetab)…"
echo

# MAYA_HOST=0.0.0.0 on vajalik, et telefon ligi pääseks. Vaikeväärtus
# config.py-s on juba 0.0.0.0, aga paneme selle siin selgelt välja.
export MAYA_HOST="${MAYA_HOST:-0.0.0.0}"
cd server
exec ../.venv/bin/python web_maya.py

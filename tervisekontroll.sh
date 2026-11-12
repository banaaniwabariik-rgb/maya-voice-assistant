#!/usr/bin/env bash
# =====================================================================
# MAYA — TERVISEKONTROLL
# =====================================================================
# Kontrollib, kas MAYA on korrektselt paigaldatud ja kas server vastab.
# EI MUUDA MIDAGI – ainult vaatab ja ütleb välja.
#
#   ./tervisekontroll.sh          # kontrolli kõike
#   ./tervisekontroll.sh --vaikne # ainult kokkuvõte (skriptide jaoks)
#
# Väljumiskood: 0 = kõik korras, 1 = probleeme (sobib automaatikaks).
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; N=$'\033[0m'
else
    R=""; G=""; Y=""; B=""; N=""
fi
VAIKNE=0
[ "${1:-}" = "--vaikne" ] && VAIKNE=1

VIGU=0; HOIATUSI=0
ok()      { [ "$VAIKNE" = "0" ] && printf '%s✓%s %s\n' "$G" "$N" "$1"; return 0; }
viga()    { printf '%s✗%s %s\n' "$R" "$N" "$1"; VIGU=$((VIGU+1)); }
hoiatus() { printf '%s!%s %s\n' "$Y" "$N" "$1"; HOIATUSI=$((HOIATUSI+1)); }
info()    { [ "$VAIKNE" = "0" ] && printf '   %s\n' "$1"; return 0; }
pealkiri(){ [ "$VAIKNE" = "0" ] && printf '\n%s%s%s\n' "$B" "$1" "$N"; return 0; }

[ "$VAIKNE" = "0" ] && {
    echo "====================================================================="
    echo " MAYA tervisekontroll"
    echo "====================================================================="
}

# --- .env lugemine (ainult vajalikud väljad, väärtusi ei trüki) ------
loe_env() {
    # loe_env MUUTUJA -> väärtus või tühi
    [ -f .env ] || return 0
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env | tail -1
}

# =====================================================================
pealkiri "1. Paigaldus"
# =====================================================================
if [ -x .venv/bin/python ]; then
    PYV=$(.venv/bin/python -c 'import sys; print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null)
    ok "Pythoni keskkond olemas (Python $PYV)"
else
    viga ".venv puudub – jooksuta ./paigalda.sh"
fi

if [ -x .venv/bin/python ]; then
    PUUDUVAD=$(.venv/bin/python - <<'PY' 2>/dev/null
import importlib.util
# KOHUSTUSLIKUD teegid: ilma nendeta server ei käivitu.
vajalikud = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "google.genai": "google-genai",
    "websockets": "websockets", "requests": "requests",
    "multipart": "python-multipart", "trafilatura": "trafilatura",
    "youtube_transcript_api": "youtube-transcript-api", "groq": "groq",
}
puudu = [p for m, p in vajalikud.items() if importlib.util.find_spec(m) is None]
print(" ".join(puudu))
PY
)
    if [ -z "${PUUDUVAD// }" ]; then
        ok "Kõik kohustuslikud teegid on paigaldatud"
    else
        viga "Teegid puuduvad:$PUUDUVAD"
        info "Paranda:  .venv/bin/pip install -r server/requirements.txt"
    fi
fi

# =====================================================================
pealkiri "2. Seadistus"
# =====================================================================
if [ -f .env ]; then
    ok ".env on olemas"
    OIGUSED=$(stat -f "%OLp" .env 2>/dev/null || stat -c "%a" .env 2>/dev/null || echo "?")
    if [ "$OIGUSED" = "600" ]; then
        ok ".env õigused on 600 (loeb ainult sina)"
    else
        hoiatus ".env õigused on $OIGUSED – soovitatav 600"
        info "Paranda:  chmod 600 .env"
    fi
else
    viga ".env puudub – jooksuta ./paigalda.sh või: cp .env.example .env"
fi

VOTI=$(loe_env GEMINI_API_KEY)
if [ -z "$VOTI" ] || [ "$VOTI" = "pane_siia_oma_gemini_voti" ]; then
    viga "GEMINI_API_KEY ei ole seatud – hääl EI TÖÖTA"
    info "Hangi võti: https://aistudio.google.com/apikey"
    info "Lisa see faili .env ritta GEMINI_API_KEY="
else
    # Väärtust ei trüki kunagi – ainult kuju ja pikkus.
    # Kuju kontroll bashi enda regexiga – võti ei lähe välisesse käsku.
    if [[ "$VOTI" =~ ^AIza[0-9A-Za-z_-]{20,}$ ]]; then
        ok "GEMINI_API_KEY on seatud (kuju sobib, pikkus ${#VOTI})"
    else
        hoiatus "GEMINI_API_KEY on seatud, aga kuju on ebatavaline (pikkus ${#VOTI})"
        info "Google'i võtmed algavad tavaliselt 'AIza'."
    fi
fi

HOST=$(loe_env MAYA_HOST); HOST="${HOST:-0.0.0.0}"
PORT=$(loe_env MAYA_PORT); PORT="${PORT:-8000}"
ok "Kuulamisaadress seadistuses: $HOST:$PORT"
if [ "$HOST" = "127.0.0.1" ]; then
    info "Server kuulab AINULT selles arvutis – telefon ligi ei pääse."
fi

# =====================================================================
pealkiri "3. Andmebaas"
# =====================================================================
if [ -x .venv/bin/python ]; then
    if .venv/bin/python server/init_db.py --check >/dev/null 2>&1; then
        ok "Andmebaas on olemas ja skeem korras"
        KONTOD=$(.venv/bin/python - <<'PY' 2>/dev/null
import sys; sys.path.insert(0, "server")
try:
    import auth; auth.ensure_schema(); print(auth.kasutajaid_kokku())
except Exception: print("?")
PY
)
        if [ "$KONTOD" = "0" ]; then
            hoiatus "Kontosid ei ole veel loodud"
            info "Loo konto Androidi rakenduses („Loo uus konto“) –"
            info "ESIMENE konto saab admin-õigused."
        else
            ok "Kontosid: $KONTOD"
        fi
    else
        viga "Andmebaas puudub või on vigane"
        info "Paranda:  .venv/bin/python server/init_db.py"
    fi
fi

# =====================================================================
pealkiri "4. Kas server vastab?"
# =====================================================================
if command -v curl >/dev/null 2>&1; then
    SIHT="127.0.0.1"
    VASTUS=$(curl -sS --max-time 5 "http://$SIHT:$PORT/api/auth/status" 2>/dev/null || echo "")
    if printf '%s' "$VASTUS" | grep -q "seadistatud"; then
        ok "Server vastab aadressil http://$SIHT:$PORT"
        if printf '%s' "$VASTUS" | grep -q '"seadistatud":true'; then
            ok "Kontod on olemas – rakenduses saab sisse logida"
        else
            info "Kontosid ei ole – loo esimene konto rakenduses"
        fi
    else
        hoiatus "Server EI VASTA aadressil http://$SIHT:$PORT"
        info "See on normaalne, kui server ei jookse. Käivita:  ./kaivita.sh"
    fi
else
    hoiatus "curl puudub – serveri vastust ei saanud kontrollida"
fi

# =====================================================================
pealkiri "5. Võrk — mida telefonis sisestada"
# =====================================================================
leia_ip() {
    if [ "$(uname)" = "Darwin" ]; then
        local dev
        dev=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
        [ -n "${dev:-}" ] && ipconfig getifaddr "$dev" 2>/dev/null && return
        for d in en0 en1 en2; do ipconfig getifaddr "$d" 2>/dev/null && return; done
    else
        hostname -I 2>/dev/null | awk '{print $1}' && return
    fi
    echo ""
}
IP="$(leia_ip)"
TS=""
command -v tailscale >/dev/null 2>&1 && TS="$(tailscale ip -4 2>/dev/null | head -1)"

if [ "$HOST" = "127.0.0.1" ]; then
    info "MAYA_HOST=127.0.0.1 – telefonist ligi ei pääse (nii on seadistatud)."
else
    [ -n "$IP" ] && ok "Kohtvõrgus:  http://$IP:$PORT"
    [ -n "$TS" ] && ok "Tailscale'is: http://$TS:$PORT  (töötab ka väljaspool kodu)"
    [ -z "$IP$TS" ] && hoiatus "Võrguaadressi ei leitud – kas oled võrgus?"
fi

# =====================================================================
# KOKKUVÕTE
# =====================================================================
echo
echo "====================================================================="
if [ "$VIGU" = "0" ] && [ "$HOIATUSI" = "0" ]; then
    printf '%s KÕIK KORRAS%s\n' "$G" "$N"
elif [ "$VIGU" = "0" ]; then
    printf '%s TÖÖKORRAS, aga %s hoiatus(t)%s\n' "$Y" "$HOIATUSI" "$N"
else
    printf '%s %s VIGA ja %s hoiatus(t) — MAYA ei pruugi töötada%s\n' \
           "$R" "$VIGU" "$HOIATUSI" "$N"
fi
echo "====================================================================="
[ "$VIGU" = "0" ] || echo "Abi: docs/PAIGALDAMINE.md peatükk „Tõrkeotsing“"
exit $([ "$VIGU" = "0" ] && echo 0 || echo 1)

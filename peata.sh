#!/usr/bin/env bash
# =====================================================================
# MAYA — PEATAMINE
# =====================================================================
# Peatab SELLE kausta MAYA serveri. Teiste programmide kallale ei lähe.
#
#   ./peata.sh            # peata viisakalt (SIGTERM)
#   ./peata.sh --joud     # peata jõuga, kui viisakalt ei peatunud
#
# KUIDAS SERVER ÜLES LEITAKSE
#   1) `./kaivita.sh` kirjutab serveri PID-i faili `.maya.pid`.
#      See on täpne ja ei saa kedagi teist tabada.
#   2) Kui PID-fail puudub (server käivitati käsitsi), otsime
#      `web_maya.py` protsesse ja kontrollime iga kandidaadi
#      TÖÖKATALOOGI – peatame ainult need, mis jooksevad selles
#      projektikaustas. Võõraid Pythoni protsesse me ei puutu.
#
# MIDA SEE EI TEE: ei peata süsteemiteenuseid, ei muuda seadistust,
# ei kustuta andmeid.
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")"
JUUR="$(pwd)"
PIDFAIL="$JUUR/.maya.pid"

if [ -t 1 ]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; N=$'\033[0m'
else
    R=""; G=""; Y=""; N=""
fi
ok()      { printf '%s✓%s %s\n' "$G" "$N" "$1"; }
viga()    { printf '%s✗%s %s\n' "$R" "$N" "$1"; }
hoiatus() { printf '%s!%s %s\n' "$Y" "$N" "$1"; }
info()    { printf '   %s\n' "$1"; }

JOUD=0
[ "${1:-}" = "--joud" ] && JOUD=1

# --- kas PID on elus ja kas see ON MAYA? ----------------------------
on_maya() {
    local p="$1"
    kill -0 "$p" 2>/dev/null || return 1
    ps -p "$p" -o command= 2>/dev/null | grep -qF "web_maya.py" || return 1
    return 0
}

# --- protsessi töökataloog (macOS: lsof, Linux: /proc) --------------
protsessi_kaust() {
    local p="$1"
    if [ -r "/proc/$p/cwd" ]; then
        readlink -f "/proc/$p/cwd" 2>/dev/null && return
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -a -p "$p" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1 && return
    fi
    echo ""
}

PIDID=""

# --- 1) PID-fail ----------------------------------------------------
if [ -f "$PIDFAIL" ]; then
    P="$(tr -dc '0-9' < "$PIDFAIL")"
    if [ -n "$P" ] && on_maya "$P"; then
        PIDID="$P"
        info "Leitud PID-failist: $P"
    else
        hoiatus "PID-fail on aegunud (protsess $P enam ei jookse) – eemaldan"
        rm -f "$PIDFAIL"
    fi
fi

# --- 2) varuvariant: otsi ja KONTROLLI töökataloogi ------------------
if [ -z "$PIDID" ]; then
    KANDIDAADID=$(ps -eo pid=,command= 2>/dev/null \
                  | grep -F "web_maya.py" | grep -v "grep" | awk '{print $1}')
    for p in $KANDIDAADID; do
        KAUST="$(protsessi_kaust "$p")"
        case "$KAUST" in
            "$JUUR"|"$JUUR"/*)
                PIDID="$PIDID $p"
                info "Leitud protsessiloendist: $p (töökaust $KAUST)"
                ;;
            "")
                hoiatus "PID $p jookseb web_maya.py-d, aga töökausta ei õnnestunud tuvastada – EI PUUDU seda"
                ;;
            *)
                info "PID $p kuulub teisele paigaldusele ($KAUST) – ei puutu"
                ;;
        esac
    done
fi

if [ -z "${PIDID// }" ]; then
    ok "MAYA ei jookse (selles kaustas pole ühtegi serveriprotsessi)"
    exit 0
fi

echo
for p in $PIDID; do kill "$p" 2>/dev/null || true; done
info "Saatsin peatamiskäsu (SIGTERM). Ootan kuni 10 sekundit…"

alles() {
    local j=""
    for p in $PIDID; do on_maya "$p" && j="$j $p"; done
    echo "${j# }"
}

for _ in $(seq 1 20); do
    sleep 0.5
    [ -z "$(alles)" ] && break
done

JAANUD="$(alles)"
if [ -z "${JAANUD// }" ]; then
    rm -f "$PIDFAIL"
    ok "MAYA on peatatud"
    exit 0
fi

hoiatus "Protsess(id) ei peatunud viisakalt: $JAANUD"
if [ "$JOUD" = "1" ]; then
    for p in $JAANUD; do kill -9 "$p" 2>/dev/null || true; done
    sleep 1
    if [ -z "$(alles)" ]; then
        rm -f "$PIDFAIL"
        ok "MAYA peatatud jõuga (SIGKILL)"
        exit 0
    fi
    viga "Peatamine ei õnnestunud ka jõuga"
    exit 1
fi
info "Jõuga peatamiseks:  ./peata.sh --joud"
exit 1

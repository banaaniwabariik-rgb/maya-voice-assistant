#!/usr/bin/env bash
# =====================================================================
# MAYA — PRIVAATSUSE JA SALADUSTE KONTROLL
# =====================================================================
# Otsib hoidlast asju, mis EI TOHI avalikku repositooriumi jõuda.
# Jooksuta ENNE iga commit'i ja pull request'i.
#
#   scripts/kontrolli_privaatsust.sh
#
# Väljub koodiga 1, kui midagi leiti.
# EI TRÜKI KUNAGI leitud saladuse väärtust – ainult faili ja rea.
set -uo pipefail
cd "$(dirname "$0")/.."

VEAD=0
teata() { echo "  ❌ $1"; VEAD=$((VEAD+1)); }
ok()    { echo "  ✅ $1"; }

echo "MAYA privaatsuse kontroll: $(pwd)"
echo

# --- 1. Keelatud failid ---------------------------------------------
echo "1) Keelatud failid (andmebaasid, .env, võtmed, sessioonid)"
LEITUD=$(find . -type f \( \
    -name "*.db" -o -name "*.db-wal" -o -name "*.db-shm" \
    -o -name "*.sqlite*" -o -name ".env" \
    -o -name "*.keystore" -o -name "*.jks" -o -name "*.p12" \
    -o -name "*.pem" -o -name "*.key" \
    -o -name "*.session" -o -name "*.apk" -o -name "*.aab" \
    -o -name "memory.json" -o -name "knowledge.json" \
  \) -not -path "./.git/*" -not -path "./.venv/*" \
     -not -path "*/build/*" -not -name ".env.example" 2>/dev/null)
# TÕELINE KRITEERIUM on "ei tohi REPOSSE jõuda", mitte "ei tohi
# kettal olla". Kui git ignoreerib faili, siis see kriteerium on
# täidetud – nii saab `valjalase/` kaustas olla väljalaske APK ja
# `data/` kaustas kohalik andmebaas, ilma et kontroll valehäiret
# annaks. Jälgitud failid jäävad endiselt vea alla.
if [ -n "$LEITUD" ] && [ -d .git ]; then
  LEITUD=$(echo "$LEITUD" | while read -r f; do
    [ -z "$f" ] && continue
    git check-ignore -q "$f" 2>/dev/null || echo "$f"
  done)
fi
if [ -n "$LEITUD" ]; then
  echo "$LEITUD" | while read -r f; do teata "keelatud fail: $f"; done
  VEAD=$((VEAD+1))
else ok "keelatud faile ei ole"; fi
echo

# --- 2. API võtmete mustrid ------------------------------------------
echo "2) API võtmete mustrid"
# AIza… = Google, gsk_… = Groq, sk-… = OpenAI-stiil, ghp_… = GitHub
if grep -rInE "(AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{40,}|sk-[0-9A-Za-z]{30,}|ghp_[0-9A-Za-z]{30,}|xox[baprs]-[0-9A-Za-z-]{10,})" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=build \
     --exclude="kontrolli_privaatsust.sh" . >/dev/null 2>&1; then
  grep -rInE "(AIza[0-9A-Za-z_-]{30,}|gsk_[0-9A-Za-z]{40,}|sk-[0-9A-Za-z]{30,}|ghp_[0-9A-Za-z]{30,}|xox[baprs]-[0-9A-Za-z-]{10,})" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=build \
     --exclude="kontrolli_privaatsust.sh" -l . 2>/dev/null \
     | while read -r f; do teata "võtmemuster failis: $f (väärtust ei trüki)"; done
  VEAD=$((VEAD+1))
else ok "võtmemustreid ei leitud"; fi
echo

# --- 3. Kõvakodeeritud IP-aadressid ---------------------------------
echo "3) Kõvakodeeritud IP-aadressid"
# Lubatud: 0.0.0.0, 127.0.0.1, 10.0.2.2 (emulaator), 192.168.x.y näited
PAHAD=$(grep -rInoE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" \
    --exclude-dir=.git --exclude-dir=.venv --exclude-dir=build \
    --exclude="kontrolli_privaatsust.sh" . 2>/dev/null \
  | grep -vE ":(0\.0\.0\.0|127\.0\.0\.1|10\.0\.2\.2|255\.255\.255\.0|1\.2\.3\.4)$" \
  | grep -vE "192\.168\.[0-9]+\.[0-9]+$" \
  | grep -vE "100\.(x|[0-9]+)\.(y|[0-9]+)\.(z|[0-9]+)$" \
  | grep -vE "Chrome/|Safari/|AppleWebKit/|User-Agent|Mozilla" \
  | grep -vE ":[0-9]+\.0\.0\.0$" || true)
if [ -n "$PAHAD" ]; then
  echo "$PAHAD" | head -20 | while read -r r; do teata "IP: $r"; done
  VEAD=$((VEAD+1))
else ok "kõvakodeeritud IP-sid ei ole"; fi
echo

# --- 4. Kõvakodeeritud kodukataloogid -------------------------------
echo "4) Kõvakodeeritud kasutajateed"
if grep -rInE "/(home|Users)/[a-zA-Z0-9_.-]+/" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=build \
     --exclude="kontrolli_privaatsust.sh" . 2>/dev/null \
   | grep -vE "/(home|Users)/(kasutaja|user|maya|<|\$)" >/dev/null; then
  grep -rInE "/(home|Users)/[a-zA-Z0-9_.-]+/" \
     --exclude-dir=.git --exclude-dir=.venv --exclude-dir=build \
     --exclude="kontrolli_privaatsust.sh" -l . 2>/dev/null \
     | while read -r f; do teata "kasutaja tee failis: $f"; done
  VEAD=$((VEAD+1))
else ok "kasutajateid ei ole"; fi
echo

# --- 5. .env on ignoreeritud -----------------------------------------
echo "5) .gitignore katab saladused"
PUUDU=""
for m in ".env" "*.db" "*.keystore" "*.session" "data/"; do
  grep -qF -- "$m" .gitignore 2>/dev/null || PUUDU="$PUUDU $m"
done
if [ -n "$PUUDU" ]; then teata ".gitignore'is puudub:$PUUDU"
else ok ".gitignore katab .env, *.db, *.keystore, *.session, data/"; fi
echo

# --- 6. Git indeksis ei ole saladusi --------------------------------
echo "6) Git indeks"
if [ -d .git ]; then
  INDEKS=$(git ls-files 2>/dev/null | grep -E "\.(db|env|keystore|jks|session|apk|pem|key)$" | grep -v "\.env\.example" || true)
  if [ -n "$INDEKS" ]; then
    echo "$INDEKS" | while read -r f; do teata "git jälgib: $f"; done
    VEAD=$((VEAD+1))
  else ok "git ei jälgi ühtegi saladust"; fi
else ok "git hoidlat ei ole (vahele jäetud)"; fi
echo

echo "====================================================="
if [ "$VEAD" -gt 0 ]; then
  echo "  TULEMUS: $VEAD probleem(i). ÄRA COMMIT'I."
  exit 1
fi
echo "  TULEMUS: puhas."

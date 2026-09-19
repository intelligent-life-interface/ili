#!/usr/bin/env bash
# architektur-review — automatische Konventions-Checks für ein Homeserver-Projekt
#
# Prüft die harten Haus-Regeln (CLAUDE.md-Vorgaben) statisch und gratis:
#   Doku, systemd-Unit, Ports, Secrets, Debug-Logs, Datei-Grössen, Kanban, Git.
# Die Urteils-Fragen (Datenfluss, DB-Wahl, Exposure) stehen in SKILL.md — die
# beantwortet Claude nach diesem Report.
#
# Usage:
#   review.sh <projektpfad>            # z.B. ~/containers/camtimport
#   review.sh <projektpfad> --name X   # falls Container-Name != Ordnername

set -uo pipefail

PROJ="${1:-}"
[[ -n "$PROJ" && -d "$PROJ" ]] || { echo "Usage: review.sh <projektpfad> [--name <container>]" >&2; exit 2; }
PROJ="$(cd "$PROJ" && pwd)"
NAME="$(basename "$PROJ")"
[[ "${2:-}" == "--name" && -n "${3:-}" ]] && NAME="$3"

UNIT="$HOME/.config/systemd/user/container-$NAME.service"
BOARD="$HOME/containers/dashboard/boards/$NAME.json"
OK=0; WARN=0; FAIL=0

ok()   { echo "  OK    $*"; OK=$((OK+1)); }
warn() { echo "  WARN  $*"; WARN=$((WARN+1)); }
fail() { echo "  FAIL  $*"; FAIL=$((FAIL+1)); }

echo "=== Architektur-Review (statisch): $NAME ($PROJ) ==="

echo "--- Doku ---"
if [[ -f "$PROJ/CLAUDE.md" ]]; then
    ok "CLAUDE.md vorhanden"
    # Beide etablierten Schreibweisen zulassen: am Zeilenanfang (22 Projekte)
    # und im einleitenden Blockquote "> Nur bei Bedarf laden. **Tags:** …"
    # (17 Projekte, u.a. caddy und dashboard).
    grep -qE '^(> .*)?\*\*Tags:\*\*' "$PROJ/CLAUDE.md" \
        && ok "Tags:-Zeile vorhanden" \
        || fail "Tags:-Zeile fehlt in CLAUDE.md (Root-Index/Router brauchen sie)"
else
    fail "CLAUDE.md fehlt in $PROJ"
fi
grep -q "$NAME" "$HOME/CLAUDE.md" 2>/dev/null \
    && ok "In Root-~/CLAUDE.md erwähnt" \
    || warn "Nicht in Root-~/CLAUDE.md (Container-Tabelle + Tag-Index ergänzen)"
grep -q "$NAME" "$HOME/.claude/skills/homeserver-projekte/SKILL.md" 2>/dev/null \
    && ok "Im Router-Skill homeserver-projekte" \
    || warn "Fehlt im Router-Skill homeserver-projekte/SKILL.md"

echo "--- systemd / Podman ---"
if [[ -f "$UNIT" ]]; then
    ok "Unit vorhanden: container-$NAME.service"
    grep -q '^User=' "$UNIT" \
        && fail "Unit enthält User= — bei systemd --user verboten (216/GROUP)!" \
        || ok "Kein User= in der Unit"
    grep -q 'Restart=' "$UNIT" && ok "Restart-Policy gesetzt" || warn "Kein Restart= in der Unit"
    PORTS=$(grep -oE -- '-p [0-9.:]*[0-9]+:[0-9]+' "$UNIT" | sed 's/-p //' || true)
    if [[ -n "$PORTS" ]]; then
        for pm in $PORTS; do
            hp="${pm%%:*}"; hp="${hp##*.}"; hp="${hp##*:}"
            grep -qE "\b${hp}(→|:| )" "$HOME/CLAUDE.md" 2>/dev/null \
                && ok "Port $pm in Root-CLAUDE.md dokumentiert" \
                || warn "Port $pm nicht in Root-CLAUDE.md-Tabelle"
        done
    fi
else
    warn "Keine systemd-Unit ($UNIT) — läuft das anders (Host-Service/Timer)?"
fi
if [[ -f "$PROJ/Containerfile" || -f "$PROJ/Dockerfile" ]]; then
    ok "Containerfile/Dockerfile vorhanden"
else
    warn "Kein Containerfile/Dockerfile im Projektordner"
fi

echo "--- Secrets ---"
HITS=$(grep -rniE '(password|passwort|api[_-]?key|secret|token)\s*[:=]\s*["'"'"'][A-Za-z0-9+/_.-]{8,}["'"'"']' \
    "$PROJ" --include='*.py' --include='*.js' --include='*.sh' --include='*.yml' --include='*.yaml' --include='*.json' \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=__pycache__ 2>/dev/null \
    | grep -vi 'config\.env\|os\.environ\|getenv\|placeholder\|example\|CHANGE_ME' | head -5 || true)
# Zweiter Durchgang: Token-artige Zeichenketten ohne Schlüsselwort davor.
# Der Filter oben verwirft Zeilen mit os.environ/getenv — genau das Muster
# os.getenv("X", "<echter-token>") ist aber ein häufiger Leak, und bei
# mehrzeiligen Aufrufen steht das Literal gar nicht auf der getenv-Zeile.
# Erfasst lange base64-artige Literale (Influx-/JWT-/API-Tokens ab 32 Zeichen).
ENTROPY_HITS=$(grep -rnE '["'"'"'][A-Za-z0-9+/_-]{32,}={0,2}["'"'"']' \
    "$PROJ" --include='*.py' --include='*.js' --include='*.sh' --include='*.yml' --include='*.yaml' \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=__pycache__ 2>/dev/null \
    | grep -viE 'example|placeholder|CHANGE_ME|sha256|md5|[0-9a-f]{40}\b.*commit' | head -5 || true)

if [[ -n "$HITS" || -n "$ENTROPY_HITS" ]]; then
    fail "Mögliche hartkodierte Secrets (gehören in ~/config.env):"
    { [[ -n "$HITS" ]] && echo "$HITS"; [[ -n "$ENTROPY_HITS" ]] && echo "$ENTROPY_HITS"; } \
        | sort -u | sed 's/^/        /' | cut -c1-160
else
    ok "Keine hartkodierten Secrets gefunden (Heuristik)"
fi

echo "--- Code-Konventionen ---"
BIG=$(find "$PROJ" -name '*.py' -o -name '*.js' 2>/dev/null \
    | grep -v -e /node_modules/ -e /venv/ -e /.git/ -e /static/vendor/ \
    | xargs -r wc -l 2>/dev/null | awk '$1>500 && $2!="insgesamt" && $2!="total" {print $1, $2}' | sort -rn | head -5)
if [[ -n "$BIG" ]]; then
    warn "Dateien >500 Zeilen (Regel: pro Funktion eine Datei, aufteilen):"
    echo "$BIG" | sed 's/^/        /'
else
    ok "Keine Datei >500 Zeilen"
fi
PY_FILES=$(find "$PROJ" -name '*.py' -not -path '*/.venv/*' -not -path '*/venv/*' -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null | head -1)
if [[ -z "$PY_FILES" ]]; then
    ok "Kein Python-Projekt (keine .py-Dateien) — Logging-Check übersprungen"
else
    grep -rq 'logging.basicConfig\|getLogger' "$PROJ" --include='*.py' --exclude-dir=venv --exclude-dir=.venv --exclude-dir=.git 2>/dev/null \
        && ok "Python-Logging vorhanden" \
        || warn "Kein Python-Logging gefunden (Vorgabe: gute Debug-Logs)"
fi

echo "--- Container-Architektur ---"
CONTAINER_CHECK="$HOME/.claude/skills/container-architektur/container-check.sh"
if [[ -x "$CONTAINER_CHECK" ]]; then
    CC_JSON="$("$CONTAINER_CHECK" "$PROJ" --json 2>/dev/null)"
    if [[ -n "$CC_JSON" ]]; then
        while IFS=$'\t' read -r lvl msg; do
            case "$lvl" in
                WARN) warn "[container-check] $msg" ;;
                FAIL) fail "[container-check] $msg" ;;
            esac
        done < <(python3 -c '
import json, sys
d = json.load(sys.stdin)
for f in d.get("findings", []):
    lvl = f["level"]
    if lvl in ("WARN", "FAIL"):
        print(lvl + "\t" + f["message"])
' <<< "$CC_JSON" 2>/dev/null)
        CC_OK=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["summary"]["ok"])' <<< "$CC_JSON" 2>/dev/null || echo 0)
        OK=$((OK + CC_OK))
        [[ "$CC_OK" -gt 0 ]] && echo "  OK    container-check.sh: $CC_OK weitere OK-Punkte (Details oben)"
    else
        warn "container-check.sh lieferte keine Ausgabe (kein Containerfile/Dockerfile gefunden?)"
    fi
else
    echo "  (Skill container-architektur nicht installiert — übersprungen)"
fi

echo "--- Kanban / Git ---"
[[ -f "$BOARD" ]] && ok "Kanban-Board vorhanden: $NAME.json" || warn "Kein Kanban-Board ($BOARD)"
if [[ -d "$PROJ/.git" ]]; then
    REMOTE=$(git -C "$PROJ" remote get-url origin 2>/dev/null || true)
    if [[ -n "$REMOTE" ]]; then
        ok "Git-Repo mit Remote: $REMOTE (privat? → gh repo view)"
    else
        warn "Git-Repo ohne Remote (privates GitHub-Repo anlegen, GH_ADMIN_TOKEN)"
    fi
    [[ -f "$PROJ/.gitignore" ]] && ok ".gitignore vorhanden" || warn "Kein .gitignore (Daten/Secrets ausnehmen!)"
else
    warn "Kein Git-Repo im Projektordner"
fi

echo
echo "=== Ergebnis: $OK OK, $WARN WARN, $FAIL FAIL ==="
[[ "$FAIL" -gt 0 ]] && exit 1 || exit 0

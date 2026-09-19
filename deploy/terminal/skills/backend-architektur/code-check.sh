#!/usr/bin/env bash
# code-check.sh — static check of Python/JS service code against the backend-architektur
# rules (file size, debug logging, English identifiers, hardcoded paths/secrets, tests).
#
# Usage:
#   code-check.sh <projektpfad>            ein Projekt (~/containers/<name> oder ~/Projekte/<name>)
#   code-check.sh --all [--json]           jedes ~/containers/*/ und ~/Projekte/*/ mit .py/.js-Dateien
#   options:  --json    maschinenlesbare Findings (fuer den Kanban-Automat)
#
# Severity:  FAIL = hartkodiertes Secret (Leak-Risiko)                  -> exit code 1
#            WARN = kostet Wartbarkeit (Datei-Groesse, fehlendes Logging,
#                   Home-Pfad hartkodiert, keine Tests, deutsche Bezeichner)
#            INFO = Hinweis
# Output style folgt architektur-review/review.sh und container-check.sh. Debug: CHECK_DEBUG=1
set -uo pipefail

JSON=0
OK=0 WARN=0 FAIL=0 INFO=0
FINDINGS_FILE=""

dbg() { [[ "${CHECK_DEBUG:-0}" == "1" ]] && echo "[code-check-debug $(date +%H:%M:%S)] $*" >&2; return 0; }
init_findings() { FINDINGS_FILE="$(mktemp)"; trap 'rm -f "$FINDINGS_FILE"' EXIT; }

# record <level> <projekt> <area> <message>
record() {
    local lvl="$1" name="$2" area="$3" msg="$4"
    printf '%s\t%s\t%s\t%s\n' "$lvl" "$name" "$area" "$msg" >> "$FINDINGS_FILE"
    [[ "$JSON" == "1" ]] || printf '  %-5s %s\n' "$lvl" "$msg"
}
ok()   { record OK   "$1" "$2" "$3"; OK=$((OK+1)); }
warn() { record WARN "$1" "$2" "$3"; WARN=$((WARN+1)); }
fail() { record FAIL "$1" "$2" "$3"; FAIL=$((FAIL+1)); }
info() { record INFO "$1" "$2" "$3"; INFO=$((INFO+1)); }
header() { [[ "$JSON" == "1" ]] || echo "== $1  ($2)"; }

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

TARGET="" ALL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)     ALL=1; shift ;;
        --json)    JSON=1; shift ;;
        -h|--help) usage 0 ;;
        -*)        echo "unbekannte Option: $1" >&2; usage 1 ;;
        *)         TARGET="$1"; shift ;;
    esac
done
[[ $ALL -eq 1 || -n "$TARGET" ]] || { echo "Ziel fehlt (Projektpfad oder --all). -h fuer Hilfe." >&2; exit 2; }

EXCLUDES=(-not -path '*/node_modules/*' -not -path '*/venv/*' -not -path '*/.venvs/*' \
    -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/static/vendor/*')

# grep-Filter fuer deutsche Bezeichner: gaengige deutsche Verb-/Nomen-Stubs in
# def/class/Variablen-Zuweisungen. Heuristik, kein Parser — Fehlalarme moeglich
# (z.B. englische Woerter, die zufaellig ein Praefix teilen), daher WARN, kein FAIL.
DE_STUB_RE='\b(pruef|prüf|lade|speicher|berechne|anzahl|datei|zeile|zeit|fehler|sende|empfange|erstelle|loesche|lösche)[a-zA-Z_]*\s*[(=]'

check_project() {
    local dir="$1" name
    dir="$(readlink -f "$dir")"
    name="$(basename "$dir")"
    header "$name" "$dir"

    local files
    files="$(find "$dir" \( -name '*.py' -o -name '*.js' \) "${EXCLUDES[@]}" 2>/dev/null)"
    if [[ -z "$files" ]]; then
        info "$name" scope "keine .py/.js-Dateien gefunden — nichts zu pruefen"
        return
    fi

    # 1. Dateigroesse
    local big
    big="$(echo "$files" | xargs -r wc -l 2>/dev/null | awk '$1>500 && $2!="total" && $2!="insgesamt" {print $2" ("$1" Zeilen)"}')"
    if [[ -n "$big" ]]; then
        while IFS= read -r line; do warn "$name" size "Datei >500 Zeilen (aufteilen): $line"; done <<< "$big"
    else
        ok "$name" size "keine Datei >500 Zeilen"
    fi

    # 2. Debug-Logging (nur .py-Dateien, JS-Logging-Konventionen sind uneinheitlich)
    local py_files
    py_files="$(echo "$files" | grep '\.py$' || true)"
    if [[ -n "$py_files" ]]; then
        if echo "$py_files" | xargs -r grep -l 'logging\.basicConfig\|getLogger' 2>/dev/null | grep -q .; then
            ok "$name" logging "Python-Logging vorhanden (logging.basicConfig/getLogger)"
        else
            warn "$name" logging "kein Python-Logging gefunden (Vorgabe: gute Debug-Logs)"
        fi
    fi

    # 3. Hartkodierte Home-Pfade (sollten aus config.env/Argumenten kommen, nicht literal im Code)
    local home_hits
    home_hits="$(echo "$files" | xargs -r grep -ln '/home/[a-z][a-z0-9_-]*' 2>/dev/null | grep -v 'config\.env' | head -5 || true)"
    if [[ -n "$home_hits" ]]; then
        warn "$name" paths "hartkodierte Home-Pfade in: $(echo "$home_hits" | xargs -n1 basename | paste -sd, -)"
    else
        ok "$name" paths "keine hartkodierten Home-Pfade gefunden"
    fi

    # 4. Hartkodierte Secrets (gleiche Heuristik wie architektur-review/review.sh)
    local secret_hits entropy_hits
    secret_hits="$(echo "$files" | xargs -r grep -niE '(password|passwort|api[_-]?key|secret|token)\s*[:=]\s*["'"'"'][A-Za-z0-9+/_.-]{8,}["'"'"']' 2>/dev/null \
        | grep -vi 'config\.env\|os\.environ\|getenv\|placeholder\|example\|CHANGE_ME' | head -5 || true)"
    entropy_hits="$(echo "$files" | xargs -r grep -nE '["'"'"'][A-Za-z0-9+/_-]{32,}={0,2}["'"'"']' 2>/dev/null \
        | grep -viE 'example|placeholder|CHANGE_ME|sha256|md5' | head -5 || true)"
    if [[ -n "$secret_hits" || -n "$entropy_hits" ]]; then
        fail "$name" secrets "moegliche hartkodierte Secrets (gehoeren in ~/config.env) — $(echo -e "${secret_hits}\n${entropy_hits}" | grep -c . ) Fundstelle(n)"
    else
        ok "$name" secrets "keine hartkodierten Secrets gefunden (Heuristik)"
    fi

    # 5. Tests vorhanden
    if find "$dir" \( -name 'test_*.py' -o -name '*_test.py' -o -path '*/tests/*' \) "${EXCLUDES[@]}" 2>/dev/null | grep -q .; then
        ok "$name" tests "Tests gefunden (tests/ oder test_*.py)"
    else
        warn "$name" tests "keine Tests gefunden (tests/ oder test_*.py)"
    fi

    # 6. Deutsche Bezeichner (Heuristik)
    local de_hits
    de_hits="$(echo "$py_files" | xargs -r grep -nEi "$DE_STUB_RE" 2>/dev/null | grep -v '#' | head -5 || true)"
    if [[ -n "$de_hits" ]]; then
        warn "$name" identifiers "moeglich deutsche Bezeichner (Code soll Englisch sein): $(echo "$de_hits" | wc -l) Fundstelle(n), z.B. $(echo "$de_hits" | head -1 | cut -d: -f1 | xargs basename)"
    else
        ok "$name" identifiers "keine deutschen Bezeichner-Muster gefunden (Heuristik)"
    fi
}

find_projects() {
    local root="$1" d
    [[ -d "$root" ]] || return 0
    for d in "$root"/*/; do
        d="${d%/}"
        find "$d" -maxdepth 2 \( -name '*.py' -o -name '*.js' \) "${EXCLUDES[@]}" 2>/dev/null | grep -q . && echo "$d"
    done
}

summary() {
    if [[ "$JSON" == "1" ]]; then
        python3 - "$FINDINGS_FILE" "$OK" "$WARN" "$FAIL" "$INFO" <<'PY'
import json, sys
rows = [l.rstrip("\n").split("\t", 3) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print(json.dumps({
    "summary": {"ok": int(sys.argv[2]), "warn": int(sys.argv[3]), "fail": int(sys.argv[4]), "info": int(sys.argv[5])},
    "findings": [{"level": r[0], "project": r[1], "area": r[2], "message": r[3]} for r in rows if r[0] != "OK"],
}, ensure_ascii=False, indent=1))
PY
    else
        echo; echo "Ergebnis: OK=$OK WARN=$WARN FAIL=$FAIL INFO=$INFO"
        [[ $FAIL -eq 0 ]] || echo "FAIL vor dem naechsten Commit beheben (Regeln: skill/backend-architektur/SKILL.md)"
    fi
    [[ $FAIL -eq 0 ]]
}

init_findings
if [[ $ALL -eq 1 ]]; then
    n=0
    for root in "$HOME/containers" "$HOME/Projekte"; do
        while IFS= read -r d; do
            check_project "$d"; n=$((n+1))
        done < <(find_projects "$root")
    done
    dbg "$n Projekte geprueft"
else
    [[ -d "$TARGET" ]] || { echo "Ziel nicht gefunden: $TARGET" >&2; exit 2; }
    check_project "$TARGET"
fi
summary

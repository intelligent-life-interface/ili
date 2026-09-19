#!/usr/bin/env bash
# frontend-check.sh — static check of a WebGUI against the frontend-architektur rules
# (UI-Kit eingebunden, keine hartkodierten deutschen Texte statt Sprachdatei, stabile
# IDs, kein Inline-CSS fuer Kit-Komponenten).
#
# Usage:
#   frontend-check.sh <projektpfad>            ein Projekt (index.html irgendwo drunter)
#   frontend-check.sh --all [--json]           jedes ~/containers/*/ und ~/Projekte/*/ mit index.html
#   options:  --json    maschinenlesbare Findings (fuer den Kanban-Automat)
#
# Severity:  FAIL = keins vorgesehen (alles hier ist Stil/Wartbarkeit, kein Breaker)
#            WARN = UI-Kit fehlt, Inline-CSS statt Kit, hartkodierte deutsche Texte,
#                   instabile IDs
#            INFO = Hinweis
# Output style folgt architektur-review/review.sh und container-check.sh. Debug: CHECK_DEBUG=1
set -uo pipefail

JSON=0
OK=0 WARN=0 FAIL=0 INFO=0
FINDINGS_FILE=""

dbg() { [[ "${CHECK_DEBUG:-0}" == "1" ]] && echo "[frontend-check-debug $(date +%H:%M:%S)] $*" >&2; return 0; }
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

EXCLUDES=(-not -path '*/node_modules/*' -not -path '*/venv/*' -not -path '*/.git/*' -not -path '*/static/vendor/*')

# grep-Heuristik fuer offensichtlich deutsche Textknoten/Strings: Umlaute/ß oder
# haeufige deutsche Fuellwoerter. Kein Parser, daher WARN statt FAIL.
DE_WORD_RE='[äöüÄÖÜß]|\b(bitte|speichern|löschen|loeschen|abbrechen|hinzufügen|hinzufuegen|einstellungen|übersicht|uebersicht)\b'

check_project() {
    local dir="$1" name
    dir="$(readlink -f "$dir")"
    name="$(basename "$dir")"
    header "$name" "$dir"

    local html_files
    html_files="$(find "$dir" -name '*.html' "${EXCLUDES[@]}" 2>/dev/null)"
    if [[ -z "$html_files" ]]; then
        info "$name" scope "kein HTML gefunden — nichts zu pruefen"
        return
    fi

    # 1. UI-Kit eingebunden
    if echo "$html_files" | xargs -r grep -lE '/ui-kit/v1/|ui\.intranet\.[A-Za-z0-9.-]+/v1' 2>/dev/null | grep -q .; then
        ok "$name" ui-kit "UI-Kit eingebunden (/ui-kit/v1/ oder volle Intranet-URL)"
    else
        warn "$name" ui-kit "kein Hinweis auf zentrales UI-Kit gefunden (/ui-kit/v1/ bzw. https://ui.intranet.<DOMAIN>/v1/…)"
    fi

    # 2. Inline-CSS statt Kit-Komponente
    local inline_style
    inline_style="$(echo "$html_files" | xargs -r grep -lE 'style="|<style[ >]' 2>/dev/null | head -5 || true)"
    if [[ -n "$inline_style" ]]; then
        warn "$name" inline-css "Inline-style=/<style>-Bloecke gefunden (gehoert ins Kit oder projekteigenes style.css): $(echo "$inline_style" | xargs -n1 basename | paste -sd, -)"
    else
        ok "$name" inline-css "kein Inline-CSS in HTML gefunden"
    fi

    # 3. Sprachdatei vorhanden?
    local lang_files
    lang_files="$(find "$dir" -iname 'de.json' -o -ipath '*/lang/*.json' -o -ipath '*/locales/*.json' 2>/dev/null | head -3)"
    if [[ -n "$lang_files" ]]; then
        ok "$name" i18n "Sprachdatei gefunden ($(echo "$lang_files" | head -1 | xargs basename))"
    else
        warn "$name" i18n "keine Sprachdatei gefunden (de.json/lang/*.json) — Texte vermutlich hartkodiert"
    fi

    # 4. Hartkodierte deutsche Texte in HTML/JS (Heuristik: Umlaute/deutsche Fuellwoerter
    #    ausserhalb von Kommentaren). Ohne Sprachdatei ist das ohnehin erwartbar (siehe 3.),
    #    daher hier nur zaehlen, nicht doppelt warnen.
    local js_files de_hits
    js_files="$(find "$dir" -name '*.js' "${EXCLUDES[@]}" 2>/dev/null)"
    de_hits="$(echo -e "${html_files}\n${js_files}" | grep -v '^$' | xargs -r grep -ncE "$DE_WORD_RE" 2>/dev/null | awk -F: '$2>0' | wc -l)"
    if [[ "$de_hits" -gt 0 && -z "$lang_files" ]]; then
        warn "$name" i18n "hartkodierte deutsche Texte in $de_hits Datei(en) ohne Sprachdatei"
    elif [[ "$de_hits" -gt 0 ]]; then
        info "$name" i18n "deutsche Textmuster in $de_hits Datei(en) trotz vorhandener Sprachdatei — pruefen, ob das Restfaelle sind"
    fi

    # 5. Stabile IDs (Heuristik: id="…" mit Umlaut/Leerzeichen/deutschem Wort ist
    #    ein Zeichen dafuer, dass die ID an der sichtbaren Beschriftung haengt)
    local bad_ids
    bad_ids="$(echo "$html_files" | xargs -r grep -noE 'id="[^"]*"' 2>/dev/null | grep -E "$DE_WORD_RE" | head -5 || true)"
    if [[ -n "$bad_ids" ]]; then
        warn "$name" ids "IDs mit deutschem/sichtbarkeits-abhaengigem Text gefunden (sollten stabil/sprachunabhaengig sein): $(echo "$bad_ids" | wc -l) Fundstelle(n)"
    else
        ok "$name" ids "keine auffaelligen IDs gefunden (Heuristik)"
    fi
}

find_projects() {
    local root="$1" d
    [[ -d "$root" ]] || return 0
    for d in "$root"/*/; do
        d="${d%/}"
        find "$d" -maxdepth 3 -name '*.html' "${EXCLUDES[@]}" 2>/dev/null | grep -q . && echo "$d"
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

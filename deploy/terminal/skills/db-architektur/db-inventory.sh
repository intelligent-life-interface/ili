#!/usr/bin/env bash
# db-inventory.sh — findet Datenbank-Dateien je Projekt und prueft sie gegen die
# db-architektur-Regeln (Engine plausibel, Backup vorhanden/frisch, Mount-Modus in der Unit).
#
# Usage:
#   db-inventory.sh <projektname|pfad>   ein Projekt (~/containers/<name> oder ~/Projekte/<name>)
#   db-inventory.sh --all [--json]       ~/containers/*/ und ~/Projekte/*/ (Tiefe 4), ohne db-snapshots selbst
#
# Severity:  FAIL = Datei kaputt/leer (0 Byte DB)                       -> exit code 1
#            WARN = kein/veraltetes Backup, Mount-Modus rw ohne Grund, Engine nicht bestimmbar
#            INFO = Hinweis (WAL-Nebendateien, Grösse, Mount nicht geprueft)
# Output style folgt container-check.sh/repo-check.sh/net-check.sh. Debug: CHECK_DEBUG=1
set -uo pipefail

SNAPSHOT_DIR="$HOME/containers/db-snapshots"
BACKUP_MAX_AGE_H=30   # db-snapshot.timer laeuft taeglich 03:00 -> > 30h ist ueberfaellig

JSON=0
OK=0 WARN=0 FAIL=0 INFO=0
FINDINGS_FILE=""

dbg() { [[ "${CHECK_DEBUG:-0}" == "1" ]] && echo "[db-inventory-debug $(date +%H:%M:%S)] $*" >&2; return 0; }
init_findings() { FINDINGS_FILE="$(mktemp)"; trap 'rm -f "$FINDINGS_FILE"' EXIT; }

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

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

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
[[ $ALL -eq 1 || -n "$TARGET" ]] || { echo "Ziel fehlt (Projektname/Pfad oder --all). -h fuer Hilfe." >&2; exit 2; }

# Engine anhand Magic-Bytes/Endung bestimmen (gleiche SQLite-Erkennung wie db-snapshots/snapshot.sh)
detect_engine() {
    local f="$1"
    if [[ "$(head -c 15 "$f" 2>/dev/null | tr -d '\0')" == "SQLite format 3" ]]; then
        echo "sqlite"
    elif [[ "$f" == *.duckdb ]]; then
        echo "duckdb"
    else
        echo "unbekannt"
    fi
}

find_backup() {   # $1 = Basisname der DB-Datei -> Pfad im Snapshot-Verzeichnis oder leer
    [[ -d "$SNAPSHOT_DIR" ]] || { echo ""; return; }
    find "$SNAPSHOT_DIR" -maxdepth 3 -type f -iname "$(basename "$1")" 2>/dev/null | head -1
}

find_unit_mount() {   # $1 = projektname, $2 = db-datei -> Mount-Flag (ro/rw/keins) oder leer
    local unit="$HOME/.config/systemd/user/container-$1.service" dirpart line
    [[ -f "$unit" ]] || { echo ""; return; }
    dirpart="$(dirname "$2")"
    line="$(grep -oE -- "-v [^ ]*$(basename "$dirpart")[^ ]*" "$unit" 2>/dev/null | head -1)"
    [[ -z "$line" ]] && { echo ""; return; }
    if [[ "$line" == *:ro* ]]; then echo "ro"; elif [[ "$line" == *:rw* || "$line" != *:* ]]; then echo "rw"; else echo "?"; fi
}

check_db_file() {
    local proj="$1" f="$2" engine size wal shm backup mount age_h

    engine="$(detect_engine "$f")"
    size="$(du -h "$f" 2>/dev/null | cut -f1)"

    if [[ ! -s "$f" ]]; then
        fail "$proj" file "$(basename "$f"): 0 Byte — kaputte oder nie initialisierte DB ($f)"
        return
    fi

    if [[ "$engine" == "unbekannt" ]]; then
        warn "$proj" engine "$(basename "$f") ($size): Engine nicht bestimmbar (kein SQLite-Header, keine .duckdb-Endung) — manuell pruefen"
    else
        info "$proj" engine "$(basename "$f"): $engine, $size"
    fi

    if [[ "$engine" == "sqlite" ]]; then
        wal="${f}-wal"; shm="${f}-shm"
        if [[ -f "$wal" ]]; then
            info "$proj" wal "$(basename "$f"): WAL-Modus aktiv ($(du -h "$wal" 2>/dev/null | cut -f1) -wal)"
        fi
    fi

    backup="$(find_backup "$f")"
    if [[ -z "$backup" ]]; then
        warn "$proj" backup "$(basename "$f"): kein Snapshot in $SNAPSHOT_DIR gefunden — in snapshot.sh ergaenzen, falls die DB per CloudBeaver/Metabase einsehbar sein soll"
    else
        age_h=$(( ( $(date +%s) - $(stat -c %Y "$backup" 2>/dev/null || echo 0) ) / 3600 ))
        if [[ $age_h -gt $BACKUP_MAX_AGE_H ]]; then
            warn "$proj" backup "$(basename "$f"): letzter Snapshot ist ${age_h}h alt (> ${BACKUP_MAX_AGE_H}h) — db-snapshot.timer pruefen"
        else
            ok "$proj" backup "$(basename "$f"): Snapshot ${age_h}h alt"
        fi
    fi

    mount="$(find_unit_mount "$proj" "$f")"
    case "$mount" in
        ro) ok "$proj" mount "$(basename "$f"): Unit mountet read-only" ;;
        rw) info "$proj" mount "$(basename "$f"): Unit mountet read-write (normal fuer die Live-DB des eigenen Dienstes)" ;;
        *)  info "$proj" mount "$(basename "$f"): Mount-Modus in Unit nicht ermittelt (kein Treffer oder kein container-$proj.service)" ;;
    esac
}

find_dbs() {   # $1 = Projektordner -> DB-Dateipfade, snapshot-eigene Kopien und venvs ausgeschlossen
    find "$1" -maxdepth 4 -type f \( -iname '*.db' -o -iname '*.sqlite' -o -iname '*.sqlite3' -o -iname '*.duckdb' \) \
        2>/dev/null | grep -vE '/(\.git|node_modules|\.venvs?|__pycache__)/'
}

check_project() {
    local dir="$1" name found=0
    name="$(basename "$dir")"
    [[ "$dir" == "$SNAPSHOT_DIR" ]] && return
    while IFS= read -r f; do
        [[ $found -eq 0 ]] && header "$name" "$dir"
        found=1
        check_db_file "$name" "$f"
    done < <(find_dbs "$dir")
    [[ $found -eq 1 ]] && dbg "$name: fertig"
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
        [[ $FAIL -eq 0 ]] || echo "FAIL pruefen (Regeln: ~/.claude/skills/db-architektur/SKILL.md)"
    fi
    [[ $FAIL -eq 0 ]]
}

init_findings
if [[ $ALL -eq 1 ]]; then
    n=0
    for root in "$HOME/containers" "$HOME/Projekte"; do
        [[ -d "$root" ]] || continue
        for d in "$root"/*/; do
            d="${d%/}"; check_project "$d"; n=$((n+1))
        done
    done
    dbg "$n Ordner geprueft"
else
    if [[ -d "$TARGET" ]]; then
        DIR="$TARGET"
    elif [[ -d "$HOME/containers/$TARGET" ]]; then
        DIR="$HOME/containers/$TARGET"
    elif [[ -d "$HOME/Projekte/$TARGET" ]]; then
        DIR="$HOME/Projekte/$TARGET"
    else
        echo "Ziel nicht gefunden: $TARGET" >&2; exit 2
    fi
    check_project "$DIR"
fi
summary

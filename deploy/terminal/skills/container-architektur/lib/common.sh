#!/usr/bin/env bash
# lib/common.sh — shared helpers for container-check.sh: finding collection (text/JSON),
# file lookup, image sizes. Sourced, not executed.

JSON="${JSON:-0}"
OK=0 WARN=0 FAIL=0 INFO=0
FINDINGS_FILE=""

dbg() { [[ "${CHECK_DEBUG:-0}" == "1" ]] && echo "[check-debug $(date +%H:%M:%S)] $*" >&2; return 0; }
init_findings() { FINDINGS_FILE="$(mktemp)"; trap 'rm -f "$FINDINGS_FILE"' EXIT; }

# record <level> <container> <area> <message>
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

find_containerfile() {   # $1 = dir -> path or empty
    local d="$1" f
    for f in Containerfile Dockerfile; do [[ -f "$d/$f" ]] && { echo "$d/$f"; return; }; done
    echo ""
}
find_unit() {            # $1 = name -> unit path or empty
    local n="$1" u
    for u in "$HOME/.config/systemd/user/container-$n.service" "$HOME/.config/systemd/user/$n.service"; do
        [[ -f "$u" ]] && { echo "$u"; return; }
    done
    echo ""
}
# join backslash-continued lines, drop comments/blank lines -> one logical instruction per line
logical_lines() { sed -e ':a' -e '/\\[[:space:]]*$/{N; s/\\[[:space:]]*\n[[:space:]]*/ /; ta}' "$1" | grep -vE '^[[:space:]]*(#|$)'; }

IMAGE_SIZES=""
load_image_sizes() { IMAGE_SIZES="$(podman images --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null || true)"; }
check_image_size() {     # $1 = name; INFO with size, WARN above 1.5 GB
    local n="$1" line size num unit
    line="$(grep -E "^localhost/$n:latest " <<< "$IMAGE_SIZES" | head -1)"
    [[ -n "$line" ]] || return 0
    size="${line#* }"; num="${size% *}"; unit="${size##* }"
    if [[ "$unit" == "GB" ]] && awk -v v="$num" 'BEGIN{exit !(v>1.5)}'; then
        warn "$n" image "Image localhost/$n:latest ist $size — Grösse prüfen (Basis-Image? Build-Tools im Runtime?)"
    else
        info "$n" image "Image localhost/$n:latest: $size"
    fi
}

summary() {
    if [[ "$JSON" == "1" ]]; then
        python3 - "$FINDINGS_FILE" "$OK" "$WARN" "$FAIL" "$INFO" <<'PY'
import json, sys
rows = [l.rstrip("\n").split("\t", 3) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print(json.dumps({
    "summary": {"ok": int(sys.argv[2]), "warn": int(sys.argv[3]), "fail": int(sys.argv[4]), "info": int(sys.argv[5])},
    "findings": [{"level": r[0], "container": r[1], "area": r[2], "message": r[3]} for r in rows if r[0] != "OK"],
}, ensure_ascii=False, indent=1))
PY
    else
        echo; echo "Ergebnis: OK=$OK WARN=$WARN FAIL=$FAIL INFO=$INFO"
        [[ $FAIL -eq 0 ]] || echo "FAIL vor dem Deploy beheben (Regeln: ~/.claude/skills/container-architektur/SKILL.md)"
    fi
    [[ $FAIL -eq 0 ]]
}

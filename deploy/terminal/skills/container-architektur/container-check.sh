#!/usr/bin/env bash
# container-check.sh — static check of a container project against the
# container-architektur rules (Containerfile, rootless-Podman systemd unit, compose).
#
# Usage:
#   container-check.sh <name>                    ~/containers/<name> + container-<name>.service
#   container-check.sh <dir>                     explicit project dir (Containerfile|Dockerfile inside)
#   container-check.sh <Containerfile> [--context <dir>]   one file; context = dir with the COPY sources
#   container-check.sh --all                     every ~/containers/*/ that has a Containerfile/Dockerfile
#   options:  --unit <file>   unit to check instead of container-<name>.service
#             --json          machine-readable findings (for the Kanban automat)
#
# Severity:  FAIL = proven to break (alpine + bash entrypoint, User= in a podman unit,
#                   claude-code in an app image)          -> exit code 1
#            WARN = costs cache, size or robustness        INFO = hint
# Output style follows architektur-review/review.sh. Debug: CHECK_DEBUG=1
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# shellcheck source=lib/common.sh
source "$HERE/lib/common.sh"
source "$HERE/lib/check_containerfile.sh"
source "$HERE/lib/check_unit.sh"
source "$HERE/lib/check_compose.sh"

TARGET="" CONTEXT="" UNIT_OVERRIDE="" ALL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)     ALL=1; shift ;;
        --context) CONTEXT="${2:-}"; shift 2 ;;
        --unit)    UNIT_OVERRIDE="${2:-}"; shift 2 ;;
        --json)    JSON=1; shift ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)        echo "unbekannte Option: $1" >&2; exit 2 ;;
        *)         TARGET="$1"; shift ;;
    esac
done
[[ $ALL -eq 1 || -n "$TARGET" ]] || { echo "Ziel fehlt (Name, Pfad oder --all). -h für Hilfe." >&2; exit 2; }

# Resolve a target into: NAME, DIR (context), CF (Containerfile path or empty)
resolve_target() {
    local t="$1"
    if [[ -f "$t" ]]; then
        CF="$(readlink -f "$t")"; DIR="${CONTEXT:-$(dirname "$CF")}"; NAME="$(basename "$DIR")"
        [[ "$(basename "$CF")" =~ ^(Containerfile|Dockerfile)(\..+)?$ ]] || warn "$NAME" file "Datei heisst nicht Containerfile/Dockerfile: $(basename "$CF")"
    elif [[ -d "$t" ]]; then
        DIR="$(readlink -f "$t")"; NAME="$(basename "$DIR")"; CF="$(find_containerfile "$DIR")"
    elif [[ -d "$HOME/containers/$t" ]]; then
        DIR="$HOME/containers/$t"; NAME="$t"; CF="$(find_containerfile "$DIR")"
    else
        echo "Ziel nicht gefunden: $t (weder Datei, Ordner noch ~/containers/$t)" >&2; return 1
    fi
    [[ -n "$CONTEXT" ]] && DIR="$(readlink -f "$CONTEXT")"
    return 0
}

check_one() {
    header "$NAME" "$DIR"
    if [[ -n "$CF" ]]; then check_containerfile "$NAME" "$CF" "$DIR"
    else warn "$NAME" containerfile "kein Containerfile/Dockerfile in $DIR"; fi
    local unit="$UNIT_OVERRIDE"
    [[ -z "$unit" ]] && unit="$(find_unit "$NAME")"
    check_unit "$NAME" "$unit" "$DIR"
    check_compose "$NAME" "$DIR"
    check_image_size "$NAME"
}

init_findings
load_image_sizes
if [[ $ALL -eq 1 ]]; then
    n=0
    for d in "$HOME"/containers/*/; do
        d="${d%/}"; cf="$(find_containerfile "$d")"; [[ -n "$cf" ]] || continue
        NAME="$(basename "$d")"; DIR="$d"; CF="$cf"; UNIT_OVERRIDE=""
        check_one; n=$((n+1))
    done
    dbg "$n Container geprüft"
else
    resolve_target "$TARGET" || exit 2
    check_one
fi
summary

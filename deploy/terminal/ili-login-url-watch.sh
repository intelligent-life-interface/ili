#!/usr/bin/env bash
# ili-login-url-watch.sh — reads Claude Code's terminal output from stdin and
# writes the OAuth sign-in URL, unbroken, to a file in the terminal home.
#
# Why: the URL is ~450 characters and is drawn across several lines. After a
# tmux re-attach or resize the screen can even show a damaged copy (chunks
# missing — found 22.08.2026). The byte stream that Claude writes is the only
# reliable source, so ili-claude.sh tees it through this script.
#
# Output file: $CLAUDE_CONFIG_DIR/ili-login-url  (the api container mounts the
# terminal home read-only and serves it as GET /api/claude-login-url).
# The file is removed as soon as a stored login exists.
#
# Must consume stdin until EOF, otherwise tee gets SIGPIPE and the TUI breaks.
set -uo pipefail

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/root/.claude}"
OUT="${CLAUDE_CONFIG_DIR}/ili-login-url"
CREDS="${CLAUDE_CONFIG_DIR}/.credentials.json"
# code_challenge and state are base64url of 32 bytes = exactly 43 characters —
# that makes the end of the URL unambiguous.
URL_RE='https://[A-Za-z0-9./_-]+/oauth/authorize\?[A-Za-z0-9%&=._~+-]*code_challenge=[A-Za-z0-9_-]{43}[A-Za-z0-9%&=._~+-]*state=[A-Za-z0-9_-]{43}'

log() { echo "[ili-login-url] $*" >&2; }

mkdir -p "$CLAUDE_CONFIG_DIR" 2>/dev/null || true
rm -f "$OUT"
buf=""
last=""
# -t: a plain `read -n 4096` would block until 4096 bytes or EOF — the login
# screen is smaller than that, so the URL would only be seen when Claude exits.
# On timeout bash keeps the partial input in $chunk (rc > 128).
eof=0
while (( ! eof )); do
    chunk=""
    IFS= read -r -n 4096 -d '' -t 0.5 chunk
    rc=$?
    if (( rc != 0 && rc <= 128 )); then eof=1; fi   # EOF (maybe with a last partial chunk)
    [[ -z "$chunk" ]] && continue
    buf+="$chunk"
    # Strip ANSI/CSI sequences, then remove line breaks so a wrapped URL is
    # contiguous again. Spaces never occur inside the URL.
    clean="$(printf '%s' "$buf" | sed -E $'s/\x1b\\[[0-9;?]*[A-Za-z]//g; s/\x1b[()][A-Za-z0-9]//g; s/\x1b[=>]//g; s/\r//g' | tr -d '\n')"
    url="$(printf '%s' "$clean" | grep -oE "$URL_RE" | tail -1 || true)"
    if [[ -n "$url" && "$url" != "$last" ]]; then
        printf '%s\n' "$url" > "${OUT}.tmp" && mv -f "${OUT}.tmp" "$OUT"
        log "sign-in URL captured (${#url} chars) -> $OUT"
        last="$url"
    fi
    if [[ -f "$CREDS" ]]; then
        rm -f "$OUT"
        log "login stored — URL file removed, draining output"
        cat > /dev/null
        exit 0
    fi
    # Keep only the tail; the URL is < 1 KB, the TUI redraws megabytes.
    if (( ${#buf} > 65536 )); then buf="${buf: -16384}"; fi
done
rm -f "$OUT"

#!/usr/bin/env bash
# entrypoint.sh — starts the ttyd instance that serves all project terminals.
#
# One ttyd instance serves every board: the board slug arrives per connection as
# a URL query (?arg=<slug>, ttyd -a) and is handed to ili-term, which opens a
# tmux session and working directory for that board.
#
# Security model (decision 2026-08-16, option C):
#   * this container publishes no port — ttyd is only reachable inside the
#     compose network, through the authenticated /projterm/ route of `web`
#   * authentication lives in that nginx route (Basic auth + WebSocket cookie),
#     so the shell is never exposed unauthenticated
# Do NOT add a `ports:` entry for this service unless you put your own
# authentication in front of it. A browser terminal is full shell access.
#
# Debug: docker compose logs -f terminal
set -euo pipefail

log() { echo "[ili-terminal] $*" >&2; }

PORT="${TERMINAL_PORT:-7690}"
BASE_PATH="${TERMINAL_BASE_PATH:-/projterm}"
PROJECTS_DIR="${PROJECTS_DIR:-/projects}"
BOARDS_DIR="${BOARDS_DIR:-/boards}"
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/root/.claude}"

log "starting: port=${PORT} base=${BASE_PATH} projects=${PROJECTS_DIR} boards=${BOARDS_DIR}"

# Tolerant on purpose: a read-only or foreign-owned bind mount must not stop the
# terminal from starting — ili-term falls back per connection.
mkdir -p "$PROJECTS_DIR" 2>/dev/null || log "WARN: cannot create ${PROJECTS_DIR}"
mkdir -p "$CLAUDE_CONFIG_DIR" 2>/dev/null || log "WARN: cannot create ${CLAUDE_CONFIG_DIR} — Claude login will not persist"

if [[ -d "$BOARDS_DIR" ]]; then
    log "boards visible: $(find "$BOARDS_DIR" -maxdepth 1 -name '*.json' 2>/dev/null | wc -l) file(s)"
else
    log "WARN: ${BOARDS_DIR} not mounted — every terminal falls back to a generic session"
fi

# Report the Claude authentication state once at startup; it is the single most
# common reason for "the terminal opens but Claude does not run".
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    log "Claude auth: ANTHROPIC_API_KEY from environment"
elif [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    log "Claude auth: CLAUDE_CODE_OAUTH_TOKEN from environment"
elif [[ -f "${CLAUDE_CONFIG_DIR}/.credentials.json" ]]; then
    log "Claude auth: stored login found in ${CLAUDE_CONFIG_DIR}"
else
    log "Claude auth: none yet — the terminal will offer the login flow on first open"
fi

# Sane tmux defaults for a browser terminal (mouse off: touch devices need the
# gestures for scrolling; see docs/PROJECT-TERMINAL.md).
# Written to $HOME instead of a hard-coded /root: the service may be pinned to
# another uid (documented Docker override), and a failed write must not kill the
# start under `set -e`.
if ! cat > "${HOME:-/root}/.tmux.conf" <<'TMUX'
set -g history-limit 10000
set -g mouse off
set -g escape-time 10
# Toggle the mouse per session: prefix + T (needed for copy/paste on desktop)
bind T set mouse
TMUX
then
    log "WARN: cannot write ${HOME:-/root}/.tmux.conf — continuing with tmux defaults"
fi

# -W  writable (without it the terminal is read-only)
# -a  allow the client to pass command arguments via URL query (?arg=<board>)
# -b  base path, so the terminal can be embedded same-origin under /projterm/
# Claude CLI bridge (HTTP in front of the logged-in Claude session). The api
# container needs it for project preparation (CLAUDE.md, tags, idea cards).
# Without it a freshly created project stays an empty template.
BRIDGE_PORT="${BRIDGE_PORT:-8950}"
if command -v python3 >/dev/null 2>&1 && [[ -f /usr/local/bin/claude_cli_bridge.py ]]; then
    log "starting Claude CLI bridge on ${BRIDGE_HOST:-0.0.0.0}:${BRIDGE_PORT}"
    ( while true; do
        python3 /usr/local/bin/claude_cli_bridge.py 2>&1 | sed -u 's/^/[claude-bridge] /' >&2
        log "WARN: Claude CLI bridge exited — restarting in 5s"
        sleep 5
      done ) &
else
    log "ERROR: Claude CLI bridge not available (python3 or script missing) — KI project preparation will FAIL"
fi

exec /usr/local/bin/ttyd \
    -p "$PORT" \
    -W \
    -a \
    -b "$BASE_PATH" \
    -t fontSize=13 \
    -t 'scrollback=10000' \
    -t 'disableLeaveAlert=true' \
    /usr/local/bin/ili-term

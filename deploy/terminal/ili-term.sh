#!/usr/bin/env bash
# ili-term.sh — per-board terminal wrapper, launched by ttyd for each connection.
#
# Usage: ili-term <board-slug>
#   The slug comes from the URL query (?arg=<slug>, ttyd -a). The frontend embeds
#   the terminal as <iframe src="/projterm/?arg=<board>">, so every board gets its
#   own persistent tmux session and its own working directory.
#
# Convention (project = board): the working directory for board <slug> is
# $PROJECTS_DIR/<slug>. It is created on first open, so a new board immediately
# has a place for its code.
#
# Debug: docker compose logs -f terminal
set -euo pipefail

# ttyd runs this script inside a pty, so plain stderr would be drawn into the
# terminal and then cleared by `tmux attach`. Write to PID 1's stdout instead, so
# the decisions below show up in `docker compose logs terminal`.
log() {
    if [ -w /proc/1/fd/1 ]; then
        echo "[ili-term] $*" >> /proc/1/fd/1
    else
        echo "[ili-term] $*" >&2
    fi
}

PROJECTS_DIR="${PROJECTS_DIR:-/projects}"
BOARDS_DIR="${BOARDS_DIR:-/boards}"

RAW="${1:-}"
# Strict allow-list: the slug becomes part of a path and a session name, so
# everything outside [A-Za-z0-9._-] is dropped (path/command injection guard).
SLUG="$(printf '%s' "$RAW" | tr -cd 'A-Za-z0-9._-')"
log "connection: raw='${RAW}' -> slug='${SLUG}'"

# A slug without a board file is not a project — fall back to a generic session
# instead of binding to a phantom board.
if [[ -n "$SLUG" && ! -f "${BOARDS_DIR}/${SLUG}.json" ]]; then
    log "WARN: no board '${SLUG}' in ${BOARDS_DIR} — generic session without board binding"
    SLUG=""
fi

DIR="$PROJECTS_DIR"
if [[ -n "$SLUG" ]]; then
    DIR="${PROJECTS_DIR}/${SLUG}"
    if [[ ! -d "$DIR" ]]; then
        log "creating working directory ${DIR} (project = board)"
        mkdir -p "$DIR" || { log "WARN: cannot create ${DIR} — falling back to ${PROJECTS_DIR}"; DIR="$PROJECTS_DIR"; }
    fi
fi
log "working directory: ${DIR}"

SESSION="proj-${SLUG:-home}"

# 1) Make sure the session exists. Creating it is independent of starting Claude,
#    so an existing session is only re-attached.
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    log "creating tmux session '${SESSION}' in '${DIR}'"
    tmux new-session -d -s "$SESSION" -c "$DIR"
else
    log "tmux session '${SESSION}' already exists — attaching"
fi

# Browser tab title: tmux writes the terminal title, xterm.js turns it into
# document.title — without this every project tab would be named "bash".
tmux set-option -t "$SESSION" set-titles on
# Pass OSC-52 clipboard writes through to the browser — lets Claude's own "c to copy"
# reach the client clipboard instead of dying inside tmux.
tmux set-option -t "$SESSION" set-clipboard on
tmux set-option -t "$SESSION" set-titles-string "📋 ${SLUG:-home} · ili"
tmux set-option -t "$SESSION" status-position top
tmux set-option -t "$SESSION" status-left-length 60
tmux set-option -t "$SESSION" status-left "#[bold] 📋 ${SLUG:-home} #[default]"
tmux set-option -t "$SESSION" status-right "%H:%M"

# 2) Is Claude already running in this session? pane_current_command often shows
#    'bash' although claude runs as its foreground child, so inspect the process
#    tree instead.
claude_runs=0
pane_pid="$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)"
if [[ -n "$pane_pid" ]]; then
    for kid in $(pgrep -P "$pane_pid" 2>/dev/null || true); do
        comm="$(ps -o comm= -p "$kid" 2>/dev/null || true)"
        [[ "$comm" == "claude" || "$comm" == "node" ]] && claude_runs=1
    done
fi

# 3) Start Claude lazily on first open. KANBAN_BOARD is exported into the pane so
#    hooks and scripts inside the session know which board they belong to. SLUG is
#    sanitised above, so it is safe to interpolate.
if [[ "$claude_runs" -eq 0 ]]; then
    log "starting Claude in '${SESSION}' (board='${SLUG}')"
    if [[ -n "$SLUG" ]]; then
        tmux send-keys -t "$SESSION" "cd '${DIR}' 2>/dev/null; export KANBAN_BOARD=${SLUG}; exec ili-claude" Enter
    else
        tmux send-keys -t "$SESSION" "cd '${DIR}' 2>/dev/null; exec ili-claude" Enter
    fi
else
    log "Claude already running in '${SESSION}' — attach only"
fi

# 4) Attach. -d detaches other clients: two clients of different sizes on one
#    session produce garbled output.
log "attaching to '${SESSION}'"
exec tmux attach -d -t "$SESSION"

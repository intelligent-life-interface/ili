#!/usr/bin/env bash
# ili-term.sh — per-board terminal wrapper, launched by ttyd for each connection.
#
# Usage: ili-term <board-slug> [instance]
#   Both come from the URL query (?arg=<slug>&arg=<n>, ttyd -a; verified: ttyd
#   appends every arg= as its own argv entry). The frontend embeds the terminal as
#   <iframe src="/projterm/?arg=<board>&arg=<n>">, so every board gets several
#   persistent tmux sessions in one working directory.
#
#   Instances 1-4 run Claude Code, instance 5 is a plain shell (no Claude) — four
#   assistants and one place to work by hand, per project. Instance 1 keeps the old
#   session name `proj-<slug>`, so sessions created before this existed stay
#   reachable and the heal endpoint and the automat keep finding them.
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

# Instance number. This is user input from the URL, so it is an allow-list and not
# a strip: the value ends up in a tmux session name.
case "${2:-1}" in
    1|2|3|4|5) INSTANCE="${2:-1}" ;;
    *) log "WARN: instance '${2:-}' is not 1-5 — using 1"; INSTANCE=1 ;;
esac

# Session names. Instance 1 must keep the historic name (see header), the others
# get a PREFIX rather than a suffix: a suffix would be ambiguous for board ids that
# themselves end in -<digit> (e.g. "ili-release-0-1-20"), and the slug is parsed
# back out of the session name elsewhere.
case "$INSTANCE" in
    1) SESSION_PREFIX="proj"  ; RUN_CLAUDE=1 ;;
    5) SESSION_PREFIX="shell" ; RUN_CLAUDE=0 ;;
    *) SESSION_PREFIX="proj${INSTANCE}" ; RUN_CLAUDE=1 ;;
esac

DIR="$PROJECTS_DIR"
if [[ -n "$SLUG" ]]; then
    DIR="${PROJECTS_DIR}/${SLUG}"
    if [[ ! -d "$DIR" ]]; then
        log "creating working directory ${DIR} (project = board)"
        mkdir -p "$DIR" || { log "WARN: cannot create ${DIR} — falling back to ${PROJECTS_DIR}"; DIR="$PROJECTS_DIR"; }
    fi
fi
log "working directory: ${DIR}"

# A project folder is a Git repo from day one, otherwise nothing an AI session
# does in there is ever versioned (F-19). Runs on every connection, not just the
# mkdir above: the api container creates the folder itself before anyone opens a
# terminal, so ".git missing" is the real signal, not "folder missing". Restricted
# to the real per-board path ($DIR == $PROJECTS_DIR/$SLUG), not just "$DIR exists":
# the mkdir fallback above can leave DIR == PROJECTS_DIR while SLUG is still set (mkdir
# failed) — git-initing PROJECTS_DIR itself would turn it into one repo that silently
# absorbs every neighbouring project without its own .git. Idempotent and best-effort
# — a git failure must never break the terminal connection.
if [[ -n "$SLUG" && "$DIR" == "${PROJECTS_DIR}/${SLUG}" && ! -d "$DIR/.git" ]] \
        && command -v git >/dev/null 2>&1; then
    log "initializing git repo in ${DIR}"
    if git -C "$DIR" init -q --initial-branch=main 2>/dev/null; then
        if ! git -C "$DIR" config user.name >/dev/null 2>&1; then
            # Neutral placeholder, not a real identity: this folder can be created in
            # any third-party installation, not just here (F-19).
            git -C "$DIR" config user.name "ili" \
                || log "WARN: could not set placeholder git identity in ${DIR} (ignored)"
            git -C "$DIR" config user.email "ili@localhost" \
                || log "WARN: could not set placeholder git identity in ${DIR} (ignored)"
            log "no git identity found anywhere — set a local placeholder (ili/ili@localhost)"
        fi
    else
        log "WARN: git init failed in ${DIR} (ignored)"
    fi
fi

SESSION="${SESSION_PREFIX}-${SLUG:-home}"
log "instance ${INSTANCE} -> session '${SESSION}' (claude: ${RUN_CLAUDE})"

# 1) Make sure the session exists. Creating it is independent of starting Claude,
#    so an existing session is only re-attached.
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    log "creating tmux session '${SESSION}' in '${DIR}'"
    # -u: force UTF-8. tmux guesses from the locale, and a client that guesses
    # wrong renders umlauts and the emoji of card titles as garbage (F-14).
    tmux -u new-session -d -s "$SESSION" -c "$DIR"
else
    log "tmux session '${SESSION}' already exists — attaching"
fi

# Browser tab title: tmux writes the terminal title, xterm.js turns it into
# document.title — without this every project tab would be named "bash".
tmux set-option -t "$SESSION" set-titles on
# Pass OSC-52 clipboard writes through to the browser — lets Claude's own "c to copy"
# reach the client clipboard instead of dying inside tmux.
tmux set-option -t "$SESSION" set-clipboard on
if [[ "$RUN_CLAUDE" -eq 1 ]]; then LABEL="🤖 ${INSTANCE}"; else LABEL="🐚 Shell"; fi
tmux set-option -t "$SESSION" set-titles-string "📋 ${SLUG:-home} · ${LABEL} · ili"
tmux set-option -t "$SESSION" status-position top
tmux set-option -t "$SESSION" status-left-length 60
tmux set-option -t "$SESSION" status-left "#[bold] 📋 ${SLUG:-home} · ${LABEL} #[default]"
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
if [[ "$RUN_CLAUDE" -eq 0 ]]; then
    log "instance ${INSTANCE} is the plain shell — not starting Claude"
elif [[ "$claude_runs" -eq 0 ]]; then
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
exec tmux -u attach -d -t "$SESSION"

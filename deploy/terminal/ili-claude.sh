#!/usr/bin/env bash
# ili-claude.sh — starts Claude Code inside a project terminal and makes the very
# first login as painless as possible.
#
# The container has no browser, so the OAuth callback to localhost cannot work.
# Claude Code handles exactly this case: it prints a URL and a "Paste code here"
# prompt (documented for SSH sessions and containers). This wrapper explains that
# flow before handing over, because a first-time user otherwise sees a login
# screen without knowing that the code has to travel back by copy & paste.
#
# Three ways to authenticate, all optional — without any of them the terminal is
# still a usable shell:
#   1. ANTHROPIC_API_KEY in .env          (Anthropic Console key, no login at all)
#   2. CLAUDE_CODE_OAUTH_TOKEN in .env    (from `claude setup-token`, valid 1 year)
#   3. interactive login in this terminal (subscription, code copied back)
#
# The login is stored in $CLAUDE_CONFIG_DIR and survives restarts as long as the
# terminal volume is kept.
set -uo pipefail

CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/root/.claude}"
BOARD="${KANBAN_BOARD:-}"

# podman-compose 1.0.3 (Debian 12) does not interpolate `${VAR:-}` in the compose
# `environment:` block — the shell then sees the literal string "${ANTHROPIC_API_KEY:-}"
# and Claude Code would try to use it as a key. Drop such placeholders entirely.
for var in ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN; do
    if [[ "${!var:-}" == \$\{* ]]; then
        echo "[ili-claude] ${var} is an unexpanded compose placeholder — ignoring it" >&2
        unset "$var"
    fi
done

has_credentials() {
    [[ -n "${ANTHROPIC_API_KEY:-}" ]] && return 0
    [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] && return 0
    [[ -f "${CLAUDE_CONFIG_DIR}/.credentials.json" ]] && return 0
    return 1
}

if ! has_credentials; then
    cat <<'BANNER'

  ┌─────────────────────────────────────────────────────────────────────┐
  │  Claude is not signed in yet                                        │
  │                                                                     │
  │  This terminal has no browser, so the login takes one extra step:    │
  │                                                                     │
  │  Easiest: the board page opens a sign-in panel with an "Open"        │
  │  button and a code field — no copying at all.                        │
  │                                                                     │
  │  By hand instead:                                                   │
  │   1. Claude prints a sign-in URL below. It may break across lines —  │
  │      join the pieces WITHOUT spaces, or the sign-in page rejects it  │
  │   2. Open it in your own browser and sign in                        │
  │   3. The browser shows a code. Paste it back here at the            │
  │      "Paste code here if prompted" line and press Enter              │
  │                                                                     │
  │  The login is stored and survives restarts.                          │
  │                                                                     │
  │  ⚠️  API costs are yours: All tokens/API costs are billed to you.    │
  │  There is no automatic control — check your limits regularly.       │
  │                                                                     │
  │  Prefer no login at all? Put ANTHROPIC_API_KEY (Anthropic Console)   │
  │  or CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`) into .env and     │
  │  restart the stack.                                                 │
  │                                                                     │
  │  Not interested in AI features? Type  exit  — the shell stays.       │
  └─────────────────────────────────────────────────────────────────────┘

BANNER
fi

if [[ -n "$BOARD" ]]; then
    echo "  Board: ${BOARD}   ·   Working directory: $(pwd)"
    echo
fi

# Hand over to Claude Code. Its own login flow takes it from here.
if ! has_credentials && command -v script >/dev/null 2>&1; then
    # Not signed in: run Claude in a pty via `script` and tee its byte stream
    # through the URL watcher, which writes the sign-in URL unbroken into the
    # terminal home for the GUI panel (see ili-login-url-watch.sh). tee's stdout
    # is still the real terminal, so the TUI behaves normally.
    export CLAUDE_CONFIG_DIR
    cmd="claude"
    for arg in "$@"; do cmd+=" $(printf '%q' "$arg")"; done
    script -q -e -f -c "$cmd" /dev/null \
        | tee >(ili-login-url-watch)
    status=${PIPESTATUS[0]}
else
    claude "$@"
    status=$?
fi
echo
echo "[ili-claude] Claude exited (status ${status}) — you are back in the shell."
echo "[ili-claude] Type  ili-claude  to start it again."
echo
exec bash -l

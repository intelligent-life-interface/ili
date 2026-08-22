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
claude "$@"
status=$?
echo
echo "[ili-claude] Claude exited (status ${status}) — you are back in the shell."
echo "[ili-claude] Type  ili-claude  to start it again."
echo
exec bash -l

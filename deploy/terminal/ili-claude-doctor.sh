#!/usr/bin/env bash
# ili-claude-doctor.sh — makes sure the Claude Code CLI in this container can
# actually start, and repairs it when it cannot.
#
# Why this exists: until 0.1.19 the CLI's self-updater was left on. It upgraded
# itself inside running containers to a version that needs a platform-native
# binary and did not download it, leaving every terminal with
#
#   Error: claude native binary not installed.
#
# and no way to start Claude at all (reported from a 0.1.16 instance on
# 2026-09-18). The updater is off since 0.1.20, but installations that already
# broke themselves keep the damaged files in their container layer — and a
# future npm/packaging change could break an install the same way. So we check
# on every start and repair instead of only documenting a manual fix.
#
# Never fatal: the terminal must come up as a plain shell even without Claude.
set -u

PKG_DIR="${CLAUDE_PKG_DIR:-/usr/local/lib/node_modules/@anthropic-ai/claude-code}"

log() { printf '[claude-doctor] %s\n' "$*" >&2; }

claude_works() {
    command -v claude > /dev/null 2>&1 || return 1
    timeout 60 claude --version > /dev/null 2>&1
}

if claude_works; then
    log "ok: $(timeout 60 claude --version 2>/dev/null | head -1)"
    exit 0
fi

log "Claude does not start — trying to repair"

# 1. The postinstall fetches the platform-native binary. This is the exact step
#    the CLI itself names in its error message.
if [[ -f "$PKG_DIR/install.cjs" ]]; then
    log "running the package postinstall ($PKG_DIR/install.cjs)"
    timeout 300 node "$PKG_DIR/install.cjs" >&2 2>&1 || log "postinstall returned $?"
    if claude_works; then
        log "repaired: $(timeout 60 claude --version 2>/dev/null | head -1)"
        exit 0
    fi
fi

# 2. Reinstall. --allow-scripts is what lets the postinstall run at all on
#    npm >= 12, exactly as the image build does it.
log "reinstalling @anthropic-ai/claude-code"
timeout 600 npm install -g --allow-scripts=@anthropic-ai/claude-code \
    "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION:-latest}" >&2 2>&1 || log "npm install returned $?"

if claude_works; then
    log "repaired: $(timeout 60 claude --version 2>/dev/null | head -1)"
    exit 0
fi

log "FAILED: Claude still does not start. The terminal works as a plain shell;"
log "AI features (project preparation, the automat) will not work."
log "Fastest way out: update ili (docker compose pull && docker compose up -d)."
exit 0

#!/bin/bash
# docker-entrypoint.sh — two jobs:
#
#   1. Subcommands that hand out the compose files baked into the image, so an
#      installation needs neither a clone nor a download (variant A, 2026-08-22):
#        init              write docker-compose.yml, docker-compose.terminal.yml and
#                          .env into /out (mount your folder there); an existing .env
#                          is never overwritten
#        compose           print docker-compose.yml to stdout
#        compose-terminal  print docker-compose.terminal.yml to stdout
#        env               print .env.example to stdout
#        help              this list
#      Works the same with Docker and Podman:
#        docker run --rm -v "$PWD":/out   ghcr.io/toa1984/ili init
#        podman run --rm -v "$PWD":/out:Z ghcr.io/toa1984/ili init
#
#   2. Anything else (the CMD = uvicorn): seed the starter boards, then exec.
#      A fresh installation would otherwise show an empty dashboard. The boards
#      live in a named volume, so the copy happens ONLY while that volume is still
#      empty: an update never writes into an existing installation.
#      What gets copied: demo/boards/*.json — the starter boards plus manifest.json.
#
# Logs go to stderr so `compose > docker-compose.yml` stays clean.
# Debug: docker compose logs api | grep entrypoint
set -e

BOARDS_DIR="${BOARDS_DIR:-/app/boards}"
SEED_DIR="${SEED_DIR:-/app/demo/boards}"
AUTOMAT_STATE_DIR="${AUTOMAT_STATE_DIR:-/opt/ili-automat/state}"

log() { echo "[entrypoint] $*" >&2; }

DIST_DIR="${DIST_DIR:-/app/dist}"
OUT_DIR="${OUT_DIR:-/out}"

usage() {
    cat >&2 <<'USAGE'
ili image — usage:
  init              write docker-compose.yml, docker-compose.terminal.yml, .env into /out
                    (existing .env is kept). Mount your folder:
                      docker run --rm -v "$PWD":/out   ghcr.io/toa1984/ili init
                      podman run --rm -v "$PWD":/out:Z ghcr.io/toa1984/ili init
                    then edit .env (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY) and:
                      docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d
  compose           print docker-compose.yml
  compose-terminal  print docker-compose.terminal.yml
  env               print .env.example
  help              this text
USAGE
}

emit() {
    # $1 = file name inside DIST_DIR — printed to stdout, nothing else.
    if [ ! -f "$DIST_DIR/$1" ]; then
        log "ERROR: $DIST_DIR/$1 missing in this image"
        exit 1
    fi
    cat "$DIST_DIR/$1"
}

do_init() {
    if [ ! -d "$OUT_DIR" ]; then
        log "ERROR: $OUT_DIR is not mounted. Run with:  -v \"\$PWD\":/out   (Podman: -v \"\$PWD\":/out:Z)"
        exit 1
    fi
    if [ ! -w "$OUT_DIR" ]; then
        log "ERROR: $OUT_DIR is not writable (SELinux? add :Z to the -v option)"
        exit 1
    fi
    for f in docker-compose.yml docker-compose.terminal.yml; do
        if [ -f "$OUT_DIR/$f" ]; then
            log "$f exists — replacing with the version from this image"
        fi
        cp "$DIST_DIR/$f" "$OUT_DIR/$f"
        log "wrote $f"
    done
    if [ -f "$OUT_DIR/.env" ]; then
        log ".env exists — keeping it (compare with: ... env > .env.example)"
    else
        cp "$DIST_DIR/.env.example" "$OUT_DIR/.env"
        log "wrote .env (from .env.example — edit ILI_PORT, passwords etc. as needed)"
    fi
    log "done. Next: edit .env (CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY), then:"
    log "  docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d   →  http://localhost:8080"
    log "  (podman: podman-compose -f docker-compose.yml -f docker-compose.terminal.yml up -d)"
}

case "${1:-}" in
    init)             do_init; exit 0 ;;
    compose)          emit docker-compose.yml; exit 0 ;;
    compose-terminal) emit docker-compose.terminal.yml; exit 0 ;;
    env)              emit .env.example; exit 0 ;;
    help|-h|--help)   usage; exit 0 ;;
esac

mkdir -p "$BOARDS_DIR"
mkdir -p "$AUTOMAT_STATE_DIR/workers"

if [ -n "$(ls -A "$BOARDS_DIR" 2>/dev/null)" ]; then
    log "boards directory holds $(ls -1 "$BOARDS_DIR" | wc -l) file(s) — keeping them, no seed"
elif [ ! -d "$SEED_DIR" ]; then
    log "WARN: no starter boards at ${SEED_DIR} — starting with an empty dashboard"
else
    log "boards directory empty — installing starter boards from ${SEED_DIR}"
    if cp "$SEED_DIR"/*.json "$BOARDS_DIR"/; then
        log "copied: $(ls -1 "$BOARDS_DIR" | tr '\n' ' ')"
        # The manifest is the registry; without it the boards exist but stay invisible.
        [ -f "$BOARDS_DIR/manifest.json" ] \
            || log "WARN: manifest.json missing — the boards will not be listed"
    else
        log "WARN: copying the starter boards failed — starting with an empty dashboard"
    fi
fi

exec "$@"

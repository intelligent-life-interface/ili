#!/bin/bash
# docker-entrypoint.sh — seeds the starter boards, then hands over to the CMD.
#
# A fresh installation would otherwise show an empty dashboard. The boards live in
# a named volume, so the copy happens ONLY while that volume is still empty:
# an update (`git pull` + rebuild) never writes into an existing installation.
#
# What gets copied: demo/boards/*.json — the two starter boards plus the
# manifest.json that registers them. Without the manifest the API would not list
# them, so it has to be part of the seed.
#
# Debug: docker compose logs api | grep entrypoint
set -e

BOARDS_DIR="${BOARDS_DIR:-/app/boards}"
SEED_DIR="${SEED_DIR:-/app/demo/boards}"

log() { echo "[entrypoint] $*"; }

mkdir -p "$BOARDS_DIR"

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

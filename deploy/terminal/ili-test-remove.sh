#!/bin/bash
#
# ili-test-remove.sh — Testversion aufräumen (Container, Image, Ordner)
#
# Löscht einen Test-Container und seinen Ordner, ohne ins Original einzugreifen.
# Sicher nur bei Kopien, die mit ili-test-deploy erstellt wurden (marker-geprüft).
#
# Nutzung:
#   ili-test-remove <slug>
#

set -euo pipefail

SLUG="${1:?Fehler: <slug> erforderlich}"
DOCKER_HOST="${DOCKER_HOST:?Fehler: DOCKER_HOST nicht gesetzt (Terminal-Umgebung?)}"
PROJECTS_DIR="${PROJECTS_DIR:-/projects}"

# Hilfsfunktionen
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }
error() { log "❌ ERROR: $*"; exit 1; }
warn() { log "⚠️  WARN: $*"; }
ok() { log "✅ OK: $*"; }

# Sanitize slug
if ! [[ "$SLUG" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    error "ungültiger Projektname"
fi

TEST_NAME="${SLUG}-test"
TEST_PATH="$PROJECTS_DIR/$TEST_NAME"
MARKER=".test-deploy-of"

log "=== ili-test-remove $TEST_NAME ==="

# 1)+2) Container und Image entfernen. Compose-Projekte heissen intern
#    <slug>-test-<service>-1 — "docker rm -f $TEST_NAME" liefe dort ins Leere.
if [[ -f "$TEST_PATH/docker-compose.yml" ]]; then
    log "Stoppe Compose-Projekt $TEST_NAME"
    docker compose -f "$TEST_PATH/docker-compose.yml" -p "$TEST_NAME" down -v --rmi local --remove-orphans 2>/dev/null || log "  (nicht aktiv)"
else
    log "Stoppe Container $TEST_NAME"
    docker rm -f "$TEST_NAME" 2>/dev/null || log "  (nicht aktiv)"
    log "Lösche Image localhost/$TEST_NAME:latest"
    docker rmi -f "localhost/$TEST_NAME:latest" 2>/dev/null || log "  (nicht vorhanden)"
fi

# 3) Test-Ordner nur löschen, falls Marker vorhanden ist (Schutz vor Versehentlichem)
if [[ -d "$TEST_PATH" ]]; then
    if [[ -f "$TEST_PATH/$MARKER" ]]; then
        log "Lösche Test-Ordner: $TEST_PATH"
        rm -rf "$TEST_PATH"
        ok "Test-Ordner gelöscht"
    else
        warn "$TEST_PATH existiert, aber Marker fehlt — kein test-deploy-Ordner"
        warn "  Lösche Ordner nicht aus Sicherheit (könnte ein echter Projektordner sein)"
        exit 1
    fi
else
    log "Test-Ordner nicht vorhanden"
fi

ok "=== ili-test-remove $TEST_NAME abgeschlossen ==="
exit 0

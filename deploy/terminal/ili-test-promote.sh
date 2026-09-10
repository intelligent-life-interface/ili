#!/bin/bash
#
# ili-test-promote.sh — geprüfte Testversion als Produktion übernehmen
#
# Schreibt die Änderungen aus einem erfolgreich getesteten Container-Projekt zurück ins Original.
# Workflow mit Team-Flow (git-auto-Commit, .autocommit-protect-main beachten):
#   1. Testversion läuft (`ili-test-deploy`)
#   2. Änderungen prüfen/testen
#   3. `ili-test-promote <slug>` — schreibt Änderungen als Commit/PR zurück
#   4. Testcontainer räumt sich selbst auf
#
# Nutzung:
#   ili-test-promote <slug> [--message "custom commit message"]
#
# Exit-Codes:
#   0   — erfolgreich übernommen und zurückgeschrieben
#   1   — Fehler (keine Testversion, git fehlgeschlagen, etc.)
#

set -euo pipefail

SLUG="${1:?Fehler: <slug> erforderlich}"
shift
COMMIT_MSG=""
if [[ "${1:-}" == "--message" ]]; then
    COMMIT_MSG="${2:?Fehler: --message erfordert einen Text}"
fi
DOCKER_HOST="${DOCKER_HOST:?Fehler: DOCKER_HOST nicht gesetzt (Terminal-Umgebung?)}"
PROJECTS_DIR="${PROJECTS_DIR:-/projects}"

# Hilfsfunktionen
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }
error() { log "❌ ERROR: $*"; exit 1; }
warn() { log "⚠️  WARN: $*"; }
ok() { log "✅ OK: $*"; }

# Sanitize slug
if ! [[ "$SLUG" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    error "ungültiger Projektname (nur alphanumerisch, Bindestrich, Unterstrich erlaubt)"
fi

PROD_PATH="$PROJECTS_DIR/$SLUG"
TEST_NAME="${SLUG}-test"
TEST_PATH="$PROJECTS_DIR/$TEST_NAME"
MARKER=".test-deploy-of"

log "=== ili-test-promote $SLUG: Testversion übernehmen ==="

# 1) Validierung: Testversion muss existieren und ein Marker haben
if [[ ! -d "$TEST_PATH" ]]; then
    error "keine Testversion gefunden: $TEST_PATH"
fi
if [[ ! -f "$TEST_PATH/$MARKER" ]]; then
    error "$TEST_PATH hat keinen Marker — nicht aus test-deploy (Abbruch)"
fi
if [[ ! -d "$PROD_PATH" ]]; then
    error "Original-Projekt nicht gefunden: $PROD_PATH"
fi

# 2) Testversion stoppt/entfernt den Container
#    Compose-Projekte heissen intern <slug>-test-<service>-1 — "docker rm -f
#    $TEST_NAME" liefe dort ins Leere, darum über docker-compose.yml erkennen.
log "Stoppet Testcontainer $TEST_NAME"
if [[ -f "$TEST_PATH/docker-compose.yml" ]]; then
    docker compose -f "$TEST_PATH/docker-compose.yml" -p "$TEST_NAME" down -v --rmi local --remove-orphans 2>/dev/null || true
else
    docker rm -f "$TEST_NAME" 2>/dev/null || true
    docker rmi -f "localhost/$TEST_NAME:latest" 2>/dev/null || true
fi

# 3) Diff anzeigen: Welche Dateien haben sich geändert?
log "Diff: Geänderte Dateien"
echo "---"
if diff -rq "$PROD_PATH" "$TEST_PATH" 2>/dev/null || true; then
    :
fi
echo "---"

# 4) Änderungen zurückschreiben (rsync): Testversion → Original
#    Ausnahmen: .git-Metadaten, Test-Marker, __pycache__, *.pyc
log "Schreibe Änderungen zurück: $TEST_PATH → $PROD_PATH"
rsync -a --delete \
    --exclude=.git \
    --exclude="$MARKER" \
    --exclude=__pycache__ \
    --exclude="*.pyc" \
    "$TEST_PATH/" "$PROD_PATH/" || error "rsync fehlgeschlagen"
ok "Änderungen zurückgeschrieben"

# 5) Git-Commit (falls das Projekt ein Repo ist)
if [[ -d "$PROD_PATH/.git" ]]; then
    cd "$PROD_PATH"

    # Status prüfen
    if ! git diff-index --quiet HEAD --; then
        log "Git-Diff erkannt — committe Änderungen"

        # Custom message oder Auto-Message
        if [[ -n "$COMMIT_MSG" ]]; then
            MSG="$COMMIT_MSG"
        else
            MSG="test-promote($SLUG): Testversion übernommen — $(date -u +%Y-%m-%d_%H:%M:%S_UTC)"
        fi

        git add -A
        git commit -m "$MSG" || warn "git commit hatte kein-EOF-Status (möglich: nothing to commit)"
        ok "Commit: $MSG"
    else
        log "Keine Unterschiede zum HEAD — skip commit"
    fi

    # Push vorbereiten (git-auto wird es aufpicken, falls .autocommit-protect-main gesetzt)
    log "Git-Status nach Commit:"
    git log --oneline -3 || true
    cd - >/dev/null
else
    log "Keine git-Repo — keine Commits geschrieben"
fi

# 6) Testcontainer räumt auf
log "Räume Testversion auf: $TEST_PATH"
rm -rf "$TEST_PATH"
ok "Testversion gelöscht"

# 7) Zusammenfassung
ok "=== ili-test-promote $SLUG erfolgreich abgeschlossen ==="
log "Änderungen ins Original zurückgeschrieben"
log "Nächster Schritt: Überprüfe '$PROD_PATH' und pushe bei Bedarf"
exit 0

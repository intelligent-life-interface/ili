#!/bin/bash
#
# ili-test-deploy.sh — Projekt-Container in der Sandbox testen
#
# Portierung der Home-Server-Mechanik "Testversion zuerst" (test_deploy.py) in den ili-Stack.
# Baut ein Projekt aus /projects/<slug> neu und startet es als <slug>-test auf einem Port
# in der Sandbox (Gateway 8100–8119).
#
# Nutzung:
#   ili-test-deploy <slug> [<api-path>]
#
# Beispiele:
#   ili-test-deploy my-project              # health-check prüft /api/health
#   ili-test-deploy my-project /api/status  # health-check prüft /api/status
#
# Exit-Codes:
#   0   — erfolgreich gestartet und health-check bestanden
#   1   — Fehler (ungültig, existiert nicht, build fehlgeschlagen, etc.)
#   2   — health-check timeout/fehlgeschlagen
#

set -euo pipefail

SLUG="${1:?Fehler: <slug> erforderlich}"
API_PATH="${2:-/api/health}"
PORT_BASE=8100
PORT_MAX=8119
DOCKER_HOST="${DOCKER_HOST:?Fehler: DOCKER_HOST nicht gesetzt (Terminal-Umgebung?)}"
PROJECTS_DIR="${PROJECTS_DIR:-/projects}"

# Hilfsfunktionen
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }
error() { log "❌ ERROR: $*"; exit 1; }
warn() { log "⚠️  WARN: $*"; }
ok() { log "✅ OK: $*"; }

# Sanitize slug: nur alphanumerisch, Bindestrich, Unterstrich, keine Leerzeichen/Sonderzeichen
if ! [[ "$SLUG" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    error "ungültiger Projektname (nur alphanumerisch, Bindestrich, Unterstrich erlaubt)"
fi

PROD_PATH="$PROJECTS_DIR/$SLUG"
TEST_NAME="${SLUG}-test"
TEST_PATH="$PROJECTS_DIR/$TEST_NAME"
MARKER=".test-deploy-of"

# Zielhost fürs Health-Check-curl: Sandbox-Modus (DOCKER_HOST=tcp://sandbox:2376)
# veröffentlicht Ports auf dem DinD-Dienst selbst, nicht auf "localhost" des
# Terminal-Containers — vgl. docker-compose.sandbox.yml + deploy/gateway/
# 10-generate-streams.sh (TARGET_HOST=sandbox). Hostdocker-Modus (DOCKER_HOST=
# unix://…) hat keinen Gateway; von hier aus ist der Host nicht garantiert
# erreichbar (bekannte Lücke, kein extra_hosts-Eintrag) — Fallback localhost.
case "$DOCKER_HOST" in
    tcp://*)
        TARGET_HOST="${DOCKER_HOST#tcp://}"
        TARGET_HOST="${TARGET_HOST%%:*}"
        ;;
    *)
        TARGET_HOST="localhost"
        warn "DOCKER_HOST ist kein tcp://-Ziel (Hostdocker-Modus) — Health-Check gegen" \
             "localhost kann fehlschlagen, falls der Host von hier nicht erreichbar ist"
        ;;
esac

# Findet den ersten freien Port im Range, anhand ALLER aktuell laufenden Container
# (nicht nur $TEST_NAME — der existiert beim ersten Aufruf noch gar nicht).
find_free_port() {
    local port used_ports
    used_ports="$(docker ps --format '{{.Ports}}' 2>/dev/null || true)"
    for port in $(seq "$PORT_BASE" "$PORT_MAX"); do
        if ! grep -q ":${port}->" <<<"$used_ports"; then
            echo "$port"
            return 0
        fi
    done
    error "Kein freier Port in Range $PORT_BASE–$PORT_MAX"
}

# Räumt eine (evtl. vorhandene) Testversion auf — Compose- und Run-Modus
# unterscheiden sich im Container-Namen (Compose: <slug>-test-<service>-1),
# darum entscheidet die Anwesenheit von docker-compose.yml im jeweiligen Pfad.
cleanup_test_container() {
    local path="$1"
    if [[ -f "$path/docker-compose.yml" ]]; then
        docker compose -f "$path/docker-compose.yml" -p "$TEST_NAME" down -v --remove-orphans 2>/dev/null || true
    else
        docker rm -f "$TEST_NAME" 2>/dev/null || true
    fi
}

log "=== ili-test-deploy $SLUG → $TEST_NAME ==="

# 1) Validierung: Prod-Projekt muss existieren
if [[ ! -d "$PROD_PATH" ]]; then
    error "Projekt nicht gefunden: $PROD_PATH"
fi
log "Projekt: $PROD_PATH"

# 2) Cleanup alte Testversion (falls vorhanden)
if [[ -d "$TEST_PATH" ]]; then
    log "Alte Testversion räume auf: $TEST_PATH"
    cleanup_test_container "$TEST_PATH"
    rm -rf "$TEST_PATH"
fi

# 3) Kopie des Projekts (rsync, Code + .git — git pull unten braucht das Repo)
log "Kopiere Projekt → $TEST_PATH"
rsync -a --delete \
    --exclude=__pycache__ \
    --exclude="*.pyc" \
    "$PROD_PATH/" "$TEST_PATH/" || error "rsync fehlgeschlagen"
log "Kopie erfolgreich"

# 4) Marker setzen (Schutz vor Löschen von Hand erstellter Ordner)
echo "$SLUG" > "$TEST_PATH/$MARKER"

# 5) Neue Version holen (falls git-Repo)
if [[ -d "$TEST_PATH/.git" ]]; then
    log "Neue Version holen (git pull)"
    cd "$TEST_PATH"
    # Nicht fatal: kein Tracking-Branch, kein TTY für Credentials, oder
    # abweichende Historie sind im Container der Normalfall, kein Abbruchgrund
    # (der Testlauf soll mit dem kopierten Arbeitsstand weitermachen können).
    git pull --ff-only 2>&1 | sed 's/^/  /' || warn "git pull fehlgeschlagen — verwende kopierten Arbeitsstand"
    cd - >/dev/null
else
    log "Kein git-Repo — verwende Arbeitsstand"
fi

# 6) Build: Dockerfile/Containerfile prüfen
BUILD_CONTEXT="."
if [[ -d "$TEST_PATH/src" ]]; then
    BUILD_CONTEXT="src"
fi

if [[ ! -f "$TEST_PATH/$BUILD_CONTEXT/Dockerfile" ]] && [[ ! -f "$TEST_PATH/$BUILD_CONTEXT/Containerfile" ]]; then
    warn "Kein Dockerfile/Containerfile gefunden — verwende vordefiniertes Image"
else
    log "Build-Kontext: $BUILD_CONTEXT"
    log "Baue Image: localhost/$TEST_NAME:latest"
    docker build -t "localhost/$TEST_NAME:latest" "$TEST_PATH/$BUILD_CONTEXT" 2>&1 | sed 's/^/  /'
fi

# 7) Starten: docker-compose.yml aus dem Projekt verwenden, falls vorhanden,
#    sonst generischer docker run. Der Port wird je nach Modus unterschiedlich
#    bestimmt (siehe unten) — Compose entscheidet über die eigenen Port-Mappings,
#    ein vorab reservierter Port würde dort ohnehin ignoriert.
COMPOSE_FILE="$TEST_PATH/docker-compose.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
    TEST_PORT=$(find_free_port)
    log "Port reserviert: $TEST_PORT"
    warn "Kein docker-compose.yml gefunden — verwende generisches Image"
    log "Starten: docker run --name=$TEST_NAME -p $TEST_PORT:80 $TEST_NAME:latest"
    docker run -d --name "$TEST_NAME" \
        -v "$TEST_PATH":/app:ro,z \
        -p "$TEST_PORT:80" \
        "localhost/$TEST_NAME:latest" \
        2>&1 | sed 's/^/  /' || error "docker run fehlgeschlagen"
else
    log "Verwende docker-compose.yml aus Projekt"
    docker compose -f "$COMPOSE_FILE" \
        -p "$TEST_NAME" \
        --profile test \
        up -d \
        2>&1 | sed 's/^/  /' || error "docker compose up fehlgeschlagen"

    # Compose entscheidet selbst über Port-Mappings — den tatsächlich belegten
    # Host-Port am ersten gestarteten Container ablesen statt zu raten.
    # `|| true` on each pipeline: `head -1` closing its stdin early can send the
    # producer a SIGPIPE (exit 141), which set -o pipefail would otherwise turn
    # into an unwanted script-abort here.
    CID="$(docker compose -f "$COMPOSE_FILE" -p "$TEST_NAME" ps -q | head -1 || true)"
    [[ -n "$CID" ]] || error "docker compose hat keinen Container gestartet"
    TEST_PORT="$(docker port "$CID" 2>/dev/null | head -1 | grep -oE '[0-9]+$' || true)"
    [[ -n "$TEST_PORT" ]] || error "Kein veröffentlichter Port am Compose-Container gefunden"
    log "Port aus Compose übernommen: $TEST_PORT"
fi

# 8) Health-Check: echten API-Pfad abfragen (nicht nur Startseite)
log "Health-Check: GET http://$TARGET_HOST:$TEST_PORT$API_PATH"
max_attempts=30
attempt=1
while [[ $attempt -le $max_attempts ]]; do
    if curl -sf "http://$TARGET_HOST:$TEST_PORT$API_PATH" >/dev/null 2>&1; then
        ok "Health-Check bestanden (Versuch $attempt/$max_attempts)"
        break
    fi
    if [[ $attempt -eq $max_attempts ]]; then
        log "❌ ERROR: Health-Check fehlgeschlagen nach $max_attempts Versuchen"
        cleanup_test_container "$TEST_PATH"
        rm -rf "$TEST_PATH"
        exit 2
    fi
    log "Versuch $attempt/$max_attempts… warte 2s"
    sleep 2
    ((attempt++))
done

ok "=== Testcontainer läuft auf Port $TEST_PORT (durch Gateway: http://localhost:$TEST_PORT) ==="
ok "Ladezeit: $(TZ=UTC date -u +%H:%M:%S)"
echo "=== Container-Logs (letzte 20 Zeilen) ==="
if [[ -f "$COMPOSE_FILE" ]]; then
    docker compose -f "$COMPOSE_FILE" -p "$TEST_NAME" logs --tail 20 2>&1 || true
else
    docker logs "$TEST_NAME" 2>&1 | tail -20 || true
fi

ok "Fertig. Nächster Schritt: ili-test-promote $SLUG (oder ili-test-remove $SLUG)"
exit 0

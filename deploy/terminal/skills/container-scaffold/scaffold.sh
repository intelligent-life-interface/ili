#!/usr/bin/env bash
# container-scaffold — Neues Homeserver-Container-Projekt vollständig aufsetzen
#
# Erstellt nach dem Muster der bestehenden Home-Stack-Container (Vorbild: camtimport):
#   ~/containers/<name>/           Projektordner
#     app/main.py                  FastAPI-Gerüst mit Debug-Logging + /health
#     requirements.txt
#     Containerfile                python:3.12-slim, uvicorn :8000
#     CLAUDE.md                    Sub-Doku mit Tags:-Zeile (für Root-Index + Router-Skill)
#   ~/.config/systemd/user/container-<name>.service   (rootless Podman, KEIN User=!)
#
# Optional: Kanban-Board via create_project/kanban_sync erstellen, Image bauen + starten.
#
# Usage:
#   scaffold.sh <name> [--port <hostport>] [--desc "Beschreibung"] [--tags "tag1, tag2"]
#                      [--network monitoring] [--volume <hostdir>] [--no-board] [--build]
#   scaffold.sh --suggest-port          # nur freien Port im 88xx-Bereich vorschlagen
#
# Sicherheit: bricht ab, wenn Projektordner oder systemd-Unit schon existieren.

set -euo pipefail

log()  { echo "[scaffold $(date +%H:%M:%S)] $*"; }
err()  { echo "[scaffold FEHLER] $*" >&2; exit 1; }

UNIT_DIR="$HOME/.config/systemd/user"
BASE_DIR="$HOME/containers"

# ---------- Port-Hilfen ----------
port_in_use() {
    local p="$1"
    # 1) aktuell lauschende Ports
    ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}\$" && return 0
    # 2) in systemd-Units publizierte Ports (auch gestoppte Container)
    grep -rhoE -- '-p [0-9.:]*[0-9]+:[0-9]+' "$UNIT_DIR" 2>/dev/null \
        | grep -oE '[0-9]+:' | tr -d ':' | grep -qx "$p" && return 0
    # 3) Root-CLAUDE.md Container-Tabelle
    grep -qE "\b${p}(→|:| )" "$HOME/CLAUDE.md" 2>/dev/null && return 0
    return 1
}

suggest_port() {
    local p
    for p in $(seq 8801 8899); do
        if ! port_in_use "$p"; then echo "$p"; return 0; fi
    done
    err "Kein freier Port im Bereich 8801-8899 gefunden."
}

# ---------- Argumente ----------
if [[ "${1:-}" == "--suggest-port" ]]; then
    suggest_port; exit 0
fi

NAME="${1:-}"
[[ -n "$NAME" ]] || err "Usage: scaffold.sh <name> [--port N] [--desc \"...\"] [--tags \"...\"] [--network monitoring] [--volume DIR] [--no-board] [--build]"
[[ "$NAME" =~ ^[a-z][a-z0-9-]*$ ]] || err "Name '$NAME' ungültig — nur Kleinbuchstaben, Ziffern, Bindestriche."
shift

PORT="" DESC="" TAGS="" NETWORK="" VOLUME="" MAKE_BOARD=1 DO_BUILD=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)     PORT="$2"; shift 2 ;;
        --desc)     DESC="$2"; shift 2 ;;
        --tags)     TAGS="$2"; shift 2 ;;
        --network)  NETWORK="$2"; shift 2 ;;
        --volume)   VOLUME="$2"; shift 2 ;;
        --no-board) MAKE_BOARD=0; shift ;;
        --build)    DO_BUILD=1; shift ;;
        *) err "Unbekannte Option: $1" ;;
    esac
done

PROJ_DIR="$BASE_DIR/$NAME"
UNIT_FILE="$UNIT_DIR/container-$NAME.service"
DESC="${DESC:-$NAME (TODO: Beschreibung)}"
TAGS="${TAGS:-$NAME}"

# ---------- Vorprüfungen ----------
[[ -e "$PROJ_DIR" ]]  && err "Projektordner existiert schon: $PROJ_DIR — nichts überschrieben."
[[ -e "$UNIT_FILE" ]] && err "systemd-Unit existiert schon: $UNIT_FILE — nichts überschrieben."

if [[ -z "$PORT" ]]; then
    PORT="$(suggest_port)"
    log "Kein --port angegeben → freier Port vorgeschlagen: $PORT"
elif port_in_use "$PORT"; then
    err "Port $PORT ist belegt (ss/Units/CLAUDE.md). Frei wäre z.B.: $(suggest_port)"
fi

SESSION_ID="$(uuidgen)"

log "Erstelle Projekt '$NAME' → $PROJ_DIR (Host-Port $PORT → Container 8000)"

# ---------- Projektstruktur ----------
mkdir -p "$PROJ_DIR/app"

cat > "$PROJ_DIR/requirements.txt" <<'EOF'
fastapi
uvicorn[standard]
EOF
log "requirements.txt geschrieben"

cat > "$PROJ_DIR/app/main.py" <<EOF
#!/usr/bin/env python3
"""$NAME – $DESC"""
import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("$NAME")

app = FastAPI(title="$NAME")


@app.get("/health")
def health():
    log.debug("Health-Check aufgerufen")
    return {"status": "ok", "service": "$NAME"}


@app.get("/", response_class=HTMLResponse)
def index():
    log.debug("Index aufgerufen")
    return "<h1>$NAME</h1><p>$DESC</p>"
EOF
log "app/main.py geschrieben (FastAPI + Debug-Logging + /health)"

cat > "$PROJ_DIR/app/healthcheck.py" <<'EOF'
#!/usr/bin/env python3
"""Container healthcheck: exit 0 only if the API answers on /health (no curl in python-slim).
Used by the Containerfile HEALTHCHECK (Docker/Compose) and by --health-cmd in the
systemd unit (Podman ignores HEALTHCHECK from OCI builds). Rules: skill container-architektur."""
import sys
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=4) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
    print(f"healthcheck failed: {exc}", file=sys.stderr)
    sys.exit(1)
EOF
log "app/healthcheck.py geschrieben"

cat > "$PROJ_DIR/Containerfile" <<EOF
# $NAME – $DESC
# Build:  podman build -t $NAME ~/containers/$NAME
# Run:    systemctl --user start container-$NAME.service   (Port $PORT → 8000)
# Layer order per skill container-architektur: base → deps → code → metadata.
FROM docker.io/library/python:3.12-slim

WORKDIR /app
# dependencies first: code changes must not rebuild this layer
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

EXPOSE 8000
# for Docker/Compose users; Podman (OCI build) ignores this → --health-cmd in the unit
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
    CMD ["python3", "/app/healthcheck.py"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF
log "Containerfile geschrieben (Regeln: container-architektur)"

cat > "$PROJ_DIR/CLAUDE.md" <<EOF
# $NAME

**Tags:** $TAGS

## Übersicht
$DESC

- **Port:** $PORT (Host) → 8000 (Container), Image \`localhost/$NAME:latest\`
- **Service:** \`container-$NAME.service\` (systemd user, rootless Podman)
- **Pfad:** \`~/containers/$NAME/\`
- **Claude-Session:** \`claude --session-id $SESSION_ID -n "$NAME"\` (einmaliger erster Start) — danach immer \`claude --resume $SESSION_ID\`

## Architektur
FastAPI-App in \`app/main.py\`, Debug-Logging aktiv, Health-Check unter \`/health\`.

## Nächste Schritte
- Funktionalität implementieren (pro Funktion eine Datei)
- Doku hier ergänzen, Root-CLAUDE.md-Tabelle + Router-Skill aktuell halten

## Befehle
\`\`\`bash
podman build -t $NAME ~/containers/$NAME
systemctl --user restart container-$NAME.service
podman logs --tail 50 $NAME
curl -s localhost:$PORT/health
\`\`\`
EOF
log "CLAUDE.md geschrieben (mit Tags:-Zeile)"

# ---------- systemd-Unit (Muster: camtimport; KEIN User= — sonst 216/GROUP!) ----------
NET_LINE=""
[[ -n "$NETWORK" ]] && NET_LINE="	--network=$NETWORK \\
"
VOL_LINE=""
[[ -n "$VOLUME" ]] && VOL_LINE="	-v $VOLUME:/data:Z \\
"

mkdir -p "$UNIT_DIR"
cat > "$UNIT_FILE" <<EOF
# container-$NAME.service
# $NAME – $DESC (FastAPI), Port $PORT
[Unit]
Description=Podman container-$NAME.service
Wants=network-online.target
After=network-online.target
RequiresMountsFor=%t/containers

[Service]
Environment=PODMAN_SYSTEMD_UNIT=%n
Restart=on-failure
TimeoutStopSec=70
Type=notify
NotifyAccess=all
ExecStart=/usr/bin/podman run \\
	--cidfile=%t/%n.ctr-id \\
	--cgroups=no-conmon \\
	--rm \\
	--sdnotify=conmon \\
	--replace \\
	-d \\
	--name $NAME \\
	--memory=512m \\
	--cpus=1.0 \\
	--health-cmd "python3 /app/healthcheck.py" \\
	--health-interval=30s \\
	--health-retries=3 \\
	--health-start-period=10s \\
${NET_LINE}${VOL_LINE}	-p $PORT:8000 \\
	localhost/$NAME:latest
ExecStop=/usr/bin/podman stop \\
	--ignore -t 10 \\
	--cidfile=%t/%n.ctr-id
ExecStopPost=/usr/bin/podman rm \\
	-f \\
	--ignore -t 10 \\
	--cidfile=%t/%n.ctr-id

[Install]
WantedBy=default.target
EOF
log "systemd-Unit geschrieben: $UNIT_FILE"

# ---------- Kanban-Board ----------
if [[ "$MAKE_BOARD" -eq 1 ]]; then
    log "Erstelle Kanban-Board via create_project/kanban_sync ..."
    if python3 - "$NAME" "$PROJ_DIR/CLAUDE.md" <<'PYEOF'
import sys
sys.path.insert(0, __import__("pathlib").Path.home().joinpath("Projekte/create_project").as_posix())
from pathlib import Path
from kanban_sync import sync_claude_md_to_board
name, md = sys.argv[1], Path(sys.argv[2])
sync_claude_md_to_board(name, md.read_text(encoding="utf-8"))
print(f"Board '{name}' gesynct.")
PYEOF
    then
        log "Kanban-Board erstellt/gesynct: $NAME"
    else
        log "WARNUNG: Board-Sync fehlgeschlagen — manuell im Dashboard nachholen."
    fi
fi

# ---------- Build + Start ----------
if [[ "$DO_BUILD" -eq 1 ]]; then
    log "Baue Image localhost/$NAME:latest ..."
    podman build -t "$NAME" "$PROJ_DIR"
    systemctl --user daemon-reload
    log "Starte container-$NAME.service ..."
    systemctl --user start "container-$NAME.service"
    sleep 2
    curl -sf "localhost:$PORT/health" && echo || log "WARNUNG: Health-Check noch nicht erreichbar."
else
    systemctl --user daemon-reload
fi

# ---------- Regel-Check (Skill container-architektur) ----------
CHECK="$HOME/.claude/skills/container-architektur/container-check.sh"
if [[ -x "$CHECK" ]]; then
    log "Prüfe das neue Projekt gegen die Container-Regeln ..."
    "$CHECK" "$NAME" || log "WARNUNG: container-check meldet FAIL — vor dem Deploy beheben."
else
    log "Hinweis: container-check.sh nicht gefunden ($CHECK) — Skill container-architektur verlinken (skill-link.sh --all)."
fi

# ---------- Checkliste ----------
cat <<EOF

============================================================
FERTIG: $PROJ_DIR  (Port $PORT → 8000)

Erster Einstieg in dieses Projekt:
  claude --session-id $SESSION_ID -n "$NAME"
Danach immer:
  claude --resume $SESSION_ID

Noch zu tun (Claude übernimmt das üblicherweise direkt):
1. ~/containers/CONTAINERS.md — Zeile ergänzen (Root-CLAUDE.md nur für die 6 Kern-Container):
| \`$NAME\` | \`localhost/$NAME:latest\` | $PORT→8000 | $DESC; → \`~/containers/$NAME/CLAUDE.md\` |
2. Router: Zeile in ~/.claude/skills/homeserver-projekte/projects.tsv
   ($NAME<TAB>~/containers/$NAME/CLAUDE.md<TAB>$TAGS) und dann
   python3 ~/.claude/skills/homeserver-projekte/build_index.py
4. Build+Start (falls nicht --build):
   podman build -t $NAME ~/containers/$NAME && systemctl --user start container-$NAME.service
5. Git-Repo (privat!): gh repo create <GITHUB_USER>/$NAME --private   (Token: GH_ADMIN_TOKEN)
============================================================
EOF

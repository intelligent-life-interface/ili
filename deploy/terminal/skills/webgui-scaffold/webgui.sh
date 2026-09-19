#!/usr/bin/env bash
# webgui-scaffold — WebGUI-Boilerplate (Navbar/Tabs, Karten, API-Helfer) für ein Container-Projekt
#
# Legt in <projekt>/app/static/ die Dateien index.html, style.css, app.js an
# (Home-Stack-Stil: Gradient-Header, Tabs, Karten, Status-Footer, Dark-Mode)
# und sorgt dafür, dass main.py die Static-Files ausliefert.
#
# Usage:
#   webgui.sh <name> [--title "Titel"] [--desc "Beschreibung"] [--tabs "Übersicht,Daten,Einstellungen"]
#                    [--dir <app-verzeichnis>]     # Default: ~/containers/<name>/app
#                    [--full [--port N] [--tags "..."]]  # ruft vorher container-scaffold auf
#
# main.py-Regel:
#   - fehlt          → wird aus Template erstellt
#   - unverändertes container-scaffold-Gerüst → wird ersetzt (Backup main.py.bak-webgui)
#   - eigener Code   → bleibt unangetastet, Skript druckt den StaticFiles-Snippet zum Einbauen
#
# Überschreibt NIE vorhandene static/-Dateien.

set -euo pipefail

log() { echo "[webgui $(date +%H:%M:%S)] $*"; }
err() { echo "[webgui FEHLER] $*" >&2; exit 1; }

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="$SKILL_DIR/templates"
SCAFFOLD="$HOME/.claude/skills/container-scaffold/scaffold.sh"

NAME="${1:-}"
[[ -n "$NAME" ]] || err "Usage: webgui.sh <name> [--title ...] [--desc ...] [--tabs \"A,B,C\"] [--dir PATH] [--full [--port N] [--tags ...]]"
[[ "$NAME" =~ ^[a-z][a-z0-9-]*$ ]] || err "Name '$NAME' ungültig — nur Kleinbuchstaben, Ziffern, Bindestriche."
shift

TITLE="" DESC="" TABS="Übersicht" APP_DIR="" FULL=0 PORT="" TAGS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --title) TITLE="$2"; shift 2 ;;
        --desc)  DESC="$2"; shift 2 ;;
        --tabs)  TABS="$2"; shift 2 ;;
        --dir)   APP_DIR="$2"; shift 2 ;;
        --full)  FULL=1; shift ;;
        --port)  PORT="$2"; shift 2 ;;
        --tags)  TAGS="$2"; shift 2 ;;
        *) err "Unbekannte Option: $1" ;;
    esac
done

TITLE="${TITLE:-$NAME}"
DESC="${DESC:-$TITLE}"
APP_DIR="${APP_DIR:-$HOME/containers/$NAME/app}"

# ---------- Optional: Basis-Projekt via container-scaffold ----------
if [[ "$FULL" -eq 1 ]]; then
    [[ -x "$SCAFFOLD" ]] || err "container-scaffold nicht gefunden: $SCAFFOLD"
    log "Rufe container-scaffold für '$NAME' auf ..."
    ARGS=("$NAME" --desc "$DESC")
    [[ -n "$PORT" ]] && ARGS+=(--port "$PORT")
    [[ -n "$TAGS" ]] && ARGS+=(--tags "$TAGS")
    "$SCAFFOLD" "${ARGS[@]}"
fi

[[ -d "$APP_DIR" ]] || err "App-Verzeichnis fehlt: $APP_DIR — erst Projekt anlegen (container-scaffold oder --full)."
STATIC_DIR="$APP_DIR/static"
[[ -e "$STATIC_DIR/index.html" ]] && err "static/index.html existiert schon in $STATIC_DIR — nichts überschrieben."
mkdir -p "$STATIC_DIR"

log "Erzeuge WebGUI in $STATIC_DIR (Tabs: $TABS)"

# ---------- Templating (python3: robust bei Umlauten/Mehrzeilern) ----------
export WG_NAME="$NAME" WG_TITLE="$TITLE" WG_DESC="$DESC" WG_TABS="$TABS" \
       WG_TPL="$TPL" WG_STATIC="$STATIC_DIR"
python3 <<'PYEOF'
import os, re, unicodedata
from pathlib import Path

name, title, desc = os.environ["WG_NAME"], os.environ["WG_TITLE"], os.environ["WG_DESC"]
tabs = [t.strip() for t in os.environ["WG_TABS"].split(",") if t.strip()]
tpl, static = Path(os.environ["WG_TPL"]), Path(os.environ["WG_STATIC"])

def slug(s: str) -> str:
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "tab"

nav, panels = [], []
for i, label in enumerate(tabs):
    s, act = slug(label), " active" if i == 0 else ""
    nav.append(f'            <button class="tab-btn{act}" data-tab="{s}">{label}</button>')
    panels.append(
        f'        <section class="tab-panel{act}" id="tab-{s}">\n'
        f'            <div class="card">\n'
        f'                <h2>{label}</h2>\n'
        f'                <p>TODO: Inhalt für „{label}".</p>\n'
        f'            </div>\n'
        f'        </section>'
    )

repl = {
    "__NAME__": name,
    "__TITLE__": title,
    "__DESC__": desc,
    "__TABS_NAV__": "\n".join(nav),
    "__TABS_PANELS__": "\n\n".join(panels),
}

for fname in ("index.html", "style.css", "app.js"):
    text = (tpl / fname).read_text(encoding="utf-8")
    for k, v in repl.items():
        text = text.replace(k, v)
    (static / fname).write_text(text, encoding="utf-8")
    print(f"[webgui py] {static / fname} geschrieben")
PYEOF

# ---------- main.py anpassen ----------
MAIN="$APP_DIR/main.py"
render_main() {
    sed -e "s/__NAME__/$NAME/g" -e "s/__DESC__/$(printf '%s' "$DESC" | sed 's/[&/\]/\\&/g')/g" "$TPL/main.py" > "$MAIN"
}

if [[ ! -f "$MAIN" ]]; then
    render_main
    log "main.py neu erstellt (StaticFiles + /api/status)"
elif grep -q "StaticFiles" "$MAIN"; then
    log "main.py hat schon StaticFiles — unverändert gelassen."
elif grep -q 'return "<h1>' "$MAIN" && grep -q "HTMLResponse" "$MAIN"; then
    cp "$MAIN" "$MAIN.bak-webgui"
    render_main
    log "main.py war unverändertes container-scaffold-Gerüst → ersetzt (Backup: main.py.bak-webgui)"
else
    log "main.py enthält eigenen Code → NICHT angefasst. Snippet zum Einbauen:"
    cat <<SNIP
    ----------------------------------------------------------
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    STATIC_DIR = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/status")
    def api_status():
        return {"status": "ok", "service": "$NAME"}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")
    ----------------------------------------------------------
SNIP
fi

cat <<EOF

============================================================
WebGUI fertig: $STATIC_DIR
Dateien: index.html (Header+Tabs+Footer, laedt das zentrale UI-Kit),
style.css + app.js (fast leer, nur fuer Projekteigenes).

Stil/Komponenten kommen aus https://ui.intranet.<DOMAIN>/v1/ui-kit.css+js
Styleguide mit allen Klassen: https://ui.intranet.<DOMAIN>/
Fehlt eine Komponente -> ins Kit aufnehmen, NICHT hierher kopieren.
(Nur LAN. GUI soll extern laufen? Kit nach static/ kopieren + Pfade anpassen.)

Weiter:
- Container neu bauen + starten:
  podman build -t $NAME ~/containers/$NAME && systemctl --user restart container-$NAME.service
- Frontend-Ausbau (Formulare, Tabellen) via ollama-code generieren lassen.
- Sichtprüfung IMMER per Browser/Playwright-Screenshot, nie nur curl.
============================================================
EOF

"""API-Router: Misc-Endpoints (Migrations-Welle 6).

Routen: GET /load-diagram, GET /list-diagrams, POST /save-diagram
        GET /api/claude-status — Claude-Anmeldungsstatus prüfen
"""
import logging
import os

from fastapi import APIRouter, HTTPException, Query

from app.services import misc_service
from app.services import version_service
from app.services import bot_status_service

log = logging.getLogger("dashboard.api.misc")
router = APIRouter(tags=["misc"])


@router.get("/api/version")
def api_version():
    """Installed version of this ili instance (VERSION file + build metadata)."""
    return version_service.version_info()


@router.get("/bot-status")
def bot_status():
    """Status aller Claude-Code-Sessions in tmux (wartet/arbeitet/leer) für die Bots-Übersicht."""
    try:
        return bot_status_service.list_sessions()
    except Exception as e:
        log.error("bot-status fehlgeschlagen: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/bot-answer")
def bot_answer(body: dict | None = None):
    """Antwort in eine wartende Claude-Session tippen (fragen.html).
    Body: {session, text?} für Text+Enter ODER {session, key?} für Einzeltaste (1-9/Enter/Escape)."""
    body = body or {}
    session = (body.get("session") or "").strip()
    if not session:
        raise HTTPException(status_code=400, detail="session nötig")
    try:
        res = bot_status_service.send_answer(session, body.get("text") or "", body.get("key") or "")
    except Exception as e:
        log.error("bot-answer fehlgeschlagen (session=%s): %s", session, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "abgelehnt"))
    return res


@router.post("/projterm-heal")
def projterm_heal(board: str = Query(default="")):
    """Projekt-Terminal heilen (vom „↻ Neu laden"-Knopf): Mosaik-Clients lösen +
    tote claude-Session via `claude --continue` fortsetzen. board = Board-Slug."""
    try:
        return bot_status_service.heal_session(board)
    except Exception as e:
        log.error("projterm-heal fehlgeschlagen (board=%s): %s", board, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# Scanner-Historie: GET /shelly ist am 2026-08-01 in den eigenen Container
# `shelly-scanner` gewandert (Port 8808) — ein 20-30s dauernder synchroner
# LAN-Scan hatte hier den uvicorn-Threadpool erschoepft (502 der gesamten
# Dashboard-API, Vorfall 2026-06-15). Am 2026-08-07 folgte POST /trigger-scan
# samt scan_network.py, scan.html und scan_config.json in denselben Container
# (dort: POST /api/lan/scan).


@router.get("/load-diagram")
def load_diagram(name: str = Query(default="")):
    try:
        return misc_service.load_diagram(name)
    except Exception as e:
        log.error("load-diagram Fehler: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/list-diagrams")
def list_diagrams():
    try:
        return misc_service.list_diagrams()
    except Exception as e:
        log.error("list-diagrams Fehler: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/save-diagram")
def save_diagram(body: dict | None = None):
    body = body or {}
    name = (body.get("name") or "").strip()
    xml = body.get("xml") or ""
    try:
        return misc_service.save_diagram(name, xml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception:
        log.exception("save-diagram Fehler")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Claude-Anmeldungs-Helfer ──
# Architektur-Zwang: `api` und `terminal` sind getrennte Container ohne gemeinsamen
# tmux-Socket (anders als im Home-Stack, wo dashboard-api als systemd --user-Prozess
# denselben Socket wie das Terminal sieht — siehe docs/WIDGETS.md). Ein tmux-basierter
# Check wie in bot_status_service liefert hier also IMMER ein falsches Ergebnis.
# Stattdessen: dasselbe Datei-/Env-Kriterium wie `deploy/terminal/ili-claude.sh`
# (has_credentials()) — der Login-Zustand ist eine Datei im terminal-home-Volume,
# das docker-compose.terminal.yml read-only in diesen Container mountet, sobald das
# Terminal-Profil aktiv ist. Ohne diesen Mount (Terminal aus) bleibt logged_in immer
# False — korrekt, denn ohne Terminal gibt es nichts, worin man sich anmelden könnte.
#
# Den Device-Code SENDEN passiert bewusst NICHT hier: das Terminal ist ein
# same-origin iframe (/projterm/), das Frontend schreibt den Code direkt über das
# xterm.js-Objekt des iframes ins Terminal (html/claude-login-panel.html) — derselbe
# Datenkanal, den project-chat-terminal.js schon für die OSC-52-Zwischenablage nutzt.
# Das braucht keinen Backend-Roundtrip und funktioniert unabhängig von der
# Container-Aufteilung.
_CLAUDE_CREDS_DIR = os.environ.get("CLAUDE_CONFIG_DIR", "/claude-home/.claude")


def _env_secret(name: str) -> str:
    """Read a secret from the environment, ignoring unexpanded compose placeholders.

    podman-compose 1.0.3 (Debian 12) does not interpolate `${VAR:-}` in the
    `environment:` block — the container literally receives the string
    "${ANTHROPIC_API_KEY:-}". Treating that as a real key made /api/claude-status
    report logged_in=true on every Podman install, so the login panel never showed
    (found 22.08.2026 in the release sandbox).
    """
    value = (os.environ.get(name) or "").strip()
    if value.startswith("${"):
        log.debug("claude-status: %s ist ein nicht aufgelöster Compose-Platzhalter (%r) — ignoriert", name, value)
        return ""
    return value


@router.get("/api/claude-status")
def get_claude_status():
    """Claude-Anmeldungsstatus fürs Login-Panel prüfen.

    Spiegelt has_credentials() aus deploy/terminal/ili-claude.sh: API-Key/Token als
    Env-Var ODER gespeicherte Anmeldung im terminal-home-Volume.
    Returns {logged_in: bool, source: str}.
    """
    if _env_secret("ANTHROPIC_API_KEY"):
        return {"logged_in": True, "source": "api-key"}
    if _env_secret("CLAUDE_CODE_OAUTH_TOKEN"):
        return {"logged_in": True, "source": "oauth-token"}
    creds_file = os.path.join(_CLAUDE_CREDS_DIR, ".credentials.json")
    if os.path.isfile(creds_file):
        return {"logged_in": True, "source": "stored-login"}
    log.debug("claude-status: keine Anmeldung gefunden (%s)", creds_file)
    return {"logged_in": False, "source": "none"}


@router.get("/api/claude-login-url")
def get_claude_login_url():
    """Unbroken OAuth sign-in URL for the login panel.

    Written by deploy/terminal/ili-login-url-watch.sh into the terminal home
    (mounted read-only here). Screen scraping in the panel is only the fallback:
    after a tmux re-attach the screen can show a damaged copy of the URL.
    Returns {url: str|null}.
    """
    path = os.path.join(_CLAUDE_CREDS_DIR, "ili-login-url")
    try:
        with open(path, encoding="utf-8") as fh:
            url = fh.read().strip()
    except FileNotFoundError:
        log.debug("claude-login-url: keine Datei (%s)", path)
        return {"url": None}
    except OSError as exc:
        log.warning("claude-login-url: %s nicht lesbar: %s", path, exc)
        return {"url": None}
    if not url.startswith("https://") or "code_challenge=" not in url or "state=" not in url:
        log.warning("claude-login-url: Inhalt unplausibel (%d Zeichen) — ignoriert", len(url))
        return {"url": None}
    log.debug("claude-login-url: %d Zeichen geliefert", len(url))
    return {"url": url}

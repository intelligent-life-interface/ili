"""API-Router: Misc-Endpoints (Migrations-Welle 6).

Routen: GET /load-diagram, GET /list-diagrams, POST /save-diagram
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import misc_service
from app.services import bot_status_service

log = logging.getLogger("dashboard.api.misc")
router = APIRouter(tags=["misc"])


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

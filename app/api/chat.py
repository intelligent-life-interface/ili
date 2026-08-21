"""API-Router: Chat/KI-Interaktion (Welle 5).

Routen: POST /chat, /title-suggest, /bug-report

Hinweis: Der frühere `/classify-intent`-Endpoint (WhatsApp-Master-Chat-Intent-Erkennung)
wurde am 2026-07-24 entfernt — diese Bot-Logik gehört in den WhatsApp-Bot, nicht ins
Dashboard. Modul liegt jetzt unter `~/containers/whatsapp-bot/intent_classifier.py`
(Kanban dashboard/arch_19bf7e6e2a).
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import chat_service

log = logging.getLogger("dashboard.api.chat")
router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(body: dict):
    log.debug("Chat-Request empfangen")
    try:
        return chat_service.chat(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Fehler im Chat-Handler: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/title-suggest")
def title_suggest(body: dict):
    text = (body.get("text") or "").strip()
    model = (body.get("model") or "mistral:latest").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Feld 'text' fehlt")
    try:
        return chat_service.title_suggest(text, model)
    except Exception as e:
        log.error("[title-suggest] Fehler: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/bug-report")
def bug_report(body: dict):
    """🐞-Karte aus Chat-Nachricht anlegen."""
    text = (body.get("text") or "").strip()
    board_id = (body.get("board_id") or "").strip()
    # Optional: idempotent card for periodic reporters (see chat_service.bug_report).
    dedup_key = (body.get("dedup_key") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Feld 'text' fehlt")
    try:
        return chat_service.bug_report(text, board_id, dedup_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Bug-Report fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

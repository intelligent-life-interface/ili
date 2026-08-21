"""Brainstorming-Modus — HTTP-Endpunkte (Logik in app/services/brainstorm_service.py).

Routen (alle unter /api/brainstorm):
  POST /api/brainstorm            – Single-Shot-Antwort (Fallback, kein Streaming)
  POST /api/brainstorm/stream     – Multi-Turn-Dialog TOKEN-WEISE (NDJSON)
  GET  /api/brainstorm/history    – serverseitigen Verlauf laden (?project_id=)
  POST /api/brainstorm/history    – Verlauf speichern (geräteübergreifend)
  POST /api/brainstorm/to-card    – Brainstorm-Aussage → Kanban-Karte
  POST /api/brainstorm/to-subproject – ausgereifte Idee → Unterprojekt
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import brainstorm_service as svc

logger = logging.getLogger(__name__)
router = APIRouter()


class BrainstormRequest(BaseModel):
    message: str
    project_id: Optional[str] = None
    history: Optional[list] = []


class HistoryRequest(BaseModel):
    project_id: str
    messages: list = []


class IdeaRequest(BaseModel):
    project_id: str
    text: str
    column_id: Optional[str] = ""


class ConversationRequest(BaseModel):
    project_id: str
    messages: list = []
    column_id: Optional[str] = ""


@router.post("/api/brainstorm/stream")
def brainstorm_stream(req: BrainstormRequest):
    """Dialog tokenweise streamen (NDJSON-Zeilen: {"t":…} … {"done":true})."""
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Nachricht leer")
    project_id = req.project_id or "unknown"
    logger.info("[Brainstorm] Stream-Request projekt=%s chars=%d", project_id, len(message))
    generator = svc.stream_brainstorm(project_id, message, req.history or [])
    return StreamingResponse(
        generator,
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/brainstorm")
def brainstorm(req: BrainstormRequest):
    """Single-Shot-Fallback (kein Streaming) — für Clients ohne Stream-Support."""
    from project_creator import _claude_abo_text  # lazy

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Nachricht leer")
    project_id = req.project_id or "unknown"
    try:
        # History als Kontext in EINEN Prompt packen (Single-Shot).
        msgs = svc._bridge_messages(req.history or [], message)
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
        response = _claude_abo_text(svc.SYSTEM_PROMPT, convo,
                                    model=svc.BRAINSTORM_MODEL, max_tokens=1000, timeout=120)
        logger.debug("[Brainstorm] projekt=%s → %d Zeichen Antwort", project_id, len(response))
        return {"response": response or "Keine Antwort erhalten"}
    except Exception as e:
        logger.exception("[Brainstorm] Fehler")
        return {"error": str(e)}


@router.get("/api/brainstorm/history")
def get_history(project_id: str = ""):
    """Serverseitigen Brainstorm-Verlauf eines Projekts laden."""
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id fehlt")
    return {"messages": svc.load_history(project_id)}


@router.post("/api/brainstorm/history")
def post_history(req: HistoryRequest):
    """Brainstorm-Verlauf serverseitig speichern (geräteübergreifend)."""
    n = svc.save_history(req.project_id, req.messages)
    return {"status": "saved", "count": n}


@router.post("/api/brainstorm/to-card")
def to_card(req: IdeaRequest):
    """Brainstorm-Aussage → Kanban-Karte im Projekt-Board."""
    try:
        return svc.idea_to_card(req.project_id, req.text, req.column_id or "")
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception:
        logger.exception("[Brainstorm] to-card Fehler")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/brainstorm/to-subproject")
def to_subproject(req: IdeaRequest):
    """Ausgereifte Idee → Unterprojekt (Board + CLAUDE.md + Tags + Ideen-Karten)."""
    try:
        return svc.idea_to_subproject(req.project_id, req.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception:
        logger.exception("[Brainstorm] to-subproject Fehler")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/brainstorm/to-description")
def to_description(req: ConversationRequest):
    """Ganzes Gespräch → Projekt-Beschreibung ins Manifest (`description`)."""
    try:
        return svc.conversation_to_description(req.project_id, req.messages)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception:
        logger.exception("[Brainstorm] to-description Fehler")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/brainstorm/to-cards")
def to_cards(req: ConversationRequest):
    """Ganzes Gespräch → mehrere Karten (Plan) ins aktuelle Board."""
    try:
        return svc.conversation_to_cards(req.project_id, req.messages, req.column_id or "")
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception:
        logger.exception("[Brainstorm] to-cards Fehler")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

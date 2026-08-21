"""API-Router: KI-Endpoints (Migrations-Welle 4).

Routen: /ki-advisor (GET+POST), /ki-accept, /ki-reject, /ki-reactivate,
        /ki-feedback, /ki-explain-results, /ki-explain-queue, /ki-bug-report,
        /ki-global-rejections, /ki-global-reject, /ki-global-reactivate,
        /ki-critique, /ollama-stats (GET+POST)
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services import ki_global_rejections_service, ki_service
from app.services.ki_service import AdvisorAlreadyRunning

log = logging.getLogger("dashboard.api.ki")
router = APIRouter(tags=["ki"])


# ── KI-Advisor ───────────────────────────────────────────────────

@router.get("/ki-advisor")
def ki_advisor_status():
    try:
        return ki_service.advisor_status()
    except Exception as e:
        log.error("KI-Advisor-Status laden fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/ki-advisor")
def ki_advisor_run(body: dict | None = None):
    try:
        result = ki_service.advisor_run(body or {})
        # Legacy antwortet 202 Accepted
        return JSONResponse(status_code=202, content=result)
    except AdvisorAlreadyRunning as e:
        # Spezial-Payload mit zwei Feldern → direkt als JSONResponse
        return JSONResponse(status_code=409, content={"error": "KI-Advisor läuft bereits", "status": e.status})
    except ValueError as e:
        # z.B. fehlende board_id (Advisor läuft nur pro Einzelprojekt)
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("KI-Advisor starten fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Accept / Reject / Reactivate ─────────────────────────────────

@router.post("/ki-accept")
def ki_accept(body: dict | None = None):
    body = body or {}
    board_id = (body.get("board_id") or "").strip()
    title = (body.get("title") or "").strip()
    if not board_id or not title:
        raise HTTPException(status_code=400, detail="board_id und title erforderlich")
    try:
        return ki_service.ki_accept(board_id, title)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Board nicht gefunden")
    except Exception as e:
        log.error("KI-Accept fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/ki-reject")
def ki_reject(body: dict | None = None):
    body = body or {}
    board_id = (body.get("board_id") or "").strip()
    title = (body.get("title") or "").strip()
    reason = (body.get("reason") or "").strip()
    if not board_id or not title:
        raise HTTPException(status_code=400, detail="board_id und title erforderlich")
    try:
        return ki_service.ki_reject(board_id, title, reason)
    except Exception as e:
        log.error("KI-Reject fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/ki-reactivate")
def ki_reactivate(body: dict | None = None):
    body = body or {}
    board_id = (body.get("board_id") or "").strip()
    title = (body.get("title") or "").strip()
    if not board_id or not title:
        raise HTTPException(status_code=400, detail="board_id und title erforderlich")
    try:
        return ki_service.ki_reactivate(board_id, title)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Board nicht gefunden")
    except Exception as e:
        log.error("KI-Reactivate fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Feedback / Explain ───────────────────────────────────────────

@router.get("/ki-feedback")
def ki_feedback():
    try:
        return ki_service.ki_feedback()
    except Exception as e:
        log.error("KI-Feedback laden fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/ki-explain-results")
def ki_explain_results(board_id: str = Query(default=""), title: str = Query(default="")):
    try:
        return ki_service.explain_results(board_id, title)
    except Exception as e:
        log.error("Explain-Results GET fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/ki-explain-queue")
def ki_explain_queue(body: dict | None = None):
    body = body or {}
    board_id = body.get("board_id", "")
    title = body.get("title", "")
    if not board_id or not title:
        raise HTTPException(status_code=400, detail="board_id und title erforderlich")
    try:
        return ki_service.explain_queue(
            board_id, title,
            body.get("desc", ""),
            body.get("board_name", board_id),
        )
    except Exception as e:
        log.error("Explain-Queue POST fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Bug-Report ───────────────────────────────────────────────────

@router.post("/ki-bug-report")
def ki_bug_report(body: dict | None = None):
    body = body or {}
    bug = (body.get("bug") or "").strip()
    if not bug:
        raise HTTPException(status_code=400, detail="bug-Text fehlt")
    board_id = body.get("board_id", "")
    try:
        return ki_service.bug_report(
            board_id,
            body.get("board_name", board_id),
            body.get("title", ""),
            body.get("desc", ""),
            bug,
        )
    except Exception as e:
        log.error("Bug-Report fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Globale Ablehnungen ──────────────────────────────────────────

@router.get("/ki-global-rejections")
def ki_global_rejections():
    return ki_global_rejections_service.global_rejections()


@router.post("/ki-global-reject")
def ki_global_reject(body: dict | None = None):
    body = body or {}
    pattern = (body.get("pattern") or "").strip()
    reason = (body.get("reason") or "").strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="pattern erforderlich")
    try:
        return ki_global_rejections_service.global_reject(pattern, reason)
    except Exception as e:
        log.error("Global-Reject fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/ki-global-reactivate")
def ki_global_reactivate(body: dict | None = None):
    body = body or {}
    try:
        return ki_global_rejections_service.global_reactivate(body.get("id", ""), body.get("pattern", ""))
    except LookupError:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    except Exception as e:
        log.error("Global-Reactivate fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Critique ─────────────────────────────────────────────────────

@router.post("/ki-critique")
def ki_critique(body: dict | None = None):
    body = body or {}
    try:
        return ki_service.critique(
            body.get("board_name", body.get("board_id", "")),
            body.get("title", ""),
            body.get("desc", ""),
            body.get("model"),
        )
    except Exception as e:
        log.error("Critique fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── Ollama-Stats (Legacy: GET und POST identisch) ────────────────

@router.api_route("/ollama-stats", methods=["GET", "POST"])
def ollama_stats():
    # Liefert auch bei Ollama-Ausfall HTTP 200 mit online=False (Legacy-Verhalten)
    return ki_service.ollama_stats()

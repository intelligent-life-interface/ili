"""API-Router: Usage-Ingest für Apps ausserhalb der Host-Skripte.

Routen:
    POST /api/usage → einen kompletten Lauf (Loop/App, Ausgang, optional Tokens/Kosten)
                      in die zentrale loop_runs.db eintragen; gibt {run_id} zurück.

Client-Regel: fire-and-forget mit ≤2s Timeout — ein fehlgeschlagener Statistik-Call
darf die aufrufende App nie bremsen oder stoppen.
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import usage_service

log = logging.getLogger("dashboard.api.usage")
router = APIRouter(tags=["usage"])


@router.post("/api/usage")
def post_usage(body: dict):
    """Einen Lauf inkl. optionaler Verbrauchsdaten registrieren."""
    try:
        result = usage_service.record(body)
        return {"status": "ok", **result}
    except ValueError as exc:
        log.warning("Ungültiger Usage-Report: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("Usage-Report fehlgeschlagen: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

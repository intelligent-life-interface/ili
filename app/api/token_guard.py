"""API-Router: Token-Wächter-Verlauf (Skript-Durchläufe via run-ki-dev.sh).

Routen: /api/token-guard/runs
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import token_guard_service

log = logging.getLogger("dashboard.api.token_guard")
router = APIRouter(tags=["token-guard"])


@router.get("/api/token-guard/runs")
def get_token_guard_runs(days: int = 14):
    try:
        return {
            "runs": token_guard_service.runs(days),
            "threshold_default": token_guard_service.DEFAULT_THRESHOLD,
        }
    except Exception as e:
        log.error("Fehler bei /api/token-guard/runs: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

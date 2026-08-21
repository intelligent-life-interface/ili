"""API-Router: Dashboard-Aggregat (Phase 6 — löst generate_dashboard.py ab).

Routen: GET /api/dashboard
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import dashboard_service

log = logging.getLogger("dashboard.api.dashboard")
router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
def get_dashboard():
    try:
        return dashboard_service.collect()
    except Exception as e:
        log.error("Fehler beim Sammeln der Dashboard-Daten: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

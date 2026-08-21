"""API-Router: 'Zuletzt bearbeitet'-Ansicht.

Routen: GET /api/projects/recent
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import recent_service

log = logging.getLogger("dashboard.api.recent")
router = APIRouter(tags=["recent"])


@router.get("/api/projects/recent")
def get_recent(limit: int = Query(200, ge=1, le=1000),
               category: str | None = None,
               status: str | None = None):
    try:
        return recent_service.collect_recent(limit=limit, category=category, status=status)
    except Exception as e:
        log.error("Fehler beim Sammeln der Recent-Activity-Daten: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

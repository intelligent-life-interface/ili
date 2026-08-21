"""API-Router: 'Nach Erstelldatum'-Ansicht.

Routen: GET /api/projects/created
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import created_service

log = logging.getLogger("dashboard.api.created")
router = APIRouter(tags=["created"])


@router.get("/api/projects/created")
def get_created(limit: int = Query(500, ge=1, le=1000),
                category: str | None = None,
                status: str | None = None):
    try:
        return created_service.collect_created(limit=limit, category=category, status=status)
    except Exception as e:
        log.error("Fehler beim Sammeln der Erstelldatum-Daten: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

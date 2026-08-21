"""API-Router: Inaktive Projekte (Leichen).

Routen:
  GET /api/projects/inactive  — Liste aller inaktiven Projekte
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import inactive_projects_service

log = logging.getLogger("dashboard.api.inactive_projects")
router = APIRouter(tags=["inactive_projects"])


@router.get("/api/projects/inactive")
def get_inactive_projects(
    threshold_days: int = Query(30, ge=1, le=365, description="Tage ohne Aktivität = inaktiv"),
    limit: int = Query(1000, ge=1, le=5000, description="Max. Anzahl Ergebnisse"),
):
    """Liste der inaktiven Projekte.

    Args:
        threshold_days: Schwellwert (default 30 Tage, Entscheidung: Hybrid Git+Board)
        limit: Max. Anzahl Ergebnisse (zur Sicherheit limitiert)

    Returns:
        {"projects": [{"id", "title", "path", "tags", "last_activity", "inactivity_days", "status"}]}
    """
    try:
        projects = inactive_projects_service.get_inactive_projects(threshold_days=threshold_days)
        return {
            "projects": projects[:limit],
            "count": len(projects),
            "threshold_days": threshold_days,
        }
    except Exception as e:
        log.error("Fehler beim Sammeln inaktiver Projekte: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

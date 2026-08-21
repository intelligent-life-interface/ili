"""API-Router: Isehauer-Priorität pro Projekt (F1.2).

Routen: GET /api/isehauer/item?project=<id>, PATCH /api/isehauer/item
Proxy auf den Isehauer-Container (Port 3005) via app/services/isehauer_service.
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services import isehauer_service
from app.services.isehauer_service import IsehauerDownError

log = logging.getLogger("dashboard.api.isehauer")
router = APIRouter(tags=["isehauer"])


@router.get("/api/isehauer/item")
def get_item(project: str = Query(default="")):
    """Eisenhower-Status eines Projekts (Quadrant/Frosch/Pareto) aus der aktuellen Woche."""
    if not project:
        raise HTTPException(status_code=400, detail="Query-Parameter 'project' fehlt")
    try:
        return isehauer_service.get_item(project)
    except Exception as e:
        log.error("Isehauer get_item('%s') fehlgeschlagen: %s", project, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.patch("/api/isehauer/item")
def patch_item(body: dict):
    """Eisenhower-Felder setzen. Body: {project, quadrant?|frog_date?|pareto?|clear_quadrant?|clear_frog?}."""
    project = (body or {}).get("project") or ""
    if not project:
        raise HTTPException(status_code=400, detail="Body-Feld 'project' fehlt")
    fields = {k: v for k, v in body.items() if k != "project"}
    try:
        return isehauer_service.patch_item(project, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except IsehauerDownError as e:
        log.warning("Isehauer down bei PATCH für '%s': %s", project, e)
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        log.error("Isehauer patch_item('%s') fehlgeschlagen: %s", project, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

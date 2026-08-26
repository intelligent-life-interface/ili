"""API-Router: Priority Widget-Priorität pro Projekt (F1.2).

Routen: GET /api/priority_widget/item?project=<id>, PATCH /api/priority_widget/item
Proxy auf den Priority Widget-Container (Port 3005) via app/services/priority_widget_service.
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services import priority_widget_service
from app.services.priority_widget_service import PriorityWidgetDownError

log = logging.getLogger("dashboard.api.priority_widget")
router = APIRouter(tags=["priority_widget"])


@router.get("/api/priority_widget/item")
def get_item(project: str = Query(default="")):
    """Eisenhower-Status eines Projekts (Quadrant/Frosch/Pareto) aus der aktuellen Woche."""
    if not project:
        raise HTTPException(status_code=400, detail="Query-Parameter 'project' fehlt")
    try:
        return priority_widget_service.get_item(project)
    except Exception as e:
        log.error("Priority Widget get_item('%s') fehlgeschlagen: %s", project, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.patch("/api/priority_widget/item")
def patch_item(body: dict):
    """Eisenhower-Felder setzen. Body: {project, quadrant?|frog_date?|pareto?|clear_quadrant?|clear_frog?}."""
    project = (body or {}).get("project") or ""
    if not project:
        raise HTTPException(status_code=400, detail="Body-Feld 'project' fehlt")
    fields = {k: v for k, v in body.items() if k != "project"}
    try:
        return priority_widget_service.patch_item(project, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except PriorityWidgetDownError as e:
        log.warning("Priority Widget down bei PATCH für '%s': %s", project, e)
        return JSONResponse(status_code=503, content={"error": str(e)})
    except Exception as e:
        log.error("Priority Widget patch_item('%s') fehlgeschlagen: %s", project, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

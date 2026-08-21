"""API-Router: Direktlinks zum (Unter-)Projekt (Webapp / Dateien / GitHub / CLAUDE.md).

Routen:
  * GET /api/project-links?id=<slug>     → ein Projekt (für den project.html-Kopf)
  * GET /api/project-links?ids=<a,b,c>   → mehrere (Unterprojekte), Map nach id
  * GET /api/project-links/by-service    → Reverse-Map {sub: board_id} (Service → Projekt)

Logik in app.services.project_links (resolve_work_dir → Links).
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import project_links as svc

log = logging.getLogger("dashboard.api.project_links")
router = APIRouter(prefix="/api/project-links", tags=["project-links"])


@router.get("")
def project_links(id: str = Query(default=""), ids: str = Query(default="")):
    """Direktlinks für ein Board (id) oder eine Liste von Unterprojekten (ids, komma-getrennt)."""
    try:
        if ids.strip():
            slugs = [s.strip() for s in ids.split(",") if s.strip()]
            return {"projects": {s: svc.build_links(s) for s in slugs}}
        if not id.strip():
            raise HTTPException(status_code=400, detail="id oder ids fehlt")
        return svc.build_links(id.strip())
    except HTTPException:
        raise
    except Exception as e:
        log.error("project-links fehlgeschlagen (id=%s ids=%s): %s", id, ids, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/by-service")
def by_service():
    """Reverse-Map {subdomain: board_id} für die Service-/Web-Adressen-Seite (Service → Projekt)."""
    try:
        return {"map": svc.service_project_map()}
    except Exception as e:
        log.error("project-links/by-service fehlgeschlagen: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

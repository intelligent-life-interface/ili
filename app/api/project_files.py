"""API-Router: Datei-Panel des Projekts (Liste + gerenderte Markdown-Ansicht).

Routen:
  * GET /api/project-files?id=<slug>                 → Top-Level-Dateiliste des Arbeitsordners
  * GET /api/project-files/view?id=<slug>&file=<rel> → .md-Datei als gerendertes HTML

Logik in app.services.project_files.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import project_files as svc

log = logging.getLogger("dashboard.api.project_files")
router = APIRouter(prefix="/api/project-files", tags=["project-files"])


@router.get("")
def project_files(id: str = Query(default="")):
    """Dateiliste des Projekt-Arbeitsordners (für das 📂-Panel in project.html)."""
    if not id.strip():
        raise HTTPException(status_code=400, detail="id fehlt")
    try:
        return svc.list_files(id.strip())
    except Exception as e:
        log.error("project-files fehlgeschlagen (id=%s): %s", id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/view")
def project_file_view(id: str = Query(default=""), file: str = Query(default="")):
    """Eine .md-Datei des Projekts als gerendertes HTML (Links anklickbar)."""
    if not id.strip() or not file.strip():
        raise HTTPException(status_code=400, detail="id und file nötig")
    try:
        return svc.render_markdown(id.strip(), file.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("project-files/view fehlgeschlagen (id=%s file=%s): %s", id, file, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

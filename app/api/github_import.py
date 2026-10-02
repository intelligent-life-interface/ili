"""API-Router: GitHub-Repo-Import.

Routen:
  GET  /api/projects/github/repos?user=<login> — Repos eines GitHub-Users auflisten
  POST /api/projects/github/import — Repos als Boards importieren
  POST /api/projects/github/sync — Sync-Mechanismus triggern (on-demand)
"""
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Body

from app.services.github_import_service import (
    list_github_repos,
    import_github_repos,
)

log = logging.getLogger("dashboard.api.github_import")
router = APIRouter(tags=["github-import"])


@router.get("/api/projects/github/repos")
def get_github_repos(
    user: str = Query("", description="GitHub-Username (leer = Viewer)"),
    force: bool = Query(False, description="Cache invalidieren"),
):
    """Listet Repos eines GitHub-Users (oder Viewer, wenn user leer).

    Query-Parameter:
      - user: GitHub-Username (leer → Token-Owner)
      - force: Cache umgehen

    Rückgabe: {viewer_login, requested_user, repos: [{full_name, name, description, private, url}]}
    """
    try:
        return list_github_repos(user.strip() if user else "", force=force)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"GitHub-API nicht erreichbar: {e}")
    except Exception as e:
        log.error("Fehler beim Laden von GitHub-Repos: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/projects/github/import")
def post_github_import(
    full_names: Annotated[list[str], Body()] = None,
    auto: bool = Query(False, description="Automat aktivieren (auto:true)"),
):
    """Importiert GitHub-Repos als neue Boards.

    Body: ["octocat/repo1", "octocat/repo2"]
    Query: auto=true → Board mit auto:true, sonst auto:false (konservativ)

    Rückgabe: {
      "octocat/repo1": {status, board_id, work_dir, ...},
      "octocat/repo2": {status, reason, ...},
      ...
    }
    """
    if not full_names:
        raise HTTPException(status_code=400, detail="full_names ist Pflicht (leere Liste okay)")

    try:
        results = import_github_repos(full_names, auto=auto)
        return results
    except Exception as e:
        log.error("Fehler beim GitHub-Import: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import fehlgeschlagen: {e}")


@router.post("/api/projects/github/sync")
def post_github_sync(
    board_id: str = Query("", description="Nur dieses Board synced (leer = alle)"),
    dry_run: bool = Query(False),
):
    """Triggert Sync von GitHub-Repos mit lokalen Ordnern.

    On-demand Sync-Wrapper für jobs/github_project_sync.py.

    Query-Parameter:
      - board_id: optional, nur dieses Board
      - dry_run: nur berichten, nicht schreiben

    Rückgabe: {"status": "ok", "synced": [...], "errors": [...]}
    """
    try:
        # Import hier, um Zirkelbezüge zu vermeiden (jobs/ sind nicht im app-Package)
        import sys
        from pathlib import Path
        jobs_dir = Path(__file__).resolve().parents[2] / "jobs"
        # Sync is NOT part of this release: pulling and pushing an imported
        # repository needs conflict handling and an answer to "what if the
        # automat commits in /projects/<board> while someone pushes from
        # elsewhere". Import ships first, sync follows. Say so plainly instead
        # of letting an ImportError look like a defect.
        if not (jobs_dir / "github_project_sync.py").exists():
            raise HTTPException(
                status_code=501,
                detail="Sync ist in dieser Version nicht enthalten — importieren "
                       "und klonen funktioniert, das Zurückspielen von Änderungen "
                       "folgt in einer späteren Version.",
            )
        if jobs_dir not in sys.path:
            sys.path.insert(0, str(jobs_dir))

        from github_project_sync import sync_github_projects

        result = sync_github_projects(board_id=board_id if board_id.strip() else None, dry_run=dry_run)
        return {"status": "ok", **result}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Fehler beim GitHub-Sync: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync fehlgeschlagen: {e}")

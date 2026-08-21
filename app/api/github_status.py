"""API-Router: GitHub-Repo-Status-Ansicht + kombinierter Commit-/Push-Status.

Routen: GET /api/projects/github, GET /api/projects/git-status
(Prefix `api/projects` bewusst gewählt, ist bereits in der nginx-Sammel-Regex
`html/_api-locations.conf` enthalten — kein Regex-Change/`podman restart dashboard` nötig.)
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.services import git_status_service, github_status_service

log = logging.getLogger("dashboard.api.github_status")
router = APIRouter(tags=["github-status"])


@router.get("/api/projects/github")
def get_github_repos(force: bool = Query(False)):
    try:
        return github_status_service.collect_github_repos(force=force)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Laden der GitHub-Repos: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/api/projects/git-status")
def get_git_status(force: bool = Query(False)):
    try:
        return git_status_service.collect_git_status(force=force)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Laden des Git-Status: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

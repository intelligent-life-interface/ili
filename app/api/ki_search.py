"""API-Router: semantische KI-Projektsuche (Fallback via lokales Ollama).

Route: POST /api/projects/ki-search  (durch 'api/projects' in der nginx-Regex
schon abgedeckt → kein podman restart, nur dashboard-api-Restart).

Bewusst `def` statt `async def`: der Ollama-Call ist synchron (urllib). FastAPI
schiebt sync-Routen in den Threadpool — ein synchroner Netzwerk-Call in einer
`async def`-Route wuerde den ganzen uvicorn-Worker einfrieren (Haus-Haertungs-
regel 06.08.). Die eigentliche Logik/das Ollama-Handling liegt im Service.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import ki_search_service

log = logging.getLogger("dashboard.api.ki_search")
router = APIRouter(tags=["ki-search"])


class _Project(BaseModel):
    id: str
    name: str | None = None
    tags: list[str] | None = None
    desc: str | None = None
    description: str | None = None

    model_config = {"extra": "allow"}


class KiSearchRequest(BaseModel):
    query: str
    projects: list[_Project] = []


@router.post("/api/projects/ki-search")
def ki_search(req: KiSearchRequest):
    try:
        projects = [p.model_dump() for p in req.projects]
        return ki_search_service.search_projects(req.query, projects)
    except Exception as e:  # service degrades itself; this is a last-resort guard
        log.error("KI-Suche-Endpoint fehlgeschlagen: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

"""API-Router: Foto→Projekt (Welle 5).

POST /project-from-photo — antwortet sofort 201, Ollama-Vision-Analyse läuft
als BackgroundTask (ersetzt threading.Thread des alten Servers).
"""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.services import photo_service

log = logging.getLogger("dashboard.api.photos")
router = APIRouter(tags=["photos"])


@router.post("/project-from-photo", status_code=201)
def project_from_photo(body: dict, background_tasks: BackgroundTasks):
    log.debug("project-from-photo empfangen")
    try:
        response, bg_args = photo_service.create_from_photo(body)
        background_tasks.add_task(photo_service.analyse_in_background, **bg_args)
        return response
    except Exception as e:
        log.error("Fehler in project-from-photo: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

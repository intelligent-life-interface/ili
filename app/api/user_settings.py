"""API-Router: Benutzereinstellungen (Theme, Akzent, Schriftgrösse, Widgets).

Routen:
    GET  /api/user-settings          → dict mit allen Einstellungen
    PUT  /api/user-settings          → dict speichern, gibt gespeicherte Werte zurück
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import user_settings_service

log = logging.getLogger("dashboard.api.user_settings")
router = APIRouter(tags=["user-settings"])


@router.get("/api/user-settings")
def get_user_settings():
    """Aktuelle Benutzereinstellungen laden."""
    try:
        settings = user_settings_service.load()
        log.debug("GET /api/user-settings → %s", settings)
        return settings
    except Exception as exc:
        log.error("Fehler beim Laden der Benutzereinstellungen: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.put("/api/user-settings")
def put_user_settings(body: dict):
    """Benutzereinstellungen speichern. Unbekannte Keys werden ignoriert."""
    try:
        saved = user_settings_service.save(body)
        log.info("PUT /api/user-settings gespeichert: %s", saved)
        return {"status": "ok", "settings": saved}
    except ValueError as exc:
        log.warning("Ungültige Einstellungen: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("Fehler beim Speichern der Benutzereinstellungen: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

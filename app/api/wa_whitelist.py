"""API-Router: WhatsApp-Whitelist (Nummern-Verwaltung).

Routen: /wa-whitelist (GET/POST/DELETE)
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import wa_whitelist_service

log = logging.getLogger("dashboard.api.wa_whitelist")
router = APIRouter(tags=["wa-whitelist"])


@router.get("/wa-whitelist")
def wa_whitelist_get():
    try:
        return wa_whitelist_service.wa_whitelist_get()
    except Exception as e:
        log.error("Whitelist GET fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/wa-whitelist")
def wa_whitelist_post(body: dict | None = None):
    body = body or {}
    number = wa_whitelist_service._wa_normalize(body.get("number", ""))
    name = (body.get("name") or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="number fehlt")
    try:
        return wa_whitelist_service.wa_whitelist_add(number, name)
    except Exception as e:
        log.error("Whitelist POST fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.delete("/wa-whitelist")
def wa_whitelist_delete(body: dict | None = None):
    body = body or {}
    number = wa_whitelist_service._wa_normalize(body.get("number", ""))
    if not number:
        raise HTTPException(status_code=400, detail="number fehlt")
    try:
        return wa_whitelist_service.wa_whitelist_remove(number)
    except LookupError:
        raise HTTPException(status_code=404, detail="Nicht in Whitelist")
    except Exception as e:
        log.error("Whitelist DELETE fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

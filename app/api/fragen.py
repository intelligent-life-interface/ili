"""API-Router: Zähler für die 'Offene Fragen'-Ansicht (Nav-Badge).

Routen: GET /api/fragen/count

Liefert exakt die Zahl, die fragen.html als '❓ N offen' anzeigt:
wartende Terminal-Sessions + offene Automat-Entscheidungskarten.
Ergebnis wird kurz gecacht (TTL), weil das Nav-Menü auf JEDER Dashboard-Seite
lädt und die Decisions-Abfrage sämtliche Board-JSONs liest.
"""
import logging

from fastapi import APIRouter

from app.api import automat as automat_api
from app.services import bot_status_service
from app.services.ttl_cache import TTLCache

log = logging.getLogger("dashboard.api.fragen")
router = APIRouter(tags=["fragen"])

_cache = TTLCache(ttl_seconds=30.0)  # Nav pollt minütlich, mehrere Tabs teilen sich


def _collect() -> dict:
    """Zählt wartende Sessions + offene Entscheidungen (gleiche Formel wie fragen.html)."""
    waiting = 0
    decisions = 0
    try:
        sessions = bot_status_service.list_sessions().get("sessions", [])
        waiting = sum(1 for s in sessions if s.get("state") == "wartet")
    except Exception as e:
        log.error("fragen/count: bot-status fehlgeschlagen: %s", e, exc_info=True)
    try:
        decisions = int(automat_api.list_decisions().get("count", 0))
    except Exception as e:
        log.error("fragen/count: automat-decisions fehlgeschlagen: %s", e, exc_info=True)
    out = {"count": waiting + decisions, "waiting": waiting, "decisions": decisions}
    log.debug("fragen/count: %s", out)
    return out


@router.get("/api/fragen/count")
def fragen_count():
    """Anzahl offener Fragen für das Nav-Badge — nie ein Fehler, im Zweifel 0."""
    try:
        data = _cache.get(_collect)
        return {**data, "cached": _cache.is_valid()}
    except Exception as e:
        log.error("fragen/count fehlgeschlagen: %s", e, exc_info=True)
        return {"count": 0, "waiting": 0, "decisions": 0, "error": True}

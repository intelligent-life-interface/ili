"""API-Router: operative Logs aus der optionalen PostgreSQL (`logs`-Tabelle,
siehe app/services/log_db_service.py). Best effort — ohne erreichbare
Datenbank liefert GET /db-logs {"available": false, "bugs": []} statt eines
Fehlers, damit bugs.html deswegen nie abstürzt.
"""
import logging

from fastapi import APIRouter, Query

from app.services import log_db_service

log = logging.getLogger("dashboard.api.db_logs")
router = APIRouter(tags=["logs"])


@router.get("/db-logs")
def db_logs(
    level: str = Query(default="", description="'error', 'warning' oder leer für beide"),
    since: int = Query(default=720, description="Stunden zurück, max. 2160 (90 Tage)"),
    q: str = Query(default="", description="Volltext-Filter über Meldung + Kontext"),
    limit: int = Query(default=200),
):
    rows = log_db_service.query(level=level.upper(), since_hours=since, q=q, limit=limit)
    bugs = [
        {
            "id": f"dblog:{r['id']}",
            "source": "dblog",
            "level": "error" if r["level"] == "ERROR" else "warning",
            "service": r["service"],
            "ts": r["ts"].strftime("%Y-%m-%d %H:%M:%S") if r.get("ts") else "",
            "headline": (r["message"] or "")[:200],
            "context": r["context"] or r["message"] or "",
        }
        for r in rows
    ]
    return {
        "available": log_db_service.is_available(),
        "retention_days": log_db_service.retention_days(),
        "count": len(bugs),
        "bugs": bugs,
    }

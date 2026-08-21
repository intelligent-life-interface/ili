"""Created-Service: Projekte sortiert nach Erstelldatum für GET /api/projects/created.

Datenquelle: boards/manifest.json, Feld `created_at` pro Board (ISO-8601, wird beim
Anlegen eines Boards gesetzt). Anders als "Zuletzt aktiv" (recent_service, worklog.db)
braucht diese Ansicht KEINE externe DB — das Erstelldatum steht direkt im Manifest und
ist ISO-formatiert, also lexikalisch korrekt sortierbar.

Nur Top-Level-Projekte (keine Unterprojekte), neueste zuerst. Boards ohne `created_at`
landen mit ts=None am Ende.
"""
import logging

from app.services.board_service import _get_parents
from app.storage.manifest_repository import ManifestRepository
from constants import CATEGORIES, STATUSES

log = logging.getLogger("dashboard.services.created")

_manifest = ManifestRepository()


def collect_created(limit: int = 500, category: str | None = None,
                    status: str | None = None) -> dict:
    """Top-Level-Projekte sortiert nach Erstelldatum (`created_at`), neueste zuerst."""
    manifest = _manifest.load()
    all_boards = manifest.get("boards", [])

    items = []
    for b in all_boards:
        if _get_parents(b):
            continue  # nur Top-Level-Projekte, keine Unterprojekte
        bid = b.get("id")
        if not bid:
            continue
        if category and b.get("category") != category:
            continue
        if status and b.get("status") != status:
            continue

        cat = CATEGORIES.get(b.get("category"), {})
        stat = STATUSES.get(b.get("status"), {})
        items.append({
            "id": bid,
            "name": b.get("name") or bid,
            "icon": b.get("icon") or cat.get("emoji", "📁"),
            "color": b.get("color") or cat.get("color", "#8892a4"),
            "category": b.get("category"),
            "category_label": cat.get("label"),
            "status": b.get("status"),
            "status_label": stat.get("label"),
            "status_emoji": stat.get("emoji"),
            "description": b.get("description"),
            "created_at": b.get("created_at"),
        })

    # created_at ist ISO-8601 → lexikalischer Vergleich = chronologisch; None ans Ende.
    items.sort(key=lambda p: p["created_at"] or "", reverse=True)
    n_with_date = sum(1 for p in items if p["created_at"])
    log.info("Created-Ansicht: %d/%d Top-Level-Projekte mit Erstelldatum",
             n_with_date, len(items))
    return {
        "projects": items[:limit],
        "total": len(items),
        "with_date": n_with_date,
    }

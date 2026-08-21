"""Globale KI-Ablehnungen — Muster, die KI-Vorschläge boardübergreifend blockieren.

Abgetrennt von ki_service.py (Karte opt_ki_service_split_0811): eigenständiger Kreis
(Sidecar-JSON + Sync-Board), unabhängig vom Advisor/Accept/Reject-Workflow einzelner Karten.

Schnittstelle
-------------
global_rejections() -> dict
global_reject(pattern, reason) -> dict
global_reactivate(reject_id, pattern) -> dict   # raises LookupError wenn nicht gefunden
"""
import json
import logging
import uuid
from datetime import datetime

from constants import KI_GLOBAL_BOARD_ID, KI_GLOBAL_REJECTIONS

from app.storage.atomic_write import write_json_atomic
from app.storage.board_repository import BoardRepository
from app.storage.locking import _lock_of, file_lock
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.ki_global_rejections")

_boards = BoardRepository()
_manifest = ManifestRepository()


def _load_global_rejections() -> list:
    if not KI_GLOBAL_REJECTIONS.exists():
        return []
    try:
        return json.loads(KI_GLOBAL_REJECTIONS.read_text())
    except Exception as e:
        # Fail-open ohne Log wäre gefährlich: eine kaputte Datei liefert eine leere Liste ->
        # bereits abgelehnte KI-Vorschläge kommen boardübergreifend wieder zurück, unbemerkt.
        log.error("Globale Ablehnungen %s unlesbar, falle auf [] zurück: %s",
                  KI_GLOBAL_REJECTIONS, e, exc_info=True)
        return []


def _save_global_rejections(data: list) -> None:
    with file_lock(_lock_of(KI_GLOBAL_REJECTIONS)):
        write_json_atomic(KI_GLOBAL_REJECTIONS, data)
    _sync_global_reject_board(data)


def _sync_global_reject_board(rejections: list) -> None:
    """Hält das Board ki-global-ablehnungen synchron mit der JSON-Liste."""
    active = [r for r in rejections if r.get("active", True)]
    inactive = [r for r in rejections if not r.get("active", True)]

    def make_card(r, is_active: bool) -> dict:
        return {
            "title":     r["pattern"][:80],
            "desc":      f"Grund: {r.get('reason','—')}\nErstellt: {r.get('created_at','')[:10]}",
            "label":     "#68d391" if not is_active else "#fc8181",
            "global_id": r["id"],
            "active":    is_active,
        }

    board = {
        "id":      KI_GLOBAL_BOARD_ID,
        "title":   "🚫 Globale KI-Ablehnungen",
        "columns": [
            {"id": "active",   "title": "🚫 Aktiv (blockiert)",
             "cards": [make_card(r, True) for r in active]},
            {"id": "inactive", "title": "✅ Reaktiviert",
             "cards": [make_card(r, False) for r in inactive]},
        ],
    }
    # Board-Write übers Repository (Lock + atomar); kein CLAUDE.md-Sync (Legacy-Verhalten)
    _boards.save(KI_GLOBAL_BOARD_ID, board, sync_claude_md=False)

    # Board im Manifest registrieren (nur wenn es fehlt — wie im Legacy)
    try:
        manifest = _manifest.load()
        if not any(b["id"] == KI_GLOBAL_BOARD_ID for b in manifest.get("boards", [])):
            def add_entry(m: dict):
                if any(b["id"] == KI_GLOBAL_BOARD_ID for b in m.get("boards", [])):
                    return  # Race: inzwischen registriert
                m.setdefault("boards", []).append({
                    "id":          KI_GLOBAL_BOARD_ID,
                    "name":        "🚫 Globale KI-Ablehnungen",
                    "description": "Globale Muster die KI-Vorschläge boardübergreifend blockieren.",
                    "icon":        "🚫",
                    "color":       "#fc8181",
                })
            _manifest.update(add_entry)
            log.info("Global-Ablehnungen-Board im Manifest registriert")
    except Exception as e:
        log.warning("Manifest-Update fehlgeschlagen: %s", e)
    log.debug("Global-Reject-Board synchronisiert: %d aktiv, %d reaktiviert", len(active), len(inactive))


def global_rejections() -> dict:
    return {"rejections": _load_global_rejections()}


def global_reject(pattern: str, reason: str) -> dict:
    """Fügt ein globales Ablehnungsmuster hinzu (dedupliziert, case-insensitive)."""
    rejections = _load_global_rejections()
    if any(r["pattern"].lower() == pattern.lower() for r in rejections):
        return {"status": "exists"}

    entry = {
        "id":         str(uuid.uuid4())[:8],
        "pattern":    pattern,
        "reason":     reason,
        "active":     True,
        "created_at": datetime.now().isoformat(),
    }
    rejections.append(entry)
    _save_global_rejections(rejections)
    log.info("Globale Ablehnung hinzugefügt: %r", pattern)
    return {"status": "ok", "entry": entry}


def global_reactivate(reject_id: str, pattern: str) -> dict:
    """Deaktiviert ein globales Muster (per id oder pattern).

    Raises:
        LookupError: kein passender Eintrag gefunden (HTTP 404).
    """
    rejections = _load_global_rejections()
    changed = False
    for r in rejections:
        if (reject_id and r.get("id") == reject_id) or (pattern and r["pattern"].lower() == pattern.lower()):
            r["active"] = False
            changed = True
            log.info("Globale Ablehnung deaktiviert: %r", r["pattern"])
            break
    if not changed:
        raise LookupError("Nicht gefunden")
    _save_global_rejections(rejections)
    return {"status": "ok"}

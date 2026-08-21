"""Karten aus einem Board in ein anderes Projekt übernehmen (Leichen-Feature).

Schnittstelle
-------------
move_cards_to_project(source_board_id, card_ids, target_board_id) -> dict

Eine Karte landet direkt im Ziel-Board (Backlog). Mehrere Karten werden als neues
Sub-Board (parent_ids:[target_board_id]) gesammelt — Wiederverwendung von
board_creation_service.create_board(fast=True), keine eigene Board-Anlage-Logik.
"""
import logging
from datetime import date

from app.services import board_creation_service, board_service
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.card_move")

_boards = BoardRepository()
_manifest = ManifestRepository()


def _source_name(board_id: str) -> str:
    entry = next((b for b in _manifest.load().get("boards", []) if b.get("id") == board_id), None)
    return (entry or {}).get("name") or board_id


def move_cards_to_project(source_board_id: str, card_ids: list[str], target_board_id: str) -> dict:
    """Karten von source_board_id nach target_board_id übernehmen.

    Bei genau einer card_id landet sie direkt im Ziel-Board. Bei mehreren wird
    vorher ein neues Sub-Board unter target_board_id angelegt und die Karten
    landen dort — das Ziel-Board selbst bleibt unangetastet.

    Returns:
        {"status": "ok", "moved": [...], "not_found": [...],
         "target_board_id": <tatsächliches Ziel>, "created_subboard": <id>|None}
    Raises:
        ValueError: card_ids leer, oder source_board_id == target_board_id.
        FileNotFoundError: Quell- oder Ziel-Board existiert nicht.
    """
    card_ids = list(dict.fromkeys(card_ids))  # Duplikate raus, Reihenfolge erhalten
    if not card_ids:
        raise ValueError("card_ids darf nicht leer sein")
    if source_board_id == target_board_id:
        raise ValueError("Quell- und Ziel-Board dürfen nicht identisch sein")
    if not _boards.exists(target_board_id):
        raise FileNotFoundError(f"Ziel-Board '{target_board_id}' nicht gefunden")

    created_subboard = None
    actual_target = target_board_id

    if len(card_ids) > 1:
        name = f"Übernommen aus {_source_name(source_board_id)} ({date.today().isoformat()})"
        result = board_creation_service.create_board({
            "name": name, "fast": True, "parent_ids": [target_board_id], "icon": "📂",
        })
        created_subboard = result["id"]
        actual_target = created_subboard
        log.info("Sub-Board '%s' für Karten-Übernahme aus '%s' angelegt (Ziel-Parent '%s')",
                 created_subboard, source_board_id, target_board_id)

    try:
        result = _boards.move_cards(source_board_id, actual_target, card_ids)
    except Exception:
        if created_subboard:
            log.warning("move_cards fehlgeschlagen — räume verwaistes Sub-Board '%s' auf",
                        created_subboard)
            try:
                board_service.delete_board(created_subboard)
            except Exception as cleanup_err:
                log.error("Aufräumen von Sub-Board '%s' fehlgeschlagen: %s",
                          created_subboard, cleanup_err)
        raise

    log.info("Karten-Übernahme '%s' -> '%s': %d verschoben, %d nicht gefunden",
             source_board_id, actual_target, len(result["moved"]), len(result["not_found"]))
    return {
        "status": "ok",
        "moved": result["moved"],
        "not_found": result["not_found"],
        "target_board_id": actual_target,
        "created_subboard": created_subboard,
    }

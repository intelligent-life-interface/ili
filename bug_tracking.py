"""\nbug_tracking.py — Fehlerverfolgung-Funktionen\nAutogeneriert von script_splitter.py\n"""
import logging
from constants import _BUG_BOARD_KEYWORDS
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.bug_tracking")


def _find_bugs_board(text: str, context_board_id: str) -> tuple[str, str]:
    """Findet das passende Bug-Board anhand von Kontext und Keyword-Matching.
    Gibt (board_id, board_name) zurück."""
    boards    = ManifestRepository().load().get("boards", [])
    board_map = {b["id"]: b.get("name", b["id"]) for b in boards}
    log.debug(f"_find_bugs_board: text={text[:60]!r}, context={context_board_id!r}")

    # Wenn Context-Board bereits ein Bug-Board ist, direkt verwenden
    if context_board_id and context_board_id in board_map and "bug" in context_board_id.lower():
        log.debug(f"Context ist Bug-Board: {context_board_id}")
        return context_board_id, board_map[context_board_id]

    # Basis-Projekt aus Context-Board extrahieren und Bug-Board ableiten
    if context_board_id:
        base = context_board_id
        for suffix in ["-app-bugs", "-bugs", "-app-features", "-features", "-app-ui",
                       "-ui", "-app-api", "-api", "-app-auth", "-auth", "-app"]:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        for candidate in [f"{base}-app-bugs", f"{base}-bugs"]:
            if candidate in board_map:
                log.debug(f"Context-Basis '{base}' → Bug-Board: {candidate}")
                return candidate, board_map[candidate]

    # Keyword-Matching auf Nachrichtentext
    text_lower = text.lower()
    for keywords, board_id in _BUG_BOARD_KEYWORDS:
        for kw in keywords:
            if kw in text_lower:
                if board_id in board_map:
                    log.debug(f"Keyword '{kw}' → Bug-Board: {board_id}")
                    return board_id, board_map[board_id]
                break

    # Fallback: allgemeines Home-Stack Bug-Board
    fallback = "home-stack-bugs"
    log.debug(f"Kein Match → Fallback: {fallback}")
    return fallback, board_map.get(fallback, "Home Stack – Bughandling")

# KANBAN_TOOLS ENTFERNT (opt_altlasten_0806): war ein toter Claude-Function-Calling-
# Toolblock, dessen einziger Konsument das ebenfalls entfernte kanban_tools.py war.
# Beide liegen jetzt in archiv/. bug_tracking.py bleibt nur wegen _find_bugs_board
# (aktiver Import in app/services/chat_service.py).

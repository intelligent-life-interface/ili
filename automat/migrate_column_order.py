#!/usr/bin/env python3
"""One-time migration (2026-08-18): fixes existing column order on all boards to
matches die Spaltenreihenfolge-Regel (card_41adaed5) — 'Wartet' left of 'In Bearbeitung', 'Erledigt'/
'Archiv' always rightmost. Run once by hand: python3 migrate_column_order.py [--dry-run]
"""
import argparse
import logging
import sys

from automat_lib import list_boards_all, get_board, save_board, reorder_columns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate_column_order")

# meine-aufgaben: Spalte '📥 Zu erledigen' (id 'todo') matcht die bestehende
# _col_kind()-Heuristik fälschlich als 'done' (Teilstring 'erledig' in 'erledigen'),
# '⏳ Wartet' (Sanduhr-Emoji) matcht 'parked' nicht (Heuristik erkennt nur '⏸').
# Reorder würde 'Zu erledigen' von Position 1 auf Position 3 verschieben — falsch für
# dieses handgebaute Board. Kein Fall des gemeldeten Bugs (das ist keine vom Automat
# angehängte Wartet/Archiv-Spalte) — bewusst ausgenommen statt die geteilte Heuristik
# projektübergreifend zu verändern.
SKIP_BOARDS = {"meine-aufgaben"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nicht speichern")
    args = parser.parse_args()

    boards = list_boards_all()
    log.info("Boards gesamt: %d", len(boards))
    changed = 0
    for entry in boards:
        slug = entry.get("id")
        if not slug or slug in SKIP_BOARDS:
            continue
        try:
            board = get_board(slug)
        except Exception as e:
            log.warning("Board %s nicht ladbar: %s", slug, e)
            continue
        cols = board.get("columns", [])
        new_cols = reorder_columns(cols)
        if [c.get("id") for c in new_cols] == [c.get("id") for c in cols]:
            continue
        changed += 1
        old_order = [c.get("title") for c in cols]
        new_order = [c.get("title") for c in new_cols]
        log.info("Board %s: %s -> %s", slug, old_order, new_order)
        if not args.dry_run:
            board["columns"] = new_cols
            save_board(slug, board)
    log.info("Fertig. %d von %d Boards geändert%s.", changed, len(boards),
              " (dry-run, nichts gespeichert)" if args.dry_run else "")


if __name__ == "__main__":
    sys.exit(main())

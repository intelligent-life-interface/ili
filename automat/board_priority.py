#!/usr/bin/env python3
"""Board-Priorisierung für Automat: welche Boards zuerst abarbeiten.

Strategie: Der Automat arbeitet Boards in PRIORITÄTSREIHENFOLGE ab statt willkürlich.
Eine Karte mit 'hoch' im höchstpiorisierten Board wird vor einer 'mittel'-Karte in
einem anderen Board bearbeitet.

Rankinglogik:
  1. Hat das Board eine Karte mit user_prio='hoch'? → Board ist 'hoch'
  2. Sonst: höchste KI-Prio der offenen Karten (Cache).
  3. Fallback-Heuristik (Bug-Stichworte, Deadlines).
  4. Keine User-Werte überschreiben, nur abfragen.

Cache: boards-priority.json (1h TTL), begrenzt auf die 50 Auto-Boards.
Performance: read-only prio_suggester, kein Schreiben ins Board.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Importiere automat_lib vor prio_suggester, damit prio_suggester nicht
# die bestehenden Dashboard-Abhängigkeiten per sys.path ziehen muss.
sys.path.insert(0, str(Path(__file__).parent))

import automat_lib as lib

log = logging.getLogger("kanban_automat.board_priority")

PRIORITY_ORDER = {"hoch": 0, "mittel": 1, "niedrig": 2, None: 3}
CACHE_PATH = lib.STATE_DIR / "board_priority_cache.json"
CACHE_TTL_SECONDS = 3600  # 1h


def _load_cache() -> dict:
    """Lade den Priority-Cache oder {}."""
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text())
        age = time.time() - data.get("_timestamp", 0)
        if age < CACHE_TTL_SECONDS:
            return data
        log.debug("board_priority: Cache abgelaufen (%ds alt)", int(age))
    except Exception as e:
        log.warning("board_priority: Cache unlesbar: %s", e)
    return {}


def _save_cache(data: dict) -> None:
    """Speichere den Priority-Cache."""
    data["_timestamp"] = time.time()
    try:
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        os.replace(tmp, CACHE_PATH)
    except Exception as e:
        log.warning("board_priority: Cache-Speicherung fehlgeschlagen: %s", e)


def _heuristic_priority(card: dict) -> str:
    """Fallback-Heuristik für Kartenprioritäten (keine Claude-Abo-Nutzung).

    Genutzt für Boards ohne User-Prioritäten und wenn prio_suggester nicht
    verfügbar ist. Schlagworte: bug, fehler, fix, down, sicherheit, etc.
    """
    title = (card.get("title") or "").lower()
    desc = (card.get("description") or "").lower()
    txt = title + " " + desc

    # High-Priority-Muster
    if any(w in txt for w in ["bug", "fehler", "fix", "crash", "down", "ausfall",
                               "sicherheit", "security", "dringend", "asap",
                               "kritisch", "blocker", "frist"]):
        return "hoch"
    # Low-Priority-Muster
    if any(w in txt for w in ["idee", "später", "evtl", "nice", "optional",
                               "irgendwann", "kosmetik", "cleanup", "refactor", "doku"]):
        return "niedrig"
    return "mittel"


def board_priority_score(slug: str) -> tuple[int, str]:
    """Gibt einen Sortierschlüssel für ein Board zurück: (prio_order, slug).

    prio_order ∈ [0..3] wobei 0='hoch' ist (wird ZUERST arbeitet).
    Intern wird gecacht und per Heuristik gearbeitet (keine Claude-Calls,
    nur read-only Abfrage bestehender Prioritäten auf Karten).
    """
    # Cache prüfen
    cache = _load_cache()
    cached = cache.get(slug)
    if cached:
        log.debug("board_priority: %s aus Cache → %s", slug, cached)
        return (PRIORITY_ORDER.get(cached, 3), slug)

    # Board laden und Priorität bestimmen
    try:
        board = lib.get_board(slug)
    except Exception as e:
        log.warning("board_priority: %s nicht ladbar: %s — fallback", slug, e)
        return (3, slug)  # niedrigste Priorität bei Fehler

    max_prio = None
    has_user_high = False

    # Durchsuche alle abarbeitbaren Karten
    try:
        cards = lib.actionable_cards(board)
        for col, card in cards:
            user_prio = card.get("priority")
            if user_prio in ("hoch", "mittel", "niedrig"):
                # User hat diese Karte priorisiert
                if user_prio == "hoch":
                    has_user_high = True
                    break
                if max_prio is None:
                    max_prio = user_prio
            else:
                # Heuristik für Karten ohne Priorität
                guess = _heuristic_priority(card)
                if guess == "hoch":
                    has_user_high = True
                    break
                if max_prio is None or PRIORITY_ORDER[guess] < PRIORITY_ORDER[max_prio]:
                    max_prio = guess
    except Exception as e:
        log.warning("board_priority: %s Kartenlesen fehlgeschlagen: %s", slug, e)

    # Resultat: hat das Board High-Priority-Karten?
    final_prio = "hoch" if has_user_high else (max_prio or "mittel")
    order_idx = PRIORITY_ORDER.get(final_prio, 3)

    log.debug("board_priority: %s → %s (order=%d)", slug, final_prio, order_idx)

    # Cache aktualisieren
    cache[slug] = final_prio
    _save_cache(cache)

    return (order_idx, slug)


def prioritize_boards(boards: list[dict]) -> list[dict]:
    """Sortiere Auto-Boards nach Priorität (high zuerst).

    Nutzt intern board_priority_score(). Respektiert alle bestehenden
    User-Prioritäten auf den Karten, überschreibt nichts.

    Args:
        boards: list of board dicts (von auto_boards())

    Returns:
        Sortierte Liste (high priority zuerst)
    """
    if not boards:
        return boards

    ranked = []
    for b in boards:
        slug = b.get("id")
        if not slug:
            continue
        order_idx, _ = board_priority_score(slug)
        ranked.append((order_idx, slug, b))

    # Sortiere nach order_idx, dann slug
    ranked.sort(key=lambda x: (x[0], x[1]))
    result = [b for _, _, b in ranked]

    if result:
        log.info("board_priority: %d Boards sortiert — Top 3: %s",
                 len(result), ", ".join(r.get("id", "?") for r in result[:3]))

    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Board-Priorisierung debuggen")
    ap.add_argument("--clear-cache", action="store_true", help="Cache löschen")
    ap.add_argument("--show-cache", action="store_true", help="Cache anzeigen")
    ap.add_argument("--score", metavar="BOARD", help="Priorität eines Boards abfragen")
    args = ap.parse_args()

    if args.clear_cache:
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
            print("Cache gelöscht")
        sys.exit(0)

    if args.show_cache:
        cache = _load_cache()
        if cache:
            print("Board-Priority-Cache:")
            for k, v in sorted(cache.items()):
                if k != "_timestamp":
                    print(f"  {k}: {v}")
        else:
            print("(leer)")
        sys.exit(0)

    if args.score:
        order_idx, slug = board_priority_score(args.score)
        print(f"{slug}: order={order_idx} (0=hoch, 3=niedrig)")
        sys.exit(0)

    ap.print_help()

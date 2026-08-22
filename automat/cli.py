#!/usr/bin/env python3
"""CLI: status() und main() — Kommandozeilen-Interface für den Orchestrator."""
import sys
import fcntl
import argparse
from datetime import datetime
from pathlib import Path

import automat_lib as lib
import models
import review
from automat_lib import logger, now_iso

from budget import capacity, starts_today, MAX_STARTS_PER_DAY
from scheduler import tick

LOCK_FILE = lib.STATE_DIR / "orchestrator.lock"


def status() -> None:
    """Zeigt den aktuellen Zustand des Orchestrators."""
    live = lib.live_workers()
    print(f"== Kanban-Automat — {now_iso()} ==")
    print(f"Kapazität jetzt: {capacity(datetime.now().hour)} | "
          f"Starts heute: {starts_today()}/{MAX_STARTS_PER_DAY}")
    print(f"Lebende Worker ({len(live)}):")
    for w in live:
        m = models.label(w.get("model", "?"))
        soll = w.get("model_target")
        if soll and soll != w.get("model"):
            m += f" (Soll {models.label(soll)} → Review folgt)"
        print(f"  - {w['board']} [{w.get('kind', 'dev')}] | card={w.get('card_id')} | "
              f"modell={m} | pid={w['pid']} | seit {w.get('started_at')}")
    pend = review.boards_with_pending()
    print(f"Offene Reviews ({len(pend)}): {', '.join(pend) or '-'}")
    ab = lib.auto_boards()
    print(f"Auto-Boards ({len(ab)}): {', '.join(b.get('id') for b in ab) or '-'}")
    print("Modelle je Board: python3 models.py --list | Statistik: python3 stats.py --summary")


def main() -> int:
    """Kommandozeilen-Einstiegspunkt für orchestrator.py."""
    ap = argparse.ArgumentParser(description="Kanban-Automat Orchestrator")
    ap.add_argument("--tick", action="store_true", help="ein Watchdog-Durchlauf")
    ap.add_argument("--dry-run", action="store_true", help="nur loggen, keine Worker starten")
    ap.add_argument("--status", action="store_true", help="Zustand anzeigen")
    args = ap.parse_args()

    if args.status:
        status()
        return 0
    if not args.tick:
        ap.print_help()
        return 1

    # Globaler Lock: nie zwei Ticks gleichzeitig
    LOCK_FILE.touch(exist_ok=True)
    lock = open(LOCK_FILE, "r+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.info("Anderer Tick läuft noch (Lock) — überspringe.")
        return 0
    try:
        tick(dry=args.dry_run)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
    return 0

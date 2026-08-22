#!/usr/bin/env python3
"""models — Modell-Stufen des Kanban-Automaten (Soll-Modell pro Board + Downgrade).

Regelwerk (23.07.2026):
  * Jedes Kanban hat ein **Soll-Modell** (Manifest-Feld `model`), Default `claude-sonnet-5`.
  * Werden mehrere Boards **gleichzeitig** entwickelt, arbeitet der zusätzliche Worker
    eine Stufe **tiefer** (schont Abo-Limits und hält mehr Tasks parallel am Laufen).
  * Wurde tiefer entwickelt als das Board-Soll, prüft anschliessend ein **Review-Worker**
    mit dem Soll-Modell die Arbeit (siehe review.py).

Stufen (aufsteigend). Nur diese IDs sind gültig — `claude -p --model <id>`:
  0 claude-haiku-4-5   günstig, für Doku-/Notiz-/Sammelboards
  1 claude-sonnet-5    Standard für Code-Projekte
  2 claude-opus-4-8    komplexe/heikle Projekte
  3 claude-fable-5     nur manuell: sehr lange autonome Läufe (teuerste Stufe)

Die automatische Zuordnung (assign_models.py) vergibt NIE Stufe 3 — nur Manager.

Debug: alle Entscheidungen landen im automat-Log (logger 'automat').
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import automat_lib as lib

logger = lib.logger

# ── Stufen ──────────────────────────────────────────────────────────────────
TIERS: list[str] = [
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "claude-fable-5",
]
LABELS: dict[str, str] = {
    "claude-haiku-4-5": "Haiku 4.5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-opus-4-8": "Opus 4.8",
    "claude-fable-5": "Fable 5",
}
# Fallback, wenn ein Board kein `model` gesetzt hat (bzw. ein unbekanntes).
DEFAULT_MODEL = os.getenv("AUTOMAT_DEFAULT_MODEL", "claude-sonnet-5")
# Höchste Stufe, die der Automat selbstständig für Reviews hochschaltet.
MAX_AUTO_TIER = int(os.getenv("AUTOMAT_MAX_AUTO_TIER", "2"))  # = Opus 4.8
# Board bekommt beim nächsten Start KEIN Downgrade (nach Review-Nacharbeit gesetzt).
NO_DOWNGRADE_FILE = lib.STATE_DIR / "no_downgrade.json"


def tier(model: str | None) -> int:
    """Stufen-Index eines Modells; unbekannt -> Stufe des Default-Modells."""
    if model in TIERS:
        return TIERS.index(model)
    return TIERS.index(DEFAULT_MODEL)


def normalize(model: str | None) -> str:
    """Beliebige Eingabe (auch Alias 'opus'/'sonnet'/'haiku'/'fable') -> gültige Modell-ID."""
    if not model:
        return DEFAULT_MODEL
    m = str(model).strip().lower()
    if m in TIERS:
        return m
    alias = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5",
             "opus": "claude-opus-4-8", "fable": "claude-fable-5"}
    if m in alias:
        return alias[m]
    logger.warning("models.normalize: unbekanntes Modell '%s' -> Default %s", model, DEFAULT_MODEL)
    return DEFAULT_MODEL


def label(model: str) -> str:
    return LABELS.get(model, model)


# ── Soll-Modell je Board ────────────────────────────────────────────────────
def board_model(slug: str, boards: list[dict] | None = None) -> str:
    """Soll-Modell des Boards aus dem Manifest-Feld `model`.

    Nicht gesetzt -> Default. (Bewusst KEINE Vererbung über parent_ids: das Modell
    hängt an der Art der Arbeit im Board, nicht am Mutterprojekt.)"""
    try:
        # all=1: Unterprojekte fehlen im Default von GET /boards
        entries = boards if boards is not None else lib.list_boards_all()
    except Exception as e:
        logger.warning("board_model(%s): Manifest nicht lesbar (%s) -> Default", slug, e)
        return DEFAULT_MODEL
    for b in entries:
        if b.get("id") == slug:
            return normalize(b.get("model"))
    return DEFAULT_MODEL


# ── Downgrade bei Parallelbetrieb ───────────────────────────────────────────
def _no_downgrade_state() -> dict:
    try:
        return json.loads(NO_DOWNGRADE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def mark_no_downgrade(slug: str) -> None:
    """Nach Review-Nacharbeit: der nächste Lauf dieses Boards läuft auf Soll-Stufe."""
    st = _no_downgrade_state()
    st[slug] = datetime.now(timezone.utc).isoformat()
    try:
        NO_DOWNGRADE_FILE.write_text(json.dumps(st, indent=2), "utf-8")
        logger.info("models: %s -> nächster Lauf ohne Downgrade (Review-Nacharbeit)", slug)
    except Exception as e:
        logger.error("mark_no_downgrade(%s) fehlgeschlagen: %s", slug, e)


def _consume_no_downgrade(slug: str) -> bool:
    """Prüft + verbraucht das Flag (gilt nur für den nächsten Start)."""
    st = _no_downgrade_state()
    if slug not in st:
        return False
    st.pop(slug, None)
    try:
        NO_DOWNGRADE_FILE.write_text(json.dumps(st, indent=2), "utf-8")
    except Exception as e:
        logger.error("_consume_no_downgrade(%s): %s", slug, e)
    return True


def choose_model(slug: str, parallel: int, boards: list[dict] | None = None,
                 dry: bool = False) -> tuple[str, str, str]:
    """Modell für den nächsten Dev-Worker.

    parallel = Anzahl bereits laufender/in diesem Tick gestarteter Worker.
    Rückgabe: (model_used, model_target, grund).
    Downgrade genau EINE Stufe (nicht kumulativ) und nie unter Stufe 0.
    """
    target = board_model(slug, boards)
    if parallel <= 0:
        return target, target, "einziger Worker — Soll-Modell"
    if not dry and _consume_no_downgrade(slug):
        return target, target, "kein Downgrade (Nacharbeit nach Review)"
    if dry and slug in _no_downgrade_state():
        return target, target, "kein Downgrade (Nacharbeit nach Review)"
    t = tier(target)
    if t == 0:
        return target, target, "bereits unterste Stufe"
    used = TIERS[t - 1]
    return used, target, f"{parallel} Worker parallel — eine Stufe unter {label(target)}"


def needs_review(model_used: str, model_target: str) -> bool:
    """Review nur, wenn tiefer entwickelt wurde als das Board-Soll."""
    return tier(model_used) < tier(model_target)


def review_model(model_target: str) -> str:
    """Prüf-Modell: das Board-Soll, aber höchstens die vom Automaten erlaubte Stufe
    (Fable 5 wird nie automatisch gestartet)."""
    return TIERS[min(tier(model_target), MAX_AUTO_TIER)]


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Modell-Stufen des Automaten")
    ap.add_argument("--board", help="Soll-Modell eines Boards zeigen")
    ap.add_argument("--parallel", type=int, default=0, help="simulierte parallele Worker")
    ap.add_argument("--list", action="store_true", help="alle Boards mit Modell auflisten")
    a = ap.parse_args()
    if a.list:
        for b in sorted(lib.list_boards_all(), key=lambda x: x.get("id", "")):
            if not b.get("auto"):
                continue
            m = normalize(b.get("model"))
            flag = "" if b.get("model") else "  (Default)"
            print(f"{b.get('id'):40s} {label(m)}{flag}")
        return 0
    if a.board:
        used, target, why = choose_model(a.board, a.parallel, dry=True)
        print(f"Board {a.board}: Soll={label(target)} | jetzt={label(used)} ({why})")
        if needs_review(used, target):
            print(f"  -> Review danach durch {label(review_model(target))}")
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())

"""Budget-Gate für die normale Kartenarbeit (tick() Schritt b), nach Board-Priorität.

Anlass (29.07.26): chile-spanisch lief seit dem 20.07. praktisch durchgehend
(bis zu 79 Worker-Sessions/Tag) und hat allein 75% des Tages-Tokenverbrauchs gefressen.
Das Tages-Startlimit (budget.MAX_STARTS_PER_DAY) zählt nur Starts, nicht Tokens — ein
Board mit teuren, langen Sessions konnte das echte Budget leerräumen, ohne dass die
Zähl-Drossel je anschlug.

Deshalb hier ein zweites, tokenbasiertes Gate, das den echten Verbrauch prüft — analog
zu fable_gate.py und aus demselben Grund OHNE eigene Budget-Rechnung: die Wahrheit
liegt im Dashboard (`GET /api/budget`, `app/services/budget_service.check_allowance`).

Priorität kommt aus dem Manifest-Feld `automat_priority` (Board-PATCH-Whitelist,
board_service.py): "high" | "normal" | "low", fehlt = "normal".
  - high:   Gate übersprungen — läuft immer (für wirklich wichtige/dringende Boards).
  - normal: läuft, ausser /api/budget meldet "allowed": False (Tages-Tranche im
            aktuellen Fenster bereits ausgeschöpft) — das ist der eigentliche Fix:
            vorher gab es für die normale Kartenarbeit GAR keinen Token-Check.
  - low:    läuft nur, solange die Tranche im aktuellen Fenster noch komfortabel Kopf
            hat (window_pct < LOW_HEADROOM_PCT) — für Boards wie chile-spanisch, die
            gerne dauerhaft weiterarbeiten dürfen, aber nicht auf Kosten anderer.

Budget nicht abrufbar (Dashboard down/Timeout): "normal" bleibt erlaubt (kein Blockieren
des ganzen Automaten wegen eines transienten API-Fehlers), "low" wird vorsichtshalber
blockiert (genau die Stufe, deren Zweck "nur wenn Budget vorhanden" ist).
"""
from __future__ import annotations

import os

import automat_lib as lib
from automat_lib import logger

PRIORITIES = {"high", "normal", "low"}
DEFAULT_PRIORITY = "normal"

# Ab welchem Anteil der Tages-Tranche im aktuellen Fenster (window_pct, 0..100+) ein
# "low"-Board pausiert. 50 = läuft nur in der günstigeren Tageshälfte, mirrort
# fable_gate.FABLE_HEADROOM (dort 0.5 der Tranche).
LOW_HEADROOM_PCT = float(os.getenv("AUTOMAT_LOW_PRIORITY_HEADROOM_PCT", "50"))


def board_priority(board: dict) -> str:
    """Normalisierte Priorität eines Manifest-Eintrags (auto_boards()-Element)."""
    val = str(board.get("automat_priority") or "").strip().lower()
    return val if val in PRIORITIES else DEFAULT_PRIORITY


def fetch_budget() -> dict | None:
    """Budget-Status vom Dashboard holen (/api/budget). None bei Fehler.

    Einmal pro Tick aufrufen (nicht pro Board) — der Wert ändert sich innerhalb
    eines 5-Minuten-Ticks nicht nennenswert, und budget_service cached ohnehin 60s."""
    try:
        return lib._req("GET", "/api/budget", timeout=15)
    except Exception as e:
        logger.warning("priority_gate: /api/budget nicht erreichbar (%s)", e)
        return None


def allowed(board: dict, budget: dict | None) -> tuple[bool, str]:
    """Darf dieses Board JETZT normale Kartenarbeit bekommen?

    `budget` = vorab per fetch_budget() geholter Status (einmal pro Tick), damit hier
    kein weiterer API-Call pro Board nötig ist."""
    prio = board_priority(board)

    if prio == "high":
        return True, "hohe Priorität — Budget-Gate übersprungen"

    if budget is None:
        if prio == "low":
            return False, "niedrige Priorität + Budget-Status nicht abrufbar — pausiert"
        return True, "Budget-Status nicht abrufbar — normale Priorität bleibt erlaubt"

    if not budget.get("enforce", True):
        return True, "budget_enforce=false — Gate wirkungslos, immer erlaubt"

    if prio == "normal":
        if budget.get("allowed", True):
            return True, budget.get("reason", "Budget OK")
        return False, f"Tages-Tranche ausgeschöpft: {budget.get('reason', '?')}"

    # prio == "low"
    window_pct = float(budget.get("window_pct", 0) or 0)
    if not budget.get("allowed", True):
        return False, f"Tages-Tranche ausgeschöpft: {budget.get('reason', '?')}"
    if window_pct >= LOW_HEADROOM_PCT:
        return False, (f"niedrige Priorität: {window_pct:.0f}% der Tranche schon genutzt "
                        f"(Schwelle {LOW_HEADROOM_PCT:.0f}%)")
    return True, f"niedrige Priorität: erst {window_pct:.0f}% der Tranche genutzt — Kopf frei"


if __name__ == "__main__":
    import json
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    b = fetch_budget()
    print(json.dumps({"budget": b}, ensure_ascii=False, indent=2))
    for prio in sorted(PRIORITIES):
        ok, reason = allowed({"automat_priority": prio}, b)
        print(f"{prio:8s} -> allowed={ok}  ({reason})")

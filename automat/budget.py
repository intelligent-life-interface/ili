#!/usr/bin/env python3
"""Budget & Drossel: Kapazitäts-Management und Tages-Startlimit."""
import os
import json
from datetime import datetime, timezone
from pathlib import Path

import automat_lib as lib
import config as cfg_mod
from automat_lib import logger, now_iso

LIMITS = lib.LIMITS
AI_CONFIG = Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "ai_config.json"
STARTS_FILE = lib.STATE_DIR / "starts.json"
REFUNDS_FILE = lib.STATE_DIR / "refunds.json"
LAST_START_FILE = lib.STATE_DIR / "last_start.json"
BOARD_COOLDOWN_S = LIMITS["board_cooldown_s"]
NOOP_REFUND_S = LIMITS["noop_refund_s"]
MAX_STARTS_PER_DAY = LIMITS["max_starts_per_day"]
MAX_REFUNDS_PER_DAY = LIMITS["max_refunds_per_day"]
DEFAULT_WINDOWS = [{"from": 10, "to": 22, "max_pct": 50}, {"from": 22, "to": 10, "max_pct": 80}]


def age_s(iso: str | None) -> float | None:
    """Alter eines ISO-Zeitstempels in Sekunden (UTC). Gibt None zurück wenn iso ungültig."""
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return None


def _current_window(hour: int) -> dict:
    """Aktives Budget-Zeitfenster aus ai_config.json (Tag/Nacht), Fallback DEFAULT."""
    try:
        wins = json.loads(AI_CONFIG.read_text()).get("budget_windows") or DEFAULT_WINDOWS
    except Exception as e:
        logger.debug("ai_config nicht lesbar (%s) -> Default-Fenster", e)
        wins = DEFAULT_WINDOWS
    for w in wins:
        f, t = int(w.get("from", 0)), int(w.get("to", 24))
        if f <= t:
            if f <= hour < t:
                return w
        else:  # über Mitternacht
            if hour >= f or hour < t:
                return w
    return {"max_pct": 50}


def capacity(hour: int) -> int:
    """Erlaubte Parallelität nach Tageszeit ("mehrere Tasks aktiv", User 16.07.26).

    Das Fenster kommt weiterhin aus ai_config.json (budget_windows); ein Fenster mit
    viel Kontingent (max_pct >= 80) gilt als Nachtfenster. Die Zahl der Worker steht
    seit 23.07.26 explizit in den Limits (parallel_day/parallel_night, GUI-einstellbar)
    statt hartkodiert. Hart gedeckelt via MAX_PARALLEL.
    """
    pct = int(_current_window(hour).get("max_pct", 50))
    cap = LIMITS["parallel_night"] if pct >= 80 else LIMITS["parallel_day"]
    return min(cap, lib.MAX_PARALLEL)


def daily_token_limit() -> int:
    """Tägliches Token-Limit aus Wochenbudget-Aufteilung.

    Wochenbudget wird durch budget_week_divisions (default 8) geteilt.
    Bei divisions=8 und normalem 7-Tage-Verbrauch bleibt ca. 1 Tag Reserve.
    Gibt 0 zurück, wenn keine gültige Konfigration.
    """
    cfg = cfg_mod.get_config()
    limit = cfg.get("budget_daily_max_tokens", 0)
    logger.debug("daily_token_limit: %d (aus Wochenbudget %d / %d)",
                 limit, cfg["budget_week_tokens"], cfg["budget_week_divisions"])
    return limit


def starts_today() -> int:
    """Anzahl der Worker, die heute gestartet wurden (aus starts.json)."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        d = json.loads(STARTS_FILE.read_text())
        return int(d.get(today, 0))
    except Exception:
        return 0


def bump_starts() -> None:
    """Erhöht den Tages-Startzähler um 1."""
    today = datetime.now().strftime("%Y-%m-%d")
    d = {}
    try:
        d = json.loads(STARTS_FILE.read_text())
    except Exception:
        pass
    d = {today: int(d.get(today, 0)) + 1}  # nur heute behalten
    STARTS_FILE.write_text(json.dumps(d))


def refunds_today() -> int:
    """Anzahl der Refunds (No-Op-Starts zurück erstattet), die heute gewährt wurden."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        return int(json.loads(REFUNDS_FILE.read_text()).get(today, 0))
    except Exception:
        return 0


def refund_start(reason: str) -> None:
    """Nimmt einen Start vom Tageszähler zurück (No-Op-Lauf soll das Limit nicht fressen).
    Gedeckelt auf MAX_REFUNDS_PER_DAY — sonst würde eine Crash-Schleife das Tageslimit
    komplett aushebeln (jeder Kurz-Lauf erstattet sich selbst zurück)."""
    today = datetime.now().strftime("%Y-%m-%d")
    if refunds_today() >= MAX_REFUNDS_PER_DAY:
        logger.warning("Refund-Tageslimit (%d) erreicht — Start bleibt gezählt (%s)",
                       MAX_REFUNDS_PER_DAY, reason)
        return
    REFUNDS_FILE.write_text(json.dumps({today: refunds_today() + 1}))
    try:
        d = json.loads(STARTS_FILE.read_text())
    except Exception:
        d = {}
    before = int(d.get(today, 0))
    d = {today: max(0, before - 1)}
    STARTS_FILE.write_text(json.dumps(d))
    logger.info("Start zurückerstattet (%s): Tageszähler %d -> %d", reason, before, d[today])


def last_board_starts() -> dict:
    """Lazim der letzten Starts pro Board (aus last_start.json)."""
    try:
        return json.loads(LAST_START_FILE.read_text())
    except Exception:
        return {}


def mark_board_start(slug: str) -> None:
    """Merkt auf, dass das Board gerade gestartet wurde (ISO-Zeitstempel)."""
    d = last_board_starts()
    d[slug] = lib.now_iso()
    LAST_START_FILE.write_text(json.dumps(d))


def board_in_cooldown(slug: str) -> bool:
    """True, wenn das Board vor weniger als BOARD_COOLDOWN_S schon gestartet wurde
    (Schutz gegen Crash-Schleifen im 5-min-Takt)."""
    age = age_s(last_board_starts().get(slug))
    return age is not None and age < BOARD_COOLDOWN_S

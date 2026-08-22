"""Fable-Optimier-Gate: darf der Automat heute noch das teure Modell Fable 5 einsetzen?

Idee (24.07.26): „Wenn noch Kapazität übrig ist, die sonst verfällt, Fable verwenden — und
ganze Projekte an Fable senden, um sie zu optimieren." Das echte Abo-Rate-Limit ist nicht
abfragbar; der beste messbare Proxy ist das **Wochen-Token-Budget** (`ai_config.json
budget_week_tokens`, ausgewertet von `dashboard/app/services/budget_service.check_allowance`).

**Trigger:** täglich, solange der wöchentliche Verbrauch auf den Tag gerechnet noch
nicht ausgeschöpft ist. `check_allowance` liefert dafür genau zwei Zahlen:
  * `day_allowance_tokens` = (Wochenlimit − Verbrauch vor heute) / Resttage der Woche
  * `today_used`           = heute bereits verbrauchte Tokens
Ist `today_used` (+ Sicherheitspuffer) noch unter der Tagestranche, gibt es Kopf, der sonst
zum Wochenende verfällt → Fable-Fenster offen.

Zusätzlich ein hartes Tageslimit an Fable-Optimierläufen (Default 1), damit ein einzelner
teurer Modus das Budget nicht doch leerräumt. State in `state/fable_runs.json`.

Bewusst KEINE eigene Budget-Rechnung hier — die Wahrheit liegt im Dashboard (`/api/budget`),
damit es nur eine Budget-Logik gibt.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import automat_lib as lib
import limits
from automat_lib import logger

FABLE_MODEL = os.getenv("AUTOMAT_FABLE_MODEL", "claude-fable-5")
# Anteil der Tagestranche, der frei bleiben muss, damit Fable startet (Puffer gegen
# Budget-Überschuss durch den teuren Lauf selbst). 0.5 = höchstens halbe Tranche verbraucht.
# Feintuning-Wert, selten geändert → bleibt reines Env (nicht im GUI-Panel).
FABLE_HEADROOM = float(os.getenv("AUTOMAT_FABLE_HEADROOM", "0.5"))

# An/Aus + Tageslimit kommen aus den GUI-schaltbaren Limits (limits.py → automat_limits.json,
# Panel /automat.html „⚙️ Drossel"), damit der Manager das ohne Unit-Edit steuern kann.
_LIM = limits.load()
FABLE_ENABLED = int(_LIM.get("fable_enabled", 0)) == 1
FABLE_MAX_RUNS_PER_DAY = int(_LIM.get("fable_max_runs_per_day", 1))

RUNS_FILE = lib.STATE_DIR / "fable_runs.json"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def fable_runs_today() -> int:
    try:
        return int(json.loads(RUNS_FILE.read_text()).get(_today(), 0))
    except Exception:
        return 0


def record_fable_run() -> None:
    """Einen verbrauchten Fable-Lauf für heute vermerken (best-effort)."""
    try:
        data = {}
        if RUNS_FILE.exists():
            data = json.loads(RUNS_FILE.read_text())
        if not isinstance(data, dict):
            data = {}
        data[_today()] = int(data.get(_today(), 0)) + 1
        # nur die letzten ~14 Tage behalten
        keys = sorted(data)
        for k in keys[:-14]:
            data.pop(k, None)
        RUNS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        logger.debug("fable_gate: Lauf vermerkt (%s = %s)", _today(), data[_today()])
    except Exception as e:
        logger.warning("fable_gate: record_fable_run fehlgeschlagen: %s", e)


def _budget() -> dict | None:
    """Budget-Status vom Dashboard holen (/api/budget). None bei Fehler = Gate zu."""
    try:
        return lib._req("GET", "/api/budget", timeout=15)
    except Exception as e:
        logger.warning("fable_gate: /api/budget nicht erreichbar (%s) — Fable bleibt aus", e)
        return None


def check() -> dict:
    """Entscheidet, ob JETZT ein Fable-Optimierlauf erlaubt ist.

    Rückgabe: {allowed: bool, reason: str, model: str, runs_today: int, budget: {...}|None}.
    Konservativ: jeder Unsicherheitsfall (Schalter aus, Budget nicht lesbar, enforce aus,
    Tranche schon halb verbraucht, Tageslauf schon gemacht) → allowed=False.
    """
    runs = fable_runs_today()
    base = {"allowed": False, "model": FABLE_MODEL, "runs_today": runs, "budget": None}

    if not FABLE_ENABLED:
        return {**base, "reason": "Fable-Modus ist aus (AUTOMAT_FABLE_ENABLED=0)"}

    if runs >= FABLE_MAX_RUNS_PER_DAY:
        return {**base, "reason": f"Tageslimit an Fable-Läufen erreicht ({runs}/{FABLE_MAX_RUNS_PER_DAY})"}

    b = _budget()
    if b is None:
        return {**base, "reason": "Budget-Status nicht abrufbar"}
    base["budget"] = {k: b.get(k) for k in
                      ("week", "week_pct", "day_allowance_tokens", "today_used", "enforce")}

    if not b.get("enforce", True):
        # Ohne Budget-Enforcement gibt es keinen verlässlichen „läuft ab"-Proxy → zu.
        return {**base, "reason": "budget_enforce=false — kein verlässlicher Ablauf-Proxy"}

    tranche = int(b.get("day_allowance_tokens", 0) or 0)
    used = int(b.get("today_used", 0) or 0)
    if tranche <= 0:
        return {**base, "reason": "Tagestranche <= 0 (Wochenlimit erschöpft/nicht gesetzt)"}

    headroom_left = tranche * FABLE_HEADROOM - used
    if headroom_left <= 0:
        return {**base, "reason":
                f"Tageskopf zu klein: heute {used:,} von halber Tranche {int(tranche*FABLE_HEADROOM):,} genutzt"}

    return {**base, "allowed": True,
            "reason": f"Kopf frei: heute {used:,} < {int(tranche*FABLE_HEADROOM):,} "
                      f"(halbe Tagestranche von {tranche:,}); Fable erlaubt"}


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    print(json.dumps(check(), ensure_ascii=False, indent=2))

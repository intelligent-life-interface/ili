"""Backfill-Gate: darf der Automat JETZT den KI-Advisor eine neue Idee-Karte
generieren lassen ("Idle-Filler")?

Idee (2026-08-11): Wenn keine echten Karten mehr warten UND das Wochenbudget
komfortabel im Plan liegt, soll der Advisor brachliegende Projekte voranbringen, indem
er EINE konkrete nächste Aufgabe generiert, die der Automat dann normal entwickelt. Die
dabei genutzten Abo-Tokens wären am Wochenende sonst verfallen ("use it or lose it").

Harte Leitplanke: **erst wenn wir "einen Tag hinter dem Budget" sind — also einen
ganzen Tag Reserve haben.** Operationalisiert als:
    tokens_used(Woche) < (verstrichene_Wochentage − RESERVE_DAYS) / 7 × week_limit
D.h. der Backfill nutzt nur Budget, das mindestens ein Tagesbudget UNTER dem zeitlich-
linearen Wochen-Soll liegt. Konstruktionsbedingt ist das Gate **montags immer zu**
(Schwelle ≤ 0 am Tag 1) — das ist gewollt, kein Fehler.

Bewusst KEINE eigene Budget-Rechnung — die Wahrheit liegt im Dashboard (`/api/budget`,
`app/services/budget_service.check_allowance`), genau wie fable_gate.py / priority_gate.py.

Absicherung (alles konservativ — jeder Unsicherheitsfall → allowed=False):
  * Kill-Switch-Datei `state/backfill.disabled` → sofort zu (wirkt pro Tick, kein Restart).
  * An/Aus-Schalter `AUTOMAT_BACKFILL_ENABLED` (Env, Default 1).
  * Hartes Tageslimit `AUTOMAT_BACKFILL_MAX_PER_DAY` (Default 3), State in
    `state/backfill_runs.json`.
  * Budget nicht abrufbar / enforce=false / ISO-Woche-Drift zwischen lokal und API → zu.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import automat_lib as lib
from automat_lib import logger

BACKFILL_ENABLED     = int(os.getenv("AUTOMAT_BACKFILL_ENABLED", "1")) == 1
BACKFILL_MAX_PER_DAY = int(os.getenv("AUTOMAT_BACKFILL_MAX_PER_DAY", "3"))
# Wie viele Tagesbudgets Reserve unter dem zeitlichen Wochen-Soll bleiben müssen.
RESERVE_DAYS         = float(os.getenv("AUTOMAT_BACKFILL_RESERVE_DAYS", "1.0"))

RUNS_FILE    = lib.STATE_DIR / "backfill_runs.json"
DISABLE_FILE = lib.STATE_DIR / "backfill.disabled"

# Advisor liegt im Dashboard-Repo und braucht dessen venv/Imports.
ADVISOR_PY     = os.getenv("AUTOMAT_ADVISOR_PY", str(Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "venv/bin/python"))
ADVISOR_SCRIPT = os.getenv("AUTOMAT_ADVISOR_SCRIPT", str(Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "jobs/ki_project_advisor.py"))
ADVISOR_MODEL  = os.getenv("AUTOMAT_BACKFILL_MODEL", "claude-sonnet-5")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def runs_today() -> int:
    try:
        data = json.loads(RUNS_FILE.read_text())
        return int(data.get(_today(), 0))
    except Exception:
        return 0


def record_run() -> None:
    """Einen Backfill-Lauf für heute vermerken (und alte Tage aufräumen)."""
    try:
        try:
            data = json.loads(RUNS_FILE.read_text())
        except Exception:
            data = {}
        data[_today()] = int(data.get(_today(), 0)) + 1
        for k in [k for k in data if k != _today()]:
            data.pop(k, None)
        RUNS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        logger.debug("backfill_gate: Lauf vermerkt (%s = %s)", _today(), data[_today()])
    except Exception as e:
        logger.warning("backfill_gate: record_run fehlgeschlagen: %s", e)


def _budget() -> dict | None:
    try:
        return lib._req("GET", "/api/budget", timeout=15)
    except Exception as e:
        logger.warning("backfill_gate: /api/budget nicht erreichbar (%s) — Backfill bleibt aus", e)
        return None


def _elapsed_week_days(now: datetime) -> float:
    """Verstrichene Tage seit Montag 00:00 (0..7), fraktional."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    frac = (now - midnight).total_seconds() / 86400.0
    return (now.isoweekday() - 1) + frac


def check() -> dict:
    """Darf JETZT ein Backfill-Lauf starten?

    Rückgabe: {allowed, reason, runs_today, budget:{...}|None}.
    Konservativ: jeder Unsicherheitsfall → allowed=False.
    """
    runs = runs_today()
    base = {"allowed": False, "runs_today": runs, "budget": None}

    if DISABLE_FILE.exists():
        return {**base, "reason": f"Kill-Switch aktiv ({DISABLE_FILE.name} existiert)"}

    if not BACKFILL_ENABLED:
        return {**base, "reason": "Backfill ist aus (AUTOMAT_BACKFILL_ENABLED=0)"}

    if runs >= BACKFILL_MAX_PER_DAY:
        return {**base, "reason": f"Tageslimit an Backfill-Läufen erreicht ({runs}/{BACKFILL_MAX_PER_DAY})"}

    b = _budget()
    if b is None:
        return {**base, "reason": "Budget-Status nicht abrufbar"}
    base["budget"] = {k: b.get(k) for k in ("week", "week_pct", "week_limit", "tokens_used", "enforce")}

    if not b.get("enforce", True):
        return {**base, "reason": "budget_enforce=false — kein verlässlicher Ablauf-Proxy"}

    # ISO-Woche lokal vs. API abgleichen (Timezone-Drift → konservativ zu)
    now = datetime.now()
    iso = now.isocalendar()
    local_week = f"{iso[0]}-W{iso[1]:02d}"
    api_week = str(b.get("week") or "")
    if api_week and api_week != local_week:
        return {**base, "reason": f"Wochen-Drift: lokal {local_week} != API {api_week} — konservativ zu"}

    week_limit  = int(b.get("week_limit", 0) or 0)
    tokens_used = int(b.get("tokens_used", 0) or 0)
    if week_limit <= 0:
        return {**base, "reason": "week_limit <= 0 (nicht gesetzt)"}

    elapsed = _elapsed_week_days(now)
    threshold = max(0.0, (elapsed - RESERVE_DAYS) / 7.0) * week_limit

    nums = (f"Woche {api_week or local_week}, Tag {elapsed:.2f}/7, Reserve {RESERVE_DAYS:.0f}d, "
            f"verbraucht {tokens_used:,} vs. Schwelle {int(threshold):,} "
            f"(= {(elapsed - RESERVE_DAYS)/7*100:.0f}% des Wochenlimits {week_limit:,})")

    if tokens_used >= threshold:
        return {**base, "reason": f"kein Tag Reserve: {nums}"}

    return {**base, "allowed": True, "reason": f"Tag Reserve vorhanden: {nums}"}


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    print(json.dumps(check(), ensure_ascii=False, indent=2))

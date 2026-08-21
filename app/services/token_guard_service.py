"""Token-Wächter-Verlauf — liest ~/ai_session_logs/token-usage/guard-runs.jsonl
(geschrieben von ~/bin/token_guard.py, pro run-ki-dev.sh-Durchlauf eine Zeile).

Schnittstelle
-------------
runs(days) -> list[dict]   # [{ts, name, weighted, threshold, spike}, …], neueste zuerst
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.services import cost_service  # Funktion via Attribut (monkeypatch-bar), gleiche Konvention wie budget_service.py

log = logging.getLogger("dashboard.services.token_guard")

RUNS_FILE = Path.home() / "ai_session_logs" / "token-usage" / "guard-runs.jsonl"
DEFAULT_THRESHOLD = 2_000_000


def runs(days: int = 14) -> list[dict]:
    if not RUNS_FILE.exists():
        return []

    entries, corrupted = cost_service._load_jsonl_lines(RUNS_FILE)
    if corrupted:
        log.warning("[TokenGuard] %d korrupte Zeile(n) in %s", corrupted, RUNS_FILE.name)

    cutoff = datetime.now() - timedelta(days=days)
    result = []
    skipped = 0
    for e in entries:
        # Ganze Zeilen-Verarbeitung absichern: ein einzelner kaputter Eintrag
        # (z.B. ts kein String -> TypeError, weighted/threshold nicht int-coercible
        # -> ValueError) darf nie den ganzen Endpoint mit HTTP 500 zum Absturz bringen.
        try:
            ts = e.get("ts") or ""
            if datetime.fromisoformat(ts) < cutoff:
                continue
            result.append({
                "ts": ts,
                "name": e.get("name", "?"),
                "weighted": int(e.get("weighted", 0) or 0),
                "threshold": int(e.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD),
                "spike": bool(e.get("spike", False)),
            })
        except (TypeError, ValueError) as ex:
            skipped += 1
            log.warning("[TokenGuard] Ungültige Zeile übersprungen (%s): %r", ex, e)

    result.sort(key=lambda r: r["ts"], reverse=True)
    return result

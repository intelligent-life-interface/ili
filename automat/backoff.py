#!/usr/bin/env python3
"""Abo-Limit-Backoff: Abpraller am Claude-Session-/Usage-Limit nicht wiederholen.

Trifft ein Worker auf das Abo-Limit (`claude -p` bricht sofort ab, Log z.B.
"You've hit your session limit · resets 4am (Europe/Zurich)"), parst reap()
die Reset-Zeit aus dem Log und setzt hier einen Backoff. Der Scheduler startet
bis dahin KEINE `claude -p`-Worker (dev/review/fable) — vorher fraß jeder
5-min-Tick einen Tages-Start für einen garantierten Abpraller (08.08.26:
71 von 94 Läufen). Der Batch-Pfad (API, eigener Topf) ist bewusst ausgenommen.

Parse-Fehlschlag → fixer Fallback (45 min), nie "kein Backoff". Die Reset-Zeit
im Log ist Lokalzeit (Europe/Zurich), wie datetime.now().
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from automat_lib import logger

STATE = Path(__file__).resolve().parent / "state" / "limit_backoff.json"
FALLBACK_MIN = 45   # wenn keine Reset-Zeit im Log gefunden wird
BUFFER_MIN = 3      # Puffer nach der Reset-Zeit (Uhren-/Rundungs-Toleranz)

# Belegte Formate: "resets 4am", "resets 2:50am" — tolerant auch "resets at 4 pm"
_RESET_RE = re.compile(r"resets\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _parse_reset(text: str, now: datetime) -> datetime | None:
    """Nächste Reset-Zeit aus dem Log-Text, None wenn nicht parsebar."""
    m = _RESET_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1)) % 12          # "12am" -> 0, "12pm" -> 12
    if m.group(3).lower() == "pm":
        hour += 12
    minute = int(m.group(2) or 0)
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t <= now:                          # Uhrzeit heute schon vorbei -> morgen
        t += timedelta(days=1)
    return t


def arm_from_log(log_path) -> datetime:
    """Backoff bis zur Reset-Zeit aus dem Worker-Log setzen (max() bei Mehrfach-Treffern)."""
    now = datetime.now()
    try:
        text = Path(log_path).read_text(errors="replace")
    except Exception as e:
        logger.debug("backoff: Log %s nicht lesbar (%s)", log_path, e)
        text = ""
    t = _parse_reset(text, now)
    if t is None:
        t = now + timedelta(minutes=FALLBACK_MIN)
        logger.warning("backoff: Reset-Zeit nicht im Log gefunden — Fallback %d min.",
                       FALLBACK_MIN)
    t += timedelta(minutes=BUFFER_MIN)
    cur = until()
    if cur is not None and cur > t:
        t = cur
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"until": t.isoformat()}))
    except Exception as e:
        logger.error("backoff: State schreiben fehlgeschlagen: %s", e)
    logger.warning("backoff: Abo-Limit erkannt — keine claude-p-Starts bis %s.",
                   t.strftime("%H:%M"))
    return t


def until() -> datetime | None:
    """Aktives Backoff-Ende, sonst None (abgelaufene State-Datei wird gelöscht)."""
    try:
        t = datetime.fromisoformat(json.loads(STATE.read_text())["until"])
    except Exception:
        return None
    if t <= datetime.now():
        try:
            STATE.unlink()
        except Exception:
            pass
        return None
    return t


if __name__ == "__main__":
    b = until()
    print(f"Backoff aktiv bis {b.strftime('%H:%M')}" if b else "kein Backoff aktiv")

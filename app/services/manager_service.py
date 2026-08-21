"""Manager service: reads state.md, STRATEGIE.md and daily report history.

Read-only — all three files are owned/written by ~/bin/manager/{collect,run}.sh,
never by the dashboard.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("dashboard.services.manager")

STATE_DIR = Path.home() / "manager"
STATE_FILE = STATE_DIR / "state.md"
STRATEGIE_FILE = STATE_DIR / "STRATEGIE.md"
BERICHTE_DIR = STATE_DIR / "berichte"


def _read_file(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        log.warning("Manager-Datei fehlt: %s", path)
        return "", None
    text = path.read_text(encoding="utf-8")
    updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return text, updated


def get_status() -> dict:
    """Roher Inhalt von state.md (collect.sh überschreibt sie bei jedem Lauf)."""
    text, updated = _read_file(STATE_FILE)
    return {"raw": text, "updated": updated}


def get_strategie() -> dict:
    """Roher Inhalt von STRATEGIE.md (Dokument des Betreibers, read-only)."""
    text, updated = _read_file(STRATEGIE_FILE)
    return {"raw": text, "updated": updated}


def get_reports(limit: int = 60) -> list[dict]:
    """Tagesberichte aus ~/manager/berichte/YYYY-MM-DD.md, neueste zuerst."""
    if not BERICHTE_DIR.exists():
        return []
    files = sorted(BERICHTE_DIR.glob("*.md"), reverse=True)[:limit]
    reports = []
    for f in files:
        try:
            reports.append({"date": f.stem, "text": f.read_text(encoding="utf-8")})
        except OSError as e:
            log.warning("Bericht %s konnte nicht gelesen werden: %s", f, e)
    return reports

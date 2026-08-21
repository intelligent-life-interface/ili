"""Service für die Ermittlung inaktiver (schlafender) Projekte.

Kombiniert letzten Git-Commit mit letztem Kanban-Board-Update — das neuere der
beiden Zeitstempel zählt als "letzte Aktivität". Wenn älter als Schwellwert
(default 30 Tage), zählt das Projekt als inaktiv ("Leiche").

API-Endpunkt: GET /api/projects/inactive
"""
import logging
import os
import subprocess
from datetime import datetime, timezone

from app.services.ttl_cache import TTLCache
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.inactive_projects")

_manifest = ManifestRepository()
_board_repo = BoardRepository()

# Config: Schwellwert (Tage ohne Aktivität = inaktiv). Entscheidung (Kanban-Karte
# decision-1786344589, Board projekt-leichen-9k0ini): Hybrid aus Git-Commit UND Board-mtime, 30 Tage.
INACTIVITY_THRESHOLD_DAYS = int(os.environ.get("INACTIVITY_THRESHOLD_DAYS", "30"))

# Single-Flight-Cache (Muster budget_service/cost_service, opt_cache_stampede_0806) um den
# rohen Aktivitäts-Scan (~264 Boards × bis zu 2 Git-Subprozesse + os.walk) — ohne Cache lief
# er bei jedem Request neu, egal welcher threshold_days. Gecacht wird der ROHE Scan (alle
# Boards, jede last_activity), die Filterung nach threshold_days/Status bleibt pro Request
# auf dem gecachten Rohstand — sonst würde ein abweichender ?threshold= stale Daten liefern.
_scan_cache = TTLCache(ttl_seconds=300.0)


_IGNORED_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    "dist", "build",
    # Laufzeit-/Datenordner unter ~/containers/<id> — ständig neue mtimes durch Container-
    # Betrieb (nicht durch Entwicklung), und teils gross (paperless media, DB-Dateien).
    "data", "media", "logs", "backups", "boards",
}


def _has_own_git_repo(expanded_path: str) -> bool:
    """True nur wenn expanded_path SELBST ein Git-Repo ist (nicht ein Elternordner).

    `git -C <pfad>` läuft sonst bei Unterordnern ohne eigenes .git bis ins
    übergeordnete Home-Repo (~/.git) hoch und liefert dessen globalen Commit.
    """
    try:
        result = subprocess.run(
            ["git", "-C", expanded_path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return False
        toplevel = os.path.realpath(result.stdout.strip())
        return toplevel == os.path.realpath(expanded_path)
    except Exception as e:
        log.debug("Git-Toplevel-Check für %s fehlgeschlagen: %s", expanded_path, e)
        return False


def _get_git_commit_time(project_path: str) -> datetime | None:
    """Letzter Git-Commit-Zeit für ein Projekt — nur falls das Projekt selbst ein Git-Repo ist."""
    expanded = os.path.expanduser(project_path)
    if not _has_own_git_repo(expanded):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", expanded, "log", "--format=%aI", "--max-count=1"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            # ISO-DateTime-String von git log
            return datetime.fromisoformat(result.stdout.strip())
    except Exception as e:
        log.debug("Git-Commit-Zeit für %s nicht ermittelbar: %s", project_path, e)
    return None


def _get_latest_file_mtime(project_path: str) -> datetime | None:
    """Jüngste Datei-Änderungszeit im Projektordner — Aktivitätssignal für Projekte ohne eigenes Git-Repo."""
    expanded = os.path.expanduser(project_path)
    if not os.path.isdir(expanded):
        return None
    latest = None
    try:
        for root, dirs, files in os.walk(expanded):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
            for name in files:
                try:
                    mtime = os.path.getmtime(os.path.join(root, name))
                except OSError:
                    continue
                if latest is None or mtime > latest:
                    latest = mtime
    except Exception as e:
        log.debug("Datei-mtime-Scan für %s fehlgeschlagen: %s", project_path, e)
        return None
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def _get_board_mtime(board_id: str) -> datetime | None:
    """Letzte Änderungszeit der Board-JSON-Datei — reiner stat(), kein Board-Load nötig."""
    try:
        board_file = _board_repo.board_path(board_id)
        if board_file.exists():
            mtime = board_file.stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception as e:
        log.debug("Board-mtime für %s nicht ermittelbar: %s", board_id, e)
    return None


def _latest_activity_time(*times: datetime | None) -> datetime | None:
    """Das neueste der übergebenen Zeitstempel (None wird ignoriert)."""
    valid = [t for t in times if t is not None]
    return max(valid) if valid else None


def _scan_all_activity() -> list[dict]:
    """Roher Aktivitäts-Scan über ALLE Boards, ungefiltert nach Schwellwert.

    Teuer (~264 Boards × bis zu 2 Git-Subprozesse + os.walk je Kandidatenpfad) — wird
    ausschliesslich über `_get_cached_scan()` aufgerufen, nie direkt pro Request.
    """
    try:
        manifest = _manifest.load()
    except Exception as e:
        log.error("Manifest nicht lesbar: %s", e)
        return []

    boards = manifest.get("boards", [])
    raw = []

    for board in boards:
        board_id = board.get("id")
        if not board_id:
            continue

        # Pfad-Kandidaten fürs Projekt — dieselbe Reihenfolge wie tmux-project.sh
        # (code_dir > ~/containers/<id> > ~/Projekte/<id>). Ohne ~/containers/<id> würde
        # jedes Container-Projekt ohne code_dir-Eintrag im Manifest fälschlich nur über
        # seinen ruhigen Planungsordner in ~/Projekte bewertet und könnte trotz aktiver
        # Entwicklung als "Leiche" durchrutschen.
        code_dir = board.get("code_dir")
        if code_dir:
            candidate_paths = [code_dir]
        else:
            candidate_paths = [f"~/containers/{board_id}", f"~/Projekte/{board_id}"]
        # Für die Anzeige (path-Feld): ersten tatsächlich existierenden Kandidaten nehmen,
        # sonst den ersten Kandidaten als Fallback-Beschriftung.
        project_path = next(
            (p for p in candidate_paths if os.path.isdir(os.path.expanduser(p))),
            candidate_paths[0],
        )

        # Letzten Git-Commit (nur eigenes Repo) + Datei-mtime über ALLE Kandidatenpfade,
        # plus Board-Update — das jüngste Signal zählt als "letzte Aktivität".
        git_times = [_get_git_commit_time(p) for p in candidate_paths]
        file_times = [_get_latest_file_mtime(p) for p in candidate_paths]
        board_time = _get_board_mtime(board_id)
        latest_time = _latest_activity_time(*git_times, *file_times, board_time)

        # Falls alle Signale fehlen: Board als "aktiv" annehmen (kein Git/keine Edits)
        if latest_time is None:
            log.debug("Keine Aktivitätszeiten für %s ermittelbar — übersprungen", board_id)
            continue

        raw.append({
            "id": board_id,
            "title": board.get("name", board_id),
            "path": f"{project_path}/CLAUDE.md",
            "tags": board.get("tags", []),
            "last_activity": latest_time,
            "status": board.get("status", "active"),  # aus Manifest
        })

    log.info("Aktivitäts-Scan: %d von %d Boards mit ermittelbarer Aktivität", len(raw), len(boards))
    return raw


def _get_cached_scan() -> list[dict]:
    """Single-Flight TTL-Cache um `_scan_all_activity()` (Muster budget_service/cost_service,
    opt_cache_stampede_0806) — verhindert, dass jeder Request (egal welcher threshold_days)
    den vollen Git+os.walk-Scan über alle Boards neu auslöst."""
    return _scan_cache.get(_scan_all_activity)


def invalidate_scan_cache() -> None:
    """Erzwingt einen frischen Scan beim nächsten Aufruf (v.a. für Tests)."""
    _scan_cache.invalidate()


def get_inactive_projects(threshold_days: int | None = None) -> list[dict]:
    """Liste aller inaktiven Projekte.

    Der teure Rohscan (Git+Datei-mtime je Board) ist gecacht (`_get_cached_scan`,
    TTL 300s) — die Filterung nach `threshold_days` läuft pro Aufruf auf dem
    gecachten Rohstand, damit ein abweichender ?threshold= nie stale Daten sieht.

    Returns:
        List[dict] mit Struktur:
        {
          "id": "board-id",
          "title": "Projektname",
          "path": "~/Projekte/ordner/CLAUDE.md",
          "tags": ["tag1", "tag2"],
          "last_activity": "2026-08-04T00:00:00+00:00",
          "inactivity_days": 7,
          "status": "active/hibernated/archived"
        }
    """
    if threshold_days is None:
        threshold_days = INACTIVITY_THRESHOLD_DAYS

    now = datetime.now(timezone.utc)
    raw = _get_cached_scan()
    inactive = []

    for entry in raw:
        last_activity = entry["last_activity"]
        inactivity_days = (now - last_activity).days

        # Nur "inaktive" Projekte liefern
        if inactivity_days >= threshold_days:
            inactive.append({
                "id": entry["id"],
                "title": entry["title"],
                "path": entry["path"],
                "tags": entry["tags"],
                "last_activity": last_activity.isoformat(),
                "inactivity_days": inactivity_days,
                "status": entry["status"],
            })

    # Sortieren nach Inaktivitätsdauer (längste zuerst)
    inactive.sort(key=lambda p: p["inactivity_days"], reverse=True)

    log.info(
        "Inaktive Projekte (>%d Tage): %d von %d Boards",
        threshold_days,
        len(inactive),
        len(raw),
    )
    return inactive

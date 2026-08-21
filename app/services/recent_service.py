"""Recent-Activity-Service: aggregiert "zuletzt bearbeitet" für GET /api/projects/recent.

Datenquelle: ~/ai_session_logs/worklog.db (worklog_commits + worklog_sessions,
befüllt von worklog.py aus `git log` + ai_dev_log.jsonl). Das ist die einzige
Quelle mit echtem sortierbarem Zeitstempel — das Manifest-Feld `last_activity`
ist nur ein Anzeigetext ("DD.MM.: ...", Tag vor Monat, NICHT sortierbar).

Join-Regel: worklog-Projektname = Repo-Ordnername. Für die meisten Boards ist
das identisch mit der Board-ID; für die Ausnahmen mit abweichendem `code_dir`
(z.B. bohrprofile-3d -> ~/containers/bohr3d) wird zusätzlich der Ordnername aus
`code_dir` versucht. Boards ohne Treffer erscheinen mit ts=None ans Ende (KEIN
Fallback auf Manifest-`updated_at` — das wird vom stündlichen Meta-Timer auch
ohne echte Arbeit angefasst und würde die Sortierung verfälschen).

DB wird read-only geöffnet (nie worklog_db.connect() — das würde DDL ausführen
und dem Writer beim WAL-Schreiben in die Quere kommen).
"""
import json
import logging
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from app.services.board_service import _get_parents
from app.services.ttl_cache import TTLCache
from app.storage.manifest_repository import ManifestRepository
from constants import CATEGORIES, STATUSES

log = logging.getLogger("dashboard.services.recent")

# opt_polling_ttl_caches_0815: _next_worklog_run() forkt zwei Subprozesse
# (systemctl show + date -d), unabhängig von limit/category/status — recent.html
# pollt collect_recent() alle 30s mit limit=500. worklog.timer läuft nur alle
# 15 Min, der Wert ändert sich also so gut wie nie zwischen zwei Polls. `date -d`
# bleibt bewusst bestehen (Zeitzonen-Name CEST u.ä. lässt sich nicht sauber in
# Python nachbauen) — nur das Ergebnis wird gecacht, nicht der Mechanismus ersetzt.
# allow_none=True, weil das Ergebnis legitim None sein kann (kein Timer aktiv).
_next_run_cache = TTLCache(ttl_seconds=60.0, allow_none=True)

WORKLOG_DB_PATH = Path(os.environ.get("WORKLOG_DB_PATH",
                                       os.path.expanduser("~/ai_session_logs/worklog.db")))

_manifest = ManifestRepository()

# Auto-Save-Commits (git-auto-Hook) sind kein sprechender Titel — bevorzugt wird
# der jüngste "echte" Commit-Betreff desselben Projekts, falls vorhanden.
_AUTOSAVE_RE = re.compile(r"^auto-save \(Claude ")


def _project_key(board: dict) -> str:
    """Worklog-Suchbegriff für ein Board: code_dir-Ordnername, sonst Board-ID."""
    code_dir = board.get("code_dir")
    if code_dir:
        name = Path(os.path.expanduser(str(code_dir))).name
        if name:
            return name
    return board.get("id", "")


def _open_worklog_db() -> sqlite3.Connection | None:
    if not WORKLOG_DB_PATH.exists():
        log.warning("worklog.db nicht gefunden unter %s — /api/projects/recent liefert keine Zeitstempel",
                    WORKLOG_DB_PATH)
        return None
    try:
        uri = f"file:{WORKLOG_DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        log.error("worklog.db read-only nicht öffenbar: %s", e)
        return None


# Sessions, die NUR Doku-Dateien angefasst haben, sind Wartung, keine echte Arbeit.
_DOC_FILES = {"CLAUDE.md", "TAGS.md", "README.md", "MEMORY.md", "AGENTS.md", "TODO.md"}
# Commit ≤ so viele Minuten neben einer Automat-Session (gleiches Projekt, gleicher
# Tag) → der Commit stammt vom Automat-Worker (Worker committen unter dem
# persönlichen Git-User, am Commit selbst ist die Herkunft nicht erkennbar).
_AUTO_COMMIT_WINDOW_MIN = 20


def _minutes(t: str) -> int:
    try:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _worklog_activity_map() -> dict:
    """{projekt_key: {work_ts, work_first_ts, work_subject, auto_ts, auto_kind,
    auto_subject, n}} aus worklog.db — zwei getrennte Spuren:

    "work"  = echte (interaktive) Arbeit: Commits + Sessions, die NICHT vom
              Kanban-Automat stammen und nicht nur Doku-Dateien angefasst haben.
              Zeitstempel dieser Spur ist die Default-Sortierung von "Zuletzt aktiv".
    "auto"  = KI-Autopilot/Wartung: Automat-Worker-Sessions (worklog_sessions.auto=1),
              Commits in deren Zeitfenster, Auto-Save-Commits, Nur-Doku-Sessions.
              Wird im Frontend nur als Badge/optionale Sortierung gezeigt.
    """
    conn = _open_worklog_db()
    if conn is None:
        return {}

    try:
        try:
            srows = conn.execute(
                "SELECT project, date, time, n_files, files, auto FROM worklog_sessions"
            ).fetchall()
            has_auto_col = True
        except sqlite3.OperationalError:
            # DB noch ohne auto-Spalte (Migration läuft mit dem nächsten worklog-Lauf)
            srows = conn.execute(
                "SELECT project, date, time, n_files, files FROM worklog_sessions"
            ).fetchall()
            has_auto_col = False
            log.warning("worklog.db ohne auto-Spalte — alle Sessions gelten als interaktiv")
        crows = conn.execute("SELECT project, date, time, subject FROM worklog_commits").fetchall()
    except Exception as e:
        log.error("worklog.db Abfrage fehlgeschlagen: %s", e, exc_info=True)
        return {}
    finally:
        conn.close()

    # Sessions klassifizieren + Index der Automat-Zeitfenster für die Commit-Zuordnung
    auto_idx: dict = {}   # proj -> {date: [minuten, ...]}
    events: dict = {}     # proj -> {"work": [(ts, subject|None)], "auto": [(ts, kind, subject)], "n": int}

    def _e(proj: str) -> dict:
        return events.setdefault(proj, {"work": [], "auto": [], "n": 0})

    for r in srows:
        proj, d, t = r["project"], r["date"], r["time"] or "00:00"
        ts = f"{d} {t}"
        is_auto = bool(r["auto"]) if has_auto_col else False
        try:
            files = json.loads(r["files"] or "[]")
        except Exception:
            files = []
        doc_only = bool(files) and all(Path(f).name in _DOC_FILES for f in files)
        n_files = r["n_files"] or 0
        e = _e(proj)
        e["n"] += 1
        if is_auto:
            auto_idx.setdefault(proj, {}).setdefault(d, []).append(_minutes(t))
            e["auto"].append((ts, "automat", f"KI-Autopilot bearbeitete {n_files} Datei{'en' if n_files != 1 else ''}"))
        elif doc_only:
            e["auto"].append((ts, "doku", "nur Doku angepasst (" + ", ".join(sorted(Path(f).name for f in files)[:3]) + ")"))
        else:
            e["work"].append((ts, f"KI bearbeitete {n_files} Datei{'en' if n_files != 1 else ''}"))

    for r in crows:
        proj, d, t = r["project"], r["date"], r["time"] or "00:00"
        ts = f"{d} {t}"
        subj = (r["subject"] or "").strip()
        e = _e(proj)
        e["n"] += 1
        near_auto = any(abs(_minutes(t) - am) <= _AUTO_COMMIT_WINDOW_MIN
                        for am in auto_idx.get(proj, {}).get(d, []))
        if near_auto or _AUTOSAVE_RE.match(subj):
            e["auto"].append((ts, "automat", subj))
        else:
            e["work"].append((ts, subj))

    out: dict = {}
    for proj, e in events.items():
        entry: dict = {"n": e["n"], "work_ts": None, "work_first_ts": None,
                       "work_subject": None, "auto_ts": None, "auto_kind": None,
                       "auto_subject": None}
        if e["work"]:
            e["work"].sort()
            entry["work_ts"] = e["work"][-1][0]
            latest_date = entry["work_ts"][:10]
            # Betreff: jüngster Commit-Betreff VOM TAG der letzten Arbeit (sprechender
            # als der Session-Zähler); ein älterer Commit-Betreff wäre irreführend.
            commit_subjects = [(ts, s) for ts, s in e["work"]
                               if ts[:10] == latest_date and s and not s.startswith("KI bearbeitete")]
            entry["work_subject"] = (commit_subjects[-1][1] if commit_subjects else e["work"][-1][1])
            same_day = [ts for ts, _ in e["work"] if ts[:10] == latest_date]
            entry["work_first_ts"] = min(same_day)
        if e["auto"]:
            e["auto"].sort()
            entry["auto_ts"], entry["auto_kind"], entry["auto_subject"] = e["auto"][-1]
        out[proj] = entry

    log.debug("worklog.db: %d Projekte mit Aktivität (work/auto getrennt)", len(out))
    return out


def _next_worklog_run() -> str | None:
    """Wie _next_worklog_run_uncached(), aber gecacht für 60 Sekunden
    (Single-Flight, Double-Checked Locking via TTLCache).
    Ergebnis kann legitim None sein — TTLCache mit allow_none=True."""
    return _next_run_cache.get(_next_worklog_run_uncached)


def _next_worklog_run_uncached() -> str | None:
    """Nächster Lauf von worklog.timer (aktualisiert worklog.db, alle 15 Min für den
    laufenden Tag) — als ISO-Zeitstempel fürs Frontend ("Nächste Aktualisierung um ...").
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "worklog.timer",
             "--property=NextElapseUSecRealtime", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        raw = r.stdout.strip()
        if not raw or raw == "n/a":
            return None
        d = subprocess.run(["date", "-d", raw, "+%Y-%m-%dT%H:%M:%S%z"],
                            capture_output=True, text=True, timeout=5)
        iso = d.stdout.strip()
        return iso or None
    except Exception as e:
        log.warning("worklog.timer NextElapseUSecRealtime nicht lesbar: %s", e)
        return None


def collect_recent(limit: int = 200, category: str | None = None,
                    status: str | None = None) -> dict:
    """Top-Level-Projekte sortiert nach letzter echter Aktivität (worklog.db).

    Projekte ohne Worklog-Treffer landen mit ts=None am Ende (Original-Reihenfolge).
    """
    manifest = _manifest.load()
    all_boards = manifest.get("boards", [])
    activity = _worklog_activity_map()

    items = []
    for b in all_boards:
        if _get_parents(b):
            continue  # nur Top-Level-Projekte, keine Unterprojekte
        bid = b.get("id")
        if not bid:
            continue
        if category and b.get("category") != category:
            continue
        if status and b.get("status") != status:
            continue

        key = _project_key(b)
        act = activity.get(key) or (activity.get(bid) if key != bid else None)
        cat = CATEGORIES.get(b.get("category"), {})
        stat = STATUSES.get(b.get("status"), {})
        items.append({
            "id": bid,
            "name": b.get("name") or bid,
            "icon": b.get("icon") or cat.get("emoji", "📁"),
            "color": b.get("color") or cat.get("color", "#8892a4"),
            "category": b.get("category"),
            "category_label": cat.get("label"),
            "status": b.get("status"),
            "status_label": stat.get("label"),
            "status_emoji": stat.get("emoji"),
            "description": b.get("description"),
            "last_activity_text": b.get("last_activity"),
            # "echte Arbeit" (interaktive Sessions + deren Commits) — Default-Sortierung
            "activity_ts": act["work_ts"] if act else None,
            "activity_first_ts": act.get("work_first_ts") if act else None,
            "activity_subject": act["work_subject"] if act else None,
            # KI-Autopilot/Wartung (Automat-Worker, Nur-Doku, Auto-Save) — optional
            "activity_auto_ts": act.get("auto_ts") if act else None,
            "activity_auto_kind": act.get("auto_kind") if act else None,
            "activity_auto_subject": act.get("auto_subject") if act else None,
            "activity_count": act["n"] if act else 0,
        })

    items.sort(key=lambda p: p["activity_ts"] or "", reverse=True)
    n_with_activity = sum(1 for p in items if p["activity_ts"])
    log.info("Recent-Activity: %d/%d Top-Level-Projekte mit worklog-Aktivität",
              n_with_activity, len(items))
    return {
        "projects": items[:limit],
        "total": len(items),
        "with_activity": n_with_activity,
        "next_worklog_run": _next_worklog_run(),
    }

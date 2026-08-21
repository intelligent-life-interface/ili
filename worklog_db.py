#!/usr/bin/env python3
"""
worklog_db.py — Persistenz + Suche für den Worklog in einer SQLite-DB.

Der Worklog wird NICHT mehr als Speicher im Kanban gehalten. `worklog.py` baut je
Tag einen Faktenbericht (Git-Commits + Claude-Sessions) und legt ihn hier idempotent
ab. Das Kanban-Board `worklog` dient nur noch als Doku (Beschreibungs-Karte + Live-
Anhang der `worklog.md`), nicht als Datenspeicher.

Schema (normalisiert):
  worklog_days     (date PK, weekday, n_commits, n_sessions, n_projects, models, tags, updated_at)
  worklog_commits  (date, project, time, hash, subject)              — je Commit eine Zeile
  worklog_sessions (date, time, model, project, n_files, files)      — je (Session×Projekt) eine Zeile
  worklog_tags     (date, tag, kind)                                 — Hashtags für die Suche

Hashtags werden automatisch erzeugt aus:
  - Projektnamen   → kind='project'  (#immobilienverwaltung)
  - Claude-Modell  → kind='model'    (#opus, #sonnet, #haiku)
  - Commit-Typ     → kind='keyword'  (#fix, #feat, #docs …, conventional commits)

Idempotenz: `upsert_day()` löscht alle Zeilen des Tages und schreibt neu → mehrfaches
Laufen ersetzt statt dupliziert (gleiche Semantik wie worklog.py fürs Markdown).

CLI (Suche):
  worklog_db.py --stats                 # Übersicht (Tage, Commits, Sessions, Top-Tags)
  worklog_db.py --tags                  # alle Hashtags mit Häufigkeit
  worklog_db.py --tag immobilienverwaltung   # Tage mit diesem Hashtag
  worklog_db.py --day 2026-06-24        # Detail eines Tages
  worklog_db.py --search "fix"          # Volltextsuche in Commit-Subjects
  worklog_db.py --debug                 # Debug-Logs

Env:
  WORKLOG_DB_PATH=/pfad/worklog.db      # Default ~/ai_session_logs/worklog.db
  WORKLOG_DB_DEBUG=1                     # Debug-Logs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

# --- Konstanten -------------------------------------------------------------
HOME    = Path.home()
DB_PATH = Path(os.environ.get("WORKLOG_DB_PATH", HOME / "ai_session_logs" / "worklog.db"))

_DEBUG = bool(os.environ.get("WORKLOG_DB_DEBUG"))

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                "Freitag", "Samstag", "Sonntag"]

# conventional-commit-Typen, die als Hashtag taugen
_COMMIT_TYPES = {"fix", "feat", "chore", "docs", "refactor", "test",
                 "perf", "style", "build", "ci", "revert", "wip"}

# bekannte Claude-Modellfamilien → kurzer Hashtag
_MODEL_FAMILIES = ("opus", "sonnet", "haiku", "fable")


def log(msg: str) -> None:
    print(f"[worklog_db] {msg}", file=sys.stderr)


def dbg(msg: str) -> None:
    if _DEBUG:
        print(f"[worklog_db][debug] {msg}", file=sys.stderr)


# --- Schema -----------------------------------------------------------------

_DDL = [
    """CREATE TABLE IF NOT EXISTS worklog_days (
        date        TEXT PRIMARY KEY,
        weekday     TEXT,
        n_commits   INTEGER NOT NULL DEFAULT 0,
        n_sessions  INTEGER NOT NULL DEFAULT 0,
        n_projects  INTEGER NOT NULL DEFAULT 0,
        models      TEXT,
        tags        TEXT,
        updated_at  TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS worklog_commits (
        date     TEXT NOT NULL,
        project  TEXT NOT NULL,
        time     TEXT,
        hash     TEXT,
        subject  TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS worklog_sessions (
        date     TEXT NOT NULL,
        time     TEXT,
        model    TEXT,
        project  TEXT,
        n_files  INTEGER NOT NULL DEFAULT 0,
        files    TEXT,
        auto     INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS worklog_tags (
        date  TEXT NOT NULL,
        tag   TEXT NOT NULL,
        kind  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_commits_date   ON worklog_commits(date)",
    "CREATE INDEX IF NOT EXISTS idx_commits_project ON worklog_commits(project)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_date  ON worklog_sessions(date)",
    "CREATE INDEX IF NOT EXISTS idx_tags_tag        ON worklog_tags(tag)",
    "CREATE INDEX IF NOT EXISTS idx_tags_date       ON worklog_tags(date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags       ON worklog_tags(date, tag, kind)",
]


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Verbindung öffnen (Ordner + Schema werden bei Bedarf angelegt)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _DDL:
        conn.execute(stmt)
    # Migration (17.07.26): auto-Flag für Automat-Worker-Sessions; bestehende DBs
    # haben die Spalte noch nicht — ADD COLUMN ist idempotent via Fehler-Ignorieren.
    try:
        conn.execute("ALTER TABLE worklog_sessions ADD COLUMN auto INTEGER NOT NULL DEFAULT 0")
        log("Migration: Spalte worklog_sessions.auto ergänzt")
    except sqlite3.OperationalError:
        pass  # Spalte existiert schon
    conn.commit()
    dbg(f"DB verbunden + Schema sichergestellt: {db_path}")
    return conn


# --- Hashtag-Extraktion -----------------------------------------------------

def _slug(s: str) -> str:
    """Kleinbuchstaben, nur [a-z0-9_-], zusammengefasste Trenner."""
    s = re.sub(r"[^a-z0-9_-]+", "-", s.strip().lower()).strip("-")
    return s


def _model_tag(model: str) -> str:
    m = model.lower()
    for fam in _MODEL_FAMILIES:
        if fam in m:
            return fam
    return _slug(model)


def _commit_type(subject: str) -> str | None:
    """Conventional-Commit-Typ am Anfang des Subjects (z.B. 'fix:', 'feat(x)!:')."""
    m = re.match(r"^(\w+)(\([^)]*\))?!?:", subject.strip())
    if m and m.group(1).lower() in _COMMIT_TYPES:
        return m.group(1).lower()
    return None


def extract_tags(report: dict) -> set[tuple[str, str]]:
    """Menge von (tag, kind) für einen Tagesbericht — für die Suche."""
    tags: set[tuple[str, str]] = set()
    for pid, p in report["projects"].items():
        t = _slug(pid)
        if t:
            tags.add((t, "project"))
        for model in p["models"]:
            mt = _model_tag(model)
            if mt:
                tags.add((mt, "model"))
        for c in p["commits"]:
            ct = _commit_type(c.get("subject", ""))
            if ct:
                tags.add((ct, "keyword"))
    return tags


# --- Schreiben (idempotent pro Tag) -----------------------------------------

def upsert_day(conn: sqlite3.Connection, report: dict) -> int:
    """Tagesbericht idempotent ablegen. Returns: Anzahl geschriebener Commit-Zeilen.

    Ein Tag ganz ohne Aktivität (0 Commits UND 0 Sessions) wird NICHT geschrieben —
    bestehende Zeilen des Tages werden aber trotzdem entfernt (idempotent).
    """
    d = report["date"]
    cur = conn.cursor()
    # alte Zeilen des Tages entfernen → keine Duplikate bei erneutem Lauf
    for tbl in ("worklog_commits", "worklog_sessions", "worklog_tags", "worklog_days"):
        cur.execute(f"DELETE FROM {tbl} WHERE date = ?", (d,))

    if not (report["n_commits"] or report["n_sessions"]):
        conn.commit()
        dbg(f"{d}: leerer Tag (0/0) — keine Zeile geschrieben")
        return 0

    day = date.fromisoformat(d)
    weekday = _WEEKDAYS_DE[day.weekday()]
    models = sorted({m for p in report["projects"].values() for m in p["models"]})
    tag_set = extract_tags(report)
    tag_text = " ".join(f"#{t}" for t, _ in sorted(tag_set))

    cur.execute(
        """INSERT INTO worklog_days
           (date, weekday, n_commits, n_sessions, n_projects, models, tags, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
        (d, weekday, report["n_commits"], report["n_sessions"],
         len(report["projects"]), ", ".join(models), tag_text),
    )

    n_commits = 0
    for pid, p in report["projects"].items():
        for c in p["commits"]:
            cur.execute(
                "INSERT INTO worklog_commits (date, project, time, hash, subject) VALUES (?,?,?,?,?)",
                (d, pid, c.get("time"), c.get("hash"), c.get("subject")),
            )
            n_commits += 1

    for s in report["sessions"]:
        for pid, files in s.get("projects", {}).items():
            files = sorted(files)
            cur.execute(
                "INSERT INTO worklog_sessions (date, time, model, project, n_files, files, auto) VALUES (?,?,?,?,?,?,?)",
                (d, s.get("time"), s.get("model"), pid, len(files), json.dumps(files, ensure_ascii=False),
                 1 if s.get("auto") else 0),
            )

    for tag, kind in tag_set:
        cur.execute("INSERT INTO worklog_tags (date, tag, kind) VALUES (?,?,?)", (d, tag, kind))

    conn.commit()
    log(f"{d} ({weekday}): {n_commits} Commits, {report['n_sessions']} Sessions, "
        f"{len(tag_set)} Tags → DB")
    return n_commits


# --- Suche / Abfragen (CLI) -------------------------------------------------

def q_stats(conn: sqlite3.Connection) -> None:
    r = conn.execute(
        "SELECT COUNT(*) d, COALESCE(SUM(n_commits),0) c, COALESCE(SUM(n_sessions),0) s "
        "FROM worklog_days").fetchone()
    span = conn.execute("SELECT MIN(date) a, MAX(date) b FROM worklog_days").fetchone()
    print(f"Tage: {r['d']}  ({span['a']} … {span['b']})")
    print(f"Commits gesamt:  {r['c']}")
    print(f"Sessions gesamt: {r['s']}")
    print("\nTop-Hashtags:")
    for row in conn.execute(
        "SELECT tag, kind, COUNT(*) n FROM worklog_tags GROUP BY tag, kind "
        "ORDER BY n DESC, tag LIMIT 15"):
        print(f"  #{row['tag']:<24} {row['n']:>3}  ({row['kind']})")


def q_tags(conn: sqlite3.Connection) -> None:
    for row in conn.execute(
        "SELECT tag, kind, COUNT(*) n FROM worklog_tags GROUP BY tag, kind "
        "ORDER BY kind, tag"):
        print(f"#{row['tag']:<28} {row['n']:>3}  {row['kind']}")


def q_tag(conn: sqlite3.Connection, tag: str) -> None:
    tag = tag.lstrip("#").lower()
    rows = conn.execute(
        "SELECT d.date, d.weekday, d.n_commits, d.n_sessions "
        "FROM worklog_tags t JOIN worklog_days d ON d.date = t.date "
        "WHERE t.tag = ? ORDER BY d.date DESC", (tag,)).fetchall()
    if not rows:
        print(f"Keine Tage mit #{tag}")
        return
    print(f"Tage mit #{tag}:")
    for r in rows:
        print(f"  {r['date']} ({r['weekday']}): {r['n_commits']} Commits / {r['n_sessions']} Sessions")


def q_day(conn: sqlite3.Connection, day: str) -> None:
    d = conn.execute("SELECT * FROM worklog_days WHERE date = ?", (day,)).fetchone()
    if not d:
        print(f"Kein Eintrag für {day}")
        return
    print(f"# {d['date']} ({d['weekday']})  {d['n_commits']} Commits / {d['n_sessions']} Sessions")
    print(f"Modelle: {d['models']}")
    print(f"Tags: {d['tags']}\n")
    print("Commits:")
    for r in conn.execute(
        "SELECT project, time, hash, subject FROM worklog_commits WHERE date=? ORDER BY project, time", (day,)):
        print(f"  [{r['project']}] {r['time']} {r['subject']} ({r['hash']})")


def q_search(conn: sqlite3.Connection, text: str) -> None:
    like = f"%{text}%"
    rows = conn.execute(
        "SELECT date, project, time, hash, subject FROM worklog_commits "
        "WHERE subject LIKE ? ORDER BY date DESC, project LIMIT 50", (like,)).fetchall()
    if not rows:
        print(f"Keine Commits mit '{text}'")
        return
    for r in rows:
        print(f"  {r['date']} [{r['project']}] {r['time']} {r['subject']} ({r['hash']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Worklog-DB durchsuchen (SQLite).")
    ap.add_argument("--stats", action="store_true", help="Übersicht + Top-Hashtags")
    ap.add_argument("--tags", action="store_true", help="Alle Hashtags mit Häufigkeit")
    ap.add_argument("--tag", help="Tage mit diesem Hashtag")
    ap.add_argument("--day", help="Detail eines Tages (YYYY-MM-DD)")
    ap.add_argument("--search", help="Volltextsuche in Commit-Subjects")
    ap.add_argument("--debug", action="store_true", help="Debug-Logs")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    global _DEBUG
    args = parse_args(argv)
    _DEBUG = _DEBUG or args.debug
    conn = connect()
    if args.tag:
        q_tag(conn, args.tag)
    elif args.day:
        q_day(conn, args.day)
    elif args.search:
        q_search(conn, args.search)
    elif args.tags:
        q_tags(conn)
    else:
        q_stats(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

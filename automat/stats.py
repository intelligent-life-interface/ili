#!/usr/bin/env python3
"""stats — Statistik des Kanban-Automaten (welches Modell, wie lange, mit welchem Ergebnis).

SQLite `state/stats.db` (gitignored). Zwei Tabellen:

  runs     — ein Datensatz pro Worker-Lauf (Dev ODER Review)
  reviews  — Urteil eines Review-Laufs über einen Dev-Lauf

Schreiber: orchestrator.py (Start/Ende), automat_cli.py (done/decision/review-result).
Leser: `python3 stats.py --summary` bzw. das Dashboard (`/api/automat/stats`).

Alle Schreibfunktionen sind **best-effort**: eine kaputte Statistik darf den Automaten
nie stoppen (Fehler landen als WARNING im automat-Log).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import automat_lib as lib

logger = lib.logger
DB_PATH = Path(os.getenv("AUTOMAT_STATS_DB", str(lib.STATE_DIR / "stats.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    board         TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'dev',   -- dev | review
    model_used    TEXT    NOT NULL,
    model_target  TEXT    NOT NULL,
    downgraded    INTEGER NOT NULL DEFAULT 0,
    parallel      INTEGER NOT NULL DEFAULT 0,       -- laufende Worker beim Start
    card_ids      TEXT    NOT NULL DEFAULT '[]',
    card_count    INTEGER NOT NULL DEFAULT 0,
    pid           INTEGER,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    duration_s    REAL,
    outcome       TEXT    NOT NULL DEFAULT 'running',  -- running|ok|noop|timeout|ended
    done_cards    INTEGER NOT NULL DEFAULT 0,
    decisions     INTEGER NOT NULL DEFAULT 0,
    review_run_id INTEGER                              -- bei kind='review': geprüfter Dev-Lauf
);
CREATE INDEX IF NOT EXISTS runs_board_idx   ON runs(board);
CREATE INDEX IF NOT EXISTS runs_started_idx ON runs(started_at);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dev_run_id  INTEGER,
    review_run_id INTEGER,
    board       TEXT NOT NULL,
    model       TEXT NOT NULL,        -- Prüf-Modell
    dev_model   TEXT NOT NULL,        -- womit entwickelt wurde
    verdict     TEXT NOT NULL,        -- ok | nacharbeit | fehler
    findings    TEXT,
    card_ids    TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_board_idx ON reviews(board);
"""


@contextmanager
def _db():
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Schreiben ───────────────────────────────────────────────────────────────
def start_run(board: str, kind: str, model_used: str, model_target: str, parallel: int,
              card_ids: list, pid: int | None = None,
              review_run_id: int | None = None) -> int | None:
    """Neuen Lauf anlegen; gibt die run_id zurück (None bei Fehler)."""
    try:
        with _db() as con:
            cur = con.execute(
                "INSERT INTO runs (board,kind,model_used,model_target,downgraded,parallel,"
                "card_ids,card_count,pid,started_at,outcome,review_run_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,'running',?)",
                (board, kind, model_used, model_target,
                 1 if model_used != model_target else 0, parallel,
                 json.dumps(card_ids, ensure_ascii=False), len(card_ids), pid,
                 _now(), review_run_id))
            rid = cur.lastrowid
        logger.debug("stats.start_run: id=%s board=%s kind=%s model=%s", rid, board, kind, model_used)
        return rid
    except Exception as e:
        logger.warning("stats.start_run fehlgeschlagen: %s", e)
        return None


def finish_run(run_id: int | None, outcome: str, duration_s: float | None = None) -> None:
    if not run_id:
        return
    try:
        with _db() as con:
            con.execute("UPDATE runs SET outcome=?, ended_at=?, duration_s=? WHERE id=?",
                        (outcome, _now(), duration_s, run_id))
        logger.debug("stats.finish_run: id=%s outcome=%s dauer=%s", run_id, outcome, duration_s)
    except Exception as e:
        logger.warning("stats.finish_run(%s) fehlgeschlagen: %s", run_id, e)


def bump(run_id: int | None, field: str, n: int = 1) -> None:
    """Zähler eines laufenden Runs erhöhen (done_cards / decisions)."""
    if not run_id or field not in ("done_cards", "decisions"):
        return
    try:
        with _db() as con:
            con.execute(f"UPDATE runs SET {field} = {field} + ? WHERE id=?", (n, run_id))
    except Exception as e:
        logger.warning("stats.bump(%s,%s) fehlgeschlagen: %s", run_id, field, e)


def record_review(board: str, model: str, dev_model: str, verdict: str, findings: str,
                  card_ids: list, dev_run_id: int | None = None,
                  review_run_id: int | None = None) -> None:
    try:
        with _db() as con:
            con.execute(
                "INSERT INTO reviews (dev_run_id,review_run_id,board,model,dev_model,verdict,"
                "findings,card_ids,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (dev_run_id, review_run_id, board, model, dev_model, verdict,
                 (findings or "")[:4000], json.dumps(card_ids, ensure_ascii=False), _now()))
        logger.info("stats: Review %s (%s prüfte %s) -> %s", board, model, dev_model, verdict)
    except Exception as e:
        logger.warning("stats.record_review fehlgeschlagen: %s", e)


def open_run_id(board: str, kind: str = "dev") -> int | None:
    """Laufender (nicht beendeter) Run eines Boards — für done/decision-Zähler."""
    try:
        with _db() as con:
            row = con.execute("SELECT id FROM runs WHERE board=? AND kind=? AND outcome='running' "
                              "ORDER BY id DESC LIMIT 1", (board, kind)).fetchone()
        return row["id"] if row else None
    except Exception as e:
        logger.warning("stats.open_run_id(%s) fehlgeschlagen: %s", board, e)
        return None


# ── Lesen / Auswertung ──────────────────────────────────────────────────────
def summary(days: int = 30) -> dict:
    """Kennzahlen für Dashboard/CLI: pro Modell, pro Board, Review-Quote."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    out: dict = {"days": days, "since": since, "models": [], "boards": [],
                 "reviews": [], "totals": {}}
    try:
        with _db() as con:
            out["models"] = [dict(r) for r in con.execute(
                "SELECT model_used AS model, kind, COUNT(*) AS laeufe, "
                "  SUM(done_cards) AS karten_fertig, SUM(decisions) AS entscheidungen, "
                "  ROUND(AVG(duration_s)/60.0,1) AS schnitt_min, "
                "  SUM(CASE WHEN outcome='noop' THEN 1 ELSE 0 END) AS noop, "
                "  SUM(CASE WHEN outcome='timeout' THEN 1 ELSE 0 END) AS timeout "
                "FROM runs WHERE started_at >= ? GROUP BY model_used, kind "
                "ORDER BY kind, laeufe DESC", (since,))]
            out["boards"] = [dict(r) for r in con.execute(
                "SELECT board, model_target AS soll, COUNT(*) AS laeufe, "
                "  SUM(downgraded) AS downgrades, SUM(done_cards) AS karten_fertig, "
                "  ROUND(AVG(duration_s)/60.0,1) AS schnitt_min "
                "FROM runs WHERE started_at >= ? AND kind='dev' GROUP BY board "
                "ORDER BY laeufe DESC", (since,))]
            out["reviews"] = [dict(r) for r in con.execute(
                "SELECT model, dev_model, verdict, COUNT(*) AS anzahl "
                "FROM reviews WHERE created_at >= ? GROUP BY model, dev_model, verdict "
                "ORDER BY anzahl DESC", (since,))]
            t = con.execute(
                "SELECT COUNT(*) AS laeufe, SUM(downgraded) AS downgrades, "
                "  SUM(done_cards) AS karten_fertig, "
                "  SUM(CASE WHEN kind='review' THEN 1 ELSE 0 END) AS reviews "
                "FROM runs WHERE started_at >= ?", (since,)).fetchone()
            out["totals"] = dict(t) if t else {}
            r = con.execute(
                "SELECT SUM(CASE WHEN verdict='ok' THEN 1 ELSE 0 END) AS ok, COUNT(*) AS n "
                "FROM reviews WHERE created_at >= ?", (since,)).fetchone()
            if r and r["n"]:
                out["totals"]["review_ok_quote"] = round(100.0 * (r["ok"] or 0) / r["n"], 1)
    except Exception as e:
        logger.warning("stats.summary fehlgeschlagen: %s", e)
        out["error"] = str(e)
    return out


def _print_summary(days: int) -> None:
    s = summary(days)
    t = s.get("totals", {})
    print(f"== Automat-Statistik, letzte {days} Tage ==")
    print(f"Läufe: {t.get('laeufe') or 0} (davon Reviews: {t.get('reviews') or 0}) | "
          f"Downgrades: {t.get('downgrades') or 0} | Karten fertig: {t.get('karten_fertig') or 0}"
          + (f" | Review-OK-Quote: {t['review_ok_quote']}%" if "review_ok_quote" in t else ""))
    print("\n-- pro Modell --")
    print(f"{'Modell':22s} {'Art':7s} {'Läufe':>6s} {'fertig':>7s} {'Entsch.':>8s} "
          f"{'Ø min':>7s} {'No-Op':>6s} {'Timeout':>8s}")
    for m in s["models"]:
        print(f"{m['model']:22s} {m['kind']:7s} {m['laeufe']:6d} {m['karten_fertig'] or 0:7d} "
              f"{m['entscheidungen'] or 0:8d} {m['schnitt_min'] or 0:7.1f} {m['noop'] or 0:6d} "
              f"{m['timeout'] or 0:8d}")
    print("\n-- pro Board (Dev-Läufe) --")
    for b in s["boards"][:25]:
        print(f"{b['board']:38s} soll={b['soll']:18s} Läufe={b['laeufe']:3d} "
              f"Downgr.={b['downgrades'] or 0:3d} fertig={b['karten_fertig'] or 0:3d} "
              f"Ø={b['schnitt_min'] or 0:.1f} min")
    if s["reviews"]:
        print("\n-- Reviews (Prüfer prüfte Entwickler) --")
        for r in s["reviews"]:
            print(f"{r['model']:22s} prüfte {r['dev_model']:22s} {r['verdict']:12s} {r['anzahl']:4d}")
    else:
        print("\n(noch keine Reviews erfasst)")


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Statistik des Kanban-Automaten")
    ap.add_argument("--summary", action="store_true", help="Kennzahlen ausgeben")
    ap.add_argument("--json", action="store_true", help="als JSON ausgeben")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--runs", type=int, metavar="N", help="letzte N Läufe zeigen")
    a = ap.parse_args()
    if a.runs:
        with _db() as con:
            rows = con.execute("SELECT id,board,kind,model_used,model_target,card_count,"
                               "done_cards,outcome,ROUND(duration_s/60.0,1) AS min,started_at "
                               "FROM runs ORDER BY id DESC LIMIT ?", (a.runs,)).fetchall()
        for r in rows:
            print(f"#{r['id']:4d} {r['started_at'][:16]} {r['board']:28s} {r['kind']:6s} "
                  f"{r['model_used']:20s} (soll {r['model_target']:20s}) "
                  f"Karten {r['done_cards']}/{r['card_count']} {r['outcome']:8s} {r['min'] or 0} min")
        return 0
    if a.json:
        print(json.dumps(summary(a.days), ensure_ascii=False, indent=2))
        return 0
    if a.summary:
        _print_summary(a.days)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())

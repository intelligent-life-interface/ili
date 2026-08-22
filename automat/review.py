#!/usr/bin/env python3
"""review — Prüf-Kreislauf des Kanban-Automaten.

Wurde eine Karte wegen Parallelbetrieb mit einem **tieferen** Modell entwickelt
(siehe models.choose_model), kommt sie hier in die Warteschlange. Beim nächsten Tick
startet der Orchestrator für dieses Board einen **Review-Worker** mit dem Soll-Modell,
der die Arbeit prüft und sein Urteil über `automat_cli.py review-result` zurückmeldet.

Warteschlange: `state/reviews/<slug>.json` = Liste von Jobs (FIFO, je Job eine
abgeschlossene Karten-Gruppe). Alles best-effort — schlägt das Schreiben fehl, läuft
die Entwicklung normal weiter, es findet nur kein Review statt (WARNING im Log).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import automat_lib as lib
import models

logger = lib.logger
REVIEW_DIR = lib.STATE_DIR / "reviews"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)
MAX_QUEUE = 5   # mehr als 5 offene Prüfaufträge pro Board bringen nichts


def _path(slug: str) -> Path:
    return REVIEW_DIR / f"{slug.replace('/', '_')}.json"


def _load(slug: str) -> list[dict]:
    try:
        return json.loads(_path(slug).read_text("utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("review._load(%s) fehlgeschlagen: %s", slug, e)
        return []


def _save(slug: str, jobs: list[dict]) -> None:
    try:
        if jobs:
            _path(slug).write_text(json.dumps(jobs, ensure_ascii=False, indent=2), "utf-8")
        else:
            _path(slug).unlink(missing_ok=True)
    except Exception as e:
        logger.warning("review._save(%s) fehlgeschlagen: %s", slug, e)


def enqueue(slug: str, card_id: str, card_title: str, summary: str,
            model_used: str, model_target: str, dev_run_id: int | None) -> None:
    """Eine fertiggemeldete Karte zum Prüfen vormerken (nur wenn tiefer entwickelt wurde)."""
    if not models.needs_review(model_used, model_target):
        return
    jobs = _load(slug)
    # gleiche Karte nicht doppelt einreihen
    for j in jobs:
        if j.get("card_id") == card_id:
            logger.debug("review.enqueue: %s/%s bereits in der Warteschlange", slug, card_id)
            return
    if len(jobs) >= MAX_QUEUE:
        logger.warning("review.enqueue: Warteschlange %s voll (%d) — ältester Job fällt raus",
                       slug, len(jobs))
        jobs = jobs[1:]
    jobs.append({
        "card_id": card_id, "card_title": card_title, "summary": (summary or "")[:2000],
        "model_used": model_used, "model_target": model_target,
        "review_model": models.review_model(model_target),
        "dev_run_id": dev_run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    _save(slug, jobs)
    logger.info("review: %s/%s vorgemerkt — %s entwickelte, %s prüft", slug, card_id,
                models.label(model_used), models.label(models.review_model(model_target)))


def pending(slug: str) -> dict | None:
    """Ältester offener Prüfauftrag eines Boards (ohne ihn zu entfernen)."""
    jobs = _load(slug)
    return jobs[0] if jobs else None


def boards_with_pending() -> list[str]:
    out = []
    for p in sorted(REVIEW_DIR.glob("*.json")):
        try:
            if json.loads(p.read_text("utf-8")):
                out.append(p.stem)
        except Exception:
            continue
    return out


def done(slug: str, card_id: str | None = None) -> None:
    """Prüfauftrag abschliessen (nach Urteil oder Worker-Ende)."""
    jobs = _load(slug)
    if not jobs:
        return
    rest = [j for j in jobs if card_id and j.get("card_id") != card_id] if card_id else jobs[1:]
    _save(slug, rest)
    logger.info("review: Auftrag %s/%s erledigt (%d offen)", slug, card_id or jobs[0].get("card_id"),
                len(rest))


def build_prompt(slug: str, workdir: Path, job: dict, cli: str) -> str:
    """Auftragstext für den Review-Worker (läuft mit dem Soll-Modell des Boards)."""
    dev = models.label(job.get("model_used", "?"))
    prue = models.label(job.get("review_model", job.get("model_target", "?")))
    return f"""Du bist der PRÜFER des Kanban-Automaten und arbeitest im Ordner {workdir}.

Ein Worker mit dem **schwächeren Modell {dev}** hat unter Zeitdruck (mehrere Projekte
liefen parallel) folgende Karte abgearbeitet. Du prüfst diese Arbeit mit **{prue}**.

Board:   {slug}
Karte:   {job.get('card_id')} — {job.get('card_title')}
Meldung des Workers:
{job.get('summary') or '(keine Zusammenfassung)'}

DEIN AUFTRAG — prüfen, nicht neu bauen:
1. Sieh dir an, was tatsächlich geändert wurde (`git -C {workdir} log --oneline -5`,
   `git -C {workdir} diff HEAD~1 --stat`, betroffene Dateien gezielt lesen — nie ganze
   grosse Dateien, mit grep/sed arbeiten).
2. Beurteile: Ist die Aufgabe der Karte wirklich erledigt? Funktioniert es (Syntax-Check,
   vorhandene Tests, `--dry-run`/`--status`-Aufrufe des Projekts)? Sind Doku (CLAUDE.md)
   und Debug-Logs nachgeführt? Wurden Hausregeln aus ~/CLAUDE.md verletzt (Secrets im Code,
   Commit im Home-Repo, fehlende Testversion bei `test_first`)?
3. **Kleine Mängel behebst du direkt** (Tippfehler, fehlender Log, fehlende Doku-Zeile).
   Grosse Lücken behebst du NICHT selbst — die gehen als Nacharbeit zurück.

ERGEBNIS MELDEN (genau einmal, am Ende):
  python3 {cli} review-result --board {slug} --card {job.get('card_id')} \\
      --verdict ok|nacharbeit|fehler --findings "<kurze Begründung, 1-3 Sätze>"

  ok         = Arbeit ist brauchbar (auch wenn du Kleinigkeiten selbst gefixt hast)
  nacharbeit = wesentliche Lücke -> Karte geht zurück in die Arbeit (mit deinen Findings)
  fehler     = du konntest nicht prüfen (z.B. nichts auffindbar geändert)

REGELN: Keine neuen Features. Keine Entscheidungskarten anlegen. Nie im Home-Repo (~/)
committen. Token sparen (grep/sed statt ganze Dateien). Wenn du selbst etwas korrigierst,
committe es im Projekt-Repo mit Präfix `review:`.

Fang jetzt an.

[Loop: kanban-automat-review]"""

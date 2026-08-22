#!/usr/bin/env python3
"""Scheduler: plan() und tick() — Orchestrierung der Worker."""
from datetime import datetime
from pathlib import Path

import automat_lib as lib
import backoff
import batch
import board_priority
import fable_gate
import fable_optimize
import grouping
import models
import priority_gate
import review
from automat_lib import logger

from budget import (
    capacity, starts_today, board_in_cooldown,
    MAX_STARTS_PER_DAY, NOOP_REFUND_S
)
from worker import reap, start_worker, start_review_worker, start_fable_worker

SELF_BOARDS = {"kanban-automat",         # nie sich selbst autonom bearbeiten
               "auto-entwicklung-log"}   # Protokoll-Board (wird von automat_cli done gepflegt)
PLAN_LOG = lib.LOG_DIR / "plan.log"      # Planung der nächsten Arbeiten (lesbar)
PLAN_LAST = lib.STATE_DIR / "plan_last.txt"  # letzter Plan-Inhalt (Dedup fürs 5-min-Log)


def plan(live: list, cap: int, hour: int) -> list[str]:
    """Ermittelt je freigegebenem Board die nächste anstehende Arbeit (Karten-GRUPPE)
    und schreibt das gut lesbar nach state/logs/plan.log. Reine Vorschau — startet/
    ändert NICHTS. Beim 5-min-Takt wird nur angehängt, wenn sich der Plan inhaltlich
    geändert hat (sonst flutet das Log). Gibt die Kandidaten-Slugs zurück (Reihenfolge)."""
    busy = {w.get("board") for w in live}
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"Kapazität: {cap} | lebende Worker: {len(live)} | "
             f"Starts heute: {starts_today()}/{MAX_STARTS_PER_DAY}"]
    boards = lib.auto_boards()
    lines.append(f"Freigegebene Projekte: {len(boards)}")
    pend_rev = [s for s in review.boards_with_pending() if s not in SELF_BOARDS]
    if pend_rev:
        lines.append("🔍 Offene Reviews (Prüfung durch das stärkere Modell): "
                     + ", ".join(pend_rev))
    next_up: list[str] = []  # Boards mit offener Arbeit (in Reihenfolge)
    # Priorisierung: Boards nach echter Wichtigkeit sortieren (seit 21.08.2026)
    # — high-priority Boards zuerst, statt in willkürlicher Reihenfolge.
    boards = board_priority.prioritize_boards(boards)
    for b in boards:
        slug = b.get("id")
        if slug in SELF_BOARDS:
            continue
        try:
            board = lib.get_board(slug)
        except Exception as e:
            lines.append(f"▶ {slug}\n    ⚠ Board nicht ladbar: {e}")
            continue
        if slug in busy:
            w = next((x for x in live if x.get("board") == slug), {})
            lines.append(f"▶ {slug}\n    ⏳ Worker läuft (Karte: "
                         f"{w.get('card_title') or w.get('card_id') or '?'})")
            continue
        blk = lib.board_is_blocked(board)
        if blk:
            lines.append(f"▶ {slug}\n    ⛔ parkiert — wartet auf Entscheidung: "
                         f"'{blk.get('title')}'")
            continue
        try:
            # compute=False: plan läuft alle 5 min über ALLE Boards — nur Cache
            # nutzen, nie auf Ollama warten (frisch rechnet erst der Worker-Start).
            group = grouping.next_group(slug, board, compute=False)
        except Exception as e:
            logger.warning("plan: Gruppierung %s fehlgeschlagen (%s) — Einzelkarte", slug, e)
            nxt = lib.next_card(board)
            group = [nxt] if nxt else []
        if not group:
            lines.append(f"▶ {slug}\n    – keine offene Karte")
            continue
        col, card = group[0]
        extra = ""
        if len(group) > 1:
            extra = " (+" + ", ".join(f"'{k.get('title', '')[:40]}'"
                                      for _c, k in group[1:]) + ")"
        # Modell-Vorschau: bei Parallelbetrieb würde eine Stufe tiefer entwickelt
        used, target, why = models.choose_model(slug, len(live), boards, dry=True)
        mtxt = (models.label(used) if used == target
                else f"{models.label(used)} statt {models.label(target)} ({why}) + Review")
        lines.append(f"▶ {slug}\n    → nächste Arbeit: [{col.get('title')}] "
                     f"{card.get('title')}{extra}\n    🤖 Modell: {mtxt}")
        next_up.append(slug)

    free = max(0, cap - len(live))
    bo = backoff.until()
    if bo is not None:
        lines.append(f"⇒ Geplant: nichts (Abo-Limit-Backoff bis {bo.strftime('%H:%M')})")
    elif free <= 0:
        lines.append(f"⇒ Geplant: nichts (Kapazität voll: {len(live)}/{cap})")
    elif starts_today() >= MAX_STARTS_PER_DAY:
        lines.append(f"⇒ Geplant: nichts (Tages-Startlimit {MAX_STARTS_PER_DAY} erreicht)")
    elif next_up:
        lines.append(f"⇒ Geplant zu starten (max {free} frei): {', '.join(next_up[:free])}")
    else:
        lines.append("⇒ Geplant: nichts (keine offenen Karten)")

    body = "\n".join(lines)
    try:
        last = PLAN_LAST.read_text() if PLAN_LAST.exists() else ""
    except Exception:
        last = ""
    if body == last:
        logger.info("Plan unverändert (%d Projekte, %d mit offener Arbeit) — plan.log nicht angehängt",
                    len(boards), len(next_up))
        return next_up
    try:
        PLAN_LAST.write_text(body)
        with open(PLAN_LOG, "a") as f:
            f.write(f"═══ Plan {ts} (Stunde {hour}) ═══\n{body}\n\n")
    except Exception as e:
        logger.error("plan.log schreiben fehlgeschlagen: %s", e)
    logger.info("Plan geschrieben (%d Projekte, %d mit offener Arbeit) -> %s",
                len(boards), len(next_up), PLAN_LOG)
    return next_up


def tick(dry: bool = False) -> None:
    """Ein Watchdog-Durchlauf: Aufräumen, Planung, Worker-Start."""
    hour = datetime.now().hour
    reap()
    live = lib.live_workers()
    cap = capacity(hour)
    busy_boards = {w["board"] for w in live}
    logger.info("Tick %s | Stunde=%d Kapazität=%d lebende Worker=%d (%s) Starts heute=%d/%d",
                "[dry]" if dry else "", hour, cap, len(live),
                ",".join(busy_boards) or "-", starts_today(), MAX_STARTS_PER_DAY)

    # Planung immer schreiben (sichtbar in state/logs/plan.log), unabhängig vom Start.
    # Rückgabe = Boards mit offener Arbeit (next_up); leer = echtes Idle (für Backfill-Hook (f)).
    next_up = plan(live, cap, hour)

    # (d) Batch-API-Pfad: async Karten-VORSCHLÄGE über die Message Batches API (parallel
    #     zum Abo, 50% günstiger). No-Op solange batch_enabled=0 (Default → Abo-only).
    #     Bewusst HIER, VOR dem Kapazitäts-Return: Batches laufen serverseitig, belegen
    #     keinen `claude -p`-Slot und sollen auch bei voller Worker-Auslastung weiterlaufen.
    batch.tick_step(dry=dry)

    # (e) ENTFALLEN 06.08.26 — hier lief `auto_finish.run()` und schrieb den Projekt-Status
    #     (`in_bearbeitung`/`abgeschlossen`) fertiger Boards. Falscher Träger: Manager —
    #     „der Automatische-Entwicklung-Status soll auf Abgeschlossen wechseln, das Projekt
    #     selber nicht." Der Zustand „Automat ist durch" wird im Dashboard aus den
    #     Kartenzahlen ABGELEITET (index.js AUTO_STATE + project-core.js renderAutoBtn) und
    #     braucht keinen Schreiber. Der Automat fasst weder `status` noch `auto` an.

    # Abo-Limit-Backoff (backoff.py): Nach einem Session-/Usage-Limit-Abpraller sind
    # ALLE `claude -p`-Starts (a Reviews, b Dev, c Fable) bis zur Reset-Zeit sinnlos —
    # jeder Versuch fräße nur einen Tages-Start. Batch (d) lief oben schon (API-Topf).
    bo = backoff.until()
    if bo is not None:
        logger.info("Abo-Limit-Backoff aktiv — keine claude-p-Starts bis %s.",
                    bo.strftime("%H:%M"))
        return

    if len(live) >= cap:
        logger.info("Es wird noch gearbeitet (%d/%d) — nichts zu tun.", len(live), cap)
        return

    free_slots = cap - len(live)
    started = 0
    # Start-Spreizung (08.08.26): Öffnet ein Stunden-Fenster, werden auf einen Schlag
    # oft mehrere Boards gleichzeitig frei (Budget-Gate + Cooldown fallen zusammen weg).
    # Ohne Bremse startet EIN Tick dann bis zu `cap` Worker gleichzeitig — das treibt den
    # tatsächlichen Verbrauch in einem kurzen Burst hoch und damit das Risiko, mitten im
    # Fenster ins Abo-Session-Limit zu laufen (danach blockiert der Backoff bis zum Reset).
    # `max_new_starts_per_tick` deckelt NEUE Starts je Tick — der Rest folgt in den
    # nächsten 5-Min-Ticks, die Last verteilt sich über die Fensterdauer statt zu bursten.
    new_starts_cap = lib.LIMITS["max_new_starts_per_tick"]
    # Das Tages-Startlimit deckelt die normale KARTEN-Arbeit (a+b). Der Fable-Optimier-Modus
    # (c) hat einen eigenen Ressourcen-Pool (Wochen-Budget-Kopf) + eigene strikte Drossel
    # (fable_max_runs_per_day + Gate) und wird bewusst NICHT vom Kartenlimit blockiert —
    # sonst wäre er an aktiven Tagen (Limit erschöpft) nie nutzbar, was seinem Zweck
    # („Kopf nutzen, der sonst verfällt") widerspricht.
    cards_budget_left = starts_today() < MAX_STARTS_PER_DAY
    if not cards_budget_left:
        logger.info("Tages-Startlimit erreicht (%d) — normale Kartenarbeit pausiert, "
                    "nur noch Fable-Optimierung (eigenes Limit) möglich.", MAX_STARTS_PER_DAY)

    # Manifest-Stand für (a)-(c): Modelle, test_first-Vererbung UND Familien-Guard.
    # all=1, sonst fehlen Unterprojekte (deren `model` + Verwandtschaft).
    all_boards = lib.list_boards_all()

    # (a) Reviews zuerst: was ein tieferes Modell unter Parallellast gebaut hat, prüft
    #     das Soll-Modell des Boards — bevor neue Arbeit obendrauf kommt (review.py).
    for slug in review.boards_with_pending():
        if free_slots <= 0 or started >= new_starts_cap or starts_today() >= MAX_STARTS_PER_DAY:
            break
        if slug in SELF_BOARDS or slug in busy_boards:
            continue
        fam_busy = lib.family_ids(slug, all_boards) & busy_boards
        if fam_busy:
            logger.info("Review %s Familien-Guard: verwandtes Board %s hat aktiven Worker — übersprungen.",
                        slug, ", ".join(sorted(fam_busy)))
            continue
        job = review.pending(slug)
        if not job:
            continue
        if start_review_worker(slug, job, dry):
            free_slots -= 1
            started += 1
            busy_boards.add(slug)

    # (b) normale Entwicklung — nur solange das Karten-Startlimit Kopf hat
    # Ein Budget-Fetch pro Tick reicht (ändert sich in 5 Min. nicht, budget_service
    # cached serverseitig ohnehin 60s) — Details/Grund: priority_gate.py.
    budget_status = priority_gate.fetch_budget() if cards_budget_left else None
    for b in (lib.auto_boards() if cards_budget_left else []):
        if free_slots <= 0 or started >= new_starts_cap:
            break
        slug = b.get("id")
        if slug in SELF_BOARDS or slug in busy_boards:
            continue
        # Familien-Guard: läuft schon ein Worker auf einem Vorfahr/Nachkommen, warten —
        # verwandte Boards teilen sich oft dasselbe Code-Verzeichnis (2 Claudes, 1 Repo).
        fam_busy = lib.family_ids(slug, all_boards) & busy_boards
        if fam_busy:
            logger.info("Board %s Familien-Guard: verwandtes Board %s hat aktiven Worker — übersprungen.",
                        slug, ", ".join(sorted(fam_busy)))
            continue
        if board_in_cooldown(slug):
            logger.info("Board %s im Cooldown (< %ds seit letztem Start) — übersprungen.",
                        slug, lib.LIMITS["board_cooldown_s"])
            continue
        gate_ok, gate_reason = priority_gate.allowed(b, budget_status)
        if not gate_ok:
            logger.info("Board %s Budget-Gate zu (%s) — übersprungen.", slug, gate_reason)
            continue
        try:
            board = lib.get_board(slug)
        except Exception:
            continue
        blk = lib.board_is_blocked(board)
        if blk:
            logger.info("Board %s parkiert (wartet auf Antwort: '%s') — nächstes Projekt.",
                        slug, blk.get("title"))
            continue
        try:
            group = grouping.next_group(slug, board)
        except Exception as e:
            logger.warning("tick: Gruppierung %s fehlgeschlagen (%s) — Einzelkarte", slug, e)
            nxt = lib.next_card(board)
            group = [nxt] if nxt else []
        if not group:
            logger.debug("Board %s: keine offene Karte.", slug)
            continue
        # parallel = wie viele Worker schon laufen/gestartet sind -> bestimmt das Downgrade
        if start_worker(slug, group, dry, parallel=len(busy_boards), boards=all_boards):
            free_slots -= 1
            started += 1
            busy_boards.add(slug)
            if starts_today() >= MAX_STARTS_PER_DAY:
                break

    # (c) Fable-Optimierung: freien Wochen-Budget-Kopf (der sonst verfällt) für einen
    #     projektweiten Optimierlauf mit dem stärksten Modell nutzen. Nur wenn das Gate
    #     grün ist (Schalter an + Tageskopf frei + Tageslimit nicht erreicht) und ein Slot
    #     übrig ist. Bewusst NACH der normalen Arbeit — Optimierung ist Kür, nicht Pflicht.
    if free_slots > 0 and started < new_starts_cap:   # bewusst OHNE MAX_STARTS_PER_DAY-Check — Fable hat eigenes Limit (Gate)
        gate = fable_gate.check()
        if gate["allowed"]:
            board = fable_optimize.pick_board(all_boards, busy_boards, SELF_BOARDS)
            if board is None:
                logger.debug("Fable-Gate offen, aber kein fable_optimize-Board frei.")
            else:
                slug = board["id"]
                fam_busy = lib.family_ids(slug, all_boards) & busy_boards
                if fam_busy:
                    logger.info("Fable %s Familien-Guard: verwandtes Board %s hat aktiven Worker — übersprungen.",
                                slug, ", ".join(sorted(fam_busy)))
                else:
                    logger.info("Fable-Gate offen (%s) — optimiere Projekt %s", gate["reason"], slug)
                    if start_fable_worker(slug, dry):
                        started += 1
        else:
            logger.debug("Fable-Gate zu: %s", gate["reason"])

    # (f) Backfill / Idle-Filler (2026-08-11): Nur wenn in diesem Tick WIRKLICH nichts
    #     los war — kein offener Plan (next_up leer), kein Worker gestartet, keiner aus einem
    #     früheren Tick lebt — UND ein ganzer Tag Budget-Reserve da ist (backfill_gate), lässt
    #     der KI-Advisor EINE neue Idee-Karte auf EIN auto-Board generieren (high-Prio zuerst).
    #     Der nächste Tick entwickelt sie ganz normal. Nutzt nur Budget, das sonst am
    #     Wochenende verfiele. LAZY import + komplett try/except: ein Fehler hier darf den
    #     laufenden Automaten NIE brechen. subprocess mit hartem Timeout (hält sonst den flock).
    if started == 0 and not next_up and len(live) == 0:
        try:
            import backfill_gate
            gate = backfill_gate.check()
            if gate.get("allowed"):
                logger.info("Backfill-Gate offen (%s) — starte Advisor-Idle-Filler", gate.get("reason"))
                if not dry:
                    import subprocess
                    # loop_logger ist bereits importierbar (worker.py hängt ~/bin schon beim
                    # Modul-Import dieser Datei an sys.path, s. "from worker import ..." oben) —
                    # keine zweite sys.path-Mutation nötig.
                    import loop_logger
                    loop_run_id = loop_logger.start_run(
                        "kanban-automat-backfill", "idle-filler",
                        model=backfill_gate.ADVISOR_MODEL, project=None)
                    # try/finally: finish_run MUSS auch bei Timeout/Exception laufen, sonst
                    # bleibt die Zeile für immer auf outcome='running' hängen (kein
                    # Aufräum-Job für verwaiste loop_runs-Zeilen).
                    r = None
                    try:
                        r = subprocess.run(
                            [backfill_gate.ADVISOR_PY, backfill_gate.ADVISOR_SCRIPT,
                             "--backfill", "--model", backfill_gate.ADVISOR_MODEL],
                            timeout=240, capture_output=True, text=True,
                        )
                        logger.info("Backfill: rc=%d out=%s", r.returncode, (r.stdout or "").strip()[:300])
                        if r.returncode != 0 and r.stderr:
                            logger.warning("Backfill stderr: %s", r.stderr.strip()[-300:])
                    finally:
                        loop_logger.finish_run(loop_run_id, "ok" if (r and r.returncode == 0) else "error")
                    if r is not None and r.returncode == 0:
                        backfill_gate.record_run()
            else:
                logger.debug("Backfill-Gate zu: %s", gate.get("reason"))
        except Exception as e:
            logger.warning("Backfill-Hook fehlgeschlagen (ignoriert): %s", e)

    if started == 0:
        logger.info("Keine neue Arbeit gestartet (keine freien Auto-Boards mit offenen Karten).")

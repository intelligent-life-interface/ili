#!/usr/bin/env python3
"""Worker: Start von Dev-/Review-/Fable-Workern + Reaping."""
import os
import sys
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import automat_lib as lib
import backoff
import fails
import fable_gate
import fable_optimize
import models
import review
import stats
from automat_lib import logger, now_iso

# Zentrale Loop-Statistik (Projekt/Trigger/Modell/Session-ID, separat von stats.py — siehe
# ~/.claude/plans/tidy-napping-mountain.md): standalone Modul unter ~/bin, kein Package hier.
sys.path.insert(0, str(Path.home() / "bin"))
import loop_logger  # noqa: E402

RESOLVER = Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "projterm_prepare.py"
CLI_PATH = Path(__file__).resolve().parent / "automat_cli.py"
NOOP_REFUND_S = lib.LIMITS["noop_refund_s"]

# Importing budget-Funktionen
from budget import refund_start, bump_starts, mark_board_start, age_s

# Abo-Schutz: den `claude -p`-Workern eine Umgebung OHNE Anthropic-API-Credentials
# mitgeben. Claude Code zieht einen gesetzten ANTHROPIC_API_KEY/-AUTH_TOKEN dem Abo-Login
# vor — sonst verbrennten die „gratis" Abo-Worker still API-Guthaben. Der Batch-Pfad
# (batch.py) liest seinen Key separat aus ~/config.env, nicht aus der Prozess-Env, darum
# darf/soll er hier für die Worker gescrubbt werden. Greift auch dann, wenn der Key mal
# doch in die Env rutscht (z.B. EnvironmentFile im Service oder manueller Lauf mit `source`).
_ABO_BLOCK_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _abo_env() -> dict:
    """Kopie der Umgebung ohne API-Credentials — erzwingt Abo-Auth für `claude -p`."""
    env = dict(os.environ)
    removed = [k for k in _ABO_BLOCK_VARS if env.pop(k, None) is not None]
    if removed:
        logger.debug("Worker-Env: %s entfernt (Abo statt API erzwingen)", ", ".join(removed))
    return env


def reap() -> None:
    """Beendete Worker aufräumen, hängende (Timeout) killen."""
    for w in lib.list_workers():
        slug, pid = w.get("board"), w.get("pid", 0)
        kind = w.get("kind", "dev")
        if not lib.pid_alive(pid):
            runtime = _runtime_s(w)
            logger.info("Worker fertig: %s (%s, pid %s, Laufzeit %s) -> aufgeräumt",
                        slug, kind, pid, f"{runtime:.0f}s" if runtime is not None else "unbekannt")
            noop = runtime is not None and runtime < NOOP_REFUND_S
            parked_now: list[str] = []
            if noop:
                refund_start(f"{slug} lief nur {runtime:.0f}s < {NOOP_REFUND_S}s = No-Op")
                # Abo-Limit-Abpraller (egal ob dev/review/fable): Backoff scharf machen,
                # damit der Scheduler bis zur Reset-Zeit keine weiteren claude-p-Worker
                # in dasselbe Limit schickt (08.08.26: 71 von 94 Läufen waren Abpraller).
                limit_hit = _hit_session_limit(w)
                if limit_hit:
                    backoff.arm_from_log(w.get("log", ""))
                # Fail-Counter: kommt dieselbe Karte wiederholt nicht voran, wird sie
                # geparkt — sonst schickt der 5-min-Tick endlos Worker in dieselbe Wand.
                # Nur dev-Läufe: ein Review ohne Urteil ist kein Karten-Fehlversuch.
                if kind == "dev":
                    if limit_hit:
                        # Abo-Limit war an — der Worker kam gar nicht zum Arbeiten.
                        # Kein Fail-Bump (sonst parkt eine Limit-Nacht gesunde Karten).
                        logger.warning("Worker %s: Abo-Session-/Usage-Limit erreicht — "
                                       "No-Op, Fail-Counter NICHT erhöht (Karten bleiben "
                                       "gesund, reap nach Reset)", slug)
                    else:
                        # w["cards"] ist [{"id":…,"title":…}] — nur die ids weiterreichen.
                        ids = [c.get("id") for c in (w.get("cards") or [])
                               if isinstance(c, dict) and c.get("id")]
                        parked_now = fails.park_if_exhausted(slug, ids)
            outcome = "noop" if noop else "ok"
            stats.finish_run(w.get("run_id"), outcome, runtime)
            loop_logger.finish_run(w.get("loop_run_id"), outcome)
            if kind == "review":
                # Auftrag in jedem Fall aus der Warteschlange nehmen — auch wenn der
                # Prüfer kein Urteil gemeldet hat (sonst liefe er endlos neu an).
                review.done(slug, w.get("card_id"))
            lib.clear_worker(slug)
            # Protokoll-Board: Karte zurück in die „Weiterentwickelt"-Spalte (best-effort)
            if runtime is None:
                dauer = "Laufzeit unbekannt"
            elif runtime >= 60:
                dauer = f"Laufzeit {runtime / 60:.0f} min"
            else:
                dauer = f"Laufzeit {runtime:.0f}s"
            park_hinweis = (f", {len(parked_now)} Karte(n) nach wiederholten No-Ops geparkt"
                            if parked_now else "")
            lib.autodev_update(slug,
                               line=f"⏹ Worker beendet ({dauer}"
                                    f"{', No-Op' if noop else ''}{park_hinweis})",
                               move_to=lib.AUTODEV_COL_LOG)
            continue
        age = age_s(w.get("started_at"))
        if age is not None and age > lib.WORKER_TIMEOUT_S:
            logger.warning("Worker %s (pid %s) hängt seit %ds -> kill", slug, pid, age)
            try:
                os.killpg(os.getpgid(pid), 9)
            except Exception as e:
                logger.error("kill fehlgeschlagen: %s", e)
            stats.finish_run(w.get("run_id"), "timeout", age)
            loop_logger.finish_run(w.get("loop_run_id"), "timeout")
            if kind == "review":
                review.done(slug, w.get("card_id"))
            lib.clear_worker(slug)
            lib.autodev_update(slug, line=f"⏹ Worker gekillt (Timeout nach {age / 3600:.1f} h)",
                               move_to=lib.AUTODEV_COL_LOG)


def _hit_session_limit(w: dict) -> bool:
    """True, wenn der Worker nur abbrach, weil das Claude-Abo-Limit erreicht war.
    `claude -p` gibt dann sofort z.B. 'You've hit your session limit · resets 2:50am'
    (oder die Wochen-Variante 'usage limit') aus und beendet sich nach Sekunden.

    Ein solcher Abbruch ist KEIN inhaltlicher Karten-Fehlversuch — er darf den
    Fail-Counter (fails.park_if_exhausted) NICHT hochzählen. Sonst parkt eine
    Limit-Phase gesunde Karten (Vorfall 07.08.26, 00:37–02:48: 10 Karten geparkt).
    Bewusst tolerant gematcht: ein Falsch-Positiv kostet nur einen ausgelassenen
    Fail-Bump, ein Falsch-Negativ parkt eine gesunde Karte — die Asymmetrie
    rechtfertigt breites Matching. noop-Logs sind winzig (~63 Byte), Volltext-Read ok."""
    try:
        text = Path(w.get("log", "")).read_text(errors="replace").lower()
    except Exception as e:
        logger.debug("_hit_session_limit: Log nicht lesbar (%s)", e)
        return False
    return "session limit" in text or "usage limit" in text


def _runtime_s(w: dict):
    """Laufzeit eines beendeten Workers: started_at bis mtime seines Logfiles.
    (Der Orchestrator lebt beim Worker-Ende nicht mehr — das Log ist der einzige Zeuge.)"""
    try:
        from datetime import timezone
        log = Path(w.get("log", ""))
        started = datetime.fromisoformat(w["started_at"])
        ended = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
        return max(0.0, (ended - started).total_seconds())
    except Exception as e:
        logger.debug("_runtime_s: nicht bestimmbar (%s)", e)
        return None


def resolve_workdir(slug: str) -> Path:
    """Arbeitsordner des Boards — exakt wie das Projekt-Terminal (Manifest code_dir
    -> reichste CLAUDE.md), via projterm_prepare.py --resolve."""
    try:
        out = subprocess.run([sys.executable, str(RESOLVER), "--resolve", slug],
                             capture_output=True, text=True, timeout=20)
        d = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
        if d and Path(d).is_dir():
            return Path(d)
        logger.warning("resolve_workdir(%s): '%s' ungültig", slug, d)
    except Exception as e:
        logger.warning("resolve_workdir(%s) fehlgeschlagen: %s", slug, e)
    # AUTOMAT_PROJECT_DIRS=/projects[:…] — checked first (ili release container)
    extra = [Path(d) / slug for d in os.getenv("AUTOMAT_PROJECT_DIRS", "").split(":") if d]
    for cand in (*extra, Path.home() / "containers" / slug, Path.home() / "Projekte" / slug):
        if cand.is_dir():
            return cand
    return Path.home()


def build_prompt(slug: str, workdir: Path, items: list[tuple[dict, dict]]) -> str:
    """Auftragstext für den headless Worker. items = Gruppe zusammengehöriger
    Karten (grouping.py) — eine Session arbeitet die ganze Gruppe ab."""
    col, card = items[0]
    card_id = card.get("id", "")
    card_lines = []
    for i, (c, k) in enumerate(items, 1):
        desc = (k.get("description") or "").strip()
        card_lines.append(f"  {i}. [Spalte '{c.get('title')}', ID {k.get('id')}] {k.get('title')}"
                          + (f"\n     Beschreibung: {desc}" if desc else ""))
    if len(items) > 1:
        auftrag = (f"DEINE AUFGABE — diese GRUPPE von {len(items)} zusammengehörigen "
                   "Kanban-Karten, alle in DIESER Session:\n" + "\n".join(card_lines) + """

GRUPPEN-REGELN:
- Arbeite die Karten in sinnvoller Reihenfolge ab (Abhängigkeiten zuerst).
- Melde JEDE fertige Karte einzeln über kanban-editor `done` (eigene kurze Zusammenfassung).
- Braucht EINE Karte eine Entscheidung vom Manager: parkiere sie (Notiz an die Karte, weiter mit
  den restlichen Karten der Gruppe). Die Entscheidungskarte legst du erst GANZ AM ENDE an
  (max EINE) und beendest dann die Session — so geht die Arbeit konstant weiter.""")
    else:
        auftrag = ("DEINE AUFGABE — diese eine Kanban-Karte:\n" + card_lines[0])

    # 🧪 Testversion zuerst (Manifest-Flag test_first, erbt via parent_ids):
    # Worker darf dann NIE direkt in den Prod-Container deployen.
    test_first, tf_src = lib.effective_test_first(slug)
    if test_first:
        logger.info("Board %s: test_first aktiv (Quelle: %s) — Testversion-Regeln im Prompt", slug, tf_src)
        testblock = f"""

🧪 TESTVERSION-PFLICHT (Manifest-Flag test_first{f", geerbt von '{tf_src}'" if tf_src != slug else ""}):
Dieses Projekt verlangt, dass neue Versionen ZUERST als Testversion laufen. Darum:
- Deploye NIEMALS direkt in den Produktiv-Container: kein `systemctl --user restart` der
  Prod-Unit, kein `podman restart`/`build` am Prod-Container, auch wenn die Projekt-CLAUDE.md
  das als normalen Ausroll-Weg nennt.
- Stattdessen nach deinen Code-Änderungen den Container-Manager nutzen (kopiert den aktuellen
  Container-Ordner nach <name>-test, installiert dort die neue Version und startet sie als
  eigenen Service mit Host-Ports +10000; Prod bleibt unangetastet. Daten-Mounts wie data/
  oder *.db nutzen DIREKT die Prod-Daten, aber READ-ONLY — Schreibversuche der Testversion
  in ihre DB schlagen bewusst fehl):
    KEY=$(grep '^CONTAINER_MANAGER_API_KEY=' ~/config.env | cut -d= -f2)
    curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8810/api/containers/<container-name>/test-deploy
  (<container-name> = Ordnername unter ~/containers/; Aufräumen später via .../test-remove)
- Verifiziere die Testversion (Port = Prod-Port + 10000) und schreibe in die done-Zusammenfassung:
  Test-URL/Port, dass Prod noch auf der alten Version läuft, und dass der Manager die Übernahme nach
  Prüfung selbst auslöst (.../test-promote: Beta wird die aktuelle Version, die bisherige
  wird deaktiviert als <name>-prev aufbewahrt).
- Betrifft die Karte keinen laufenden Container/Service (reine Doku/Analyse/Code ohne Deploy),
  gilt die Regel nicht. Hat das Projekt einen Host-Service statt Podman-Container (test-deploy
  meldet "keine systemd-Unit"), dann NICHT deployen — Notiz an die Karte, Manager rollt manuell aus."""
        auftrag += testblock

    return f"""Du bist ein autonomer Entwickler und arbeitest EIGENSTÄNDIG am Projekt \
'{slug}' (Arbeitsordner: {workdir}). Lies zuerst die CLAUDE.md in diesem Ordner.

{auftrag}

Kanban-Status NICHT selbst mit python3 abfragen/ändern — delegiere JEDE Status-Interaktion an
den Subagent **kanban-editor** (eigenes Kontextfenster; gibt dir nur eine kurze Bestätigung
zurück statt die volle Board-Rohausgabe von {CLI_PATH} in DEINEN Kontext zu dumpen). Er kennt die
Kommandos (show/note/decision/done) selbst — sag ihm nur WAS du willst, z.B.:
  - "kanban-editor: Stand von Board {slug} — bin ich blockiert? gibt es eine beantwortete
    Entscheidung zu Karte {card_id}, die ich umsetzen soll?"
  - "kanban-editor: notiere an Karte {card_id} auf Board {slug}: <Fortschritt>"
  - "kanban-editor: lege Entscheidungskarte auf Board {slug} an (Bezug Karte {card_id}) —
    Frage: ... Optionen: A||B||C"
  - "kanban-editor: melde Karte {card_id} auf Board {slug} fertig, Zusammenfassung: ..."

REGELN:
- Frag den kanban-editor zuerst nach dem aktuellen Stand. Liegt eine beantwortete
  '🟡 ENTSCHEIDUNG'-Karte vor (Feld `answered_decision` im show-Output, Manager-Antwort
  am Ende der description), setze diese Antwort JETZT um — sie schlägt deinen Auftrag oben.
- Sagt die Manager-Antwort sinngemäss "gehört nicht zu diesem Projekt", "verwerfen" oder
  "nicht machen": lass die Bezugskarte aussortieren
  ("kanban-editor: discard Karte <id> auf Board {slug} — Grund: <Manager-Antwort>")
  und BEENDE die Session sofort. KEINE neue Entscheidungskarte zum selben Thema,
  keine Nachfragen zur Umsetzung, kein Umzug in andere Projekte (macht der Manager selbst).
- Triff KEINE grossen Richtungs-/Designentscheidungen allein: lass dann über kanban-editor eine
  Entscheidungskarte mit klaren Optionen anlegen und BEENDE die Session danach (kein done).
  Der Manager entscheidet beim nächsten Lauf.
- Pro Board höchstens EINE offene Entscheidungskarte: zeigt `show` bereits eine decision_card,
  lege NIEMALS eine weitere an — ergänze höchstens eine Notiz an der bestehenden Karte und
  beende die Session sofort. Entscheidungskarten NUR über das decision-Kommando von {CLI_PATH}
  anlegen (setzt das Label 'Entscheidung', ohne das die Karte für Blockier-Erkennung und
  automat.html unsichtbar ist) — nie von Hand ins Board schreiben, auch nicht den
  kanban-editor eine 'ENTSCHEIDUNG'-Karte frei formulieren lassen (Vorfall dec_27630d0f
  16.08.: solche Karten umgehen den Dedup-Guard und die projekt-fremd-Erkennung).
- Wenn die Aufgabe vollständig erledigt und verifiziert ist: über kanban-editor `done` mit
  kurzer Zusammenfassung melden.
- Hängt die Karte an etwas, das DU nicht erledigen kannst (fehlende Hardware, nicht
  installierter Fremd-Dienst, ausstehender Termin, Antwort eines Dritten): NIE stillschweigend
  ohne Meldung beenden — sonst bekommt die Karte beim nächsten Tick in 5 Minuten wieder einen
  Worker, der genau dieselbe Blockade nochmal feststellt (so entstanden 202 Leerläufe auf
  einem Board). Stattdessen parken:
    "kanban-editor: parke Karte {card_id} auf Board {slug} — Grund: <woran es hängt>,
     Reaktivierung: <was passieren muss>"
  Die Karte wandert in die Warte-Spalte und ruht, bis der Manager sie zurückschiebt. `done` wäre
  hier falsch (nichts ist fertig), eine Entscheidungskarte auch (es ist keine Frage an ihn).
- Token sparen: einfache Code-/Textgenerierung direkt selbst erledigen (die Ollama-Skills
  sind seit dem Ollama-Ausstieg 16.08.2026 deaktiviert — nicht aufrufen),
  grosse Dateien nie ganz lesen. Es muss nicht schnell gehen — lieber sauber als viel.
- NIEMALS im Home-Repo (~/) committen. GitHub-Push nur mit GH_PUSH_TOKEN aus ~/config.env.
- Schweizer Recht (OR/revDSG) bei rechtlichen Themen. Gute Debug-Logs im Code.

Arbeite jetzt los.

[Loop: kanban-automat-dev]"""


def start_worker(slug: str, items: list[tuple[dict, dict]], dry: bool,
                 parallel: int = 0, boards: list[dict] | None = None) -> bool:
    """Startet einen Dev-Worker für eine Kartengruppe."""
    workdir = resolve_workdir(slug)
    prompt = build_prompt(slug, workdir, items)
    card = items[0][1]
    ids = [k.get("id") for _c, k in items]
    # Modell-Stufe: Soll aus dem Manifest, bei Parallelbetrieb eine Stufe tiefer (models.py)
    model_used, model_target, why = models.choose_model(slug, parallel, boards, dry=dry)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    logf = lib.LOG_DIR / f"worker-{slug.replace('/', '_')}-{ts}.log"
    session_id = str(uuid.uuid4())
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--model", model_used,
           "--session-id", session_id]
    if dry:
        logger.info("[dry-run] würde Worker starten: board=%s cards=%s modell=%s (soll %s: %s) "
                    "cwd=%s log=%s", slug, ",".join(ids), model_used, model_target, why,
                    workdir, logf.name)
        return True
    try:
        fh = open(logf, "w")
        proc = subprocess.Popen(cmd, cwd=str(workdir), stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env=_abo_env())
    except FileNotFoundError:
        logger.error("claude-CLI nicht im PATH gefunden — Worker nicht gestartet")
        return False
    except Exception as e:
        logger.error("Worker-Start %s fehlgeschlagen: %s", slug, e)
        return False
    # card_title bleibt das Feld, das automat.html anzeigt — bei Gruppen mit Zusatz.
    title = card.get("title", "")
    if len(items) > 1:
        title += f" (+{len(items) - 1} zusammengehörige)"
    run_id = stats.start_run(slug, "dev", model_used, model_target, parallel, ids, proc.pid)
    loop_run_id = loop_logger.start_run("kanban-automat-dev", "card-work", cwd=str(workdir),
                                        model=model_used, session_id=session_id,
                                        detail=f"board={slug} cards={len(ids)}")
    lib.write_worker({"board": slug, "card_id": card.get("id"), "card_title": title,
                      "cards": [{"id": k.get("id"), "title": k.get("title")} for _c, k in items],
                      "pid": proc.pid, "started_at": now_iso(), "log": str(logf),
                      "workdir": str(workdir), "kind": "dev", "model": model_used,
                      "model_target": model_target, "run_id": run_id,
                      "loop_run_id": loop_run_id})
    bump_starts()
    mark_board_start(slug)
    logger.info("Worker gestartet: board=%s cards=%s modell=%s (soll %s: %s) pid=%s cwd=%s",
                slug, ",".join(ids), model_used, model_target, why, proc.pid, workdir)
    # Protokoll-Board: Projekt-Karte in die „arbeitet gerade"-Spalte (best-effort)
    mtxt = models.label(model_used) + (f" statt {models.label(model_target)}"
                                       if model_used != model_target else "")
    lib.autodev_update(slug, line=f"▶️ Worker gestartet ({mtxt}): {title}",
                       move_to=lib.AUTODEV_COL_WORKING)
    return True


def start_review_worker(slug: str, job: dict, dry: bool) -> bool:
    """Prüf-Worker: das stärkere Soll-Modell kontrolliert, was ein tieferes Modell gebaut hat."""
    workdir = resolve_workdir(slug)
    model = job.get("review_model") or models.review_model(job.get("model_target", ""))
    prompt = review.build_prompt(slug, workdir, job, str(CLI_PATH))
    card_id = job.get("card_id")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    logf = lib.LOG_DIR / f"review-{slug.replace('/', '_')}-{ts}.log"
    session_id = str(uuid.uuid4())
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--model", model,
           "--session-id", session_id]
    if dry:
        logger.info("[dry-run] würde REVIEW starten: board=%s card=%s prüfer=%s (entwickelt mit %s)",
                    slug, card_id, model, job.get("model_used"))
        return True
    try:
        fh = open(logf, "w")
        proc = subprocess.Popen(cmd, cwd=str(workdir), stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env=_abo_env())
    except Exception as e:
        logger.error("Review-Start %s fehlgeschlagen: %s", slug, e)
        return False
    run_id = stats.start_run(slug, "review", model, model, 0, [card_id], proc.pid,
                             review_run_id=job.get("dev_run_id"))
    loop_run_id = loop_logger.start_run("kanban-automat-review", "review", cwd=str(workdir),
                                        model=model, session_id=session_id,
                                        detail=f"board={slug} card={card_id}")
    lib.write_worker({"board": slug, "card_id": card_id,
                      "card_title": f"🔍 Review: {job.get('card_title', '')}",
                      "cards": [{"id": card_id, "title": job.get("card_title")}],
                      "pid": proc.pid, "started_at": now_iso(), "log": str(logf),
                      "workdir": str(workdir), "kind": "review", "model": model,
                      "model_target": model, "run_id": run_id, "loop_run_id": loop_run_id,
                      "dev_model": job.get("model_used"), "dev_run_id": job.get("dev_run_id")})
    bump_starts()
    logger.info("Review gestartet: board=%s card=%s prüfer=%s (entwickelt mit %s) pid=%s",
                slug, card_id, model, job.get("model_used"), proc.pid)
    lib.autodev_update(slug, line=f"🔍 Review gestartet ({models.label(model)} prüft "
                                  f"{models.label(job.get('model_used', '?'))}): "
                                  f"{job.get('card_title', '')}",
                       move_to=lib.AUTODEV_COL_WORKING)
    return True


def start_fable_worker(slug: str, dry: bool) -> bool:
    """Fable-Optimier-Worker: das stärkste Modell analysiert ein ganzes Projekt und schlägt
    Verbesserungen als Karten vor (nur Test-Deploys, kein Prod). Gated durch fable_gate."""
    workdir = resolve_workdir(slug)
    model = fable_gate.FABLE_MODEL
    prompt = fable_optimize.build_prompt(slug, workdir, str(CLI_PATH))
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    logf = lib.LOG_DIR / f"fable-{slug.replace('/', '_')}-{ts}.log"
    session_id = str(uuid.uuid4())
    cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions", "--model", model,
           "--session-id", session_id]
    if dry:
        logger.info("[dry-run] würde FABLE-OPTIMIERUNG starten: board=%s modell=%s cwd=%s log=%s",
                    slug, model, workdir, logf.name)
        return True
    try:
        fh = open(logf, "w")
        proc = subprocess.Popen(cmd, cwd=str(workdir), stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env=_abo_env())
    except FileNotFoundError:
        logger.error("claude-CLI nicht im PATH — Fable-Worker nicht gestartet")
        return False
    except Exception as e:
        logger.error("Fable-Start %s fehlgeschlagen: %s", slug, e)
        return False
    run_id = stats.start_run(slug, "fable", model, model, 0, [], proc.pid)
    loop_run_id = loop_logger.start_run("kanban-automat-fable", "fable-optimize", cwd=str(workdir),
                                        model=model, session_id=session_id, detail=f"board={slug}")
    lib.write_worker({"board": slug, "card_id": None, "card_title": "✨ Fable-Optimierung",
                      "cards": [], "pid": proc.pid, "started_at": now_iso(), "log": str(logf),
                      "workdir": str(workdir), "kind": "fable", "model": model,
                      "model_target": model, "run_id": run_id, "loop_run_id": loop_run_id})
    bump_starts()
    mark_board_start(slug)
    fable_gate.record_fable_run()
    fable_optimize.mark_optimized(slug)
    logger.info("Fable-Optimierung gestartet: board=%s modell=%s pid=%s cwd=%s",
                slug, model, proc.pid, workdir)
    lib.autodev_update(slug, line=f"✨ Fable-Optimierung gestartet ({models.label(model)}) — "
                                  f"projektweite Verbesserungsvorschläge",
                       move_to=lib.AUTODEV_COL_WORKING)
    return True

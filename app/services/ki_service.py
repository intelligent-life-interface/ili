"""KI-Dienste — Advisor, Accept/Reject/Reactivate, Feedback, Explain-Queue,
Critique, Bug-Reports, Ollama-Stats.

Semantik 1:1 aus trigger_server.py extrahiert (Welle 4) — Board-/Manifest-Writes
laufen jetzt über die Storage-Repositories (Lock + atomar), Responses bleiben
byte-kompatibel zum Legacy-Server. Globale KI-Ablehnungen (boardübergreifende
Sperrmuster) leben getrennt in ki_global_rejections_service.py.

Schnittstelle
-------------
advisor_status() -> dict                      # Inhalt von ki_advisor_status.json
advisor_run(body) -> dict                     # startet Advisor-Prozess; raises AdvisorAlreadyRunning
ki_accept(board_id, title) -> dict            # KI-Label entfernen; raises FileNotFoundError
ki_reject(board_id, title, reason) -> dict    # Feedback + Karte → ki_archiv
ki_reactivate(board_id, title) -> dict        # Karte ki_archiv → backlog; raises FileNotFoundError
ki_feedback() -> dict                         # ki_feedback.json
explain_results(board_id, title) -> dict      # status done/queued/none
explain_queue(board_id, title, desc, board_name) -> dict
bug_report(board_id, board_name, title, desc, bug) -> dict
critique(board_name, title, desc, model) -> dict
ollama_stats() -> dict                        # immer 200, online-Flag im Body
"""
import json
import logging
import os
import re
import subprocess
from datetime import datetime

from constants import (
    KI_ADVISOR_SCRIPT,
    KI_ADVISOR_STATUS,
    KI_ADVISOR_STDERR_LOG,
    KI_BUG_REPORTS,
    KI_EXPLAIN_QUEUE,
    KI_EXPLAIN_RESULTS,
    KI_LABEL,
)
from chat_helpers import _simple_ollama_chat as _ollama_chat
from config_handler import _effort_temp, _load_ai_config
from logging_utils import _load_ki_feedback, _save_ki_feedback
from app.services import ollama_client
from app.storage.atomic_write import write_json_atomic
from app.storage.board_repository import BoardRepository
from app.storage.locking import _lock_of, file_lock

log = logging.getLogger("dashboard.services.ki")

_boards = BoardRepository()

# Der Advisor lief im Legacy-Server unter dem System-Python (/usr/bin/python3),
# nicht unter dem venv-Python der FastAPI-App — Semantik beibehalten.
_ADVISOR_PYTHON = "/usr/bin/python3"


class AdvisorAlreadyRunning(Exception):
    """KI-Advisor läuft bereits — HTTP 409 mit Spezial-Payload (error + status)."""
    def __init__(self, status: dict):
        self.status = status
        super().__init__("KI-Advisor läuft bereits")


# ── KI-Advisor ───────────────────────────────────────────────────

def advisor_status() -> dict:
    if KI_ADVISOR_STATUS.exists():
        status = json.loads(KI_ADVISOR_STATUS.read_text())
    else:
        status = {"running": False, "last_run": None, "processed": [], "errors": {}}
    log.debug("KI-Advisor-Status: running=%s, last_run=%s", status.get("running"), status.get("last_run"))
    return status


def advisor_run(body: dict) -> dict:
    """Startet den KI-Advisor als Hintergrundprozess (Einzel- oder Panel-Modus)."""
    if KI_ADVISOR_STATUS.exists():
        status = json.loads(KI_ADVISOR_STATUS.read_text())
        if status.get("running"):
            # Prüfe PID-Liveness — wenn die PID tot ist, ist der Advisor faktisch nicht mehr running.
            pid = status.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)  # Signal 0: kein Effekt, aber gibt Fehler wenn Prozess nicht läuft.
                    log.warning("KI-Advisor läuft bereits (PID %d) — kein Neustart", pid)
                    raise AdvisorAlreadyRunning(status)
                except ProcessLookupError:
                    # PID existiert nicht (der Advisor crashte/wurde stopped).
                    log.info("Alte running-PID %d tot — lockup aufgelöst, Neustart erlaubt", pid)
            else:
                # running=True aber keine PID? Auch ein Indiz für einen Crash.
                log.warning("running=True aber PID fehlt — Neustart erlaubt")

    ai_cfg = _load_ai_config()
    board_id = body.get("board_id")
    if not board_id:
        # Seit 2026-08-10 Pflicht: der Advisor läuft nur pro EINZELPROJEKT, nie mehr
        # portfolioweit über alle Boards (der alte Massenlauf erzeugte nur Müll-Karten).
        raise ValueError("board_id erforderlich — der KI-Advisor läuft nur pro Einzelprojekt")
    models = body.get("models") or ai_cfg.get("ki_advisor_panel_models")
    rounds = body.get("rounds", 2)
    model = body.get("model") or ai_cfg["ki_advisor_model"]

    if models and len(models) > 1:
        # Panel-Modus
        rounds = min(int(rounds), 3)
        cmd = [_ADVISOR_PYTHON, str(KI_ADVISOR_SCRIPT),
               "--models", ",".join(models),
               "--rounds", str(rounds)]
        log.info("Panel-Modus: models=%s, rounds=%s", models, rounds)
    else:
        # Einzelmodell
        cmd = [_ADVISOR_PYTHON, str(KI_ADVISOR_SCRIPT), "--model", model]
        log.info("Einzelmodell-Modus: model=%s", model)

    if board_id:
        cmd += ["--board", board_id]

    if not KI_ADVISOR_SCRIPT.exists():
        log.error("KI-Advisor-Skript fehlt: %s", KI_ADVISOR_SCRIPT)
        raise RuntimeError(f"KI-Advisor-Skript nicht gefunden: {KI_ADVISOR_SCRIPT}")

    log.info("Starte KI-Advisor: %s", " ".join(cmd))
    with open(KI_ADVISOR_STDERR_LOG, "ab") as stderr_log:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_log,
            start_new_session=True,
        )

    return {
        "status":   "gestartet",
        "board_id": board_id,
        "models":   models or [model],
        "rounds":   rounds if (models and len(models) > 1) else 1,
        "cmd":      " ".join(cmd),
    }


# ── Accept / Reject / Reactivate ─────────────────────────────────

def ki_accept(board_id: str, title: str) -> dict:
    """Nimmt einen KI-Vorschlag an: entfernt das KI-Label, macht ihn zur echten Aufgabe.

    Raises:
        FileNotFoundError: Board existiert nicht (Feedback ist dann trotzdem
        gespeichert — exakt wie im Legacy-Server).
    """
    # Feedback speichern (für KI-Lerneffekt) — passiert wie im Legacy VOR dem Board-Check
    feedback = _load_ki_feedback()
    feedback.setdefault("accepted", []).append({
        "board_id": board_id, "title": title,
        "timestamp": datetime.now().isoformat(),
    })
    _save_ki_feedback(feedback)

    found = False

    def mutate(board: dict):
        nonlocal found
        for col in board["columns"]:
            for card in col.get("cards", []):
                if card.get("title") == title and card.get("label") == KI_LABEL:
                    card.pop("label", None)
                    found = True
                    log.info("KI-Accept: board=%s, titel=%r", board_id, title)
                    break
            if found:
                break

    # Legacy schreibt das Board raw zurück, ohne CLAUDE.md-Rücksync
    board = _boards.update(board_id, mutate, sync_claude_md=False)
    return {"status": "ok", "found": found, "board": board}


def ki_reject(board_id: str, title: str, reason: str) -> dict:
    """Speichert eine Ablehnung + archiviert die Karte im Board (Spalte ki_archiv)."""
    # ── 1. Feedback speichern ────────────────────────
    feedback = _load_ki_feedback()
    feedback.setdefault("rejections", []).append({
        "board_id":  board_id,
        "title":     title,
        "reason":    reason,
        "timestamp": datetime.now().isoformat(),
    })
    _save_ki_feedback(feedback)
    log.info("KI-Ablehnung: board=%s, titel=%r, grund=%r", board_id, title, reason)

    # ── 2. Karte im Board archivieren ─────────────────
    moved = False

    def mutate(board: dict):
        nonlocal moved
        # ki_archiv Spalte finden oder anlegen
        archiv_col = next((c for c in board["columns"] if c.get("id") == "ki_archiv"), None)
        if archiv_col is None:
            archiv_col = {"id": "ki_archiv", "title": "🗄️ KI-Archiv", "cards": []}
            board["columns"].append(archiv_col)

        # Karte in allen Spalten suchen und verschieben
        for col in board["columns"]:
            if col.get("id") == "ki_archiv":
                continue
            for i, card in enumerate(col.get("cards", [])):
                if card.get("title") == title and card.get("label") == KI_LABEL:
                    card["rejected"] = True
                    card["rejection_reason"] = reason
                    card["rejected_at"] = datetime.now().strftime("%Y-%m-%d")
                    archiv_col["cards"].insert(0, card)
                    col["cards"].pop(i)
                    moved = True
                    log.debug("Karte '%s' aus '%s' in ki_archiv verschoben", title, col["id"])
                    break
            if moved:
                break

    try:
        board = _boards.update(board_id, mutate, sync_claude_md=False)
    except FileNotFoundError:
        # Legacy: fehlendes Board ist hier KEIN Fehler — Feedback zählt trotzdem
        return {"status": "ok", "note": "Board-Datei nicht gefunden"}
    return {"status": "ok", "moved": moved, "board": board}


def ki_reactivate(board_id: str, title: str) -> dict:
    """Reaktiviert eine abgelehnte KI-Karte: verschiebt sie aus dem Archiv in den Backlog.

    Raises:
        FileNotFoundError: Board existiert nicht.
    """
    moved = False

    def mutate(board: dict):
        nonlocal moved
        for col in board["columns"]:
            if col.get("id") != "ki_archiv":
                continue
            for i, card in enumerate(col.get("cards", [])):
                if card.get("title") == title:
                    card.pop("rejected", None)
                    card.pop("rejection_reason", None)
                    card.pop("rejected_at", None)
                    card.pop("archived_at", None)
                    card["label"] = KI_LABEL  # bleibt KI-Karte, Nutzer entscheidet dann
                    # In Backlog verschieben
                    for bcol in board["columns"]:
                        if bcol.get("id") == "backlog":
                            bcol.setdefault("cards", []).insert(0, card)
                            break
                    col["cards"].pop(i)
                    moved = True
                    log.info("KI-Reactivate: board=%s, titel=%r", board_id, title)
                    break
            break

    board = _boards.update(board_id, mutate, sync_claude_md=False)
    return {"status": "ok", "moved": moved, "board": board}


# ── Feedback ─────────────────────────────────────────────────────

def ki_feedback() -> dict:
    feedback = _load_ki_feedback()
    log.debug("KI-Feedback: %d Einträge", len(feedback.get("rejections", [])))
    return feedback


# ── Explain-Queue / -Results ─────────────────────────────────────

def explain_results(board_id: str, title: str) -> dict:
    """Gespeichertes Erklärungs-Ergebnis (oder Queue-Status) für eine Karte."""
    key = f"{board_id}::{title}"

    results = {}
    if KI_EXPLAIN_RESULTS.exists():
        results = json.loads(KI_EXPLAIN_RESULTS.read_text())

    if key in results:
        log.debug("Explain-Ergebnis gefunden für: %r", key)
        return {"status": "done", "text": results[key]["text"],
                "critiques": results[key].get("critiques", []),
                "model": results[key].get("model", ""),
                "created_at": results[key].get("created_at", "")}

    # Prüfen ob in Queue
    queue = []
    if KI_EXPLAIN_QUEUE.exists():
        queue = json.loads(KI_EXPLAIN_QUEUE.read_text())
    in_queue = any(t.get("board_id") == board_id and t.get("title") == title for t in queue)
    return {"status": "queued" if in_queue else "none"}


def explain_queue(board_id: str, title: str, desc: str, board_name: str) -> dict:
    """Fügt einen Erklärungsauftrag zur Nacht-Queue hinzu (idempotent).

    Kompletter Read-Modify-Write unter file_lock + atomarem Schreiben: der
    Nacht-Worker (jobs/ki_explain_worker.py) schreibt DIESELBE Datei aus einem
    anderen Prozess — ohne den geteilten Lock (_lock_of) würde er frisch
    eingereihte Aufträge überschreiben (Lost Update / stiller Queue-Verlust).
    """
    with file_lock(_lock_of(KI_EXPLAIN_QUEUE)):
        queue = []
        if KI_EXPLAIN_QUEUE.exists():
            try:
                queue = json.loads(KI_EXPLAIN_QUEUE.read_text())
            except Exception:
                log.error("Explain-Queue %s unlesbar/kaputt — starte leer",
                          KI_EXPLAIN_QUEUE, exc_info=True)
                queue = []

        key = f"{board_id}::{title}"
        already = any(t.get("board_id") == board_id and t.get("title") == title for t in queue)

        if not already:
            queue.append({
                "board_id":   board_id,
                "board_name": board_name,
                "title":      title,
                "desc":       desc,
                "queued_at":  datetime.now().isoformat(),
            })
            write_json_atomic(KI_EXPLAIN_QUEUE, queue)
            log.info("Explain-Queue: Auftrag hinzugefügt: %r (%d gesamt)", key, len(queue))
            return {"status": "queued", "queue_size": len(queue)}

        log.debug("Explain-Queue: Auftrag bereits vorhanden: %r", key)
        return {"status": "already_queued", "queue_size": len(queue)}


# ── Bug-Reports zu KI-Vorschlägen ────────────────────────────────

def bug_report(board_id: str, board_name: str, title: str, desc: str, bug: str) -> dict:
    with file_lock(_lock_of(KI_BUG_REPORTS)):
        reports = []
        if KI_BUG_REPORTS.exists():
            try:
                reports = json.loads(KI_BUG_REPORTS.read_text())
            except Exception:
                # Stiller Datenverlust darf nicht ohne Logzeile passieren.
                log.error("Bug-Reports %s unlesbar/kaputt — starte leer (bestehende "
                          "Reports gehen verloren)", KI_BUG_REPORTS, exc_info=True)
                reports = []

        reports.append({
            "board_id":   board_id,
            "board_name": board_name,
            "title":      title,
            "desc":       desc,
            "bug":        bug,
            "reported_at": datetime.now().isoformat(),
        })
        write_json_atomic(KI_BUG_REPORTS, reports)
        log.info("Bug-Report für %r: %s", title, bug[:60])
        return {"status": "ok", "total": len(reports)}


# ── Critique (Ollama-Gegenargumente) ─────────────────────────────

def critique(board_name: str, title: str, desc: str, model: str | None) -> dict:
    """Lässt Ollama 3 Gegenargumente für einen KI-Vorschlag generieren."""
    model = model or _load_ai_config().get("ki_critique_model", "qwen2.5-coder:latest")

    prompt = (
        f"Du bist ein kritischer Software-Entwickler. "
        f"Nenne genau 3 konkrete Einwände oder Gegenargumente gegen folgenden Entwicklungsvorschlag "
        f"für das Projekt \"{board_name}\":\n\n"
        f"Titel: {title}\n"
        + (f"Beschreibung: {desc}\n\n" if desc else "\n")
        + "Antworte NUR mit einem JSON-Array, keine Erklärung davor oder danach:\n"
        '[{"text": "Einwand 1"}, {"text": "Einwand 2"}, {"text": "Einwand 3"}]'
    )

    raw_result = _ollama_chat({
        "model":    model,
        "messages": [{"role": "user", "content": prompt}],
        "options":  {"temperature": _effort_temp("ki_critique_effort")},
    }, context="ki_critique")
    raw_text = raw_result.get("message", {}).get("content", "")
    log.debug("Critique raw: %s", raw_text[:200])

    # JSON extrahieren
    m = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if m:
        critiques = json.loads(m.group(0))
        critiques = [{"text": str(c.get("text", ""))[:200]} for c in critiques if c.get("text")]
    else:
        critiques = [{"text": raw_text.strip()[:300]}]

    log.info("Critique für %r: %d Punkte", title, len(critiques))
    return {"critiques": critiques[:3]}


# ── Ollama-Stats ─────────────────────────────────────────────────

def ollama_stats() -> dict:
    """Fragt Ollama-Status ab: laufende Modelle, verfügbare Modelle.

    Gibt bei Nichterreichbarkeit KEINEN Fehler, sondern online=False (Legacy: HTTP 200).
    """
    try:
        ps_data = ollama_client.ps(timeout=5)
        tags_data = ollama_client.tags(timeout=5)

        running_models = ps_data.get("models", [])
        all_models = tags_data.get("models", [])

        def fmt_bytes(b):
            if b >= 1024**3:
                return f"{b/1024**3:.1f} GB"
            if b >= 1024**2:
                return f"{b/1024**2:.0f} MB"
            return f"{b} B"

        result = {
            "online": True,
            "running_models": [
                {
                    "name":       m.get("name"),
                    "size_vram":  fmt_bytes(m.get("size_vram", 0)),
                    "size":       fmt_bytes(m.get("size", 0)),
                    "expires_at": m.get("expires_at"),
                }
                for m in running_models
            ],
            "all_models": [
                {
                    "name": m.get("name"),
                    "size": fmt_bytes(m.get("size", 0)),
                }
                for m in sorted(all_models, key=lambda x: x.get("size", 0), reverse=True)
            ],
            "model_count": len(all_models),
        }
        log.debug("Ollama-Stats: %d laufend, %d gesamt", len(running_models), len(all_models))
        return result
    except Exception as e:
        log.warning("Ollama nicht erreichbar: %s", e)
        return {"online": False, "error": str(e), "running_models": [], "all_models": []}
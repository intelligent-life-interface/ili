#!/usr/bin/env python3
"""
automat_lib — gemeinsame Bausteine für den Kanban-Automaten.

Der Automat arbeitet Kanban-Karten autonom ab: ein stündlicher Watchdog
(orchestrator.py) prüft, ob noch gearbeitet wird, und startet sonst für ein
freigegebenes Board (Manifest-Flag `auto: true`) einen headless Claude-Worker.

Dieses Modul kapselt:
  * Dashboard-HTTP-API-Zugriff (Port 8798) — NIE direkt boards/*.json schreiben!
  * Worker-State (state/workers/<slug>.json) inkl. Liveness via os.kill(pid, 0)
  * Board-/Karten-Auswahl (nächste actionable Karte, Blockier-Erkennung)
  * Logging nach state/logs/automat.log

Konventionen siehe README.md / CLAUDE.md.
"""
from __future__ import annotations

import re
import json
import os
import sys
import time
import signal
import logging
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import limits

# ── Pfade ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
WORKERS_DIR = STATE_DIR / "workers"
LOG_DIR = STATE_DIR / "logs"
for _d in (WORKERS_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def config_env(key: str) -> str:
    """Wert aus der Prozess-Env, sonst best-effort aus ~/config.env gelesen
    (Konvention wie batch.py:_api_key — systemd lädt config.env nicht automatisch,
    ~/config.env ist die geteilte Datei ALLER Homeserver-Projekte, darum projekt-
    präfigierte Keys statt generischer Namen wie BRIDGE_URL/DASHBOARD_URL)."""
    val = os.getenv(key, "").strip()
    if val:
        return val
    cfg = Path(os.getenv("ILI_CONFIG_ENV", str(Path.home() / "config.env")))
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _detect_kanban_source() -> str:
    """Identity rule shared with ~/.claude/statusline-kanban.sh: KANBAN_SOURCE
    env if set, else the tmux session name (term2, proj-<slug>), else "".
    Sent as X-Kanban-Source on every dashboard API call so board activity
    events can be attributed to the terminal (or automat) that caused them.
    """
    src = os.getenv("KANBAN_SOURCE", "").strip()
    if src:
        return src
    if os.getenv("TMUX"):
        try:
            import subprocess
            out = subprocess.run(["tmux", "display-message", "-p", "#S"],
                                 capture_output=True, text=True, timeout=2)
            return out.stdout.strip()
        except Exception as e:
            logging.getLogger("automat").debug("tmux source lookup failed: %s", e)
    return ""


KANBAN_SOURCE = _detect_kanban_source()
# Drossel-Limits: zentral in limits.py (Datei > Env > Default), per Dashboard-GUI
# änderbar — siehe /automat.html → "⚙️ Drossel".
LIMITS = limits.load()
# User-Vorgabe 16.07.26: "mehrere Tasks können aktiv sein" — Parallelität je Tageszeit
# in orchestrator.capacity(); MAX_PARALLEL ist die harte Obergrenze darüber.
MAX_PARALLEL = LIMITS["max_parallel"]
# Worker-Modell: Abo-CLI (claude -p nutzt die lokale Anmeldung = Abo, kein API-Guthaben).
# VERALTET seit 23.07.26 — das Modell wird jetzt PRO BOARD bestimmt (models.py: Manifest-Feld
# `model` + Downgrade bei Parallelbetrieb). Bleibt nur als Notnagel-Default stehen.
WORKER_MODEL = os.getenv("AUTOMAT_WORKER_MODEL", "claude-sonnet-5")
# Nach dieser Laufzeit gilt ein Worker als hängend und wird aufgeräumt (Default 2h).
WORKER_TIMEOUT_S = LIMITS["worker_timeout_s"]

# Label-Texte als Protokoll zwischen Worker und Orchestrator
LABEL_DECISION = "Entscheidung"   # offene Entscheidungskarte => Board blockiert
LABEL_AUTOMAT = "Automat"         # vom Automaten bearbeitet/angelegt

# Spalten-Erkennung per Substring (Boards nutzen unterschiedliche IDs/Titel)
# 03.08.26: Park-Spalte für Karten, die an etwas ausserhalb der Reichweite des Automaten
# hängen (Hardware fehlt, Termin steht aus, fremder Dienst nicht installiert). Ohne diese
# Art fielen sie unter "other" und wurden bei JEDEM 5-min-Tick erneut angefasst — der
# Worker erkannte die Blockade, beendete ohne `done`, und beim nächsten Tick von vorn.
# Bewusst ENGE Muster: ein falscher Treffer macht echte Arbeit unsichtbar.
PARKED_HINTS = ("wartet auf", "parkiert", "geparkt", "⏸")
# Titel-Marker einer Entscheidungskarte am Kartenanfang, tolerant gegenüber führenden
# Emoji und einem Zusatzwort ('Entscheidung offen:', 'Entscheidung vertagt:'). Wortanfang
# und Doppelpunkt sind Pflicht, sonst matchen 'Kaufentscheidung dokumentieren' o.ä.
# ⚠️ Zwillings-Regex in dashboard/app/api/automat.py (_DECISION_TITLE_RE) — immer beide ändern.
_DECISION_TITLE_RE = re.compile(r"^[\W_]*Entscheidung(?:\s+\w+)?\s*:", re.IGNORECASE)
# 'archiv' = abgelegte/verworfene Karten (z.B. Advisor-Spalte 'ki_archiv' / '🗄️ KI-Archiv').
# Wie 'parked' vom Automaten NICHT abzuarbeiten — sonst entwickelt er verworfene KI-Vorschläge
# (Token-Verschwendung) UND das Board gilt nie als idle (Advisor-Backfill triggert dann nie).
ARCHIV_HINTS = ("archiv",)
DONE_HINTS = ("erledig", "done", "fertig", "abgeschlossen", "behoben", "fixed")
REVIEW_HINTS = ("überprüf", "uberpruf", "review", "prüf", "test")
PROGRESS_HINTS = ("arbeit", "progress", "doing", "wip")
BACKLOG_HINTS = ("backlog", "todo", "to do", "offen", "ideen", "geplant")
SKIP_CARD_IDS = {"claudemd-description"}

# ── Logging ─────────────────────────────────────────────────────────────────
logger = logging.getLogger("automat")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s")
    _fh = logging.FileHandler(LOG_DIR / "automat.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)

# ── Konfiguration ───────────────────────────────────────────────────────────
DASHBOARD_URL = (os.getenv("DASHBOARD_URL") or config_env("KANBAN_AUTOMAT_DASHBOARD_URL")).rstrip("/")
if not DASHBOARD_URL:
    logger.error("automat_lib: KANBAN_AUTOMAT_DASHBOARD_URL fehlt (env oder ~/config.env) — Dashboard-Zugriff nicht moeglich")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_question_project_foreign(question: str) -> bool:
    """Klassifiziert, ob eine Entscheidungsfrage projekt-fremd ist.

    Projekt-fremde Fragen behandeln Terminal-Config, Claude-Code-Workflow,
    allgemeine CLI-Themen — nicht Projekt-spezifisches. Diese landen im
    home-stack-meta-Board statt im aktuell offenen Projekt-Board.

    Klassifizierung: Keywords-Liste (Fail-Safe via Manager, der Karte manuell
    verschieben kann, falls False-Positive). Matching auf Wortgrenzen, nicht
    Substring — sonst triggert z.B. "modell" in "modelliere" fälschlich
    (Fehlrouting einer EMDR-Entscheidungskarte am 2026-08-16/18 beobachtet).

    Return: True wenn projekt-fremd → meta-board, False sonst → projekt-board.
    """
    keywords = {
        "terminal", "cli", "befehl", "shell", "bash", "zsh", "tmux",
        "rdp", "zwischenablage", "clipboard",
        "login", "auth", "session", "limit", "claude-code", "claude code",
        "config", "konfiguration", "einstellung", "shortcut", "keybinding",
        "prompt", "modell", "token", "abo", "abonnement"
    }
    q_lower = (question or "").lower()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", q_lower):
            logger.debug("is_question_project_foreign: '%s' erkannt als projekt-fremd (Keyword: %s)",
                        question[:60], kw)
            return True
    return False


# ── Dashboard-API ───────────────────────────────────────────────────────────
def _req(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict | list:
    """HTTP-Aufruf gegen die Dashboard-API. Wirft bei != 2xx."""
    url = f"{DASHBOARD_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if KANBAN_SOURCE:
        req.add_header("X-Kanban-Source", KANBAN_SOURCE)
    logger.debug("API %s %s%s", method, path, f" body={len(data)}B" if data else "")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        logger.error("API %s %s -> %s %s", method, path, e.code, detail)
        raise
    except Exception as e:
        logger.error("API %s %s -> %s", method, path, e)
        raise


def list_boards() -> list[dict]:
    """Manifest-Einträge aller Boards."""
    res = _req("GET", "/boards")
    if isinstance(res, dict):
        return res.get("boards", [])
    return res or []


def list_boards_all() -> list[dict]:
    """Manifest-Einträge inkl. Unterprojekte (`?all=1`).

    Der Default von GET /boards liefert nur Top-Level-Boards — wer Felder eines
    Unterprojekts braucht (model, test_first, parent_ids), muss all=1 nehmen."""
    res = _req("GET", "/boards?all=1")
    if isinstance(res, dict):
        return res.get("boards", [])
    return res or []


# Status-Werte, bei denen der Automat ein Board NIE bearbeitet (keine Worker,
# keine Entscheidungs-Fragen). "pausiert" = bewusst ruhen gelassen, "archiviert"
# = aus der Übersicht ausgeblendet. Beides soll den Automaten stumm halten.
PAUSED_STATUSES = {"pausiert", "archiviert"}


def auto_boards() -> list[dict]:
    """Nur die für den Automaten freigegebenen Boards (Manifest-Flag auto==true),
    ausgenommen pausierte/archivierte (deren Status soll den Automaten stumm halten).

    Seit 16.08.2026 via list_boards_all(): der Default von GET /boards filtert
    Boards mit parent_ids weg — 21 Unterprojekte mit auto:true wurden dadurch nie
    bearbeitet. Ein Board wird zusätzlich übersprungen, wenn ein VORFAHR
    pausiert/archiviert ist (Pause am Mutterprojekt stellt den ganzen Teilbaum ruhig)."""
    boards = list_boards_all()
    by_id = {b.get("id"): b for b in boards}
    out = []
    for b in boards:
        if b.get("auto") is not True:
            continue
        if b.get("status") in PAUSED_STATUSES:
            logger.info("auto_boards: Board %r übersprungen (status=%s)",
                        b.get("id"), b.get("status"))
            continue
        anc = _paused_ancestor(b, by_id)
        if anc:
            logger.info("auto_boards: Board %r übersprungen (Vorfahr %r ist %s)",
                        b.get("id"), anc.get("id"), anc.get("status"))
            continue
        out.append(b)
    return out


def _paused_ancestor(entry: dict, by_id: dict) -> dict | None:
    """Erster pausierter/archivierter Vorfahr via parent_ids-Kette (BFS, zyklussicher),
    sonst None. Gleiche Traversierung wie effective_test_first()."""
    seen = {entry.get("id")}
    queue = _parent_ids(entry)
    while queue:
        nxt: list = []
        for pid in queue:
            if pid in seen:
                continue
            seen.add(pid)
            p = by_id.get(pid)
            if not p:
                continue
            if p.get("status") in PAUSED_STATUSES:
                return p
            nxt.extend(_parent_ids(p))
        queue = nxt
    return None


def family_ids(slug: str, boards: list[dict]) -> set:
    """IDs aller Vorfahren UND Nachkommen von slug (ohne slug selbst), zyklussicher.

    Basis für den Familien-Guard im Scheduler: Mutter- und Unterprojekt teilen sich
    oft dasselbe Code-Verzeichnis — zwei gleichzeitige Worker wären dort zwei
    headless Claudes im selben Repo."""
    by_id = {b.get("id"): b for b in boards}
    children: dict[str, set] = {}
    for b in boards:
        for pid in _parent_ids(b):
            children.setdefault(pid, set()).add(b.get("id"))
    fam: set = set()
    seen = {slug}
    queue = _parent_ids(by_id.get(slug, {}))
    while queue:  # Vorfahren
        nxt: list = []
        for pid in queue:
            if pid in seen:
                continue
            seen.add(pid)
            fam.add(pid)
            p = by_id.get(pid)
            if p:
                nxt.extend(_parent_ids(p))
        queue = nxt
    seen = {slug}
    queue = list(children.get(slug, ()))
    while queue:  # Nachkommen
        nxt = []
        for cid in queue:
            if cid in seen:
                continue
            seen.add(cid)
            fam.add(cid)
            nxt.extend(children.get(cid, ()))
        queue = nxt
    return fam


def _parent_ids(entry: dict) -> list:
    ids = entry.get("parent_ids")
    if ids is not None:
        return list(ids) if isinstance(ids, list) else [ids]
    legacy = entry.get("parent_id")
    return [legacy] if legacy else []


def effective_test_first(slug: str, boards: list[dict] | None = None) -> tuple[bool, str | None]:
    """Effektives Manifest-Flag `test_first` ("Testversion zuerst deployen").

    Eigener bool-Wert gewinnt; ohne eigenen Wert erbt das Board via parent_ids-Kette
    vom Mutterprojekt (BFS, zyklussicher — gleiche Logik wie resolveTestFirst() im
    Dashboard-Frontend project.js). Liefert (wert, quelle_board_id|None).
    """
    if boards is None:
        # WICHTIG: all=1 — der Default von GET /boards liefert nur Top-Level-Boards,
        # Unterprojekte (die hier ja erben sollen) fehlen darin.
        res = _req("GET", "/boards?all=1")
        boards = res.get("boards", []) if isinstance(res, dict) else (res or [])
    by_id = {b.get("id"): b for b in boards}
    entry = by_id.get(slug)
    if not entry:
        logger.debug("effective_test_first: Board %r nicht im Manifest", slug)
        return (False, None)
    if isinstance(entry.get("test_first"), bool):
        return (entry["test_first"], slug)
    seen = {slug}
    queue = _parent_ids(entry)
    while queue:
        nxt: list = []
        for pid in queue:
            if pid in seen:
                continue
            seen.add(pid)
            p = by_id.get(pid)
            if not p:
                continue
            if isinstance(p.get("test_first"), bool):
                logger.debug("effective_test_first: %s erbt test_first=%s von %s",
                             slug, p["test_first"], pid)
                return (p["test_first"], pid)
            nxt.extend(_parent_ids(p))
        queue = nxt
    return (False, None)


def get_board(slug: str) -> dict:
    """Board-Inhalt (columns/cards). FastAPI: GET /board?id=<slug>."""
    return _req("GET", f"/board?id={urllib.parse.quote(slug)}")


def save_board(slug: str, board: dict) -> dict:
    """Board speichern. POST /board?id=<slug> (Repository macht fcntl-Lock)."""
    return _req("POST", f"/board?id={urllib.parse.quote(slug)}", board)


def save_board_with_retry(slug: str, board: dict, max_retries: int = 3) -> dict:
    """Board speichern mit 409-Retry (Stale Revision).

    Bei rev-Mismatch: lädt aktuellste Board-Version, überträgt Änderungen,
    versucht erneut (bis max_retries mal). Debuglog für jeden Versuch.

    Returniert die neue Revision wie save_board().
    Wirft bei Fehler (bleibt stale auch nach Retries).
    """
    for attempt in range(max_retries):
        try:
            path = f"/board?id={urllib.parse.quote(slug)}"
            logger.debug("save_board_with_retry: %s v%s (attempt %d/%d)",
                        slug, board.get("rev", "?"), attempt + 1, max_retries)
            return _req("POST", path, board)
        except urllib.error.HTTPError as e:
            if e.code != 409 or attempt == max_retries - 1:
                # Nicht 409 oder letzer Versuch: Fehler propagieren
                logger.error("save_board_with_retry: %s fehlgeschlagen (attempt %d, code %d)",
                            slug, attempt + 1, e.code)
                raise
            # 409: Server-Board ist neuer, erneut laden
            logger.warning("save_board_with_retry: %s hat stale rev=%s (attempt %d), lade neu",
                          slug, board.get("rev", "?"), attempt + 1)
            time.sleep(0.1 * (attempt + 1))  # exponential backoff
            try:
                fresh = get_board(slug)
                # Aktuelle Board-Struktur übernehmen, Änderungen wieder eintragen
                # (einfache Strategie: Spalten/Karten-IDs sind stabil, nur Inhalt merged)
                fresh_by_col = {c.get("id"): c for c in fresh.get("columns", [])}
                for col in board.get("columns", []):
                    col_id = col.get("id")
                    if col_id in fresh_by_col:
                        # Übernehme neue rev + Spalten-Struktur vom Server, aber unser cards
                        fresh_by_col[col_id]["cards"] = col.get("cards", [])
                board = fresh
                board["columns"] = [fresh_by_col.get(c.get("id"), c) for c in board.get("columns", [])]
            except Exception as merge_err:
                logger.error("save_board_with_retry: Merge nach 409 fehlgeschlagen (%s)", merge_err)
                raise
    assert False, "unreachable (while loop with early exit)"


# ── Spalten-/Karten-Heuristik ───────────────────────────────────────────────
def _col_kind(col: dict) -> str:
    """Klassifiziert eine Spalte grob über Titel/ID."""
    t = (str(col.get("title", "")) + " " + str(col.get("id", ""))).lower()
    # Zuerst prüfen: 'Wartet auf Manager — abgeschlossen' soll 'parked' sein, nicht 'done'.
    if any(h in t for h in PARKED_HINTS):
        return "parked"
    # Vor DONE: 'archiviert' enthält 'archiv' — Archiv-Spalten sollen 'archiv' sein, nicht 'done'.
    if any(h in t for h in ARCHIV_HINTS):
        return "archiv"
    if any(h in t for h in DONE_HINTS):
        return "done"
    if any(h in t for h in REVIEW_HINTS):
        return "review"
    if any(h in t for h in PROGRESS_HINTS):
        return "progress"
    if any(h in t for h in BACKLOG_HINTS):
        return "backlog"
    return "other"


def reorder_columns(columns: list[dict]) -> list[dict]:
    """Erzwingt die Spaltenreihenfolge-Regel (2026-08-17): 'parked' (Wartet) direkt
    vor die erste 'progress'-Spalte (In Bearbeitung), 'done' und 'archiv' immer ganz
    rechts (in dieser Reihenfolge). Alle anderen Spalten behalten ihre bisherige
    Reihenfolge — nur stabile Umgruppierung, keine inhaltliche Sortierung.

    park_card()/discard_card() hängten neue Spalten bisher blind ans Ende (board.
    columns.append), das landete rechts von 'Erledigt' statt links von 'In
    Bearbeitung' bzw. vor 'Erledigt'/'Archiv' (Bug-Report card_41adaed5)."""
    kinds = [_col_kind(c) for c in columns]
    parked = [c for c, k in zip(columns, kinds) if k == "parked"]
    done = [c for c, k in zip(columns, kinds) if k == "done"]
    archiv = [c for c, k in zip(columns, kinds) if k == "archiv"]
    rest = [c for c, k in zip(columns, kinds) if k not in ("parked", "done", "archiv")]

    rest_kinds = [_col_kind(c) for c in rest]
    insert_at = rest_kinds.index("progress") if "progress" in rest_kinds else len(rest)

    return rest[:insert_at] + parked + rest[insert_at:] + done + archiv


def _has_label(card: dict, text: str) -> bool:
    for lb in card.get("labels", []) or []:
        if isinstance(lb, dict) and lb.get("text") == text:
            return True
    return False


def is_decision_card(card: dict) -> bool:
    """Erkennt Entscheidungskarten robust. Norm ist das Label 'Entscheidung'
    (automat_cli decision setzt es), aber Worker/Subagents haben Karten auch OHNE
    Label angelegt (Vorfall 11.07.26: ids 'decision_…', teils 'ENTSCHEIDUNG' im
    Titel) — die wurden dann fälschlich als 'nächste Arbeit' gewählt und haben
    das Tages-Startlimit mit No-Op-Läufen verbrannt."""
    if _has_label(card, LABEL_DECISION):
        return True
    # 03.08.26: auch 'dec_…' — das Dashboard-Frontend vergibt diesen kürzeren Präfix,
    # und solche Karten trugen weder Label noch Titel-Marker. Folge: board_is_blocked()
    # meldete 'frei', der Orchestrator startete alle 5 min einen Worker, der die Blockade
    # selbst erkannte und sofort aufgab — allein chile-spanisch 202 No-Op-Läufe (0 fertig)
    # und crowdentwicklung-2 34, zusammen 42 % aller Dev-Läufe von 30 Tagen.
    if str(card.get("id", "")).startswith(("decision", "dec_")):
        logger.debug("is_decision_card: %s per id-Präfix erkannt (Label fehlt)", card.get("id"))
        return True
    # Bewusst case-sensitiv mit Doppelpunkt (Protokoll-Marker '… ENTSCHEIDUNG: …') —
    # sonst matchen normale Karten wie 'Kaufentscheidung dokumentieren'.
    if "ENTSCHEIDUNG:" in str(card.get("title", "")):
        logger.debug("is_decision_card: %s per Titel-Marker erkannt (Label fehlt)", card.get("id"))
        return True
    # 17.08.26: Kleinschreibung + Zusatzwort ('❓ Entscheidung: …', '🧩 Entscheidung offen: …')
    # fielen durch — solche Karten galten dem Orchestrator als normale Arbeit und dem
    # Dashboard als nicht vorhanden (GET /api/automat/decisions meldete count 0 bei 7 offenen Fragen).
    if _DECISION_TITLE_RE.match(str(card.get("title", ""))):
        logger.debug("is_decision_card: %s per Titel-Regex erkannt (Label fehlt)", card.get("id"))
        return True
    return False


def board_is_blocked(board: dict) -> dict | None:
    """Gibt die offene Entscheidungskarte zurück, falls eine existiert (=> Board wartet
    auf den User). Eine Entscheidungskarte in einer 'done'-Spalte gilt als beantwortet."""
    for col in board.get("columns", []):
        if _col_kind(col) in ("done", "archiv"):
            continue
        for card in col.get("cards", []):
            if is_decision_card(card):
                return card
    return None


# Stopword-Set analog dashboard/jobs/kanban_dedup.py (dort wöchentlich nachträglich;
# hier als Pre-Check VOR Kartenerstellung, damit Duplikate gar nicht erst entstehen).
_DEDUP_STOPWORDS = {
    "der", "die", "das", "und", "oder", "für", "fuer", "mit", "von", "ein", "eine",
    "einen", "einem", "des", "den", "dem", "im", "in", "auf", "zu", "zur", "zum",
    "bei", "als", "ist", "sind", "wird", "werden", "nicht", "auch", "aus", "nach",
    "wie", "was", "wann", "welche", "welcher", "welchen", "sollen", "soll", "wir",
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "how",
}


def _dedup_tokens(text: str) -> set[str]:
    """Text → normalisierte Token-Menge (lowercase, ohne Stopwörter/Kurzwörter)."""
    words = re.split(r"[^a-zA-Z0-9äöüÄÖÜéèêàâß]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _DEDUP_STOPWORDS}


def find_similar_decision_card(board: dict, question: str,
                               threshold: float = 0.85) -> tuple[dict, str] | None:
    """Sucht eine inhaltlich (nahezu) gleiche Entscheidungskarte auf dem Board —
    über ALLE Spalten inkl. done/archiv.

    Hintergrund (19.08.26): board_is_blocked() sieht done/archiv nicht. Sobald eine
    Entscheidungskarte beantwortet oder aussortiert war, galt das Board als frei und
    der nächste Lauf legte dieselbe Frage ERNEUT an (beobachtet: je 2 identische
    Karten 'Session-Persistenz gespraechsbegleiter' und 'git-author-Findings' auf
    home-stack-meta). Der wöchentliche kanban_dedup-Job räumt erst sonntags auf —
    bis dahin verbrennt jedes Duplikat Worker-Läufe und Tokens.

    Mass: Containment |Frage-Tokens ∩ Karten-Tokens| / |Frage-Tokens| statt
    symmetrischem Jaccard, weil die Karten-Description viel Boilerplate enthält
    (Optionen, Antwort-Anleitung), die den Jaccard-Wert verwässern würde.

    Return: (karte, spalten-kind) bei Treffer, sonst None.
    """
    q_tokens = _dedup_tokens(question)
    if not q_tokens:
        return None
    for col in board.get("columns", []):
        kind = _col_kind(col)
        for card in col.get("cards", []) or []:
            if not is_decision_card(card):
                continue
            # Frage steht am Anfang von title (question[:80]) und description —
            # 800 Zeichen reichen, ohne den Options-Boilerplate voll mitzuziehen.
            card_text = " ".join((
                str(card.get("title", "")),
                str(card.get("desc") or ""),
                str(card.get("description") or ""),
            ))[:800]
            c_tokens = _dedup_tokens(card_text)
            if not c_tokens:
                continue
            containment = len(q_tokens & c_tokens) / len(q_tokens)
            if containment >= threshold:
                logger.info("find_similar_decision_card: Frage '%s…' matcht Karte %s "
                            "('%s…', Spalte-kind=%s, containment=%.2f)",
                            question[:50], card.get("id"),
                            str(card.get("title", ""))[:50], kind, containment)
                return card, kind
    return None


def actionable_cards(board: dict) -> list[tuple[dict, dict]]:
    """Alle abarbeitbaren Karten in Prioritätsreihenfolge: zuerst laufende
    ('progress'), dann Backlog, dann Other. Überspringt Meta-, Dokument- und
    Entscheidungskarten. Basis für next_card UND die Gruppierung (grouping.py).

    'parked' fehlt in der Schleife bewusst — geparkte Karten (automat_cli park)
    warten auf etwas ausserhalb der Reichweite des Automaten und dürfen keinen
    Worker mehr auslösen, bis der Manager sie zurückschiebt. 'archiv' fehlt aus demselben
    Grund — abgelegte/verworfene Karten (z.B. Advisor-Spalte 'ki_archiv') sind keine
    offene Arbeit (sonst würden verworfene KI-Vorschläge entwickelt)."""
    out: list[tuple[dict, dict]] = []
    for kind in ("progress", "backlog", "other"):
        for col in board.get("columns", []):
            if _col_kind(col) != kind:
                continue
            for card in col.get("cards", []):
                if not card.get("id"):
                    # Ohne id kann der Worker die Karte nie via done/note melden
                    # (Endlos-Wiederholung) — überspringen, aber sichtbar loggen.
                    logger.warning("actionable_cards: Karte ohne id übersprungen: %r",
                                   str(card.get("title", ""))[:60])
                    continue
                if card.get("id") in SKIP_CARD_IDS:
                    continue
                if is_decision_card(card):
                    continue
                out.append((col, card))
    return out


PARK_COL_TITLE = "⏸️ Wartet (Automat blockiert)"


def park_card(slug: str, card_id: str, reason: str, until: str = "") -> bool:
    """Karte in die Warte-Spalte verschieben (legt sie bei Bedarf an) und Grund +
    Reaktivierungsbedingung an die Beschreibung hängen.

    Zwei Aufrufer: `automat_cli park` (Worker meldet selbst eine externe Blockade) und
    worker.reap() (Fail-Counter: Karte kam N-mal in Folge nicht voran). Rückgabe False,
    wenn die Karte nicht gefunden wurde."""
    board = get_board(slug)
    src = card = None
    for col in board.get("columns", []):
        for c in col.get("cards", []):
            if c.get("id") == card_id:
                src, card = col, c
                break
        if card:
            break
    if not card:
        logger.warning("park_card: %s/%s nicht gefunden", slug, card_id)
        return False
    target = None
    for col in board.get("columns", []):
        if _col_kind(col) == "parked":
            target = col
            break
    if target is None:
        target = {"id": f"parked_{int(time.time())}", "title": PARK_COL_TITLE, "cards": []}
        board.setdefault("columns", []).append(target)
        logger.info("park_card: Spalte '%s' in %s angelegt", PARK_COL_TITLE, slug)
    line = f"\n\n— 🤖 {now_iso()[:16]}: geparkt — {reason}"
    if until:
        line += f" Reaktivierung: {until}"
    card["description"] = (card.get("description") or "") + line
    if not _has_label(card, LABEL_AUTOMAT):
        card.setdefault("labels", []).append({"text": LABEL_AUTOMAT, "color": "#805ad5"})
    if src is not target:
        src["cards"] = [c for c in src["cards"] if c.get("id") != card_id]
        target.setdefault("cards", []).insert(0, card)
    board["columns"] = reorder_columns(board.get("columns", []))
    save_board(slug, board)
    logger.info("park_card: %s/%s -> '%s' (%s)", slug, card_id, target.get("title"), reason)
    return True


DISCARD_COL_TITLE = "🗄️ Archiv (Automat aussortiert)"


def discard_card(slug: str, card_id: str, reason: str) -> bool:
    """Karte aussortieren: in eine Archiv-Spalte verschieben (legt sie bei Bedarf an)
    und den Grund an die Beschreibung hängen.

    Braucht es für Manager-Entscheidungs-Antworten der Art 'gehört nicht zu diesem
    Projekt' / 'verwerfen': `done` wäre gelogen (nichts wurde umgesetzt), `park`
    falsch (die Karte wartet auf nichts). Archiv-Spalten sind für actionable_cards()
    und board_is_blocked() unsichtbar — die Karte bekommt nie wieder einen Worker.
    Vorfall 16.08.26 (dev-log): ohne diesen Pfad hat der Worker die beantwortete
    'gehört NICHT hierher'-Entscheidung ignoriert und stattdessen eine neue
    Entscheidungskarte (dec_27630d0f) erfunden."""
    board = get_board(slug)
    src = card = None
    for col in board.get("columns", []):
        for c in col.get("cards", []):
            if c.get("id") == card_id:
                src, card = col, c
                break
        if card:
            break
    if not card:
        logger.warning("discard_card: %s/%s nicht gefunden", slug, card_id)
        return False
    target = None
    for col in board.get("columns", []):
        if _col_kind(col) == "archiv":
            target = col
            break
    if target is None:
        target = {"id": f"archiv_{int(time.time())}", "title": DISCARD_COL_TITLE, "cards": []}
        board.setdefault("columns", []).append(target)
        logger.info("discard_card: Spalte '%s' in %s angelegt", DISCARD_COL_TITLE, slug)
    card["description"] = (card.get("description") or "") + \
        f"\n\n— 🤖 {now_iso()[:16]}: aussortiert — {reason}"
    if not _has_label(card, LABEL_AUTOMAT):
        card.setdefault("labels", []).append({"text": LABEL_AUTOMAT, "color": "#805ad5"})
    if src is not target:
        src["cards"] = [c for c in src["cards"] if c.get("id") != card_id]
        target.setdefault("cards", []).insert(0, card)
    board["columns"] = reorder_columns(board.get("columns", []))
    save_board(slug, board)
    logger.info("discard_card: %s/%s -> '%s' (%s)", slug, card_id, target.get("title"), reason)
    return True


def _card_priority_key(card: dict) -> tuple[int, str]:
    """Sortierschlüssel für eine Karte (für priority-aware next_card).

    Returns: (priority_order, title) wobei priority_order niedrig = wichtig.
    - user-gesetzte Priorität schlägt alles
    - sonst fallback auf einfache Heuristik
    """
    priority_order = {"hoch": 0, "mittel": 1, "niedrig": 2}
    user_prio = card.get("priority")
    if user_prio in priority_order:
        return (priority_order[user_prio], card.get("title", ""))

    # Fallback-Heuristik (keine Claude-Abfrage hier, nur local)
    title = (card.get("title") or "").lower()
    desc = (card.get("description") or "").lower()
    txt = title + " " + desc

    if any(w in txt for w in ["bug", "fehler", "fix", "crash", "down", "ausfall",
                               "sicherheit", "security", "dringend", "kritisch"]):
        return (0, card.get("title", ""))  # hoch
    if any(w in txt for w in ["idee", "später", "evtl", "nice", "optional", "kosmetik"]):
        return (2, card.get("title", ""))  # niedrig
    return (1, card.get("title", ""))  # mittel


def next_card(board: dict) -> tuple[dict, dict] | None:
    """Höchstpriore abzuarbeitende Karte. Rückgabe: (column, card) oder None.

    Seit 21.08.2026: sortiert nach echter Priorität statt Reihenfolge im JSON.
    Respektiert user-gesetzte `card.priority`, nutzt Heuristik als Fallback.
    """
    cands = actionable_cards(board)
    if not cands:
        return None
    # Sortiere nach Priorität (hoch zuerst)
    cands_sorted = sorted(cands, key=lambda x: _card_priority_key(x[1]))
    return cands_sorted[0]


# ── Worker-State ────────────────────────────────────────────────────────────
def _worker_path(slug: str) -> Path:
    safe = slug.replace("/", "_")
    return WORKERS_DIR / f"{safe}.json"


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # existiert, gehört nur jemand anderem


def list_workers() -> list[dict]:
    out = []
    for f in WORKERS_DIR.glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except Exception as e:
            logger.warning("Worker-State %s unlesbar: %s", f.name, e)
    return out


def live_workers() -> list[dict]:
    return [w for w in list_workers() if pid_alive(w.get("pid", 0))]


def write_worker(state: dict) -> None:
    p = _worker_path(state["board"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def clear_worker(slug: str) -> None:
    p = _worker_path(slug)
    if p.exists():
        p.unlink()


# ── Protokoll-Board `auto-entwicklung-log` ──────────────────────────────────
# Eine Karte pro Projekt (id autodev-<slug>, Board-Name im Titel). Spalte "working"
# = Automat arbeitet gerade daran (Worker-Start), Spalte "log" = weiterentwickelt
# (Worker-Ende / done). Neueste Karte immer oben in ihrer Spalte.
AUTODEV_BOARD = os.getenv("AUTOMAT_LOG_BOARD", "auto-entwicklung-log")
AUTODEV_COL_WORKING = "working"
AUTODEV_COL_LOG = "log"


def _autodev_col(board: dict, col_id: str) -> dict:
    for col in board.get("columns", []):
        if col.get("id") == col_id:
            return col
    logger.warning("autodev: Spalte '%s' fehlt in %s — nehme erste Spalte", col_id, AUTODEV_BOARD)
    return board.get("columns", [{}])[0]


def autodev_update(slug: str, line: str = "", move_to: str | None = None) -> None:
    """Best-effort-Eintrag ins Protokoll-Board — darf den Aufrufer NIE scheitern lassen.

    line: wird zeitgestempelt an die Karten-Beschreibung gehängt (leer = nur verschieben).
    move_to: Ziel-Spalten-id (AUTODEV_COL_WORKING/LOG); None = in aktueller Spalte lassen
             (bzw. neue Karten in die Log-Spalte). Die Karte rutscht immer an Position 0.
    """
    if not AUTODEV_BOARD or slug == AUTODEV_BOARD:
        # AUTOMAT_LOG_BOARD="" disables the protocol board (not shipped in the release)
        return  # Rekursionsschutz: das Protokoll-Board protokolliert sich nicht selbst
    try:
        board = get_board(AUTODEV_BOARD)
        card_id = f"autodev-{slug}"
        cur_col, card = None, None
        for col in board.get("columns", []):
            for c in col.get("cards", []):
                if c.get("id") == card_id:
                    cur_col, card = col, c
                    break
        if card is None:
            name = next((b.get("name") or slug for b in list_boards()
                         if b.get("id") == slug), slug)
            card = {"id": card_id,
                    "title": f"{name} — Board: {slug}",
                    "description": f"Automatisch weiterentwickelt vom Kanban-Automat (Board `{slug}`).",
                    "labels": [{"text": LABEL_AUTOMAT, "color": "#805ad5"}]}
            logger.info("autodev: neue Projekt-Karte %s im Board %s", card_id, AUTODEV_BOARD)
        if line:
            card["description"] = (card.get("description") or "") + f"\n\n— 🤖 {now_iso()[:16]}: {line}"
        target = _autodev_col(board, move_to) if move_to else (cur_col or _autodev_col(board, AUTODEV_COL_LOG))
        if cur_col is not None:
            cur_col["cards"] = [c for c in cur_col["cards"] if c.get("id") != card_id]
        target.setdefault("cards", []).insert(0, card)
        save_board(AUTODEV_BOARD, board)
        logger.info("autodev: %s -> Spalte '%s'%s", slug, target.get("id"),
                    f" ('{line[:60]}')" if line else "")
    except Exception as e:
        logger.warning("autodev-Protokoll fehlgeschlagen (%s): %s", slug, e)

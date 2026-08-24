"""
Kanban-Automat — zentrale Sicht auf offene Entscheidungen über ALLE Boards.

Der Automat (~/containers/kanban-automat) legt bei nötigen Entscheidungen Karten mit
dem Label 'Entscheidung' an und blockiert damit das Board. Damit man nicht jedes
Projekt einzeln öffnen muss, sammelt dieser Router alle offenen Entscheidungskarten
und erlaubt das Beantworten in einem Rutsch (Karte -> Erledigt + Wahl an die Karte).

Endpunkte:
  GET  /api/automat/decisions  -> {count, decisions:[{board,board_name,card_id,title,question,
                                  options,options_generic,column}]}  — Optionen kommen aus
                                  'description' ODER 'desc'; ohne Fund Standard-Antworten
                                  (options_generic=true), damit nie Knöpfe fehlen.
  POST /api/automat/decide     -> Antwort setzen (Body: {board, card_id, choice}); bei
                                  Spiegel-Karten wird die Quellkarte mitbeantwortet.
  GET  /api/automat/status     -> {auto_boards:[...], workers:[...]}  (Freigaben + laufende Worker)
  GET  /api/automat/limits     -> Drossel-Limits inkl. Grenzen/Erklärungen (GUI-Panel)
  PUT  /api/automat/limits     -> Limits speichern (Body: {max_starts_per_day: 72, ...})
  POST /api/automat/limits/reset -> zurück auf die Code-Defaults
"""
from __future__ import annotations

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services import automat_limits_service
from app.services.ttl_cache import TTLCache
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

router = APIRouter()
log = logging.getLogger("uvicorn.error")

_boards = BoardRepository()
_manifest = ManifestRepository()

# opt_decisions_lock_0810: list_decisions() iterierte früher über ALLE ~264 Boards
# mit je einem eigenen _boards.load() -> 264 exklusive boards/.lock-Zyklen pro Poll
# (gepollt alle 10-15s von automat.html/fragen.html/index.js/project-decisions.js
# + /api/fragen/count). Das serialisiert gegen JEDEN Board-Write im System. Jetzt:
# TTL-Cache mit Single-Flight (Double-Checked Locking, gleiches Muster wie
# github_status_service/cost_service/budget_service seit opt_cache_stampede_0806)
# + ein einziger Sammel-Read (BoardRepository.load_many) statt N Einzel-Loads.
_decisions_cache = TTLCache(ttl_seconds=12)


def invalidate_decisions_cache() -> None:
    """Erzwingt beim nächsten GET /api/automat/decisions einen frischen Read.

    Aufgerufen nach decide(), damit eine gerade beantwortete Entscheidung nicht
    bis zu 12 Sekunden weiter als offen angezeigt wird.
    """
    _decisions_cache.invalidate()

DECISION_LABEL = "Entscheidung"
DONE_HINTS = ("erledig", "done", "fertig", "abgeschlossen", "behoben", "fixed")
# Eine Wahl mit diesen Wörtern bedeutet "die Karte ist Rauschen/Müll -> weg":
# Karte wird als gelöscht markiert (deleted_at), sofort aus 'Offene Fragen'
# ausgeblendet und vom board_archiver-Purge nach einer Frist endgültig entfernt.
_DELETE_HINTS = ("löschen", "loeschen", "rauschen", "verwerfen")
# Optionen kommen je nach Erzeuger in DREI Formaten (bug_fixer nutzt '- ',
# Worker mal '1.' mal 'A:'). Frueher matchte nur '1.' -> Bug-Karten hatten
# keine Antwort-Buttons. Diese Zeile erkennt Aufzaehlung ('-'/'*'/'•'),
# Nummerierung ('1.'/'1)') und Buchstaben ('A:'/'A)'/'A.').
_OPT_LINE_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•]|[A-Za-z][.):])\s+(.*\S)\s*$")
_OPT_MARKER_RE = re.compile(r"optionen", re.I)
# Fallback (kein 'Optionen:'-Marker): nur nummerierte Zeilen global — altes
# Verhalten, damit bestehende Karten nicht regressieren.
_OPT_NUM_RE = re.compile(r"^\s*\d+\.\s+(.*\S)", re.M)
# Last resort: a decision card whose text lists no options at all would otherwise
# render without a single answer button (dead end for the user). These generic answers
# always work: 'löschen' hits _DELETE_HINTS, the others are plain choices.
_GENERIC_OPTIONS = [
    "Ja — umsetzen (Claude soll es machen)",
    "Nein — nicht umsetzen",
    "Rauschen → Karte löschen",
]


def _card_text(card: dict) -> str:
    """Full card body. Cards carry their text in EITHER 'description' (sync/KI cards)
    or 'desc' (GUI cards and every mirror card from mine_collector). Reading only
    'description' meant bug- and mirror decision cards parsed to zero options."""
    parts = []
    for key in ("description", "desc"):
        val = str(card.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    return "\n\n".join(parts)


def _extract_options(desc: str) -> list[str]:
    """Optionen aus der Karten-Beschreibung ziehen.

    Bevorzugt den Block direkt nach einer Zeile mit 'Optionen' (dort sammeln wir
    zusammenhaengende Aufzaehlungs-Zeilen, egal ob '-', '1.' oder 'A:'), sonst
    Fallback auf global nummerierte Zeilen.
    """
    lines = desc.splitlines()
    for i, line in enumerate(lines):
        if not _OPT_MARKER_RE.search(line):
            continue
        opts: list[str] = []
        for nxt in lines[i + 1:]:
            m = _OPT_LINE_RE.match(nxt)
            if m:
                opts.append(m.group(1).strip())
                continue
            if not nxt.strip():
                # Leerzeile: erst nach dem ersten Treffer beendet sie den Block,
                # davor (z.B. '**Optionen:**' gefolgt von Leerzeile) ueberspringen.
                if opts:
                    break
                continue
            # Nicht-Options-Text nach Beginn der Liste -> Block zu Ende.
            if opts:
                break
        if opts:
            log.debug("automat/decisions: %d Optionen via Marker geparst", len(opts))
            return opts
    return [m.strip() for m in _OPT_NUM_RE.findall(desc)]


def _is_delete_choice(choice: str) -> bool:
    """True, wenn die Wahl 'Karte ist Rauschen -> löschen' bedeutet."""
    c = choice.lower()
    return any(h in c for h in _DELETE_HINTS)


def _is_done_col(col: dict) -> bool:
    t = (str(col.get("title", "")) + " " + str(col.get("id", ""))).lower()
    return any(h in t for h in DONE_HINTS)


def _has_decision_label(card: dict) -> bool:
    """Entscheidungskarte robust erkennen — gleiche Heuristik wie
    automat_lib.is_decision_card: Label ist die Norm, aber Worker haben Karten
    auch ohne Label angelegt (id 'decision…' / 'ENTSCHEIDUNG' im Titel); die
    waren hier unsichtbar und die offene Entscheidung blieb unbemerkt."""
    for lb in card.get("labels", []) or []:
        if isinstance(lb, dict) and lb.get("text") == DECISION_LABEL:
            return True
    # 03.08.26: auch 'dec_…' (Präfix des Dashboard-Frontends). Diese Karten trugen weder
    # Label noch Titel-Marker → sie fehlten auf fragen.html/automat.html UND galten dem
    # Orchestrator als 'nicht blockiert'. Doppelter Schaden: die Frage blieb unbemerkt, und
    # der Automat verbrannte No-Op-Worker (chile-spanisch 202 Läufe / 0 fertig).
    # ⚠️ Diese Heuristik existiert zweimal — bei Änderung IMMER
    # automat_lib.is_decision_card() (~/containers/kanban-automat/) mitziehen.
    if str(card.get("id", "")).startswith(("decision", "dec_")):
        log.debug("automat/decisions: %s per id-Präfix erkannt (Label fehlt)", card.get("id"))
        return True
    # Bewusst case-sensitiv mit Doppelpunkt (Protokoll-Marker '… ENTSCHEIDUNG: …') —
    # sonst matchen normale Karten wie 'Kaufentscheidung dokumentieren'.
    if "ENTSCHEIDUNG:" in str(card.get("title", "")):
        log.debug("automat/decisions: %s per Titel-Marker erkannt (Label fehlt)", card.get("id"))
        return True
    return False


def _parse(card: dict) -> dict:
    """Frage + Optionen aus der vom Automaten erzeugten Beschreibung herauslesen."""
    desc = _card_text(card)
    options = _extract_options(desc)
    generic = not options
    if generic:
        options = list(_GENERIC_OPTIONS)
        log.debug("automat/decisions: %s ohne Optionen im Text -> Standard-Antworten", card.get("id"))
    # Frage = Titel ohne Emoji/Präfix
    title = card.get("title", "")
    question = re.sub(r"^[⚠️🟡\s]*ENTSCHEIDUNG:\s*", "", title).strip() or title
    return {"question": question, "options": options, "options_generic": generic}


def _compute_decisions() -> dict:
    """Frischer Scan über alle Boards — nimmt boards/.lock genau 2x (Manifest +
    ein Sammel-Read aller Board-Dateien), unabhängig von der Boardanzahl."""
    manifest = _manifest.load()
    slugs = [entry.get("id") for entry in manifest.get("boards", []) if entry.get("id")]
    boards_by_slug = _boards.load_many(slugs, inject_claude_md=False)

    out = []
    for entry in manifest.get("boards", []):
        slug = entry.get("id")
        if not slug:
            continue
        board = boards_by_slug.get(slug)
        if not board:
            continue
        for col in board.get("columns", []):
            if _is_done_col(col):
                continue
            for card in col.get("cards", []):
                if not _has_decision_label(card):
                    continue
                # Bereits beantwortet -> ausblenden: '✅ '-Titelpräfix (decide()
                # setzt es) oder als gelöscht markiert (deleted_at, wartet auf
                # den Purge) — auch wenn die Karte noch in keiner Done-Spalte liegt.
                if str(card.get("title", "")).startswith("✅"):
                    continue
                if card.get("deleted_at"):
                    continue
                parsed = _parse(card)
                out.append({
                    "board": slug,
                    "board_name": entry.get("name", slug),
                    "category": entry.get("category", ""),
                    "card_id": card.get("id"),
                    "title": card.get("title"),
                    "description": _card_text(card),
                    "column": col.get("title"),
                    "question": parsed["question"],
                    "options": parsed["options"],
                    "options_generic": parsed["options_generic"],
                })
    out.sort(key=lambda d: d["board_name"].lower())
    return {"count": len(out), "decisions": out}


@router.get("/api/automat/decisions")
def list_decisions():
    """Alle offenen Entscheidungskarten über sämtliche Boards.

    Cached für 12 Sekunden (Single-Flight, Double-Checked Locking via TTLCache) —
    wiederholte Polls innerhalb der TTL lösen 0 Board-Datei-Reads/-Locks aus.
    """
    return _decisions_cache.get(_compute_decisions)


def _append_body(card: dict, note: str) -> None:
    """Answer text into the field the card really renders ('desc' for GUI/mirror
    cards, 'description' for sync/KI cards). Writing only 'description' left the
    answer invisible on exactly those cards whose text lives in 'desc'."""
    keys = [k for k in ("description", "desc") if str(card.get(k) or "").strip()]
    if not keys:
        keys = ["desc"]
    for k in keys:
        card[k] = (card.get(k) or "") + note


def _mark_answered(card: dict, choice: str, is_delete: bool) -> None:
    """Stamp choice onto title + body and (for delete) set the purge marker.

    Already answered (✅/🗑️ prefix)? Then only the delete marker is (re)set —
    stamping title and body twice would just bloat the card. That case only
    happens on the source card of a mirror."""
    already = str(card.get("title", "")).startswith(("✅", "🗑️"))
    if is_delete:
        card["deleted_at"] = datetime.now().isoformat(timespec="seconds")
    if already:
        log.debug("automat/decide: %s war schon beantwortet, nur Löschmarke gesetzt (delete=%s)",
                  card.get("id"), is_delete)
        return
    if is_delete:
        _append_body(card, f"\n\n— 🗑️ Antwort: {choice} · als Rauschen gelöscht (wird später endgültig entfernt)")
        card["title"] = f"🗑️ {choice[:60]} — {card.get('title', '')}"[:160]
    else:
        _append_body(card, f"\n\n— ✅ Antwort: {choice}")
        card["title"] = f"✅ {choice[:70]} — {card.get('title', '')}"[:160]


def _answer_source_card(src_board: str, src_card: str, choice: str, is_delete: bool) -> bool:
    """Same answer onto the ORIGINAL card of a mirror (mine_collector copies
    owner-me cards into 'meine-aufgaben*'). Without this the source board stays
    blocked and the next mirror run overwrites title/desc from the source again —
    the answer would simply vanish. Best effort: never fails the request."""
    moved = {"ok": False}

    def mutate(board: dict):
        found = None
        for col in board.get("columns", []):
            for c in list(col.get("cards", [])):
                if c.get("id") == src_card:
                    found = c
                    col["cards"].remove(c)
                    break
            if found:
                break
        if not found:
            log.warning("automat/decide: Quellkarte %s/%s nicht gefunden", src_board, src_card)
            return board
        _mark_answered(found, choice, is_delete)
        done_col = next((c for c in board.get("columns", []) if _is_done_col(c)), None)
        if done_col is None:
            done_col = board.get("columns", [{}])[-1]
        done_col.setdefault("cards", []).insert(0, found)
        moved["ok"] = True
        return board

    try:
        _boards.update(src_board, mutate)
    except Exception as e:
        log.warning("automat/decide: Quellboard %s nicht aktualisierbar: %s", src_board, e)
        return False
    log.info("automat/decide: Quellkarte %s/%s mitbeantwortet: %s", src_board, src_card, moved["ok"])
    return moved["ok"]


@router.post("/api/automat/decide")
def decide(body: dict):
    """Entscheidung beantworten: Karte mit der Wahl markieren und nach 'Erledigt'
    verschieben -> Board ist entsperrt, der nächste Automat-Lauf setzt die Antwort um."""
    slug = (body.get("board") or "").strip()
    card_id = (body.get("card_id") or "").strip()
    choice = (body.get("choice") or "").strip()
    if not (slug and card_id and choice):
        raise HTTPException(status_code=400, detail="board, card_id und choice nötig")

    # Löschen entweder explizit vom Frontend (delete=true) oder aus der Wahl
    # abgeleitet ('… löschen'/'Rauschen …'). Gelöschte Karten werden nur markiert
    # (deleted_at) — der board_archiver-Purge entfernt sie nach einer Frist endgültig
    # (Sicherheitsfenster gegen Fehlklicks).
    is_delete = bool(body.get("delete")) or _is_delete_choice(choice)
    result = {"moved": False, "deleted": is_delete, "source": None}

    def mutate(board: dict):
        # Karte finden + aus ihrer Spalte lösen
        found = None
        for col in board.get("columns", []):
            for c in list(col.get("cards", [])):
                if c.get("id") == card_id:
                    found = c
                    col["cards"].remove(c)
                    break
            if found:
                break
        if not found:
            raise HTTPException(status_code=404, detail=f"Karte {card_id} nicht in {slug}")
        # Wahl sichtbar an die Karte schreiben
        _mark_answered(found, choice, is_delete)
        # Mirror card? Remember the origin, answer it after this update (the repo
        # lock is not reentrant, so no nested update here).
        if found.get("mirror_source_board") and found.get("mirror_source_card"):
            result["source"] = (found["mirror_source_board"], found["mirror_source_card"])
        # in die Erledigt-Spalte legen (sonst letzte Spalte)
        done_col = next((c for c in board.get("columns", []) if _is_done_col(c)), None)
        if done_col is None:
            done_col = board.get("columns", [{}])[-1]
        done_col.setdefault("cards", []).insert(0, found)
        result["moved"] = True
        return board

    _boards.update(slug, mutate)
    log.info("automat/decide: %s/%s beantwortet: %s (delete=%s)", slug, card_id, choice, is_delete)

    source_answered = False
    if result["source"]:
        src_board, src_card = result["source"]
        if src_board != slug:
            source_answered = _answer_source_card(src_board, src_card, choice, is_delete)

    invalidate_decisions_cache()
    return {"status": "ok", "board": slug, "card_id": card_id, "choice": choice,
            "deleted": is_delete, "source_answered": source_answered}


@router.get("/api/automat/status")
def status():
    """Freigegebene Boards + aktuell laufende Automat-Worker (aus dem State-Ordner)."""
    manifest = _manifest.load()
    auto = [{"id": b.get("id"), "name": b.get("name", b.get("id"))}
            for b in manifest.get("boards", []) if b.get("auto") is True]
    workers = []
    automat_state_dir = Path(os.getenv("AUTOMAT_STATE_DIR", "/opt/ili-automat/state"))
    wdir = automat_state_dir / "workers"
    if wdir.is_dir():
        for f in wdir.glob("*.json"):
            try:
                w = json.loads(f.read_text())
                pid = w.get("pid", 0)
                alive = False
                try:
                    import os
                    os.kill(pid, 0)
                    alive = True
                except Exception:
                    alive = False
                if alive:
                    workers.append({"board": w.get("board"), "card_title": w.get("card_title"),
                                    "started_at": w.get("started_at")})
            except Exception as e:
                # Stilles Überspringen liess kaputte Worker-Einträge unbemerkt aus dem
                # Automat-Status verschwinden — sichtbar machen statt verschlucken.
                log.warning("automat/status: Worker-Datei %s unlesbar/kaputt: %s", f, e)
                continue
    return {"auto_boards": auto, "workers": workers}


# ── Drossel-Limits (GUI-Panel „⚙️ Drossel" in automat.html) ──────────────────
@router.get("/api/automat/limits")
def get_limits():
    """Aktuelle Drossel-Werte + zulässige Bereiche + Erklärung je Stellschraube."""
    try:
        return automat_limits_service.get_limits()
    except automat_limits_service.AutomatUnavailable as e:
        log.error("automat/limits: %s", e)
        raise HTTPException(status_code=503, detail=f"{e}")


@router.put("/api/automat/limits")
def put_limits(body: dict):
    """Limits speichern. Werte werden geklemmt; greift beim nächsten Tick (max. 5 min)."""
    try:
        res = automat_limits_service.save_limits(body or {})
        log.info("automat/limits gespeichert: %s", res.get("changed"))
        return res
    except automat_limits_service.AutomatUnavailable as e:
        raise HTTPException(status_code=503, detail=f"{e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")


@router.post("/api/automat/limits/reset")
def reset_limits():
    """Alle Limits auf die Code-Defaults zurücksetzen."""
    try:
        return automat_limits_service.reset_limits()
    except automat_limits_service.AutomatUnavailable as e:
        raise HTTPException(status_code=503, detail=f"{e}")

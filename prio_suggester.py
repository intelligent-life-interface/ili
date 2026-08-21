"""KI-Prioritäten-Vorschlag für die Karten eines Boards (read-only, Claude-Abo Bridge 8950).

Kernregel: **vom User gesetzte Prioritäten (`card.priority`) werden NIE an die KI gegeben
und NIE verändert.** Die KI stuft ausschliesslich Karten OHNE gesetzte Priorität ein.
Es wird nichts ins Board zurückgeschrieben — reiner Anzeige-Vorschlag fürs Prio-Widget.

Ablauf (token-sparend, vgl. dedup_finder):
  1. Offene Karten einsammeln (gleiche Filterregeln wie das Frontend-Widget).
  2. Karten mit gesetzter Priorität  -> source="user", unverändert.
  3. Karten ohne Priorität          -> EIN gebündelter Claude-Abo-Call (nur Titel) -> "hoch/mittel/niedrig".
                                       Was Claude nicht/ungültig liefert -> lokale Schlagwort-Heuristik (source="heuristik").
  4. Liste nach Priorität sortiert zurück (hoch->mittel->niedrig, laufende Spalten zuerst).

Wiederverwendet: project_creator._claude_abo_text (Claude-Abo Bridge 8950),
app.storage.board_repository.BoardRepository.
"""
from __future__ import annotations

import json
import logging
import re

from app.storage.board_repository import BoardRepository
from project_creator import _claude_abo_text

# System-Prompt für die strikt-JSON-Klassifikation übers Claude-Abo.
_SYS_JSON = ("Du bist ein präziser Projektplaner. Antworte AUSSCHLIESSLICH im geforderten "
             "JSON-Format, ohne Fliesstext, ohne Code-Fences, ohne Erklärung.")

log = logging.getLogger("dashboard.prio_suggester")

VALID_PRIOS = {"hoch", "mittel", "niedrig"}
PRIO_ORDER = {"hoch": 0, "mittel": 1, "niedrig": 2}
SKIP_CARD_IDS = {"claudemd-description"}
MAX_AI_CARDS = 40  # mehr Titel gehen nicht an Ollama (Rest -> Heuristik), hält den Call klein

# Schlagwort-Heuristik (identisch zum Frontend project-prio-widget.js)
_RE_HIGH = re.compile(r"\b(bug|fehler|fix|dringend|wichtig|sofort|kritisch|asap|deadline|frist|crash|down|ausfall|sicherheit|security|blocker)\b", re.I)
_RE_LOW = re.compile(r"\b(idee|sp(ä|ae)ter|evtl|eventuell|vielleicht|nice|optional|irgendwann|kosmetik|refactor|aufr(ä|ae)umen|cleanup|doku)\b", re.I)


def _col_is_skipped(col_id: str, title: str) -> bool:
    """navigation/ki_archiv-Spalten und erledigte Spalten ausblenden (id ODER Titel)."""
    if re.search(r"navigation|ki_archiv", col_id):
        return True
    if re.search(r"done", col_id) or re.search(r"erledig|fertig|abgeschlossen|done|archiv", title):
        return True
    return False


def _col_rank(col_id: str, title: str) -> int:
    s = col_id + " " + title
    if re.search(r"inprogress|in.?progress|bearbeitung|laufend", s):
        return 0
    if re.search(r"review|pr(ü|ue)f", s):
        return 1
    if re.search(r"backlog|offen|todo|ideen", s):
        return 2
    return 3


def _heuristic(title: str, desc: str) -> str:
    txt = (title or "") + " " + (desc or "")
    if _RE_HIGH.search(txt):
        return "hoch"
    if _RE_LOW.search(txt):
        return "niedrig"
    return "mittel"


def _collect_open(board: dict) -> list[dict]:
    """Offene Karten mit Spalteninfo: [{title, desc, column, col_rank, user_prio}]."""
    out = []
    for col in board.get("columns", []):
        cid = (col.get("id") or "").lower()
        ctitle = (col.get("title") or "").lower()
        if _col_is_skipped(cid, ctitle):
            continue
        for c in col.get("cards", []):
            if c.get("id") in SKIP_CARD_IDS:
                continue
            user_prio = c.get("priority")
            out.append({
                "title": c.get("title") or "(ohne Titel)",
                "desc": c.get("description") or c.get("desc") or "",
                "column": col.get("title") or col.get("id") or "",
                "col_rank": _col_rank(cid, ctitle),
                "user_prio": user_prio if user_prio in VALID_PRIOS else None,
                "effort": c.get("effort"),
            })
    return out


def _ai_rank(cards: list[dict]) -> dict[int, str]:
    """Ollama stuft die übergebenen Karten ein. Returns {index: prio}. Leer bei Ausfall.

    Nur Titel gehen raus (token-sparend). `cards` enthält NUR Karten ohne user_prio.
    """
    if not cards:
        return {}
    lines = [f"- nr={i} | {c['title']}" for i, c in enumerate(cards)]
    prompt = (
        "Du priorisierst Aufgaben eines Projekts nach Dringlichkeit UND Wichtigkeit.\n"
        "Stufe JEDE Aufgabe als \"hoch\", \"mittel\" oder \"niedrig\" ein:\n"
        "- hoch: dringend & wichtig, blockiert anderes, Fehler/Sicherheit/Frist.\n"
        "- mittel: normale Aufgabe, sollte erledigt werden.\n"
        "- niedrig: nice-to-have, Idee, Aufräumen, kann warten.\n\n"
        "Aufgaben:\n" + "\n".join(lines) +
        "\n\nAntworte AUSSCHLIESSLICH als JSON-Array, eine Zeile pro Aufgabe:\n"
        '[{"nr": 0, "prio": "hoch"}]'
    )
    raw = _claude_abo_text(_SYS_JSON, prompt, max_tokens=min(60 + len(cards) * 20, 1024),
                           temperature=0.1, timeout=120)
    if not raw:
        log.debug("Claude-Abo lieferte keine Prio-Antwort -> Heuristik-Fallback")
        return {}
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        arr = json.loads(raw[start:end + 1])
    except Exception as e:
        log.debug("Ollama-Prio-JSON nicht parsebar (%s): %r", e, raw[:160])
        return {}
    out: dict[int, str] = {}
    for item in arr:
        if isinstance(item, str):  # manche Modelle kodieren doppelt als String
            try:
                item = json.loads(item)
            except Exception:
                continue
        if not isinstance(item, dict):
            continue
        try:
            nr = int(item.get("nr"))
        except (TypeError, ValueError):
            continue
        prio = str(item.get("prio") or "").strip().lower()
        if 0 <= nr < len(cards) and prio in VALID_PRIOS:
            out[nr] = prio
    return out


def suggest_priorities(board_id: str, use_ai: bool = True) -> dict:
    """Liefert die offenen Karten des Boards mit (KI-)Prioritäten, sortiert.

    Returns: {board_id, count, ai, cards:[{title, column, priority, source, effort}]}
             source ∈ "user" (gesetzt, unangetastet) | "ki" | "heuristik".
    """
    board = BoardRepository().load(board_id, inject_claude_md=False)
    if not board:
        log.warning("Prio: Board %r nicht gefunden", board_id)
        return {"board_id": board_id, "count": 0, "ai": False, "cards": [], "note": "Board nicht gefunden"}

    cards = _collect_open(board)
    # Karten ohne user-Priorität für die KI/Heuristik isolieren (mit Rückbezug per Index).
    need = [(idx, c) for idx, c in enumerate(cards) if c["user_prio"] is None]
    ai_map: dict[int, str] = {}
    if use_ai and need:
        ai_input = [c for _, c in need][:MAX_AI_CARDS]
        ranked = _ai_rank(ai_input)
        # ranked-Index bezieht sich auf ai_input -> zurück auf cards-Index mappen
        for ai_idx, prio in ranked.items():
            orig_idx = need[ai_idx][0]
            ai_map[orig_idx] = prio
    log.info("Prio board=%s: %d offen, %d ohne Prio, %d von KI eingestuft (use_ai=%s)",
             board_id, len(cards), len(need), len(ai_map), use_ai)

    result = []
    for idx, c in enumerate(cards):
        if c["user_prio"]:
            prio, source = c["user_prio"], "user"   # NIE überschreiben
        elif idx in ai_map:
            prio, source = ai_map[idx], "ki"
        else:
            prio, source = _heuristic(c["title"], c["desc"]), "heuristik"
        result.append({
            "title": c["title"], "column": c["column"],
            "priority": prio, "source": source, "effort": c["effort"],
            "_o": PRIO_ORDER[prio], "_c": c["col_rank"],
        })

    result.sort(key=lambda x: (x["_o"], x["_c"]))
    for r in result:
        r.pop("_o", None)
        r.pop("_c", None)
    return {"board_id": board_id, "count": len(result), "ai": bool(use_ai and ai_map), "cards": result}


# ── Eisenhower-Quadrant für PROJEKTE (Übersicht) ───────────────────────────────
VALID_QUADRANTS = {"q1", "q2", "q3", "q4"}
MAX_AI_PROJECTS = 60


def suggest_eisenhower(items: list[dict], use_ai: bool = True) -> dict:
    """Schätzt für eine Liste Projekte (nur die ohne Quadrant) den Eisenhower-Quadranten.

    `items`: [{id, name, category?, desc?}] — der Aufrufer (Frontend) übergibt NUR Projekte
    OHNE gesetzten `eisenhower`-Wert; vom User einsortierte gehen gar nicht erst rein.
    Schreibt NICHTS — liefert nur Vorschläge; das Frontend setzt sie via PATCH und überspringt
    dabei alles, was inzwischen doch einen Quadranten hat (nie überschreiben).

    Returns: {count, ai, suggestions:[{id, quadrant}]}  (quadrant ∈ q1..q4).
    """
    items = [it for it in (items or []) if it.get("id")]
    if not items:
        return {"count": 0, "ai": False, "suggestions": []}

    use = items[:MAX_AI_PROJECTS]
    suggestions: list[dict] = []
    if use_ai:
        lines = []
        for i, it in enumerate(use):
            cat = (it.get("category") or "").strip()
            desc = (it.get("desc") or "").strip().replace("\n", " ")[:140]
            label = it.get("name") or it.get("id")
            extra = (f" [Kategorie: {cat}]" if cat else "") + (f" — {desc}" if desc else "")
            lines.append(f"- nr={i} | {label}{extra}")
        prompt = (
            "Du ordnest Projekte nach der EISENHOWER-Matrix ein (Dringlichkeit & Wichtigkeit).\n"
            "Weise JEDEM Projekt genau einen Quadranten zu:\n"
            "- q1: dringend UND wichtig (sofort).\n"
            "- q2: dringend ODER wichtig (bald einplanen).\n"
            "- q3: unwichtig & nicht dringend (kann warten).\n"
            "- q4: nicht umsetzen / vergessen.\n\n"
            "Projekte:\n" + "\n".join(lines) +
            "\n\nAntworte AUSSCHLIESSLICH als JSON-Array, ein Objekt pro Projekt:\n"
            '[{"nr": 0, "q": "q1"}]'
        )
        raw = _claude_abo_text(_SYS_JSON, prompt, max_tokens=min(60 + len(use) * 18, 1100),
                               temperature=0.1, timeout=150)
        ai_map = _parse_nr_map(raw, len(use), "q", VALID_QUADRANTS)
        for i, it in enumerate(use):
            if i in ai_map:
                suggestions.append({"id": it["id"], "quadrant": ai_map[i]})
    log.info("Eisenhower-Vorschlag: %d Projekte rein, %d eingestuft (use_ai=%s)",
             len(use), len(suggestions), use_ai)
    return {"count": len(suggestions), "ai": bool(use_ai and suggestions), "suggestions": suggestions}


def _parse_nr_map(raw: str, n: int, value_key: str, valid: set[str]) -> dict[int, str]:
    """Parst Ollama-JSON `[{"nr":int, "<value_key>":str}]` -> {nr: value}. Robust/leer bei Fehler."""
    if not raw:
        return {}
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        arr = json.loads(raw[start:end + 1])
    except Exception as e:
        log.debug("nr-map JSON nicht parsebar (%s): %r", e, raw[:160])
        return {}
    out: dict[int, str] = {}
    for item in arr:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except Exception:
                continue
        if not isinstance(item, dict):
            continue
        try:
            nr = int(item.get("nr"))
        except (TypeError, ValueError):
            continue
        val = str(item.get(value_key) or "").strip().lower()
        if 0 <= nr < n and val in valid:
            out[nr] = val
    return out

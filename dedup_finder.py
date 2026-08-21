#!/usr/bin/env python3
"""dedup_finder.py — Duplikat-Prüfung für neue Wunsch-/Aufgabenkarten eines Boards.

Ziel (Token-sparend): verhindern, dass dieselbe Aufgabe doppelt angelegt und dann
womöglich zweimal (teuer) von Claude abgearbeitet wird. Statt vorab das ganze Board an
eine KI zu schicken, läuft ein zweistufiger, billiger Check:

  1. **Jaccard-Vorfilter (lokal, instant, gratis):** Wort-Mengen-Ähnlichkeit zwischen dem
     neuen Titel(+Beschreibung) und jeder OFFENEN Karte des Boards. Erledigte Spalten und
     die Meta-Karte `claudemd-description` werden übersprungen. Sind keine ähnlichen Karten
     da (Normalfall), endet der Check sofort — **kein** KI-Aufruf.
  2. **Claude-Bestätigung (nur bei Verdacht, nur Titel):** Gibt es ähnliche Kandidaten,
     entscheidet Claude (Abo-Bridge 8950), welche davon WIRKLICH dieselbe Aufgabe sind
     (semantisch), und liefert je einen kurzen Grund. An die KI gehen NUR die Kartentitel,
     nie Board-Inhalt.

Öffentliche Schnittstelle:
  check_duplicate(board_id, title, desc="", use_ai=True) -> dict
    -> {"board_id", "query", "duplicates": [{id,title,column,score,reason}], "note"?}

Debug-Logs über den Logger "dashboard.dedup".
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.storage.board_repository import BoardRepository
from project_creator import _claude_abo_text

# System-Prompt für die strikt-JSON-Duplikatprüfung übers Claude-Abo (Bridge 8950).
_SYS_DEDUP = ("Du bist ein präziser Projekt-Assistent. Antworte AUSSCHLIESSLICH als JSON-Array, "
              "ohne Fliesstext, ohne Code-Fences, ohne Erklärung.")

log = logging.getLogger("dashboard.dedup")

# Spalten, die als "erledigt" gelten und beim Dedup-Check ignoriert werden.
DONE_TITLES = {"erledigt", "done", "fertig", "abgeschlossen", "archiv", "archiviert"}
# Meta-Karten, die keine echten Aufgaben sind.
SKIP_CARD_IDS = {"claudemd-description"}

# Vorfilter-Schwellen: ein Kandidat ist "verdächtig", wenn die Jaccard-Ähnlichkeit
# hoch genug ist ODER genügend bedeutungstragende Wörter geteilt werden.
PREFILTER_JACCARD = 0.18
PREFILTER_SHARED = 2
MAX_CANDIDATES = 8          # an Ollama gehen höchstens so viele Titel
# Ohne KI gilt erst ab dieser Ähnlichkeit als wahrscheinliches Duplikat.
AI_OFF_THRESHOLD = 0.45

# Kurze/inhaltsleere Wörter, die die Ähnlichkeit verzerren.
_STOP = {
    "und", "oder", "der", "die", "das", "den", "dem", "ein", "eine", "einen", "einem",
    "fuer", "für", "mit", "von", "auf", "aus", "ist", "im", "in", "an", "am", "zu", "zum",
    "zur", "auch", "nicht", "neu", "neue", "neuer", "neues", "the", "and", "for", "with",
    "wunsch", "aufgabe", "karte", "todo", "task", "soll", "sollte", "machen", "bitte",
}


def _tokens(text: str) -> set[str]:
    """Bedeutungstragende Wörter (kleingeschrieben, >=3 Zeichen, ohne Stoppwörter)."""
    toks = re.findall(r"[a-zäöüß0-9]+", (text or "").lower())
    return {t for t in toks if len(t) >= 3 and t not in _STOP}


def _open_cards(board: dict) -> list[dict]:
    """Alle offenen, echten Karten eines Boards mit ihrer Spalte: [{id,title,desc,column}]."""
    out = []
    for col in board.get("columns", []):
        if (col.get("title", "").strip().lower()) in DONE_TITLES:
            continue
        for c in col.get("cards", []):
            if c.get("id") in SKIP_CARD_IDS:
                continue
            out.append({
                "id": c.get("id") or "",
                "title": c.get("title") or "",
                "desc": c.get("desc") or "",
                "column": col.get("title", ""),
            })
    return out


def _prefilter(query_tokens: set[str], cards: list[dict]) -> list[dict]:
    """Lokaler Jaccard-Vorfilter -> verdächtige Kandidaten, absteigend nach Score."""
    cands = []
    for card in cards:
        ctok = _tokens(card["title"] + " " + card["desc"])
        if not ctok:
            continue
        inter = query_tokens & ctok
        if not inter:
            continue
        union = query_tokens | ctok
        score = round(len(inter) / len(union), 3) if union else 0.0
        if score >= PREFILTER_JACCARD or len(inter) >= PREFILTER_SHARED:
            cands.append({**card, "score": score, "shared": sorted(inter)})
    cands.sort(key=lambda x: (-x["score"], -len(x["shared"])))
    return cands[:MAX_CANDIDATES]


def _ai_confirm(query: str, candidates: list[dict]) -> dict:
    """Ollama entscheidet, welche Kandidaten DIESELBE Aufgabe sind (nur Titel).

    Returns: {card_id: reason}. Bei Ollama-Ausfall/Parsing-Fehler -> {} (Fallback greift).
    """
    lines = [f"- id={c['id'] or '(ohne-id)'} | {c['title']}" for c in candidates]
    prompt = (
        "Du prüfst, ob eine NEUE Aufgabe inhaltlich bereits als Karte existiert (Duplikat), "
        "damit nichts doppelt bearbeitet wird.\n\n"
        f"NEUE Aufgabe:\n{query}\n\n"
        "Vorhandene Karten:\n" + "\n".join(lines) +
        "\n\nWelche vorhandenen Karten beschreiben DASSELBE Anliegen wie die neue Aufgabe? "
        "Nur echte inhaltliche Dubletten, keine bloss thematisch ähnlichen. "
        "Antworte AUSSCHLIESSLICH als JSON-Array (leer [] wenn keine):\n"
        '[{"id": "<id>", "reason": "<kurzer Grund>"}]'
    )
    raw = _claude_abo_text(_SYS_DEDUP, prompt, max_tokens=300, temperature=0.1, timeout=90)
    if not raw:
        log.debug("Claude-Abo lieferte keine Antwort -> Fallback auf Jaccard")
        return {}
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        arr = json.loads(raw[start:end + 1])
    except Exception as e:
        log.debug("Ollama-JSON nicht parsebar (%s): %r", e, raw[:120])
        return {}
    out = {}
    for item in arr:
        # Manche Modelle kodieren das Objekt doppelt als String -> nachparsen.
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except Exception:
                continue
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = str(item.get("reason") or "Inhaltlich dieselbe Aufgabe").strip()
    return out


def check_duplicate(board_id: str, title: str, desc: str = "", use_ai: bool = True) -> dict:
    """Prüft, ob eine neue Karte (title/desc) eine offene Karte des Boards dupliziert.

    Zweistufig: Jaccard-Vorfilter (gratis) -> bei Verdacht Ollama-Bestätigung (nur Titel).
    """
    title = (title or "").strip()
    if not title:
        return {"board_id": board_id, "query": "", "duplicates": [], "note": "kein Titel"}

    board = BoardRepository().load(board_id, inject_claude_md=False)
    if not board:
        log.warning("Dedup: Board %r nicht gefunden", board_id)
        return {"board_id": board_id, "query": title, "duplicates": [], "note": "Board nicht gefunden"}

    qtok = _tokens(title + " " + desc)
    cards = _open_cards(board)
    cands = _prefilter(qtok, cards)
    log.info("Dedup board=%s neu=%r -> %d/%d Kandidaten (Vorfilter)",
             board_id, title[:60], len(cands), len(cards))

    if not cands:
        return {"board_id": board_id, "query": title, "duplicates": []}

    confirmed = _ai_confirm(title + ("\n" + desc if desc else ""), cands) if use_ai else {}

    dups = []
    for c in cands:
        cid = c["id"]
        if use_ai:
            # Mit KI: nur was Ollama bestätigt hat (id muss matchen).
            if cid and cid in confirmed:
                dups.append({**_pub(c), "reason": confirmed[cid]})
        else:
            # Ohne KI: ab hoher Jaccard-Ähnlichkeit als wahrscheinliches Duplikat.
            if c["score"] >= AI_OFF_THRESHOLD:
                dups.append({**_pub(c), "reason": "Gemeinsame Begriffe: " + ", ".join(c["shared"])})

    log.info("Dedup board=%s -> %d Duplikat(e) bestätigt (use_ai=%s)", board_id, len(dups), use_ai)
    return {"board_id": board_id, "query": title, "duplicates": dups}


def _pub(c: dict) -> dict:
    """Karte auf die öffentlichen Felder reduzieren."""
    return {"id": c["id"], "title": c["title"], "column": c["column"], "score": c["score"]}

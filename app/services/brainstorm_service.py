"""Brainstorming-Modus — Logik (HTTP-frei, wird von app/api/brainstorm.py genutzt).

Vier Bausteine, alle über das Claude-Abo (CLI-Bridge :8950, KEIN API-Guthaben):

1. stream_brainstorm()  – Multi-Turn-Dialog TOKEN-WEISE (Bridge /stream, NDJSON).
2. History             – serverseitig je Projekt (boards/brainstorm/<id>.json),
                          geräteübergreifend statt localStorage.
3. idea_to_card()      – eine Brainstorm-Aussage → EINE Kanban-Karte im Projekt-Board.
4. idea_to_subproject()– eine ausgereifte Idee → Unterprojekt (reuse create_board).

Debug-Logs sind bewusst gesprächig (Home-Konvention): jeder Schritt loggt Modell,
Zeichenzahl und Ergebnis, damit Fehler im Nachhinein nachvollziehbar sind.
"""
import json
import logging
import re
from pathlib import Path

import anyio

from constants import BOARDS_DIR, PRIORITY_COLORS
from app.services import claude_client
from app.storage.atomic_write import write_json_atomic
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.brainstorm")

# Brainstorm-Verlauf pro Projekt: eine JSON-Datei je Board unter boards/brainstorm/.
_HISTORY_DIR = Path(BOARDS_DIR) / "brainstorm"
_boards = BoardRepository()
_manifest = ManifestRepository()

# Default-Modell fürs Brainstorming (kreatives Ausarbeiten → Sonnet reicht, schnell).
BRAINSTORM_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "Du bist ein kreativer Brainstorming-Partner für ein privates Homeserver-Projekt. "
    "Höre aktiv zu, stelle gezielte Rückfragen, bring eigene Ideen ein und hilf, Gedanken "
    "zu schärfen und weiterzuentwickeln. Sei prägnant statt ausschweifend, biete konkrete "
    "Alternativen an und nutze Emojis sparsam. Antworte auf Deutsch.\n"
    "WICHTIG (Anti-Fantasie): Stütze dich auf das, was der Nutzer wirklich sagt. Ist eine "
    "Idee noch dünn, frag lieber nach, statt Details zu erfinden."
)

# Rollen aus dem Frontend → Bridge/Claude-Rollen.
_ROLE_MAP = {"user": "user", "ai": "assistant", "assistant": "assistant"}


# ── Projekt-Kontext (damit der Brainstorm das Board von Anfang an KENNT) ──────
def _project_context(project_id: str) -> str:
    """Kompakter Kontext-Block über das aktuelle Projekt für den System-Prompt.

    Enthält Name, Beschreibung, Tags (aus dem Manifest) und die aktuellen Karten
    je Spalte (aus dem Board-JSON). So weiss die KI beim Öffnen sofort, um welches
    Projekt es geht, ohne dass der Nutzer es erklären muss. Leerer String, wenn zum
    Projekt nichts gefunden wird (dann bleibt der generische Prompt).
    """
    if not project_id:
        return ""
    lines: list[str] = []
    # 1) Manifest-Stammdaten: Name, Beschreibung, Tags.
    try:
        boards = _manifest.load().get("boards", [])
        entry = next((b for b in boards if b.get("id") == project_id), None)
        if entry:
            name = entry.get("name") or project_id
            lines.append(f"Projekt: {name}")
            desc = " ".join((entry.get("description") or "").split())[:600]
            if desc:
                lines.append(f"Beschreibung: {desc}")
            tags = ", ".join(entry.get("tags") or [])
            if tags:
                lines.append(f"Tags: {tags}")
        else:
            lines.append(f"Projekt-ID: {project_id}")
            log.debug("[brainstorm] Kontext: %r nicht im Manifest", project_id)
    except Exception as exc:
        log.warning("[brainstorm] Kontext-Manifest für %r nicht lesbar: %s", project_id, exc)

    # 2) Board-Karten je Spalte (nur Titel, kompakt — max. 8 Karten/Spalte).
    try:
        board = _boards.load(project_id, inject_claude_md=False)
        if board:
            for col in board.get("columns", []):
                cards = col.get("cards", []) or []
                if not cards:
                    continue
                titles = []
                for c in cards[:8]:
                    t = (c.get("title") or "").strip()
                    if t:
                        titles.append(t)
                more = f" (+{len(cards) - 8} weitere)" if len(cards) > 8 else ""
                if titles:
                    col_name = col.get("title") or col.get("id") or "Spalte"
                    lines.append(f"Spalte {col_name}: " + "; ".join(titles) + more)
    except Exception as exc:
        log.warning("[brainstorm] Kontext-Board für %r nicht lesbar: %s", project_id, exc)

    if not lines:
        return ""
    return (
        "\n\nKONTEXT — du befindest dich im Brainstorming zu genau diesem Projekt. "
        "Du kennst es also bereits; frag NICHT, um welche Idee es geht, sondern beziehe "
        "dich direkt auf den Stand:\n" + "\n".join(lines)
    )


# ── History (serverseitig, geräteübergreifend) ───────────────────────────────
def _history_path(project_id: str) -> Path:
    # Nur harmlose Zeichen im Dateinamen zulassen (Board-IDs können Umlaute haben).
    safe = re.sub(r"[^\w.\-äöüÄÖÜ]", "_", project_id or "unknown")
    return _HISTORY_DIR / f"{safe}.json"


def load_history(project_id: str) -> list:
    """Brainstorm-Verlauf eines Projekts laden ([] wenn keiner existiert)."""
    path = _history_path(project_id)
    if not path.exists():
        log.debug("[brainstorm] keine History für %r (%s)", project_id, path)
        return []
    try:
        data = json.loads(path.read_text())
        msgs = data.get("messages", []) if isinstance(data, dict) else []
        log.debug("[brainstorm] History geladen: %r (%d Nachrichten)", project_id, len(msgs))
        return msgs
    except Exception as exc:
        log.warning("[brainstorm] History %r nicht lesbar (%s) — leer", project_id, exc)
        return []


def save_history(project_id: str, messages: list) -> int:
    """Brainstorm-Verlauf atomar speichern. Gibt die Anzahl gespeicherter Nachrichten zurück."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    # Loading-Platzhalter nie persistieren.
    clean = [m for m in (messages or []) if isinstance(m, dict) and not m.get("loading")]
    write_json_atomic(_history_path(project_id), {"messages": clean})
    log.info("[brainstorm] History gespeichert: %r (%d Nachrichten)", project_id, len(clean))
    return len(clean)


# ── Streaming-Dialog (Bridge :8950/stream, NDJSON tokenweise) ────────────────
def _bridge_messages(history: list, message: str) -> list:
    """Frontend-History + neue Nachricht → Claude-messages-Array."""
    out = []
    for msg in history or []:
        if not isinstance(msg, dict) or msg.get("loading"):
            continue
        role = _ROLE_MAP.get(msg.get("role"), "user")
        content = (msg.get("content") or "").strip()
        if content:
            out.append({"role": role, "content": content})
    out.append({"role": "user", "content": message})
    return out


async def stream_brainstorm(project_id: str, message: str, history: list):
    """Yieldet die Claude-Antwort tokenweise als NDJSON-Zeilen (wie die Bridge selbst).

    Format je Zeile: {"t": "<token>"} … abschliessend {"done": true}.
    Bei Fehler: {"error": "<text>"}. Der Aufrufer (StreamingResponse) reicht das
    unverändert durch; das Frontend liest zeilenweise.

    Async-Generator (opt_stream_threadpool_0811): claude_client.stream_lines läuft
    über httpx im Event-Loop statt einen anyio-Threadpool-Worker für bis zu 300s zu
    belegen — Details/Begründung im Docstring von app/services/stream_service.py.
    _project_context() macht blockierende Datei-/Lock-Reads (Manifest+Board) und
    läuft daher via anyio.to_thread.run_sync, statt sync im Event-Loop zu blockieren
    (card_42585751 — sonst friert genau der Aufruf ein, den der async-Umbau vermeiden wollte).
    """
    messages = _bridge_messages(history, message)
    context = await anyio.to_thread.run_sync(_project_context, project_id)
    system = SYSTEM_PROMPT + context
    log.info("[brainstorm] Stream start: projekt=%r turns=%d model=%s kontext=%dZ",
             project_id, len(messages), BRAINSTORM_MODEL, len(context))
    try:
        async for line in claude_client.stream_lines(system, messages, BRAINSTORM_MODEL, timeout=300):
            # Bridge-NDJSON 1:1 durchreichen (enthält {"t":…}, {"done":…}, {"error":…}).
            yield line + "\n"
        log.info("[brainstorm] Stream fertig: projekt=%r", project_id)
    except Exception as exc:
        log.error("[brainstorm] Stream-Fehler (projekt=%r): %s", project_id, exc)
        yield json.dumps({"error": f"Bridge nicht erreichbar: {exc}"}) + "\n"


# ── Idee → Kanban-Karte ──────────────────────────────────────────────────────
_CARD_SYSTEM = (
    "Du wandelst eine Brainstorming-Notiz in EINE konkrete Kanban-Karte um. "
    "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, kein Fliesstext, keine Code-Fences:\n"
    '{"title":"kurzer Titel (max 8 Wörter)","desc":"1-2 Sätze, was zu tun ist",'
    '"priority":"hoch|mittel|niedrig"}\n'
    "Bleib nah am Wortlaut der Notiz, erfinde keine neuen Details. Sprache: Deutsch."
)


def idea_to_card(project_id: str, text: str, column_id: str = "") -> dict:
    """Eine Brainstorm-Aussage → Karte im Projekt-Board (erste bzw. gewählte Spalte).

    Raises:
        ValueError: Text leer.
        FileNotFoundError: Board existiert nicht.
        RuntimeError: Board hat keine Spalten.
    """
    from project_creator import _claude_abo_text, _strip_md_fences  # lazy, Zirkelvermeidung

    text = (text or "").strip()
    if not text:
        raise ValueError("Kein Text für die Karte übergeben")
    if not _boards.exists(project_id):
        raise FileNotFoundError(f"Board '{project_id}' nicht gefunden")

    # KI-Verdichtung; bei Fehler Fallback auf Roh-Text (Karte entsteht IMMER).
    title, desc, prio = _fallback_card_fields(text)
    try:
        raw = _strip_md_fences(_claude_abo_text(_CARD_SYSTEM, text, max_tokens=400, timeout=90))
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end >= 0:
            obj = json.loads(raw[start:end + 1])
            title = (obj.get("title") or title).strip()[:120]
            desc = (obj.get("desc") or desc).strip()
            prio = (obj.get("priority") or prio).strip().lower()
            if prio not in PRIORITY_COLORS:
                prio = "mittel"
            log.info("[brainstorm] Karte via KI: %r (prio=%s)", title, prio)
        else:
            log.warning("[brainstorm] Karten-KI ohne JSON — Fallback-Text genutzt")
    except Exception as exc:
        log.warning("[brainstorm] Karten-KI fehlgeschlagen (%s) — Fallback-Text", exc)

    card = {
        "title": f"💡 {title}",
        "desc": desc or text[:1500],
        "description": desc or text[:1500],
        "label": PRIORITY_COLORS.get(prio, PRIORITY_COLORS["mittel"]),
        "priority": prio,
    }
    result: dict = {}

    def mutate(board_data):
        cols = board_data.get("columns", [])
        col = None
        if column_id:
            col = next((c for c in cols if c.get("id") == column_id), None)
        if col is None:
            col = cols[0] if cols else None
        if col is None:
            raise RuntimeError(f"Board '{project_id}' hat keine Spalten")
        col.setdefault("cards", []).append(card)
        result["column"] = col.get("title", col.get("id"))

    _boards.update(project_id, mutate, sync_claude_md=False)
    log.info("[brainstorm] Karte angelegt: %r → Board %r / Spalte %r",
             card["title"], project_id, result.get("column"))
    return {"status": "created", "card_title": card["title"], "column": result.get("column")}


def _fallback_card_fields(text: str) -> tuple:
    """Ohne KI: erste Zeile = Titel, ganzer Text = Beschreibung, Prio mittel."""
    first = " ".join(text.splitlines()[0].split())
    return first[:80], text[:1500], "mittel"


# ── Idee → Unterprojekt (reuse create_board mit Eltern-Kontext) ──────────────
def idea_to_subproject(project_id: str, text: str) -> dict:
    """Ausgereifte Idee → Unterprojekt (Board + CLAUDE.md + Tags + Ideen-Karten).

    Nutzt board_creation_service.create_board, das den Mutterprojekt-Kontext in ALLE
    KI-Schritte reicht (mehrdeutige Namen werden im Thema des Mutterprojekts interpretiert).

    Raises:
        ValueError: Text leer / Name unklar.
    """
    from app.services import board_creation_service  # lazy

    text = (text or "").strip()
    if not text:
        raise ValueError("Kein Text für das Unterprojekt übergeben")

    # Titel = erste Zeile (kompakt), Rest = Beschreibung.
    lines = [l for l in text.splitlines() if l.strip()]
    name = " ".join(lines[0].split())[:80] if lines else text[:80]
    description = text.strip()
    log.info("[brainstorm] Unterprojekt aus Idee: name=%r parent=%r", name, project_id)

    created = board_creation_service.create_board({
        "name": name,
        "description": description,
        "parent_ids": [project_id],
    })
    log.info("[brainstorm] Unterprojekt angelegt: %s", created.get("id"))
    return created


# ── Ganzes Gespräch verdichten (Transkript für die Prompts) ──────────────────
def _transcript(messages: list) -> str:
    """Frontend-Nachrichten → lesbares Transkript „Du: …" / „KI: …" für die Prompts."""
    label = {"user": "Du", "ai": "KI", "assistant": "KI"}
    out = []
    for m in messages or []:
        if not isinstance(m, dict) or m.get("loading"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        out.append(f"{label.get(m.get('role'), 'Du')}: {content}")
    return "\n".join(out)


# ── Ganzes Gespräch → Projekt-Beschreibung („die Story") ─────────────────────
_DESC_SYSTEM = (
    "Du fasst ein Brainstorming-Gespräch zu EINER prägnanten Projekt-Beschreibung zusammen. "
    "Schreibe 2-4 Sätze in ganzen Sätzen (kein Stichwort-Fliess, keine Aufzählung, keine "
    "Anrede, kein Titel): Worum geht das Projekt, was ist das Ziel, ggf. der geplante Weg. "
    "Bleib nah am Gesagten, erfinde nichts dazu. Nur der Beschreibungstext, sonst nichts. "
    "Sprache: Deutsch."
)


def conversation_to_description(project_id: str, messages: list) -> dict:
    """Ganzes Brainstorm-Gespräch → Projekt-Beschreibung ins Manifest (`description`).

    Ersetzt die bisherige Beschreibung bewusst (der Nutzer klickt den Button aktiv);
    der alte Wert wird zurückgegeben, damit das Frontend ihn anzeigen/rückgängig-anbieten kann.

    Raises:
        ValueError: kein Gesprächsinhalt.
        FileNotFoundError: Board nicht im Manifest.
    """
    from project_creator import _claude_abo_text  # lazy, Zirkelvermeidung
    from app.services import board_service  # lazy

    convo = _transcript(messages)
    if not convo.strip():
        raise ValueError("Kein Gesprächsinhalt für die Beschreibung")

    # Bisherige Beschreibung merken (für „rückgängig" im Frontend).
    old = ""
    try:
        entry = next((b for b in _manifest.load().get("boards", [])
                      if b.get("id") == project_id), None)
        if entry:
            old = entry.get("description") or ""
    except Exception as exc:
        log.debug("[brainstorm] alte Beschreibung nicht lesbar: %s", exc)

    desc = _claude_abo_text(_DESC_SYSTEM, convo, model=BRAINSTORM_MODEL,
                            max_tokens=400, timeout=90)
    desc = " ".join((desc or "").split()).strip()
    if not desc:
        raise ValueError("KI lieferte keine Beschreibung")
    log.info("[brainstorm] Beschreibung generiert (%d Z.) für %r", len(desc), project_id)

    # description lebt im Manifest (patch_board-Whitelist), NIE in der Karte.
    board_service.patch_board(project_id, {"description": desc})
    log.info("[brainstorm] Beschreibung gesetzt für %r", project_id)
    return {"status": "updated", "description": desc, "old_description": old}


# ── Ganzes Gespräch → mehrere Karten ins aktuelle Board ──────────────────────
_PLAN_SYSTEM = (
    "Du leitest aus einem Brainstorming-Gespräch die konkreten, umsetzbaren Aufgaben ab. "
    "Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Fliesstext, keine Code-Fences), "
    "je Aufgabe ein Objekt:\n"
    '[{"title":"kurzer Titel (max 8 Wörter)","desc":"1-2 Sätze, was zu tun ist",'
    '"priority":"hoch|mittel|niedrig"}]\n'
    "Nur Aufgaben, die im Gespräch wirklich vorkommen — erfinde keine dazu. Reihenfolge "
    "sinnvoll (Voraussetzungen zuerst). Höchstens 8 Aufgaben. Sprache: Deutsch."
)


def conversation_to_cards(project_id: str, messages: list, column_id: str = "") -> dict:
    """Ganzes Brainstorm-Gespräch → mehrere Karten in EINER Board-Spalte (Standard: erste).

    Raises:
        ValueError: kein Gesprächsinhalt / KI ohne verwertbare Aufgaben.
        FileNotFoundError: Board existiert nicht.
        RuntimeError: Board hat keine Spalten.
    """
    from project_creator import _claude_abo_text, _strip_md_fences  # lazy

    convo = _transcript(messages)
    if not convo.strip():
        raise ValueError("Kein Gesprächsinhalt für Karten")
    if not _boards.exists(project_id):
        raise FileNotFoundError(f"Board '{project_id}' nicht gefunden")

    raw = _strip_md_fences(_claude_abo_text(_PLAN_SYSTEM, convo, model=BRAINSTORM_MODEL,
                                            max_tokens=1200, timeout=120))
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < 0:
        log.warning("[brainstorm] Plan-KI ohne JSON-Array: %r", raw[:200])
        raise ValueError("KI lieferte keine verwertbare Aufgabenliste")
    items = json.loads(raw[start:end + 1])
    if not isinstance(items, list) or not items:
        raise ValueError("KI-Aufgabenliste leer")

    cards = []
    for it in items[:8]:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()[:120]
        if not title:
            continue
        desc = (it.get("desc") or "").strip()
        prio = (it.get("priority") or "mittel").strip().lower()
        if prio not in PRIORITY_COLORS:
            prio = "mittel"
        cards.append({
            "title": f"💡 {title}",
            "desc": desc or title,
            "description": desc or title,
            "label": PRIORITY_COLORS.get(prio, PRIORITY_COLORS["mittel"]),
            "priority": prio,
        })
    if not cards:
        raise ValueError("Keine gültigen Karten aus der KI-Antwort")

    result: dict = {}

    def mutate(board_data):
        cols = board_data.get("columns", [])
        col = None
        if column_id:
            col = next((c for c in cols if c.get("id") == column_id), None)
        if col is None:
            col = cols[0] if cols else None
        if col is None:
            raise RuntimeError(f"Board '{project_id}' hat keine Spalten")
        col.setdefault("cards", []).extend(cards)
        result["column"] = col.get("title", col.get("id"))

    _boards.update(project_id, mutate, sync_claude_md=False)
    log.info("[brainstorm] %d Karten angelegt → Board %r / Spalte %r",
             len(cards), project_id, result.get("column"))
    return {"status": "created", "count": len(cards), "column": result.get("column")}

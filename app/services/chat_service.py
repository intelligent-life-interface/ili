"""Chat-/KI-Dienste — extrahiert aus trigger_server (_handle_chat, _handle_title_suggest,
_handle_bug_report). Routing Claude↔Ollama via chat_helpers (wiederverwendet).

Schnittstelle
-------------
chat(data)                  -> dict   # OpenAI-kompatibles Chat-Result (mit Board-Kontext + Tools)
title_suggest(text, model)  -> dict   # {"title": ..., "desc": <Originaltext>}
bug_report(text, board_id)  -> dict   # legt 🐞-Karte im passenden Bug-Board an
"""
import logging
import os
from datetime import datetime
from uuid import uuid4

from bug_tracking import _find_bugs_board
from chat_helpers import _anthropic_chat_with_fallback, _simple_ollama_chat as _ollama_chat
from config_handler import _effort_temp, _load_ai_config
from logging_utils import _log_chat_history
from ow_integration import _ow_chat

from app.services import link_service
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.chat")

_boards = BoardRepository()
_manifest = ManifestRepository()


# Erledigt-/Archiv-Spalten: Karten nur als [id] Titel (referenzierbar), ohne desc-Ballast
_SLIM_SKIP_DESC_COLS = {"Erledigt", "Done", "Archiv", "Archive"}


def _slim_board(board_data: dict) -> str:
    """Minimal-Serialisierung des Boards für den Chat-System-Prompt.

    Statt json.dumps(indent=2) mit allen internen Feldern (Finding C#1 im Audit,
    ~9-13k Tokens/Call) nur das, was der Assistent zum Reden/Tool-Use braucht:
    pro Spalte die Karten als ``[id] Titel :: desc``. Erledigt/Archiv ohne desc.
    Spart je nach Board ~15-95 % Input-Tokens, ohne inhaltlichen Verlust.
    """
    lines = []
    for col in board_data.get("columns", []):
        title = col.get("title", "?")
        cards = col.get("cards", [])
        if title in _SLIM_SKIP_DESC_COLS:
            lines.append(f"## {title} ({len(cards)})")
            lines.extend(f"- [{c.get('id', '?')}] {c.get('title', '')}" for c in cards)
            continue
        lines.append(f"## {title}")
        for c in cards:
            cid = c.get("id", "?")
            t = c.get("title", "")
            d = (c.get("desc") or c.get("description") or "").strip().replace("\n", " ")
            lines.append(f"- [{cid}] {t}" + (f" :: {d}" if d else ""))
    slim = "\n".join(lines)
    log.debug("Slim-Board: %d Spalten, %d Zeichen (~%d Tokens)",
              len(board_data.get("columns", [])), len(slim), len(slim) // 4)
    return slim


def _build_system_context(board_id: str) -> str:
    """Board-Liste (kompakt, max 25) + aktuelles Board (slim) als System-Kontext."""
    manifest = _manifest.load()
    boards_list = manifest.get("boards", [])

    # Kompakte Board-Liste: nur ID=Name, max 25 aktuelle (spart ~38k Zeichen Input-Tokens)
    _MAX_BOARDS = 25
    recent = boards_list[-_MAX_BOARDS:]
    boards_compact = "; ".join(f"{b.get('id', '?')}={b.get('name', '?')}" for b in recent)
    extra_count = len(boards_list) - _MAX_BOARDS
    boards_summary = f"Boards ({len(boards_list)} gesamt, letzte {len(recent)}: {boards_compact}"
    if extra_count > 0:
        boards_summary += f" … +{extra_count} ältere"
    boards_summary += ")"

    system_ctx = "Kanban-Assistent. Boards erstellen, Karten verwalten.\n"
    system_ctx += boards_summary + "\n\n"
    log.debug("Board-Kontext: %d Boards, %d Zeichen", len(boards_list), len(boards_summary))

    if board_id:
        board_data = _boards.load(board_id, inject_claude_md=False)
        if board_data is not None:
            board_slim = _slim_board(board_data)
            system_ctx += f"Aktuelles Board (ID: {board_id}):\n{board_slim}\n\n"
            log.debug("Board '%s' als Slim-Context geladen (%d Zeichen)", board_id, len(board_slim))
        else:
            log.warning("Board '%s' für Chat-Context nicht gefunden", board_id)

    parent_hint = (
        f" WICHTIG: Wenn du Sub-Boards erstellst, verwende immer parent_ids=['{board_id}']"
        f" damit sie als Unterprojekte des aktuellen Boards '{board_id}' erscheinen."
    ) if board_id else ""
    system_ctx += (
        "Antworte auf Deutsch. "
        "Nutze die verfügbaren Tools um Boards anzulegen oder zu bearbeiten — "
        "erkläre dem Nutzer was du gemacht hast."
        + parent_hint
    )
    return system_ctx


def chat(data: dict) -> dict:
    """Chat-Request mit Board-Kontext, History-Limit und Claude/Ollama-Routing.

    Raises:
        ValueError: messages fehlt/leer.
    """
    ai_cfg = _load_ai_config()
    model = data.get("model") or ai_cfg["chat_model"]
    messages = data.get("messages", [])
    board_id = data.get("board_id", "")
    log.debug("Chat: model=%r, messages=%d, board_id=%r", model, len(messages), board_id)

    if not messages:
        raise ValueError("Feld 'messages' fehlt oder ist leer")

    system_ctx = _build_system_context(board_id)

    # Chat-History auf max. 10 Nachrichten (5 Turns) begrenzen — verhindert Token-Inflation
    _MAX_HISTORY = 10
    non_sys = [m for m in messages if m.get("role") != "system"]
    if len(non_sys) > _MAX_HISTORY:
        dropped = len(non_sys) - _MAX_HISTORY
        non_sys = non_sys[-_MAX_HISTORY:]
        log.info("Chat-History gekürzt: %d alte Nachrichten entfernt, %d behalten", dropped, len(non_sys))
    messages = [{"role": "system", "content": system_ctx}] + non_sys
    log.debug("System-Context: %d Zeichen, %d Chat-Nachrichten", len(system_ctx), len(messages) - 1)

    ow_payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": _effort_temp("chat_effort")},
    }
    for key in ("temperature", "max_tokens", "top_p", "stop"):
        if key in data:
            ow_payload[key] = data[key]

    # Routing: Claude → Anthropic (mit Ollama-Fallback bei Quota), sonst Ollama plain
    if model.lower().startswith("claude"):
        log.debug("Claude-Modell: %s", model)
        result = _anthropic_chat_with_fallback(ow_payload)
    else:
        log.debug("Ollama plain Chat: %s", model)
        result = _ollama_chat(ow_payload, context=f"chat:{board_id}")

    log.debug("Chat-Antwort erhalten: keys=%s", list(result.keys()))

    # History-Log (letzte User-Nachricht + Antwort)
    user_msgs_only = [m for m in messages if m.get("role") == "user"]
    last_user_msg = user_msgs_only[-1]["content"] if user_msgs_only else ""
    if isinstance(last_user_msg, list):  # multipart content
        last_user_msg = " ".join(p.get("text", "") for p in last_user_msg if isinstance(p, dict))
    assistant_text = ""
    try:
        assistant_text = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        pass
    _log_chat_history(board_id, model, last_user_msg, assistant_text)

    if board_id:
        try:
            link_service.add_from_chat(board_id, "user", last_user_msg)
            link_service.add_from_chat(board_id, "assistant", assistant_text)
        except Exception:
            log.exception("Link-Erkennung aus Chat fehlgeschlagen (board=%s)", board_id)

    return result


def title_suggest(text: str, model: str = "mistral:latest") -> dict:
    """Kurztitel (max 55 Zeichen) aus Freitext via KI. desc = Originaltext."""
    log.info("[title-suggest] model=%r, text=%r…", model, text[:60])
    prompt = (
        "Erstelle aus dem folgenden Text einen kurzen Kanban-Kartentitel auf Deutsch.\n"
        "Regeln:\n"
        "- Maximal 55 Zeichen\n"
        "- Aktive Formulierung (z.B. 'Login-Fehler beheben', 'Mobile Navigation einbauen')\n"
        "- Kein Punkt am Ende, keine Anführungszeichen\n"
        "- Nur den Titel ausgeben — keine Erklärung, kein Präfix wie 'Titel:'\n\n"
        f"Text: {text}"
    )
    result = _ow_chat({"model": model, "messages": [{"role": "user", "content": prompt}]})

    raw_title = ""
    if result and result.get("choices"):
        raw_title = result["choices"][0].get("message", {}).get("content", "")
    elif result and result.get("message"):
        raw_title = result["message"].get("content", "")

    title = raw_title.strip().split("\n")[0].strip().rstrip(".")
    for prefix in ("titel:", "title:", "karte:", "aufgabe:"):
        if title.lower().startswith(prefix):
            title = title[len(prefix):].strip()
    if len(title) > 55:
        title = title[:52] + "…"

    log.info("[title-suggest] Ergebnis: %r", title)
    return {"title": title, "desc": text}


def bug_report(text: str, context_id: str = "", dedup_key: str = "") -> dict:
    """🐞-Karte im passenden Bug-Board anlegen (Semantik aus _handle_bug_report).

    dedup_key: idempotent mode for periodic reporters (healthchecks etc.).
    The card gets the stable id ``bug::<dedup_key>`` and repeat reports UPDATE
    that one card (occurrence counter + latest details) instead of piling up
    date-stamped clones — house rule [[feedback_idempotenz_hash_statt_datum]];
    24 clones of the GB healthcheck card were the main dedup-noise source.

    Raises:
        ValueError: Beschreibung fehlt.
        RuntimeError: Ziel-Board hat keine Spalten.
    """
    description = text.replace("🐞", "").strip()
    if not description:
        raise ValueError("Bug-Beschreibung fehlt (bitte nach 🐞 beschreiben)")

    board_id, board_name = _find_bugs_board(text, context_id)
    if not _boards.exists(board_id):
        log.warning("Bug-Board '%s' nicht gefunden — Fallback auf home-stack-bugs", board_id)
        board_id = "home-stack-bugs"
        board_name = "Home Stack – Bughandling"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Titel nur aus der ersten Zeile (Whitespace normalisiert) — mehrzeilige Reports
    # zerschnitt [:80] sonst mitten im Kontext (Bug 2026-07-08: Titel endete auf 1 Buchstaben).
    # Der volle Text wandert in die Karten-Beschreibung, damit nichts verloren geht.
    first_line = " ".join(description.splitlines()[0].split())
    card_title = f"🐞 {first_line[:80]}"
    log.debug("bug_report: first_line=%r (aus %d Zeichen Text)", first_line[:80], len(description))
    result: dict = {}

    card_id = f"bug::{dedup_key.strip()}" if dedup_key.strip() else ""
    desc_text = f"Gemeldet am {timestamp} via Chat\n\n{description[:1500]}"

    def mutate(board_data):
        # Idempotent path: update the existing card wherever it sits (also when
        # it was moved to another column — never re-file or duplicate it).
        if card_id:
            for c in board_data.get("columns", []):
                for card in c.get("cards", []):
                    if card.get("id") == card_id:
                        n = int(card.get("bug_count") or 1) + 1
                        card["bug_count"] = n
                        card["title"] = card_title
                        upd = (f"Zuletzt am {timestamp} — {n}. Meldung "
                               f"(idempotente Karte, keine Datums-Klone)\n\n{description[:1500]}")
                        card["desc"] = card["description"] = upd
                        result["column"] = c.get("title", c.get("id"))
                        result["updated"] = True
                        result["card_id"] = card_id
                        log.debug("bug_report: Karte %s aktualisiert (Meldung #%d)", card_id, n)
                        return
        # "reported"-Spalte bevorzugen, sonst erste Spalte
        col = next((c for c in board_data.get("columns", []) if c.get("id") == "reported"), None)
        if col is None:
            cols = board_data.get("columns", [])
            col = cols[0] if cols else None
        if col is None:
            raise RuntimeError(f"Board '{board_id}' hat keine Spalten")
        # Auch ohne dedup_key eine stabile id vergeben (gleiches Muster wie
        # _ensure_card_ids() in board_repository.py) — Aufrufer wie der geplante
        # UI-Kit-Report-Button brauchen die card_id sofort zurück, um danach per
        # POST /api/attachments einen Screenshot anzuhängen.
        new_id = card_id or f"card_{uuid4().hex[:8]}"
        log.debug("bug_report: neue Karte bekommt id=%r (dedup_key gesetzt: %s)", new_id, bool(card_id))
        new_card = {
            "id": new_id,
            "title": card_title,
            "desc": desc_text,
            "description": desc_text,
            "label": "#fc8181",
        }
        if card_id:
            new_card["bug_count"] = 1
        col.setdefault("cards", []).append(new_card)
        result["column"] = col.get("title", col.get("id"))
        result["card_id"] = new_id

    _boards.update(board_id, mutate, sync_claude_md=False)
    log.info("Bug-Report %s: '%s' → Board '%s' / Spalte '%s'",
             "aktualisiert" if result.get("updated") else "erstellt",
             card_title, board_id, result["column"])

    return {
        "status": "updated" if result.get("updated") else "created",
        "board_id": board_id,
        "board_name": board_name,
        "board_url": f"{os.environ.get('SERVER_URL', 'http://localhost')}/project.html?id={board_id}",
        "card_title": card_title,
        "column": result["column"],
        "card_id": result.get("card_id"),
    }

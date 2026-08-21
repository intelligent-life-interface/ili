"""Automatische Link-Erkennung im Projekt-Chat.

Trägt URLs, die im Chat (User- oder KI-Nachricht) auftauchen, als Anhang-
Einträge (`type="link"`) ins Board ein — landen damit automatisch im
bestehenden 📎-Anhänge-Modal, neueste zuoberst. Kein manueller Upload nötig.

Hook: chat_service.chat() ruft add_from_chat() nach jeder Chat-Runde auf
(einziger zentraler Ort, an dem User-Text + Assistant-Text zusammen mit der
board_id vorliegen).

Schnittstelle:
- extract_urls(text)                  -> list[str]
- add_from_chat(board_id, role, text) -> int   (Anzahl neu eingetragener Links)
"""
import logging
import re
import uuid
from datetime import datetime

from app.storage.board_repository import BoardRepository

log = logging.getLogger("dashboard.services.link")

_boards = BoardRepository()

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_TRAILING_PUNCT = ".,;:!?)]}\"'"


def _clean_url(url: str) -> str:
    """Schneidet Satzzeichen/Klammern ab, die noch zum Fliesstext gehören (z.B. '...siehe https://x.ch/y.')."""
    while url and url[-1] in _TRAILING_PUNCT:
        url = url[:-1]
    return url


def extract_urls(text: str) -> list:
    """Alle http(s)-URLs aus Freitext, dedupliziert, in Fundreihenfolge."""
    if not text:
        return []
    seen, out = set(), []
    for m in _URL_RE.finditer(text):
        u = _clean_url(m.group(0))
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _label(url: str) -> str:
    """Kurzer Anzeigename fürs Anhänge-Modal: alles nach dem Schema, gekürzt."""
    rest = url.split("://", 1)[-1]
    return rest if len(rest) <= 70 else rest[:67] + "…"


def add_from_chat(board_id: str, role: str, text: str) -> int:
    """URLs aus einer Chat-Nachricht extrahieren und neue (nicht bereits vorhandene)
    als Anhang-Einträge ganz oben in board["attachments"] eintragen.

    Returns: Anzahl neu eingetragener Links (0 wenn keine/nur schon bekannte URLs).
    """
    if not board_id or not text:
        return 0
    urls = extract_urls(text)
    if not urls:
        return 0

    added = {"n": 0}

    def mut(data):
        existing = {a.get("url") for a in data.get("attachments", []) if a.get("type") == "link"}
        new_entries = []
        for u in urls:
            if u in existing:
                continue
            existing.add(u)
            new_entries.append({
                "id": uuid.uuid4().hex[:12],
                "type": "link",
                "url": u,
                "filename": _label(u),
                "uploaded": datetime.now().isoformat(timespec="seconds"),
                "source": "chat",
                "role": role,
            })
        if new_entries:
            data.setdefault("attachments", [])[:0] = new_entries  # neueste zuoberst
            added["n"] = len(new_entries)
        return data

    _boards.update(board_id, mut, sync_claude_md=False)
    if added["n"]:
        log.info("Chat-Link(s) erkannt: %d neu für Board %s (role=%s)", added["n"], board_id, role)
    return added["n"]

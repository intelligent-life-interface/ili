"""Prompt-Loader: zentrale Prompts aus Bibliothek laden mit Fallback auf Alt-Werte.

Verhindert, dass Prompts inline verstreut sind, stattdessen: zentral in prompts/
verwaltet und versioniert. Lädt Markdown-Dateien, parsed den "Text"-Block,
cacht das Ergebnis (pro Process).

Changelog: prompts/CHANGELOG.md
"""
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("dashboard.prompts.loader")

# Prompt-Cache: {id -> text}. Einmal pro Process geladen (keine Hot-Reload).
_PROMPT_CACHE: dict[str, str] = {}

# Fallback-Werte (Alt-Inlines für Fehlerfall).
_FALLBACKS = {
    "brainstorm/system_prompt": (
        "Du bist ein kreativer Brainstorming-Partner für ein privates Homeserver-Projekt. "
        "Höre aktiv zu, stelle gezielte Rückfragen, bring eigene Ideen ein und hilf, Gedanken "
        "zu schärfen und weiterzuentwickeln. Sei prägnant statt ausschweifend, biete konkrete "
        "Alternativen an und nutze Emojis sparsam. Antworte auf Deutsch.\n"
        "WICHTIG (Anti-Fantasie): Stütze dich auf das, was der Nutzer wirklich sagt. Ist eine "
        "Idee noch dünn, frag lieber nach, statt Details zu erfinden."
    ),
    "brainstorm/card_from_idea": (
        "Du wandelst eine Brainstorming-Notiz in EINE konkrete Kanban-Karte um. "
        "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, kein Fliesstext, keine Code-Fences:\n"
        '{"title":"kurzer Titel (max 8 Wörter)","desc":"1-2 Sätze, was zu tun ist",'
        '"priority":"hoch|mittel|niedrig"}\n'
        "Bleib nah am Wortlaut der Notiz, erfinde keine neuen Details. Sprache: Deutsch."
    ),
    # Weitere Fallbacks hier hinzufügen...
}


def _parse_md_text_block(md_content: str) -> Optional[str]:
    """Extrahiert aus Markdown-Datei den '## Text'-Block bis zur nächsten Überschrift.

    Format:
        ```
        ## Text

        ```
        Du bist ein...
        ```
        ```

        ## Eigenschaften
        ...
    ```

    Returns text-content (mit Code-Fences entfernt) oder None falls kein Block.
    """
    match = re.search(r'## Text\s*\n+```\n(.*?)\n```', md_content, re.DOTALL)
    if not match:
        log.warning("Kein '## Text'-Block mit ```-Fences gefunden")
        return None
    return match.group(1).strip()


def load_prompt(prompt_id: str) -> str:
    """Prompt aus der Bibliothek laden (mit Caching + Fallback).

    Args:
        prompt_id: z.B. "brainstorm/system_prompt" (slug für die .md-Datei)

    Returns:
        Prompt-Text oder Fallback-Wert. Wirft NIEMALS; schlimmstenfalls Fallback.
    """
    # Cache-Hit?
    if prompt_id in _PROMPT_CACHE:
        return _PROMPT_CACHE[prompt_id]

    # Datei finden: prompts/<id>.md
    prompt_path = Path(__file__).parent / f"{prompt_id}.md"
    if not prompt_path.exists():
        log.warning(f"Prompt-Datei nicht gefunden: {prompt_path} — Fallback")
        text = _FALLBACKS.get(prompt_id)
        if text:
            _PROMPT_CACHE[prompt_id] = text
            return text
        # Fallback auch nicht vorhanden.
        log.error(f"Kein Fallback für {prompt_id!r}")
        return ""

    # Markdown laden und parsen.
    try:
        md_content = prompt_path.read_text(encoding="utf-8")
        text = _parse_md_text_block(md_content)
        if not text:
            raise ValueError(f"'## Text'-Block nicht parsebar in {prompt_path}")
        _PROMPT_CACHE[prompt_id] = text
        log.debug(f"Prompt geladen: {prompt_id} ({len(text)} Zeichen)")
        return text
    except Exception as exc:
        log.warning(f"Fehler beim Laden von {prompt_id}: {exc} — Fallback")
        text = _FALLBACKS.get(prompt_id)
        if text:
            _PROMPT_CACHE[prompt_id] = text
            return text
        log.error(f"Kein Fallback für {prompt_id!r}")
        return ""


# Convenience-Shortcuts für häufig benutzte Prompts.
def load_brainstorm_system() -> str:
    return load_prompt("brainstorm/system_prompt")


def load_brainstorm_card() -> str:
    return load_prompt("brainstorm/card_from_idea")


def load_brainstorm_description() -> str:
    return load_prompt("brainstorm/description_from_convo")


def load_brainstorm_cards() -> str:
    return load_prompt("brainstorm/cards_from_plan")


def load_project_correct_name() -> str:
    return load_prompt("project_creation/correct_name")


def load_bug_triage() -> str:
    return load_prompt("bug_analysis/bug_triage")

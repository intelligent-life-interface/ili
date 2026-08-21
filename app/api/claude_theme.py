"""API-Router: Claude-Code-Farbmodus (Theme) lesen/setzen.

Routen: GET /api/claude-theme, POST /api/claude-theme

Claude Code hat sechs eingebaute Farbmodi und liest den gewählten beim START aus
~/.claude/settings.json. Es gibt KEINEN CLI-Unterbefehl dafür ("claude config" wird
als Prompt interpretiert), und ein laufender Prozess übernimmt eine Änderung nicht —
sie gilt ab der nächsten Session. Genau so ist es mit dem User abgesprochen.

Bewusst KEIN json.dump beim Schreiben: settings.json enthält Hooks, Permissions und
Env des Harness. Ein Reformatieren der ganzen Datei wäre ein unnötiges Risiko, darum
wird gezielt nur die eine "theme"-Zeile ersetzt (und vorher validiert, dass es genau
eine gibt).
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException

log = logging.getLogger("dashboard.api.claude_theme")
router = APIRouter(tags=["claude-theme"])

# Verifiziert aus dem installierten Claude-Binary (2.1.224): die Werte, die der
# Einrichtungs-Dialog anbietet. Reihenfolge = Reihenfolge im Knopf-Durchlauf.
THEMES = [
    {"key": "dark",             "icon": "🌙", "label": "Dunkel"},
    {"key": "light",            "icon": "☀️", "label": "Hell"},
    {"key": "dark-daltonized",  "icon": "🌘", "label": "Dunkel, farbfehlsichtigkeits-freundlich"},
    {"key": "light-daltonized", "icon": "🌗", "label": "Hell, farbfehlsichtigkeits-freundlich"},
    {"key": "dark-ansi",        "icon": "🖤", "label": "Dunkel, nur ANSI-Farben des Terminals"},
    {"key": "light-ansi",       "icon": "🤍", "label": "Hell, nur ANSI-Farben des Terminals"},
]
_VALID = {t["key"] for t in THEMES}

# Beide Dateien: settings.local.json überschreibt settings.json — würde nur eine
# gesetzt, bliebe der alte Wert je nach Vorrang wirksam (gleiche Falle wie bei
# "language" am 07.08.2026).
_FILES = [Path.home() / ".claude" / "settings.json",
          Path.home() / ".claude" / "settings.local.json"]
_THEME_RE = re.compile(r'^(?P<pre>\s*"theme"\s*:\s*")(?P<val>[^"]*)(?P<post>")', re.M)


def _read_theme() -> str | None:
    """Aktueller Wert — settings.local.json gewinnt, weil sie Vorrang hat."""
    for path in reversed(_FILES):
        try:
            if path.exists():
                val = json.loads(path.read_text(encoding="utf-8")).get("theme")
                if val:
                    return val
        except Exception as e:
            log.error("claude-theme: %s nicht lesbar: %s", path, e, exc_info=True)
    return None


def _write_theme(path: Path, theme: str) -> bool:
    """Ersetzt NUR die theme-Zeile, atomar. False = Datei ohne theme-Eintrag."""
    if not path.exists():
        log.debug("claude-theme: %s existiert nicht — übersprungen", path)
        return False
    text = path.read_text(encoding="utf-8")
    hits = _THEME_RE.findall(text)
    if len(hits) != 1:
        log.error("claude-theme: %s hat %d 'theme'-Zeilen (erwartet 1) — nicht angefasst",
                  path, len(hits))
        return False
    new = _THEME_RE.sub(lambda m: m.group("pre") + theme + m.group("post"), text, count=1)
    json.loads(new)   # Sicherheitsnetz: nie kaputtes JSON zurückschreiben
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    log.info("claude-theme: %s -> %s", path.name, theme)
    return True


@router.get("/api/claude-theme")
def get_theme():
    """Aktueller Farbmodus + Liste aller verfügbaren (für den Knopf im Terminal)."""
    cur = _read_theme()
    return {"theme": cur, "themes": THEMES, "valid": cur in _VALID}


@router.post("/api/claude-theme")
def set_theme(body: dict | None = None):
    """Farbmodus setzen. Wirkt ab der NÄCHSTEN Claude-Session (siehe Modul-Docstring)."""
    theme = ((body or {}).get("theme") or "").strip()
    if theme not in _VALID:
        raise HTTPException(status_code=400,
                            detail=f"Unbekannter Farbmodus '{theme}' — erlaubt: {sorted(_VALID)}")
    written = []
    for path in _FILES:
        try:
            if _write_theme(path, theme):
                written.append(path.name)
        except Exception as e:
            log.error("claude-theme: Schreiben in %s fehlgeschlagen: %s", path, e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Interner Serverfehler beim Schreiben von {path.name}")
    if not written:
        raise HTTPException(status_code=500, detail="Keine settings-Datei mit 'theme'-Eintrag gefunden")
    return {"theme": theme, "written": written,
            "hint": "Gilt ab der nächsten Claude-Session — laufende behalten ihre Farben."}

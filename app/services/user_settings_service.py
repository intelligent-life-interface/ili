"""user_settings_service.py — Benutzereinstellungen laden und speichern.

Die Einstellungen (Theme, Akzentfarbe, Schriftgrösse, Spalten, Widget-Sichtbarkeit)
werden in user_settings.json im Dashboard-Verzeichnis persistiert.
Da das Dashboard kein Login hat (bewusst, LAN-only), gibt es einen einzigen
globalen Einstellungs-Datensatz.

Erlaubte Keys (alle anderen werden beim Schreiben ignoriert):
    theme       str     "dark" | "light" | "contrast"
    accent      str     "#rrggbb" oder null (Standard)
    fontscale   int     90 | 100 | 110 | 125
    cols        str     "auto" | "1" | "2" | "3"
    widgets     dict    {<id>: bool}  — Widget-Sichtbarkeit auf Index-Seite
    github_auto_report  bool  opt-in: send sanitized error reports to GitHub (default False)
"""
import json
import logging

from constants import USER_SETTINGS_FILE
from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.user_settings")

_VALID_THEMES    = {"dark", "light", "contrast"}
_VALID_SCALES    = {90, 100, 110, 125}
_VALID_COLS      = {"auto", "1", "2", "3"}
_VALID_WIDGETS   = {"zoom", "eisenhower", "ki_prio", "ki_settings", "archiv", "arrange"}
_HEX_RE = __import__("re").compile(r'^#[0-9a-fA-F]{6}$')

_DEFAULTS: dict = {
    "theme":     "dark",
    "accent":    None,
    "fontscale": 100,
    "cols":      "auto",
    "widgets":   {w: True for w in _VALID_WIDGETS},
    "github_auto_report": False,
}


def load() -> dict:
    """Einstellungen laden. Fehlt die Datei, werden Defaults zurückgegeben."""
    if not USER_SETTINGS_FILE.exists():
        log.debug("user_settings.json fehlt — Defaults zurückgeben")
        return dict(_DEFAULTS)
    try:
        raw = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
        result = _merge_with_defaults(raw)
        log.debug("user_settings geladen: %s", result)
        return result
    except Exception as exc:
        log.error("user_settings.json lesen fehlgeschlagen: %s", exc)
        return dict(_DEFAULTS)


def save(data: dict) -> dict:
    """Einstellungen validieren und speichern. Gibt die gespeicherten Werte zurück.

    Raises:
        ValueError: ungültige Feldwerte
    """
    cleaned = _validate(data)
    write_json_atomic(USER_SETTINGS_FILE, cleaned)
    log.info("user_settings gespeichert: theme=%s accent=%s fontscale=%s cols=%s",
             cleaned["theme"], cleaned["accent"], cleaned["fontscale"], cleaned["cols"])
    return cleaned


def _merge_with_defaults(raw: dict) -> dict:
    """Unbekannte/fehlende Keys mit Defaults füllen (kein Fehler bei fehlenden Keys)."""
    result = dict(_DEFAULTS)
    if "theme" in raw and raw["theme"] in _VALID_THEMES:
        result["theme"] = raw["theme"]
    if "accent" in raw:
        v = raw["accent"]
        result["accent"] = v if (v is None or _HEX_RE.match(str(v))) else None
    if "fontscale" in raw:
        try:
            n = int(raw["fontscale"])
            if n in _VALID_SCALES:
                result["fontscale"] = n
        except (TypeError, ValueError):
            pass
    if "cols" in raw and str(raw["cols"]) in _VALID_COLS:
        result["cols"] = str(raw["cols"])
    if "widgets" in raw and isinstance(raw["widgets"], dict):
        result["widgets"] = {
            w: bool(raw["widgets"].get(w, True)) for w in _VALID_WIDGETS
        }
    if "github_auto_report" in raw:
        result["github_auto_report"] = bool(raw["github_auto_report"])
        log.debug("github_auto_report=%s", result["github_auto_report"])
    return result


def _validate(data: dict) -> dict:
    """Strenge Validierung — wirft ValueError bei ungültigen Werten."""
    result = _merge_with_defaults(data)

    # Explizite Fehler für unbekannte Werte (nicht nur still ignorieren)
    if "theme" in data and data["theme"] not in _VALID_THEMES:
        raise ValueError(f"Ungültiger Theme-Wert: {data['theme']!r}. Erlaubt: {_VALID_THEMES}")
    if "fontscale" in data:
        try:
            n = int(data["fontscale"])
            if n not in _VALID_SCALES:
                raise ValueError(f"Ungültige Schriftgrösse: {n}. Erlaubt: {sorted(_VALID_SCALES)}")
        except (TypeError, ValueError) as exc:
            if "Ungültige" in str(exc):
                raise
            raise ValueError(f"fontscale muss eine Zahl sein, got: {data['fontscale']!r}") from exc
    if "cols" in data and str(data["cols"]) not in _VALID_COLS:
        raise ValueError(f"Ungültige Spaltenzahl: {data['cols']!r}. Erlaubt: {_VALID_COLS}")
    if "accent" in data and data["accent"] is not None:
        if not _HEX_RE.match(str(data["accent"])):
            raise ValueError(f"Ungültige Akzentfarbe: {data['accent']!r}. Erwartet: #rrggbb")

    return result

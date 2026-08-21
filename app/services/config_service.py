"""Config-/Modell-Lesedienste — dünne Wrapper um Bestandsmodule.

Schnittstelle
-------------
board_templates() -> dict  # board_templates.json (via template_loader)
ai_config()      -> dict   # ai_config.json (via config_handler)
categories()     -> dict   # {"categories": CATEGORIES}
statuses()       -> dict   # {"statuses": STATUSES}
ollama_models()  -> dict   # OpenWebUI-Format {data: [{id, name, size}]} — leere Liste bei Fehler
"""
import logging

from config_handler import _load_ai_config, _save_ai_config
from constants import CATEGORIES, STATUSES, TEMPLATES_FILE
from template_loader import _load_templates
from app.services import ollama_client
from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.config")


def board_templates() -> dict:
    log.debug("Board-Templates laden")
    return _load_templates()


def ai_config() -> dict:
    return _load_ai_config()


def categories() -> dict:
    return {"categories": CATEGORIES}


def statuses() -> dict:
    return {"statuses": STATUSES}


def save_templates(data: dict) -> int:
    """board_templates.json speichern. Returns Anzahl Templates.

    Raises:
        ValueError: Feld 'templates' fehlt.
    """
    if "templates" not in data:
        raise ValueError("Feld 'templates' fehlt")
    write_json_atomic(TEMPLATES_FILE, data)
    log.info("board_templates.json gespeichert: %d Templates", len(data["templates"]))
    return len(data["templates"])


def save_ai_config(data: dict) -> dict:
    """KI-Konfiguration speichern (nur bekannte Keys), Returns die neue Voll-Config."""
    _save_ai_config(data)
    return _load_ai_config()


def ollama_models() -> dict:
    """Verfügbare Ollama-Modelle (OpenWebUI-kompatibel). Fehler → leere Liste, kein 500."""
    log.debug("GET /api/models — Ollama-Modellliste abrufen")
    try:
        data = ollama_client.tags(timeout=10)
        models = data.get("models", [])
        log.info("Ollama-Modelle: %s", [m["name"] for m in models])
        return {"data": [{"id": m["name"], "name": m["name"], "size": m.get("size", 0)} for m in models]}
    except Exception as e:
        log.error("Ollama-Modellliste fehlgeschlagen: %s", e)
        return {"data": []}

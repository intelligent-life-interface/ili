"""\ntemplate_loader.py — Template-Management-Funktionen\nAutogeneriert von script_splitter.py\n"""
import json
import logging
from constants import TEMPLATES_FILE

log = logging.getLogger("dashboard.template_loader")


def _load_templates() -> dict:
    """Lädt board_templates.json. Gibt leeres Dict bei Fehler zurück."""
    try:
        return json.loads(TEMPLATES_FILE.read_text())
    except Exception as e:
        log.error(f"board_templates.json konnte nicht geladen werden: {e}")
        return {"templates": {}}



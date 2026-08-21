"""config_handler.py — KI-Konfiguration laden, speichern und Effort-Temperaturen auflösen.

Öffentliche Schnittstellen
--------------------------
_load_ai_config() -> dict
    Aktuelle KI-Konfiguration laden (Datei + Defaults zusammengeführt).
    Rückgabe: {"chat_model": str, "ki_advisor_model": str, "bug_model": str, ...}
    Alle möglichen Keys: siehe _AI_CONFIG_DEFAULTS in constants.py.

_save_ai_config(data) -> None
    Nur bekannte Keys (aus _AI_CONFIG_DEFAULTS) speichern, unbekannte ignorieren.
    Side effect: Schreibt ai_config.json.

_effort_temp(effort_key) -> float
    Effort-Key aus Config → Temperatur-Float für Ollama.
    Mapping: "low" → 0.2,  "medium" → 0.5,  "high" → 0.8.
    Gibt 0.5 zurück wenn Key nicht vorhanden oder Wert unbekannt.
"""
import json
import logging
from constants import AI_CONFIG_FILE, _AI_CONFIG_DEFAULTS, _EFFORT_TEMP
from app.storage.atomic_write import write_json_atomic
from app.storage.locking import file_lock

log = logging.getLogger("dashboard.config_handler")

_AI_CONFIG_LOCK = AI_CONFIG_FILE.with_name(AI_CONFIG_FILE.name + ".lock")


def _load_ai_config() -> dict:
    """Liest ai_config.json und füllt fehlende Keys mit Defaults auf.

    Returns:
        Vollständiges Config-Dict (immer alle Keys vorhanden, nie KeyError).
    """
    try:
        data = json.loads(AI_CONFIG_FILE.read_text())
        return {**_AI_CONFIG_DEFAULTS, **data}
    except Exception:
        return dict(_AI_CONFIG_DEFAULTS)



def _save_ai_config(data: dict) -> None:
    """KI-Konfiguration speichern. Nur bekannte Keys werden übernommen.

    Args:
        data: Partial- oder Voll-Config-Dict. Unbekannte Keys werden ignoriert.
    Side effects:
        Schreibt ai_config.json (erstellt Datei falls nicht vorhanden).

    Kompletter Read-Modify-Write unter file_lock: zwei parallele POST
    /api/ai-config verlieren sonst eine der beiden Änderungen (Lost Update).
    Liest die Datei hier bewusst direkt statt über _load_ai_config() —
    file_lock ist nicht re-entrant (neuer fd blockiert gegen den bereits
    gehaltenen Lock desselben Prozesses).
    """
    with file_lock(_AI_CONFIG_LOCK):
        try:
            current = {**_AI_CONFIG_DEFAULTS, **json.loads(AI_CONFIG_FILE.read_text())}
        except Exception:
            current = dict(_AI_CONFIG_DEFAULTS)
        current.update({k: v for k, v in data.items() if k in _AI_CONFIG_DEFAULTS})
        write_json_atomic(AI_CONFIG_FILE, current)
    log.info(f"AI-Config gespeichert: {current}")

HOST = "0.0.0.0"
PORT = 8799
CORS_ORIGIN = "*"

# Keyword → Bug-Board Mapping: einzige Quelle in constants.py (_BUG_BOARD_KEYWORDS),
# oben re-importiert. NICHT hier duplizieren.


def _effort_temp(effort_key: str) -> float:
    """Effort-Einstellung aus Config → Ollama-Temperatur.

    Args:
        effort_key: Config-Key, z.B. "bug_effort", "ki_advisor_effort".
    Returns:
        0.2 (low) | 0.5 (medium/default) | 0.8 (high)
    """
    cfg = _load_ai_config()
    effort = cfg.get(effort_key, "medium")
    return _EFFORT_TEMP.get(effort, 0.5)

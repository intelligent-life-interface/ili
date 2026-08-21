"""Drossel-Limits des Kanban-Automaten lesen/schreiben (für /automat.html → „⚙️ Drossel").

Die Werte liegen in `automat_limits.json` neben dieser Anwendung; der Automat
(`~/containers/kanban-automat/`) liest dieselbe Datei bei jedem Tick.

Bewusst KEINE zweite Kopie der Grenzwerte hier: die Spezifikation (Default, min, max,
Beschreibung je Stellschraube) wird aus dem `limits.py` des Automaten geladen. Zwei
Kopien würden garantiert auseinanderlaufen. Fehlt der Automat-Ordner, liefert der
Service einen klaren Fehler statt geratener Grenzen.
"""
import importlib.util
import logging
import os
from pathlib import Path

from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.automat_limits")

AUTOMAT_DIR = Path(os.getenv("AUTOMAT_DIR", str(Path.home() / "containers/kanban-automat")))
LIMITS_FILE = Path(__file__).resolve().parents[2] / "automat_limits.json"

_limits_mod = None


class AutomatUnavailable(RuntimeError):
    """Das limits.py des Automaten ist nicht ladbar (Ordner fehlt/defekt)."""


def _load_limits_module():
    """limits.py des Automaten als Modul laden (einmalig, dann gecacht)."""
    global _limits_mod
    if _limits_mod is not None:
        return _limits_mod
    path = AUTOMAT_DIR / "limits.py"
    if not path.exists():
        log.error("automat_limits: %s nicht gefunden", path)
        raise AutomatUnavailable(f"limits.py des Automaten fehlt: {path}")
    spec = importlib.util.spec_from_file_location("automat_limits_spec", path)
    if spec is None or spec.loader is None:
        raise AutomatUnavailable(f"limits.py nicht ladbar: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    log.debug("automat_limits: %s geladen (%d Stellschrauben)", path, len(mod.SPEC))
    _limits_mod = mod
    return mod


def get_limits() -> dict:
    """Aktuelle Werte + Grenzen + Erklärungen für die GUI."""
    mod = _load_limits_module()
    data = mod.describe()
    data["file"] = str(LIMITS_FILE)
    log.debug("automat_limits gelesen: %s",
              {k: v["value"] for k, v in data["limits"].items()})
    return data


def save_limits(new_values: dict) -> dict:
    """Validiert und speichert die Limits atomar. Gibt den gespeicherten Stand zurück.

    Unbekannte Schlüssel werden verworfen, jeder Wert wird auf seinen gültigen Bereich
    geklemmt (gleiche Regeln wie im Automaten — `limits._clamp`). Der Automat übernimmt
    die neuen Werte beim nächsten Tick (max. 5 Minuten).
    """
    mod = _load_limits_module()
    if not isinstance(new_values, dict):
        raise ValueError("Erwarte ein JSON-Objekt mit den Limit-Werten")

    unknown = [k for k in new_values if k not in mod.SPEC]
    if unknown:
        log.warning("automat_limits: unbekannte Schlüssel ignoriert: %s", unknown)

    current = mod.load()
    out = dict(current)
    changed = {}
    for key in mod.SPEC:
        if key not in new_values:
            continue
        clamped = mod._clamp(key, new_values[key])
        if clamped != current.get(key):
            changed[key] = (current.get(key), clamped)
        out[key] = clamped

    # Parallelität nie über der harten Obergrenze
    for key in ("parallel_day", "parallel_night"):
        if out[key] > out["max_parallel"]:
            log.debug("automat_limits: %s auf max_parallel=%s gedeckelt", key, out["max_parallel"])
            out[key] = out["max_parallel"]

    write_json_atomic(LIMITS_FILE, out)
    log.info("automat_limits gespeichert: %s (geändert: %s)", out,
             {k: f"{a}→{b}" for k, (a, b) in changed.items()} or "nichts")
    return {"status": "ok", "limits": out,
            "changed": {k: {"from": a, "to": b} for k, (a, b) in changed.items()}}


def reset_limits() -> dict:
    """Setzt alle Werte auf die Code-Defaults zurück (Datei wird entfernt)."""
    mod = _load_limits_module()
    try:
        LIMITS_FILE.unlink()
        log.info("automat_limits: %s gelöscht → Defaults aktiv", LIMITS_FILE)
    except FileNotFoundError:
        log.debug("automat_limits: %s existierte nicht", LIMITS_FILE)
    return {"status": "ok", "limits": mod.load()}

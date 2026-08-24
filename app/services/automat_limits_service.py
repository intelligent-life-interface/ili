"""Drossel-Limits des Kanban-Automaten lesen/schreiben (für /automat.html → „⚙️ Drossel").

Die Werte liegen in `automat_limits.json` neben dieser Anwendung; der Automat
(`~/containers/kanban-automat/`) liest dieselbe Datei bei jedem Tick.

Bewusst KEINE zweite Kopie der Grenzwerte hier: die Spezifikation (Default, min, max,
Beschreibung je Stellschraube) wird aus dem `limits.py` des Automaten geladen, oder
bei Fehlschlag aus einem eingebauten Fallback (beim Paketieren ohne Automat-Binaries).
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
from types import ModuleType

from app.storage.atomic_write import write_json_atomic

log = logging.getLogger("dashboard.services.automat_limits")

AUTOMAT_DIR = Path(os.getenv("AUTOMAT_DIR", str(Path.home() / "containers/kanban-automat")))
LIMITS_FILE = Path(__file__).resolve().parents[2] / "automat_limits.json"

_limits_mod = None


class AutomatUnavailable(RuntimeError):
    """Das limits.py des Automaten ist nicht ladbar (Ordner fehlt/defekt)."""


def _create_fallback_module() -> ModuleType:
    """Fallback-Limits, wenn limits.py nicht existiert (z.B. im Paket)."""
    mod = ModuleType("automat_limits_fallback")

    # Spezifikation (key -> (Default, Env-Variable, min, max, Beschreibung))
    mod.SPEC = {
        "max_starts_per_day": (24, "AUTOMAT_MAX_STARTS_PER_DAY", 1, 500,
                               "Wie viele Worker-Starts pro Tag insgesamt erlaubt sind (hartes Limit)."),
        "max_parallel":       (3,  "AUTOMAT_MAX_PARALLEL", 1, 10,
                               "Absolute Obergrenze gleichzeitig laufender Worker."),
        "parallel_day":       (2,  "AUTOMAT_PARALLEL_DAY", 1, 10,
                               "Gleichzeitige Worker im Tagfenster (schont das Kontingent tagsüber)."),
        "parallel_night":     (3,  "AUTOMAT_PARALLEL_NIGHT", 1, 10,
                               "Gleichzeitige Worker im Nachtfenster."),
        "board_cooldown_s":   (1800, "AUTOMAT_BOARD_COOLDOWN_S", 0, 86400,
                               "Wartezeit, bis dasselbe Board erneut gestartet werden darf (Crash-Schleifen-Schutz)."),
        "max_new_starts_per_tick": (2, "AUTOMAT_MAX_NEW_STARTS_PER_TICK", 1, 10,
                               "Höchstens so viele NEUE Worker-Starts pro 5-Min-Tick."),
        "max_refunds_per_day": (6, "AUTOMAT_MAX_REFUNDS_PER_DAY", 0, 100,
                                "Wie oft ein No-Op-Start pro Tag zurückerstattet werden darf."),
        "noop_refund_s":      (300, "AUTOMAT_NOOP_REFUND_S", 0, 3600,
                               "Worker, die kürzer laufen, gelten als No-Op und werden zurückerstattet."),
        "worker_timeout_s":   (7200, "AUTOMAT_WORKER_TIMEOUT_S", 300, 43200,
                               "Ab dieser Laufzeit gilt ein Worker als hängend und wird aufgeräumt."),
        "max_card_fails":     (3, "AUTOMAT_MAX_CARD_FAILS", 0, 50,
                               "Nach so vielen No-Op-Läufen IN FOLGE wird eine Karte automatisch geparkt."),
        "fable_enabled":      (0, "AUTOMAT_FABLE_ENABLED", 0, 1,
                               "Fable-Optimierung an (1) / aus (0)."),
        "fable_max_runs_per_day": (1, "AUTOMAT_FABLE_MAX_RUNS_PER_DAY", 0, 10,
                                  "Wie viele Fable-Optimierläufe pro Tag maximal."),
        "batch_enabled":      (0, "AUTOMAT_BATCH_ENABLED", 0, 1,
                               "Batch-API-Pfad an (1) / aus (0)."),
        "batch_max_in_flight": (1, "AUTOMAT_BATCH_MAX_IN_FLIGHT", 1, 10,
                                "Wie viele Batches gleichzeitig laufen dürfen."),
        "batch_max_requests_per_tick": (20, "AUTOMAT_BATCH_MAX_REQUESTS_PER_TICK", 1, 500,
                                        "Höchstzahl Karten-Vorschläge pro Submit."),
        "batch_max_output_tokens": (2000, "AUTOMAT_BATCH_MAX_OUTPUT_TOKENS", 256, 32000,
                                    "Max. Output-Tokens je Karten-Vorschlag."),
    }

    def _clamp(key: str, value):
        """Wert auf den plausiblen Bereich klemmen."""
        spec = mod.SPEC.get(key)
        if not spec or len(spec) < 4:
            return value
        try:
            v = int(value)
            return max(spec[2], min(spec[3], v))
        except (ValueError, TypeError):
            return spec[0]

    def load() -> dict:
        """Lade Limits aus JSON, oder Defaults mit Env-Overrides."""
        result = {}
        for key, spec in mod.SPEC.items():
            default = spec[0]
            env_var = spec[1]
            env_val = os.getenv(env_var)
            if env_val:
                try:
                    result[key] = _clamp(key, int(env_val))
                except ValueError:
                    result[key] = default
            else:
                result[key] = default

        # Datei überschreibt Env
        if LIMITS_FILE.exists():
            try:
                file_data = json.loads(LIMITS_FILE.read_text())
                for key, val in file_data.items():
                    if key in mod.SPEC:
                        result[key] = _clamp(key, val)
            except Exception as e:
                log.warning("automat_limits: %s nicht lesbar: %s, nutze Defaults", LIMITS_FILE, e)
        return result

    def describe() -> dict:
        """Aktuelles + Grenzen + Erklärung."""
        result = {"limits": {}}
        current = load()
        for key, spec in mod.SPEC.items():
            result["limits"][key] = {
                "value": current.get(key, spec[0]),
                "min": spec[2],
                "max": spec[3],
                "description": spec[4]
            }
        return result

    mod._clamp = _clamp
    mod.load = load
    mod.describe = describe
    log.debug("automat_limits: Fallback-Modul erstellt (%d Stellschrauben)", len(mod.SPEC))
    return mod


def _load_limits_module():
    """limits.py des Automaten als Modul laden, oder Fallback."""
    global _limits_mod
    if _limits_mod is not None:
        return _limits_mod

    path = AUTOMAT_DIR / "limits.py"
    if path.exists():
        try:
            spec = importlib.util.spec_from_file_location("automat_limits_spec", path)
            if spec is None or spec.loader is None:
                log.warning("automat_limits: %s nicht ladbar, nutze Fallback", path)
                _limits_mod = _create_fallback_module()
                return _limits_mod
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            log.debug("automat_limits: %s geladen (%d Stellschrauben)", path, len(mod.SPEC))
            _limits_mod = mod
            return mod
        except Exception as e:
            log.warning("automat_limits: %s nicht ladbar: %s, nutze Fallback", path, e)
    else:
        log.debug("automat_limits: %s nicht gefunden, nutze Fallback", path)

    _limits_mod = _create_fallback_module()
    return _limits_mod


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

"""Drossel-Limits des Kanban-Automaten — zentral, zur Laufzeit änderbar.

Quelle der Wahrheit ist die JSON-Datei `~/containers/dashboard/automat_limits.json`,
damit die Werte über die Dashboard-GUI (/automat.html → „⚙️ Drossel") angepasst werden
können, ohne systemd-Unit-Edit und `daemon-reload`.

Vorrang: Datei > Environment (AUTOMAT_*) > Default. Jeder Tick ist ein frischer
oneshot-Prozess (Timer alle 5 min), darum reicht Laden beim Import — eine Änderung in
der GUI greift spätestens beim nächsten Tick.

Jeder Wert wird beim Laden auf einen plausiblen Bereich geklemmt (siehe SPEC), damit ein
Vertipper in der GUI den Automaten nicht in eine Crash-Schleife oder Vollgas schickt.
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("automat.limits")

LIMITS_FILE = Path(
    os.getenv("AUTOMAT_LIMITS_FILE", str(Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "automat_limits.json"))
)

# key -> (Default, Env-Variable, min, max, Beschreibung für die GUI)
SPEC = {
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
                           "Höchstens so viele NEUE Worker-Starts pro 5-Min-Tick (über alle Boards, "
                           "dev+review+fable). Verteilt Lastspitzen über mehrere Ticks statt die ganze "
                           "freie Kapazität auf einen Schlag zu nutzen — senkt das Risiko, das "
                           "Abo-Session-Limit durch einen Start-Burst schneller zu erreichen."),
    "max_refunds_per_day": (6, "AUTOMAT_MAX_REFUNDS_PER_DAY", 0, 100,
                            "Wie oft ein No-Op-Start pro Tag zurückerstattet werden darf."),
    "noop_refund_s":      (300, "AUTOMAT_NOOP_REFUND_S", 0, 3600,
                           "Worker, die kürzer laufen, gelten als No-Op und werden zurückerstattet."),
    "worker_timeout_s":   (7200, "AUTOMAT_WORKER_TIMEOUT_S", 300, 43200,
                           "Ab dieser Laufzeit gilt ein Worker als hängend und wird aufgeräumt."),
    "max_card_fails":     (3, "AUTOMAT_MAX_CARD_FAILS", 0, 50,
                           "Nach so vielen No-Op-Läufen IN FOLGE wird eine Karte automatisch "
                           "geparkt (Grund: kommt nicht voran). 0 = Automatik aus. Zähler wird "
                           "bei jedem erfolgreichen Lauf der Karte zurückgesetzt."),
    # Hier standen am 06.08.26 kurzzeitig `auto_finish_enabled`/`auto_finish_grace_s`
    # (Modul auto_finish.py). Beides ist entfallen: der Zustand „Automat ist durch" wird
    # im Dashboard aus den Kartenzahlen ABGELEITET und nirgends gespeichert — kein
    # Schalter nötig. Details: CLAUDE.md, Abschnitt „Status der Auto-Entwicklung".
    # Fable-Optimier-Modus (teures Modell für freien Wochen-Budget-Kopf, s. fable_gate.py)
    "fable_enabled":      (0, "AUTOMAT_FABLE_ENABLED", 0, 1,
                           "Fable-Optimierung an (1) / aus (0). Nutzt freien Wochen-Budget-Kopf für "
                           "projektweite Verbesserungen mit dem stärksten Modell — nur bei Boards mit "
                           "Opt-in (🧬-Toggle)."),
    "fable_max_runs_per_day": (1, "AUTOMAT_FABLE_MAX_RUNS_PER_DAY", 0, 10,
                              "Wie viele Fable-Optimierläufe pro Tag maximal (harte Deckelung gegen "
                              "Budget-Leerlauf)."),
    # Batch-API-Pfad (echtes API-Guthaben, parallel zum Abo, s. batch.py/batch_gate.py).
    # Erzeugt pro Karte einen Entwicklungs-VORSCHLAG (Text) über die Message Batches API
    # (async, 50% günstiger) — kein Datei-Editieren, das bleibt beim Abo.
    "batch_enabled":      (0, "AUTOMAT_BATCH_ENABLED", 0, 1,
                           "Batch-API-Pfad an (1) / aus (0). Erzeugt für Boards mit Opt-in (📦-Toggle) "
                           "über Nacht günstige Karten-Vorschläge via Message Batches API. "
                           "Kostet echtes API-Guthaben — Kostenlimit pro Projektgruppe in batch_budget.json."),
    "batch_max_in_flight": (1, "AUTOMAT_BATCH_MAX_IN_FLIGHT", 1, 10,
                            "Wie viele Batches gleichzeitig laufen dürfen (async, kein Worker-Slot). "
                            "Neue Karten werden erst submittet, wenn weniger als so viele Batches offen sind."),
    "batch_max_requests_per_tick": (20, "AUTOMAT_BATCH_MAX_REQUESTS_PER_TICK", 1, 500,
                                    "Höchstzahl Karten-Vorschläge (Requests) pro Submit — begrenzt die "
                                    "Grösse eines einzelnen Batches."),
    "batch_max_output_tokens": (2000, "AUTOMAT_BATCH_MAX_OUTPUT_TOKENS", 256, 32000,
                                "Max. Output-Tokens je Karten-Vorschlag (deckelt Kosten pro Request "
                                "und dient als Aufwand-Schätzung fürs Gruppen-Budget)."),
}


def _clamp(key: str, value) -> int:
    default, _env, lo, hi, _desc = SPEC[key]
    try:
        v = int(value)
    except (TypeError, ValueError):
        logger.debug("limits: %s=%r nicht ganzzahlig -> Default %s", key, value, default)
        return default
    if v < lo or v > hi:
        clamped = max(lo, min(hi, v))
        logger.warning("limits: %s=%s ausserhalb [%s..%s] -> auf %s geklemmt", key, v, lo, hi, clamped)
        return clamped
    return v


def load() -> dict:
    """Liest die Limits (Datei > Env > Default) und klemmt sie auf gültige Bereiche."""
    raw = {}
    try:
        raw = json.loads(LIMITS_FILE.read_text())
        if not isinstance(raw, dict):
            logger.warning("limits: %s enthält kein Objekt -> ignoriert", LIMITS_FILE)
            raw = {}
    except FileNotFoundError:
        logger.debug("limits: %s existiert nicht -> Env/Defaults", LIMITS_FILE)
    except Exception as e:
        logger.warning("limits: %s nicht lesbar (%s) -> Env/Defaults", LIMITS_FILE, e)

    out = {}
    for key, (default, env, _lo, _hi, _desc) in SPEC.items():
        if key in raw:
            out[key] = _clamp(key, raw[key])
        else:
            out[key] = _clamp(key, os.getenv(env, default))

    # parallel_day/night dürfen die harte Obergrenze nie überschreiten
    for key in ("parallel_day", "parallel_night"):
        if out[key] > out["max_parallel"]:
            logger.debug("limits: %s=%s > max_parallel=%s -> gedeckelt",
                         key, out[key], out["max_parallel"])
            out[key] = out["max_parallel"]

    logger.debug("limits geladen: %s", out)
    return out


def describe() -> dict:
    """Metadaten für die GUI: aktueller Wert + Grenzen + Erklärung je Stellschraube."""
    current = load()
    return {
        "file": str(LIMITS_FILE),
        "limits": {
            key: {
                "value": current[key],
                "default": default,
                "min": lo,
                "max": hi,
                "env": env,
                "description": desc,
            }
            for key, (default, env, lo, hi, desc) in SPEC.items()
        },
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    print(json.dumps(describe(), ensure_ascii=False, indent=2))

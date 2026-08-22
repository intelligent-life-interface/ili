"""Fable-Optimier-Modus: ein ganzes Projekt an das stärkste Modell (Fable 5) geben, damit
es Verbesserungen vorschlägt — bezahlt aus Wochen-Budget-Kopf, der sonst verfällt.

Gesteuert vom Orchestrator (Schritt (c) in tick()): NUR wenn `fable_gate.check()` grünes
Licht gibt und ein freier Slot da ist. Auswahl der Projekte:
  * Opt-in pro Board über das Manifest-Feld `fable_optimize: true` (analog zu `auto`).
  * Aus den freigegebenen wird das am längsten nicht optimierte gewählt (Rotation,
    State `state/fable_last.json`), höchstens eins pro Tick.

Wirkung (24.07.26): Fable **schlägt vor** (neue Karten via automat_cli) und darf nur
**Test-Deploys** (test_first-Mechanik), nie Prod anfassen. Kein Direkt-Commit in Prod.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import automat_lib as lib
from automat_lib import logger

LAST_FILE = lib.STATE_DIR / "fable_last.json"


def opt_in_boards(boards: list[dict]) -> list[dict]:
    """Boards mit Manifest-Flag fable_optimize==true (und nicht ausgeschlossen)."""
    return [b for b in boards if b.get("fable_optimize") is True and b.get("id")]


def _last_map() -> dict:
    try:
        d = json.loads(LAST_FILE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def mark_optimized(slug: str) -> None:
    try:
        d = _last_map()
        d[slug] = datetime.now(timezone.utc).isoformat()
        LAST_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        logger.debug("fable_optimize: %s als optimiert vermerkt", slug)
    except Exception as e:
        logger.warning("fable_optimize: mark_optimized(%s) fehlgeschlagen: %s", slug, e)


def pick_board(boards: list[dict], busy: set[str], self_boards: set[str]) -> dict | None:
    """Das am längsten nicht optimierte Opt-in-Board, das gerade frei ist."""
    cands = [b for b in opt_in_boards(boards)
             if b.get("id") not in busy and b.get("id") not in self_boards]
    if not cands:
        return None
    last = _last_map()
    # nie optimierte (kein Eintrag) zuerst, dann ältester Zeitstempel
    cands.sort(key=lambda b: last.get(b["id"], ""))
    choice = cands[0]
    logger.debug("fable_optimize: Kandidaten=%s -> gewählt %s (zuletzt %s)",
                 [b["id"] for b in cands], choice["id"], last.get(choice["id"], "nie"))
    return choice


def build_prompt(slug: str, workdir: Path, cli_path: str) -> str:
    """Auftrag für den Fable-Optimier-Worker. Fable sieht das ganze Projekt, schlägt aber
    nur vor (Karten) und deployt höchstens als Testversion — kein Prod-Eingriff."""
    return f"""Du bist ein sehr erfahrener Software-Architekt und arbeitest mit dem stärksten
verfügbaren Modell (Fable 5) am Projekt '{slug}' (Verzeichnis: {workdir}).

Dies ist ein OPTIMIER-Lauf, kein normaler Karten-Auftrag: Du bekommst absichtlich das ganze
Projekt, weil freies Wochen-Budget sonst verfällt. Nutze deine Stärke für eine gründliche,
projektweite Analyse — aber halte dich strikt an die Grenzen unten.

AUFGABE
1. Lies die CLAUDE.md des Projekts und verschaffe dir einen Überblick über Struktur, Code
   und offene Kanban-Karten (`python3 {cli_path} show --board {slug}`).
2. FOKUS (16.08.26): **Software-Architektur und Security.** Erarbeite die 3–7
   WIRKSAMSTEN Befunde — Architektur (Schichtentrennung, Modul-Schnitt, Doppelspurigkeiten,
   Robustheit, Testbarkeit) und Security (Secrets-Handling, Exposure, Input-Validierung,
   Locking/Race-Conditions). Qualität vor Menge. Massstab sind die Haus-Konventionen
   (Skills `architektur-review` / `security-konventionen` / `backend-architektur`).
3. KEINE FANTASIE: Jeder Befund muss im Code VERIFIZIERT sein und den Beleg als
   `Datei:Zeile` nennen. Findest du nichts Substanzielles, lege KEINE Karte an —
   lieber 2 echte Befunde als 7 erfundene.
4. DEDUP-PFLICHT: Prüfe VOR dem Anlegen, welche `[{slug}]`-Karten auf den Sammel-Boards
   schon existieren (`python3 {cli_path} show --board code-architektur` und
   `python3 {cli_path} show --board security`) — bereits gemeldete Befunde NICHT erneut
   anlegen, auch nicht umformuliert. Nichts Neues gefunden → keine Karte, Lauf sauber beenden.
5. Lege JEDE Verbesserung als EIGENE Kanban-Karte an — NICHT im Projekt-Board, sondern
   in den zentralen Sammel-Projekten (16.08.26):
   * Architektur-Befunde → Board `code-architektur`
   * Security-Befunde  → Board `security`
   `python3 {cli_path} note --board code-architektur --card <NEU> ...` bzw.
   `python3 {cli_path} note --board security --card <NEU> ...`
   Karten-Format (self-contained, ein späterer Worker kennt dein Projekt nicht):
   * Titel: `[{slug}] <Problem in einem Satz>`
   * Beschreibung: **Problem** (was + warum problematisch, Beleg `Datei:Zeile` mit
     ABSOLUTEM Pfad unter {workdir}) · **Lösung** (konkreter Umsetzungsweg, Schritte) ·
     **Akzeptanzkriterium** (prüfbarer Befehl).
   Wenn du eine Idee direkt umsetzt (siehe unten), vermerke das in derselben Karte
   (Zusatz-note mit Test-URL/Diff-Zusammenfassung).

GRENZEN (strikt)
- Du DARFST Code ändern, aber Änderungen gehen NIE direkt in Produktion. Deploye ausschließlich
  als TESTVERSION über die test_first-Mechanik (Container-Manager :8810 `test-deploy`,
  `<name>-test`, Ports +10000) — genau wie im Abschnitt „Testversion-Pflicht" der Projekt- bzw.
  kanban-automat-CLAUDE.md beschrieben. Kein Prod-Restart, kein Prod-Build.
- Bei Projekten ohne deploybaren Container: nur Vorschläge als Karten, keine Live-Änderung.
- Entscheidungen, die der Manager treffen muss: als EINE Entscheidungskarte parkieren
  (`python3 {cli_path} decision ...`), Board blockiert dann bis zu seiner Antwort.
- Fasse dich in Commits/Karten präzise. Erfinde nichts — prüfe, was wirklich im Code steht.

Am Ende: kurze Zusammenfassung, welche Karten du angelegt und was du (falls überhaupt) als
Testversion deployt hast.

[Loop: kanban-automat-fable]
"""

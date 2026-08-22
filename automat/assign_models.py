#!/usr/bin/env python3
"""assign_models — schlägt jedem Kanban ein Soll-Modell vor und schreibt es ins Manifest.

Einmal-Analyse (23.07.2026: „sollte entscheiden welches Modell ideal ist").
Danach ist die Zuordnung im Dashboard pro Projekt änderbar (project.html → 🧠 Modell)
— dieses Skript überschreibt eine von Hand gesetzte Wahl nur mit `--force`.

Heuristik (bewusst deterministisch, kein LLM — nachvollziehbar und gratis):

  Stufe 2 (Opus 4.8)  wenn das Projekt Code hat UND heikel/komplex ist:
                      Infrastruktur/Container/DB/Netz-Themen, Geld/Recht/Gesundheitsdaten,
                      viele offene Karten (>12) oder viel Code (>3000 Zeilen).
  Stufe 1 (Sonnet 5)  Standard: alles mit Code.
  Stufe 0 (Haiku 4.5) Boards ohne Code: reine Sammel-/Doku-/Ideen-/Lern-Boards.

Stufe 3 (Fable 5) vergibt das Skript NIE — die kostet ein Mehrfaches und wird nur
von Hand für sehr lange autonome Läufe gesetzt.

Aufruf:
  python3 assign_models.py                 # Vorschlag anzeigen (ändert nichts)
  python3 assign_models.py --apply         # nur Boards OHNE eigene Wahl setzen
  python3 assign_models.py --apply --force # auch von Hand gesetzte überschreiben
  python3 assign_models.py --board <slug>  # nur ein Board ansehen
"""
from __future__ import annotations

import os
import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import automat_lib as lib
import models

logger = lib.logger
RESOLVER = Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "projterm_prepare.py"

# Themen, bei denen ein Fehler teuer/schwer reparierbar ist -> stärkeres Modell.
# NUR gegen Board-Metadaten (Name/Beschreibung/Tags) geprüft, NIE gegen die CLAUDE.md:
# die enthält bei jedem Projekt die Haus-Boilerplate (Container/systemd/Caddy) und
# würde sonst pauschal jedes Board auf Opus heben.
# Ganze Wörter (Wortgrenzen) — "steuer" darf nicht in "Steuerung" matchen.
HEIKEL = (r"produktiv", r"infrastruktur", r"backup", r"security", r"sicherheit",
          r"passw\w*", r"secrets?", r"tokens?", r"zahlung\w*", r"rechnung\w*",
          r"miete?\w*", r"immobilien\w*", r"steuererkl\w*", r"finanz\w*", r"buchhaltung",
          r"ekg", r"medikament\w*", r"blutdruck", r"diagnose\w*",
          r"heizung\w*", r"w[äa]rmepumpe\w*", r"stromz[äa]hler\w*",
          r"migration", r"datenbank-?schema", r"produktions?daten")
# Boards, die typischerweise gar keinen Code haben -> günstige Stufe reicht
TEXT_KATEGORIEN = ("ideen", "lernen", "buero", "arbeit")
CODE_SUFFIXE = (".py", ".js", ".ts", ".sh", ".html", ".css", ".sql", ".yaml", ".yml")
# Wörter in Beschreibung/CLAUDE.md, die auf Programmierarbeit hindeuten — wichtig, weil
# viele ~/Projekte/<slug>-Ordner NUR Doku enthalten und der echte Code woanders liegt
# (z.B. heartbeat: Doku in ~/Projekte/heartbeat, Code in ~/containers/HeartBeat).
CODE_SIGNAL = ("container", "port ", "port:", "service", "systemd", "python", "skript",
               "script", "api", "fastapi", "endpoint", "podman", "repo", "commit",
               "datenbank", "pipeline", "timer", "bot", "web-ui", "webgui", "frontend")


def _workdir(slug: str) -> Path | None:
    """Projektordner wie der Automat ihn auflöst (projterm_prepare --resolve)."""
    try:
        out = subprocess.run([sys.executable, str(RESOLVER), "--resolve", slug],
                             capture_output=True, text=True, timeout=20)
        d = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
        p = Path(d) if d else None
        return p if p and p.is_dir() and p != Path.home() else None
    except Exception as e:
        logger.debug("assign_models: workdir(%s) nicht auflösbar: %s", slug, e)
        return None


def _code_umfang(d: Path | None) -> tuple[int, int]:
    """(Anzahl Code-Dateien, Zeilen) — grob, max. 400 Dateien, ohne .git/venv/node_modules."""
    if not d:
        return (0, 0)
    files = 0
    lines = 0
    for p in d.rglob("*"):
        if files >= 400:
            break
        if not p.is_file() or p.suffix.lower() not in CODE_SUFFIXE:
            continue
        if any(part in (".git", "venv", ".venv", "node_modules", "state", "__pycache__")
               for part in p.parts):
            continue
        files += 1
        try:
            lines += sum(1 for _ in p.open("r", errors="ignore"))
        except Exception:
            pass
    return (files, lines)


def _offene_karten(slug: str) -> int:
    try:
        return len(lib.actionable_cards(lib.get_board(slug)))
    except Exception as e:
        logger.debug("assign_models: Karten(%s) nicht lesbar: %s", slug, e)
        return 0


def vorschlag(entry: dict) -> tuple[str, str]:
    """(Modell, Begründung) für einen Manifest-Eintrag."""
    slug = entry.get("id", "")
    # meta = nur Board-Metadaten (für die Heikel-Prüfung), text = meta + CLAUDE.md
    # (für die Frage „gibt es hier überhaupt Programmierarbeit?").
    meta = " ".join(str(entry.get(k, "")) for k in ("id", "name", "description", "category"))
    meta += " " + " ".join(str(t) for t in (entry.get("tags") or []))
    meta = meta.lower()
    text = meta
    d = _workdir(slug)
    files, lines = _code_umfang(d)
    karten = _offene_karten(slug)
    # CLAUDE.md des Projekts mitlesen: dort steht, ob es um einen Container/Service geht,
    # auch wenn im aufgelösten Ordner selbst nur Doku liegt.
    if d and (d / "CLAUDE.md").is_file():
        try:
            text += " " + (d / "CLAUDE.md").read_text("utf-8", errors="ignore")[:4000].lower()
        except Exception as e:
            logger.debug("assign_models: CLAUDE.md(%s) nicht lesbar: %s", slug, e)
    heikel = [m.group(0) for m in (re.search(rf"\b{p}\b", meta) for p in HEIKEL) if m]
    code_hinweis = [w for w in CODE_SIGNAL if w in text]
    hat_code = files > 0 or bool(code_hinweis)

    if not hat_code:
        return ("claude-haiku-4-5",
                f"kein Code und keine Technik-Hinweise ({d.name if d else 'kein Ordner'}) — "
                "Sammel-/Doku-/Notiz-Board")
    if heikel or lines > 3000 or karten > 12:
        gruende = []
        if heikel:
            gruende.append("heikles Thema: " + ", ".join(heikel[:3]))
        if lines > 3000:
            gruende.append(f"{lines} Zeilen Code")
        if karten > 12:
            gruende.append(f"{karten} offene Karten")
        return ("claude-opus-4-8", "; ".join(gruende))
    quelle = (f"{files} Code-Dateien / {lines} Zeilen" if files
              else "Code liegt ausserhalb des Doku-Ordners (" + ", ".join(code_hinweis[:3]) + ")")
    return ("claude-sonnet-5", f"{quelle}, {karten} offene Karten")


def _patch(slug: str, model: str) -> bool:
    body = json.dumps({"model": model}).encode()
    url = f"{lib.DASHBOARD_URL}/boards/{urllib.parse.quote(slug)}"
    req = urllib.request.Request(url, data=body, method="PATCH",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        logger.info("assign_models: %s -> %s", slug, model)
        return True
    except Exception as e:
        logger.error("assign_models: PATCH %s fehlgeschlagen: %s", slug, e)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Soll-Modelle für die Kanban-Boards")
    ap.add_argument("--apply", action="store_true", help="Vorschläge ins Manifest schreiben")
    ap.add_argument("--force", action="store_true", help="auch bestehende Wahl überschreiben")
    ap.add_argument("--board", help="nur dieses Board")
    ap.add_argument("--all", action="store_true", help="alle Boards, nicht nur auto:true")
    a = ap.parse_args()

    boards = lib.list_boards_all()
    if a.board:
        boards = [b for b in boards if b.get("id") == a.board]
    elif not a.all:
        boards = [b for b in boards if b.get("auto") is True]
    print(f"{len(boards)} Board(s) werden bewertet …\n")

    zaehler: dict[str, int] = {}
    for b in sorted(boards, key=lambda x: x.get("id", "")):
        slug = b.get("id")
        aktuell = b.get("model")
        neu, warum = vorschlag(b)
        zaehler[neu] = zaehler.get(neu, 0) + 1
        marker = "="
        if aktuell and aktuell != neu:
            marker = "≠" if not a.force else "→"
        elif not aktuell:
            marker = "→"
        print(f"{marker} {slug:40s} {models.label(neu):10s}"
              f"{'  (gesetzt: ' + models.label(aktuell) + ')' if aktuell else ''}\n"
              f"    {warum}")
        if a.apply and (a.force or not aktuell) and neu != aktuell:
            _patch(slug, neu)

    print("\nVerteilung: " + ", ".join(f"{models.label(m)}={n}" for m, n in
                                       sorted(zaehler.items(), key=lambda x: models.tier(x[0]))))
    if not a.apply:
        print("(Vorschau — mit --apply schreiben, --force überschreibt auch Handeinstellungen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

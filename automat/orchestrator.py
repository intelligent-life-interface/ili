#!/usr/bin/env python3
"""
orchestrator — Watchdog des Kanban-Automaten (Thin Wrapper).

Leitplanken (User, 16.07.26): "muss nicht schnell gehen, aber KONSTANT weiter" +
"Fragen werden parkiert, nach 5 min ohne Eingabe am nächsten Projekt gearbeitet" +
"mehrere Tasks können aktiv sein". Darum: 5-Minuten-Tick (parkierte Entscheidung
blockiert nur ihr Board, spätestens der nächste Tick startet ein anderes Projekt),
Parallelität 2 (Tag) / 3 (Nacht), Tages-Startlimit 24.

Ablauf je Tick (via kanban-automat.timer, alle 5 min):
  1. Globaler Lock (flock) — nie zwei Ticks gleichzeitig.
  2. Tote/hängende Worker aufräumen (Liveness via PID, Timeout).
  3. "Wird noch gearbeitet?" -> lebende Worker zählen. Sind es >= Kapazität: nichts tun.
  4. Drossel: Tageszeit-Fenster (aus ai_config.json budget_windows) bestimmt die
     erlaubte Parallelität; zusätzlich ein hartes Tages-Startlimit.
  5. Freie Auto-Boards (Manifest auto==true, nicht blockiert, ohne lebenden Worker)
     ihrer nächsten KARTEN-GRUPPE zuordnen (grouping.py: Ollama bündelt
     zusammengehörige Karten = KI-1-Stufe) und je einen headless Claude-Worker
     starten, der die ganze Gruppe in EINER Session abarbeitet (= KI 2).

WICHTIG: Worker laufen mit `claude -p ... --dangerously-skip-permissions` im
Projektordner = volle Autonomie. Darum NUR explizit freigegebene Boards (auto:true).
Sicherheits-Selbstausschluss: das eigene Board 'kanban-automat' wird nie automatisch
bearbeitet (kein autonomes Selbst-Editieren).

Die Logik liegt jetzt in separaten Modulen (Option A: 1 Funktion = 1 Datei):
  budget.py     — Kapazitäts-Management (capacity, starts_today, board_in_cooldown, ...)
  worker.py     — Worker-Start (reap, start_worker, start_review_worker, start_fable_worker)
  scheduler.py  — Planung & Tick (plan, tick)
  cli.py        — Kommandozeilen-Interface (status, main)

orchestrator.py = Thin Wrapper (nur Einstiegspunkt via sys.argv).

CLI:
  orchestrator.py --tick [--dry-run]   ein Watchdog-Durchlauf (Timer ruft das)
  orchestrator.py --status             aktueller Zustand (Worker, Auto-Boards)
"""
import sys

from cli import main

if __name__ == "__main__":
    sys.exit(main())

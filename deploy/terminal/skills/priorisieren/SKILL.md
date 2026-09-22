---
name: priorisieren
description: Reihenfolge-Entscheidungen auf den Kanban-Boards — was als Nächstes, was liegen bleibt, was raus. Enthält die Hausregeln (KI schlägt nur vor und überschreibt nie vom Menschen gesetzte Werte, echte vs. erfundene Deadlines, Eisenhower, pausiert/archiviert) und die vorhandenen Werkzeuge (prio_suggester, kanban-analyst, Wochenfrage). Nutze bei "was zuerst", "priorisieren", "was ist wichtig", "Reihenfolge", "womit anfangen", "Board aufräumen", "lohnt sich das noch".
---

# priorisieren — Reihenfolge auf den Boards

## Die harte Regel zuerst

**Vom Menschen gesetzte Werte werden NIE überschrieben und NIE zur Bewertung an eine KI
gegeben** — das gilt für `card.priority`, `eisenhower` und Kategorien. Eine KI stuft
ausschliesslich Karten **ohne** gesetzten Wert ein, und das Ergebnis ist ein
**Vorschlag zur Anzeige**, kein Schreibvorgang ins Board.

Wenn du unsicher bist, ob ein Wert vom Menschen oder von einer KI stammt: nicht anfassen.

## Werkzeuge statt Eigenbau

| Frage | Werkzeug |
|---|---|
| Prio-Vorschlag für ein Board | `~/containers/dashboard/prio_suggester.py` (read-only, bündelt einen Abo-Call, Fallback Heuristik) |
| „Was ist auf Board X offen/blockiert?" | Subagent **kanban-analyst** (eigenes Kontextfenster, gibt nur die verdichtete Antwort zurück) |
| Kanban-Status ändern (note/park/discard/done/decision) | `automat_cli.py` — nie Board-JSON selbst editieren |
| Duplikate & tote Boards | `kanban_dedup.py` (So 04:30, löscht nichts, meldet nur) |
| „Wo ging der Aufwand hin?" | `~/bin/aufwand-wochenfrage.py` (Mo 08:00, eine Karte in `home-stack`) |

Nie das komplette Kanban in den Kontext holen — immer nur die gebrauchten Teile.

## Wonach priorisiert wird

**1. Echte Termine schlagen alles.** Eine Deadline zählt nur, wenn sie real ist
(Behörde, Mietrecht, Steuer, ein wartender Mensch). Keine Deadlines erfinden, um
Dringlichkeit zu erzeugen — das entwertet die echten.

**2. Eisenhower für den Rest.** Wichtig/dringend als Kartenfeld, nicht als Bauchgefühl.
Wichtig = bringt das Projekt zum Ziel. Dringend = wird durch Warten schlechter.

**3. Kaputt vor neu.** Ein Dienst, der nicht läuft, schlägt jedes Feature. Prüfen,
ob etwas stillsteht, bevor Neues geplant wird:

```bash
systemctl --user list-timers --all | head -30      # inactive/dead bei enabled = Verdacht
journalctl --user -u <service> --since "-7d" | grep -i -m5 "error\|refused\|failed"
```

Ein Timer, der `enabled` ist, aber `Active: inactive (dead)` zeigt, läuft **nicht**.

**4. Aufwand gegen Ergebnis.** Viel Arbeit ohne sichtbares Resultat ist ein Signal zum
Umplanen, nicht zum Weitermachen. Die Wochenfrage montags stellt genau das.

**5. Token-Budget als Rahmen, nicht als Ziel.** Zwischen 10 und 22 Uhr höchstens 50 %
des Tagesbudgets, nachts bis 70 %. Teure Arbeit nach hinten, wenn sie warten kann.

## Was aus der Priorisierung herausfällt

- `status: pausiert` oder `archiviert` → Automat schweigt, Karte taucht in der
  Übersicht nicht auf. Das ist eine bewusste Entscheidung, kein Versehen — nicht
  „zur Sicherheit" reaktivieren.
- Karten in `done`/`review` sind raus, auch wenn der Titel offen klingt.
- Boards auf der Split-Blacklist (`home-stack`, `meine-aufgaben`, `ideen`, …) werden
  nicht automatisch zerlegt.

## Wenn eine Entscheidung an den Menschen geht

Nicht raten, nicht als offene Aufgabe parken: **Entscheidungskarte** mit klarer Frage
und Optionen anlegen — `automat_cli.py decision --board <board> --card <id> --question "<Frage>"
--options "A||B||C"`. Pro Board höchstens **eine** offene Entscheidungskarte — gibt es schon
eine, nur eine Notiz ergänzen (`automat_cli.py note ...`).

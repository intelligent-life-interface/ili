---
name: backend-architektur
description: Wie Backend-/Service-Code im Home-Stack sauber strukturiert wird — Schichtentrennung (Route → Service → Data), Datei-/Modul-Schnitt, einheitlicher config.env-Zugriff, Debug-Logging, Fehler-/Retry-/Timeout-Muster und die Wahl Event/MQTT vs. Polling vs. Cron. Enthält code-check.sh (OK/WARN/FAIL wie architektur-review: Dateigrösse, Debug-Logging, deutsche Bezeichner, hartkodierte Pfade/Secrets, Tests). Nutze bei allem, was einen FastAPI-/Python-Service, API-Endpoints, Business-Logik, Datenzugriff, Hintergrund-Jobs, Scheduling, systemd-Unit oder „der Code/Service ist unsauber/aufräumen" betrifft — BEVOR du Service-Code schreibst oder umbaust. NICHT für die Frontend-Ebene (dafür frontend-architektur) und NICHT für die Stack-Einordnung eines fertigen Projekts (dafür architektur-review).
---

# backend-architektur — sauberer Service-Aufbau

Diese Regeln sagen, **wie** der Code *innerhalb* eines Dienstes strukturiert wird.
Die **Stack-Einordnung** (DB-Wahl, Exposure, Datenfluss, Betrieb) macht
`architektur-review`; hier wird nichts davon dupliziert, nur verwiesen.

## 0. Prüfen statt nur lesen

```bash
~/.claude/skills/backend-architektur/code-check.sh <projektpfad>
~/.claude/skills/backend-architektur/code-check.sh --all [--json]
```

Ausgabe: OK/WARN/FAIL wie architektur-review — Dateigrösse (>500 Zeilen), Debug-Logging
(logging.basicConfig/getLogger), deutsche Bezeichner (Heuristik), hartkodierte Home-Pfade,
hartkodierte Secrets (FAIL) und ob Tests vorhanden sind. `--json` für den Kanban-Automat.

## 1. Schichtentrennung (verbindlich)

**Route → Service → Data.** Drei Verantwortlichkeiten, nicht vermischt:

| Schicht | Aufgabe | Regel |
|---|---|---|
| Route/Handler (`main.py`/`routes/`) | HTTP annehmen, validieren, Antwort formen | **keine** Business-Logik, **kein** direktes SQL |
| Service/Logik | Rechnen, Entscheiden, Orchestrieren | kennt kein HTTP, keine Requests/Responses |
| Data/Repository | DB-/Datei-/API-Zugriff | einzige Schicht, die SQL/Storage kennt |

- Ein Route-Handler, der SQL absetzt und nebenbei rechnet, ist die häufigste
  Unsauberkeit — trenne das.
- **LLM soll nicht rechnen:** deterministische Berechnungen gehören in Code
  (Ground Truth), nicht in einen Modell-Prompt.

## 2. Datei- & Modul-Schnitt (verbindlich)

- **Ein Skript/Modul = eine Funktion/Verantwortung.** Pro Datei ein klarer Zweck.
- **Dateien < 500 Zeilen.** Wird eine Datei grösser, ist das ein Schnitt-Signal,
  kein Grund für ein Riesenfile.
- Grosse Dateien nie komplett lesen/schreiben — gezielt mit `grep`/`sed`/Offset
  arbeiten (Token- und Übersichts-Gründe).
- **Code Englisch** (Bezeichner, neue Kommentare, Docstrings); bestehende deutsche
  Kommentare nicht übersetzen.

## 3. Config & Secrets (verbindlich)

- **Alle Secrets aus `~/config.env`** laden — einheitlich über eine kleine
  Config-Ladefunktion, nicht verstreut per `os.environ` überall. Nie ein Secret
  loggen oder im Klartext ausgeben (Details: Skill `security-konventionen`).
- Nicht-geheime Config (Ports, Pfade) klar von Secrets trennen.

## 4. Debug-Logging (verbindlich)

- **Immer gute Debug-Logs.** Jeder Service loggt Start, wichtige Zustandswechsel,
  Fehler mit Kontext. Secrets dabei maskieren (`token=***`).
- Logs sollen im Log-Viewer (8899) brauchbar landen; strukturiert genug, um einen
  Fehler ohne Rätselraten zu finden.

## 5. Fehler / Retry / Timeout

- Externe Aufrufe (HTTP, MQTT, DB) **immer mit Timeout**; kein unbegrenztes Warten.
- Transiente Fehler mit begrenztem Retry + Backoff; permanente Fehler klar
  melden, nicht stumm schlucken.
- Health-Endpoint bereitstellen, von aussen prüfbar.

## 6. Event vs. Polling vs. Cron

| Wenn … | dann … |
|---|---|
| Sensordaten/Nachrichten pushen laufend rein | **Event/MQTT** (1884 → Telegraf → InfluxDB), kein Eigenbau-Poll |
| Externer Zustand ändert sich unregelmässig, keine Push-Quelle | **Polling** mit vernünftigem Intervall + Timeout |
| Feste Zeit, planbar (Reports, Scans, Exports) | **systemd-Timer / Cron** |

## 7. Betrieb (Kurz — Details in architektur-review)

- Rootless Podman, **systemd `--user`-Unit ohne `User=`-Direktive** (sonst
  `216/GROUP`), `WantedBy=default.target`, `enable` gesetzt → übersteht Reboot.
- KI-Routing (Ollama vs. Claude), DB-Wahl (SQLite/DuckDB pro Projekt, InfluxDB nur
  Zeitreihen), Exposure → gehören in `architektur-review`/`planen`, hier nur der Zeiger.

## Verweise (nicht duplizieren)

- Neues Projekt-Gerüst → `container-scaffold`
- Idee → Karten, Verortung, KI-Routing → `planen`
- Fertiges Projekt gegen Stack prüfen → `architektur-review`
- Frontend davor → Skill `frontend-architektur`
- Isolierte Funktion/Boilerplate schreiben lassen → `ollama-code`

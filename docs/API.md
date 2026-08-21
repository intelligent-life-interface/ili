# Dashboard — Architektur, HTTP-API \& Server-Gotchas (Detail-Modul)

> **Tags:** fastapi, 8798, api, endpoints, routen, nginx, streaming, locking, repositories, boards-json, rev, eiserne-regeln, shelly, threading, gotchas
> Ausgelagert aus `~/containers/dashboard/CLAUDE.md` (1:1, unverändert). Kern-Doku + Trigger-Tabelle: `../CLAUDE.md`.

## Architektur seit 2026-06-10: FastAPI (Port 8798) — Migration ABGESCHLOSSEN

**Alle API-Routen laufen über die FastAPI-App `app/`** (Service `dashboard-api.service`, uvicorn im `venv/`, Port 8798). Der alte trigger_server ist **stillgelegt** (Service disabled, Code liegt als `trigger_server.py.legacy`); nginx (Port 80) proxied alle API-Locations auf 8798. Externe Konsumenten (Isehauer `KANBAN_API_URL`, WhatsApp-Bot `DASHBOARD_URL`, Wekan-Sync `TRIGGER_URL`, n8n-Workflow-JSONs) zeigen seit 2026-06-10 ebenfalls auf 8798. Frontend komplett modularisiert: alle Seiten nutzen `html/js/api.js`, index.html rendert clientseitig aus `GET /api/dashboard` (Generator + Timer stillgelegt; alte Seite: `index-static-backup.html`; `services.html`/`scan.html` sind eingefrorene Generator-Reste).

```
app/
├── main.py        # FastAPI, Logging, Legacy-Fehlerformat {"error":...}, OpenAPI: :8798/docs
├── api/           # nur HTTP: boards, kanban, chat, ki, photos, logs(Streaming), config, misc, dashboard
├── services/      # Logik: board_, chat_, photo_, stream_, cost_, config_, ki_, misc_, dashboard_service, gps_exif
├── storage/       # locking (fcntl auf boards/.lock), atomic_write, board_repository, manifest_repository
└── schemas/       # Pydantic: Board/Column/Card, Manifest (extra="allow"!)
tests/             # pytest: venv/bin/pytest — Locking cross-process, CRUD, Umlaute, CLAUDE.md-Sync
```

**Eiserne Regeln:**
- boards/*.json + manifest.json NIE direkt schreiben — IMMER über `app/storage/`-Repositories (fcntl-Lock + tmp+os.replace). Gilt auch für Timer-Scripts und Hooks (alle umgestellt). Read-Modify-Write → `repo.update(mutator)` (EIN Lock), nie load→save getrennt.
- `board_utils.py` ist nur noch Kompatibilitäts-Wrapper (delegiert ans Repository) für den alten Server.
- Neue Route: Router in `app/api/`, Logik in `app/services/`, in `main.py` registrieren, nginx-Regex (8798-Block) ergänzen, dann `podman restart dashboard` (inode-Falle — kein nginx -s reload!).
- Frontend: `html/js/api.js` ist der EINZIGE API-Client (window.API, relativ via nginx — nie :8799/:8798 hartcodieren). bugs.html ist modularisiert (css/js extrahiert); project.html + ki-advisor.html stehen noch aus.
- `index-new.html` (clientseitig aus `GET /api/dashboard`) ersetzt nach Browser-Freigabe die generierte index.html; `generate_dashboard.py` + Timer entfallen dann (Timer war schon seit ~23.05. inactive!).
- Streaming neu: `/analyse-bug` + `/ki-explain-stream` als StreamingResponse — das alte ThreadingHTTPServer-Freeze-Problem ist damit strukturell weg.

**2026-06-10 nebenbei gefixt:** `kanban_ki_sortierer.py` fehlte `import os` (crashte immer), `ki_project_advisor.py` nutzte `_LOCAL` vor Definition (crashte immer), GPS-EXIF-Injektion (`app/services/gps_exif.py`) aus Git-History restauriert (war nach script_splitter-Refactoring verloren, piexif im venv).

## Ollama-Warteliste-Ansicht (2026-07-16)

**`html/ollama-queue.html`** (Nav „🦙 Ollama-Queue") zeigt die Prioritäts-Warteliste des
ollama-analyse-Proxys (:11435): Live-Stand (aktiv/wartend, Auto-Refresh 5 s), **editierbare
Prioritäten pro Aufrufer** (schreibt `~/containers/ollama-analyse/data/priorities.json`, Proxy
lädt per mtime-Reload — kein Neustart) und die letzten Aufträge mit Prio/Wartezeit/Dauer
(liest die Proxy-SQLite read-only). Router **`app/api/ollama_queue.py`**:
- `GET /api/ollama/queue` — proxied `:11435/queue`
- `GET /api/ollama/recent?limit=N` — letzte Inferenz-Requests (priority, queue_wait_ms, …)
- `GET/POST /api/ollama/priorities` — priorities.json lesen/Eintrag setzen (`prio:null` = löschen)
nginx-Regex um `api/ollama` ergänzt (`html/_api-locations.conf`). Hintergrund/Queue-Doku:
`~/Projekte/ollama-analyse/CLAUDE.md` Abschnitt „Prioritäts-Warteliste".

### API-Endpunkte trigger_server (Port 8799)
- `POST /analyse-bug` — Streaming-Fehleranalyse via Ollama; Body: `{bug: {...}, model?: str}`; nutzt `bug_model` aus KI-Config
- `GET /search-by-tag?q=<stichwort>` — Projekte nach Tag suchen
- `GET /find-related?project=<id>&n=<N>&ai=<0|1>` — verwandte Projekte (Jaccard-Tags + Ollama, nur Tags+Namen)
- `GET /scan-logs?since=<h>` — Log-Scan starten (1–168h)
- `PATCH /boards/<id>` akzeptiert jetzt auch `description_updated`, `tags`, `child_order` (Reihenfolge der Unterprojekte; `GET /boards?parent=<id>` sortiert danach)

### Legacy `/kanban`-Endpoints entfernt (2026-07-28, Karte opt_55d9f1678f)
Die toten Endpoints **`GET /kanban`** (→ Board `overview`) und **`POST /kanban`** (schrieb
`kanban.json` per `write_text` — ohne Lock, gegen die Eiserne Regel, Daten doppelt) sind samt
`board_service.save_legacy_kanban` und dem `kanban.json`-Load-Fallback in `get_board("overview")`
entfernt (0 Zugriffe über 30 Tage im Journal). `kanban.json` liegt jetzt in `archiv/`.
- **`GET /kanban-api?board=<id>`** (roh, ohne CLAUDE.md-Injektion, `raw_board`) **BLEIBT** —
  aktiver Consumer: `~/bin/kanban-split` (Direktzugriff auf `:8798`, wöchentlicher Timer).
  Funktion in `app/api/boards.py` heisst jetzt `kanban_api` (statt `legacy_kanban_api`).
- nginx: die `/kanban-api`-Location proxied jetzt korrekt auf `:8798/kanban-api` (vorher fälschlich
  `/kanban`); `kanban` aus der Sammel-Regex entfernt → `/kanban` gibt über nginx den Static-Fallback,
  Backend-`/kanban` → 404.

### Gotchas
- **Shelly-Scan Single-Flight (2026-06-15):** `GET /shelly` ist ein synchroner Endpoint; ein Scan dauert ~20–30s und hält dabei einen uvicorn-Worker-Thread (+60 interne Scan-Threads). Ohne Sperre starteten rapide Reloads/Klicks Dutzende Scans gleichzeitig → AnyIO-Threadpool erschöpft → **die ganze API warf 502** (Symptom: `/project-from-photo` & Co. 502, Logs voll mit „Shelly-Scan: subnets=…" und Antwortzeiten >1.900.000 ms). Fix in `app/services/misc_service.py`: `threading.Lock` (Single-Flight, `acquire(blocking=False)`) + 30s-TTL-Cache pro Subnetz-Key. Es läuft nie mehr als EIN Scan; parallele Aufrufe bekommen sofort das letzte Ergebnis (`cached`/`scanning`-Flag). Kein Timer — Scan läuft nur on-demand auf Knopfdruck.
- **`POST /boards` `fast`-Flag (2026-06-05):** Standardmässig jagt die Board-Erstellung Name + Tags + CLAUDE.md durch Ollama (~27s!) und die Namenskorrektur verfälscht teils (z.B. „Steuererklärung"→„Steuererlassung"). Body `{"name":…, "fast":true}` überspringt alle Ollama-Schritte → Name bleibt exakt, <1s, simple Template-CLAUDE.md. Genutzt vom Isehauer-+Knopf. (`trigger_server._handle_boards_create` + `project_creator._create_project_folder(fast=…)`)
- **`from constants import *` importiert KEINE `_`-prefixed Namen** (Python-Verhalten) — bei `NameError: name '_xyz'` immer explizit `from constants import _xyz` ergänzen
- **Streaming-Endpoints brauchen HTTP/1.1**: `TriggerHandler` hat `protocol_version = "HTTP/1.1"` gesetzt; fehlt das, empfängt der Browser rohe Chunk-Size-Header statt Text. Streaming-Antworten immer mit `Connection: close` senden.
- **trigger_server muss `ThreadingHTTPServer` nutzen, nicht `HTTPServer`**: Single-threaded Server friert komplett ein, wenn ein einziger Streaming-Client die Verbindung offenhält → alle anderen Requests laufen in Timeout (Symptom: nginx upstream timeouts auf `/claude-cost`, `/api/ai-config`, etc., Boards laden nicht). Fix in `trigger_server.py` main(): `ThreadingHTTPServer(...)` mit `server.daemon_threads = True`.
- Ollama-Prompts für Namen: immer Beispiel im Format `Eingabe='...' → Ausgabe=` verwenden, sonst kommen Sätze statt Namen zurück
- Async Foto-Analyse: `POST /project-from-photo` gibt sofort `201` zurück, Ollama läuft in `threading.Thread(daemon=True)`
- Ollama Vision: Modell `minicpm-v:latest` auf `192.0.2.50:11434` (LAN-Host, Beispiel-IP), Fallback Claude Haiku

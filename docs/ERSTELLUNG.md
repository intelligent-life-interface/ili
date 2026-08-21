# Dashboard — Projekt-Erstellung (Foto/Formular) \& Modul-Übersicht (Detail-Modul)

> **Tags:** projekt-erstellung, foto, foto.html, projekt.html, quick.html, bugs.html, vision, claude-abo, bridge-8950, namens-korrektur, brainstorm, project_creator, module
> Ausgelagert aus `~/containers/dashboard/CLAUDE.md` (1:1, unverändert). Kern-Doku + Trigger-Tabelle: `../CLAUDE.md`.

### ⚡ Vereinter, timeout-sicherer Erstell-Flow (2026-07-28)
`projekt.html` + `foto.html` sind **eine Seite** („ein und dasselbe"): `projekt.html` hat Name +
Beschreibung + **optionale Fotos (mehrere)**; `foto.html` ist nur noch ein `<meta refresh>`-Redirect
dorthin, der Nav-Eintrag „📸 Foto" wurde entfernt (nur noch „➕ Neues Projekt").
- **Mehrere Fotos:** Frontend sammelt sie in `pendingPhotos[]` (Thumbnail-Grid mit ✕-Entfernen,
  `<input multiple>`, „Weiteres Foto hinzufügen") und schickt sie als **`photos: [dataURL,…]`**
  (Einzelfeld `photo` bleibt als Fallback). Backend speichert jedes via
  `photo_service.decode_and_save_photo(..., suffix="_<i>")` (eindeutige Dateinamen), legt **je Foto
  eine „📸 Inspiration"-Karte** an (Notiz nur auf der ersten), `cover_photo` = erstes Foto. Die
  Foto-**Vision** (Titel/Tags) im BackgroundTask läuft nur aufs **erste** Foto (Kosten-Deckel);
  Vision-Tags werden mit den Text-Tags gemerged. `/boards` liegt in der 30m-nginx-Location →
  mehrere Fotos passen ohne Config-Änderung.
- **Anti-Doppelprojekt:** `projekt.html` **vergibt die Board-ID selbst** (`slugify(name)-<rand6>`,
  einmal pro Seite, bei Retry wiederverwendet) und schickt sie als `id` mit. `POST /boards`
  (non-`fast`) legt Board + Manifest **sofort** an → **201 in <1 s** (Manifest `analyzing:true`),
  die schwere KI (Namenskorrektur, Tags, Ideen-Karten = „das Kanban", CLAUDE.md, ggf. Foto-Vision)
  läuft als **BackgroundTask**. Weil die Antwort in <1 s kommt, kann ein Client-Timeout kein
  zweites Board mehr erzeugen; kommt derselbe Request doch nochmal, existiert die ID bereits →
  Response `status:"exists"`, **kein Duplikat**.
- **Code:** `board_service.create_board_immediate()` (Sync-Teil, idempotent via
  `_boards.create`/`_boards.exists`) + `finalize_board_background()` (BG-Teil, best-effort, jeder
  Schritt einzeln abgesichert). Foto-Speicherung teilen sich Foto- und Formular-Flow über
  `photo_service.decode_and_save_photo()`. `POST /boards` in `app/api/boards.py` bekam
  `BackgroundTasks`; **`fast:true` bleibt synchron** (Isehauer-+Knopf/Unterprojekt via
  `board_service.create_board`, unverändert). `/project-from-photo` bleibt für Alt-Aufrufer
  (index.html/quick.html-Kacheln, Mobile) bestehen.
- Auch `quick.html` + `index.html` (posten weiter an `/boards` ohne `id`) profitieren automatisch
  vom Sofort-Return; sie bekommen eine generierte Slug-ID.

### Projekt-Erstellung via Dashboard (Port 80 → FastAPI 8798)
- **`/foto.html`** — Foto aufnehmen → sofort `201` zurück, **Foto-Analyse („Bildersuche") via Claude-Abo** im Hintergrund (BackgroundTask). **Gotcha (2026-06-15):** Seite hatte `const API='http://…:8799'` hartcodiert (Migration vergessen) → "Load failed" beim Upload. Fix: `const API=''` → relativ via nginx → 8798. NIE Ports hartcodieren.
- **Sammelfix 2026-06-15:** Dieselbe 8799-Altlast steckte auch in `projekt.html`, `quick.html`, `whitelist.html` (CORS/"Not allowed to request resource" beim Projekt-Erstellen) — alle drei auf `const API=''` (relativ via URL) umgestellt. `scan.html` (eingefrorener Generator-Rest) und der Fehlertext in `kanban.html:337` haben noch 8799-Strings, sind aber nicht live. **Regel: im Frontend immer relativ über die URL/nginx, nie Host:Port hartcodieren.**
- **`/projekt.html`** — Formular: Name + Beschreibung → Namens-Korrektur (Claude-Abo) → Board + Ordner
- **Claude-Abo-Brainstorm bei Projekt-Erstellung (2026-06-16):** `create_board()` (nicht `fast`) lässt jetzt das **Claude-Abo** die `CLAUDE.md` schreiben **und** 5–8 konkrete Ideen-/Aufgabenkarten in die **Backlog**-Spalte brainstormen — pro Karte `priority` + `effort` (hoch/mittel/niedrig). **Seit 2026-06-27 läuft auch die Foto-Analyse („Bildersuche": Titel + Tags via `/vision`) und die Namens-Korrektur übers Claude-Abo — KEIN lokales Ollama mehr im Foto-/Ideen-Erstellungs-Flow.** (Nur der periodische Massen-Tagger `_text_tags`/`project_tagger` und andere Hintergrund-Jobs nutzen weiter Ollama.) Zugang über die lokale **CLI-Bridge** (`claude-cli-bridge.service`, Port **8950**, = Abo, KEIN API-Guthaben); `dashboard-api` ist ein **Host-Prozess** → URL `http://127.0.0.1:8950` (NICHT `host.containers.internal`). Code: `project_creator._claude_abo_text` + `generate_idea_cards` (best-effort, JSON-Array-Parsing, Fallback = keine Karten), Helper `_strip_md_fences`; `_generate_claude_md` nutzt Abo zuerst, Ollama als Fallback. **Vision-Helper `_claude_abo_vision`** (POST `/vision` an Bridge 8950, Bild als base64-Content-Block) bedient `_vision_title`/`_vision_tags`; **Namens-Korrektur `_correct_project_name`** (vormals `_ollama_correct_name`) via `/chat`, mit Anti-Fantasie-Systemprompt (nur Tippfehler, Thema NICHT umdeuten/ausschmücken). Modelle via `ai_config.json` → `project_ideas_model` (Text) bzw. `project_vision_model` (Foto), Default je `claude-sonnet-4-6`. Frontend: `project.js` rendert ⚡Priorität (Farbe rot/orange/grün, auch als `label`-Chip) + ⏱Aufwand-Badge; Card-Schema um `priority`/`effort` ergänzt. Dauer Board-Erstellung dadurch ~30–40s. `fast=true` (Isehauer-+Knopf) überspringt alles. Nach Python-Änderungen: `systemctl --user restart dashboard-api.service`.
- **🧠 Brainstorming-Modus im Projekt (`project-brainstorm.js` + `app/api/brainstorm.py` + `app/services/brainstorm_service.py`, ausgebaut 2026-07-25):** Pro Projekt ein KI-Dialog zum Ausarbeiten von Ideen — **komplett übers Claude-Abo (Bridge 8950), kein Ollama mehr**. Vier Bausteine:
  1. **Streaming** — `POST /api/brainstorm/stream` proxied die Bridge **`/stream`** (NDJSON `{"t":…}` … `{"done":true}`, Multi-Turn via `messages`+`system`) und reicht die Zeilen als `StreamingResponse` (`application/x-ndjson`) durch; Frontend liest tokenweise (blinkender Cursor). **nginx:** `/api/brainstorm/stream` ist in den Streaming-Location-Block (`proxy_buffering off`, Zeile 18 in `html/_api-locations.conf`) aufgenommen — sonst puffert nginx die Tokens. Modell `brainstorm_service.BRAINSTORM_MODEL` (Default `claude-sonnet-4-6`). `POST /api/brainstorm` bleibt als Single-Shot-Fallback (Bridge `/chat`).
  2. **Serverseitige History** (geräteübergreifend) — `GET|POST /api/brainstorm/history?project_id=` → `boards/brainstorm/<id>.json` (atomar via `app/storage/atomic_write`); Frontend nutzt sie primär, localStorage nur als Offline-Fallback. Loading-Platzhalter werden nie persistiert.
  3. **Idee → Kanban-Karte** — `POST /api/brainstorm/to-card` (`idea_to_card`): verdichtet eine KI-Antwort per Bridge-`/chat` zu Titel+`desc`+`priority` (JSON, Fallback = Roh-Text) und hängt sie via `BoardRepository.update` (Locking) in die erste Spalte; Titel-Prefix `💡`, Farbe aus `constants.PRIORITY_COLORS`.
  4. **Idee → Unterprojekt** — `POST /api/brainstorm/to-subproject` (`idea_to_subproject`): erste Zeile = Name, Rest = Beschreibung → `board_service.create_board({parent_ids:[<projekt>]})` (voller Eltern-Kontext, keine Ausschmückung).
  - **Projekt-Kontext beim Öffnen (2026-07-27):** Der Brainstorm kannte das Projekt früher NICHT (der `project_id` diente nur History/Logging → KI fragte „welche Idee?"). `_project_context(project_id)` baut jetzt aus Manifest (Name/Beschreibung/Tags) **und** den Board-Karten je Spalte einen Kontext-Block, den `stream_brainstorm` an den `SYSTEM_PROMPT` hängt. Kein Frontend-Change (`project_id` wurde eh mitgeschickt).
  - **Ganz-Gespräch-Aktionen (2026-07-27):** Toolbar `.brainstorm-tools` unterm Header (operieren auf dem KOMPLETTEN Verlauf, nicht pro Einzelantwort):
    - **📖 Als Beschreibung** — `POST /api/brainstorm/to-cards` Geschwister-Route `to-description` (`conversation_to_description`): verdichtet das Transkript zu 2-4 Sätzen → `board_service.patch_board(pid, {"description": …})` ins **Manifest** (NIE in die Karte!). Ersetzt bewusst die alte Beschreibung (User-Klick = Zustimmung), liefert `old_description`; Frontend setzt `projHeadEntry.description` + `renderProjectHead()` live.
    - **📋 Plan → Karten** — `POST /api/brainstorm/to-cards` (`conversation_to_cards`): JSON-Array (max 8 Aufgaben) → alle als 💡-Karten in die erste Spalte (Massen-Als-Karte). Beide über `_transcript()` + `_claude_abo_text`; JS `convoToDescription()`/`convoToCards()`, Status in `#brainstorm-tool-status`. nginx-Regex `api/brainstorm(/.*)?` deckt beide ab → nur `dashboard-api`-Restart. Cache-Bust `project-brainstorm.js?v=20260727-convoactions`, `project.css?v=20260727-brainstormtools`. Browser-verifiziert (Playwright): beide Buttons sichtbar, Generierung end-to-end ok.
  - **GUI (project.html/project.css):** Desktop hatte das Panel als permanent gequetschte Mittelspalte (`flex:1` zwischen Board 60% + Terminal min 600px → ~0px, unbenutzbar). Jetzt Toggle-Button **„🧠 Brainstorm"** in der `.board-tools`-Leiste → `.main-split.brainstorm-on`: Panel `flex:0 0 clamp(320px,32vw,460px)`, **Terminal weicht** (`display:none`) → Board + Brainstorm nebeneinander (Workflow Idee→Karte). Jede fertige KI-Antwort trägt zwei Buttons **➕ Als Karte** / **🌱 Als Unterprojekt**; danach `loadBoard()`/`loadSubprojects()`. **Bugfix:** `initBrainstorm` hing an einem `project-name-nav !== '⏳ Lade…'`-Guard, der beim `DOMContentLoaded` IMMER fehlschlug (Name lädt async) → Listener wurden nie gebunden, Senden tat nichts. Jetzt Init unbedingt mit der Board-ID aus der URL. Mobile: fehlendes `.brainstorm-panel.tab-hidden{display:none}` ergänzt, damit der „🧠 Brainstorm"-Tab wirklich um-/ausblendet. Cache-Bust `project-brainstorm.js?v=20260725-brainstorm4`, `project.css?v=20260725-brainstorm3`. Browser-verifiziert (Playwright): Toggle → Streaming → Buttons sichtbar, 0 JS-Fehler.
- **`/quick.html`** — Kachel-Übersicht mit Links zu allen Schnellstart-Aktionen
- **`/bugs.html`** — Log-Viewer: filtert Errors/Warnings, zeigt Kontext, "Für Claude kopieren", "🤖 Ollama analysieren" (Streaming)

### Dashboard-Module (`~/containers/dashboard/`)
- `project_creator.py` — Projekt/Idee erstellen: `_correct_project_name`, `_vision_title`, `_vision_tags` (alle via **Claude-Abo** Bridge 8950, `_claude_abo_text`/`_claude_abo_vision`), `_text_tags` (periodischer Massen-Tagger, weiterhin Ollama), `_create_project_folder`, `search_projects_by_tag`
- `project_tagger.py` — projektweite KI-Tags + `tags-index.json`: `generate_for_board`, `rebuild_tags_index`
- `project_describer.py` — KI-Kurzbeschreibung ins Manifest: `ollama_short_desc`, `describe_one`
- `related_finder.py` — verwandte Projekte (Tag-Vorfilter + Ollama): `score_candidates`, `find_related`
- `log_scanner.py` — Log-Scan: `scan_journal`, `scan_file`, `scan_container_logs`, `run_full_scan`
- `log_sources.json` — Konfigurierbare Log-Quellen (journal, files, containers)
- `bug_fixer.py` — Log → Kanban-Karte: `scan_and_propose(board_id, since_hours, max_fixes)` (s.u.)
- `dedup_finder.py` — Duplikat-Check neuer Karten: `check_duplicate(board_id, title, desc, use_ai)`
- Schnittstellen aller Module sind vollständig dokumentiert (Args/Returns/Side effects) — Modul-Docstrings als Einstiegspunkt

## Terminal-Race beim Async-Flow (Fix 2026-08-07)

- **Bug:** Der Sync-Teil legte NUR Board+Manifest an; Projektordner + tmux-Session kamen erst
  im BackgroundTask (~1–2 min, Ollama). Öffnete man das Projekt-Terminal sofort nach dem 201
  (Normalfall: projekt.html leitet direkt weiter), fand `~/bin/tmux-project.sh` keinen Ordner
  → Fallback `$HOME` → Session `proj-<slug>` für immer in `$HOME` verankert, `claude --continue`
  lud dort die letzte **Home**-Konversation statt frisch im Projekt zu starten.
- **Fix 1:** `create_board_immediate()` macht jetzt synchron `mkdir ~/Projekte/<id>` +
  `_ensure_project_session()` (try/except, gefährdet den 201 nie). Das mkdir ist der tragende
  Teil — existiert der Ordner, wählt tmux-project.sh selbst den richtigen cwd.
- **Fix 2 (Heilung):** `tmux-project.sh` schickt beim Claude-Start `cd '$DIR'` mit (ohne `&&`,
  damit nie eine tote bash übrig bleibt) — heilt leer vorab angelegte Sessions mit stale cwd
  beim nächsten Öffnen. Zusätzlich läuft `projterm_prepare.py` nie mehr gegen `$HOME`.
- **Betroffene Alt-Sessions** mit laufendem Claude (cwd=$HOME) heilt nur Kill+Neuöffnen:
  `tmux kill-session -t proj-<slug>` → im Dashboard ↻.

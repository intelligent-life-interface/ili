# Dashboard — Projektstruktur, Kanban-Sync, Tags, Beschreibung, Related (Detail-Modul)

> **Tags:** projekte, kanban-sync, claudemd-description, ideen, tags, tags-index, project_tagger, project_describer, description, last_activity, code_dir, related, related_finder, search-by-tag
> Ausgelagert aus `~/containers/dashboard/CLAUDE.md` (1:1, unverändert). Kern-Doku + Trigger-Tabelle: `../CLAUDE.md`.

## Projektstruktur (`~/Projekte/`)

Jedes Projekt hat einen eigenen Ordner `~/Projekte/<name>/` mit `CLAUDE.md` (Ollama-generiert).
Unterordner → eigene Sub-CLAUDE.md.

### Kanban-Sync (bidirektional)
- **Board → CLAUDE.md**: Wenn ein Board gespeichert wird (POST oder via Chat-Tool), wird die Beschreibungskarte (`id: claudemd-description`) automatisch in `~/Projekte/<name>/CLAUDE.md` zurückgeschrieben.
- **CLAUDE.md → Board**: Beim Laden eines Boards (`GET /board?id=<name>`) wird CLAUDE.md live vom Disk gelesen und als Beschreibungskarte injiziert — kein veralteter Copy.
- **Änderungen** nur via Chat-Funktion (Ollama oder Claude API wählbar) — Modellwahl direkt im Chat-Widget.

### Tools (`~/Projekte/create_project/`)
- `main.py` — Neues Projekt erstellen (Ollama generiert CLAUDE.md), `--resync` für Kanban-Sync
- `rebuild_boards.py` — Alle Boards aus `~/Projekte/` neu aufbauen (pro Ordner ein Board)
- `create_idea_folders.py` — Ideen-Boards → `~/Projekte/`-Ordner mit CLAUDE.md

### Ideen-Projekte
- Boards in `~/containers/dashboard/boards/ideen-box.json` (Übersicht, 1 Karte pro Gruppe)
- Jede Idee hat eigenen `~/Projekte/<name>/`-Ordner + CLAUDE.md + `.idea`-Marker
- Aktiv wird ein Projekt wenn Code existiert (dann Unterordner + Sub-Boards anlegen)

### Tags-System
- Jedes Projekt hat `~/Projekte/<name>/TAGS.md` (menschenlesbar, editierbar)
- Ollama generiert Tags aus Foto (Vision) oder Beschreibung (Text) → max 8 Tags
- Suchbar via `GET /search-by-tag?q=<stichwort>` (FastAPI 8798). **Match seit 2026-06-24 gegen Tags UND Projektname/ID** (`search_projects_by_tag`, `project_creator.py`) → Treffer-Feld `match_in: ["name"|"tag"]`; `__pycache__`-Artefakte werden übersprungen. So findet z.B. `avatar` auch `avatar-plattform` ohne passenden Tag.
  - **Hashtag-Präfix `#` toleriert (2026-07-25):** Tags im Index sind OHNE `#` gespeichert, User tippen aber oft `#mqtt`. Bisher suchte der Code den Literal-String `#mqtt` → 0 Treffer. Fix an DREI konsistenten Stellen: Backend `search_projects_by_tag` (`query.lower().strip().lstrip("#").strip()`), Frontend `applyFilter` UND `runTagSearch` in `index.js` (`.replace(/^#+\s*/, '')` — beide gleich, sonst passt `tagQuery !== search` und die „+X im Index"-Sektion bleibt aus). Cache-Bust `index.js?v=20260725-hashtag`.
- **Such-UI in der Übersicht (`index.html`, 2026-06-24):** Das Suchfeld `#project-search` filtert weiterhin clientseitig die geladenen Board-Kacheln (sofort), ruft aber **debounced (250 ms) zusätzlich `API.searchByTag(q)`** (`js/api.js`) und zeigt Treffer, die NICHT im `/api/dashboard`-Payload stecken (= container-Projekte ohne Board, z.B. `rueckentrainer`), in einer eigenen Sektion **„🔎 Weitere Treffer im Index"** (lila Kacheln, `match_in`-Badge, Tags mit hervorgehobenem Treffer, Pfad; Klick → `/project.html?id=`). Code: `index.js` `onSearchInput`/`runTagSearch` (race-safe: nur jüngste Antwort gilt) + `appendTagHits`/`renderTagHitCard`, CSS `.tag-hit-*`/`.tag-chip*` in `index.css`. Reines nginx-Mount (live) → nur Hardreload (Cache-Bust `?v=20260624-tagsearch`). Browser-verifiziert (Playwright): `avatar` zeigt avatar-plattform+tag-suche-fix als Board UND rueckentrainer als Index-Treffer, keine Console-Errors.
- **Projektweite Auto-Tags (`project_tagger.py`, 2026-06-06):** stündlicher Job (Timer `project-meta.timer`, :15) taggt JEDES Projekt (**Claude-Abo Bridge 8950** seit 2026-06-27, `project_creator._text_tags`), schreibt `TAGS.md` (immer nach `~/Projekte/<id>/`) und baut den **zentralen Index `boards/tags-index.json`** (`{updated, projects:{id:{name,tags}}}`). NB: getrennt vom per-Karte-Tagger `kanban_tagger.py`.
  - **Quelle = beste CLAUDE.md (`_source_text`, 2026-06-24):** 3-Stufen wie `project_describer` — Manifest-`code_dir` → längste aus `~/Projekte/<id>` UND `~/containers/<id>` → Karten-Titel. Vorher las der Tagger NUR `~/Projekte/` → container-Projekte bekamen schlechte/keine Tags.
  - **`_all_projects()` (2026-06-24):** erfasst Manifest-Boards **PLUS** alle `~/containers/<x>/` mit CLAUDE.md, die KEIN Board haben (z.B. `rueckentrainer`, `telegraf`, `caddy`, `wekan` — 21 Stück). Vorher fielen diese komplett aus Index UND Suche, weil der Tagger nur über Manifest-Boards iterierte. `CONTAINERS_BASE` jetzt in `constants.py`.
  - **Technik-Tags (`_text_tags`-Prompt, 2026-06-24):** der Prompt verlangt jetzt explizit ZWEI Dimensionen — Thema/Zweck UND konkret verwendete Technik/Bausteine (mediapipe, three.js, fastapi, mqtt, tts…), Quelltext-Fenster auf 1200 Zeichen erweitert (Technik steht oft weiter unten). So sind Projekte auch nach eingesetzter Technologie auffindbar, nicht nur nach Thema. Wirkt für Tagger UND Projekt-Erstellung (gemeinsame Funktion).
  - **Idempotenz über den QUELL-HASH statt über das Datum (2026-08-03):** `TAGS.md` trägt im Abschnitt „## Generiert" eine Zeile `- Quell-Hash: <16 hex>` = sha256 aus `PROMPT_VERSION` + Quelltext (`_src_hash`). `_tags_fresh(ppath, src)` vergleicht diesen Hash → **nur Projekte mit wirklich geänderter CLAUDE.md/Karten-Quelle gehen durch Ollama.** Vorher galt „TAGS.md trägt heutiges Datum" als frisch, weshalb der erste Lauf nach Mitternacht **jedes Mal alle ~250 Projekte neu taggte** (456 Ollama-Requests/Nacht, ~34 min Rechenzeit; der volle Slot verursachte zusätzlich 13 Queue-Timeouts bei anderen Diensten, u.a. WhatsApp-Bot). Der Prüfweg ist jetzt: Quelle lesen (billig) → Hash vergleichen → nur bei Abweichung KI. `PROMPT_VERSION` (Konstante im Tagger) hochzählen, wenn sich der Prompt ändert — dann taggt der nächste Lauf automatisch alles neu, ohne `--force`.
    - **Migration ohne Kosten (`_backfill_hash`):** TAGS.md ohne `Quell-Hash`, aber mit heutigem Datum + echten Tags = im heutigen Lauf aus genau dieser Quelle erzeugt → Hash wird nachgetragen statt neu zu taggen (Umstellungslauf 03.08.: 231 Tagger + 205 Describer nachgetragen, **0 Ollama-Calls**).
    - `_write_tags_md_raw(..., src_hash=None)` übernimmt einen vorhandenen Hash aus der Datei — sonst würden `pin_tag`/`set_individual_terms` ihn löschen und ein unnötiges Neu-Taggen auslösen.
  - **`--force` (2026-06-24):** `python3 project_tagger.py --force` ignoriert die Idempotenz (`_tags_fresh`) und taggt ALLE Projekte neu — Notnagel, seit 03.08.2026 meist unnötig (Quell-/Prompt-Änderungen greifen von selbst).
  - **Platzhalter-Handling (`TAGS_PLACEHOLDER`, 2026-06-24):** Projekte ohne echte Tags tragen in TAGS.md den Platzhalter `_(noch keine Tags)_`. `_read_tags_md` filtert ihn → liefert `[]` (kein falscher „Tag" im Index/Suche), `rebuild_tags_index` nimmt das Projekt gar nicht erst auf. `_tags_fresh` wertet eine reine Platzhalter-TAGS.md NICHT als „frisch" → der nächste Lauf versucht erneut, sobald eine Quelle da ist (vorher blieben Projekte mit anfangs dünner Quelle für immer ohne Tags). Über den Projektnamen bleiben sie trotzdem auffindbar.

### Kurzbeschreibung pro Projekt (`project_describer.py`, 2026-06-06)
- KI-Job (gleicher Timer `project-meta.timer`, nach dem Tagger) fasst CLAUDE.md/Projektinhalt in 1 Satz (max ~140 Zeichen, Ollama) zusammen und schreibt ihn via `PATCH /boards/<id> {description, description_updated}` ins **Manifest** (`boards/manifest.json`). Das Frontend `index.html`/`js/index.js` zeigt `board.description` als `.card-desc` (max 2 Zeilen) auf der Projekt-Kachel.
- **Wichtig:** `description` lebt im Manifest. NIE in die `claudemd-description`-Karte schreiben (die ginge via CLAUDE.md in die Karten-Sync ein).
- **Idempotenz über `description_src_hash` (2026-08-03, analog zum Tagger):** Manifest-Feld mit dem Fingerabdruck der Quelle, aus der `description` erzeugt wurde (`_src_hash` = sha256 aus `PROMPT_VERSION` + Quelltext). Gleicher Hash = Quelle unverändert = **kein Ollama-Call**. Vorher entschied `description_updated` (Datum) → jede Nacht liefen alle ~240 Boards neu durch die KI. `description_updated` bleibt erhalten (zeigt, wann zuletzt generiert). Beide Felder stehen in der PATCH-Whitelist `board_service.patch_board`; Migration wie beim Tagger kostenlos (Hash nachtragen, wenn Beschreibung vom heutigen Lauf stammt).
- **Worklog-Aktivität (`last_activity`, 2026-06-16):** Zusätzlich zum Satz schreibt der Job das Manifest-Feld `last_activity` = jüngster Worklog-Eintrag des Projekts (`"DD.MM.: <Commit-Subject | KI bearbeitete N Dateien>"`). Quelle: `_worklog_activity_map()` **parst die fertige `~/ai_session_logs/worklog.md`** (deterministisch, kein git/Ollama) — Projekt-Match = `### <board_id>`. Wird bei JEDEM Lauf aktualisiert (billig), auch wenn die Beschreibung heute schon „frisch" ist. Frontend: `.card-activity` (🕒, grün) unter der Beschreibung; Feld in `dashboard_service._PROJECT_FIELDS` + PATCH-Whitelist in `board_service.patch_board`.
- **`SKIP_RE` statt `SKIP_PREFIXES` (2026-06-16):** Übersprungen werden nur echte Foto-Timestamp-Boards (`^foto[-_]\d`) + `sub_` + `testesteset` — **echte Projekte wie `foto-metadaten` werden jetzt beschrieben** (vorher fälschlich vom `"foto-"`-Prefix erschlagen).
- **Quelle = reichste CLAUDE.md (2026-06-16):** `_source_text(board_id, code_dir)` wählt die Quelle in 3 Stufen:
  1. **Manifest-Feld `code_dir`** (falls gesetzt) → `<code_dir>/CLAUDE.md` ist autoritativ. Für Projekte, deren Code-Ordner ≠ board_id heisst (z.B. Board `bohrprofile-3d` → `code_dir: ~/containers/bohr3d`). Setzen via `PATCH /boards/<id> {"code_dir":"~/containers/bohr3d"}` (auch relative Pfade/`~` ok, `_resolve_code_dir`).
  2. Sonst die **längere** aus `~/Projekte/<id>/CLAUDE.md` und `~/containers/<id>/CLAUDE.md` (`CONTAINERS_BASE`) — container-basierte Projekte haben unter `~/Projekte/` oft nur ein Stub, die echte Doku in `~/containers/<id>/`.
  3. Fallback = Karten-Titel des Boards.
  `code_dir` steht in der PATCH-Whitelist (`board_service.patch_board`); `describe_one` lädt es bei Standalone-Aufruf selbst aus dem Manifest nach.

### Verwandte Projekte / wiederverwendbarer Code (`related_finder.py`, 2026-06-06)
- `GET /find-related?project=<id>&n=<N>&ai=<0|1>` — **token-sparend**: an die KI gehen NUR Tags+Projektnamen, nie der Inhalt.
- Ablauf: (1) Jaccard-Tag-Überschneidung aus `tags-index.json` (Vorfilter, Top-N), (2) Ollama begründet je Kandidat warum Code/Konzepte wiederverwendbar sind. `ai=0` → reine Jaccard-Liste (ohne Ollama, sofort). Degradiert sauber wenn Ollama fehlt.
- UI: Button „🔗 Verwandte Projekte" in `project.html` (Board-Tools-Leiste).

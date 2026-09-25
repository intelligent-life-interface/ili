# automat — Kanban-Automat im ili-Release

Kopie von `~/containers/kanban-automat` des Home-Stacks (Quelle der Wahrheit dort). Die
Kopie weicht nur in Env-Überschreibungen ab (Defaults = Home-Stack-Layout):

| Env | Zweck | Release-Wert |
|---|---|---|
| `ILI_DASHBOARD_DIR` | `ai_config.json`, `automat_limits.json`, `batch_budget.json`, Resolver | `/opt/ili-automat/state` (Volume `automat-state`; GUI-Kopplung offen, s. Karte) |
| `ILI_CONFIG_ENV` | Pfad der config.env | `/dev/null` (Werte kommen aus der Prozess-Env) |
| `AUTOMAT_PROJECT_DIRS` | Projektordner-Kandidaten (zuerst) | `/projects` |
| `AUTOMAT_LOG_BOARD` | Protokoll-Board; leer = aus | `""` |
| `DASHBOARD_URL` | Dashboard-API | `http://api:8798` |
| `AUTOMAT_INTERVAL` | Tick-Abstand (ticker.py) | `300` |
| `ILI_AUTOMAT_BACKFILL` | Idle-Filler (braucht Advisor-venv) | `0` |

Weitere Abweichung: `worker.py` lässt mit `AUTOMAT_ALLOW_API_KEY=1` den `ANTHROPIC_API_KEY` durch
(Home-Stack erzwingt Abo).

Shims statt Home-Stack-Module: `loop_logger.py` (No-op), `config_env.py` (nur Env).
`ticker.py` ersetzt `kanban-automat.timer` (Compose kennt keine Timer). Kill-Switch:
`touch state/automat.disabled` im Volume `automat-state`.

**Dritte Abweichung, kein Env-Patch:** `worker.py` `build_prompt()` nennt statt des
Subagenten `kanban-editor` (existiert nur im Home-Stack) direkt `automat_cli.py`
(90d57ad4) und erklärt zusätzlich die Compose-Servicenamen `api`/`db`/`terminal`
für den Fall, dass die KI-Session ilis eigene Dienste direkt ansprechen muss
(F-17). `tests/test_no_kanban_editor_references.py` hält Ersteres fest; Letzteres
nach einem rsync von Hand gegenprüfen.

**Vierte Abweichung, kein Env-Patch, NICHT upstream schieben:** `worker.py`
`resolve_workdir()` ruft `_ensure_git_repo()` auf jeden aufgelösten Projektordner
(F-19, `git init` + Platzhalter-Identität `ili`/`ili@localhost`, falls keine
konfiguriert ist — idempotent über den `.git`-Check, Fehler nur geloggt). Nur für
dieses Release relevant: der Home-Stack `~/containers/kanban-automat` hat sein
eigenes Terminal-Image mit eigenem Ordner-Handling; ein Upstream-rsync dieses
Patches würde dort beim nächsten Karten-Pick jeden Nicht-Repo-Ordner unter
`~/Projekte`/`~/containers` (264+ Boards) still git-initen — ausserhalb des Zwecks
dieser Karte. `tests/test_project_git_init.py` hält den Patch fest.

Aktualisieren: `rsync -a --include='*.py' --exclude='*' ~/containers/kanban-automat/ automat/`
und danach die Env-Patches, den `build_prompt()`-Patch **und den `_ensure_git_repo()`-
Patch in `resolve_workdir()`** erneut anwenden (siehe git log dieses Ordners).

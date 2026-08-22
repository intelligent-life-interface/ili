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

Aktualisieren: `rsync -a --include='*.py' --exclude='*' ~/containers/kanban-automat/ automat/`
und danach die Env-Patches erneut anwenden (siehe git log dieses Ordners).

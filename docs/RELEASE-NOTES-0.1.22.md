## ili 0.1.22

### Project terminal
- **Four Claude terminals and one plain shell per project.** Each board gets its own
  tmux sessions, so a long-running Claude session no longer blocks a quick shell.
- **11 Claude skills ship with the terminal image** (architecture review, backend/
  frontend/container/database conventions, networking, security, scaffolding,
  planning, prioritising). They are sanitised — no host names, addresses or paths
  from the machine they were written on.
- **Docker-MCP switch in Settings → Docker**, so the terminal's Claude can drive
  project containers without hand-editing the compose files.

### Projects
- **One reserved host port per board**, assigned when the board is created and
  released when it is deleted — no more hunting for a free port by hand.
- **Stale-card filter on the project page**: old cards that nobody touched are now
  visible as a filter instead of quietly padding the board.
- **Self-test of the installation**: one command and one button that check the whole
  stack instead of the start page, which stays green even when the backend is down.

### Reporting
- The **bug report form arrives filled in** — version, route and environment are
  prefilled from the running instance, no GitHub login required.

### Security
- **Query strings no longer reach the logs** (#2). uvicorn's access logger printed
  the full request line, query included, and query strings carry tokens. The API now
  runs with `--no-access-log`; the request-logging middleware keeps logging method,
  path, status and duration. The nginx container logged the same thing through its
  default `combined` format — it now uses a format that logs `$uri`, the path alone.

### Questions
- **A question without a card is a question too.** "Offene Fragen" used to list
  decision cards only, so a question raised by an AI session while working never
  showed up. It now also reads `data/open_questions.json` (fed by
  `POST /api/questions`) and, if one is configured, an external decisions database.

### Fixes a fresh installation actually sees
- **An empty model id no longer looks like a broken login.** A blank value in
  `ai_config.json` used to beat the default and travel into `claude --model ""`,
  which failed with `unrecognized_model` — while the error card blamed the Claude
  login. Blank values are ignored on load, never stored on save, skipped by the
  settings page and treated as absent by the bridge. The card now prints the real
  error instead of guessing, and no longer looks like a task to the automation.
- The generated Docker guide no longer claims `DOCKER_HOST=` with an empty value,
  and a guide that could not be refreshed is marked as stale instead of silently
  staying wrong.
- The settings page no longer calls `/api/claude-limits`. That service was removed
  earlier; every installation logged a 404 and showed two empty bars. The budget
  fields beside them stay — those work.
- The bug viewer no longer fetches a board that a fresh install does not have.

### Upgrading
```bash
docker compose pull && docker compose up -d
```
Data lives in volumes and is untouched. If your `.env` pins `ILI_VERSION` to a
version older than 0.1.18, remove or update that line — those image tags no longer
exist in the registries.

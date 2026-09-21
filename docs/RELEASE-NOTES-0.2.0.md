## ili 0.2.0

The 0.1.x line ends here. Nothing in this release breaks an existing
installation — the jump in the version number says that the package has grown
past the shape it had when the numbering started.

### The automation now works in an installation that is not ours

- **Workers were told to use a channel no image ships.** `worker.py` named the
  subagent `kanban-editor` in twelve places as the only allowed way to touch a
  board. That agent exists in the author's Claude configuration, not in the
  shipped image, so every worker elsewhere received an instruction it could not
  follow. The prompts now call `automat_cli.py`, which is part of the package.
- Two more passages belonged to the author's machine rather than to the
  product: a POST to a container manager on `localhost:8810` with a key read
  from `~/config.env`, and a rule about a token from the same file. Replaced by
  the rule they were meant to express — run a test version beside the live one,
  on its own port, with the live data mounted read-only.

### Questions no longer disappear

"Offene Fragen" listed decision cards and nothing else, so a question raised by
an AI session while working was never shown. It now also reads
`data/open_questions.json`, which anything can append to through
`POST /api/questions` — a terminal session, a script, the automation — and an
external decisions database if one is configured.

### An empty setting no longer looks like a broken login

A blank model id in `ai_config.json` used to beat the default and travel all the
way into `claude --model ""`, which fails with `unrecognized_model`. Creating a
project then produced an empty board and a red card blaming the Claude login,
which was fine. Blank values are now ignored on load, never stored on save,
skipped by the settings page, and treated as absent by the bridge. The failure
card prints the real error instead of guessing, and no longer looks like a task
to the automation.

### The terminal tells the truth about containers

- When no engine answers, the generated `/projects/CLAUDE.md` used to vanish
  entirely — indistinguishable from "docker is off", so the AI found no guide
  and assumed docker worked. It now states that there is no engine, names the
  reason, and tells the session to put that in the card instead of improvising.
- `ili-claude.sh` reports an empty answer from `/api/docker/env` instead of
  passing over it in silence.
- Settings → Docker now warns that **podman-compose ignores `COMPOSE_FILE` from
  `.env`** and gives the explicit `-f` invocation. Following the old wording
  changed nothing and looked like a broken feature.

### Terminal

- **UTF-8**: `LANG` and `LC_ALL` are set and tmux starts with `-u`. Without a
  locale, umlauts and the emoji of card titles arrived broken.
- **`gh` is installed** — the shipped method asks the AI to export cards as
  issues and return work as pull requests, which needs it.

### Smaller things

- `TAGS.md` claimed its tags came from `ollama-text`, long after tag generation
  had moved to the Claude bridge. It now names what produced them, and says so
  plainly when the AI produced nothing instead of leaving a placeholder that
  reads like a result.
- Query strings stay out of the logs on both sides: the API runs with
  `--no-access-log`, and nginx logs `$uri` instead of the full request line.
- New self-test check: if a source tree is mounted, its `VERSION` must match the
  running one. A test report that reads different code than it tests produces
  failures that were fixed long ago.
- A test now fails when a file is deleted that something still references —
  a cleanup once removed a script four places still called.

### Upgrading

```bash
docker compose pull && docker compose up -d
```

Data lives in volumes and is untouched. **If you pinned `ILI_VERSION=0.1`**,
that tag stops at 0.1.22 and will not follow here; use `0.2`, a full version, or
remove the line to track `latest`.

# Operational logs — the `logs` table

`bugs.html` shows errors and warnings from ili's own `api` container. Two
older sources were home-server-specific and stay empty on any other install:
a hardcoded Kanban board (`home-stack-bugs`) that only exists on the original
author's server, and a scan of the systemd journal / podman socket that a
portable container simply cannot reach. This is the third, generic source: a
`logs` table in the PostgreSQL service (`db`) that ships with the stack.

## How it works

`api` attaches a `logging.Handler` to its root logger
(`app/services/log_db_service.py`) that mirrors every **WARNING and ERROR**
record into `logs`, in addition to the normal stdout output you already see
with `docker compose logs api`. `bugs.html` reads them through
`GET /db-logs` (`level`, `since` in hours, `q` full-text, `limit`).

```sql
CREATE TABLE logs (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    level TEXT NOT NULL,      -- WARNING | ERROR
    service TEXT NOT NULL,    -- Python logger name, e.g. "dashboard.api"
    message TEXT NOT NULL,
    context TEXT              -- formatted record incl. traceback, if any
);
```

## Retention

Rows older than `LOG_RETENTION_DAYS` (default **30**, set in `.env`) are
deleted once an hour — without a limit `db-data` would grow without bound.
Change it any time, no restart needed beyond the next hourly run picking up
the new value.

## Works without a database, on purpose

Nothing here requires `db` to exist:

- **No `db` service at all** (removed from `docker-compose.yml`, see
  `docs/PROJECT-TERMINAL.md`): `api` cannot resolve the hostname, logs that
  once and keeps working — logging just stays stdout-only, `GET /db-logs`
  answers `{"available": false, "bugs": []}`.
- **`db` not up yet** (a fresh `docker compose up -d` starts services in
  parallel, Postgres' own init takes a few seconds): `api` retries a few
  times at startup, then hourly, and starts writing as soon as it connects —
  no restart needed.
- **`db` was reachable and drops** (restart, network hiccup): the next
  write just fails silently and stdout keeps going; the hourly retry brings
  DB logging back once `db` is reachable again.

None of this ever raises into the code that triggered the log line — a
database problem must never turn into an application problem.

## What is not (yet) covered

- Only `api`'s own Python logging feeds the table right now. `web` (nginx)
  and the project terminal have their own container logs
  (`docker compose logs web` / `terminal`) but nothing ships them here yet.
- `GET /db-logs` supports a full-text/time-range query already (`q`, `since`)
  for scripting, but `bugs.html` only uses it for the error/warning list —
  a dedicated search view in the UI can build on the same endpoint later.

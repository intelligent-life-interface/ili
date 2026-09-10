"""log_db_service — mirrors ili's own WARNING/ERROR log records into the `logs`
table of the optional PostgreSQL service (`db` in docker-compose.yml), so
bugs.html has real data on a fresh install where the host journal / podman
socket / `home-stack-bugs` Kanban board (all home-server-specific) are not
reachable.

Everything here is best-effort by design: a deleted `db` service, an
unreachable host or wrong credentials must never break logging or the API —
the line still reaches stdout via the normal StreamHandler regardless of what
happens in this module. `write()`/`query()`/`cleanup_old()` all swallow their
own errors; only `ensure_schema()` (called once at startup, then retried
periodically) is allowed to log a single info/warning line about DB logging
being on or off.
"""
import logging
import os
import time
from typing import Any

log = logging.getLogger("dashboard.services.log_db_service")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    level TEXT NOT NULL,
    service TEXT NOT NULL,
    message TEXT NOT NULL,
    context TEXT
);
CREATE INDEX IF NOT EXISTS logs_ts_idx ON logs (ts DESC);
CREATE INDEX IF NOT EXISTS logs_level_idx ON logs (level);
"""

# Circuit breaker: after a failed connection attempt, skip further attempts for
# this long instead of retrying (and adding connect-timeout latency) on every
# single warning/error while the database is down.
_CIRCUIT_COOLDOWN_S = 60.0
_last_failure_monotonic = 0.0
_schema_ready = False


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        log.warning("%s=%r ist keine Zahl — nutze %d", name, raw, default)
        return default


_RETENTION_DAYS = max(1, _int_env("LOG_RETENTION_DAYS", 30))


def retention_days() -> int:
    return _RETENTION_DAYS


def is_available() -> bool:
    """True once ensure_schema() has succeeded at least once and no failure
    happened within the current circuit-breaker cooldown."""
    return _schema_ready and _should_attempt()


def _should_attempt() -> bool:
    return (time.monotonic() - _last_failure_monotonic) > _CIRCUIT_COOLDOWN_S


def _mark_failure() -> None:
    global _last_failure_monotonic
    _last_failure_monotonic = time.monotonic()


def _dsn_configured() -> dict[str, Any] | None:
    """Connection kwargs from POSTGRES_* env vars, or None if unset.

    Same variable names as the `db` service in docker-compose.yml — api gets
    them passed through with the same defaults, so this is "configured"
    whenever the compose file's db service is (i.e. always, unless someone
    strips the environment block). Whether the host is actually *reachable*
    is a separate question, answered by the connect attempt itself.
    """
    user = os.environ.get("POSTGRES_USER", "")
    db = os.environ.get("POSTGRES_DB", "")
    if not user or not db:
        return None
    return {
        "host": os.environ.get("POSTGRES_HOST", "db"),
        "port": _int_env("POSTGRES_PORT", 5432),
        "user": user,
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "dbname": db,
        "connect_timeout": 2,
    }


def _connect():
    import psycopg  # imported lazily — a missing/broken driver must not break app startup

    kwargs = _dsn_configured()
    if kwargs is None:
        return None
    return psycopg.connect(**kwargs)


def ensure_schema() -> bool:
    """Create the `logs` table if the database is reachable. Safe to call
    repeatedly (e.g. from a periodic retry while `db` is not up yet)."""
    global _schema_ready
    if _dsn_configured() is None:
        log.info("logs-Tabelle: POSTGRES_USER/POSTGRES_DB nicht gesetzt — DB-Logging bleibt aus, nur stdout")
        return False
    try:
        conn = _connect()
        if conn is None:
            return False
        with conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
        if not _schema_ready:
            log.info("logs-Tabelle in PostgreSQL bereit — bugs.html liest ab jetzt von dort")
        _schema_ready = True
        return True
    except Exception as e:
        if _schema_ready:
            log.warning("logs-Tabelle nicht mehr erreichbar (%s) — fällt auf stdout zurück", e)
        _schema_ready = False
        _mark_failure()
        return False


def write(level: str, service: str, message: str, context: str = "") -> None:
    """Insert one log row. No-op (not an error) whenever the DB is not ready —
    the caller is a logging.Handler and must never see an exception from here."""
    if not is_available():
        return
    try:
        conn = _connect()
        if conn is None:
            return
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO logs (level, service, message, context) VALUES (%s, %s, %s, %s)",
                    (level, service[:200], message[:4000], (context or "")[:8000]),
                )
    except Exception as e:
        # log.debug ONLY: this module is reached from a logging.Handler attached to
        # the root logger, and that handler is only invoked for WARNING+ records.
        # A log.warning()/.error() call here would loop straight back into the same
        # handler. DEBUG never reaches a WARNING-level handler, so it is the one
        # safe way to note the failure.
        log.debug("logs-Tabelle: INSERT fehlgeschlagen (%s)", e)
        _mark_failure()


def query(level: str = "", since_hours: int = 720, q: str = "", limit: int = 200) -> list[dict]:
    """Rows for bugs.html, newest first. Empty list (not an error) when the DB
    is unavailable — the API layer reports availability separately."""
    if not is_available():
        return []
    since_hours = max(1, min(since_hours, 24 * 90))
    limit = max(1, min(limit, 1000))
    sql = "SELECT id, ts, level, service, message, context FROM logs WHERE ts >= now() - (%s || ' hours')::interval"
    params: list[Any] = [str(since_hours)]
    if level in ("ERROR", "WARNING"):
        sql += " AND level = %s"
        params.append(level)
    if q:
        sql += " AND (message ILIKE %s OR context ILIKE %s)"
        like = f"%{q}%"
        params += [like, like]
    sql += " ORDER BY ts DESC LIMIT %s"
    params.append(limit)
    try:
        conn = _connect()
        if conn is None:
            return []
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        log.debug("logs-Tabelle: SELECT fehlgeschlagen (%s)", e)
        _mark_failure()
        return []


def cleanup_old() -> int:
    """Delete rows older than LOG_RETENTION_DAYS. Cheap even run hourly — an
    indexed DELETE over `ts`, normally 0 rows between runs."""
    if not is_available():
        return 0
    try:
        conn = _connect()
        if conn is None:
            return 0
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM logs WHERE ts < now() - (%s || ' days')::interval",
                    (str(_RETENTION_DAYS),),
                )
                deleted = cur.rowcount
        if deleted:
            log.info("logs-Retention: %d Zeile(n) älter als %d Tage gelöscht", deleted, _RETENTION_DAYS)
        return deleted
    except Exception as e:
        log.debug("logs-Retention: DELETE fehlgeschlagen (%s)", e)
        _mark_failure()
        return 0


class PostgresLogHandler(logging.Handler):
    """Mirrors WARNING+ records into the `logs` table. Never raises — a broken
    DB write must not break the request that triggered the log line."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            context = self.format(record)
            write(record.levelname, record.name, record.getMessage(), context)
        except Exception:
            pass

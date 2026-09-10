"""Background tasks for ili (startup, periodic checks, etc.)."""
import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("dashboard.background_tasks")

_last_update_check: datetime | None = None
_check_interval = timedelta(hours=24)
_log_db_interval = timedelta(hours=1)


async def check_for_updates_periodic() -> None:
    """Periodically refresh update status (1× per day).

    Started at app startup, runs continuously in the background.
    """
    global _last_update_check

    from app.services.update_checker_service import refresh_update_status

    # Initial check at startup
    try:
        result = await asyncio.to_thread(refresh_update_status)
        _last_update_check = datetime.utcnow()
        log.info("Initial update check completed: %s", result.get("available_version", "no update"))
    except Exception as e:
        log.warning("Initial update check failed: %s", e)

    # Then every 24 hours
    while True:
        try:
            await asyncio.sleep(_check_interval.total_seconds())
            result = await asyncio.to_thread(refresh_update_status)
            _last_update_check = datetime.utcnow()
            log.info("Periodic update check completed: %s", result.get("available_version", "no update"))
        except asyncio.CancelledError:
            log.debug("Update check task cancelled")
            break
        except Exception as e:
            log.error("Periodic update check failed: %s (will retry in 24h)", e)


async def maintain_log_db_periodic() -> None:
    """Keep the optional `logs` table (PostgreSQL) usable, without ever
    depending on it being there.

    A few quick retries right at startup: on a fresh `docker compose up -d`,
    `db` is usually not accepting connections yet the moment `api` starts —
    Compose starts services in parallel and Postgres' own init takes a few
    seconds. Without this, DB logging would stay off until the next container
    restart on almost every fresh install. After that, retry hourly for as
    long as it stays unavailable (deleted db service, wrong credentials,
    temporary outage — all the same from here), and run the retention cleanup
    once it is.
    """
    from app.services import log_db_service

    for _ in range(5):
        if await asyncio.to_thread(log_db_service.ensure_schema):
            break
        await asyncio.sleep(3)

    while True:
        try:
            await asyncio.sleep(_log_db_interval.total_seconds())
            if log_db_service.is_available():
                await asyncio.to_thread(log_db_service.cleanup_old)
            else:
                await asyncio.to_thread(log_db_service.ensure_schema)
        except asyncio.CancelledError:
            log.debug("Log-DB-Wartung abgebrochen")
            break
        except Exception as e:
            log.error("Log-DB-Wartung fehlgeschlagen: %s (nächster Versuch in %ds)",
                       e, int(_log_db_interval.total_seconds()))


async def startup() -> None:
    """Called when the FastAPI app starts.

    Schedules background tasks that should run continuously.
    """
    # Schedule the periodic update check as a background task
    # It will run continuously (await asyncio.sleep(24h) in a loop)
    log.info("Starting background tasks")

    # Create a task that runs the periodic check
    asyncio.create_task(check_for_updates_periodic())
    log.debug("Update checker task scheduled")

    asyncio.create_task(maintain_log_db_periodic())
    log.debug("Log-DB-Wartung task scheduled")

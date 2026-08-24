"""Background tasks for ili (startup, periodic checks, etc.)."""
import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger("dashboard.background_tasks")

_last_update_check: datetime | None = None
_check_interval = timedelta(hours=24)


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

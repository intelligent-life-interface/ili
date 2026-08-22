"""FastAPI-Hauptapp des Dashboards (Port 8798).

Strangler-Migration: Routen werden Welle für Welle von trigger_server.py (8799)
hierher migriert; nginx schaltet pro Route um. OpenAPI-Doku: /docs
"""
import logging
import sys
import time
from pathlib import Path

# Dashboard-Dir auf sys.path → Legacy-Module (constants, chat_helpers, ...) sind
# unabhängig vom cwd importierbar (uvicorn, pytest, Hooks)
_DASHBOARD_DIR = Path(__file__).resolve().parents[1]
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.version_service import read_version

# Debug-Logs auf stdout → journalctl (User-Regel: gute Debug-Logs)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("dashboard.api")

app = FastAPI(
    title="Dashboard API",
    description="Kanban-/Projekt-Dashboard — FastAPI-Migration von trigger_server.py",
    version=read_version(),
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Loggt jede Anfrage mit Dauer — zentrale Debug-Sicht.

    try/finally, damit auch unbehandelte Exceptions (die call_next nach oben
    durchreicht) noch geloggt werden, statt spurlos zu verschwinden.
    """
    start = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        dur_ms = (time.monotonic() - start) * 1000
        log.debug("%s %s -> %s (%.1f ms)", request.method, request.url.path, status_code, dur_ms)


@app.exception_handler(StarletteHTTPException)
async def legacy_error_format(request: Request, exc: StarletteHTTPException):
    """Fehlerformat des alten trigger_servers beibehalten: {"error": ...} statt {"detail": ...}.

    Auf Starlette-Ebene registriert, damit auch Routing-404/405 (z.B. tote
    nginx-Catch-all-Routen wie /services-api) das Legacy-Format bekommen.
    """
    log.debug("HTTP %s auf %s: %s", exc.status_code, request.url.path, exc.detail)
    if exc.status_code == 404 and exc.detail == "Not Found":
        # Unbekannte Route — Legacy antwortet exakt mit "not found"
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error_format(request: Request, exc: RequestValidationError):
    """Pydantic-Validierungsfehler ebenfalls im Legacy-{"error": ...}-Format statt {"detail": [...]}."""
    log.debug("422 auf %s: %s", request.url.path, exc.errors())
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msg = err.get("msg", "ungültig")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(status_code=422, content={"error": "; ".join(parts) or "Validierungsfehler"})


@app.exception_handler(Exception)
async def unhandled_error_format(request: Request, exc: Exception):
    """Letzte Sicherheitsnetz: unbehandelte Exceptions als {"error": ...} statt nacktem
    "Internal Server Error"-Plaintext — hält den Legacy-Kontrakt auch im Fehlerfall ein.
    """
    log.error("Unbehandelte Exception auf %s %s", request.method, request.url.path, exc_info=True)
    _maybe_report_to_github(request, exc)
    return JSONResponse(status_code=500, content={"error": "interner Fehler"})


def _maybe_report_to_github(request: Request, exc: Exception) -> None:
    """Opt-in auto report (user_settings.github_auto_report + GitHub login).

    Runs in a thread so the 500 response is never delayed; only the route path
    and the exception reach the report — github_issue_service sanitizes the rest.
    """
    try:
        from app.services import user_settings_service
        if not user_settings_service.load().get("github_auto_report"):
            return
        from app.services import github_auth_service
        if not github_auth_service.status().get("logged_in"):
            log.debug("github_auto_report on, but not logged in — skip")
            return
        import asyncio
        from app.services import github_issue_service
        component = f"{request.method} {request.url.path}"
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, lambda: github_issue_service.report(
            "backend", "", component=component, exc=exc))
        log.debug("GitHub auto report scheduled for %s", component)
    except Exception as rep_exc:  # never let reporting break the error response
        log.warning("GitHub auto report scheduling failed: %s", rep_exc)


@app.get("/health")
def health():
    """Liveness-Check für nginx/Monitoring."""
    return {"status": "ok", "service": "dashboard-api"}


def _register_routers() -> None:
    """Router pro Domäne registrieren — wächst mit den Migrations-Wellen."""
    from app.api import attachments as attachments_api
    from app.api import automat as automat_api
    from app.api import ollama_queue as ollama_queue_api
    from app.api import boards as boards_api
    from app.api import brainstorm as brainstorm_api
    from app.api import chat as chat_api
    from app.api import config as config_api
    from app.api import dashboard as dashboard_api
    from app.api import isehauer as isehauer_api
    from app.api import kanban as kanban_api
    from app.api import manager as manager_api
    from app.api import ki as ki_api
    from app.api import logs as logs_api
    from app.api import misc as misc_api
    from app.api import photos as photos_api
    from app.api import project_files as project_files_api
    from app.api import project_links as project_links_api
    from app.api import recent as recent_api
    from app.api import created as created_api
    from app.api import github_status as github_status_api
    from app.api import fragen as fragen_api
    from app.api import claude_theme as claude_theme_api
    from app.api import ki_search as ki_search_api
    from app.api import wa_whitelist as wa_whitelist_api
    from app.api import token_guard as token_guard_api
    from app.api import usage as usage_api
    from app.api import github_issues as github_issues_api

    app.include_router(config_api.router)
    app.include_router(logs_api.router)
    app.include_router(boards_api.router)
    app.include_router(kanban_api.router)
    app.include_router(ki_api.router)
    app.include_router(wa_whitelist_api.router)
    app.include_router(chat_api.router)
    app.include_router(photos_api.router)
    app.include_router(misc_api.router)
    app.include_router(dashboard_api.router)
    app.include_router(isehauer_api.router)
    app.include_router(attachments_api.router)
    app.include_router(project_links_api.router)
    app.include_router(project_files_api.router)
    app.include_router(automat_api.router)
    app.include_router(ollama_queue_api.router)
    app.include_router(brainstorm_api.router)
    from app.api import user_settings as user_settings_api
    from app.api import inactive_projects as inactive_projects_api

    app.include_router(recent_api.router)
    app.include_router(inactive_projects_api.router)
    app.include_router(created_api.router)
    app.include_router(github_status_api.router)
    app.include_router(user_settings_api.router)
    app.include_router(fragen_api.router)
    app.include_router(claude_theme_api.router)
    app.include_router(ki_search_api.router)
    app.include_router(manager_api.router)
    app.include_router(token_guard_api.router)
    app.include_router(usage_api.router)
    app.include_router(github_issues_api.router)
    log.info("Router registriert: config (W1), boards+kanban (W2/3), ki (W4), chat+photos (W5), misc (W6), logs/streaming (W7), dashboard (Phase 6), isehauer (F1), attachments, web-adressen, brainstorm, recent, github-status, user-settings, manager, token-guard")


_register_routers()

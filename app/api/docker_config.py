"""API-Router: Docker / project-container settings (settings page section "Docker").

Routes:
  GET  /api/docker/status     effective state (mode, overlay, engine, reachable, error)
  GET  /api/docker/config     stored config only (no probe)
  PUT  /api/docker/config     validate + save, returns the new status
  POST /api/docker/test       probe unsaved form values (nothing written)
  GET  /api/docker/env        shell `export` lines for the terminal (ili-claude.sh)
  GET  /api/docker/claude-md  guide the terminal/automat write to /projects/CLAUDE.md
                              (env + claude-md are compose-internal, called from the
                              terminal container, not from the browser)
  GET  /api/docker/ports      reserved host ports per board (range, assignments, free)
  POST /api/docker/ports      reserve a port for a board (idempotent)
  DELETE /api/docker/ports    give a board's port back
  GET  /api/docker/mcp/status  is the ili-docker MCP server registered in the terminal
  POST /api/docker/mcp/setup   register it (400 unless status().reachable is true)
  POST /api/docker/mcp/remove  unregister it (always allowed — the only way back off)

Logic lives in app/services/docker_service.py; this file only maps HTTP.
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.services import docker_service, project_ports_service

log = logging.getLogger("dashboard.api.docker")
router = APIRouter(tags=["docker"])


@router.get("/api/docker/status")
def get_status():
    try:
        return docker_service.status()
    except Exception as e:
        log.error("GET /api/docker/status failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/api/docker/config")
def get_config():
    return docker_service.load_config()


@router.put("/api/docker/config")
def put_config(body: dict):
    try:
        cfg = docker_service.save_config(body or {})
    except ValueError as e:
        # value is an i18n key (docker.err.*) — the page translates it
        log.info("PUT /api/docker/config rejected: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("PUT /api/docker/config failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")
    return {"status": "ok", "config": cfg, "state": docker_service.status(cfg)}


@router.post("/api/docker/test")
def post_test(body: dict):
    """Probe the values from the form without saving them."""
    try:
        return docker_service.status(candidate=body or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("POST /api/docker/test failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/api/docker/env", response_class=PlainTextResponse)
def get_env():
    """Consumed by deploy/terminal/ili-claude.sh: eval "$(curl .../api/docker/env)"."""
    text = docker_service.shell_exports()
    log.debug("GET /api/docker/env → %d line(s)", text.count("\n"))
    return text


@router.get("/api/docker/claude-md", response_class=PlainTextResponse)
def get_claude_md():
    """200 + text = write it; 200 + empty = remove it (mode off); 503 = unknown right now
    (engine/bridge not answering) — the caller keeps whatever file it has."""
    try:
        st = docker_service.status()
    except Exception as e:
        log.error("GET /api/docker/claude-md failed: %s", e)
        return PlainTextResponse("", status_code=503)
    if st["mode"] == "off":
        return ""
    if not st["reachable"]:
        log.debug("claude-md: engine not reachable (%s) → 503, caller keeps its file", st["error"])
        return PlainTextResponse("", status_code=503)
    return docker_service.claude_md(st)


# ── Reserved ports ────────────────────────────────────────────────────────────
# A project container can take a port but not reserve one. ili keeps the books so
# every board has a fixed number that survives restarts — see
# app/services/project_ports_service.py.

@router.get("/api/docker/ports")
def get_ports():
    try:
        return project_ports_service.status()
    except Exception as e:
        log.error("GET /api/docker/ports failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/docker/ports")
def post_ports(board: str = Query(default="")):
    try:
        result = project_ports_service.assign(board)
        if not result.get("ok") and result.get("reason") == "no-board":
            raise HTTPException(status_code=400, detail="board fehlt")
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /api/docker/ports (board=%s) failed: %s", board, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.delete("/api/docker/ports")
def delete_ports(board: str = Query(default="")):
    try:
        return project_ports_service.release(board)
    except Exception as e:
        log.error("DELETE /api/docker/ports (board=%s) failed: %s", board, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


# ── MCP server for container control (Settings → Docker → MCP switch) ─────────
# Warning shown next to the switch in the GUI: the AI can start, stop and remove
# containers with it — over the socket path that is effectively root on the host.

@router.get("/api/docker/mcp/status")
def get_mcp_status():
    try:
        return docker_service.mcp_status()
    except Exception as e:
        log.error("GET /api/docker/mcp/status failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/docker/mcp/setup")
def post_mcp_setup():
    try:
        st = docker_service.status()
        if not st.get("reachable"):
            raise HTTPException(status_code=400, detail="docker.mcp.err.not_reachable")
        return docker_service.mcp_setup()
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /api/docker/mcp/setup failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/docker/mcp/remove")
def post_mcp_remove():
    try:
        return docker_service.mcp_remove()
    except Exception as e:
        log.error("POST /api/docker/mcp/remove failed: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

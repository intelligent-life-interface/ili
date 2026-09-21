"""API-Router: SSH access status (settings page section "SSH-Zugang").

Routes:
  GET  /api/ssh/status     is sshd in the terminal container answering? + configured bind/port

Read-only by design (Variante A, Manager decision 2026-09-20): the api never receives
the public key and has no writable mount. The setup command is assembled in the
browser (html/js/ssh-settings.js) and run by the operator on the host.
Logic lives in app/services/ssh_status_service.py.
"""
import logging

from fastapi import APIRouter, HTTPException

from app.services import ssh_status_service

log = logging.getLogger("dashboard.api.ssh")
router = APIRouter(tags=["ssh"])


@router.get("/api/ssh/status")
def get_ssh_status():
    """Return SSH status: state (ok|sshd_down|no_terminal|unknown), sshd_running,
    ssh_port/ssh_bind (configuration), lan_exposed, overlay_in_env."""
    try:
        return ssh_status_service.get_status()
    except Exception as e:  # get_status never raises; belt and braces for the route
        log.error("GET /api/ssh/status failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="SSH-Status konnte nicht ermittelt werden")

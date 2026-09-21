"""SSH access status (read-only) for the settings section "SSH-Zugang".

Where sshd lives: in the *terminal* container, listening on its internal port 22.
The api container shares the compose network with it, so `terminal:22` is the one
address the api can actually probe. The published host port (SSH_PORT, default 2222)
and bind (SSH_BIND) are only *configuration* from the api's point of view — it cannot
connect to them, and it must not pretend it did.

Configuration comes from the api's own environment: docker-compose.terminal.yml gives
the api `env_file: .env`, so SSH_BIND / SSH_PORT / COMPOSE_FILE from the operator's
.env are visible here without any extra mount (Variante A, 2026-09-20: no writable
mount, the public key never reaches the api).

States (`state`), from most to least healthy:
  ok               terminal container reachable, sshd answers on :22
  sshd_down        terminal container reachable, nothing listens on :22
                   -> overlay not active, or no key in ./ssh/authorized_keys
  no_terminal      `terminal` does not resolve -> terminal overlay not started
  unknown          probe failed for another reason
"""
import logging
import os
import socket

log = logging.getLogger("dashboard.services.ssh_status")

PROBE_HOST = os.environ.get("ILI_SSH_PROBE_HOST", "terminal")
PROBE_PORT = 22  # sshd_config: Port 22 inside the container, fixed
PROBE_TIMEOUT = 2.0
DEFAULT_PORT = 2222
DEFAULT_BIND = "127.0.0.1"
SSH_OVERLAY = "docker-compose.ssh.yml"


def probe_sshd(host: str = None, port: int = PROBE_PORT, timeout: float = PROBE_TIMEOUT) -> str:
    """Probe host:port. Returns 'open', 'closed', 'no_host' or 'error'."""
    host = host or PROBE_HOST
    try:
        with socket.create_connection((host, port), timeout=timeout):
            log.debug("ssh probe %s:%d -> open", host, port)
            return "open"
    except socket.gaierror as e:
        log.debug("ssh probe %s:%d -> host does not resolve: %s", host, port, e)
        return "no_host"
    except (ConnectionRefusedError, socket.timeout, TimeoutError) as e:
        log.debug("ssh probe %s:%d -> closed (%s)", host, port, e.__class__.__name__)
        return "closed"
    except OSError as e:
        log.warning("ssh probe %s:%d failed: %s", host, port, e)
        return "error"


def _port_from_env(raw: str) -> int:
    """SSH_PORT from the environment; anything invalid falls back to the default."""
    try:
        port = int(str(raw).strip())
        if 1 <= port <= 65535:
            return port
    except (TypeError, ValueError):
        pass
    log.warning("SSH_PORT %r is not a valid port, showing default %d", raw, DEFAULT_PORT)
    return DEFAULT_PORT


def get_status(environ=None, probe=probe_sshd) -> dict:
    """Build the status dict for GET /api/ssh/status. Never raises."""
    env = os.environ if environ is None else environ
    ssh_port = _port_from_env(env.get("SSH_PORT") or DEFAULT_PORT)
    ssh_bind = (env.get("SSH_BIND") or DEFAULT_BIND).strip() or DEFAULT_BIND
    compose_file = env.get("COMPOSE_FILE", "")
    overlay_listed = SSH_OVERLAY in compose_file

    result = probe()
    state = {"open": "ok", "closed": "sshd_down", "no_host": "no_terminal"}.get(result, "unknown")

    status = {
        "state": state,
        "sshd_running": state == "ok",
        "ssh_port": ssh_port,
        "ssh_bind": ssh_bind,
        "lan_exposed": ssh_bind not in ("127.0.0.1", "localhost", "::1"),
        # None = COMPOSE_FILE not visible to the api (e.g. set in the shell, not .env)
        "overlay_in_env": overlay_listed if compose_file else None,
    }
    log.debug("ssh status: %s", status)
    return status

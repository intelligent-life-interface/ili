"""docker_service — how the ili AI reaches a Docker engine for project containers.

Single source for the "Docker / project containers" section of the settings page
and for the environment the terminal and the automat hand to Claude Code.

Config file: ``AUTOMAT_STATE_DIR/docker_config.json`` (same volume as ai_config.json,
mounted in api AND automat; the terminal asks the api via GET /api/docker/env).

Modes
-----
auto    use whatever the compose overlay provides (docker-compose.sandbox.yml sets
        DOCKER_HOST=tcp://sandbox:2376 + TLS, docker-compose.hostdocker.yml mounts
        the host socket). Nothing can be switched at runtime here — the GUI only
        shows the status and the exact commands.
remote  DOCKER_HOST=tcp://<host>:<port> set at runtime (no restart, no re-mount).
        Typical: Docker Desktop with "Expose daemon on tcp://localhost:2375" →
        tcp://host.docker.internal:2375. Anything beyond localhost must use TLS
        (2376) — an unprotected TCP daemon is root for the whole LAN.
off     the AI is told not to build/run containers; no DOCKER_* is injected.

Probing: the api itself has no socket in the socket-mount overlay (only terminal
and automat get it), so the reliable probe runs in the terminal container through
the Claude bridge (POST /docker/probe, `docker version`). The api-side probe via
the engine HTTP API is the fallback when the terminal is not running.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.storage.atomic_write import write_json_atomic
from app.storage.locking import file_lock
from constants import AI_CONFIG_FILE, CLAUDE_BRIDGE_URL

log = logging.getLogger("dashboard.services.docker_service")

DOCKER_CONFIG_FILE = AI_CONFIG_FILE.with_name("docker_config.json")
_LOCK = DOCKER_CONFIG_FILE.with_name(DOCKER_CONFIG_FILE.name + ".lock")

MODES = ("auto", "remote", "off")
DEFAULTS = {
    "mode": "auto",
    "host": "",            # remote only: tcp://host:port
    "tls_verify": False,   # remote only: DOCKER_TLS_VERIFY=1
    "cert_path": "",       # remote only: DOCKER_CERT_PATH (folder mounted in terminal+automat)
    "updated_at": "",
}
# Port range the sandbox gateway forwards by default (docker-compose.sandbox.yml) and
# the convention for host-published project ports in the socket overlay.
def _int_env(name: str, default: int) -> int:
    """Numeric .env value with a safe default — a typo must not take the whole API down
    (this module is imported while the routers register)."""
    raw = os.environ.get(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        log.warning("%s=%r is not a number — using %d", name, raw, default)
        return default


PORT_RANGE = (_int_env("SANDBOX_PORT_FROM", 8100), _int_env("SANDBOX_PORT_TO", 8119))

_HOST_RE = re.compile(r"^tcp://[A-Za-z0-9._-]+(:\d{1,5})?$")
_PROBE_TIMEOUT_S = 12


# ── config ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """docker_config.json → full dict (defaults filled in, never KeyError)."""
    try:
        data = json.loads(DOCKER_CONFIG_FILE.read_text())
        cfg = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    except FileNotFoundError:
        cfg = dict(DEFAULTS)
    except Exception as e:  # corrupt file → defaults, but say so
        log.warning("docker_config.json unreadable (%s) — using defaults", e)
        cfg = dict(DEFAULTS)
    if cfg["mode"] not in MODES:
        log.warning("docker_config.json: unknown mode %r → auto", cfg["mode"])
        cfg["mode"] = "auto"
    log.debug("docker config loaded: mode=%s host=%s", cfg["mode"], cfg["host"] or "-")
    return cfg


def validate(data: dict) -> dict:
    """Normalise + validate a (partial) config. Raises ValueError with a user-facing key."""
    cfg = {**load_config(), **{k: v for k, v in (data or {}).items() if k in DEFAULTS}}
    mode = str(cfg.get("mode") or "auto").strip().lower()
    if mode not in MODES:
        raise ValueError("docker.err.mode")
    host = str(cfg.get("host") or "").strip()
    if mode == "remote":
        if not host:
            raise ValueError("docker.err.host_required")
        if not _HOST_RE.match(host):
            raise ValueError("docker.err.host_format")
    cert_path = str(cfg.get("cert_path") or "").strip()
    if cert_path and not cert_path.startswith("/"):
        raise ValueError("docker.err.cert_path")
    return {
        "mode": mode,
        "host": host,
        "tls_verify": bool(cfg.get("tls_verify")),
        "cert_path": cert_path,
        "updated_at": cfg.get("updated_at") or "",
    }


def save_config(data: dict) -> dict:
    """Validate + write. The whole read-modify-write runs under the lock (validate() merges
    the partial body over the stored file), otherwise two parallel PUTs lose one update.
    load_config() takes no lock itself, so calling validate() inside is safe."""
    DOCKER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_LOCK):
        cfg = validate(data)
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_json_atomic(DOCKER_CONFIG_FILE, cfg)
    log.info("docker config saved: mode=%s host=%s tls=%s", cfg["mode"], cfg["host"] or "-",
             cfg["tls_verify"])
    return cfg


# ── environment for Claude Code (terminal + automat) ────────────────────────

DOCKER_ENV_KEYS = ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")


def env_overrides(cfg: dict | None = None) -> dict:
    """DOCKER_* variables for the given config. Empty dict for auto/off — `auto`
    inherits the compose overlay, `off` must not add anything.

    In `remote` mode ALL three keys are returned; an empty value means "unset it":
    the sandbox overlay leaves DOCKER_TLS_VERIFY=1 + DOCKER_CERT_PATH in the
    environment, and a plain tcp://…:2375 host would otherwise fail the TLS handshake.
    """
    cfg = cfg or load_config()
    if cfg["mode"] != "remote" or not cfg["host"]:
        return {}
    return {
        "DOCKER_HOST": cfg["host"],
        "DOCKER_TLS_VERIFY": "1" if cfg["tls_verify"] else "",
        "DOCKER_CERT_PATH": cfg["cert_path"] or "",
    }


def apply_overrides(env: dict, overrides: dict) -> dict:
    """Apply env_overrides() to a process environment: set non-empty, drop empty."""
    for k, v in overrides.items():
        if v:
            env[k] = v
        else:
            env.pop(k, None)
    return env


def shell_exports(cfg: dict | None = None) -> str:
    """`export K='v'` / `unset K` lines for `eval` in ili-claude.sh. Values are
    single-quoted; a literal quote in a value is escaped the POSIX way."""
    lines = []
    for k, v in env_overrides(cfg).items():
        if v:
            safe = v.replace("'", "'\\''")
            lines.append(f"export {k}='{safe}'")
        else:
            lines.append(f"unset {k}")
    return "\n".join(lines) + ("\n" if lines else "")


def overlay_of(docker_host: str) -> str:
    """Classify the effective DOCKER_HOST: sandbox | socket | remote | none."""
    h = (docker_host or "").strip()
    if not h:
        return "none"
    if h.startswith("tcp://sandbox:"):
        return "sandbox"
    if h.startswith("unix://"):
        return "socket"
    return "remote"


# ── probes ──────────────────────────────────────────────────────────────────

def _engine_from_version_json(v: dict) -> dict:
    """Normalise `docker version` (Server block) or GET /version JSON."""
    platform = v.get("Platform") or {}
    return {
        "name": platform.get("Name") or ("Podman" if "podman" in json.dumps(v).lower() else "Docker"),
        "version": v.get("Version", "?"),
        "api_version": v.get("ApiVersion", "?"),
        "os": v.get("Os", "?"),
        "arch": v.get("Arch", "?"),
    }


def probe_via_bridge(overrides: dict | None = None, timeout: int = _PROBE_TIMEOUT_S) -> dict | None:
    """Ask the terminal container (Claude bridge) to run `docker version`.
    Returns the bridge answer or None when the bridge is unreachable."""
    payload = {"env": overrides or {}}
    req = urllib.request.Request(
        f"{CLAUDE_BRIDGE_URL}/docker/probe",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 3) as r:
            body = json.loads(r.read().decode("utf-8"))
        log.debug("bridge probe: ok=%s host=%s", body.get("ok"), body.get("docker_host"))
        return body
    except urllib.error.HTTPError as e:
        if e.code == 404:  # older terminal image without the endpoint
            log.info("bridge has no /docker/probe (old terminal image)")
            return None
        log.warning("bridge probe HTTP %s: %s", e.code, e)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.info("bridge probe unavailable: %s", e)
        return None


def probe_via_api(docker_host: str, tls_verify: bool = False, cert_path: str = "",
                  timeout: int = _PROBE_TIMEOUT_S) -> dict:
    """Talk to the engine HTTP API (GET /version) from the api container.
    Works for unix:// sockets and tcp:// hosts (TLS when tls_verify + cert_path)."""
    host = (docker_host or "").strip()
    result = {"ok": False, "docker_host": host, "engine": None, "error": ""}
    if not host:
        result["error"] = "no DOCKER_HOST"
        return result
    try:
        if host.startswith("unix://"):
            path = host[len("unix://"):]
            if not Path(path).exists():
                result["error"] = f"socket {path} not found"
                return result
            transport = httpx.HTTPTransport(uds=path)
            with httpx.Client(transport=transport, timeout=timeout) as c:
                r = c.get("http://docker/version")
        elif host.startswith("tcp://"):
            base = host[len("tcp://"):]
            if tls_verify:
                cert_dir = Path(cert_path or "")
                verify = str(cert_dir / "ca.pem") if cert_path else True
                cert = ((str(cert_dir / "cert.pem"), str(cert_dir / "key.pem"))
                        if cert_path and (cert_dir / "cert.pem").exists() else None)
                with httpx.Client(verify=verify, cert=cert, timeout=timeout) as c:
                    r = c.get(f"https://{base}/version")
            else:
                with httpx.Client(timeout=timeout) as c:
                    r = c.get(f"http://{base}/version")
        else:
            result["error"] = f"unsupported DOCKER_HOST scheme for api-side probe: {host}"
            return result
        r.raise_for_status()
        result["ok"] = True
        result["engine"] = _engine_from_version_json(r.json())
        log.debug("api probe ok: %s %s", result["engine"]["name"], result["engine"]["version"])
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        log.info("api probe failed for %s: %s", host, result["error"])
    return result


def status(cfg: dict | None = None, candidate: dict | None = None) -> dict:
    """Effective state for the settings page.

    candidate: unsaved form values (POST /api/docker/test) — probed instead of the
    stored config, nothing is written.
    """
    cfg = validate(candidate) if candidate is not None else (cfg or load_config())
    overrides = env_overrides(cfg)
    out = {
        "mode": cfg["mode"],
        "host": cfg["host"],
        "tls_verify": cfg["tls_verify"],
        "cert_path": cfg["cert_path"],
        "updated_at": cfg["updated_at"],
        "port_range": list(PORT_RANGE),
        "reachable": False,
        "engine": None,
        "docker_host": "",
        "overlay": "none",
        "projects_host_dir": "",
        "probe_source": "none",
        "error": "",
    }
    if cfg["mode"] == "off":
        out["probe_source"] = "skipped"
        log.debug("docker status: mode off, no probe")
        return out

    bridge = probe_via_bridge(overrides)
    if bridge is not None:
        out.update({
            "probe_source": "terminal",
            "reachable": bool(bridge.get("ok")),
            "engine": bridge.get("engine"),
            "docker_host": bridge.get("docker_host") or "",
            "projects_host_dir": bridge.get("projects_host_dir") or "",
            "error": bridge.get("error") or "",
        })
    else:
        # terminal not running / old image → best effort from the api container.
        # remote: exactly what the config says (empty = unset, never the api's own
        # sandbox TLS leftovers); auto: whatever the overlay gave the api.
        src = overrides if overrides else os.environ
        effective_host = src.get("DOCKER_HOST", "")
        api = probe_via_api(
            effective_host,
            tls_verify=bool(src.get("DOCKER_TLS_VERIFY")),
            cert_path=src.get("DOCKER_CERT_PATH", ""),
        )
        out.update({
            "probe_source": "api",
            "reachable": api["ok"],
            "engine": api["engine"],
            "docker_host": effective_host,
            "projects_host_dir": os.environ.get("PROJECTS_HOST_DIR", ""),
            "error": api["error"] if not api["ok"] else "",
        })
    out["overlay"] = overlay_of(out["docker_host"])
    log.info("docker status: mode=%s overlay=%s reachable=%s via=%s", out["mode"], out["overlay"],
             out["reachable"], out["probe_source"])
    return out


# ── guide for the AI (/projects/CLAUDE.md) ──────────────────────────────────

def claude_md(st: dict | None = None) -> str:
    """Markdown the terminal/automat write to /projects/CLAUDE.md so every Claude
    session under /projects/<board> knows how containers work here. Empty string =
    remove the file (mode off or nothing reachable). English on purpose: it is
    read by the AI, not shown in the GUI."""
    st = st or status()
    if st["mode"] == "off" or not st["reachable"]:
        return ""
    lo, hi = st["port_range"]
    overlay = st["overlay"]
    eng = st.get("engine") or {}
    lines = [
        "# Project containers (generated by ili — do not edit, see Settings → Docker)",
        "",
        f"A container engine is available: {eng.get('name', 'Docker')} {eng.get('version', '')} "
        f"({eng.get('os', '?')}/{eng.get('arch', '?')}) via `DOCKER_HOST={st['docker_host']}`.",
        "The `docker` CLI in this terminal already points at it — no setup needed.",
        "",
        "Rules:",
        f"- Publish project ports in the range {lo}–{hi} (`-p {lo}:<container-port>`)"
        + (" — the gateway only forwards this range, anything else is unreachable from the browser."
           if overlay == "sandbox" else
           " — convention so project ports never collide with ili itself (8080/8798)."),
        "- Name containers after the board (`--name <board>`), add `--restart unless-stopped` "
        "so they survive an engine restart, and build from the project folder "
        "(`docker build -t <board> /projects/<board>`).",
    ]
    if overlay == "socket" or overlay == "remote":
        host_dir = st.get("projects_host_dir") or ""
        if host_dir:
            lines += [
                "- Bind mounts are resolved by the HOST engine, so they need host paths: "
                f"`-v \"{host_dir}/projects/<board>:/app\"` — NOT `/projects/<board>` "
                "(that path only exists inside this terminal and would give you an empty directory).",
            ]
        else:
            lines += [
                "- Bind mounts are resolved by the HOST engine and need HOST paths, but "
                "PROJECTS_HOST_DIR is not configured here — do not guess a path: ask the user "
                "for the host folder that contains `projects/`, or build the project into the "
                "image (`COPY`) instead of mounting it.",
            ]
        if overlay == "socket":
            lines += ["- You are on the host engine: never stop, remove or prune containers "
                      "you did not create for this board (`ili-*` are ili itself)."]
    if overlay == "sandbox":
        lines += [
            "- This is an isolated Docker-in-Docker sandbox: bind mounts use `/projects/<board>` "
            "directly, and `docker system prune` only affects the sandbox.",
            "- A published port only works after the gateway forwards it — stay inside the range.",
        ]
    lines += [
        "",
        "Check with `docker ps` before creating; reuse an existing container for the board.",
        "",
    ]
    return "\n".join(lines)

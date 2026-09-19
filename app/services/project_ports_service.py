"""One reserved host port per board, stable across restarts.

Why this exists: a project container can *take* a port, it cannot *reserve* one —
by the time it runs, someone else may hold the number. So the assignment is made
here, once per board, and everyone else reads it: the AI guide written into
/projects/CLAUDE.md, the settings page, and the person typing `docker run`.

The range is the same one the sandbox gateway already forwards
(SANDBOX_PORT_FROM..SANDBOX_PORT_TO, default 8100-8119), so an assignment works on
both paths: in the sandbox the gateway forwards it, on the host socket the project
container publishes it directly and nothing collides because ili keeps the books.

Storage: project_ports.json next to ai_config.json (the automat state volume —
shared by api, terminal and automat, and it survives an update).
"""
import json
import logging
import os
from pathlib import Path

from constants import AI_CONFIG_FILE

log = logging.getLogger("dashboard.services.project_ports")

PORTS_FILE: Path = AI_CONFIG_FILE.with_name("project_ports.json")


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, "")).strip() or default)
    except ValueError:
        log.warning("%s is not a number — using %s", name, default)
        return default


def port_range() -> tuple[int, int]:
    """(from, to) — same range the sandbox gateway publishes."""
    lo = _int_env("SANDBOX_PORT_FROM", 8100)
    hi = _int_env("SANDBOX_PORT_TO", 8119)
    if hi < lo:
        log.warning("SANDBOX_PORT_TO (%s) below SANDBOX_PORT_FROM (%s) — swapping", hi, lo)
        lo, hi = hi, lo
    return lo, hi


def _load() -> dict[str, int]:
    try:
        with open(PORTS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        ports = {str(k): int(v) for k, v in (data.get("ports") or {}).items()}
        log.debug("project_ports.json: %d assignment(s)", len(ports))
        return ports
    except FileNotFoundError:
        return {}
    except Exception as e:                      # corrupt file must not break the API
        log.error("project_ports.json unreadable (%s) — starting empty", e)
        return {}


def _save(ports: dict[str, int]) -> None:
    PORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PORTS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"ports": ports}, fh, indent=2, sort_keys=True)
    tmp.replace(PORTS_FILE)                     # atomic: never leave a half-written file
    log.info("project_ports.json written (%d assignment(s))", len(ports))


def get(board: str) -> int | None:
    """Port of this board, or None when it has none yet."""
    return _load().get((board or "").strip()) or None


def assign(board: str) -> dict:
    """Give this board a port (idempotent: an existing one is returned unchanged).

    Returns {ok, board, port, created} or {ok: False, reason}.
    """
    board = (board or "").strip()
    if not board:
        return {"ok": False, "reason": "no-board"}
    ports = _load()
    if board in ports:
        return {"ok": True, "board": board, "port": ports[board], "created": False}

    lo, hi = port_range()
    taken = set(ports.values())
    for candidate in range(lo, hi + 1):
        if candidate not in taken:
            ports[board] = candidate
            _save(ports)
            log.info("board '%s' reserved port %d", board, candidate)
            return {"ok": True, "board": board, "port": candidate, "created": True}

    log.warning("no free port for '%s' in %d-%d (%d assigned)", board, lo, hi, len(ports))
    return {"ok": False, "reason": "range-full", "range": [lo, hi], "assigned": len(ports)}


def release(board: str) -> dict:
    """Free a board's port again (deleted board, or a deliberate re-assignment)."""
    board = (board or "").strip()
    ports = _load()
    if board not in ports:
        return {"ok": True, "board": board, "released": False}
    port = ports.pop(board)
    _save(ports)
    log.info("board '%s' released port %d", board, port)
    return {"ok": True, "board": board, "port": port, "released": True}


def status() -> dict:
    """Everything the settings page and the AI guide need in one call."""
    lo, hi = port_range()
    ports = _load()
    taken = set(ports.values())
    free = [p for p in range(lo, hi + 1) if p not in taken]
    return {
        "range": [lo, hi],
        "total": hi - lo + 1,
        "assignments": [{"board": b, "port": p} for b, p in sorted(ports.items(), key=lambda kv: kv[1])],
        "free": free,
        "free_count": len(free),
    }

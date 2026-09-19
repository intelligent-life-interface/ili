"""Does this installation actually work? One answer for humans and for the AI.

The question "are all containers running?" cannot be answered from here: the api
container deliberately has no access to the container engine (decision 2026-08-24,
no socket = no root-equivalent inside ili). So this checks what can be checked
honestly — whether every part *answers* — and says "not checkable" where it cannot
look, instead of reporting a green light it did not earn.

Each check is isolated: a failing one never breaks the others, everything has a
short timeout, and the overall result is a plain list. Callers: GET /api/selftest
(settings page) and `ili-selftest` in the terminal (the AI runs that one).
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from constants import CLAUDE_BRIDGE_URL

log = logging.getLogger("dashboard.services.selftest")

_TIMEOUT_S = 3.0
_WEB_URL = os.environ.get("ILI_SELFTEST_WEB_URL", "http://web")


def _get_json(url: str, timeout: float = _TIMEOUT_S) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(raw)
        except json.JSONDecodeError:
            return r.status, raw


def _check(check_id: str, title: str, fn) -> dict:
    """Run one probe. Never raises: a broken check is a failed check, not a 500."""
    started = time.monotonic()
    try:
        ok, detail, hint = fn()
    except Exception as e:                      # noqa: BLE001 — every probe is untrusted
        log.info("selftest %s failed: %s", check_id, e)
        ok, detail, hint = False, f"{type(e).__name__}: {e}", "Logs des Dienstes ansehen"
    return {
        "id": check_id,
        "title": title,
        "ok": bool(ok),
        "detail": detail,
        "hint": hint if not ok else "",
        "ms": int((time.monotonic() - started) * 1000),
    }


# ── the individual probes ─────────────────────────────────────────────────────

def _probe_api() -> tuple[bool, str, str]:
    from app.services.version_service import version_info
    v = version_info()
    detail = f"{v['version']} (commit {v['commit'][:7]}, gebaut {v['build_date'][:10]})"
    if v["commit"] == "unknown":
        # Self-built images have no build metadata — true, but not a fault.
        return True, detail + " — selbst gebaut, ohne Build-Daten", ""
    return True, detail, ""


def _probe_web() -> tuple[bool, str, str]:
    """web must reach api: this is the proxy path every browser request takes."""
    status, body = _get_json(f"{_WEB_URL}/api/version")
    if status != 200 or not isinstance(body, dict):
        return False, f"HTTP {status}", "nginx-Logs: docker compose logs web"
    return True, f"nginx → api ok (meldet {body.get('version', '?')})", ""


def _probe_projterm() -> tuple[bool, str, str]:
    """401 = the terminal route is up and asks for the password (correct).
    503 = the terminal container is not running (overlay missing or stopped)."""
    try:
        status, _ = _get_json(f"{_WEB_URL}/projterm/")
    except urllib.error.HTTPError as e:
        status = e.code
    if status == 401:
        return True, "Route aktiv, fragt nach Passwort (401)", ""
    if status == 503:
        return False, "503 — Terminal-Container läuft nicht", \
            "Terminal-Overlay starten: docker compose up -d (COMPOSE_FILE prüfen)"
    return False, f"unerwartet HTTP {status}", "docker compose logs web"


def _probe_bridge() -> tuple[bool, str, str]:
    """The Claude bridge lives in the terminal container and answers for it."""
    status, body = _get_json(f"{CLAUDE_BRIDGE_URL}/health")
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        return False, f"HTTP {status}", "docker compose logs terminal"
    ver = body.get("claude_version") or "?"
    return True, f"Terminal erreichbar, Claude {ver}", ""


def _probe_db() -> tuple[bool, str, str]:
    from app.services import log_db_service
    if not log_db_service._dsn_configured():
        return True, "nicht konfiguriert (optional)", ""
    conn = log_db_service._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    finally:
        conn.close()
    return True, "PostgreSQL antwortet", ""


def _probe_automat() -> tuple[bool, str, str]:
    """The ticker writes a heartbeat into the shared state volume every tick."""
    from constants import AI_CONFIG_FILE
    hb = AI_CONFIG_FILE.with_name("ticker_heartbeat.json")
    if not hb.exists():
        return False, "kein Lebenszeichen", \
            "Automat läuft nicht oder ist älter als 0.1.21: docker compose logs automat"
    data = json.loads(hb.read_text(encoding="utf-8"))
    age = max(0, int(time.time() - float(data.get("ts", 0))))
    interval = int(data.get("interval", 300))
    if age > interval * 3:
        return False, f"letztes Lebenszeichen vor {age}s (Takt {interval}s)", \
            "docker compose logs automat — Ticker hängt oder ist gestoppt"
    return True, f"aktiv, letztes Lebenszeichen vor {age}s", ""


def _probe_docker() -> tuple[bool, str, str]:
    from app.services import docker_service
    st = docker_service.status()
    if st["mode"] == "off":
        return True, "abgeschaltet (Einstellungen → Docker)", ""
    if not st.get("reachable"):
        return False, st.get("error") or "nicht erreichbar", \
            "Einstellungen → Docker: Verbindung testen"
    eng = st.get("engine") or {}
    return True, f"{eng.get('name', 'Docker')} {eng.get('version', '')} über {st['docker_host']}", ""


def _probe_ports() -> tuple[bool, str, str]:
    from app.services import project_ports_service
    st = project_ports_service.status()
    lo, hi = st["range"]
    if st["free_count"] == 0:
        return False, f"Bereich {lo}–{hi} voll belegt", \
            "Nicht mehr genutzte Ports freigeben oder SANDBOX_PORT_TO erhöhen"
    return True, f"Bereich {lo}–{hi}, {len(st['assignments'])} vergeben, {st['free_count']} frei", ""


def _probe_boards() -> tuple[bool, str, str]:
    from app.services import board_service
    boards = board_service.list_boards()
    boards = boards.get("boards", boards) if isinstance(boards, dict) else boards
    n = len(boards or [])
    if n == 0:
        return False, "keine Boards", "Seed fehlt: Volume leer? docker compose logs api"
    return True, f"{n} Projekte lesbar", ""


CHECKS = (
    ("api", "API", _probe_api),
    ("web", "Weboberfläche", _probe_web),
    ("boards", "Projekte", _probe_boards),
    ("projterm", "Projekt-Terminal", _probe_projterm),
    ("claude", "Claude im Terminal", _probe_bridge),
    ("automat", "Automat", _probe_automat),
    ("db", "PostgreSQL", _probe_db),
    ("docker", "Docker", _probe_docker),
    ("ports", "Projekt-Ports", _probe_ports),
)


def run() -> dict:
    """All checks. `ok` is true only when every check passed."""
    started = time.monotonic()
    checks = [_check(cid, title, fn) for cid, title, fn in CHECKS]
    failed = [c["id"] for c in checks if not c["ok"]]
    result = {
        "ok": not failed,
        "failed": failed,
        "checks": checks,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "note": "Container-Zustände (läuft / Neustarts) sind von hier nicht sichtbar: "
                "die api hat bewusst keinen Zugriff auf die Container-Engine. "
                "Geprüft wird, ob jeder Teil antwortet.",
    }
    log.info("selftest: %s (%d Prüfungen, %d ms)",
             "ok" if result["ok"] else f"Funde: {', '.join(failed)}",
             len(checks), result["duration_ms"])
    return result

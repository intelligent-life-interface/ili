#!/usr/bin/env python3
"""ili automat ticker — replaces the systemd timer of the home stack.

Runs `orchestrator.py --tick` every AUTOMAT_INTERVAL seconds (default 300) inside the
terminal image (the worker needs the logged-in Claude Code CLI). Honours the kill switch
`state/automat.disabled` (touch it to pause, remove it to resume) and waits for the
dashboard API before the first tick.
"""
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "state"
DISABLED = STATE / "automat.disabled"
INTERVAL = int(os.getenv("AUTOMAT_INTERVAL", "300"))
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://api:8798").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ticker] %(levelname)s %(message)s",
                    stream=sys.stderr)
log = logging.getLogger("ticker")


def api_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{DASHBOARD_URL}/boards", timeout=5):
            return True
    except Exception as e:
        log.debug("api not ready (%s): %s", DASHBOARD_URL, e)
        return False


def _stop(signum, frame) -> None:
    log.info("signal %s — stopping ticker", signum)
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    STATE.mkdir(parents=True, exist_ok=True)
    if os.getenv("ILI_AUTOMAT_BACKFILL", "0") != "1":
        # The backfill/idle-filler needs the dashboard's advisor venv, which the
        # release does not ship — keep it off unless explicitly enabled.
        (STATE / "backfill.disabled").touch()
    log.info("start: interval=%ss dashboard=%s state=%s", INTERVAL, DASHBOARD_URL, STATE)
    waited = 0
    while not api_ready():
        if waited % 60 == 0:
            log.info("waiting for dashboard api at %s …", DASHBOARD_URL)
        time.sleep(5)
        waited += 5
    while True:
        if DISABLED.exists():
            log.info("paused: %s exists", DISABLED)
        else:
            t0 = time.time()
            r = subprocess.run([sys.executable, str(BASE / "orchestrator.py"), "--tick"],
                               cwd=str(BASE))
            log.info("tick done rc=%s in %.1fs", r.returncode, time.time() - t0)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

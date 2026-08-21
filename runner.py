#!/usr/bin/env python3
"""Minimaler Webhook-Runner für n8n. Führt registrierte Scripts aus wenn n8n POST schickt."""
import hmac
import json
import logging
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

from constants import CONTAINERS_BASE

logging.basicConfig(level=logging.INFO, format="%(asctime)s [runner] %(message)s")
log = logging.getLogger("runner")

# opt_runner_auth_0809: Port 8800 lauscht auf 0.0.0.0 (LAN-weit erreichbar) ohne diesen
# Header wäre jeder registrierte Subprozess von jedem LAN-Client startbar. Bind bleibt
# 0.0.0.0, weil n8n als Podman-Container über host.containers.internal zugreift — von dort
# ist 127.0.0.1 des Hosts NICHT erreichbar, ein Bind-Downgrade würde den (aktuell inaktiven,
# aber vorgesehenen) n8n-Aufrufpfad kaputt machen. Das Secret ist darum der einzige Schutz.
RUNNER_WEBHOOK_SECRET = os.environ.get("RUNNER_WEBHOOK_SECRET", "")
if not RUNNER_WEBHOOK_SECRET:
    log.warning("RUNNER_WEBHOOK_SECRET nicht gesetzt — alle Requests werden mit 401 abgelehnt!")

SCRIPTS = {
    # Der Dashboard-Generator-Eintrag wurde ENTFERNT (opt_altlasten_0806): generate_dashboard.py
    # ueberschrieb das handgepflegte html/index.html/services.html/scan.html mit veralteten
    # Generator-Versionen und war ueber diesen Auth-losen Webhook (Port 8800) ausloesbar. Das
    # Skript liegt jetzt in archiv/. Kein Ersatz noetig — Aggregat laeuft ueber app/api/dashboard.py.
    "rpa-energyportal":        ["/usr/bin/python3", str(CONTAINERS_BASE / "rpa/energyportal/thurplus_influx.py")],
    "rpa-calendar":        ["/usr/bin/python3", str(CONTAINERS_BASE / "rpa/calendar-clinic/calendar_sync.py")],
}

for _name, _cmd in SCRIPTS.items():
    _script_path = _cmd[1]
    if not os.path.exists(_script_path):
        log.error(f"SCRIPTS[{_name!r}] zeigt auf nicht existierenden Pfad: {_script_path}")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def _respond(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        got = self.headers.get("X-Runner-Secret", "")
        ok = bool(RUNNER_WEBHOOK_SECRET) and hmac.compare_digest(got, RUNNER_WEBHOOK_SECRET)
        if not ok:
            log.warning(f"Auth fehlgeschlagen von {self.client_address[0]} für {self.path!r}")
        return ok

    def do_POST(self):
        if not self._authorized():
            self._respond(401, {"error": "unauthorized"})
            return
        name = self.path.lstrip("/")
        if name not in SCRIPTS:
            log.warning(f"Unbekanntes Script: {name!r}")
            self._respond(404, {"error": f"unknown script: {name}"})
            return

        cmd = SCRIPTS[name]
        log.info(f"Starte: {name} → {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = result.returncode == 0
            log.info(f"{name} beendet: rc={result.returncode}")
            if result.stderr:
                log.debug(f"{name} stderr: {result.stderr[:200]}")
            self._respond(200 if ok else 500, {
                "ok": ok, "script": name, "rc": result.returncode,
                "stdout": result.stdout[-500:], "stderr": result.stderr[-200:]
            })
        except subprocess.TimeoutExpired:
            log.error(f"{name} Timeout nach 120s")
            self._respond(504, {"error": "timeout", "script": name})
        except Exception as e:
            log.error(f"{name} Fehler: {e}")
            self._respond(500, {"error": str(e), "script": name})

    def do_GET(self):
        self._respond(200, {"status": "ok", "scripts": list(SCRIPTS.keys())})

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8800), Handler)
    log.info("Runner gestartet auf Port 8800")
    server.serve_forever()

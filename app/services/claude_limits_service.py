"""Lesezugriff auf InfluxDB (Bucket claude_limits) für die Claude-Plan-Auslastung.

Daten kommen von ~/Projekte/automatische-ki-entwicklung/claude-limit-watcher/
(systemd-Timer, alle 15min, treibt `claude` per tmux und liest `/usage`).

Nur LESEND, eigener auf den Bucket beschränkter Token (Least-Privilege), gleiche
Philosophie wie immobilienverwaltung/app/influx_client.py: nur urllib, keine neue
Dependency, Flux-Query, CSV-Antwort selbst geparst.
"""
import csv
import io
import logging
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("dashboard.services.claude_limits")

LOCAL_TZ = ZoneInfo("Europe/Zurich")

INFLUX_URL = os.environ.get("AI_METRICS_INFLUX_URL", "http://localhost:8086")
INFLUX_ORG = "home"
INFLUX_BUCKET = "claude_limits"
CONFIG_ENV = Path.home() / "config.env"


class ClaudeLimitsError(RuntimeError):
    """InfluxDB nicht erreichbar, nicht konfiguriert oder unerwartete Antwort."""


def _influx_token() -> str:
    tok = os.environ.get("INFLUXDB_CLAUDE_LIMITS_TOKEN", "").strip()
    if tok:
        return tok
    try:
        m = re.search(r"^INFLUXDB_CLAUDE_LIMITS_TOKEN=(.+)$", CONFIG_ENV.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip()
    except Exception as e:
        log.error("config.env nicht lesbar: %s", e)
    return ""


def _flux_query(flux: str) -> list[dict]:
    token = _influx_token()
    if not token:
        raise ClaudeLimitsError("INFLUXDB_CLAUDE_LIMITS_TOKEN nicht konfiguriert")
    url = f"{INFLUX_URL.rstrip('/')}/api/v2/query?org={INFLUX_ORG}"
    log.debug("InfluxDB-Query (claude_limits): %s", flux.replace("\n", " "))
    req = urllib.request.Request(
        url, data=flux.encode("utf-8"), method="POST",
        headers={"Authorization": f"Token {token}",
                 "Accept": "application/csv",
                 "Content-Type": "application/vnd.flux"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        raise ClaudeLimitsError(f"InfluxDB-Query fehlgeschlagen: {e}") from e

    rows: list[dict] = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        rows.extend(csv.DictReader(io.StringIO(block)))
    log.debug("InfluxDB-Query (claude_limits): %d Zeile(n)", len(rows))
    return rows


def latest_claude_limits() -> dict:
    """Letzter Datenpunkt je Fenster (five_hour/seven_day): {used_pct, resets_at, ts}.

    24h-Fenster genügt (Timer läuft alle 15min) — verhindert nur, dass bei
    gestopptem Timer beliebig alte Werte als "aktuell" durchgehen."""
    flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "claude_limits")
  |> filter(fn: (r) => r._field == "used_pct" or r._field == "resets_at")
  |> group(columns: ["window", "_field"])
  |> last()'''
    rows = _flux_query(flux)

    result: dict[str, dict] = {}
    for row in rows:
        window = row.get("window")
        field = row.get("_field")
        if not window or not field:
            continue
        block = result.setdefault(window, {})
        if field == "used_pct":
            try:
                block["used_pct"] = round(float(row.get("_value", 0)), 1)
            except (TypeError, ValueError):
                pass
        elif field == "resets_at":
            block["resets_at"] = row.get("_value", "")
        block["ts"] = row.get("_time", block.get("ts"))

    log.info("latest_claude_limits: %s", {k: v.get("used_pct") for k, v in result.items()})
    return result


def used_pct_at_start_of_day(window: str) -> float | None:
    """used_pct of the FIRST data point of today (local time) for a window
    (e.g. "seven_day") — reference value to compute today's increase (instead
    of wrongly counting the whole week's usage as "today").

    None if there's no point yet for today (e.g. the timer was down
    overnight) — caller decides how to fall back."""
    midnight_local = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = midnight_local.astimezone(ZoneInfo("UTC")).isoformat()
    flux = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {start_utc})
  |> filter(fn: (r) => r._measurement == "claude_limits")
  |> filter(fn: (r) => r._field == "used_pct")
  |> filter(fn: (r) => r.window == "{window}")
  |> first()'''
    rows = _flux_query(flux)
    for row in rows:
        try:
            return round(float(row.get("_value", 0)), 1)
        except (TypeError, ValueError):
            continue
    return None

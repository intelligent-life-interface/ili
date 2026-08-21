#!/usr/bin/env python3
"""
log_scanner.py — Systemd-Journal, Dateien und Container-Logs nach Fehlern durchsuchen.

Öffentliche Schnittstellen
--------------------------
run_full_scan(since_hours=24) -> dict
    Vollständiger Scan laut log_sources.json. Haupteinstiegspunkt.
    Rückgabe-Struktur:
        {"scanned_at": "YYYY-MM-DD HH:MM:SS",
         "since_hours": int,
         "total": int,
         "errors": int,       # Anzahl level=="error"
         "warnings": int,     # Anzahl level=="warning"
         "bugs": list[Bug]}   # Sortiert: neueste zuerst, jeder Bug hat "nr"

scan_journal(since_hours=24, max_bugs=200) -> list[Bug]
    Nur systemd --user Journal scannen.

scan_file(path, max_bugs=50) -> list[Bug]
    Einzelne Log-Datei scannen (letzte 2000 Zeilen).

scan_container_logs(since_hours=24, max_bugs=100) -> list[Bug]
    Alle laufenden Podman-Container scannen.

Bug-Dict-Struktur
-----------------
{
  "id":       str,   # Eindeutige ID: "<source>:<zeilennr>:<timestamp>"
  "service":  str,   # Service-Name (aus Zeile extrahiert oder Container-Name)
  "ts":       str,   # Timestamp "YYYY-MM-DD HH:MM:SS" oder "" wenn nicht parsebar
  "level":    str,   # "error" | "warning" | "info"
  "headline": str,   # Bereinigte Fehlerzeile, max 200 Zeichen
  "context":  str,   # 3 Zeilen davor + bis zu 30 Zeilen danach (inkl. Traceback)
  "source":   str,   # "journal" | "container:<name>" | absoluter Dateipfad
  "line_nr":  int,   # Zeilennummer im Quell-Log
  "nr":       int,   # Laufnummer (nur in run_full_scan-Ausgabe)
}

Konfiguration
-------------
log_sources.json im Dashboard-Verzeichnis steuert welche Quellen gescannt werden:
{
  "journal":    {"enabled": true, "max_bugs": 150},
  "files":      [{"path": "/pfad/zu/datei.log", "enabled": true, "max_bugs": 20}],
  "containers": {"enabled": false, "max_bugs": 50}
}
"""

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("trigger-server")

# Muster die auf Fehler hinweisen
# \b…\b = Wortgrenzen, damit "FEHLER" nicht in "fehlermuster" / "Fehlermeldung" matcht
# und "ERROR" nicht in "errorMessage" o.ä. Substrings.
_ERROR_PATTERNS = re.compile(
    r"(Traceback|NameError|AttributeError|TypeError|ValueError|KeyError|"
    r"ImportError|ModuleNotFoundError|FileNotFoundError|PermissionError|"
    r"RuntimeError|Exception|Error:|\bERROR\b|\bCRITICAL\b|\bFEHLER\b|"
    r"\bfailed\b|\bFailed\b|HTTP 5\d\d|500 -)",
    re.IGNORECASE,
)

# Diese Muster ignorieren (false positives)
_IGNORE_PATTERNS = re.compile(
    r"(DEBUG|logrotate|Checking for|healthcheck|ping|heartbeat.*ok|"
    r"successfully|erfolgreich|Bereit|started|stopped normally)",
    re.IGNORECASE,
)

# Welche Services scannen
_SKIP_SERVICES = {
    "session-", "dbus", "gnome", "pulseaudio", "pipewire",
    "xdg-", "gvfs", "evolution", "tracker",
}


def _should_skip_service(unit: str) -> bool:
    return any(unit.startswith(s) for s in _SKIP_SERVICES)


def scan_journal(since_hours: int = 24, max_bugs: int = 200) -> list[dict]:
    """Systemd --user Journal scannen und Fehlerblöcke extrahieren.

    Args:
        since_hours: Wie weit zurück scannen (1–168).
        max_bugs:    Maximale Anzahl zurückgegebener Einträge.
    Returns:
        Liste von Bug-Dicts (siehe Modul-Docstring). Leere Liste bei Fehler.
    """
    since = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M:%S")
    cmd = [
        "journalctl", "--user",
        "--since", since,
        "--output", "short-iso",
        "--no-pager",
        "-n", "5000",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = result.stdout.splitlines()
    except Exception as e:
        log.error(f"journalctl fehlgeschlagen: {e}")
        return []

    log.info(f"Journal: {len(lines)} Zeilen seit {since_hours}h")
    return _parse_log_lines(lines, source="journal", max_bugs=max_bugs)


def scan_file(path: Path, max_bugs: int = 50) -> list[dict]:
    """Einzelne Log-Datei nach Fehlermustern durchsuchen (letzte 2000 Zeilen).

    Args:
        path:     Path-Objekt zur Log-Datei. Wird mit errors="replace" gelesen.
        max_bugs: Maximale Anzahl zurückgegebener Einträge.
    Returns:
        Liste von Bug-Dicts. Leere Liste wenn Datei nicht lesbar.
    """
    try:
        lines = path.read_text(errors="replace").splitlines()[-2000:]
    except Exception as e:
        log.warning(f"Datei nicht lesbar {path}: {e}")
        return []
    return _parse_log_lines(lines, source=str(path), max_bugs=max_bugs)


def scan_container_logs(since_hours: int = 24, max_bugs: int = 100, only: list | None = None) -> list[dict]:
    """Laufende Podman-Container via `podman logs` scannen (max. 20 Container).

    Args:
        since_hours: Wie weit zurück scannen.
        max_bugs:    Maximale Anzahl zurückgegebener Einträge (über alle Container).
        only:        Optionale Whitelist von Container-Namen. Wenn gesetzt, werden
                     nur diese Container gescannt (Rest wird ignoriert).
    Returns:
        Liste von Bug-Dicts. Leere Liste wenn podman nicht verfügbar.
    """
    bugs = []
    try:
        result = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5
        )
        containers = [c.strip() for c in result.stdout.splitlines() if c.strip()]
    except Exception as e:
        log.warning(f"podman ps fehlgeschlagen: {e}")
        return []

    if only:
        only_set = set(only)
        containers = [c for c in containers if c in only_set]
        log.debug(f"Container-Filter aktiv: {containers}")

    since_str = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    for name in containers[:20]:  # max 20 Container
        try:
            r = subprocess.run(
                ["podman", "logs", "--since", since_str, "--tail", "500", name],
                capture_output=True, text=True, timeout=8
            )
            lines = (r.stdout + r.stderr).splitlines()
            found = _parse_log_lines(lines, source=f"container:{name}", max_bugs=10)
            bugs.extend(found)
        except Exception:
            pass

    log.info(f"Container-Logs: {len(bugs)} Bugs aus {len(containers)} Containern")
    return bugs[:max_bugs]


def _parse_log_lines(lines: list[str], source: str, max_bugs: int) -> list[dict]:
    """Extrahiert Fehlerblöcke aus Zeilen."""
    bugs = []
    i = 0
    while i < len(lines) and len(bugs) < max_bugs:
        line = lines[i]

        if not _ERROR_PATTERNS.search(line):
            i += 1
            continue
        if _IGNORE_PATTERNS.search(line):
            i += 1
            continue

        # Service-Name aus Zeile extrahieren
        service = _extract_service(line, source)

        # Kontext: 3 Zeilen vorher + 10 Zeilen nachher (für Traceback)
        ctx_start = max(0, i - 3)
        ctx_end   = min(len(lines), i + 10)
        context   = lines[ctx_start:ctx_end]

        # Traceback vollständig erfassen
        j = i + 1
        while j < len(lines) and j < i + 30:
            l = lines[j]
            if re.search(r"(  File |^\s+|Traceback|Error:|NameError|Exception)", l):
                ctx_end = j + 1
                j += 1
            else:
                break
        context = lines[ctx_start:min(len(lines), ctx_end)]

        # Headline: die Fehlerzeile selbst, bereinigt
        headline = _clean_headline(line)

        # Timestamp extrahieren
        ts = _extract_ts(line)

        bug_id = f"{source}:{i}:{ts}"

        bugs.append({
            "id":       bug_id,
            "service":  service,
            "ts":       ts,
            "level":    _extract_level(line),
            "headline": headline,
            "context":  "\n".join(context),
            "source":   source,
            "line_nr":  i,
        })

        # Nächste Fehlersuche nach dem Traceback-Block
        i = ctx_end
    return bugs


def _extract_service(line: str, source: str) -> str:
    # journalctl short-iso Format: "2026-05-08T07:50:26+0200 hostname python3[1234]:"
    m = re.search(r"\s(\S+)\[\d+\]:", line)
    if m:
        return m.group(1)
    if source.startswith("container:"):
        return source.split(":", 1)[1]
    if "/" in source:
        return Path(source).stem
    return source


_QUOTA_PATTERNS = re.compile(
    r"(credit balance|insufficient.{0,20}(credit|funds|balance|guthaben)|"
    r"quota.{0,30}(exceed|exhaust)|rate.?limit|"
    r"\"status\":\s*(400|402|429)|HTTP 4(00|02|29)|"
    r"kein.{0,10}guthaben|aufladen|payment.required)",
    re.IGNORECASE,
)


def _extract_level(line: str) -> str:
    # Quota/Billing-Probleme: nicht als ERROR — sind erwartete Aussenfehler.
    if _QUOTA_PATTERNS.search(line):
        return "warning"
    if re.search(r"(Traceback|NameError|TypeError|Error:|Exception|CRITICAL|ERROR|HTTP 5)", line, re.I):
        return "error"
    if re.search(r"(WARNING|WARN|failed)", line, re.I):
        return "warning"
    return "info"


def _extract_ts(line: str) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if m:
        return m.group(1).replace("T", " ")
    m = re.search(r"([A-Z][a-z]+ \d+ \d{2}:\d{2}:\d{2})", line)
    if m:
        return m.group(1)
    return ""


def _clean_headline(line: str) -> str:
    # Timestamp und Hostname am Anfang entfernen
    clean = re.sub(r"^\S+\s+\S+\s+\S+\s+", "", line).strip()
    return clean[:200]


from constants import LOG_SOURCES_FILE as _LOG_SOURCES_FILE


def _load_log_sources() -> dict:
    try:
        return json.loads(_LOG_SOURCES_FILE.read_text())
    except Exception as e:
        log.warning(f"log_sources.json nicht lesbar: {e} — nutze Defaults")
        return {"journal": {"enabled": True, "max_bugs": 150}, "files": [], "containers": {"enabled": False}}


def run_full_scan(since_hours: int = 24) -> dict:
    """Vollständiger Scan aller konfigurierten Quellen — Haupteinstiegspunkt.

    Liest log_sources.json, scannt Journal/Dateien/Container je nach Konfiguration,
    dedupliziert nach (service, headline[:80]), sortiert neueste zuerst.

    Args:
        since_hours: Wie weit zurück scannen (Standard 24h; max sinnvoll 168 = 7 Tage).
    Returns:
        {"scanned_at": str, "since_hours": int, "total": int,
         "errors": int, "warnings": int, "bugs": list[Bug]}
        Jeder Bug enthält zusätzlich "nr" (1-basiert, entspricht Anzeigereihenfolge).
    """
    log.info(f"Bug-Scan gestartet (letzte {since_hours}h)")
    cfg = _load_log_sources()
    all_bugs = []

    # Journal
    j_cfg = cfg.get("journal", {})
    if j_cfg.get("enabled", True):
        all_bugs.extend(scan_journal(since_hours=since_hours, max_bugs=j_cfg.get("max_bugs", 150)))

    # Dateien
    for f_cfg in cfg.get("files", []):
        if not f_cfg.get("enabled", True):
            continue
        p = Path(f_cfg["path"])
        if p.exists():
            all_bugs.extend(scan_file(p, max_bugs=f_cfg.get("max_bugs", 20)))
        else:
            log.debug(f"Log-Datei nicht vorhanden: {p}")

    # Container (optional)
    c_cfg = cfg.get("containers", {})
    if c_cfg.get("enabled", False):
        all_bugs.extend(scan_container_logs(
            since_hours=since_hours,
            max_bugs=c_cfg.get("max_bugs", 50),
            only=c_cfg.get("only") or None,
        ))

    # Deduplizieren nach Headline + Service (gleiche Fehler mehrfach)
    seen = set()
    deduped = []
    for b in all_bugs:
        key = f"{b['service']}|{b['headline'][:80]}"
        if key not in seen:
            seen.add(key)
            deduped.append(b)

    # Sortieren: neueste zuerst
    deduped.sort(key=lambda x: x["ts"], reverse=True)

    # Nummerierung für einfache Referenz
    for idx, b in enumerate(deduped):
        b["nr"] = idx + 1

    result = {
        "scanned_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "since_hours": since_hours,
        "total":       len(deduped),
        "errors":      sum(1 for b in deduped if b["level"] == "error"),
        "warnings":    sum(1 for b in deduped if b["level"] == "warning"),
        "bugs":        deduped,
    }
    log.info(f"Bug-Scan fertig: {result['total']} Einträge ({result['errors']} Errors, {result['warnings']} Warnings)")
    return result

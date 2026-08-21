"""Container-Status: Podman-Abfrage, bekannte Services, Auto-Detect.

Aus generate_dashboard.py herausgelöst (2026-07-23), damit der Produktivpfad
(GET /api/dashboard → dashboard_service) nicht mehr den 2000-Zeilen-HTML-
Generator importieren muss. generate_dashboard.py nutzt jetzt umgekehrt dieses
Modul, es gibt also weiterhin nur EINE Implementierung.

Schnittstelle:
    load_services_config()          -> (auto_ignore:set, services:list)  [gecacht]
    get_running_containers()        -> {name: [port-dicts]}   (podman ps, timeout 10s)
    get_known_containers()          -> {container-namen aus der Config}
    detect_auto_containers(run, kn) -> [item-dicts] für unbekannte Container mit Ports
    collect_services(running)       -> [service-dicts mit status online/offline/system]
"""
import json
import logging
import os
import re
import subprocess

from constants import SERVICES_CONFIG_FILE

log = logging.getLogger("dashboard.services.container_status")

_ENV_PLACEHOLDER = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")

# Fallback für frische Installationen ohne services_config.json (siehe .example.json)
_DEFAULT_AUTO_IGNORE = ["dashboard"]
_DEFAULT_SERVICES = [
    {
        "category": "Beispiel",
        "items": [
            {
                "name": "Dashboard",
                "url": "http://localhost:8798",
                "container": "dashboard",
                "user": "—",
                "icon": "🏠",
                "desc": "Dieses Dashboard — siehe services_config.example.json zum Anpassen",
            },
        ],
    },
]

_config_cache: tuple[set[str], list[dict]] | None = None


def load_services_config(force_reload: bool = False) -> tuple[set[str], list[dict]]:
    """Lädt AUTO_IGNORE + SERVICES aus der personalisierten (gitignorten)
    services_config.json. Fällt auf ein Minimalbeispiel zurück, falls die
    Datei fehlt (frische OSS-Installation) — siehe services_config.example.json.

    Das Ergebnis wird gecacht (Prozess-Lebensdauer); `force_reload=True` liest neu.
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    if SERVICES_CONFIG_FILE.exists():
        try:
            data = json.loads(SERVICES_CONFIG_FILE.read_text(encoding="utf-8"))
            auto_ignore = set(data.get("auto_ignore", []))
            services = data.get("services", [])
            for cat in services:
                for item in cat.get("items", []):
                    url = item.get("url")
                    if url:
                        item["url"] = _ENV_PLACEHOLDER.sub(
                            lambda m: os.environ.get(m.group(1), ""), url)
            log.debug("services_config.json geladen: %d Kategorien, %d ignorierte Container",
                      len(services), len(auto_ignore))
            _config_cache = (auto_ignore, services)
            return _config_cache
        except Exception as e:
            log.error(f"{SERVICES_CONFIG_FILE} fehlerhaft, nutze Minimal-Fallback: {e}")
    else:
        log.warning("%s fehlt — Minimal-Fallback aktiv", SERVICES_CONFIG_FILE)
    _config_cache = (set(_DEFAULT_AUTO_IGNORE), _DEFAULT_SERVICES)
    return _config_cache


def get_running_containers() -> dict[str, list[dict]]:
    """Gibt alle laufenden Podman-Container zurück mit ihren Port-Mappings.

    Wirft bei fehlgeschlagenem `podman ps` (Returncode != 0, z.B. kaputter
    Socket) bewusst statt still ein leeres dict zu liefern — sonst sieht
    _collect_containers() keine Exception und meldet "alle Container gestoppt"
    statt eines Fehlers. Aufrufer fangen die Exception ab.

    Returns:
        dict: container_name → list of port dicts (host_port, container_port, protocol)
    """
    result = subprocess.run(
        ["podman", "ps", "--format", "json"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"podman ps fehlgeschlagen (rc={result.returncode}): {(result.stderr or '').strip()[:300]}"
        )
    containers = json.loads(result.stdout)
    running = {}
    for c in containers:
        name = c["Names"][0] if c.get("Names") else c.get("Name", "unknown")
        ports = c.get("Ports") or []
        running[name] = ports
    log.debug(f"Laufende Container: {list(running.keys())}")
    return running


def get_known_containers(services: list[dict] | None = None) -> set[str]:
    """Gibt alle in SERVICES bekannten Container-Namen zurück."""
    if services is None:
        services = load_services_config()[1]
    known = set()
    for cat in services:
        for item in cat.get("items", []):
            if item.get("container"):
                known.add(item["container"])
    return known


def detect_auto_containers(running: dict[str, list[dict]], known: set[str],
                           auto_ignore: set[str] | None = None) -> list[dict]:
    """Erkennt neue Container, die nicht in der bekannten Liste sind.

    Nur Container mit öffentlichen (nicht localhost-only) Ports werden gezeigt.
    """
    if auto_ignore is None:
        auto_ignore = load_services_config()[0]
    auto_items = []
    for name, ports in running.items():
        if name in known or name in auto_ignore:
            log.debug(f"Auto-Detect: Überspringe bekannten/ignorierten Container '{name}'")
            continue

        # Nur Ports, die nicht auf 127.0.0.1 gebunden sind
        public_ports = [
            p for p in (ports or [])
            if p.get("host_ip", "") not in ("127.0.0.1", "::1")
        ]
        if not public_ports:
            log.debug(f"Auto-Detect: Container '{name}' hat keine öffentlichen Ports, überspringe")
            continue

        # Primären Port für URL bestimmen (kleinster Host-Port, der nicht 80/443 ist, sonst erster)
        def port_priority(p):
            hp = p.get("host_port", 99999)
            return (0 if hp not in (80, 443) else 1, hp)

        primary = sorted(public_ports, key=port_priority)[0]
        host_port = primary.get("host_port")
        scheme = "https" if host_port == 443 else "http"
        _server_host = os.environ.get("DASHBOARD_HOST_IP", "127.0.0.1")
        url = f"{scheme}://{_server_host}:{host_port}"

        # Alle Ports als Beschreibung
        port_list = ", ".join(str(p.get("host_port")) for p in sorted(public_ports, key=lambda p: p.get("host_port", 0)))

        log.info(f"Auto-Detect: Neuer Container '{name}' mit Ports [{port_list}] gefunden")
        auto_items.append({
            "name": name,
            "url": url,
            "container": name,
            "user": "—",
            "icon": "🔧",
            "desc": f"Automatisch erkannt · Port(s): {port_list}",
        })

    return auto_items


def collect_services(running: dict[str, list[dict]],
                     services: list[dict] | None = None) -> list[dict]:
    """Flache Service-Liste mit Status für die API.

    status: "system" wenn kein Container hinterlegt ist (z.B. Host-Dienste),
            sonst "online"/"offline" je nach podman ps.
    """
    if services is None:
        services = load_services_config()[1]
    result = []
    for cat in services:
        for item in cat.get("items", []):
            cname = item.get("container")
            if cname is None:
                status = "system"
            else:
                status = "online" if cname in running else "offline"
            result.append({
                "name": item.get("name"),
                "category": cat.get("category"),
                "url": item.get("url"),
                "icon": item.get("icon", "🔧"),
                "desc": item.get("desc", ""),
                "container": cname,
                "status": status,
            })
    log.debug("collect_services: %d Services, davon %d online",
              len(result), sum(1 for s in result if s["status"] == "online"))
    return result

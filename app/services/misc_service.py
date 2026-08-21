"""Misc-Dienste — Netzwerk-Scan-Trigger, Diagramm-Storage (Welle 6).

Semantik 1:1 aus trigger_server.py; Diagramme laufen über das bestehende Modul
diagram_storage (Wiederverwendung, kein Duplikat).

Der Shelly-Scan ist am 2026-08-01 in den eigenen Container `shelly-scanner`
gewandert (Port 8808) — ein 20-30s
dauernder synchroner LAN-Scan hat hier den uvicorn-Threadpool erschoepft.

Schnittstelle
-------------
load_diagram(name) -> dict              # {"name", "xml"} ("" wenn fehlt/ungültig)
list_diagrams() -> dict                 # {"diagrams": [...]}
save_diagram(name, xml) -> dict         # raises ValueError bei ungültigem Name/XML
"""
import logging
import os
from pathlib import Path

import diagram_storage

log = logging.getLogger("dashboard.services.misc")

_DASH = Path(os.environ.get("DASHBOARD_DIR", str(Path.home() / "containers/dashboard")))


def load_diagram(name: str) -> dict:
    """Diagramm laden — leeres xml wenn nicht vorhanden (Legacy-Verhalten)."""
    xml = diagram_storage.load_diagram(name)
    return {"name": name, "xml": xml}


def list_diagrams() -> dict:
    return {"diagrams": diagram_storage.list_diagrams()}


def save_diagram(name: str, xml: str) -> dict:
    """Diagramm speichern.

    Raises:
        ValueError: ungültiger Name oder fehlendes XML (HTTP 400).
    """
    return diagram_storage.save_diagram(name, xml)

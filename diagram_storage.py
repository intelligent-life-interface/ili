"""
diagram_storage.py — draw.io / Mermaid Diagramme persistieren

Speichert XML-Diagramme als .drawio-Dateien in ~/containers/dashboard/diagrams/.
Lädt sie zurück, wenn eine Seite das Diagramm braucht.

Schnittstelle:
- save_diagram(name, xml) -> dict   # {"saved": True, "path": "..."}
- load_diagram(name)      -> str    # XML als String, oder "" wenn nicht vorhanden
- list_diagrams()         -> list   # ["masterchat-flow", ...]
"""
import os
import re
from pathlib import Path
import logging

log = logging.getLogger("diagram_storage")

_DIAGRAMS_DIR = Path(
    os.environ.get("DIAGRAMS_DIR", str(Path.home() / "containers/dashboard/diagrams"))
)
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _safe_path(name: str) -> Path:
    if not _SAFE_NAME.match(name or ""):
        raise ValueError(f"Ungültiger Diagramm-Name: {name!r}")
    _DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    return _DIAGRAMS_DIR / f"{name}.drawio"


def save_diagram(name: str, xml: str) -> dict:
    if not xml or not isinstance(xml, str):
        raise ValueError("xml fehlt oder ist kein String")
    p = _safe_path(name)
    p.write_text(xml, encoding="utf-8")
    log.info(f"[diagram] gespeichert: {p} ({len(xml)} chars)")
    return {"saved": True, "path": str(p), "bytes": len(xml)}


def load_diagram(name: str) -> str:
    try:
        p = _safe_path(name)
    except ValueError as e:
        log.warning(f"[diagram] load abgelehnt: {e}")
        return ""
    if not p.exists():
        log.debug(f"[diagram] nicht vorhanden: {p}")
        return ""
    xml = p.read_text(encoding="utf-8")
    log.info(f"[diagram] geladen: {p} ({len(xml)} chars)")
    return xml


def list_diagrams() -> list:
    if not _DIAGRAMS_DIR.exists():
        return []
    return sorted(p.stem for p in _DIAGRAMS_DIR.glob("*.drawio"))

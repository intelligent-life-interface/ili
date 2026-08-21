"""Atomares JSON-Schreiben: tmp-Datei im Zielverzeichnis + os.replace.

Verhindert Partial-Writes (z.B. bei Crash mitten im write_text) — Leser sehen
immer entweder die alte oder die neue Datei, nie eine halbe.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("dashboard.storage.atomic")


def write_json_atomic(path: Path, data) -> None:
    """JSON atomar nach path schreiben (tmp im selben Verzeichnis → os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
        log.debug("Atomar geschrieben: %s (%d Bytes)", path, path.stat().st_size)
    except Exception:
        # tmp-Datei nicht liegen lassen
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

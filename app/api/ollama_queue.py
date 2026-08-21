"""
Ollama-Warteliste — Dashboard-Sicht auf die Prioritäts-Queue des ollama-analyse-Proxys.

Der Proxy (:11435, ~/containers/ollama-analyse) ordnet seit 16.07.26 alle
Inferenz-Aufträge in eine Prioritäts-Warteliste (höchste Prio zuerst, Alterung,
Prio 0 = nur bei freier Kapazität). Dieser Router macht die Liste im Dashboard
sichtbar und erlaubt das Pflegen der Aufrufer-Prioritäten (priorities.json).

Endpunkte:
  GET  /api/ollama/queue       -> Live-Snapshot der Warteliste (aktiv/wartend)
  GET  /api/ollama/recent      -> letzte Inferenz-Aufträge inkl. Prio + Wartezeit (SQLite ro)
  GET  /api/ollama/priorities  -> Inhalt priorities.json (Aufrufer -> Prio)
  POST /api/ollama/priorities  -> {caller, prio} setzen; prio=null löscht den Eintrag
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage.atomic_write import write_json_atomic
from constants import OLLAMA_URL as _DEFAULT_OLLAMA_URL

router = APIRouter()
log = logging.getLogger("uvicorn.error")

PROXY_URL = os.environ.get("OLLAMA_PROXY_URL", _DEFAULT_OLLAMA_URL).rstrip("/")
PRIORITIES_FILE = Path(os.environ.get(
    "OLLAMA_PRIORITIES_FILE",
    str(Path.home() / "containers/ollama-analyse/data/priorities.json")))
PROXY_DB = Path(os.environ.get(
    "OLLAMA_PROXY_DB",
    str(Path.home() / "containers/ollama-analyse/data/ollama_analyse.sqlite")))


@router.get("/api/ollama/queue")
def queue_snapshot():
    """Live-Stand der Warteliste direkt vom Proxy."""
    try:
        with urllib.request.urlopen(f"{PROXY_URL}/queue", timeout=5) as r:
            snap = json.loads(r.read())
        log.debug("ollama-queue: Snapshot ok (%d wartend)", len(snap.get("wartend", [])))
        return snap
    except Exception as e:
        log.warning("ollama-queue: Proxy nicht erreichbar: %s", e)
        raise HTTPException(status_code=502, detail="Ollama-Proxy nicht erreichbar")


@router.get("/api/ollama/recent")
def recent_requests(limit: int = 40):
    """Letzte Inferenz-Aufträge aus der Proxy-SQLite (read-only)."""
    limit = max(1, min(200, limit))
    if not PROXY_DB.exists():
        log.warning("ollama-queue: Proxy-DB fehlt: %s", PROXY_DB)
        raise HTTPException(status_code=404, detail="Proxy-Datenbank nicht gefunden")
    try:
        con = sqlite3.connect(f"file:{PROXY_DB}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT ts, caller_name, model, priority, queue_wait_ms,
                      proxy_duration_ms, prompt_tokens, completion_tokens,
                      status_code, error
               FROM requests ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
        con.close()
        return {"requests": [dict(r) for r in rows]}
    except sqlite3.Error as e:
        log.error("ollama-queue: DB-Lesefehler: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/api/ollama/priorities")
def get_priorities():
    """priorities.json: Aufrufer -> Prio (plus _default/_hinweis)."""
    try:
        data = json.loads(PRIORITIES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception as e:
        log.error("ollama-queue: priorities.json unlesbar: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")
    entries = {k: v for k, v in data.items() if not k.startswith("_")}
    return {"default": data.get("_default", 0), "hinweis": data.get("_hinweis", ""),
            "priorities": entries, "file": str(PRIORITIES_FILE)}


class PrioUpdate(BaseModel):
    caller: str
    prio: float | None = None  # None = Eintrag löschen (zurück auf _default)


@router.post("/api/ollama/priorities")
def set_priority(body: PrioUpdate):
    """Einen Aufrufer-Eintrag setzen/löschen. Der Proxy lädt die Datei
    selbst per mtime-Check neu — kein Neustart nötig."""
    caller = body.caller.strip()
    if not caller or caller.startswith("_"):
        raise HTTPException(status_code=400, detail="Ungültiger Aufrufer-Name")
    try:
        data = json.loads(PRIORITIES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {"_default": 0}
    except Exception as e:
        log.error("ollama-queue: priorities.json unlesbar: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")
    if body.prio is None:
        removed = data.pop(caller, None)
        log.info("ollama-queue: Prio-Eintrag %s entfernt (war %s)", caller, removed)
    else:
        prio = max(0.0, min(10.0, float(body.prio)))
        data[caller] = int(prio) if prio == int(prio) else prio
        log.info("ollama-queue: Prio %s = %s gesetzt", caller, data[caller])
    write_json_atomic(PRIORITIES_FILE, data)
    return get_priorities()

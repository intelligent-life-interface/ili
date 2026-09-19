#!/usr/bin/env python3
"""__NAME__ – __DESC__ (WebGUI via webgui-scaffold)"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("__NAME__")

app = FastAPI(title="__NAME__")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    log.debug("Health-Check aufgerufen")
    return {"status": "ok", "service": "__NAME__"}


@app.get("/api/status")
def api_status():
    log.debug("Status-API aufgerufen")
    return {"status": "ok", "service": "__NAME__"}


@app.get("/")
def index():
    log.debug("Index ausgeliefert")
    return FileResponse(STATIC_DIR / "index.html")

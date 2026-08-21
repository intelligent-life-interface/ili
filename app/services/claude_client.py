"""Gemeinsamer Client für die Claude-Abo-CLI-Bridge (Port 8950, KEIN API-Guthaben).

Vorher: 3 unabhängige POST-Implementierungen mit je eigenem Timeout-/Fehlerpfad
(project_creator.py _claude_abo_text/_claude_abo_vision, jobs/ki_project_advisor.py
_claude_abo_chat, app/services/brainstorm_service.py stream_brainstorm) — analog zum
Vorher-Zustand von app/services/ollama_client.py (opt_atomic_writes_jobs_0809). Jetzt:
EINE Quelle (constants.CLAUDE_BRIDGE_URL), gleiches Timeout-/Fehlermuster wie dort.

Die bisherigen Wrapper-Funktionen (_claude_abo_text usw.) bleiben an ihren Stellen
erhalten (viele Aufrufer, unveränderte Signatur) und delegieren nur noch hierher.
"""
import base64
import json
import logging
import urllib.error
import urllib.request
from typing import AsyncIterator

import httpx

from constants import CLAUDE_BRIDGE_URL
from app.services.httpx_stream import post_lines

log = logging.getLogger("dashboard.services.claude_client")

# Indirektion statt direktem httpx.AsyncClient-Aufruf (httpx ist ein geteiltes Modul,
# s. app/services/ollama_client.py) — Tests patchen gezielt diesen Namen.
_ASYNC_CLIENT = httpx.AsyncClient


class ClaudeBridgeError(Exception):
    """Bridge nicht erreichbar oder Fehler-Antwort."""


def _post(path: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{CLAUDE_BRIDGE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.error("Claude-Bridge %s fehlgeschlagen: %s", path, e)
        raise ClaudeBridgeError(str(e)) from e


def chat(system: str, prompt: str, model: str, *, max_tokens: int = 800,
         temperature: float = 0.3, timeout: int = 120) -> str:
    """POST /chat — Text-Antwort der eingeloggten Claude-CLI-Session (Abo, kein API-Guthaben)."""
    payload = {
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    log.info("chat model=%s prompt_chars=%d -> %s/chat", model, len(prompt), CLAUDE_BRIDGE_URL)
    body = _post("/chat", payload, timeout)
    text = (body.get("text") or "").strip()
    log.info("chat ok, out_chars=%d", len(text))
    return text


def vision(photo_bytes: bytes, system: str, prompt: str, model: str, *,
           media_type: str = "image/jpeg", timeout: int = 120) -> str:
    """POST /vision — Foto-Analyse übers Claude-Abo (Bild als Base64-Content-Block,
    reine Inferenz ohne Agent-Tools — Bridge-Sicherheitssperre)."""
    payload = {
        "system": system,
        "prompt": prompt,
        "images": [{"base64": base64.b64encode(photo_bytes).decode(), "media_type": media_type}],
        "model": model,
    }
    log.info("vision model=%s bytes=%d -> %s/vision", model, len(photo_bytes), CLAUDE_BRIDGE_URL)
    body = _post("/vision", payload, timeout)
    text = (body.get("text") or "").strip()
    log.info("vision ok, out_chars=%d", len(text))
    return text


def is_reachable(timeout: int = 10) -> bool:
    """GET /health — schneller Erreichbarkeits-Check der Bridge (Muster ollama_client)."""
    try:
        with urllib.request.urlopen(f"{CLAUDE_BRIDGE_URL}/health", timeout=timeout):
            return True
    except Exception as e:
        log.debug("Claude-Bridge nicht erreichbar (%s): %s", CLAUDE_BRIDGE_URL, e)
        return False


async def stream_lines(system: str, messages: list[dict], model: str, *,
                        timeout: int = 300) -> AsyncIterator[str]:
    """POST /stream — rohe NDJSON-Zeilen der Bridge 1:1 durchreichen (je Zeile
    {"t": "<token>"} / {"done": true} / {"error": "..."}).

    Echtes async-Streaming (httpx statt urllib, opt_stream_threadpool_0811): ein
    sync-Generator würde für die volle Stream-Dauer (bis zu 300s) einen anyio-
    Threadpool-Worker belegen — denselben Pool, den auch normale `def`-Routen
    nutzen. httpx.AsyncClient läuft im Event-Loop, verbraucht 0 Worker.

    Wirft bei Transportfehlern normal (kein Swallowing) — der Aufrufer (brainstorm_service)
    entscheidet selbst über das Fehler-Framing im ausgehenden NDJSON-Stream.
    """
    payload = {"system": system, "messages": messages, "model": model}
    async for line in post_lines(f"{CLAUDE_BRIDGE_URL}/stream", payload,
                                  client_factory=_ASYNC_CLIENT, timeout=timeout):
        yield line

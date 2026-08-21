"""Gemeinsamer Ollama-HTTP-Client für Jobs/Tools-Skripte (opt_atomic_writes_jobs_0809).

Vorher: neun Module mit je eigenem OLLAMA_URL-Default + urllib-Boilerplate
(jobs/bug_fixer.py, jobs/ki_project_advisor.py, jobs/kanban_dedup.py,
jobs/kanban_tagger.py, kanban_ki_sortierer/config.py, tools/script_splitter.py,
jobs/ki_explain_worker.py, jobs/ki_cost_monitor.py, jobs/claude_session_monitor.py).
Belegter Schaden: der Ausfall des Ollama-Gateways musste in mehreren Units
einzeln nachgepflegt werden (Environment=OLLAMA_URL divergierte), Timeout/Retry
unterschieden sich pro Kopie. Jetzt: EINE Quelle (constants.OLLAMA_URL).
"""
import json
import logging
import urllib.error
import urllib.request
from typing import AsyncIterator

import httpx

from constants import OLLAMA_URL
from app.services.httpx_stream import post_lines

log = logging.getLogger("dashboard.services.ollama_client")

# Indirektion statt direktem httpx.AsyncClient-Aufruf: httpx ist ein geteiltes Modul
# (dasselbe sys.modules-Objekt in jedem Importer) — ein Test, der httpx.AsyncClient
# global patcht, würde auch fremden Code treffen. Tests patchen stattdessen gezielt
# diesen Modul-Namen.
_ASYNC_CLIENT = httpx.AsyncClient


class OllamaError(Exception):
    """Ollama nicht erreichbar oder Fehler-Antwort (chunk["error"])."""


class OllamaHTTPError(OllamaError):
    """Ollama antwortete mit einem HTTP-Fehlerstatus (z.B. 500 bei Poison-Input wie
    dem bge-m3-NaN-Fall). Abgegrenzt von reinen Netzwerkfehlern (Verbindung down,
    Timeout), damit Aufrufer mit Batch-Split-/Skip-Logik (ki_search_service) gezielt
    nur auf HTTP-Fehler reagieren können, nicht auf einen kompletten Ausfall."""
    def __init__(self, status: int, msg: str):
        self.status = status
        super().__init__(msg)


def _post(path: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log.error("Ollama %s fehlgeschlagen: HTTP %s", path, e.code)
        raise OllamaHTTPError(e.code, str(e)) from e
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.error("Ollama %s fehlgeschlagen: %s", path, e)
        raise OllamaError(str(e)) from e


def _get(path: str, timeout: int) -> dict:
    req = urllib.request.Request(f"{OLLAMA_URL}{path}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log.error("Ollama GET %s fehlgeschlagen: HTTP %s", path, e.code)
        raise OllamaHTTPError(e.code, str(e)) from e
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        log.error("Ollama GET %s fehlgeschlagen: %s", path, e)
        raise OllamaError(str(e)) from e


def generate_raw(model: str, prompt: str, *, options: dict | None = None,
                  format: str | None = None, think: bool | None = None,
                  timeout: int = 120) -> dict:
    """POST /api/generate (non-streaming) — liefert die volle Antwort (inkl.
    prompt_eval_count/eval_count für Kosten-Tracking).

    `think`: bei Reasoning-Modellen (z.B. nemotron-3.5-lightning) landet die
    Antwort sonst im separaten "thinking"-Feld statt in "response" — bei knappem
    num_predict kommt "response" dann leer zurück. think=False erzwingt eine
    direkte Antwort ohne sichtbare Denkschritte."""
    payload = {"model": model, "prompt": prompt, "stream": False}
    if options:
        payload["options"] = options
    if format:
        payload["format"] = format
    if think is not None:
        payload["think"] = think
    data = _post("/api/generate", payload, timeout)
    if data.get("error"):
        raise OllamaError(data["error"])
    return data


def chat_raw(model: str, messages: list[dict], *, options: dict | None = None,
             timeout: int = 120) -> dict:
    """POST /api/chat (non-streaming) — liefert die volle Antwort (inkl.
    prompt_eval_count/eval_count für Kosten-Tracking)."""
    payload = {"model": model, "messages": messages, "stream": False}
    if options:
        payload["options"] = options
    data = _post("/api/chat", payload, timeout)
    if data.get("error"):
        raise OllamaError(data["error"])
    return data


def generate(model: str, prompt: str, *, options: dict | None = None,
             format: str | None = None, think: bool | None = None,
             timeout: int = 120) -> str:
    """POST /api/generate (non-streaming) — liefert nur den response-Text."""
    return generate_raw(model, prompt, options=options, format=format, think=think,
                         timeout=timeout).get("response", "")


def chat(model: str, messages: list[dict], *, options: dict | None = None,
          timeout: int = 120) -> str:
    """POST /api/chat (non-streaming) — liefert nur message.content."""
    return chat_raw(model, messages, options=options, timeout=timeout).get("message", {}).get("content", "")


def is_reachable(timeout: int = 10) -> bool:
    """GET /api/tags — schneller Erreichbarkeits-Check ohne Modell-Ladung."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout):
            return True
    except Exception as e:
        log.debug("Ollama nicht erreichbar (%s): %s", OLLAMA_URL, e)
        return False


def tags(timeout: int = 10) -> dict:
    """GET /api/tags — installierte Modelle (voller Body, nicht nur der bool-Check)."""
    return _get("/api/tags", timeout)


def ps(timeout: int = 10) -> dict:
    """GET /api/ps — aktuell im VRAM residente (geladene) Modelle."""
    return _get("/api/ps", timeout)


def embed_raw(model: str, input_texts: list[str], *, keep_alive: str | None = None,
              timeout: int = 60) -> dict:
    """POST /api/embed — Batch-Embedding, liefert den vollen Body (inkl. "embeddings").

    Raises:
        OllamaHTTPError: HTTP-Fehlerstatus (z.B. 500 bei einem NaN-Vektor für einen
            einzelnen Poison-Text) — von Netzwerkfehlern unterscheidbar für Batch-Split-Logik.
    """
    payload = {"model": model, "input": input_texts}
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    return _post("/api/embed", payload, timeout)


async def chat_stream(model: str, messages: list[dict], *, options: dict | None = None,
                       timeout: int = 300) -> AsyncIterator[dict]:
    """POST /api/chat (stream=True) — geparste NDJSON-Chunks (dicts) async yielden.

    Echtes async-Streaming (httpx statt urllib) — anders als alle anderen Funktionen
    hier läuft diese in FastAPI-Request-Kontext bis zu 300s (opt_stream_threadpool_0811):
    ein sync-Generator würde über Starlettes iterate_in_threadpool für die GESAMTE
    Stream-Dauer einen anyio-Threadpool-Worker belegen (dieselben ~40 Worker, die auch
    alle normalen `def`-Routen bedienen) — mehrere parallele Streams erschöpfen den
    Pool. httpx.AsyncClient hält den Request im Event-Loop, verbraucht 0 Worker.

    Aufrufer werten selbst aus (chunk["message"]["content"], chunk.get("done"),
    chunk.get("error")) — wie stream_service._stream_ollama es vorher inline tat.
    """
    payload = {"model": model, "messages": messages, "stream": True}
    if options:
        payload["options"] = options
    try:
        async for line in post_lines(f"{OLLAMA_URL}/api/chat", payload,
                                      client_factory=_ASYNC_CLIENT, timeout=timeout):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("Ollama-Stream-Chunk nicht parsbar: %r", line[:200])
    except httpx.HTTPStatusError as e:
        log.error("Ollama chat_stream fehlgeschlagen: HTTP %s", e.response.status_code)
        raise OllamaHTTPError(e.response.status_code, str(e)) from e
    except (httpx.RequestError, TimeoutError, OSError) as e:
        # httpx statt urllib (opt_stream_threadpool_0811) — httpx wirft nie
        # urllib.error.URLError, das fing hier vorher nichts ab: Verbindungsfehler/
        # Timeouts liefen als rohe httpx-Exception statt OllamaError zum Aufrufer durch.
        log.error("Ollama chat_stream fehlgeschlagen: %s", e)
        raise OllamaError(str(e)) from e

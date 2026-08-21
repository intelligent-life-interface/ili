"""Gemeinsamer httpx-Streaming-Transport für POST-Token-Streams (card_157ab2ca).

Vorher öffneten claude_client.stream_lines, ollama_client.chat_stream und
stream_service._stream_openwebui je einen fast identischen httpx.AsyncClient-
POST-Stream (Client öffnen, raise_for_status, Zeilen async yielden) — dieselbe
~10-Zeilen-Boilerplate dreimal abgetippt, mit dem Risiko, dass ein künftiger
Fix (z.B. an genau dieser Stelle, s. card_e9a3a4ff) nur an einer von drei
Kopien landet. Reine Transport-Schicht: parst NICHTS (kein JSON, kein
SSE-"data:"-Prefix) — das unterscheidet die drei Aufrufer und bleibt bei ihnen.
"""
import logging
from typing import AsyncIterator, Callable

import httpx

log = logging.getLogger("dashboard.services.httpx_stream")


async def post_lines(url: str, payload: dict, *, client_factory: Callable[..., httpx.AsyncClient],
                      headers: dict | None = None, timeout: float = 300.0) -> AsyncIterator[str]:
    """POST <url> mit stream=True, liefert nicht-leere, gestrippte Zeilen async.

    `client_factory` ist absichtlich ein Parameter statt hier fest auf
    `httpx.AsyncClient` verdrahtet: jedes der drei Aufrufer-Module behält damit
    sein eigenes `_ASYNC_CLIENT`-Modulattribut als Test-Patch-Punkt (Tests biegen
    gezielt EIN Modul auf einen httpx.MockTransport um, statt global auf
    httpx.AsyncClient zu patchen und damit fremde Tests mitzutreffen).

    Wirft httpx.HTTPStatusError / httpx.RequestError unverändert weiter —
    Fehler-Mapping (z.B. OllamaError/OllamaHTTPError) bleibt Sache des jeweiligen
    Aufrufers, der die Fehlerbedeutung kennt (Ollama tot vs. Poison-Input, ...).
    """
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    async with client_factory(timeout=httpx.Timeout(timeout)) as client:
        async with client.stream("POST", url, json=payload, headers=hdrs) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    yield line

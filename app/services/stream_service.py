"""Streaming-Dienste — Token-weise KI-Antworten (analyse-bug, ki-explain-stream).

Generatoren liefern rohe Text-Tokens; FastAPI StreamingResponse übernimmt das
Chunked-Encoding (das der alte Server von Hand machte). Abschluss: "\\n[DONE]",
Fehler mitten im Stream: "\\n[FEHLER] ...". Claude-Tagessperre → ClaudeBlockedError
VOR Stream-Beginn (HTTP 403).

Die eigentlichen Streams (_stream_openwebui/_stream_ollama/_run_stream) sind
ASYNC-Generatoren (opt_stream_threadpool_0811, Variante a von 3 vorgeschlagenen:
echtes async-Streaming statt dediziertem Threadpool oder mehr Limiter-Kapazität —
gewählt weil es Worker-Verbrauch auf 0 senkt statt ihn nur zu verschieben/vergrössern).
Starlettes StreamingResponse erkennt AsyncIterable und iteriert es direkt im
Event-Loop, statt wie bei einem sync-Generator jeden `next()`-Schritt über
iterate_in_threadpool in den anyio-Threadpool zu schieben — ein bis zu 300s
laufender Stream hätte sonst effektiv einen der ~40 Worker für die volle Dauer
belegt, denselben Pool, den auch alle normalen `def`-Routen nutzen. Tradeoff:
die Upstream-Parallelität (Ollama/OpenWebUI-Verbindungen) ist jetzt nicht mehr
implizit durch die Threadpool-Grösse (~40) gedeckelt, sondern unbegrenzt — bisher
kein Problem, da Ollama/OpenWebUI selbst die Bremse sind.

Die Factory-Funktionen (analyse_bug_stream/ki_explain_stream) bleiben bewusst
SYNC `def`: der Claude-Tagessperre-Check (_check_claude_block) muss VOR dem
ersten Byte der Response laufen, damit `_streaming_or_403` noch mit einem
sauberen 403 antworten kann. Würden die Factories selbst async-Generatoren sein,
liefe der Check erst bei der ersten Iteration — nach dem Response-Start, also
zu spät für einen 403.
"""
import json
import logging
from typing import AsyncIterator

import anyio
import httpx

import ow_integration
from config_handler import _effort_temp, _load_ai_config
from constants import OPENWEBUI_URL
from cost_management import _is_claude_blocked
from logging_utils import _track_ollama_usage
from app.services import ollama_client
from app.services.httpx_stream import post_lines

log = logging.getLogger("dashboard.services.stream")

# Indirektion statt direktem httpx.AsyncClient-Aufruf (httpx ist ein geteiltes Modul,
# s. app/services/ollama_client.py) — Tests patchen gezielt diesen Namen.
_ASYNC_CLIENT = httpx.AsyncClient


class ClaudeBlockedError(Exception):
    """Claude-Tagesbudget erschöpft — Request ablehnen bevor der Stream startet."""


def _check_claude_block(model: str) -> None:
    if model.startswith("claude"):
        blocked, reason = _is_claude_blocked()
        if blocked:
            log.warning("Claude-Stream gesperrt: %s", reason)
            raise ClaudeBlockedError(reason)


async def _stream_openwebui(model: str, prompt: str) -> AsyncIterator[str]:
    """Claude via Open WebUI (OpenAI-SSE) — Tokens async yielden."""
    token = getattr(ow_integration, "_ow_token", "")
    if not token:
        # Blockierender Login-Call (bis zu 10s) — nicht im Event-Loop, siehe
        # opt_async_blocker_0806 (derselbe Bug, den dieser Fix hier für die
        # Stream-Dauer selbst behebt).
        token = await anyio.to_thread.run_sync(ow_integration._ow_login)
    stream_body = {
        "model": model, "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"Authorization": f"Bearer {token}"}
    async for line in post_lines(f"{OPENWEBUI_URL}/api/chat/completions", stream_body,
                                  client_factory=_ASYNC_CLIENT, headers=headers, timeout=300.0):
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except Exception:
            log.warning("Stream-Chunk (openwebui) nicht parsbar: %r", data_str[:200])
            continue
        if chunk.get("error"):
            # Fehler-Payload NICHT stillschweigend verschlucken — sonst bekommt der
            # User eine leere Antwort, die wie Erfolg aussieht.
            raise RuntimeError(chunk["error"])
        try:
            tok = chunk["choices"][0]["delta"].get("content", "")
            if tok:
                yield tok
        except (KeyError, IndexError, TypeError) as e:
            log.warning("Stream-Chunk (openwebui) unerwartetes Format: %r (%s)", data_str[:200], e)


async def _stream_ollama(model: str, prompt: str, effort_key: str, usage_context: str) -> AsyncIterator[str]:
    """Ollama NDJSON-Stream — Tokens async yielden, am Ende Usage tracken."""
    p_tok = e_tok = 0
    async for chunk in ollama_client.chat_stream(
        model, [{"role": "user", "content": prompt}],
        options={"temperature": _effort_temp(effort_key)}, timeout=300,
    ):
        if chunk.get("error"):
            # Fehler-Payload (z.B. "model not found") NICHT stillschweigend verschlucken.
            raise RuntimeError(chunk["error"])
        tok = chunk.get("message", {}).get("content", "")
        if tok:
            yield tok
        if chunk.get("done"):
            p_tok = chunk.get("prompt_eval_count", 0)
            e_tok = chunk.get("eval_count", 0)
            break
    # Kleiner blockierender Datei-Append — konsistent im Threadpool statt im Event-Loop.
    await anyio.to_thread.run_sync(_track_ollama_usage, model, p_tok, e_tok, usage_context)


async def _run_stream(model: str, prompt: str, effort_key: str, usage_context: str,
                      done_log: str) -> AsyncIterator[str]:
    """Gemeinsamer Rahmen: Routing + [DONE]/[FEHLER]-Abschluss."""
    try:
        if model.startswith("claude"):
            async for tok in _stream_openwebui(model, prompt):
                yield tok
        else:
            async for tok in _stream_ollama(model, prompt, effort_key, usage_context):
                yield tok
        yield "\n[DONE]"
        log.info("%s", done_log)
    except Exception as e:
        log.error("Stream fehlgeschlagen (%s): %s", usage_context, e)
        yield f"\n[FEHLER] {e}"


def analyse_bug_stream(body: dict) -> AsyncIterator[str]:
    """POST /analyse-bug — Ollama/Claude-Fehleranalyse streamen.

    Raises:
        ClaudeBlockedError: vor Stream-Beginn (→ 403).
    """
    bug = body.get("bug", {})
    model = body.get("model") or _load_ai_config().get("bug_model", "qwen2.5-coder:latest")

    headline = bug.get("headline", "")
    context = bug.get("context", "")
    service = bug.get("service", "")
    level = bug.get("level", "")
    source = bug.get("source", "")

    prompt = (
        f"Du bist ein erfahrener Linux/Python-Entwickler. Analysiere folgenden Fehler und antworte auf Deutsch.\n\n"
        f"Service: {service}\n"
        f"Schweregrad: {level}\n"
        f"Quelle: {source}\n"
        f"Fehler: {headline}\n\n"
        f"Log-Kontext:\n```\n{context}\n```\n\n"
        f"Antworte in genau diesem Format:\n\n"
        f"**Ursache:** <1-2 Sätze>\n\n"
        f"**Zu ändernde Dateien:**\n"
        f"- `<absoluter Pfad>:<Zeile|Zeilenbereich>` — <was geändert werden muss>\n"
        f"- (mehrere Einträge falls nötig)\n\n"
        f"**Fix:** <1-3 Sätze konkreter Lösungsweg>\n\n"
        f"**Prävention:** <1 Satz, falls relevant>\n\n"
        f"WICHTIG: Wenn du die Datei oder Zeile nicht eindeutig kennst, schreibe "
        f"`<unbekannt — zu suchen mit: grep -n \"PATTERN\" PFAD>`. "
        f"Erfinde KEINE Pfade. Nutze IMMER absolute Pfade passend zum System oder `/etc/...` etc."
    )

    _check_claude_block(model)
    log.info("Analyse-Bug: model=%r service=%r claude=%s", model, service, model.startswith("claude"))
    return _run_stream(model, prompt, "bug_effort",
                       f"bug_analyse:{service}:{headline[:40]}",
                       f"Analyse-Bug abgeschlossen: service={service!r}")


def ki_explain_stream(body: dict) -> AsyncIterator[str]:
    """POST /ki-explain-stream — KI-Erklärung eines Vorschlags streamen.

    Raises:
        ClaudeBlockedError: vor Stream-Beginn (→ 403).
    """
    model = body.get("model") or _load_ai_config().get("ki_explain_model", "gemma3:12b")
    board_name = body.get("board_name", body.get("board_id", ""))
    title = body.get("title", "")
    desc = body.get("desc", "")

    prompt = (
        f"Du bist ein erfahrener Software-Entwickler. "
        f"Erkläre folgenden Entwicklungsvorschlag für das Projekt \"{board_name}\" ausführlich auf Deutsch:\n\n"
        f"Titel: {title}\n"
        + (f"Beschreibung: {desc}\n\n" if desc else "\n")
        + "Beantworte:\n"
        "1. Was soll konkret umgesetzt werden?\n"
        "2. Warum ist das sinnvoll?\n"
        "3. Wie würde die technische Umsetzung aussehen? (Konkrete Schritte)\n"
        "4. Worauf muss man achten?"
    )

    _check_claude_block(model)
    log.info("Explain-Stream: model=%r title=%r claude=%s", model, title, model.startswith("claude"))
    return _run_stream(model, prompt, "ki_explain_effort",
                       f"ki_explain:{title[:40]}",
                       f"Explain-Stream abgeschlossen: {title!r}")

"""chat_helpers.py — direkte Anthropic + Ollama Chat-Calls mit Quota-Fallback.

Ersetzt die in trigger_server.py.bak definierten _anthropic_with_tools /
_ollama_with_tools / _ollama_chat — ohne Tool-Use (für Bug-Chat genügt das).
"""
import json
import logging
import urllib.request
import urllib.error
from constants import ANTHROPIC_API_KEY, OLLAMA_URL

log = logging.getLogger("dashboard.chat_helpers")


_QUOTA_KEYWORDS = ("credit balance", "insufficient", "quota", "rate limit",
                   "rate_limit", "guthaben", "payment", "billing")


def _is_quota_error(status: int, body: str) -> bool:
    """Heuristik: 4xx-Fehler + Quota-Stichwort im Body."""
    if status not in (400, 402, 429):
        return False
    body_lc = (body or "").lower()
    return any(k in body_lc for k in _QUOTA_KEYWORDS)


def _anthropic_messages_call(payload: dict) -> tuple[int, dict]:
    """Direkter Call an Anthropic Messages API. Gibt (status, parsed_json) zurück."""
    if not ANTHROPIC_API_KEY:
        return 500, {"error": "ANTHROPIC_API_KEY nicht gesetzt"}

    # OpenAI-Style messages → Anthropic-Style: system separat, restliche als messages
    msgs = payload.get("messages", [])
    system_parts = [m["content"] for m in msgs if m.get("role") == "system"]
    chat_msgs    = [m for m in msgs if m.get("role") != "system"]

    # Prompt-Caching: letzte User/Assistant-Message als Content-Block-Liste markieren,
    # damit der gesamte vorausgehende Conversation-Prefix wiederverwendbar gecacht wird.
    # Anthropic erlaubt max. 4 cache_control Breakpoints; wir nutzen 2: system + letzte Msg.
    if chat_msgs:
        last = dict(chat_msgs[-1])
        content = last.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        elif not isinstance(content, list):
            content = [{"type": "text", "text": str(content)}]
        if content:
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        last["content"] = content
        chat_msgs = chat_msgs[:-1] + [last]

    body = {
        "model":      payload.get("model", "claude-sonnet-4-6"),
        "max_tokens": payload.get("max_tokens", 1500),
        "messages":   chat_msgs,
    }
    if system_parts:
        body["system"] = [{
            "type": "text",
            "text": "\n\n".join(system_parts),
            "cache_control": {"type": "ephemeral"},
        }]
    if "temperature" in payload:
        body["temperature"] = payload["temperature"]

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": raw}
    except Exception as e:
        log.error(f"Anthropic-Call Exception: {e}")
        return 500, {"error": str(e)}


def _anthropic_to_openai_format(resp: dict) -> dict:
    """Anthropic-Antwort → OpenAI-kompatibles Format (für Frontend-Konsumenten)."""
    text = ""
    for block in resp.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    usage = resp.get("usage") or {}
    log.info(
        "anthropic usage: input=%s cache_read=%s cache_write=%s output=%s",
        usage.get("input_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
        usage.get("cache_creation_input_tokens", 0),
        usage.get("output_tokens", 0),
    )
    return {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": resp.get("stop_reason", "stop"),
        }],
        "model": resp.get("model"),
    }


def _simple_ollama_chat(payload: dict, context: str = "") -> dict:
    """Plain Ollama-Chat (kein Tool-Use). Gibt OpenAI-Format zurück."""
    body = {
        "model":    payload.get("model", "gemma3:12b"),
        "messages": payload.get("messages", []),
        "stream":   False,
    }
    if "options" in payload:
        body["options"] = payload["options"]

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        log.error(f"Ollama-Call Exception ({context}): {e}")
        return {"choices": [{"message": {"role": "assistant",
                                          "content": f"⚠️ Ollama-Fehler: {e}"}}]}

    msg = data.get("message", {})
    return {
        "choices": [{
            "index": 0,
            "message": {"role": msg.get("role", "assistant"),
                        "content": msg.get("content", "")},
            "finish_reason": "stop",
        }],
        "model": data.get("model"),
    }


def _anthropic_chat_with_fallback(payload: dict, fallback_model: str = "qwen3:8b") -> dict:
    """Versucht Anthropic; bei Quota-Fehler → Ollama mit Hinweis-Banner."""
    status, resp = _anthropic_messages_call(payload)
    if status == 200:
        return _anthropic_to_openai_format(resp)

    body_str = json.dumps(resp)
    if _is_quota_error(status, body_str):
        log.warning(f"Anthropic Quota-Fehler ({status}) — Fallback auf Ollama")
        # Banner an erste assistant-message vorne dranhängen
        fb_payload = dict(payload)
        fb_payload["model"] = fallback_model
        ollama_resp = _simple_ollama_chat(fb_payload, context="anthropic-fallback")
        try:
            txt = ollama_resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            txt = ""
        banner = (
            "💸 **Anthropic-Guthaben aufgebraucht** — bitte aufladen unter "
            "https://console.anthropic.com/settings/billing\n\n"
            f"_Antwort jetzt von Ollama (`{fallback_model}`):_\n\n"
        )
        ollama_resp["choices"][0]["message"]["content"] = banner + txt
        return ollama_resp

    # Anderer Fehler — direkt zurückgeben
    err = resp.get("error", {})
    err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
    return {"choices": [{"message": {
        "role": "assistant",
        "content": f"⚠️ Anthropic-Fehler {status}: {err_msg or body_str[:300]}"
    }}]}

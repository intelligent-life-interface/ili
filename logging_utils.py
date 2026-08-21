"""\nlogging_utils.py — Logging und Tracking-Funktionen\nAutogeneriert von script_splitter.py\n"""
import json
import logging
from datetime import datetime
from constants import CHAT_HISTORY_FILE, AI_DEV_LOG_FILE, OLLAMA_USAGE_FILE, KI_FEEDBACK_FILE

log = logging.getLogger("dashboard.logging_utils")
from app.storage.atomic_write import write_json_atomic


def _log_chat_history(board_id: str, model: str, user_message: str, assistant_message: str) -> None:
    """Appends a chat turn to chat_history.jsonl and the unified ai_dev_log.jsonl."""
    ts = datetime.now().isoformat()
    chat_entry = {
        "timestamp":  ts,
        "source":     "kanban-chat",
        "board_id":   board_id,
        "model":      model,
        "user":       user_message,
        "assistant":  assistant_message,
    }
    try:
        with CHAT_HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(chat_entry, ensure_ascii=False) + "\n")
        log.debug(f"Chat-History gespeichert: board={board_id!r}, model={model!r}, user={user_message[:60]!r}")
    except Exception as e:
        log.error(f"Chat-History konnte nicht gespeichert werden: {e}")

    # Auch ins unified AI-Dev-Log schreiben
    dev_entry = {
        "timestamp": ts,
        "source":    "kanban-chat",
        "model":     model,
        "board_id":  board_id,
        "user":      user_message[:300],
        "assistant": assistant_message[:300],
    }
    try:
        with AI_DEV_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(dev_entry, ensure_ascii=False) + "\n")
        log.debug(f"AI-Dev-Log (chat) gespeichert: model={model!r}")
    except Exception as e:
        log.error(f"AI-Dev-Log (chat) konnte nicht gespeichert werden: {e}")


# Preise (USD per 1M Tokens, Stand 2025-05)
# USD pro 1 Mio Tokens. Konvention: cache_read = 0.1x in, cache_write(5min) = 1.25x in.
# Preise Stand 2026-07 (Anthropic). WICHTIG: hier müssen ALLE tatsächlich genutzten
# Modelle stehen, sonst greift der (billigere) Default und die Kosten werden zu tief
# berechnet. Genutzt werden aktuell v.a. opus-4-8, fable-5, sonnet-5.
_CLAUDE_PRICES = {
    "claude-opus-4-8":           {"in": 5.00,  "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-7":           {"in": 5.00,  "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-6":           {"in": 5.00,  "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-fable-5":            {"in": 10.00, "out": 50.00, "cache_read": 1.00, "cache_write": 12.50},
    # Sonnet-5 Standardpreis ab 01.09.2026 (Einführungspreis endete 31.08.2026).
    "claude-sonnet-5":           {"in": 3.00,  "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-6":         {"in": 3.00,  "out": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5":          {"in": 1.00,  "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
    "claude-haiku-4-5-20251001": {"in": 1.00,  "out": 5.00,  "cache_read": 0.10, "cache_write": 1.25},
}

# Fallback-Tarif für unbekannte Modelle = Sonnet-5-Preis. KANONISCH und EINZIGE Quelle
# (opt_altlasten_0806): früher stand dieser Tarif 4× hartkodiert herum (hier inline, plus
# 2× in cost_service.py). Bewusst als Referenz auf den Tabelleneintrag, damit es garantiert
# keine driftende Kopie mehr gibt. Wer den Default braucht: `from logging_utils import _PRICE_DEFAULT`.
_PRICE_DEFAULT = _CLAUDE_PRICES["claude-sonnet-5"]


def _track_ollama_usage(model: str, prompt_tokens: int, eval_tokens: int,
                        context: str = "", source: str = "dashboard") -> None:
    """Loggt Ollama-Token-Nutzung (keine Kosten) in ollama_usage_log.jsonl."""
    entry = {
        "ts":            datetime.now().isoformat(),
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "model":         model,
        "prompt_tokens": prompt_tokens,
        "eval_tokens":   eval_tokens,
        "total_tokens":  prompt_tokens + eval_tokens,
        "context":       context,
        "source":        source,
    }
    try:
        with OLLAMA_USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        log.debug(f"[OllamaTrack] {model}: prompt={prompt_tokens} eval={eval_tokens} ctx={context!r}")
    except Exception as e:
        log.error(f"Ollama-Usage-Log fehlgeschlagen: {e}")




def _load_ki_feedback() -> dict:
    try:
        if KI_FEEDBACK_FILE.exists():
            return json.loads(KI_FEEDBACK_FILE.read_text())
    except Exception as e:
        log.warning(f"ki_feedback.json laden fehlgeschlagen: {e}")
    return {"rejections": []}


def _save_ki_feedback(data: dict):
    write_json_atomic(KI_FEEDBACK_FILE, data)
    log.debug(f"ki_feedback.json gespeichert: {len(data.get('rejections',[]))} Einträge")

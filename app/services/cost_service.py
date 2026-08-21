"""Kosten-/Usage-Aggregation — extrahiert aus trigger_server._handle_claude_cost / _handle_ollama_usage.

Schnittstelle
-------------
claude_cost_summary()  -> dict   # {total_usd, today_usd, calls_*, by_day, by_model, calls, hourly_today}
                                 # 60s-Cache (Datei-I/O über ~/.claude/projects ist teuer)
ollama_usage_summary() -> dict   # {calls_*, total_*, today_*, by_model, calls}
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from app.services.ttl_cache import TTLCache
from constants import CLAUDE_COST_FILE, OLLAMA_USAGE_FILE, _DASH
from logging_utils import _CLAUDE_PRICES, _PRICE_DEFAULT  # zentrale Preisliste + Fallback — keine Kopien pflegen (opt_altlasten_0806)

log = logging.getLogger("dashboard.services.cost")


def _load_jsonl_lines(filepath: Path) -> tuple[list, int]:
    """Liest JSONL-Datei, zählt und logged korrupte Zeilen EINMAL pro Datei.

    Rückgabe: (gültige_objekte, count_korrupt)
    """
    lines = []
    corrupted = 0
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("[CostAPI] Kann %s nicht lesen: %s", filepath.name, e)
        return [], 0

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        try:
            obj = json.loads(raw_line)
            lines.append(obj)
        except (json.JSONDecodeError, ValueError) as e:
            corrupted += 1
            log.debug("[CostAPI] Korrupte Zeile in %s: %s (Zeile ~%d)",
                     filepath.name, str(e)[:60], len(lines) + corrupted)

    if corrupted > 0:
        log.warning("[CostAPI] %s: %d korrupte Zeilen übersprungen (%d gültig)",
                   filepath.name, corrupted, len(lines))

    return lines, corrupted


# Single-Flight-Caches gegen Cache-Stampede (opt_cache_stampede_0806): läuft der
# Cache ab während mehrere Requests anliegen, würden sonst ALLE parallel den teuren
# CLI-Session-Scan (hunderte Dateien) fahren. TTLCache nutzt Double-Checked Locking —
# der Cache-Hit-Pfad bleibt lockfrei, damit schnelle Requests nicht serialisiert werden.
_calls_cache_ttl = TTLCache(ttl_seconds=60.0)
_summary_cache_ttl = TTLCache(ttl_seconds=60.0)


def _get_all_calls_uncached() -> list:
    """Interne Hilfsfunktion für get_all_calls() — wird vom TTLCache aufgerufen."""
    all_calls: list = []
    seen_msg_ids: set = set()
    _scan_cli_sessions(all_calls, seen_msg_ids)
    _scan_dashboard_log(all_calls)
    log.debug("[CostAPI] get_all_calls: %d Einträge gescannt (Cache erneuert)",
              len(all_calls))
    return all_calls


def get_all_calls() -> list:
    """Alle Claude-Calls (CLI-Sessions + Dashboard-Log) — EIN gemeinsamer, gelockter Scan.

    Single Source of Truth für den teuren Datei-Scan: sowohl `claude_cost_summary`
    als auch `budget_service` konsumieren dieses Ergebnis (früher zwei getrennte
    Caches, die dieselben Dateien doppelt scannten). Rückgabe ist die gecachte Liste
    — Aufrufer NUR lesen/kopieren, nicht mutieren. Single-Flight via TTLCache.
    """
    return _calls_cache_ttl.get(_get_all_calls_uncached)


def _cost_for_entry(model: str, in_tok: int, out_tok: int,
                    cache_read: int = 0, cache_write: int = 0) -> float:
    p = _CLAUDE_PRICES.get(model, _PRICE_DEFAULT)
    return (in_tok / 1_000_000 * p["in"]
            + out_tok / 1_000_000 * p["out"]
            + cache_read / 1_000_000 * p.get("cache_read", 0.30)
            + cache_write / 1_000_000 * p.get("cache_write", 3.75))


def _first_user_text(content) -> str:
    if isinstance(content, list):
        for part in content:
            if part.get("type") == "text":
                return part.get("text", "")[:60].strip()
        return ""
    if isinstance(content, str):
        return content[:60].strip()
    return ""


def _first_user_full_text(content) -> str:
    """Wie `_first_user_text`, aber UNGEKÜRZT — für die Loop-Marker-Suche (der Marker
    steht am Ende langer Automat-Prompts, die 60-Zeichen-Kürzung würde ihn abschneiden)."""
    if isinstance(content, list):
        for part in content:
            if part.get("type") == "text":
                return part.get("text", "")
        return ""
    if isinstance(content, str):
        return content
    return ""


# Projekt-/Loop-Zuordnung (2026-08-14): Claude Code kodiert den absoluten Session-cwd
# in den Verzeichnisnamen unter ~/.claude/projects/ (`/` -> `-`, verifiziert per `ls`).
# Bekannte Basen sind ~/containers/<slug> und ~/Projekte/<slug> — daraus lässt sich der
# Projekt-Slug rückwirkend für die GESAMTE Historie zurückgewinnen. Die Loop-Zuordnung
# (welcher automatisierte Auftraggeber die Session gestartet hat) ist dagegen nur AB JETZT
# zuverlässig: sie stützt sich auf einen expliziten `[Loop: ...]`-Marker am Ende der
# Kanban-Automat-Prompts (worker.py/review.py/fable_optimize.py) bzw. den eindeutigen cwd
# des Manager-Loops (~/bin/manager) — für ältere Sessions ohne Marker greift der Fallback
# "terminal" (interaktive Nutzung, die nie einen Prompt-Text als Argument übergibt).
_HOME_ENC = str(Path.home()).replace("/", "-")
_CONTAINERS_PREFIX = f"{_HOME_ENC}-containers-"
_PROJEKTE_PREFIX = f"{_HOME_ENC}-Projekte-"
_MANAGER_DIR = f"{_HOME_ENC}-bin-manager"
_LOOP_MARKER_RE = re.compile(r"\[Loop: ([\w.-]+)\]")


def _project_from_session_dir(dir_name: str) -> "str | None":
    """Projekt-Slug aus dem kodierten Session-Verzeichnisnamen, oder None ohne Projektbezug
    (Home-Root, ~/bin/manager, unbekannte Basis)."""
    if dir_name.startswith(_CONTAINERS_PREFIX):
        return dir_name[len(_CONTAINERS_PREFIX):]
    if dir_name.startswith(_PROJEKTE_PREFIX):
        return dir_name[len(_PROJEKTE_PREFIX):]
    return None


def _loop_from_session(dir_name: str, first_user_full_text: str) -> str:
    """Welcher Loop die Session gestartet hat: `manager` (eindeutiger cwd), ein per
    `[Loop: ...]`-Marker erkannter Kanban-Automat-Worker, sonst Fallback `terminal`."""
    if dir_name == _MANAGER_DIR:
        return "manager"
    m = _LOOP_MARKER_RE.search(first_user_full_text)
    if m:
        return m.group(1)
    return "terminal"


def _scan_cli_sessions(all_calls: list, seen_msg_ids: set) -> None:
    """Claude-Code-CLI-Session-JSONLs einsammeln (dedupliziert über message-id)."""
    session_dir = Path(os.environ.get("CLAUDE_SESSION_DIR", str(Path.home() / ".claude/projects")))
    # rglob: Claude Code legt Sessions in Projekt-Unterordnern ab (~/.claude/projects/<proj>/*.jsonl)
    jsonl_files = list(session_dir.rglob("*.jsonl"))
    log.debug("[CostAPI] Scanne %d Session-Dateien…", len(jsonl_files))

    for fp in jsonl_files:
        lines, _ = _load_jsonl_lines(fp)
        first_user_full = ""
        for obj in lines:
            if obj.get("type") == "user":
                first_user_full = _first_user_full_text(obj.get("message", {}).get("content", ""))
                if first_user_full:
                    break
        session_label = first_user_full[:60].strip()
        project = _project_from_session_dir(fp.parent.name)
        loop = _loop_from_session(fp.parent.name, first_user_full)

        last_user_text = session_label
        for obj in lines:

            if obj.get("type") == "user":
                txt = _first_user_text(obj.get("message", {}).get("content", ""))
                if txt:
                    last_user_text = txt
                continue

            msg = obj.get("message", {})
            model = msg.get("model", "")
            if not model.startswith("claude"):
                continue
            usage = msg.get("usage")
            if not usage:
                continue
            out_tok = usage.get("output_tokens", 0)
            if out_tok == 0:
                continue
            msg_id = msg.get("id", "")
            if msg_id and msg_id in seen_msg_ids:
                continue
            if msg_id:
                seen_msg_ids.add(msg_id)

            in_tok = usage.get("input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_write = usage.get("cache_creation_input_tokens", 0)

            content = msg.get("content", [])
            tools = [c.get("name") for c in content if c.get("type") == "tool_use" and c.get("name")]
            tool_str = ", ".join(tools) if tools else "Text"
            context = f"{tool_str} | {last_user_text}" if last_user_text else tool_str

            all_calls.append({
                "ts": obj.get("timestamp", ""),
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "cost_usd": round(_cost_for_entry(model, in_tok, out_tok, cache_read, cache_write), 6),
                "source": "claude-code",
                "context": context,
                "session": fp.stem[:8],
                "project": project,
                "loop": loop,
            })


def _extract_endpoint_from_context(context: str) -> str:
    """
    Heuristik: Endpoint-Name aus context-String ableiten.
    z.B. "chat:board-name" -> "/api/chat"
    """
    if not context:
        return "unknown"
    context_lower = context.lower()
    if context_lower.startswith("chat:"):
        return "/api/chat"
    elif context_lower == "ki_critique":
        return "/api/ki/critique"
    elif context_lower.startswith("brainstorm"):
        return "/api/brainstorm"
    elif context_lower.startswith("project:"):
        return "/api/project"
    elif context_lower.startswith("bug"):
        return "/api/bug"
    elif "_" in context_lower:
        # Fallback: first part before colon/underscore as module
        module = context_lower.split(":")[0].split("_")[0]
        return f"/api/{module}" if module and module != "dashboard" else "unknown"
    return "unknown"


def _scan_dashboard_log(all_calls: list) -> None:
    """Einträge aus claude_cost_log.jsonl (Dashboard-Chat etc.) anhängen."""
    if not CLAUDE_COST_FILE.exists():
        return
    lines, _ = _load_jsonl_lines(CLAUDE_COST_FILE)
    count = 0
    for e in lines:
        model = e.get("model", "")
        if not model.startswith("claude"):
            continue
        in_tok = e.get("input_tokens", 0)
        out_tok = e.get("output_tokens", 0)
        cost = e.get("cost_usd")
        if cost is None:
            cost = _cost_for_entry(model, in_tok, out_tok)
        context = e.get("context", "")
        endpoint = _extract_endpoint_from_context(context)
        all_calls.append({
            "ts": e.get("ts", ""),
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cache_read_tokens": e.get("cache_read_tokens", 0),
            "cache_write_tokens": e.get("cache_write_tokens", 0),
            "cost_usd": round(float(cost), 6),
            "source": e.get("source", "dashboard"),
            "context": context,
            "endpoint": endpoint,
            "session": "",
            # Kein aktiver Schreiber von claude_cost_log.jsonl setzt aktuell einen
            # projektbezogenen `context` (geprüft: cost_management.py/check_ai_routing.py
            # setzen das Feld nie) — daher hier ehrlich None statt einer Heuristik auf ein
            # praktisch immer leeres Feld. `loop` ist für Dashboard-Aufrufe immer "dashboard".
            "project": None,
            "loop": "dashboard",
        })
        count += 1
    log.debug("[CostAPI] Dashboard-Log: %d Einträge", count)


def _claude_cost_summary_uncached() -> dict:
    """Interne Hilfsfunktion für claude_cost_summary() — wird vom TTLCache aufgerufen."""
    log.info("[CostAPI] Berechne Claude-Kosten aus Session-Dateien und Dashboard-Log…")
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Gemeinsamer, ebenfalls gelockter Scan (mit budget_service geteilt).
    all_calls = get_all_calls()
    log.info("[CostAPI] Gesamt %d Einträge verarbeitet", len(all_calls))

    result = _aggregate_calls(all_calls, today_str)
    log.info("[CostAPI] total=$%.4f, heute=$%.4f, calls_gesamt=%d, calls_heute=%d",
             result["total_usd"], result["today_usd"],
             result["calls_total"], result["calls_today"])
    return result


def claude_cost_summary() -> dict:
    """Claude-API-Kosten aggregieren (CLI-Sessions + Dashboard-Log), 60s gecacht.

    Single-Flight via TTLCache: nur der erste Thread aggregiert, parallele Requests
    warten und übernehmen danach das frische Ergebnis."""
    return _summary_cache_ttl.get(_claude_cost_summary_uncached)


def _aggregate_calls(all_calls: list, today_str: str) -> dict:
    """Aggregiert die Roh-Calls zur Kosten-Zusammenfassung (reine Rechnung, kein I/O)."""
    total_usd = 0.0
    today_usd = 0.0
    calls_today = 0
    by_day: dict = {}
    by_model: dict = {}
    by_project: dict = {}
    by_loop: dict = {}
    hourly_today: dict = {str(h).zfill(2): 0.0 for h in range(24)}
    # Caching-Kennzahlen: cache_read wird nur zu ~10% des Input-Preises berechnet.
    # "Ersparnis" = was die cache_read-Tokens zum vollen Input-Preis GEKOSTET hätten,
    # minus was sie tatsächlich (cache_read-Preis) kosten.
    cache_read_total = 0
    cache_write_total = 0
    cache_savings_usd = 0.0

    for c in all_calls:
        cost = c["cost_usd"]
        ts = c["ts"]
        model = c["model"]
        date_str = ts[:10] if len(ts) >= 10 else ""
        hour_str = ts[11:13] if len(ts) >= 13 else ""

        cr = c.get("cache_read_tokens", 0)
        cache_read_total += cr
        cache_write_total += c.get("cache_write_tokens", 0)
        pr = _CLAUDE_PRICES.get(model, _PRICE_DEFAULT)
        cache_savings_usd += cr / 1_000_000 * (pr["in"] - pr.get("cache_read", pr["in"] * 0.1))

        total_usd += cost
        if date_str == today_str:
            today_usd += cost
            calls_today += 1
            if hour_str:
                hourly_today[hour_str] = round(hourly_today.get(hour_str, 0.0) + cost, 6)
        if date_str:
            by_day[date_str] = round(by_day.get(date_str, 0.0) + cost, 6)

        bm = by_model.setdefault(model, {
            "calls": 0, "cost_usd": 0.0,
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
        })
        bm["calls"] += 1
        bm["cost_usd"] = round(bm["cost_usd"] + cost, 6)
        bm["input_tokens"] += c.get("input_tokens", 0)
        bm["output_tokens"] += c.get("output_tokens", 0)
        bm["cache_read_tokens"] += c.get("cache_read_tokens", 0)

        # Projekt/Loop = "?" statt None als Dict-Key, damit "kein Projektbezug"/"kein
        # erkannter Loop" in der Anzeige sichtbar bleibt statt als JSON-null-Key zu landen.
        proj_key = c.get("project") or "?"
        bp = by_project.setdefault(proj_key, {"calls": 0, "cost_usd": 0.0, "tokens": 0})
        bp["calls"] += 1
        bp["cost_usd"] = round(bp["cost_usd"] + cost, 6)
        bp["tokens"] += c.get("input_tokens", 0) + c.get("output_tokens", 0) + cr + c.get("cache_write_tokens", 0)

        loop_key = c.get("loop") or "?"
        bl = by_loop.setdefault(loop_key, {"calls": 0, "cost_usd": 0.0, "tokens": 0})
        bl["calls"] += 1
        bl["cost_usd"] = round(bl["cost_usd"] + cost, 6)
        bl["tokens"] += c.get("input_tokens", 0) + c.get("output_tokens", 0) + cr + c.get("cache_write_tokens", 0)

    result = {
        "total_usd": round(total_usd, 4),
        "today_usd": round(today_usd, 4),
        "calls_total": len(all_calls),
        "calls_today": calls_today,
        "by_day": dict(sorted(by_day.items())),
        "by_model": by_model,
        "by_project": dict(sorted(by_project.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True)),
        "by_loop": dict(sorted(by_loop.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True)),
        "calls": sorted(all_calls, key=lambda x: x["ts"], reverse=True),
        "hourly_today": hourly_today,
        "cache_read_total": cache_read_total,
        "cache_write_total": cache_write_total,
        "cache_savings_usd": round(cache_savings_usd, 2),
    }
    return result


def ollama_usage_summary() -> dict:
    """Ollama-Token-Nutzung aus allen Usage-Logs aggregieren."""
    log.info("[OllamaAPI] Berechne Ollama-Usage…")
    today_str = datetime.now().strftime("%Y-%m-%d")

    all_calls: list = []
    usage_files = [OLLAMA_USAGE_FILE,
                   _DASH / "ki_advisor_ollama_usage.jsonl",
                   _DASH / "ki_explain_ollama_usage.jsonl",
                   _DASH / "session_monitor_ollama_usage.jsonl"]
    for f in usage_files:
        if not f.exists():
            continue
        lines, _ = _load_jsonl_lines(f)
        all_calls.extend(lines)

    total_prompt = sum(c.get("prompt_tokens", 0) for c in all_calls)
    total_eval = sum(c.get("eval_tokens", 0) for c in all_calls)
    total_tok = sum(c.get("total_tokens", 0) for c in all_calls)
    today_calls = [c for c in all_calls if c.get("date", c.get("ts", "")[:10]) == today_str]

    by_model: dict = {}
    for c in all_calls:
        m = c.get("model", "unbekannt")
        bm = by_model.setdefault(m, {"calls": 0, "prompt_tokens": 0, "eval_tokens": 0, "total_tokens": 0})
        bm["calls"] += 1
        bm["prompt_tokens"] += c.get("prompt_tokens", 0)
        bm["eval_tokens"] += c.get("eval_tokens", 0)
        bm["total_tokens"] += c.get("total_tokens", 0)

    result = {
        "calls_total": len(all_calls),
        "calls_today": len(today_calls),
        "total_prompt": total_prompt,
        "total_eval": total_eval,
        "total_tokens": total_tok,
        "today_prompt": sum(c.get("prompt_tokens", 0) for c in today_calls),
        "today_eval": sum(c.get("eval_tokens", 0) for c in today_calls),
        "today_tokens": sum(c.get("total_tokens", 0) for c in today_calls),
        "by_model": by_model,
        "calls": sorted(all_calls, key=lambda x: x.get("ts", ""), reverse=True),
    }
    log.info("[OllamaAPI] %d Einträge, gesamt=%d Tokens, heute=%d",
             len(all_calls), total_tok, result["today_tokens"])
    return result

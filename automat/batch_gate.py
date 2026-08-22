"""Kostenlimit-Gate für den Batch-API-Pfad — PRO PROJEKTGRUPPE (Manifest `category`).

Idee: Offene, nicht zeitkritische Karten dürfen über die Message Batches API
(async, 50% günstiger) einen Entwicklungs-Vorschlag bekommen — aber pro Projektgruppe
(z.B. Hobby) nur bis zu einem Kostenlimit (in CHF ODER Token). Analog zu priority_gate.py
/ fable_gate.py: konservativ (jeder Unsicherheitsfall → zu), keine eigene komplizierte
Budget-Logik, sondern einfache Summe aus dem lokalen Spend-Ledger.

Warum lokal statt über /api/budget: Der Abo-Verbrauch liegt im Dashboard-Token-Budget;
der Batch-API-Spend (echtes API-Guthaben) ist ein SEPARATER Topf. Wir tracken ihn deshalb
selbst in `state/batch/spend.jsonl` (Source of Truth) und lesen das GUI-editierbare Limit
aus `~/containers/dashboard/batch_budget.json` — dasselbe Cross-Read-Muster, das limits.py
schon mit automat_limits.json nutzt.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import automat_lib as lib
from automat_lib import logger

# GUI-editierbare Konfig (Limit je category). Cross-Read wie limits.py → automat_limits.json.
BUDGET_FILE = Path(
    os.getenv("AUTOMAT_BATCH_BUDGET_FILE",
              str(Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "batch_budget.json"))
)
# Lokaler Spend-Ledger (Source of Truth für den Batch-API-Verbrauch).
SPEND_DIR = lib.STATE_DIR / "batch"
SPEND_LEDGER = SPEND_DIR / "spend.jsonl"

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_CHF_PER_USD = 0.88


def _load_config() -> dict:
    """Batch-Budget-Konfig lesen (best-effort; leere/kaputte Datei → sichere Defaults)."""
    try:
        raw = json.loads(BUDGET_FILE.read_text())
        if isinstance(raw, dict):
            return raw
        logger.warning("batch_gate: %s enthält kein Objekt -> Defaults", BUDGET_FILE)
    except FileNotFoundError:
        logger.debug("batch_gate: %s existiert nicht -> Defaults", BUDGET_FILE)
    except Exception as e:
        logger.warning("batch_gate: %s nicht lesbar (%s) -> Defaults", BUDGET_FILE, e)
    return {}


def chf_per_usd(cfg: dict | None = None) -> float:
    cfg = cfg if cfg is not None else _load_config()
    try:
        v = float(cfg.get("chf_per_usd", DEFAULT_CHF_PER_USD))
        return v if v > 0 else DEFAULT_CHF_PER_USD
    except (TypeError, ValueError):
        return DEFAULT_CHF_PER_USD


def group_config(category: str, cfg: dict | None = None) -> dict:
    """Effektive Limit-Konfig einer Gruppe: eigener Eintrag, sonst `default`.

    Rückgabe normalisiert: {limit_usd|None, limit_tokens|None, window, model, raw}.
    Ein CHF-Limit wird in USD umgerechnet (der Ledger trackt in USD)."""
    cfg = cfg if cfg is not None else _load_config()
    cats = cfg.get("categories") or {}
    entry = cats.get(category) or cfg.get("default") or {}
    rate = chf_per_usd(cfg)

    limit_usd = None
    limit_tokens = None
    if entry.get("limit_chf") is not None:
        try:
            limit_usd = float(entry["limit_chf"]) / rate
        except (TypeError, ValueError, ZeroDivisionError):
            limit_usd = None
    if entry.get("limit_tokens") is not None:
        try:
            limit_tokens = int(entry["limit_tokens"])
        except (TypeError, ValueError):
            limit_tokens = None

    window = entry.get("window") or "day"
    if window not in ("day", "week"):
        window = "day"
    model = entry.get("model") or cfg.get("default_model") or DEFAULT_MODEL
    return {"limit_usd": limit_usd, "limit_tokens": limit_tokens,
            "window": window, "model": model, "raw": entry}


def _window_key(ts_iso: str, window: str) -> str:
    """Fenster-Schlüssel eines Ledger-Zeitstempels (UTC) in Lokalzeit."""
    try:
        dt = datetime.fromisoformat(ts_iso).astimezone()
    except Exception:
        return ""
    if window == "week":
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    return dt.strftime("%Y-%m-%d")


def _current_key(window: str) -> str:
    dt = datetime.now(timezone.utc).astimezone()
    if window == "week":
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    return dt.strftime("%Y-%m-%d")


def spend_in_window(category: str, window: str) -> dict:
    """Summiert usd + Tokens einer Gruppe im aktuellen Fenster aus dem Ledger."""
    cur = _current_key(window)
    usd, tok, n = 0.0, 0, 0
    if not SPEND_LEDGER.exists():
        return {"usd": 0.0, "tokens": 0, "requests": 0}
    try:
        for line in SPEND_LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("category") != category:
                continue
            if _window_key(e.get("ts", ""), window) != cur:
                continue
            usd += float(e.get("usd", 0) or 0)
            tok += int(e.get("in_tok", 0) or 0) + int(e.get("out_tok", 0) or 0)
            n += 1
    except Exception as e:
        logger.warning("batch_gate: Ledger nicht lesbar (%s) — Spend als 0 angenommen", e)
    return {"usd": usd, "tokens": tok, "requests": n}


def budget_for(category: str, cfg: dict | None = None) -> dict:
    """Vollständiger Budgetstand einer Gruppe: Limit + bisheriger Verbrauch + Restkopf.

    Genau das, was batch.py beim Submit braucht (es rechnet die Reservierungen dann
    selbst hoch, damit ein einzelner Batch das Limit nicht überschiesst)."""
    cfg = cfg if cfg is not None else _load_config()
    gc = group_config(category, cfg)
    spent = spend_in_window(category, gc["window"])
    rate = chf_per_usd(cfg)
    remaining_usd = None
    if gc["limit_usd"] is not None:
        remaining_usd = max(0.0, gc["limit_usd"] - spent["usd"])
    remaining_tokens = None
    if gc["limit_tokens"] is not None:
        remaining_tokens = max(0, gc["limit_tokens"] - spent["tokens"])
    return {
        "category": category,
        "window": gc["window"],
        "model": gc["model"],
        "limit_usd": gc["limit_usd"],
        "limit_tokens": gc["limit_tokens"],
        "spent_usd": round(spent["usd"], 6),
        "spent_chf": round(spent["usd"] * rate, 4),
        "spent_tokens": spent["tokens"],
        "requests": spent["requests"],
        "remaining_usd": None if remaining_usd is None else round(remaining_usd, 6),
        "remaining_tokens": remaining_tokens,
        "chf_per_usd": rate,
    }


def has_room(budget: dict, add_usd: float, add_tokens: int) -> tuple[bool, str]:
    """Passt ein zusätzlicher Aufwand (add_usd/add_tokens) noch ins Gruppen-Budget?

    `budget` = Rückgabe von budget_for(), plus die in DIESEM Tick bereits reservierten
    Beträge, die der Aufrufer selbst dazurechnet (siehe batch.py). Konservativ: fehlt
    jedes Limit, gilt die Gruppe als NICHT freigegeben (kein Limit gesetzt = kein Batch)."""
    lim_usd = budget.get("limit_usd")
    lim_tok = budget.get("limit_tokens")
    if lim_usd is None and lim_tok is None:
        return False, f"kein Limit für Gruppe '{budget.get('category')}' gesetzt — übersprungen"
    if lim_usd is not None:
        if budget["spent_usd"] + add_usd > lim_usd:
            return False, (f"CHF-Limit erreicht: {budget['spent_chf']:.2f}+ von "
                           f"{lim_usd * budget['chf_per_usd']:.2f} CHF im {budget['window']}")
    if lim_tok is not None:
        if budget["spent_tokens"] + add_tokens > lim_tok:
            return False, (f"Token-Limit erreicht: {budget['spent_tokens']:,}+ von "
                           f"{lim_tok:,} im {budget['window']}")
    return True, "Kopf frei"


def allowed(category: str, add_usd: float = 0.0, add_tokens: int = 0) -> tuple[bool, str]:
    """Convenience-One-Shot: darf die Gruppe JETZT einen Vorschlag im geschätzten
    Aufwand (add_usd/add_tokens) bekommen? Für den Mehrkarten-Submit rechnet batch.py
    die laufenden Reservierungen selbst hoch (budget_for + has_room)."""
    return has_room(budget_for(category), add_usd, add_tokens)


def record(category: str, board: str, card: str, model: str,
           in_tok: int, out_tok: int, usd: float) -> None:
    """Einen fertiggestellten Request in den Ledger schreiben (best-effort)."""
    try:
        SPEND_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"ts": lib.now_iso(), "category": category, "board": board, "card": card,
                 "model": model, "in_tok": int(in_tok), "out_tok": int(out_tok),
                 "usd": round(float(usd), 6)}
        with SPEND_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("batch_gate: Spend-Ledger schreiben fehlgeschlagen (%s): %s", card, e)


def status() -> dict:
    """Übersicht je konfigurierter Gruppe — für /automat.html und `python3 batch_gate.py`."""
    cfg = _load_config()
    cats = list((cfg.get("categories") or {}).keys())
    if "default" in cfg and not cats:
        cats = []
    return {
        "file": str(BUDGET_FILE),
        "ledger": str(SPEND_LEDGER),
        "chf_per_usd": chf_per_usd(cfg),
        "groups": {c: budget_for(c, cfg) for c in cats},
    }


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")
    print(json.dumps(status(), ensure_ascii=False, indent=2))

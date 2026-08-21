"""Usage ingest: one-shot run records from apps into the central loop_runs.db.

Backend for POST /api/usage (app/api/usage.py). Apps that do not run as host
scripts (containers, satellites) report their runs/consumption here instead of
calling ~/bin/loop_logger.py directly. The insert logic itself lives in
loop_logger (single write path, plan cheerful-mapping-unicorn.md) — loaded via
importlib from ~/bin because it is a standalone stdlib-only script outside the
dashboard package (same no-cross-import reasoning as jobs/cost_db_sync.py).

Double-count rule: apps whose Ollama calls already go through the :11435 proxy
must NOT also report tokens here — report the run (outcome/duration) without
token fields, or skip entirely if only token stats are wanted.
"""
import importlib.util
import logging
from pathlib import Path

log = logging.getLogger("dashboard.services.usage")

_LOOP_LOGGER_PATH = Path.home() / "bin" / "loop_logger.py"
_loop_logger = None

ALLOWED_FIELDS = {"loop", "trigger", "outcome", "project", "model", "duration_s",
                  "input_tokens", "output_tokens", "cost_usd", "detail"}


def _get_loop_logger():
    global _loop_logger
    if _loop_logger is None:
        spec = importlib.util.spec_from_file_location("loop_logger", _LOOP_LOGGER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _loop_logger = mod
    return _loop_logger


def record(body: dict) -> dict:
    """Validate and store one run record. Raises ValueError on bad input."""
    if not isinstance(body, dict):
        raise ValueError("Body muss ein JSON-Objekt sein")
    unknown = set(body) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unbekannte Felder: {sorted(unknown)}")
    loop = body.get("loop")
    if not loop or not isinstance(loop, str):
        raise ValueError("Feld 'loop' (string) ist Pflicht")
    trigger = body.get("trigger") or "manual"
    outcome = body.get("outcome") or "ok"

    def _num(key):
        v = body.get(key)
        if v is None:
            return None
        try:
            return float(v) if key in ("duration_s", "cost_usd") else int(v)
        except (TypeError, ValueError):
            raise ValueError(f"Feld '{key}' muss eine Zahl sein")

    ll = _get_loop_logger()
    run_id = ll.log_run(
        loop, trigger, outcome,
        project=body.get("project", ll._UNSET),
        model=body.get("model"),
        duration_s=_num("duration_s"),
        input_tokens=_num("input_tokens"),
        output_tokens=_num("output_tokens"),
        cost_usd=_num("cost_usd"),
        detail=body.get("detail"),
    )
    if not run_id:
        raise RuntimeError("loop_logger.log_run lieferte keine run_id")
    log.info("usage ingest: loop=%s outcome=%s run_id=%s", loop, outcome, run_id)
    return {"run_id": run_id}

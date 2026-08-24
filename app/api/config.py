"""API-Router: Config-/Kosten-Endpoints (Migrations-Welle 1, alle read-only).

Routen: /board-templates, /categories, /statuses, /api/models, /api/ai-config,
        /claude-cost, /ollama-usage, /api/client-config

/config (GET+POST) ist am 2026-08-07 entfallen — die Routen bedienten ausschliesslich
die LAN-Scan-Konfiguration, die mit dem Scan nach `shelly-scanner` gewandert ist
(dort: /api/lan/config).
"""
import logging
import os

from fastapi import APIRouter, HTTPException

from app.services import budget_service, config_service, cost_service

log = logging.getLogger("dashboard.api.config")
router = APIRouter(tags=["config"])


@router.get("/board-templates")
def get_board_templates():
    try:
        return config_service.board_templates()
    except Exception as e:
        log.error("Fehler beim Laden der Templates: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/categories")
def get_categories():
    return config_service.categories()


@router.get("/statuses")
def get_statuses():
    return config_service.statuses()


@router.get("/api/models")
def get_models():
    return config_service.ollama_models()


@router.get("/api/ai-config")
def get_ai_config():
    return config_service.ai_config()


@router.post("/board-templates")
def post_board_templates(body: dict):
    try:
        count = config_service.save_templates(body)
        return {"status": "ok", "count": count}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Speichern der Templates: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/api/ai-config")
def post_ai_config(body: dict):
    try:
        return {"status": "ok", "config": config_service.save_ai_config(body or {})}
    except Exception as e:
        log.error("Fehler beim Speichern der AI-Config: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/api/budget")
def get_budget():
    """F2.3: Kompletter Budget-Status (check_allowance + usage_week)."""
    try:
        allowance = budget_service.check_allowance()
        usage = budget_service.usage_week()
        cfg = config_service.ai_config()
        result = {
            "week": usage["week"],
            "tokens_used": usage["tokens_used"],
            "by_source": usage["by_source"],
            "by_day": usage["by_day"],
            "week_limit": int(cfg.get("budget_week_tokens", 0) or 0),
            "week_pct": allowance["week_pct"],
            "window_pct": allowance["window_pct"],
            "day_allowance_tokens": allowance["day_allowance_tokens"],
            "today_used": allowance["today_used"],
            "window": allowance["window"],
            "allowed": allowance["allowed"],
            "enforce": bool(cfg.get("budget_enforce", True)),
            "reason": allowance["reason"],
            # source der Steuergrösse week_pct/window_pct ("usage" = echte InfluxDB-
            # Auslastung, "estimate" = Schätzung) — tokens_used bleibt IMMER der
            # lokale Log-Scan (usage_week), die beiden können divergieren (card_544ceaa5).
            "source": allowance["source"],
        }
        log.debug("[Budget-API] %s", result["reason"])
        return result
    except Exception as e:
        log.error("Fehler bei /api/budget: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/claude-cost")
def get_claude_cost():
    return cost_service.claude_cost_summary()


@router.get("/ollama-usage")
def get_ollama_usage():
    return cost_service.ollama_usage_summary()


@router.get("/api/client-config")
def get_client_config():
    """Liefert deployment-spezifische Konfiguration ans Frontend (kein Secret)."""
    return {
        "domain": os.environ.get("DASHBOARD_DOMAIN", ""),
        "dashboard_url": os.environ.get("DASHBOARD_URL", ""),
    }

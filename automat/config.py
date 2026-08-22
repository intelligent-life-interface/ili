#!/usr/bin/env python3
"""Konfigsystem: Wochenlimit-Budgetierung, Tagesreserven, Drossel-Limits.

Lädt ai_config.json und berechnet daraus das tägliche Token-Limit mit Reserve.
Die Logik folgt dem Wochenbudget-Aufteilungsprinzip: Woche durch 8 = Tagesbasis,
sodass bei normalem Verbrauch ca. 1 Tag Reserve für Manager-Projekte bleibt.
"""
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("automat.config")

# ILI_DASHBOARD_DIR: set by the ili release container (default = home stack layout)
AI_CONFIG_FILE = Path(os.getenv("ILI_DASHBOARD_DIR", str(Path.home() / "containers/dashboard"))) / "ai_config.json"


def load_ai_config() -> dict:
    """Liest ai_config.json, Fallback auf sichere Defaults."""
    try:
        return json.loads(AI_CONFIG_FILE.read_text())
    except FileNotFoundError:
        logger.warning("ai_config.json nicht gefunden -> Defaults")
        return {}
    except Exception as e:
        logger.error("ai_config.json nicht lesbar (%s) -> Defaults", e)
        return {}


def calculate_daily_limit(budget_week_tokens: int, divisions: int = 8) -> int:
    """Berechnet das tägliche Token-Limit aus Wochenbudget.

    Prinzip: Woche / Divisionen = Tagesbasis.
    Mit divisions=8: auch bei 7 Tagen normalen Verbrauch bleibt 1 Tag Reserve.
    """
    if budget_week_tokens <= 0:
        logger.warning("budget_week_tokens=%s ungültig", budget_week_tokens)
        return 0
    daily = budget_week_tokens // divisions
    logger.debug("daily_limit: %d Wochen-Token / %d Divisionen = %d pro Tag",
                 budget_week_tokens, divisions, daily)
    return daily


def get_config() -> dict:
    """Liefert die komplette Konfiguration mit berechneten Werten."""
    ai_cfg = load_ai_config()

    budget_week = ai_cfg.get("budget_week_tokens", 100_000_000)
    divisions = ai_cfg.get("budget_week_divisions", 8)
    daily_max = ai_cfg.get("budget_daily_max_tokens")

    # Wenn daily_max nicht explizit gesetzt, aus Wochenbudget berechnen
    if daily_max is None:
        daily_max = calculate_daily_limit(budget_week, divisions)

    return {
        "budget_week_tokens": budget_week,
        "budget_week_divisions": divisions,
        "budget_daily_max_tokens": daily_max,
        "budget_windows": ai_cfg.get("budget_windows", [
            {"from": 10, "to": 22, "max_pct": 50},
            {"from": 22, "to": 10, "max_pct": 80},
        ]),
        "budget_enforce": ai_cfg.get("budget_enforce", True),
        "budget_reserve_days": ai_cfg.get("budget_reserve_days", 1),
    }


def describe() -> dict:
    """Für Debug/Logging: alle Konfigrationswerte."""
    cfg = get_config()
    return {
        "source": str(AI_CONFIG_FILE),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "notes": {
            "daily_max": f"aus Wochenbudget {cfg['budget_week_tokens']} / {cfg['budget_week_divisions']} berechnet"
                if cfg["budget_daily_max_tokens"] is not None else "explizit in ai_config.json gesetzt",
            "reserve_concept": f"Mit divisions={cfg['budget_week_divisions']} bleiben bei normalem Verbrauch "
                f"ca. {cfg['budget_reserve_days']} Tag Reserve für User-Projekte",
        }
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    import sys
    print(json.dumps(describe(), indent=2, ensure_ascii=False), file=sys.stdout)

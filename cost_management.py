"""\ncost_management.py — Kostenverwaltung-Funktionen\nAutogeneriert von script_splitter.py\n"""
import json
import logging
from datetime import datetime
from constants import CLAUDE_COST_CHECKPOINT, CLAUDE_BLOCK_FILE, DASHBOARD_DIR, _DAILY_BLOCK_CHF

log = logging.getLogger("dashboard.cost_management")
from app.storage.atomic_write import write_json_atomic


def _daily_cost_usd(date: str) -> float:
    """Tageskosten (USD) für ein Datum — aus der EINEN Aggregation claude_cost_summary().

    opt_altlasten_0806: früher las diese Funktion nur CLAUDE_COST_FILE (Dashboard-Log) und
    IGNORIERTE die CLI-Session-Kosten — je nach Aufrufer kamen so verschiedene Tageskosten
    heraus (claude_cost_summary() zählt beide). Jetzt EINE Quelle: das `by_day`-Aggregat.
    Lazy import gegen Zirkular-Import (cost_service → logging_utils → cost_management)."""
    try:
        from app.services.cost_service import claude_cost_summary
        return float(claude_cost_summary().get("by_day", {}).get(date, 0.0))
    except Exception as e:
        log.error(f"[Kosten] _daily_cost_usd({date}) fehlgeschlagen: {e}")
        return 0.0




def _maybe_trigger_cost_analysis(date: str, daily_chf: float):
    """Erstellt eine Warn-Karte wenn die 5-CHF-Schwelle überschritten wird (einmal pro Tag)."""
    try:
        checkpoint = {}
        if CLAUDE_COST_CHECKPOINT.exists():
            checkpoint = json.loads(CLAUDE_COST_CHECKPOINT.read_text())
        if checkpoint.get("last_warn_date") == date:
            return  # Heute schon gewarnt
        checkpoint["last_warn_date"] = date
        checkpoint["last_warn_chf"]  = round(daily_chf, 2)
        write_json_atomic(CLAUDE_COST_CHECKPOINT, checkpoint)
        # Karte asynchron im Hintergrund erstellen (blockiert nicht den Request)
        import threading
        threading.Thread(target=_create_cost_warn_card, args=(date, daily_chf), daemon=True).start()
    except Exception as e:
        log.error(f"Cost-Analysis-Trigger fehlgeschlagen: {e}")




def _create_cost_warn_card(date: str, daily_chf: float):
    """Erstellt eine Kanban-Warn-Karte via Ollama-Zusammenfassung (läuft im Hintergrund)."""
    import subprocess
    try:
        subprocess.run(
            ["python3", str(DASHBOARD_DIR / "ki_cost_monitor.py"),
             "--date", date, "--chf", str(round(daily_chf, 2))],
            timeout=180,
        )
        log.info(f"[Kosten] Analyse-Karte erstellt für {date}")
    except Exception as e:
        log.error(f"[Kosten] Analyse-Karte fehlgeschlagen: {e}")



def _is_claude_blocked() -> tuple[bool, str]:
    # 1) Bestehende Tagessperre (CHF-Limit)
    if CLAUDE_BLOCK_FILE.exists():
        try:
            data = json.loads(CLAUDE_BLOCK_FILE.read_text())
            blocked_date = data.get("blocked_date", "")
            today = datetime.now().strftime("%Y-%m-%d")
            if blocked_date == today:
                chf = data.get("daily_chf", 0)
                log.debug(f"[Budget] Claude blockiert via CHF-Tageslimit ({chf:.2f} CHF)")
                return True, f"Tageslimit von {_DAILY_BLOCK_CHF:.0f} CHF erreicht ({chf:.2f} CHF heute). Claude bis Mitternacht gesperrt."
        except Exception:
            pass

    # 2) F2 Token-Budget-Fenster (lazy import — Zirkular-Import-Gefahr app.services ↔ cost_management)
    try:
        from app.services import budget_service
        allowance = budget_service.check_allowance()
        if not allowance.get("allowed", True):
            log.warning(f"[Budget] Claude blockiert via Token-Budget: {allowance.get('reason', '')}")
            return True, "Budget-Fenster erschöpft: " + allowance.get("reason", "")
        log.debug(f"[Budget] Token-Budget OK: {allowance.get('reason', '')}")
    except Exception as e:
        # Budget-Check darf Claude nie durch eigene Fehler sperren (fail-open)
        log.error(f"[Budget] check_allowance fehlgeschlagen (fail-open): {e}")

    return False, ""


def _set_claude_block(date: str, daily_chf: float):
    data = {"blocked_date": date, "daily_chf": round(daily_chf, 2), "set_at": datetime.now().isoformat()}
    write_json_atomic(CLAUDE_BLOCK_FILE, data)
    log.warning(f"[Kosten] Claude GESPERRT für {date}: {daily_chf:.2f} CHF überschreitet Limit von {_DAILY_BLOCK_CHF} CHF")

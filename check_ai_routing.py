#!/usr/bin/env python3
"""
check_ai_routing.py — Tägliche Prüfung ob Claude API unbeabsichtigt benutzt wird.

Ablauf:
  1. Schickt Test-Chat an dashboard-api (chat_model laut ai_config)
  2. Prüft ob danach ein neuer Claude-Cost-Log-Eintrag erscheint
  3. Erstellt Kanban-Karte auf "dashboard-funktion" wenn Claude benutzt wurde

Cron: täglich 08:00
"""
import json
import time
import urllib.request
import urllib.error
from datetime import datetime

from constants import CLAUDE_COST_FILE as COST_LOG, BOARDS_DIR, DASHBOARD_URL
from app.storage.board_repository import BoardRepository

# Persistenz NUR über das Repository (fcntl-Lock + tmp+os.replace) —
# direktes write_text() auf boards/*.json ist Lost-Update-Risiko.
_boards = BoardRepository(boards_dir=BOARDS_DIR)

TRIGGER_URL  = DASHBOARD_URL
ALERT_BOARD  = "dashboard-funktion"

RED   = "\033[31m"
GREEN = "\033[32m"
YELLOW= "\033[33m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def _last_claude_ts() -> str:
    if not COST_LOG.exists():
        return ""
    lines = [l for l in COST_LOG.read_text().splitlines() if l.strip()]
    if not lines:
        return ""
    try:
        return json.loads(lines[-1]).get("ts", "")
    except Exception:
        return ""


def _get_chat_model() -> str:
    try:
        req = urllib.request.Request(f"{TRIGGER_URL}/api/ai-config", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            cfg = json.loads(r.read())
        return cfg.get("chat_model", "gemma3:12b")
    except Exception:
        return "gemma3:12b"


def _send_test_chat(model: str) -> bool:
    """Sendet Test-Nachricht, gibt True wenn Antwort erhalten."""
    try:
        body = json.dumps({
            "model": model,
            "board_id": "dashboard",
            "messages": [{"role": "user", "content": "Routing-Test: antworte nur mit OK"}],
        }).encode()
        req = urllib.request.Request(
            f"{TRIGGER_URL}/chat?id=dashboard",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
        text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"  Antwort: {text[:80]!r}")
        return True
    except Exception as e:
        print(f"  Chat-Fehler: {e}")
        return False


def _create_alert_card(model: str, new_claude_ts: str):
    """Erstellt Warn-Karte auf dashboard-funktion Board (Read-Modify-Write unter Lock)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    card = {
        "title": f"⚠️ Claude API statt Ollama [{ts}]",
        "desc": (
            f"check_ai_routing.py hat erkannt dass Chat-Modell '{model}' "
            f"eine Claude-API-Anfrage ausgelöst hat (Log-Eintrag: {new_claude_ts[:19]}).\n\n"
            f"Bitte prüfen: app/api/chat.py Routing-Logik und ai_config.json."
        ),
        "label": "#fc8181",
    }
    placed = {"col": None}

    def _insert(board: dict):
        columns = board.get("columns", [])
        col = next((c for c in columns if c.get("id") in ("backlog", "in-arbeit", "todo")), None)
        if col is None:
            col = columns[0] if columns else None
        if col is None:
            raise ValueError(f"Board '{ALERT_BOARD}' hat keine Spalten")
        col.setdefault("cards", []).insert(0, card)
        placed["col"] = col.get("id")

    try:
        _boards.update(ALERT_BOARD, _insert, sync_claude_md=False)
    except FileNotFoundError:
        print(f"  Board {ALERT_BOARD} nicht gefunden — kein Alert")
        return
    except Exception as e:
        print(f"  Alert-Karte konnte nicht erstellt werden: {e}")
        return
    print(f"  {RED}Alert-Karte auf '{ALERT_BOARD}' erstellt (Spalte '{placed['col']}'){RESET}")


def run_check():
    print(f"\n{BOLD}=== AI Routing Check {datetime.now().strftime('%Y-%m-%d %H:%M')} ==={RESET}\n")

    model = _get_chat_model()
    print(f"Chat-Modell laut ai_config: {YELLOW}{model}{RESET}")
    is_claude = model.lower().startswith("claude")
    if is_claude:
        print(f"  {RED}⚠️  ai_config.chat_model ist bereits Claude — das ist unerwünscht!{RESET}")

    before_ts = _last_claude_ts()
    print(f"Letzter Claude-Call vor Test: {before_ts[:19] or 'keiner'}")

    print(f"\nSende Test-Chat mit Modell '{model}'…")
    ok = _send_test_chat(model)
    if not ok:
        print(f"  {YELLOW}Test-Chat fehlgeschlagen — Prüfung abgebrochen{RESET}")
        return

    time.sleep(2)
    after_ts = _last_claude_ts()
    new_call = after_ts != before_ts

    if new_call or is_claude:
        print(f"\n{RED}{BOLD}FEHLER: Claude wurde benutzt!{RESET}")
        print(f"  Neuer Claude-Log-Eintrag: {after_ts[:19]}")
        _create_alert_card(model, after_ts)
    else:
        print(f"\n{GREEN}{BOLD}✓ OK — kein Claude-Call. Routing korrekt.{RESET}")
        print(f"  Modell '{model}' hat Anfrage lokal verarbeitet.")

    print()


if __name__ == "__main__":
    run_check()

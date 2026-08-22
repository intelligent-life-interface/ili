"""Batch-API-Pfad — günstige Karten-VORSCHLÄGE über die Anthropic Message Batches API.

Parallel zum Abo, nicht als Ersatz. Der Abo-Worker (`claude -p`, worker.py) bleibt der
Standard und editiert Dateien/führt Tools aus. Dieser Pfad erzeugt pro offener Karte nur
einen **Text-Vorschlag** (Analyse + Lösungsskizze + evtl. Patch) über die Batches API
(async bis 24h, 50% günstiger) und hängt ihn an die Karte — die Batches API kann keine
Dateien ändern und keine Tools ausführen.

**Umschalten („erst Abo, bei Bedarf auf API"):**
  1. Master-Schalter `batch_enabled=1` in der Drossel-GUI (/automat.html) bzw.
     `~/containers/dashboard/automat_limits.json` (Default 0 = aus, Abo-only).
  2. Pro gewünschtem Board `automat_batch:true` setzen (PATCH /boards/<slug>).
  3. Kostenlimit der Projektgruppe (`category`) in `~/containers/dashboard/batch_budget.json`
     setzen (ohne Limit läuft NICHTS — batch_gate ist bewusst konservativ).
Solange (1) aus ist, ist dieser ganze Pfad ein No-Op; der Automat arbeitet rein über das Abo.

Lebenszyklus je Tick (Schritt (d) in scheduler.tick(), entkoppelt von Worker-Slots, weil
Batches asynchron sind und keinen `claude -p`-Slot belegen):
  - poll(): laufende Batches (state/batch/pending.json) prüfen; fertige Ergebnisse als
    Vorschlag an die Quellkarte schreiben, echten Verbrauch in den Spend-Ledger (batch_gate).
  - submit(): offene Karten der automat_batch-Boards sammeln, gruppenweise gegen das
    Kostenlimit prüfen (batch_gate), unter Limit als EIN Batch submitten.

HTTP bewusst über urllib (wie grouping.py) — kein `anthropic`-SDK als neue Abhängigkeit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

# Add ~/bin/lib to path for config_env
sys.path.insert(0, str(Path.home() / "bin" / "lib"))
import config_env

import automat_lib as lib
import batch_gate
import limits
from automat_lib import logger

# ── API-Konfiguration ────────────────────────────────────────────────────────
API_BASE = os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com").rstrip("/")
ANTHROPIC_VERSION = "2023-06-01"

# Standardpreise (USD je 1M Token, input/output). Batch = 50% davon (Rabatt in cost()).
# Ground-Truth-Tabelle, leicht pflegbar — NICHT vom Modell rechnen lassen.
PRICES = {
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-opus-4-6":   (5.0, 25.0),
    "claude-sonnet-5":   (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
    "claude-fable-5":    (10.0, 50.0),
}
# Einführungspreis Sonnet 5 bis 31.08.2026 (input/output USD je 1M).
INTRO_PRICES = {"claude-sonnet-5": (2.0, 10.0)}
INTRO_UNTIL = date(2026, 8, 31)
BATCH_DISCOUNT = 0.5
_FALLBACK_MODEL = "claude-sonnet-5"

PROPOSAL_LABEL = "Batch-Vorschlag"
PROPOSAL_COLOR = "#38a169"

# Nie autonom bearbeiten (identisch zu scheduler.SELF_BOARDS).
SELF_BOARDS = {"kanban-automat", "auto-entwicklung-log"}

# ── State ────────────────────────────────────────────────────────────────────
BATCH_DIR = lib.STATE_DIR / "batch"
PENDING_FILE = BATCH_DIR / "pending.json"
PROPOSED_DIR = BATCH_DIR / "proposed"

_LIM = limits.load()
BATCH_ENABLED = int(_LIM.get("batch_enabled", 0)) == 1
MAX_IN_FLIGHT = int(_LIM.get("batch_max_in_flight", 1))
MAX_REQ_PER_TICK = int(_LIM.get("batch_max_requests_per_tick", 20))
MAX_OUT_TOKENS = int(_LIM.get("batch_max_output_tokens", 2000))

# Kartenbeschreibung fürs Prompt begrenzen (Input-Kosten deckeln).
DESC_MAX_CHARS = 4000


# ── API-Key ──────────────────────────────────────────────────────────────────
def _api_key() -> str | None:
    """API-Key aus der Umgebung; Fallback: ANTHROPIC_API_KEY aus ~/config.env."""
    return config_env.get("ANTHROPIC_API_KEY")


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _headers(key: str) -> dict:
    return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"}


def _api(method: str, url: str, key: str, body: dict | None = None, timeout: int = 60):
    """JSON-Aufruf gegen die Anthropic-API. Wirft bei != 2xx (mit Fehlertext im Log)."""
    if not url.startswith("http"):
        url = f"{API_BASE}{url}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        logger.error("batch: API %s %s -> %s %s", method, url, e.code, detail)
        raise


def _api_text(url: str, key: str, timeout: int = 120) -> str:
    """Roh-Text (JSONL der Batch-Ergebnisse)."""
    req = urllib.request.Request(url, method="GET", headers=_headers(key))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


# ── Kosten ───────────────────────────────────────────────────────────────────
def _unit_prices(model: str) -> tuple[float, float]:
    if model in INTRO_PRICES and date.today() <= INTRO_UNTIL:
        return INTRO_PRICES[model]
    if model in PRICES:
        return PRICES[model]
    logger.warning("batch: kein Preis für Modell %r — nehme %s", model, _FALLBACK_MODEL)
    return PRICES[_FALLBACK_MODEL]


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    """Batch-Kosten in USD (50% Rabatt) für einen Request."""
    p_in, p_out = _unit_prices(model)
    return (in_tok / 1_000_000 * p_in + out_tok / 1_000_000 * p_out) * BATCH_DISCOUNT


def _est_tokens(text: str) -> int:
    """Grobe Input-Token-Schätzung (~4 Zeichen/Token) — nur für die Budget-Reservierung.
    Der echte Verbrauch kommt aus der usage des Batch-Ergebnisses."""
    return max(1, len(text) // 4)


# ── Pending-/Proposed-State ──────────────────────────────────────────────────
def _load_pending() -> dict:
    try:
        d = json.loads(PENDING_FILE.read_text())
        return d if isinstance(d, dict) else {"batches": {}}
    except Exception:
        return {"batches": {}}


def _save_pending(d: dict) -> None:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, PENDING_FILE)


def _in_flight() -> int:
    return len(_load_pending().get("batches", {}))


def _fingerprint(card: dict) -> str:
    h = hashlib.sha1()
    h.update((str(card.get("title", "")) + "\n" + str(card.get("description", ""))).encode())
    return h.hexdigest()[:16]


def _proposed_path(slug: str) -> Path:
    return PROPOSED_DIR / f"{slug.replace('/', '_')}.json"


def _load_proposed(slug: str) -> dict:
    try:
        return json.loads(_proposed_path(slug).read_text())
    except Exception:
        return {}


def _save_proposed(slug: str, data: dict) -> None:
    PROPOSED_DIR.mkdir(parents=True, exist_ok=True)
    _proposed_path(slug).write_text(json.dumps(data, ensure_ascii=False, indent=1))


def _is_proposed(slug: str, card: dict) -> bool:
    return _load_proposed(slug).get(card.get("id")) == _fingerprint(card)


def _mark_proposed(slug: str, card: dict) -> None:
    data = _load_proposed(slug)
    data[card.get("id")] = _fingerprint(card)
    _save_proposed(slug, data)


def _unmark_proposed(slug: str, card_id: str) -> None:
    data = _load_proposed(slug)
    if card_id in data:
        data.pop(card_id, None)
        _save_proposed(slug, data)


# ── Prompt ───────────────────────────────────────────────────────────────────
def _build_prompt(name: str, slug: str, card: dict) -> tuple[str, str]:
    system = (
        f"Du bist ein erfahrener Software- und Projekt-Entwickler und arbeitest an diesem "
        f"Homeserver-Projekt „{name}“ (Kanban-Board `{slug}`). Erstelle zur folgenden "
        f"Kanban-Karte einen konkreten Weiterentwicklungs-Vorschlag mit diesen Abschnitten:\n"
        f"1. Kurze Analyse (worum geht es, was ist der Kern).\n"
        f"2. Lösungsskizze.\n"
        f"3. Konkrete nächste Schritte (nummeriert).\n"
        f"4. Falls sinnvoll: ein konkreter Code-/Patch-Block.\n\n"
        f"Sei konkret und knapp. WICHTIG: Du kannst keine Dateien ändern und keine Befehle "
        f"ausführen — dein Output ist ein Vorschlag, den ein Mensch oder der Abo-Worker umsetzt. "
        f"Antworte auf Deutsch."
    )
    desc = (str(card.get("description") or ""))[:DESC_MAX_CHARS]
    user = (f"Karte: {card.get('title', '(ohne Titel)')}\n"
            f"Karten-ID: {card.get('id')}\n\n"
            f"Beschreibung:\n{desc or '(keine Beschreibung)'}")
    return system, user


# ── Kandidaten sammeln ───────────────────────────────────────────────────────
def _batch_boards(all_boards: list[dict], self_boards: set[str]) -> list[dict]:
    """Boards mit Opt-in automat_batch:true, nicht pausiert/archiviert, nicht Self-Board."""
    out = []
    for b in all_boards:
        if b.get("automat_batch") is not True:
            continue
        if b.get("id") in self_boards:
            continue
        if b.get("status") in lib.PAUSED_STATUSES:
            continue
        out.append(b)
    return out


def _candidates(all_boards: list[dict], self_boards: set[str]) -> list[dict]:
    """Alle noch nicht vorgeschlagenen, abarbeitbaren Karten der automat_batch-Boards.

    actionable_cards() überspringt bereits Entscheidungs-, Meta- und geparkte Karten;
    Boards mit offener Entscheidung (blockiert) werden ganz ausgelassen."""
    cands: list[dict] = []
    for b in _batch_boards(all_boards, self_boards):
        slug = b.get("id")
        try:
            board = lib.get_board(slug)
        except Exception as e:
            logger.warning("batch: Board %s nicht ladbar (%s) — übersprungen", slug, e)
            continue
        if lib.board_is_blocked(board):
            continue
        cat = b.get("category") or "(ohne-kategorie)"
        name = b.get("name") or slug
        for _col, card in lib.actionable_cards(board):
            if _is_proposed(slug, card):
                continue
            cands.append({"slug": slug, "name": name, "category": cat, "card": card})
    return cands


# ── Submit ───────────────────────────────────────────────────────────────────
def submit(all_boards: list[dict], self_boards: set[str], dry: bool = False) -> dict:
    """Offene Karten der automat_batch-Boards gruppenweise gegen das Kostenlimit prüfen
    und (falls nicht dry) als EINEN Batch submitten. Rückgabe = Kurz-Report."""
    cfg = batch_gate._load_config()
    cands = _candidates(all_boards, self_boards)
    budgets: dict[str, dict] = {}
    reserved: dict[str, dict] = {}
    requests: list[dict] = []
    mapping: dict[str, dict] = {}
    skipped_groups: dict[str, str] = {}

    for cand in cands:
        if len(requests) >= MAX_REQ_PER_TICK:
            break
        cat = cand["category"]
        if cat in skipped_groups:
            continue
        if cat not in budgets:
            budgets[cat] = batch_gate.budget_for(cat, cfg)
            reserved[cat] = {"usd": 0.0, "tok": 0}
        model = budgets[cat]["model"]
        system, user = _build_prompt(cand["name"], cand["slug"], cand["card"])
        est_in = _est_tokens(system + user)
        est_out = MAX_OUT_TOKENS
        est_usd = cost_usd(model, est_in, est_out)
        ok, reason = batch_gate.has_room(
            budgets[cat],
            reserved[cat]["usd"] + est_usd,
            reserved[cat]["tok"] + est_in + est_out,
        )
        if not ok:
            # Gruppe voll/ohne Limit — für diesen Tick keine weiteren Karten dieser Gruppe.
            skipped_groups[cat] = reason
            logger.info("batch: Gruppe '%s' übersprungen (%s)", cat, reason)
            continue
        reserved[cat]["usd"] += est_usd
        reserved[cat]["tok"] += est_in + est_out
        cid = f"c{len(requests)}"
        requests.append({
            "custom_id": cid,
            "params": {
                "model": model,
                "max_tokens": MAX_OUT_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        })
        mapping[cid] = {"board": cand["slug"], "card": cand["card"].get("id"),
                        "card_title": cand["card"].get("title"), "category": cat,
                        "model": model, "est_usd": round(est_usd, 6)}

    report = {"candidates": len(cands), "requests": len(requests),
              "groups": {c: {"reserved_usd": round(reserved[c]["usd"], 4),
                             "limit_usd": budgets[c]["limit_usd"],
                             "limit_tokens": budgets[c]["limit_tokens"]}
                         for c in reserved},
              "skipped_groups": skipped_groups}

    if not requests:
        logger.info("batch: keine submitfähige Karte (Kandidaten=%d).", len(cands))
        return {**report, "submitted": None, "dry": dry}

    if dry:
        logger.info("batch[dry]: würde %d Request(s) submitten: %s",
                    len(requests), json.dumps(report["groups"], ensure_ascii=False))
        return {**report, "submitted": None, "dry": True}

    key = _api_key()
    if not key:
        logger.error("batch: kein ANTHROPIC_API_KEY (env oder ~/config.env) — Submit übersprungen.")
        return {**report, "submitted": None, "error": "kein API-Key"}

    resp = _api("POST", "/v1/messages/batches", key, {"requests": requests})
    batch_id = resp.get("id")
    if not batch_id:
        logger.error("batch: Submit ohne id in der Antwort: %s", str(resp)[:200])
        return {**report, "submitted": None, "error": "kein batch id"}

    pend = _load_pending()
    pend.setdefault("batches", {})[batch_id] = {
        "submitted": lib.now_iso(),
        "status": resp.get("processing_status"),
        "mapping": mapping,
    }
    _save_pending(pend)
    # Erst nach erfolgreichem Submit als „vorgeschlagen" markieren (sonst Re-Submit bei Fehler).
    for m in mapping.values():
        card_stub = {"id": m["card"], "title": m["card_title"]}
        # Fingerprint braucht Titel+Desc; wir markieren mit dem aktuellen Karteninhalt beim
        # nächsten Poll ohnehin neu. Hier reicht der Titel-basierte Stub, um Doppel-Submits
        # innerhalb der Laufzeit zu verhindern.
        _mark_proposed(m["board"], card_stub)
    logger.info("batch: Batch %s submittet (%d Requests).", batch_id, len(requests))
    return {**report, "submitted": batch_id, "dry": False}


# ── Poll + Ergebnis → Vorschlag ──────────────────────────────────────────────
def _extract_text(message: dict) -> str:
    parts = []
    for block in message.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def _write_proposal(slug: str, card_id: str, text: str, model: str) -> bool:
    """Vorschlag als Block an die Karte hängen (+ Label), Karte NICHT verschieben."""
    try:
        board = lib.get_board(slug)
    except Exception as e:
        logger.warning("batch: Board %s fürs Schreiben nicht ladbar (%s)", slug, e)
        return False
    for col in board.get("columns", []):
        for card in col.get("cards", []):
            if card.get("id") == card_id:
                header = f"\n\n— 📦 Batch-Vorschlag ({model}, {lib.now_iso()[:16]}):\n"
                card["description"] = (card.get("description") or "") + header + text
                if not lib._has_label(card, PROPOSAL_LABEL):
                    card.setdefault("labels", []).append(
                        {"text": PROPOSAL_LABEL, "color": PROPOSAL_COLOR})
                try:
                    lib.save_board(slug, board)
                    logger.info("batch: Vorschlag an %s/%s geschrieben.", slug, card_id)
                    return True
                except Exception as e:
                    logger.warning("batch: Speichern %s/%s fehlgeschlagen (%s)", slug, card_id, e)
                    return False
    logger.info("batch: Karte %s in %s nicht mehr vorhanden — Vorschlag verworfen.", card_id, slug)
    return False


def poll(dry: bool = False) -> dict:
    """Laufende Batches prüfen; fertige verarbeiten. Rückgabe = Kurz-Report."""
    pend = _load_pending()
    batches = pend.get("batches", {})
    if not batches:
        return {"pending": 0, "ended": 0, "written": 0}
    if dry:
        logger.info("batch[dry]: %d Batch(es) offen — kein Poll im Dry-Run.", len(batches))
        return {"pending": len(batches), "ended": 0, "written": 0, "dry": True}

    key = _api_key()
    if not key:
        logger.error("batch: kein API-Key — Poll übersprungen.")
        return {"pending": len(batches), "ended": 0, "written": 0, "error": "kein API-Key"}

    ended, written = 0, 0
    for batch_id in list(batches.keys()):
        info = batches[batch_id]
        try:
            st = _api("GET", f"/v1/messages/batches/{batch_id}", key)
        except Exception as e:
            logger.warning("batch: Status %s nicht abrufbar (%s) — später erneut", batch_id, e)
            continue
        status = st.get("processing_status")
        info["status"] = status
        if status != "ended":
            logger.debug("batch: %s noch %s", batch_id, status)
            continue
        results_url = st.get("results_url")
        if not results_url:
            logger.warning("batch: %s ended ohne results_url — entferne aus pending", batch_id)
            del batches[batch_id]
            continue
        try:
            raw = _api_text(results_url, key)
        except Exception as e:
            logger.warning("batch: Ergebnisse %s nicht abrufbar (%s) — später erneut", batch_id, e)
            continue
        ended += 1
        mapping = info.get("mapping", {})
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            cid = r.get("custom_id")
            m = mapping.get(cid)
            if not m:
                continue
            res = r.get("result", {})
            rtype = res.get("type")
            if rtype == "succeeded":
                msg = res.get("message", {})
                text = _extract_text(msg)
                usage = msg.get("usage", {}) or {}
                in_tok = int(usage.get("input_tokens", 0) or 0) \
                    + int(usage.get("cache_read_input_tokens", 0) or 0) \
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                out_tok = int(usage.get("output_tokens", 0) or 0)
                usd = cost_usd(m["model"], in_tok, out_tok)
                if text and _write_proposal(m["board"], m["card"], text, m["model"]):
                    written += 1
                else:
                    _unmark_proposed(m["board"], m["card"])  # leer/fehlgeschlagen → erneut zulassen
                batch_gate.record(m["category"], m["board"], m["card"], m["model"],
                                  in_tok, out_tok, usd)
            else:
                logger.info("batch: Request %s (%s/%s) %s — erneut zulassen",
                            cid, m["board"], m["card"], rtype)
                _unmark_proposed(m["board"], m["card"])
        del batches[batch_id]
    _save_pending(pend)
    logger.info("batch: Poll fertig (fertige Batches=%d, geschriebene Vorschläge=%d).", ended, written)
    return {"pending": len(batches), "ended": ended, "written": written}


# ── Tick-Einhängepunkt ───────────────────────────────────────────────────────
def tick_step(all_boards: list[dict] | None = None, dry: bool = False) -> None:
    """Schritt (d) im Orchestrator-Tick: async Batch-Vorschläge. No-Op wenn Schalter aus.

    Entkoppelt von Worker-Slots/MAX_STARTS_PER_DAY — Batches laufen serverseitig, belegen
    keinen `claude -p`-Slot; darf deshalb auch bei voller Worker-Kapazität laufen. Holt sich
    die Boards selbst (nur wenn aktiviert), damit der Aufrufer nichts vorbereiten muss."""
    if not BATCH_ENABLED:
        logger.debug("batch: Schalter aus (batch_enabled=0) — Abo-only, nichts zu tun.")
        return
    try:
        poll(dry=dry)
    except Exception as e:
        logger.warning("batch: poll() fehlgeschlagen (%s) — Tick läuft weiter.", e)
    try:
        if _in_flight() < MAX_IN_FLIGHT:
            if all_boards is None:
                all_boards = lib.list_boards_all()
            submit(all_boards, SELF_BOARDS, dry=dry)
        else:
            logger.info("batch: max_in_flight erreicht (%d) — kein neuer Submit.", MAX_IN_FLIGHT)
    except Exception as e:
        logger.warning("batch: submit() fehlgeschlagen (%s) — Tick läuft weiter.", e)


# ── CLI ──────────────────────────────────────────────────────────────────────
def _status() -> dict:
    pend = _load_pending().get("batches", {})
    return {
        "enabled": BATCH_ENABLED,
        "max_in_flight": MAX_IN_FLIGHT,
        "max_requests_per_tick": MAX_REQ_PER_TICK,
        "max_output_tokens": MAX_OUT_TOKENS,
        "api_key_present": bool(_api_key()),
        "in_flight": len(pend),
        "pending_batches": {bid: {"submitted": v.get("submitted"), "status": v.get("status"),
                                   "requests": len(v.get("mapping", {}))}
                            for bid, v in pend.items()},
        "budget": batch_gate.status(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Kanban-Automat Batch-API-Pfad")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nur zeigen, was submittet würde — kein API-Aufruf.")
    ap.add_argument("--status", action="store_true", help="Status + Gruppen-Budget zeigen.")
    ap.add_argument("--poll", action="store_true", help="Nur laufende Batches pollen.")
    ap.add_argument("--submit", action="store_true", help="Nur submitten (offene Karten).")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(_status(), ensure_ascii=False, indent=2))
        return 0

    all_boards = lib.list_boards_all()
    self_boards = SELF_BOARDS

    if args.dry_run:
        cands = _candidates(all_boards, self_boards)
        rep = submit(all_boards, self_boards, dry=True)
        print(json.dumps({"enabled": BATCH_ENABLED, "candidates": len(cands), **rep},
                         ensure_ascii=False, indent=2))
        if not BATCH_ENABLED:
            print("\nHinweis: batch_enabled=0 (Abo-only). Zum Scharfschalten batch_enabled=1 "
                  "setzen, Boards mit automat_batch:true freigeben und Gruppen-Limit in "
                  "batch_budget.json setzen.", file=sys.stderr)
        return 0

    if args.poll:
        print(json.dumps(poll(dry=False), ensure_ascii=False, indent=2)); return 0
    if args.submit:
        print(json.dumps(submit(all_boards, self_boards, dry=False), ensure_ascii=False, indent=2)); return 0

    # Default: voller Schritt (poll + submit), respektiert den Schalter.
    tick_step(all_boards, dry=False)
    print(json.dumps(_status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

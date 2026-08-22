#!/usr/bin/env python3
"""
grouping — KI-1-Stufe des Kanban-Automaten: gruppiert zusammengehörige Karten.

2-Stufen-Muster (KI 1 organisiert, KI 2 führt aus — siehe Memory 2-Stufen-Pipeline):
  KI 1 = Claude Haiku (Abo-Bridge 8950, seit Ollama-Ausstieg 16.08.2026) sieht alle offenen Karten
  eines Boards und bildet Gruppen inhaltlich zusammengehöriger Aufgaben.
  KI 2 = headless Claude-Worker bekommt die GANZE Gruppe in EINER Session statt
  Karte für Karte in getrennten Sessions — spart Tages-Starts (Limit 6) und
  den wiederholten Kontext-Aufbau pro Session.

Cache: state/groups/<slug>.json — neu gerechnet nur, wenn sich die Menge der
offenen Karten ändert (Hash über ids+Titel). Fallback bei KI-Fehler oder
unbrauchbarer Antwort: jede Karte ist ihre eigene Gruppe (= bisheriges Verhalten,
der Automat steht dadurch NIE still).

CLI (Test/Debug):
  python3 grouping.py --board <slug>            Gruppen anzeigen (nutzt Cache)
  python3 grouping.py --board <slug> --fresh    Cache ignorieren, neu gruppieren
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request

import automat_lib as lib
from automat_lib import logger, now_iso

# ── Konfiguration (env-überschreibbar) ──────────────────────────────────────
# Seit Ollama-Ausstieg 16.08.2026: Claude-Abo-CLI-Bridge (8950) statt Ollama.
# Haiku, weil reine Sortier-/Gruppieraufgabe (Modell-Politik: Massen-Jobs Haiku).
BRIDGE_URL = os.getenv("BRIDGE_URL") or lib.config_env("KANBAN_AUTOMAT_BRIDGE_URL")
if not BRIDGE_URL:
    logger.error("grouping: KANBAN_AUTOMAT_BRIDGE_URL fehlt (env oder ~/config.env) — Gruppierung faellt auf Einzelkarten zurueck")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")
GROUP_MODEL = os.getenv("AUTOMAT_GROUP_MODEL", "claude-haiku-4-5")
MAX_GROUP = int(os.getenv("AUTOMAT_MAX_GROUP", "4"))       # max Karten je Gruppe
MAX_CARDS = int(os.getenv("AUTOMAT_GROUP_MAX_CARDS", "40"))  # max Karten im KI-Prompt
# Bridge spawnt pro Call einen claude-Prozess (~5-30s); bei Timeout greift
# ohnehin der Einzelkarten-Fallback.
KI_TIMEOUT_S = int(os.getenv("AUTOMAT_KI_TIMEOUT_S", "180"))

GROUPS_DIR = lib.STATE_DIR / "groups"
GROUPS_DIR.mkdir(parents=True, exist_ok=True)


# ── Cache ───────────────────────────────────────────────────────────────────
def _cache_path(slug: str):
    return GROUPS_DIR / f"{slug.replace('/', '_')}.json"


def _fingerprint(cards: list[dict]) -> str:
    """Hash über ids+Titel der offenen Karten — ändert sich die Menge, wird neu gruppiert."""
    raw = "\n".join(sorted(f"{c.get('id')}|{c.get('title')}" for c in cards))
    return hashlib.sha1(raw.encode()).hexdigest()


def _load_cache(slug: str) -> dict | None:
    p = _cache_path(slug)
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception as e:
        logger.warning("grouping: Cache %s unlesbar: %s", p.name, e)
        return None


def _save_cache(slug: str, fp: str, groups: list[dict]) -> None:
    data = {"hash": fp, "computed_at": now_iso(), "model": GROUP_MODEL, "groups": groups}
    p = _cache_path(slug)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, p)
    logger.debug("grouping: Cache %s geschrieben (%d Gruppen)", p.name, len(groups))


# ── Claude-Bridge (KI 1) ────────────────────────────────────────────────────
def _ki_generate(prompt: str, num_predict: int = 900) -> str:
    """POST {BRIDGE_URL}/chat — Claude-Abo via CLI-Bridge, kein API-Guthaben."""
    payload = json.dumps({
        "model": GROUP_MODEL,
        "system": "Du organisierst Kanban-Karten. Antworte ausschliesslich mit dem verlangten JSON.",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict, "temperature": 0.1,
    }).encode()
    headers = {"Content-Type": "application/json"}
    bridge_token = os.getenv("BRIDGE_TOKEN", "")
    if bridge_token:
        headers["X-Bridge-Token"] = bridge_token
    req = urllib.request.Request(f"{BRIDGE_URL}/chat", data=payload,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=KI_TIMEOUT_S) as resp:
        return json.loads(resp.read()).get("text", "").strip()


def _group_prompt(slug: str, cards: list[dict]) -> str:
    lines = []
    for c in cards:
        desc = (c.get("description") or "").strip().replace("\n", " ")[:150]
        lines.append(f"- {c.get('id')} | {c.get('title')}" + (f" | {desc}" if desc else ""))
    return f"""Du organisierst das Kanban-Board '{slug}'. Offene Karten:

{chr(10).join(lines)}

Bilde Gruppen von Karten, die inhaltlich ZUSAMMENGEHÖREN und sinnvoll in EINEM
Arbeitsgang erledigt werden (gleiches Thema, gleiche Dateien/Komponente,
aufeinander aufbauend).

Antworte NUR mit JSON, ohne weiteren Text:
{{"gruppen": [{{"karten": ["id1", "id2"], "grund": "1 kurzer Satz"}}]}}

Regeln:
- Jede id aus der Liste kommt in GENAU eine Gruppe.
- Nur echte Zusammengehörigkeit gruppieren — im Zweifel Karte einzeln lassen (Gruppe mit 1 id).
- Höchstens {MAX_GROUP} Karten pro Gruppe.
- Verwende NUR ids aus der Liste, erfinde keine."""


def _validate_groups(raw_groups, cards: list[dict]) -> list[dict]:
    """Macht aus der KI-Antwort garantiert-konsistente Gruppen:
    nur bekannte ids, jede id genau einmal, Gruppengrösse gedeckelt,
    fehlende Karten als Einzelgruppen (in Prioritätsreihenfolge) angehängt."""
    known = {c.get("id") for c in cards}
    seen: set[str] = set()
    groups: list[dict] = []
    for g in raw_groups or []:
        ids = []
        for cid in (g.get("karten") or []):
            # LLM-Antworten normalisieren: Modelle kopieren gern Präfixe aus dem
            # Prompt-Listenformat mit (beobachtet 16.07.26: "id=card_…").
            cid = str(cid).strip()
            if cid.startswith("id="):
                cid = cid[3:]
            if cid in known and cid not in seen:
                ids.append(cid)
                seen.add(cid)
            elif cid not in known:
                logger.debug("grouping: unbekannte id %r von der KI verworfen", cid)
        for chunk_start in range(0, len(ids), MAX_GROUP):
            chunk = ids[chunk_start:chunk_start + MAX_GROUP]
            if chunk:
                groups.append({"karten": chunk, "grund": str(g.get("grund", ""))[:200]})
    missing = [c.get("id") for c in cards if c.get("id") not in seen]
    for cid in missing:
        groups.append({"karten": [cid], "grund": "(nicht gruppiert)"})
    if missing:
        logger.debug("grouping: %d Karten fehlten in der Antwort -> Einzelgruppen", len(missing))
    return groups


def _compute_groups(slug: str, cards: list[dict]) -> list[dict]:
    """Fragt die Claude-Bridge. Bei jedem Fehler: Fallback = alles Einzelgruppen."""
    try:
        raw = _ki_generate(_group_prompt(slug, cards))
        start, end = raw.find("{"), raw.rfind("}") + 1
        parsed = json.loads(raw[start:end])
        groups = _validate_groups(parsed.get("gruppen"), cards)
        n_multi = sum(1 for g in groups if len(g["karten"]) > 1)
        logger.info("grouping: %s -> %d Gruppen (%d mit >1 Karte) via %s",
                    slug, len(groups), n_multi, GROUP_MODEL)
        return groups
    except Exception as e:
        logger.warning("grouping: KI-Gruppierung für %s fehlgeschlagen (%s) — "
                       "Fallback Einzelkarten", slug, e)
        return [{"karten": [c.get("id")], "grund": "(Fallback: KI-Fehler)"} for c in cards]


def groups_for(slug: str, board: dict, fresh: bool = False,
               compute: bool = True) -> list[dict] | None:
    """Gruppen für die offenen Karten des Boards — aus Cache oder frisch via Claude-Bridge.

    compute=False: NUR Cache verwenden, nie die KI aufrufen (für plan(), das alle
    5 min über alle Boards läuft — sonst dauert ein Tick länger als der Takt).
    Rückgabe dann None bei Cache-Miss."""
    cards = [card for _col, card in lib.actionable_cards(board)][:MAX_CARDS]
    if not cards:
        return []
    fp = _fingerprint(cards)
    if not fresh:
        cached = _load_cache(slug)
        if cached and cached.get("hash") == fp:
            logger.debug("grouping: %s Cache-Treffer (%d Gruppen)", slug,
                         len(cached.get("groups", [])))
            return cached.get("groups", [])
    if not compute:
        return None
    groups = _compute_groups(slug, cards)
    _save_cache(slug, fp, groups)
    return groups


# ── Auswahl für den Orchestrator ────────────────────────────────────────────
def next_group(slug: str, board: dict, compute: bool = True) -> list[tuple[dict, dict]]:
    """Nächste Arbeitseinheit: die Gruppe, in der die höchstpriore Karte
    (bisheriges next_card) liegt. Rückgabe: Liste (column, card), Anker zuerst,
    Rest in Board-Prioritätsreihenfolge. Leer = keine offene Karte.
    compute=False: nur Cache (plan-Modus) — bei Cache-Miss nur die Anker-Karte."""
    cands = lib.actionable_cards(board)
    if not cands:
        return []
    anchor_col, anchor = cands[0]
    by_id = {card.get("id"): (col, card) for col, card in cands}
    for g in groups_for(slug, board, compute=compute) or []:
        if anchor.get("id") in g.get("karten", []):
            members = [by_id[cid] for cid in g["karten"] if cid in by_id]
            ordered = [(anchor_col, anchor)] + [(c, k) for c, k in members
                                                if k.get("id") != anchor.get("id")]
            return ordered[:MAX_GROUP]
    return [(anchor_col, anchor)]


# ── CLI (Test/Debug) ────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Kanban-Automat Karten-Gruppierung (KI 1 = Claude Haiku)")
    ap.add_argument("--board", required=True, help="Board-Slug")
    ap.add_argument("--fresh", action="store_true", help="Cache ignorieren, neu gruppieren")
    args = ap.parse_args()
    board = lib.get_board(args.board)
    titles = {card.get("id"): card.get("title") for _c, card in lib.actionable_cards(board)}
    groups = groups_for(args.board, board, fresh=args.fresh)
    print(f"== Gruppen für '{args.board}' ({len(groups)}) ==")
    for i, g in enumerate(groups, 1):
        print(f"\nGruppe {i} — {g.get('grund', '')}")
        for cid in g.get("karten", []):
            print(f"  - {cid}: {titles.get(cid, '?')}")
    nxt = next_group(args.board, board)
    print(f"\n→ next_group ({len(nxt)} Karten): " +
          ", ".join(card.get("title", "?") for _col, card in nxt))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

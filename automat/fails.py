#!/usr/bin/env python3
"""fails.py — Fehlversuchs-Zähler pro Karte (03.08.2026).

**Warum:** Ein Worker, der eine Karte nicht voranbringt, endet als No-Op (Laufzeit unter
`noop_refund_s`). Der Start wird zwar zurückerstattet, die Karte bleibt aber abarbeitbar —
und bekommt beim nächsten 5-min-Tick wieder einen Worker, der an derselben Stelle scheitert.
In den 30 Tagen vor diesem Modul: 597 Läufe, 53 fertige Karten (8,9 %). Der grösste Einzelfall
(`chile-spanisch`, 202 Läufe / 0 fertig) hatte eine erkennbare Ursache und ist separat gefixt —
dieser Zähler ist das **generische Netz** für alle übrigen, auch unbekannte Ursachen.

**Regel:** `max_card_fails` No-Op-Läufe IN FOLGE für dieselbe Karte → Karte wird automatisch
geparkt (raus aus `actionable_cards`, kein Worker mehr). Ein Lauf, der `done` meldet, setzt
den Zähler zurück; die Karte gilt dann wieder als gesund.

Bewusst NICHT als Board-Sperre umgesetzt: eine einzelne kaputte Karte darf die anderen
Karten desselben Boards nicht blockieren (Unterschied zur Entscheidungskarte).

Ansehen: `python3 fails.py`
"""
from __future__ import annotations

import json
import logging

import automat_lib as lib

logger = logging.getLogger("automat.fails")

FAILS_FILE = lib.STATE_DIR / "fails.json"
MAX_FAILS = lib.LIMITS["max_card_fails"]


def _key(slug: str, card_id: str) -> str:
    return f"{slug}/{card_id}"


def _load() -> dict:
    try:
        return json.loads(FAILS_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        FAILS_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    except Exception as e:
        logger.error("fails: schreiben fehlgeschlagen: %s", e)


def count(slug: str, card_id: str) -> int:
    return int(_load().get(_key(slug, card_id), 0))


def reset(slug: str, card_id: str) -> None:
    """Nach einem erfolgreichen Lauf (done) oder beim Parken aufrufen."""
    data = _load()
    if data.pop(_key(slug, card_id), None) is not None:
        _save(data)
        logger.debug("fails: %s/%s zurückgesetzt", slug, card_id)


def bump(slug: str, card_ids: list[str]) -> list[tuple[str, int]]:
    """Zähler für alle Karten eines No-Op-Laufs +1. Gibt [(card_id, neuer_stand)] zurück."""
    data = _load()
    out: list[tuple[str, int]] = []
    for cid in [c for c in card_ids if c]:
        n = int(data.get(_key(slug, cid), 0)) + 1
        data[_key(slug, cid)] = n
        out.append((cid, n))
    if out:
        _save(data)
    return out


def park_if_exhausted(slug: str, card_ids: list[str]) -> list[str]:
    """Zählt hoch und parkt jede Karte, die `max_card_fails` erreicht hat.
    Gibt die Liste der geparkten Karten-ids zurück. `max_card_fails=0` schaltet ab."""
    parked: list[str] = []
    for cid, n in bump(slug, card_ids):
        if MAX_FAILS and n >= MAX_FAILS:
            grund = (f"{n} Läufe in Folge ohne Ergebnis — der Automat kommt hier nicht "
                     f"weiter (Fail-Counter, Schwelle {MAX_FAILS})")
            # Aufrufer ist worker.reap(): eine Exception hier (Board weg, API down,
            # Timeout) würde das Aufräumen ALLER übrigen Worker abbrechen. Darum
            # kapseln — der Zähler bleibt dann stehen und der nächste Lauf versucht
            # es erneut, statt dass der Automat als Ganzes hängt.
            try:
                ok = lib.park_card(slug, cid, grund,
                                   "Manager prüft die Karte und zieht sie zurück ins Backlog")
            except Exception as e:
                logger.error("fails: parken von %s/%s fehlgeschlagen (%s) — Zähler bleibt "
                             "bei %d, nächster Lauf versucht es erneut", slug, cid, e, n)
                continue
            if ok:
                reset(slug, cid)
                parked.append(cid)
                logger.warning("fails: %s/%s nach %d No-Ops geparkt", slug, cid, n)
        elif MAX_FAILS:
            logger.info("fails: %s/%s No-Op %d/%d", slug, cid, n, MAX_FAILS)
    return parked


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data = _load()
    print(f"Schwelle max_card_fails = {MAX_FAILS}"
          f"{'  (Automatik AUS)' if not MAX_FAILS else ''}")
    print(f"Datei: {FAILS_FILE}")
    if not data:
        print("Keine Karte hat aktuell offene Fehlversuche.")
    for k, v in sorted(data.items(), key=lambda kv: -kv[1]):
        print(f"  {v}x  {k}")

#!/usr/bin/env python3
"""mine_collector — spiegelt 'meine' (owner=='me') Karten ins zentrale Board 'meine-aufgaben'.

Trennung KI/Ich: Jede Karte kann einen Besitzer haben:
  owner == "me"  -> 👤 ich muss das (meist physisch) erledigen
  owner == "ki"  -> 🤖 die KI/Claude erledigt das
  (kein owner)   -> unmarkiert

Dieser Job sammelt aus ALLEN Projekt-Boards die OFFENEN owner=='me'-Karten und
legt für jede eine Spiegel-Karte (id 'mirror::<board>::<cardid>') im Board
'meine-aufgaben' an. Idempotent:
  - existiert die Spiegel-Karte schon, werden Titel/Beschreibung/Quelle aktualisiert,
    ihre SPALTE bleibt aber, wo der User sie hingezogen hat (Fortschritt bleibt erhalten).
  - ist die Quelle erledigt (Erledigt-Spalte) oder eine beantwortete Entscheidung
    (Titel '✅ …'/'🗑️ …'), wandert der Spiegel in die Spalte 'Erledigt' — er
    verschwindet NICHT, damit sichtbar bleibt, was abgehakt wurde.
  - ist die Quelle weg / nicht mehr owner=='me' / abgelehnt -> Spiegel wird entfernt.
Manuell im Sammelboard angelegte Karten (ohne 'mirror::'-id) bleiben unangetastet.

Entscheidungen werden bewusst NICHT gespiegelt — die laufen über das eigene
Entscheidungs-/Automat-Board. Erkannt am Label 'Entscheidung'/'decision', an der
id 'decision…' ODER am Titel-Marker 'ENTSCHEIDUNG:' (die Bug-Pipeline setzt kein
Label — deshalb landeten deren Entscheidungen früher doch im Sammelboard).

CLI:  python mine_collector.py [--dry-run] [--debug]
Importierbar:  from mine_collector import collect  -> collect() gibt Statistik-dict.
"""
from __future__ import annotations
import sys, re, argparse, logging
sys.path.insert(0, ".")

from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("mine-collector")

TARGET_BOARD = "meine-aufgaben"
TARGET_COL = "todo"          # neue Spiegel landen hier
MIRROR_PREFIX = "mirror::"

# Boards, die nie als Quelle taugen (Meta/Sammel/Foto-Timestamps/Unterprojekt-Stubs)
SKIP_BOARDS = {TARGET_BOARD, "worklog", "ideen-box", "navigation", "ki_archiv"}
SKIP_RE = re.compile(r"^(foto[-_]\d|sub_|testesteset)")

# Spalten, die als "erledigt/raus" gelten (Substring, case-insensitiv) -> nicht spiegeln.
# 'behoben'/'fixed'/'closed' 2026-08-01 ergänzt: die Erledigt-Spalte von
# 'home-stack-bugs' heisst "Behoben" — sie fehlte hier, darum blieben 20 längst
# beantwortete Bug-Entscheidungen für immer im Sammelboard stehen.
# Gleiche Wortliste wie DONE_HINTS in app/api/automat.py.
DONE_RE = re.compile(r"(done|erledigt|fertig|abgeschlossen|beendet|behoben|fixed|closed|archiv)", re.I)
# Karten-Label, das Entscheidungen markiert -> separat halten
DECISION_RE = re.compile(r"(entscheidung|decision)", re.I)
# Bereits beantwortete Entscheidungskarte: decide() setzt genau diese Titel-Präfixe.
ANSWERED_PREFIXES = ("✅", "🗑️")


def _is_decision(card: dict) -> bool:
    """Entscheidungskarte robust erkennen — gleiche Heuristik wie
    automat_lib.is_decision_card / app/api/automat.py: das Label ist die Norm,
    aber die Bug-Pipeline legt Karten auch ohne Label an (id 'decision…' bzw.
    Titel-Marker 'ENTSCHEIDUNG:'). Nur auf das Label zu schauen hiess: die
    Bug-Entscheidungen landeten doch im Sammelboard."""
    if DECISION_RE.search((card.get("label") or "")):
        return True
    if str(card.get("id", "")).startswith("decision"):
        return True
    return "ENTSCHEIDUNG:" in str(card.get("title", ""))


def _mine_state(card: dict, col: dict) -> str:
    """Was soll mit dieser Karte im Sammelboard passieren?

      'open'     -> spiegeln bzw. bestehenden Spiegel aktualisieren
      'finished' -> erledigt (Quell-Spalte erledigt ODER Entscheidung beantwortet):
                    bestehender Spiegel wandert nach 'Erledigt' statt zu verschwinden
      'out'      -> gehört nicht (mehr) hierher: Spiegel entfernen
    """
    if (card.get("owner") or "").lower() != "me":
        return "out"
    if card.get("rejected") or card.get("deleted_at"):
        return "out"   # abgelehnt / als Rauschen gelöscht -> kein Eintrag für mich
    col_key = f"{col.get('id','')} {col.get('title','')}"
    if str(card.get("title", "")).startswith(ANSWERED_PREFIXES) or DONE_RE.search(col_key):
        return "finished"
    if _is_decision(card):
        return "out"   # offene Entscheidung läuft im eigenen Board, nicht hier
    return "open"


def _done_column(cols: list) -> dict | None:
    """Erledigt-Spalte des Sammelboards (sonst None)."""
    for c in cols:
        if DONE_RE.search(f"{c.get('id','')} {c.get('title','')}"):
            return c
    return None


def _family_boards(manifest: dict) -> list[str]:
    """Sammelboard + seine Unterboards, Unterboards ZUERST.

    Der KI-Sortierer verteilt Spiegel-Karten in Unterboards ('meine-aufgaben-*').
    Früher schaute der Collector nur ins Hauptboard: den verschobenen Spiegel sah
    er nicht mehr, legte im Hauptboard einen zweiten an (Duplikat) und pflegte den
    im Unterboard nie wieder. Darum wird die ganze Familie verwaltet — und bei
    einem Duplikat gewinnt die Karte im Unterboard (dort hat sie jemand einsortiert).
    """
    subs = []
    for b in manifest.get("boards", []):
        bid = b.get("id")
        if not bid or bid == TARGET_BOARD:
            continue
        if TARGET_BOARD in (b.get("parent_ids") or []) or bid.startswith(TARGET_BOARD + "-"):
            subs.append(bid)
    return subs + [TARGET_BOARD]


def _board_name(manifest: dict, board_id: str) -> str:
    for b in manifest.get("boards", []):
        if b.get("id") == board_id:
            return b.get("name") or board_id
    return board_id


def _mirror_id(board_id: str, card_id: str) -> str:
    return f"{MIRROR_PREFIX}{board_id}::{card_id}"


def _make_mirror_card(src_board_id: str, src_name: str, card: dict) -> dict:
    """Spiegel-Karte aus einer Quell-Karte bauen."""
    cid = card.get("id") or ""
    src_desc = (card.get("description") or card.get("desc") or "").strip()
    body = f"🔁 Aus Projekt **{src_name}**\n\n{src_desc}".strip()
    return {
        "id": _mirror_id(src_board_id, cid),
        "title": card.get("title") or "(ohne Titel)",
        "desc": body,
        "label": "mine",
        "priority": card.get("priority"),
        "effort": card.get("effort"),
        "mirror_source_board": src_board_id,
        "mirror_source_card": cid,
    }


def collect(dry_run: bool = False) -> dict:
    boards_repo = BoardRepository()
    manifest_repo = ManifestRepository()
    manifest = manifest_repo.load()

    board_ids = [b.get("id") for b in manifest.get("boards", []) if b.get("id")]
    family = _family_boards(manifest)          # Unterboards zuerst, TARGET_BOARD zuletzt
    skip_as_source = SKIP_BOARDS | set(family)  # die Familie ist Ziel, nie Quelle

    # 1) Soll-Zustand: alle offenen owner==me-Karten einsammeln; zusätzlich merken,
    #    welche Quellen inzwischen erledigt sind (deren Spiegel wandert nach 'Erledigt').
    wanted: dict[str, dict] = {}   # mirror_id -> mirror_card
    finished: set[str] = set()     # mirror_ids, deren Quelle erledigt/beantwortet ist
    for bid in board_ids:
        if bid in skip_as_source or SKIP_RE.match(bid):
            continue
        b = boards_repo.load(bid, inject_claude_md=False)
        if not b:
            continue
        name = _board_name(manifest, bid)
        for col in b.get("columns", []):
            for card in col.get("cards", []):
                state = _mine_state(card, col)
                if state == "open":
                    mc = _make_mirror_card(bid, name, card)
                    wanted[mc["id"]] = mc
                elif state == "finished":
                    finished.add(_mirror_id(bid, card.get("id") or ""))
    log.info("%d offene 'meine' Karten in %d Projekten gefunden (%d erledigte Quellen); "
             "Sammelboard-Familie: %s", len(wanted), len(board_ids), len(finished), family)

    stats = {"wanted": len(wanted), "added": 0, "updated": 0,
             "removed": 0, "finished": 0, "dupes": 0, "dry_run": dry_run}
    if dry_run:
        for mc in wanted.values():
            log.info("  würde spiegeln: %s  (%s)", mc["title"], mc["mirror_source_board"])
        return stats

    # 2) Wo liegt welcher Spiegel? Ein Vorab-Scan über die GANZE Familie, damit
    #    (a) ein ins Unterboard verschobener Spiegel gefunden statt doppelt angelegt wird
    #    und (b) echte Duplikate gezielt entfernt werden können.
    seen: dict[str, str] = {}          # mirror_id -> board_id, das ihn behält
    dupes: dict[str, set] = {}         # board_id -> {mirror_id, ...} (überzählige Kopien)
    for bid in family:
        b = boards_repo.load(bid, inject_claude_md=False)
        if not b:
            continue
        for col in b.get("columns", []):
            for card in col.get("cards", []):
                mid = card.get("id") or ""
                if not mid.startswith(MIRROR_PREFIX):
                    continue
                if mid not in seen:
                    seen[mid] = bid
                elif seen[mid] != bid:
                    dupes.setdefault(bid, set()).add(mid)
                    log.info("  Duplikat in %s (Original liegt in %s): %s",
                             bid, seen[mid], card.get("title"))
                # gleiche id ZWEIMAL im selben Board -> unten in mutate() zusammengelegt

    # 3) Jedes Familien-Board einzeln abgleichen (ein Lock pro Board, RMW).
    #    Neue Spiegel entstehen nur im Hauptboard; bestehende werden dort gepflegt,
    #    wo sie liegen (auch im Unterboard).
    def make_mutator(bid: str):
        def mutate(tb: dict):
            cols = tb.get("columns", [])
            if not cols:
                return tb
            col_by_id = {c.get("id"): c for c in cols}
            target_col = col_by_id.get(TARGET_COL, cols[0])
            done_col = _done_column(cols)
            board_dupes = dupes.get(bid, set())

            # dieselbe Spiegel-id mehrfach im SELBEN Board -> nur die erste behalten
            seen_here: set[str] = set()
            for c in cols:
                kept = []
                for card in c.get("cards", []):
                    cid = card.get("id") or ""
                    if cid.startswith(MIRROR_PREFIX):
                        if cid in seen_here:
                            stats["dupes"] += 1
                            log.info("  [%s] doppelte Karte im selben Board entfernt: %s",
                                     bid, card.get("title"))
                            continue
                        seen_here.add(cid)
                    kept.append(card)
                c["cards"] = kept

            # bestehende Spiegel finden (über alle Spalten) + ihre Spalte merken
            existing: dict[str, tuple] = {}   # mirror_id -> (col, card)
            for c in cols:
                for card in c.get("cards", []):
                    cid = card.get("id") or ""
                    if cid.startswith(MIRROR_PREFIX) and cid not in existing:
                        existing[cid] = (c, card)

            # erledigte Spiegel nach 'Erledigt' schieben, den Rest entfernen.
            # Früher wurde ALLES entfernt, was nicht mehr offen war — beantwortete
            # Entscheidungen verschwanden also entweder spurlos oder blieben (wenn die
            # Quell-Spalte nicht als erledigt erkannt wurde) für immer im Eingang liegen.
            for mid, (col, card) in list(existing.items()):
                if mid in wanted and mid not in board_dupes:
                    continue
                col["cards"] = [x for x in col["cards"] if (x.get("id") or "") != mid]
                if mid in board_dupes:
                    stats["dupes"] += 1
                    log.info("  [%s] Duplikat entfernt: %s", bid, card.get("title"))
                elif mid in finished and done_col is not None:
                    if col is not done_col:
                        done_col.setdefault("cards", []).insert(0, card)
                        stats["finished"] += 1
                        log.info("  [%s] → Erledigt (Quelle erledigt/beantwortet): %s",
                                 bid, card.get("title"))
                    else:
                        done_col["cards"].insert(0, card)   # lag schon richtig
                else:
                    stats["removed"] += 1
                    log.info("  [%s] entfernt (Quelle weg / nicht mehr meine): %s",
                             bid, card.get("title"))

            # aktualisieren, was hier liegt; NEUE Spiegel nur im Hauptboard anlegen
            for mid, mc in wanted.items():
                if mid in existing and mid not in board_dupes:
                    _col, card = existing[mid]
                    # Titel/Beschreibung/Meta aktualisieren, Spalte (Fortschritt) belassen
                    card["title"] = mc["title"]
                    card["desc"] = mc["desc"]
                    card["label"] = "mine"
                    card["priority"] = mc.get("priority")
                    card["effort"] = mc.get("effort")
                    card["mirror_source_board"] = mc["mirror_source_board"]
                    card["mirror_source_card"] = mc["mirror_source_card"]
                    stats["updated"] += 1
                elif bid == TARGET_BOARD and mid not in seen:
                    target_col.setdefault("cards", []).append(mc)
                    seen[mid] = bid
                    stats["added"] += 1
                    log.info("  + neu gespiegelt: %s", mc["title"])
            return tb
        return mutate

    for bid in family:
        try:
            boards_repo.update(bid, make_mutator(bid), sync_claude_md=False)
        except FileNotFoundError:
            log.warning("Familien-Board %s existiert nicht (mehr) — übersprungen", bid)

    log.info("Fertig: +%d neu, %d aktualisiert, %d → Erledigt, -%d entfernt, -%d Duplikate",
             stats["added"], stats["updated"], stats["finished"],
             stats["removed"], stats["dupes"])
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    collect(dry_run=a.dry_run)


if __name__ == "__main__":
    main()

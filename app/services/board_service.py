"""Board-LEBENSZYKLUS Phase 2 — laufender Betrieb: Lesen, Speichern, Patchen, Löschen, Rollup.

Erstellung (Phase 1: create_board/create_board_immediate/finalize_board_background,
KI-lastig) lebt getrennt in app/services/board_creation_service.py.

Schnittstelle
-------------
list_boards(parent, all_flag) -> dict   # {"boards": [...]} aus Manifest, child_order-Sortierung
get_board(board_id)           -> dict   # mit CLAUDE.md-Injektion; overview-Sonderfall: Default anlegen
board_rollup(root_id)         -> dict   # rekursives Karten-Aggregat über Sub-Boards
raw_board(board_id)           -> dict|None  # Board-JSON ohne Injektion (Legacy /kanban-api)
save_board(board_id, data)    -> int    # rev nach atomarem Speichern
patch_board(board_id, data)   -> dict   # Manifest-Metadaten ändern (Whitelist)
delete_board(board_id, purge) -> dict
set_card_owner(board_id, card_id, owner) -> dict
"""
import logging

from pydantic import ValidationError

from constants import AUTOMAT_MODELS, AUTOMAT_PRIORITIES, CATEGORIES

from app.schemas.board import Board
from app.storage.board_repository import BoardRepository, default_board_data
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.boards")


_boards = BoardRepository()
_manifest = ManifestRepository()


def _get_parents(b: dict) -> list:
    """parent_ids (Array, neu) hat Vorrang; parent_id (String, Legacy) als Fallback."""
    ids = b.get("parent_ids")
    if ids is not None:
        return ids if isinstance(ids, list) else [ids]
    legacy = b.get("parent_id")
    return [legacy] if legacy else []


def list_boards(parent: str = "", all_flag: bool = False) -> dict:
    manifest = _manifest.load()
    boards = manifest.get("boards", [])

    if all_flag:
        log.debug("Boards alle (kein Filter): %d Einträge", len(boards))
    elif parent:
        boards = [b for b in boards if parent in _get_parents(b)]
        # manuelle Reihenfolge (child_order am Parent, gesetzt per Drag&Drop)
        parent_entry = next((b for b in manifest.get("boards", []) if b.get("id") == parent), {})
        order = parent_entry.get("child_order") or []
        if order:
            pos = {cid: i for i, cid in enumerate(order)}
            boards.sort(key=lambda b: pos.get(b.get("id"), len(order)))
        log.debug("Boards gefiltert auf parent=%r: %d Einträge", parent, len(boards))
    else:
        boards = [b for b in boards if not _get_parents(b)]
        log.debug("Boards Top-Level: %d Einträge", len(boards))
    return {"boards": boards}


def get_board(board_id: str) -> dict:
    """Board mit CLAUDE.md-Injektion laden.

    Raises:
        FileNotFoundError: Board existiert nicht (und ist kein overview-Sonderfall).
    """
    log.debug("Board laden: id=%r", board_id)
    data = _boards.load(board_id)
    if data is not None:
        return data

    # Sonderfall 'overview': fehlt das Board, Default anlegen
    if board_id == "overview":
        log.info("Board 'overview' fehlt — lege Default-Board an")
        default = default_board_data()
        _boards.save(board_id, default, sync_claude_md=False)
        return default

    raise FileNotFoundError(f"Board '{board_id}' nicht gefunden")


def raw_board(board_id: str):
    """Board-JSON ohne CLAUDE.md-Injektion (Legacy /kanban-api). None wenn fehlt."""
    return _boards.load(board_id, inject_claude_md=False)


def save_board(board_id: str, data: dict) -> int:
    """Board-Inhalt speichern (POST /board) — atomar + CLAUDE.md-Rücksync + rev-Check (F4).

    Returns:
        Die neue Revision.
    Raises:
        ValueError: ungültige ID oder columns/Spalten/Karten entsprechen nicht dem
            Board-Schema (app/schemas/board.py) — z.B. columns fehlt/kein Array,
            eine Spalte ist kein Objekt, cards ist kein Array.
        StaleRevisionError: Client-Revision veraltet (→ 409).
    """
    if "columns" not in data:
        raise ValueError("Feld 'columns' fehlt oder ist kein Array")
    try:
        Board.model_validate(data)
    except ValidationError as e:
        # Kompakte Fehlermeldung statt vollem Pydantic-Traceback im 400er.
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"Board-Schema ungültig: {details}") from e
    rev = _boards.save_checked(board_id, data)
    log.info("Board '%s' gespeichert: %d Spalten (rev %d)", board_id, len(data["columns"]), rev)
    return rev


def _current_parents(e: dict) -> list:
    ids = e.get("parent_ids")
    if ids is not None:
        return list(ids) if isinstance(ids, list) else [ids]
    legacy = e.get("parent_id", "")
    return [legacy] if legacy else []


def patch_board(board_id: str, data: dict) -> dict:
    """Manifest-Metadaten eines Boards ändern (Semantik aus _handle_boards_patch).

    Raises:
        ValueError (400), FileNotFoundError (404)
    """
    if "parent_ids" in data and not isinstance(data["parent_ids"], list):
        raise ValueError("parent_ids muss eine Liste sein")

    result: dict = {}

    def mutate(manifest):
        entry = next((b for b in manifest["boards"] if b.get("id") == board_id), None)
        if entry is None:
            log.warning("PATCH: Board '%s' nicht in Manifest gefunden", board_id)
            raise FileNotFoundError(f"Board '{board_id}' nicht gefunden")

        if "parent_ids" in data:
            entry["parent_ids"] = data["parent_ids"]
            entry.pop("parent_id", None)
            log.info("Board '%s' parent_ids gesetzt: %s", board_id, data["parent_ids"])

        if "add_parent" in data:
            add_id = str(data["add_parent"]).strip()
            if add_id:
                current = _current_parents(entry)
                if add_id not in current:
                    current.append(add_id)
                entry["parent_ids"] = current
                entry.pop("parent_id", None)
                log.info("Board '%s' parent %r hinzugefügt: %s", board_id, add_id, current)

        if "remove_parent" in data:
            rm_id = str(data["remove_parent"]).strip()
            if rm_id:
                current = [p for p in _current_parents(entry) if p != rm_id]
                entry["parent_ids"] = current
                entry.pop("parent_id", None)
                log.info("Board '%s' parent %r entfernt: %s", board_id, rm_id, current)

        # description_updated: Datum der letzten KI-Beschreibung (Anzeige/Diagnose);
        # description_src_hash: Idempotenz-Marker des KI-Beschreibers — Fingerabdruck der
        #        Quelle (CLAUDE.md/Karten-Titel), aus der `description` erzeugt wurde.
        #        Gleicher Hash = Quelle unverändert = project_describer überspringt das Board
        #        ohne Ollama-Call (vorher tageweise → jede Nacht alle ~240 Boards neu);
        # tags: KI-Tags;
        # child_order: manuelle Unterprojekt-Reihenfolge (Drag&Drop);
        # last_activity: jüngster Worklog-Eintrag des Projekts (project_describer, kein Ollama);
        # code_dir: Code-Ordner abweichend von board_id (Quelle für project_describer)
        # eisenhower: Priorisierung pro Projekt (q1..q4, "" = nicht einsortiert)
        # auto: Freigabe für den Kanban-Automaten (bool) — nur diese Boards arbeitet
        #       der stündliche Watchdog ~/containers/kanban-automat/ autonom ab
        # archived: True = aus der Desktop-Übersicht ausblenden (verbergen, reversibel)
        # status: Lebenszyklus-Stand des Projekts (entwurf/in_bearbeitung/blockiert/
        #         pausiert/abgeschlossen/archiviert, s. STATUSES) — orthogonal zu category
        # test_first: Tri-State (True/False/nicht gesetzt=None→erbt via parent_ids).
        #             True = neue Versionen zuerst als Testcontainer <name>-test deployen
        #             (Container-Manager :8810 test-deploy), nie direkt in Prod.
        # model: Soll-Modell des Kanban-Automaten für dieses Projekt (claude-haiku-4-5 /
        #        claude-sonnet-5 / claude-opus-4-8 / claude-fable-5; None/"" = Standard).
        #        Bei Parallelbetrieb entwickelt der Automat eine Stufe tiefer und lässt
        #        anschliessend mit DIESEM Modell prüfen (~/containers/kanban-automat/models.py).
        # fable_optimize: Opt-in für den Fable-Optimier-Modus des Automaten (bool). Bei
        #        freiem Wochen-Budget-Kopf lässt der Automat das stärkste Modell (Fable 5)
        #        dieses Projekt projektweit analysieren + Verbesserungskarten anlegen
        #        (nur Test-Deploys). Steuerung: ~/containers/kanban-automat/fable_gate.py.
        # automat_priority: Priorität am Budget-Gate des Automaten (high/normal/low,
        #        fehlt = normal). "low" arbeitet nur, solange die Tages-Tranche noch
        #        komfortabel Kopf hat; "high" ignoriert das Budget-Gate ganz.
        #        Steuerung: ~/containers/kanban-automat/priority_gate.py.
        # automat_batch: Opt-in für den Batch-API-Pfad des Automaten (bool). Erzeugt für
        #        offene Karten dieses Boards über die Message Batches API (async, 50%
        #        günstiger, echtes API-Guthaben) einen Text-VORSCHLAG an der Karte —
        #        parallel zum Abo, kein Datei-Editieren. Master-Schalter `batch_enabled`
        #        + Gruppen-Kostenlimit in ~/containers/kanban-automat/batch.py / batch_gate.py.
        for field in ("name", "description", "color", "icon", "description_updated",
                      "description_src_hash",
                      "tags", "child_order", "category", "last_activity", "code_dir",
                      "eisenhower", "auto", "archived", "status", "test_first", "model",
                      "fable_optimize", "automat_priority", "automat_batch"):
            if field in data:
                if field == "test_first" and data[field] is None:
                    entry.pop("test_first", None)   # zurück auf "erbt vom Mutterprojekt"
                    log.debug("Board '%s' test_first entfernt (erbt)", board_id)
                    continue
                if field == "model":
                    val = data[field]
                    if not val:
                        entry.pop("model", None)    # zurück auf Standard-Modell
                        log.debug("Board '%s' model entfernt (Standard)", board_id)
                        continue
                    if val not in AUTOMAT_MODELS:
                        log.warning("Board '%s': unbekanntes Modell %r ignoriert", board_id, val)
                        continue
                if field == "automat_priority":
                    val = data[field]
                    if not val:
                        entry.pop("automat_priority", None)   # zurück auf Standard "normal"
                        log.debug("Board '%s' automat_priority entfernt (normal)", board_id)
                        continue
                    if val not in AUTOMAT_PRIORITIES:
                        log.warning("Board '%s': unbekannte automat_priority %r ignoriert", board_id, val)
                        continue
                entry[field] = data[field]
                log.debug("Board '%s' %s=%r", board_id, field, data[field])

        # Kategorie setzt automatisch die Board-Farbe (sofern nicht explizit mitgegeben)
        cat = data.get("category")
        if cat in CATEGORIES and "color" not in data:
            entry["color"] = CATEGORIES[cat]["color"]
            log.debug("Board '%s' color aus Kategorie %r: %s", board_id, cat, entry["color"])

        result["entry"] = entry

    _manifest.update(mutate)
    return {"status": "ok", "id": board_id, "entry": result["entry"]}


def _purge_project_folder(board_id: str):
    """Projektordner ~/Projekte/<board_id> löschen — mit hartem Sicherheits-Guard.

    NUR Ordner direkt unter ~/Projekte/ werden gelöscht (Ideen/Foto-Projekte). ~/containers/
    (echte Container-Quellen!) und alles ausserhalb bleiben unangetastet. Gibt den gelöschten
    Pfad zurück (oder None, wenn nichts gelöscht / abgelehnt).
    """
    import os
    import shutil
    from pathlib import Path
    base = Path(os.path.expanduser("~/Projekte")).resolve()
    target = (base / board_id).resolve()
    if target == base or base not in target.parents:
        log.warning("Purge ABGELEHNT (ausserhalb ~/Projekte): %s", target)
        return None
    if not target.is_dir():
        log.info("Purge: kein Ordner %s — nichts zu löschen", target)
        return None
    # Git-Repo = wertvoller Quellcode (z.B. immobilienverwaltung, crowai) → NIEMALS purgen.
    if (target / ".git").exists():
        log.warning("Purge ABGELEHNT (Git-Repo, geschützt): %s", target)
        return None
    shutil.rmtree(target)
    log.info("Projektordner gelöscht (purge): %s", target)
    return str(target)


def delete_board(board_id: str, purge: bool = False) -> dict:
    """Board-Datei löschen + Manifest-Eintrag entfernen.

    Args:
        purge: True → zusätzlich den Projektordner ~/Projekte/<id> löschen (Dateien/Fotos).
               Standard False = nur aus dem Dashboard entfernen, Ordner bleibt als Backup.
    Raises:
        ValueError: ungültige ID.
    """
    if not _boards.delete(board_id):
        log.warning("Board-Datei nicht gefunden, nur Manifest-Eintrag entfernen: %s",
                    _boards.board_path(board_id))

    counts: dict = {}

    def mutate(manifest):
        counts["before"] = len(manifest["boards"])
        manifest["boards"] = [b for b in manifest["boards"] if b.get("id") != board_id]
        counts["after"] = len(manifest["boards"])
        return manifest

    _manifest.update(mutate)
    log.info("Board '%s' aus Manifest entfernt (%d → %d Boards)",
             board_id, counts["before"], counts["after"])

    purged = _purge_project_folder(board_id) if purge else None
    return {"status": "ok", "deleted": board_id, "purged": purged}


def board_rollup(root_id: str) -> dict:
    """Karten aus root_id + allen Nachfolger-Boards (rekursiv, BFS) aggregieren."""
    manifest = _manifest.load()
    all_boards = manifest.get("boards", [])

    visited: set = set()
    queue = [root_id]
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        queue.extend(b["id"] for b in all_boards if cur in _get_parents(b) and b.get("id"))

    log.debug("Rollup %s: %d Boards", root_id, len(visited))

    result_cards: list = []
    result_boards: list = []
    col_order: dict = {}

    for bid in sorted(visited):
        bdata = _boards.load(bid, inject_claude_md=False)
        if bdata is None:
            continue
        meta = next((b for b in all_boards if b.get("id") == bid), {})
        bname = meta.get("name") or bdata.get("title") or bid
        result_boards.append({"id": bid, "name": bname})

        for col_idx, col in enumerate(bdata.get("columns", [])):
            cid = col.get("id", f"col{col_idx}")
            ctitle = col.get("title", cid)
            if cid not in col_order:
                col_order[cid] = (col_idx, ctitle)
            for card in col.get("cards", []):
                if card.get("archived_at") or card.get("rejected"):
                    continue
                result_cards.append({
                    **card,
                    "_board_id": bid,
                    "_board_name": bname,
                    "_col_id": cid,
                    "_col_title": ctitle,
                    "_col_index": col_idx,
                })

    columns = sorted(
        [{"id": cid, "title": t, "index": idx} for cid, (idx, t) in col_order.items()],
        key=lambda x: x["index"],
    )
    log.info("Rollup %s: %d Karten aus %d Boards", root_id, len(result_cards), len(visited))
    return {"root_id": root_id, "boards": result_boards, "columns": columns, "cards": result_cards}


def set_card_owner(board_id: str, card_id: str, owner: str | None) -> dict:
    """Setzt den Besitzer einer Karte: 'me' (👤 ich), 'ki' (🤖 KI) oder None (löschen).

    Atomar via Repository-Lock (read-modify-write). Triggert KEINEN Sammel-Job —
    der läuft per Timer / on-demand (mine_collector.collect()).

    Returns: {"board_id", "card_id", "owner"}.
    Raises: ValueError (Board/Karte fehlt oder ungültiger owner).
    """
    if owner not in ("me", "ki", None, ""):
        raise ValueError(f"Ungültiger owner: {owner!r} (erlaubt: me|ki|leer)")
    owner = owner or None

    found = {"hit": False}

    def mutate(b: dict):
        for col in b.get("columns", []):
            for card in col.get("cards", []):
                if (card.get("id") or "") == card_id:
                    if owner is None:
                        card.pop("owner", None)
                    else:
                        card["owner"] = owner
                    found["hit"] = True
                    return b
        return b  # nichts geändert -> Repository schreibt trotzdem (idempotent), wir prüfen unten

    if not _boards.exists(board_id):
        raise ValueError(f"Board '{board_id}' existiert nicht")
    _boards.update(board_id, mutate, sync_claude_md=False)
    if not found["hit"]:
        raise ValueError(f"Karte '{card_id}' in Board '{board_id}' nicht gefunden")
    log.info("Karte %s/%s owner=%s gesetzt", board_id, card_id, owner)
    return {"board_id": board_id, "card_id": card_id, "owner": owner}

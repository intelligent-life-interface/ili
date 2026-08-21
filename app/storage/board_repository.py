"""BoardRepository — einzige Lese-/Schreibstelle für boards/<id>.json inkl. CLAUDE.md-Sync.

Schnittstelle
-------------
repo = BoardRepository()                  # Produktiv-Pfade (env-überschreibbar)
repo = BoardRepository(boards_dir=tmp)    # Tests

repo.load(board_id)        -> dict|None   # mit CLAUDE.md-Injektion (live vom Disk)
repo.load_many(board_ids)  -> {id: dict|None}  # EIN Lock-Zyklus für viele Boards (Sammel-Read)
repo.save(board_id, data)                 # Lock → atomar schreiben → CLAUDE.md-Rücksync
repo.update(board_id, fn)                 # Lock über Read-Modify-Write (verhindert Lost Updates)
repo.delete(board_id)      -> bool
repo.exists(board_id)      -> bool
repo.board_path(board_id)  -> Path

CLAUDE.md-Sync:
- Injektion: ~/Projekte/<id>/CLAUDE.md → Karte id="claudemd-description" (erste Backlog-Karte)
- Rücksync: Beschreibungskarte → CLAUDE.md (nur wenn Projektordner existiert)
"""
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from app.storage.atomic_write import write_json_atomic
from app.storage.locking import file_lock, file_lock_shared

log = logging.getLogger("dashboard.storage.boards")

_DASHBOARD_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BOARDS_DIR = Path(os.environ.get("BOARDS_DIR", str(_DASHBOARD_DIR / "boards")))
DEFAULT_PROJEKTE_BASE = Path(os.environ.get("PROJEKTE_DIR", str(Path.home() / "Projekte")))

CLAUDE_MD_CARD_ID = "claudemd-description"


def _ensure_card_ids(data: dict, board_id: str) -> None:
    """Karten ohne 'id' bekommen serverseitig eine feste id (in-place).

    Sonst sind Karten per API/automat_cli (note/done arbeiten über die Karten-id)
    nicht adressierbar — Dedup/Reminder/Automat-Jobs können sie nicht referenzieren.
    """
    assigned = 0
    for col in data.get("columns", []):
        for card in col.get("cards", []):
            if not card.get("id"):
                card["id"] = f"card_{uuid.uuid4().hex[:8]}"
                assigned += 1
    if assigned:
        log.info("Board '%s': %d Karte(n) ohne id — Server-ids vergeben", board_id, assigned)


def _card_ids(data: dict) -> set:
    ids = set()
    for col in data.get("columns", []):
        for card in col.get("cards", []):
            cid = card.get("id")
            if cid:
                ids.add(cid)
    return ids


def _stamp_created_at(data: dict, previous_ids: set, board_id: str) -> None:
    """Echte Neuanlagen (id war vorher nicht im Board) bekommen `created_at`.

    Bewusst NICHT pauschal alle Karten ohne `created_at` stempeln — sonst würde
    z.B. ein einzelnes Notiz-Update alle Alt-Karten mit dem heutigen Datum
    überschreiben und deren echte Herkunft vortäuschen (Anlass: Bugfix 15.08.26 —
    Karten ohne nachvollziehbares Erstellungsdatum).
    """
    now = datetime.now().isoformat(timespec="seconds")
    stamped = 0
    for col in data.get("columns", []):
        for card in col.get("cards", []):
            cid = card.get("id")
            if cid and cid not in previous_ids and not card.get("created_at"):
                card["created_at"] = now
                stamped += 1
    if stamped:
        log.info("Board '%s': %d neue Karte(n) mit created_at gestempelt", board_id, stamped)


class StaleRevisionError(Exception):
    """Client-Revision passt nicht zum Server-Stand — alter Browser-Tab (F4-Schutz)."""
    def __init__(self, server_rev: int):
        self.server_rev = server_rev
        super().__init__(f"Board wurde inzwischen geändert (Server-Revision {server_rev})")


def default_board_data() -> dict:
    """Leere Board-Struktur mit 4 Standard-Spalten."""
    return {
        "columns": [
            {"id": "backlog",    "title": "Backlog",        "cards": []},
            {"id": "inprogress", "title": "In Bearbeitung", "cards": []},
            {"id": "review",     "title": "Überprüfen",     "cards": []},
            {"id": "done",       "title": "Erledigt",       "cards": []},
        ]
    }


class BoardRepository:
    def __init__(self, boards_dir: Path | None = None,
                 projekte_base: Path | None = None,
                 lock_timeout: float = 10.0):
        self.boards_dir = Path(boards_dir or DEFAULT_BOARDS_DIR)
        self.projekte_base = Path(projekte_base or DEFAULT_PROJEKTE_BASE)
        self.lock_file = self.boards_dir / ".lock"
        self.lock_timeout = lock_timeout

    # ---------- Pfade ----------

    @staticmethod
    def _safe_under(base: Path, *parts: str) -> Path:
        """`base` + `parts` zusammensetzen, auflösen und gegen Path-Traversal absichern.

        Zentraler Schutz für ALLE Lese-/Schreibpfade (board_path, CLAUDE.md-Sync):
        eine board_id wie '../../../../etc/passwd' oder '../user_settings' würde sonst
        aus `base` ausbrechen. Das aufgelöste Ergebnis MUSS unterhalb von `base`
        liegen — sonst ValueError (die API mappt das auf HTTP 400). resolve() fängt
        auch `..`-Ketten und Symlink-Ausbrüche ab.
        """
        base_resolved = base.resolve()
        candidate = (base / Path(*parts)).resolve()
        if candidate != base_resolved and not candidate.is_relative_to(base_resolved):
            log.warning("Path-Traversal abgelehnt: base=%s parts=%r -> %s",
                        base, parts, candidate)
            raise ValueError(f"Ungültige id (Path-Traversal abgelehnt): {'/'.join(parts)!r}")
        return candidate

    def board_path(self, board_id: str) -> Path:
        return self._safe_under(self.boards_dir, f"{board_id}.json")

    def exists(self, board_id: str) -> bool:
        return self.board_path(board_id).exists()

    def _project_dir(self, board_id: str) -> Path:
        """Validierter Projektordner ~/Projekte/<board_id> (Traversal-geschützt)."""
        return self._safe_under(self.projekte_base, board_id)

    def _claude_md_path(self, board_id: str) -> Optional[Path]:
        p = self._project_dir(board_id) / "CLAUDE.md"
        return p if p.exists() else None

    # ---------- Lese-/Schreib-API (mit Lock) ----------

    def load(self, board_id: str, inject_claude_md: bool = True) -> Optional[dict]:
        """Board laden. None wenn nicht vorhanden. Injiziert CLAUDE.md live vom Disk.

        Nutzt LOCK_SH (Shared) — mehrere Readers können parallel laufen.
        """
        with file_lock_shared(self.lock_file, self.lock_timeout):
            data = self._load_unlocked(board_id)
        if data is not None and inject_claude_md:
            data = self.inject_claude_md(data, board_id)
        return data

    def load_many(self, board_ids: list[str], inject_claude_md: bool = False) -> dict[str, Optional[dict]]:
        """Mehrere Boards unter EINEM Lock laden (Sammel-Read).

        opt_decisions_lock_0810: Aufrufer, die über viele/alle Boards iterieren
        (z.B. /api/automat/decisions über ~264 Boards), nahmen mit N x load()
        boards/.lock N mal exklusiv — das serialisiert gegen JEDEN Board-Write im
        System (FastAPI, Timer-Jobs, Hooks teilen denselben Lock). Hier EIN
        Lock-Zyklus für den ganzen Batch. Fehlende/kaputte Boards liefern None
        (gleiche Semantik wie load()), CLAUDE.md-Injektion läuft bewusst NACH dem
        Lock (Disk-Read, braucht boards/.lock nicht).

        Nutzt LOCK_SH (Shared) — mehrere Leseprozesse können parallel laufen.
        """
        with file_lock_shared(self.lock_file, self.lock_timeout):
            result = {bid: self._load_unlocked(bid) for bid in board_ids}
        if inject_claude_md:
            result = {bid: (self.inject_claude_md(data, bid) if data is not None else None)
                      for bid, data in result.items()}
        return result

    def save(self, board_id: str, data: dict, sync_claude_md: bool = True) -> None:
        """Board atomar speichern; danach Beschreibungskarte → CLAUDE.md zurücksyncen.

        F4: Jeder Save erhöht die Revision (rev) — Basis für den Stale-Tab-Schutz.
        Dieser Pfad prüft NICHT (Hooks/Timer/Sync dürfen immer schreiben).
        """
        with file_lock(self.lock_file, self.lock_timeout):
            stored = self._load_unlocked(board_id)
            previous_ids = _card_ids(stored) if stored else set()
            data["rev"] = (stored or {}).get("rev", 0) + 1
            _ensure_card_ids(data, board_id)
            _stamp_created_at(data, previous_ids, board_id)
            self._save_unlocked(board_id, data)
        if sync_claude_md:
            self.sync_claude_md_from_board(data, board_id)

    def save_checked(self, board_id: str, data: dict, sync_claude_md: bool = True) -> int:
        """Wie save(), aber MIT Revisions-Prüfung (F4-Stale-Tab-Schutz).

        Enthält data["rev"], muss sie der gespeicherten Revision entsprechen —
        sonst StaleRevisionError (→ HTTP 409). Ohne rev im Payload: erlaubt
        (Übergangs-Clients), Revision wird trotzdem hochgezählt.

        Returns:
            Die neue Revision.
        """
        with file_lock(self.lock_file, self.lock_timeout):
            stored = self._load_unlocked(board_id)
            previous_ids = _card_ids(stored) if stored else set()
            server_rev = (stored or {}).get("rev", 0)
            client_rev = data.get("rev")
            if stored is not None and client_rev is not None and int(client_rev) != server_rev:
                log.warning("Board '%s': Stale-Save abgelehnt (client_rev=%s, server_rev=%s)",
                            board_id, client_rev, server_rev)
                raise StaleRevisionError(server_rev)
            if client_rev is None:
                log.debug("Board '%s': Save ohne rev (Übergangs-Client) — erlaubt", board_id)
            data["rev"] = server_rev + 1
            _ensure_card_ids(data, board_id)
            _stamp_created_at(data, previous_ids, board_id)
            self._save_unlocked(board_id, data)
        if sync_claude_md:
            self.sync_claude_md_from_board(data, board_id)
        return data["rev"]

    def create(self, board_id: str, data: dict, sync_claude_md: bool = False) -> None:
        """Board NEU anlegen — Existenz-Prüfung und Schreiben unter EINEM Lock.

        Ersetzt das unsichere `if not path.exists(): path.write_text(...)`.

        Raises:
            FileExistsError: Board gibt es bereits (nichts wird überschrieben).
        """
        with file_lock(self.lock_file, self.lock_timeout):
            if self.board_path(board_id).exists():
                log.warning("Board '%s' existiert bereits — create() abgelehnt", board_id)
                raise FileExistsError(f"Board '{board_id}' existiert bereits")
            data.setdefault("rev", 1)
            _ensure_card_ids(data, board_id)
            _stamp_created_at(data, set(), board_id)
            self._save_unlocked(board_id, data)
            log.info("Board '%s' neu angelegt (%s)", board_id, self.board_path(board_id))
        if sync_claude_md:
            self.sync_claude_md_from_board(data, board_id)

    def update(self, board_id: str, mutator: Callable[[dict], Optional[dict]],
               create_default: bool = False, sync_claude_md: bool = True) -> dict:
        """Read-Modify-Write unter EINEM Lock — verhindert Lost Updates.

        Args:
            mutator: bekommt das Board-Dict, mutiert in-place oder gibt neues zurück.
            create_default: bei fehlendem Board mit default_board_data() starten.
        Returns:
            Das gespeicherte Board-Dict.
        Raises:
            FileNotFoundError: Board fehlt und create_default=False.
        """
        with file_lock(self.lock_file, self.lock_timeout):
            data = self._load_unlocked(board_id)
            if data is None:
                if not create_default:
                    raise FileNotFoundError(f"Board '{board_id}' nicht gefunden")
                data = default_board_data()
            previous_ids = _card_ids(data)
            result = mutator(data)
            if result is not None:
                data = result
            data["rev"] = data.get("rev", 0) + 1  # F4: jede Änderung zählt hoch
            _ensure_card_ids(data, board_id)
            _stamp_created_at(data, previous_ids, board_id)
            self._save_unlocked(board_id, data)
        if sync_claude_md:
            self.sync_claude_md_from_board(data, board_id)
        return data

    def move_cards(self, source_board_id: str, target_board_id: str,
                   card_ids: list[str], target_column_id: str = "backlog") -> dict:
        """Karten board-übergreifend verschieben — EIN Lock-Zyklus für Quelle+Ziel.

        flock ist NICHT reentrant (locking.py) — zwei verkettete update()-Aufrufe
        wären zwar je für sich lost-update-sicher, aber nicht atomar über beide
        Boards hinweg. Hier laufen Entfernen+Einfügen unter einem Lock.

        Args:
            card_ids: angefragte Karten-ids (id-basiertes Matching, s. _ensure_card_ids).
            target_column_id: Zielspalte im Ziel-Board, sonst erste Spalte.
        Returns:
            {"moved": [verschobene ids], "not_found": [angefragte, nicht gefundene ids]}
        Raises:
            FileNotFoundError: Quell- oder Ziel-Board fehlt.
        """
        wanted = set(card_ids) - {CLAUDE_MD_CARD_ID}
        with file_lock(self.lock_file, self.lock_timeout):
            src = self._load_unlocked(source_board_id)
            if src is None:
                raise FileNotFoundError(f"Board '{source_board_id}' nicht gefunden")
            tgt = self._load_unlocked(target_board_id)
            if tgt is None:
                raise FileNotFoundError(f"Board '{target_board_id}' nicht gefunden")

            collected = []
            for col in src.get("columns", []):
                keep = []
                for card in col.get("cards", []):
                    if card.get("id") in wanted and card.get("id") != CLAUDE_MD_CARD_ID:
                        collected.append(card)
                    else:
                        keep.append(card)
                col["cards"] = keep

            moved = [c["id"] for c in collected]
            not_found = list(wanted - set(moved))

            if collected:
                tgt_cols = tgt.get("columns", [])
                target_col = next((c for c in tgt_cols if c.get("id") == target_column_id),
                                   tgt_cols[0] if tgt_cols else None)
                if target_col is None:
                    raise ValueError(f"Ziel-Board '{target_board_id}' hat keine Spalten")
                target_col.setdefault("cards", []).extend(collected)

                src["rev"] = src.get("rev", 0) + 1
                tgt["rev"] = tgt.get("rev", 0) + 1
                _ensure_card_ids(src, source_board_id)
                _ensure_card_ids(tgt, target_board_id)
                self._save_unlocked(source_board_id, src)
                self._save_unlocked(target_board_id, tgt)
                log.info("move_cards: %d Karte(n) von '%s' nach '%s' verschoben",
                          len(moved), source_board_id, target_board_id)

            return {"moved": moved, "not_found": not_found}

    def delete(self, board_id: str) -> bool:
        """Board-Datei löschen. Returns True wenn etwas gelöscht wurde."""
        with file_lock(self.lock_file, self.lock_timeout):
            p = self.board_path(board_id)
            if p.exists():
                p.unlink()
                log.info("Board '%s' gelöscht (%s)", board_id, p)
                return True
            log.debug("Board '%s' zum Löschen nicht gefunden", board_id)
            return False

    # ---------- intern (Aufruf NUR mit gehaltenem Lock) ----------

    def _load_unlocked(self, board_id: str) -> Optional[dict]:
        p = self.board_path(board_id)
        if not p.exists():
            log.debug("Board '%s' nicht vorhanden (%s)", board_id, p)
            return None
        try:
            return json.loads(p.read_text())
        except Exception as e:
            log.error("Board '%s' nicht lesbar: %s", board_id, e)
            return None

    def _save_unlocked(self, board_id: str, data: dict) -> None:
        write_json_atomic(self.board_path(board_id), data)
        log.debug("Board '%s' gespeichert (%d Spalten)", board_id, len(data.get("columns", [])))

    # ---------- CLAUDE.md-Sync ----------

    def inject_claude_md(self, board_data: dict, board_id: str) -> dict:
        """CLAUDE.md live vom Disk lesen und als Beschreibungskarte einbetten."""
        md_path = self._claude_md_path(board_id)
        if not md_path:
            return board_data
        try:
            content = md_path.read_text()
        except Exception as e:
            log.warning("CLAUDE.md für '%s' nicht lesbar: %s", board_id, e)
            return board_data

        columns = board_data.get("columns", [])
        if not columns:
            return board_data

        for col in columns:
            for card in col.get("cards", []):
                if card.get("id") == CLAUDE_MD_CARD_ID:
                    card["description"] = content
                    log.debug("CLAUDE.md für '%s' in bestehende Karte injiziert", board_id)
                    return board_data

        backlog = next((c for c in columns if c.get("id") == "backlog"), columns[0])
        backlog.setdefault("cards", []).insert(0, {
            "id": CLAUDE_MD_CARD_ID,
            "title": f"📋 {board_id} – Beschreibung",
            "description": content,
            "category": "beschreibung",
            "status": "active",
            "label": "#4a90e2",
        })
        log.debug("CLAUDE.md für '%s' als neue Karte eingefügt", board_id)
        return board_data

    def sync_claude_md_from_board(self, board_data: dict, board_id: str) -> None:
        """Beschreibungskarte zurück nach ~/Projekte/<id>/CLAUDE.md schreiben."""
        for col in board_data.get("columns", []):
            for card in col.get("cards", []):
                if card.get("id") == CLAUDE_MD_CARD_ID:
                    content = (card.get("description") or "").strip()
                    if not content:
                        return
                    project_dir = self._project_dir(board_id)
                    if not project_dir.exists():
                        log.debug("Projekt-Ordner '%s' fehlt — kein CLAUDE.md-Rücksync", board_id)
                        return
                    md_path = project_dir / "CLAUDE.md"
                    try:
                        md_path.write_text(content)
                        log.info("CLAUDE.md für '%s' zurückgeschrieben (%d Zeichen)", board_id, len(content))
                    except Exception as e:
                        log.error("CLAUDE.md für '%s' nicht schreibbar: %s", board_id, e)
                    return

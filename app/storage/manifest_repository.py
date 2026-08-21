"""ManifestRepository — einzige Lese-/Schreibstelle für boards/manifest.json.

Teilt sich den Lock (boards/.lock) mit BoardRepository → Manifest+Board bleiben konsistent.

Schnittstelle
-------------
repo = ManifestRepository()               # Produktiv-Pfade
repo.load()              -> dict          # {"boards": [...]} — leeres Manifest bei Fehler
repo.save(manifest)                       # setzt created_at (einmalig) + updated_at (immer)
repo.update(fn)          -> dict          # Read-Modify-Write unter EINEM Lock
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.storage.atomic_write import write_json_atomic
from app.storage.locking import file_lock, file_lock_shared

log = logging.getLogger("dashboard.storage.manifest")

_DASHBOARD_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BOARDS_DIR = Path(os.environ.get("BOARDS_DIR", str(_DASHBOARD_DIR / "boards")))


class ManifestRepository:
    def __init__(self, boards_dir: Path | None = None, lock_timeout: float = 10.0):
        self.boards_dir = Path(boards_dir or DEFAULT_BOARDS_DIR)
        self.manifest_path = self.boards_dir / "manifest.json"
        self.lock_file = self.boards_dir / ".lock"   # GLEICHER Lock wie BoardRepository
        self.lock_timeout = lock_timeout

    def load(self) -> dict:
        """Manifest laden. Nutzt LOCK_SH (Shared) — mehrere Readers können parallel laufen."""
        with file_lock_shared(self.lock_file, self.lock_timeout):
            return self._load_unlocked()

    def save(self, manifest: dict) -> None:
        with file_lock(self.lock_file, self.lock_timeout):
            self._save_unlocked(manifest)

    def update(self, mutator: Callable[[dict], Optional[dict]]) -> dict:
        """Read-Modify-Write unter EINEM Lock — verhindert Lost Updates zwischen Prozessen."""
        with file_lock(self.lock_file, self.lock_timeout):
            manifest = self._load_unlocked()
            result = mutator(manifest)
            if result is not None:
                manifest = result
            self._save_unlocked(manifest)
        return manifest

    # ---------- intern (Aufruf NUR mit gehaltenem Lock) ----------

    def _load_unlocked(self) -> dict:
        if not self.manifest_path.exists():
            log.info("manifest.json fehlt — leeres Manifest")
            return {"boards": []}
        try:
            return json.loads(self.manifest_path.read_text())
        except Exception as e:
            log.error("manifest.json nicht lesbar: %s", e)
            return {"boards": []}

    def _save_unlocked(self, manifest: dict) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for b in manifest.get("boards", []):
            if "created_at" not in b:
                b["created_at"] = now
            b["updated_at"] = now
        write_json_atomic(self.manifest_path, manifest)
        log.debug("manifest.json gespeichert: %d Boards", len(manifest.get("boards", [])))

"""Datei-Anhänge für Boards & Karten — lokale Ablage + OneDrive-Sync via rclone.

Konzept (2026-06-16):
- Jede hochgeladene Datei wird zuerst lokal auf der grossen Platte gespeichert
  (`ATTACH_LOCAL_BASE/<board>/<scope>/<att_id>__<safe_name>`) und danach als
  Background-Task per `rclone copyto` in den OneDrive-Ordner
  `ATTACH_RCLONE_REMOTE/<board>/<scope>/<...>` (Remote `FHEM:`, type=onedrive)
  hochgeladen.  scope = "_projekt" (Projekt-Anhang) oder "card_<card_id>".
- Anhang-Metadaten leben im Board-JSON, IMMER via `BoardRepository.update`
  (fcntl-Lock, kein Direktschreiben):
    * Projekt-Anhänge → board["attachments"]   (Liste)
    * Karten-Anhänge  → card["attachments"]    (Karte per stabiler card["id"])
- status:  "uploading"  rclone läuft noch
           "synced"     in OneDrive angekommen
           "failed"     rclone-Fehler (Datei liegt lokal weiter vor & ist abrufbar)

Download läuft über /api/attachments/file/<att_id> (FileResponse aus der lokalen
Kopie) — kein direkter OneDrive-Zugriff aus dem Browser nötig.

Schnittstellen:
- save_upload(board_id, card_id, filename, content, content_type) -> dict (Anhang-Eintrag)
- sync_to_onedrive(board_id, att_id, card_id)         -> None   (Background-Task)
- find_entry(board_id, att_id, card_id)               -> dict|None
- delete_attachment(board_id, att_id, card_id)        -> bool
- list_attachments(board_id, card_id)                 -> list[dict]
"""
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from constants import (ATTACH_LOCAL_BASE, ATTACH_MOUNT_GUARD, ATTACH_RCLONE_BIN,
                       ATTACH_RCLONE_REMOTE)
from app.storage.board_repository import BoardRepository

log = logging.getLogger("dashboard.services.attachment")

_boards = BoardRepository()

_SAFE_RE = re.compile(r"[^A-Za-z0-9._\- ]+")


# ── Helfer ────────────────────────────────────────────────────────────────
def _scope(card_id: Optional[str]) -> str:
    """OneDrive-/Lokal-Unterordner: '_projekt' oder 'card_<id>'.

    card_id MUSS durch _safe_name — sonst schreibt ein card_id wie
    '../../../../app/html' die Datei in den von nginx ausgelieferten
    html/-Ordner (Stored XSS auf der Dashboard-Origin).
    """
    return f"card_{_safe_name(card_id)}" if card_id else "_projekt"


def _safe_name(name: str) -> str:
    """Dateiname für FS/rclone entschärfen (Pfad-Anteile + Sonderzeichen raus)."""
    name = os.path.basename((name or "datei").strip()) or "datei"
    name = _SAFE_RE.sub("_", name).strip("._ ") or "datei"
    return name[:120]


def _check_mount() -> None:
    """Bricht ab, wenn /mnt/daten NICHT gemountet ist — sonst landen die Dateien
    auf dem knappen Root-FS (gleiche Schutzlogik wie rclone-onedrive/sync.sh)."""
    if not os.path.ismount(ATTACH_MOUNT_GUARD):
        raise RuntimeError(f"Datenplatte {ATTACH_MOUNT_GUARD} ist nicht gemountet — "
                           f"Upload abgebrochen, damit nichts ins Root-FS läuft.")


def _local_dir(board_id: str, scope: str) -> Path:
    return ATTACH_LOCAL_BASE / _safe_name(board_id) / scope


def _safe_scope(scope: str) -> str:
    """scope ('_projekt' | 'card_<id>') von Pfad-Anteilen befreien.

    Anders als _safe_name wird das führende '_' von '_projekt' NICHT gestrippt
    (sonst zeigt der aufgelöste Pfad ins Leere und legitime Projekt-Anhänge
    wären nicht mehr abrufbar). '..' wird zu '_projekt' entschärft.
    """
    s = os.path.basename((scope or "").strip())
    return s if s and s != ".." else "_projekt"


def _resolved_under_base(board_id: str, scope: str, stored_name: str) -> Path:
    """Lokalen Anhang-Pfad bilden UND hart gegen Path-Traversal absichern.

    `scope` und `stored_name` kommen ROH aus dem Board-JSON, das per
    `POST /board?id=` (Schema extra='allow') frei beschreibbar ist. Ohne
    Härtung würde ein Anhang-Eintrag mit z.B. scope='../../../../home/produser'
    + stored_name='.ssh/id_rsa' aus ATTACH_LOCAL_BASE ausbrechen → Arbitrary
    File Read (local_file) bzw. Delete (delete_attachment) auf ~/config.env,
    ~/.claude/, SSH-Keys. Beide Anteile werden entschärft (scope via
    _safe_scope, stored_name via _safe_name) und danach greift derselbe
    resolve()/is_relative_to()-Check wie in save_upload().
    """
    path = _local_dir(board_id, _safe_scope(scope)) / _safe_name(stored_name)
    if not path.resolve().is_relative_to(ATTACH_LOCAL_BASE.resolve()):
        log.warning("Attachment-Traversal abgelehnt: board=%r scope=%r name=%r -> %s",
                    board_id, scope, stored_name, path)
        raise ValueError("Ungültiger Anhang-Pfad (Path-Traversal abgelehnt)")
    return path


def _remote_path(board_id: str, scope: str, stored_name: str) -> str:
    # rclone-Pfad: Remote:Ordner/<board>/<scope>/<stored_name>
    # scope/stored_name entschärfen — sie stammen roh aus dem Board-JSON und
    # gehen sonst ungefiltert in einen rclone-Zielpfad (OneDrive).
    return (f"{ATTACH_RCLONE_REMOTE}/{_safe_name(board_id)}"
            f"/{_safe_scope(scope)}/{_safe_name(stored_name)}")


def _owner(data: dict, card_id: Optional[str]) -> Optional[dict]:
    """Liefert das Dict, das die attachments-Liste hält (Board-Root oder Karte)."""
    if not card_id:
        return data
    for col in data.get("columns", []):
        for c in col.get("cards", []):
            if c.get("id") == card_id:
                return c
    return None


# ── Board-JSON-Mutationen (alle über repo.update → fcntl-Lock) ──────────────
def _add_entry(board_id: str, card_id: Optional[str], entry: dict) -> None:
    def mut(data):
        owner = _owner(data, card_id)
        if owner is None:
            raise KeyError(f"Karte '{card_id}' in Board '{board_id}' nicht gefunden")
        owner.setdefault("attachments", []).append(entry)
        return data
    _boards.update(board_id, mut, sync_claude_md=False)


def _update_entry(board_id: str, card_id: Optional[str], att_id: str, patch: dict) -> None:
    def mut(data):
        owner = _owner(data, card_id)
        if owner is None:
            return data
        for a in owner.get("attachments", []):
            if a.get("id") == att_id:
                a.update(patch)
                break
        return data
    _boards.update(board_id, mut, sync_claude_md=False)


def _remove_entry(board_id: str, card_id: Optional[str], att_id: str) -> Optional[dict]:
    removed = {}
    def mut(data):
        owner = _owner(data, card_id)
        if owner is None:
            return data
        lst = owner.get("attachments", [])
        keep = []
        for a in lst:
            if a.get("id") == att_id:
                removed["e"] = a
            else:
                keep.append(a)
        owner["attachments"] = keep
        return data
    _boards.update(board_id, mut, sync_claude_md=False)
    return removed.get("e")


# ── Öffentliche API ─────────────────────────────────────────────────────────
def save_upload(board_id: str, card_id: Optional[str], filename: str,
                content: bytes, content_type: Optional[str] = None) -> dict:
    """Datei lokal speichern + Anhang-Eintrag ins Board schreiben.

    rclone-Upload läuft NICHT hier, sondern als Background-Task (sync_to_onedrive).
    Returns: der Anhang-Eintrag (status='uploading').
    """
    _check_mount()
    # Karte muss existieren, BEVOR etwas geschrieben wird — sonst legt ein
    # ungültiges card_id eine Datei-Leiche an (der KeyError in _add_entry käme
    # erst NACH write_bytes). Projekt-Anhänge (card_id=None) sind ausgenommen.
    if card_id:
        data = _boards.load(board_id, inject_claude_md=False)
        if data is None or _owner(data, card_id) is None:
            raise KeyError(f"Karte '{card_id}' in Board '{board_id}' nicht gefunden")
    scope = _scope(card_id)
    att_id = uuid.uuid4().hex[:12]
    safe = _safe_name(filename)
    stored_name = f"{att_id}__{safe}"

    local_dir = _local_dir(board_id, scope)
    # Traversal-Guard (defense-in-depth zu _safe_name in _scope/_local_dir):
    # der aufgelöste Zielordner MUSS unter ATTACH_LOCAL_BASE liegen.
    base_resolved = ATTACH_LOCAL_BASE.resolve()
    if not local_dir.resolve().is_relative_to(base_resolved):
        log.warning("Attachment-Traversal abgelehnt: board=%r card=%r -> %s",
                    board_id, card_id, local_dir)
        raise ValueError("Ungültige board_id/card_id (Path-Traversal abgelehnt)")
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / stored_name
    local_path.write_bytes(content)
    log.info("Anhang gespeichert: %s (%s Bytes, board=%s, card=%s)",
             local_path, f"{len(content):,}", board_id, card_id or "-")

    entry = {
        "id": att_id,
        "filename": safe,
        "stored_name": stored_name,
        "size": len(content),
        "content_type": content_type or "application/octet-stream",
        "uploaded": datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "status": "uploading",
        "onedrive_path": _remote_path(board_id, scope, stored_name).split(":", 1)[-1],
        "download_url": f"/api/attachments/file/{att_id}",
    }
    _add_entry(board_id, card_id, entry)
    return entry


def sync_to_onedrive(board_id: str, att_id: str, card_id: Optional[str]) -> None:
    """Background-Task: lokale Kopie per rclone nach OneDrive hochladen."""
    entry = find_entry(board_id, att_id, card_id)
    if not entry:
        log.warning("sync_to_onedrive: Anhang %s nicht gefunden (board=%s)", att_id, board_id)
        return
    scope = entry.get("scope", _scope(card_id))
    local_path = _local_dir(board_id, scope) / entry["stored_name"]
    remote = _remote_path(board_id, scope, entry["stored_name"])
    cmd = [ATTACH_RCLONE_BIN, "copyto", str(local_path), remote, "-q"]
    log.info("rclone Upload → OneDrive: %s", remote)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if res.returncode == 0:
            _update_entry(board_id, card_id, att_id, {"status": "synced"})
            log.info("Anhang %s nach OneDrive synchronisiert", att_id)
        else:
            _update_entry(board_id, card_id, att_id,
                          {"status": "failed", "error": (res.stderr or "")[:300]})
            log.error("rclone-Fehler (rc=%s) für %s: %s", res.returncode, att_id, res.stderr[:300])
    except Exception as e:
        _update_entry(board_id, card_id, att_id, {"status": "failed", "error": str(e)[:300]})
        log.error("rclone-Exception für %s: %s", att_id, e, exc_info=True)


def find_entry(board_id: str, att_id: str, card_id: Optional[str]) -> Optional[dict]:
    """Anhang-Eintrag aus dem Board lesen (ohne CLAUDE.md-Injektion)."""
    data = _boards.load(board_id, inject_claude_md=False)
    if not data:
        return None
    owner = _owner(data, card_id)
    if owner is None:
        return None
    for a in owner.get("attachments", []):
        if a.get("id") == att_id:
            return a
    return None


def list_attachments(board_id: str, card_id: Optional[str]) -> list:
    data = _boards.load(board_id, inject_claude_md=False)
    if not data:
        return []
    owner = _owner(data, card_id)
    return list(owner.get("attachments", [])) if owner else []


def local_file(board_id: str, att_id: str, card_id: Optional[str]):
    """(Path, filename, content_type) für FileResponse — oder None wenn nicht da."""
    entry = find_entry(board_id, att_id, card_id)
    if not entry:
        return None
    scope = entry.get("scope", _scope(card_id))
    try:
        path = _resolved_under_base(board_id, scope, entry.get("stored_name", ""))
    except ValueError:
        return None  # → 404 statt Arbitrary File Read
    if not path.exists():
        return None
    return path, entry.get("filename", "datei"), entry.get("content_type", "application/octet-stream")


def delete_attachment(board_id: str, att_id: str, card_id: Optional[str]) -> bool:
    """Anhang entfernen: Board-Eintrag + lokale Datei + OneDrive-Kopie (best effort).

    Link-Einträge (type="link", z.B. aus link_service) haben keine lokale Datei/
    OneDrive-Kopie — für sie reicht das Entfernen aus dem Board-Eintrag.
    """
    entry = _remove_entry(board_id, card_id, att_id)
    if not entry:
        return False
    if entry.get("type") == "link":
        log.info("Link-Anhang entfernt: %s (board=%s)", entry.get("url"), board_id)
        return True
    scope = entry.get("scope", _scope(card_id))
    # lokale Datei — Board-Eintrag ist oben schon entfernt; bei Traversal wird
    # nur das Datei-Löschen übersprungen (kein Arbitrary File Delete).
    try:
        _resolved_under_base(board_id, scope, entry["stored_name"]).unlink(missing_ok=True)
    except ValueError as e:
        log.warning("Anhang-Datei-Löschung abgelehnt (Path-Traversal): %s", e)
    except Exception as e:
        log.warning("Lokale Anhang-Datei %s nicht löschbar: %s", att_id, e)
    # OneDrive-Kopie (best effort, nur wenn überhaupt hochgeladen)
    if entry.get("status") == "synced":
        remote = _remote_path(board_id, scope, entry["stored_name"])
        try:
            subprocess.run([ATTACH_RCLONE_BIN, "deletefile", remote, "-q"],
                           capture_output=True, text=True, timeout=120)
            log.info("OneDrive-Kopie gelöscht: %s", remote)
        except Exception as e:
            log.warning("OneDrive-Datei %s nicht löschbar: %s", remote, e)
    return True

"""Foto→Projekt-Pipeline — extrahiert aus trigger_server._handle_project_from_photo.

Sync-Teil: Foto speichern (+GPS-EXIF), Board + Manifest sofort anlegen → 201.
Async-Teil (FastAPI BackgroundTasks statt threading.Thread): Ollama-Vision
(Titel + Tags) + Projektordner, danach Board/Manifest aktualisieren.
"""
import base64
import logging
import os
from datetime import datetime

from constants import PHOTOS_DIR, CATEGORIES
from project_creator import (_create_project_folder, _slugify, _unique_board_id,
                             _vision_tags, _vision_title)

from app.services.gps_exif import inject_gps_exif
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.photo")

_boards = BoardRepository()
_manifest = ManifestRepository()


def decode_and_save_photo(photo_b64: str, ts: str, gps: tuple | None = None,
                          suffix: str = "") -> tuple[str, str, bytes]:
    """Base64-Foto dekodieren + unter /photos speichern (+ optional GPS-EXIF).

    Gemeinsamer Helper für den Foto-Flow (create_from_photo) UND den vereinten
    Erstell-Flow (board_creation_service.create_board_immediate) — "ein und dasselbe".

    Args:
        photo_b64: dataURL oder reines Base64 (leer erlaubt).
        ts:        Zeitstempel für den Dateinamen (foto_<ts><suffix>.jpg).
        gps:       (lat, lon, alt|None, direction|None) oder None.
        suffix:    Eindeutigkeits-Suffix, wenn mehrere Fotos denselben ts teilen (z.B. "_1").
    Returns:
        (photo_url, photo_filename, photo_bytes) — photo_url leer, wenn nichts gespeichert.
    """
    photo_b64 = (photo_b64 or "").strip()
    photo_bytes = b""
    if photo_b64:
        try:
            if "," in photo_b64:
                photo_b64 = photo_b64.split(",", 1)[1]
            photo_bytes = base64.b64decode(photo_b64)
        except Exception as e:
            log.error("Foto dekodieren fehlgeschlagen: %s", e)
    if not photo_bytes:
        return "", "", b""

    photo_filename = f"foto_{ts}{suffix}.jpg"
    photo_url = ""
    try:
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        photo_path = PHOTOS_DIR / photo_filename
        photo_path.write_bytes(photo_bytes)
        if gps:
            lat, lon, alt, direction = gps
            inject_gps_exif(photo_path, float(lat), float(lon),
                            float(alt) if alt is not None else None,
                            float(direction) if direction is not None else None)
        photo_url = f"/photos/{photo_filename}"
        log.info("Foto gespeichert: %s (%s Bytes)", photo_path, f"{len(photo_bytes):,}")
    except Exception as e:
        log.error("Foto speichern fehlgeschlagen: %s", e)
    return photo_url, photo_filename, photo_bytes


def create_from_photo(data: dict) -> tuple[dict, dict]:
    """Sync-Teil: Foto + Board + Manifest anlegen.

    Returns:
        (response_payload, bg_args) — bg_args für analyse_in_background().
    """
    photo_b64 = (data.get("photo") or "").strip()
    title = (data.get("title") or "").strip()
    note = (data.get("note") or "").strip()
    parent_id = (data.get("parent_id") or "").strip()

    gps_lat = data.get("gps_lat")
    gps_lon = data.get("gps_lon")
    gps_alt = data.get("gps_alt")
    gps_direction = data.get("gps_direction")
    gps_accuracy = data.get("gps_accuracy")
    has_gps = gps_lat is not None and gps_lon is not None

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    # Foto dekodieren + speichern
    photo_bytes_raw = b""
    if photo_b64:
        try:
            if "," in photo_b64:
                photo_b64 = photo_b64.split(",", 1)[1]
            photo_bytes_raw = base64.b64decode(photo_b64)
        except Exception as e:
            log.error("Foto dekodieren fehlgeschlagen: %s", e)

    photo_url = ""
    photo_filename = f"foto_{ts}.jpg"
    if photo_bytes_raw:
        try:
            PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
            photo_path = PHOTOS_DIR / photo_filename
            photo_path.write_bytes(photo_bytes_raw)
            if has_gps:
                inject_gps_exif(photo_path, float(gps_lat), float(gps_lon),
                                float(gps_alt) if gps_alt is not None else None,
                                float(gps_direction) if gps_direction is not None else None)
            photo_url = f"/photos/{photo_filename}"
            log.info("Foto gespeichert: %s (%s Bytes)", photo_path, f"{len(photo_bytes_raw):,}")
        except Exception as e:
            log.error("Foto speichern fehlgeschlagen: %s", e)

    temp_title = title or f"Foto {now.strftime('%d.%m.%Y %H:%M')}"
    board_id = _unique_board_id(f"foto-{ts}")

    # Board sofort anlegen
    first_card: dict = {
        "title": "📸 Inspiration",
        "desc": (note + "\n\n" if note else "") + "⏳ Wird analysiert…",
        "label": "#b794f4",
    }
    if photo_url:
        first_card["photo_url"] = photo_url

    board_data = {
        "title": temp_title,
        "columns": [
            {"id": "ideen",      "title": "Ideen",          "cards": [first_card]},
            {"id": "backlog",    "title": "Backlog",        "cards": []},
            {"id": "inprogress", "title": "In Bearbeitung", "cards": []},
            {"id": "done",       "title": "Erledigt",       "cards": []},
        ],
    }
    _boards.save(board_id, board_data, sync_claude_md=False)

    # Manifest-Eintrag
    gps_desc = ""
    if has_gps:
        dir_str = f", Richtung {float(gps_direction):.1f}°" if gps_direction is not None else ""
        gps_desc = f" | GPS: {float(gps_lat):.5f},{float(gps_lon):.5f}{dir_str}"
    foto_entry: dict = {
        "id": board_id,
        "name": temp_title,
        "description": f"Schnell-Idee via Foto — {now.strftime('%d.%m.%Y %H:%M')}{gps_desc}",
        "color": "#b794f4",
        "icon": "📸",
        "type": "idea",
        "analyzing": True,
    }
    if has_gps:
        foto_entry["gps"] = {
            "lat": float(gps_lat), "lon": float(gps_lon),
            "alt": float(gps_alt) if gps_alt is not None else None,
            "direction": float(gps_direction) if gps_direction is not None else None,
            "accuracy": float(gps_accuracy) if gps_accuracy is not None else None,
        }
    if photo_url:
        foto_entry["cover_photo"] = photo_url
    if parent_id:
        foto_entry["parent_ids"] = [parent_id]

    _manifest.update(lambda m: m["boards"].append(foto_entry) or None)

    board_url = f"{os.environ.get('SERVER_URL', 'http://localhost')}/project.html?id={board_id}"
    log.info("Foto-Board sofort angelegt: %r — Analyse startet im Hintergrund", board_id)

    response = {
        "status": "ok",
        "board_id": board_id,
        "board_url": board_url,
        "title": temp_title,
        "analyzing": True,
    }
    bg_args = {
        "board_id": board_id,
        "photo_bytes": photo_bytes_raw,
        "note": note,
        "user_title": title,
        "photo_filename": photo_filename,
        "fallback_title": f"Foto {now.strftime('%d.%m.%Y %H:%M')}",
    }
    return response, bg_args


def analyse_in_background(board_id: str, photo_bytes: bytes, note: str,
                          user_title: str, photo_filename: str, fallback_title: str) -> None:
    """Async-Teil: Ollama-Vision-Analyse, Projektordner, Board-/Manifest-Update."""
    log.info("[BG] Starte Ollama-Analyse für %r", board_id)
    try:
        final_title = user_title
        if not final_title and photo_bytes:
            final_title = _vision_title(photo_bytes, note)
        if not final_title:
            final_title = fallback_title

        tags = _vision_tags(photo_bytes, note) if photo_bytes else []

        # Projektordner (inkl. CLAUDE.md + TAGS.md + fotos/)
        new_board_id = _unique_board_id(_slugify(final_title)) if _slugify(final_title) else board_id
        _create_project_folder(
            name=final_title, board_id=new_board_id,
            description=note, photo_bytes=photo_bytes,
            photo_filename=photo_filename, tags=tags, is_idea=True,
        )

        # Board-Karte aktualisieren (gelockt, Read-Modify-Write)
        def update_board(bd):
            bd["title"] = final_title
            for col in bd.get("columns", []):
                for card in col.get("cards", []):
                    if card.get("title") == "📸 Inspiration":
                        card["desc"] = (note + "\n\n" if note else "") + (
                            f"🏷️ Tags: {', '.join(tags)}" if tags else "✓ Analysiert"
                        )
        try:
            _boards.update(board_id, update_board, sync_claude_md=False)
        except FileNotFoundError:
            log.warning("[BG] Board %r verschwunden — überspringe Board-Update", board_id)

        # Auto-Kategorie (Foto-Pfad ist async → Ollama-Fallback erlaubt). Prio bewusst
        # NICHT setzen → Foto-Idee zeigt sich als 📥 'noch nicht einsortiert' = sichtbar neu.
        category = ""
        try:
            from auto_categorize import categorize_one
            category = categorize_one(final_title, tags, note, use_ai=True)
        except Exception as e:
            log.warning("[BG] Auto-Kategorie übersprungen (%r): %s", board_id, e)

        # Manifest: Titel + Tags + Kategorie, analyzing entfernen
        def update_manifest(m):
            for entry in m["boards"]:
                if entry.get("id") == board_id:
                    entry["name"] = final_title
                    entry.pop("analyzing", None)
                    if tags:
                        entry["tags"] = tags
                    if category and not entry.get("category"):
                        entry["category"] = category
                        entry["color"] = CATEGORIES.get(category, {}).get("color", entry.get("color"))
                    break
        _manifest.update(update_manifest)
        log.info("[BG] Analyse fertig: %r → '%s' tags=%s cat=%s", board_id, final_title, tags, category)
    except Exception as e:
        log.error("[BG] Analyse fehlgeschlagen für %r: %s", board_id, e, exc_info=True)

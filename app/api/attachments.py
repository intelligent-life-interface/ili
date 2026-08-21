"""API-Router: Datei-Anhänge für Boards & Karten (2026-06-16).

Speicher: lokale Kopie auf /mnt/daten + OneDrive-Sync via rclone (eigener Ordner).
Logik komplett in app/services/attachment_service.py.

Endpunkte:
  POST   /api/attachments                 multipart: file, board_id, [card_id]
  GET    /api/attachments?board_id&card_id Liste der Anhänge (Board- oder Karten-Ebene)
  GET    /api/attachments/{id}/status      Sync-Status (Polling nach Upload)
  GET    /api/attachments/file/{id}        Datei-Download (FileResponse, lokale Kopie)
  DELETE /api/attachments/{id}             Anhang löschen (Board + lokal + OneDrive)

card_id ist optional (leer = Projekt-/Board-Anhang). Karten werden über ihre
stabile card["id"] identifiziert — das Frontend stellt sicher, dass die Karte
vor dem Upload eine id hat.
"""
import logging
from typing import Optional

from fastapi import (APIRouter, BackgroundTasks, File, Form, HTTPException,
                     Query, UploadFile)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from constants import ATTACH_MAX_BYTES
from app.services import attachment_service as att

log = logging.getLogger("dashboard.api.attachments")
router = APIRouter(prefix="/api/attachments", tags=["attachments"])


def _norm_card(card_id: Optional[str]) -> Optional[str]:
    cid = (card_id or "").strip()
    if not cid:
        return None
    # card_id fliesst in den lokalen/OneDrive-Pfad ein — Pfadtrenner/Traversal sind
    # nie eine echte Karten-id (card_<hex>/c_<...>) und würden sonst aus dem
    # Anhang-Ordner ausbrechen (Stored-XSS-Risiko, sec_attach_scope_2607).
    if any(ch in cid for ch in ("/", "\\", "\x00")) or ".." in cid:
        raise HTTPException(status_code=400, detail="Ungültige card_id")
    return cid


@router.post("")
async def upload_attachment(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    board_id: str = Form(...),
    card_id: Optional[str] = Form(None),
):
    cid = _norm_card(card_id)

    # Content-Length vorab prüfen, wenn vorhanden (verhindert auch Anfragen mit
    # extremen Headern, bevor irgendwelche Reads stattfinden)
    content_length = file.size
    if content_length is not None and content_length > ATTACH_MAX_BYTES:
        log.warning("Upload abgelehnt (Content-Length %s > %s): %s board=%s",
                    f"{content_length:,}", f"{ATTACH_MAX_BYTES:,}", file.filename, board_id)
        raise HTTPException(status_code=413,
                            detail=f"Datei zu gross (max {ATTACH_MAX_BYTES // (1024*1024)} MB)")

    # Chunkweise lesen mit Limit-Check — verhindert, dass eine grosse Datei komplett
    # in den RAM gepuffert wird, bevor die Grössen-Prüfung greift.
    # review: file.file.read() ist synchron und blockiert bei auf Platte gespoolten
    # Uploads (Starlette spoolt >1MB automatisch) den ganzen Event-Loop — await
    # file.read() nutzt Starlettes eigenen run_in_threadpool-Wrapper.
    chunk_size = 1_048_576  # 1 MB Chunks
    content = b""
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content += chunk
        if len(content) > ATTACH_MAX_BYTES:
            log.warning("Upload abgelehnt (Limit überschritten während Lesen): %s board=%s",
                        file.filename, board_id)
            raise HTTPException(status_code=413,
                                detail=f"Datei zu gross (max {ATTACH_MAX_BYTES // (1024*1024)} MB)")

    log.info("Upload empfangen: %s (%s Bytes) board=%s card=%s",
             file.filename, f"{len(content):,}", board_id, cid or "-")
    if not content:
        raise HTTPException(status_code=400, detail="Leere Datei")
    try:
        # save_upload blockiert (file_lock-Busy-Wait + write_bytes) — im Threadpool
        # ausführen, damit der Event-Loop (Board-Requests, /health, Streaming) frei bleibt.
        entry = await run_in_threadpool(att.save_upload, board_id, cid,
                                        file.filename or "datei", content,
                                        file.content_type)
    except RuntimeError as e:          # Mount-Guard
        log.error("Upload abgelehnt: %s", e)
        raise HTTPException(status_code=503, detail=f"{e}")
    except ValueError as e:            # Path-Traversal-Guard (_scope/_local_dir)
        log.warning("Upload abgelehnt (Traversal): %s", e)
        raise HTTPException(status_code=400, detail=f"{e}")
    except KeyError as e:              # Karte nicht gefunden
        raise HTTPException(status_code=404, detail=f"{e}")
    except Exception as e:
        log.error("Upload-Fehler: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")
    # rclone-Upload nach OneDrive im Hintergrund (Antwort kommt sofort zurück)
    background_tasks.add_task(att.sync_to_onedrive, board_id, entry["id"], cid)
    return entry


@router.get("")
def list_attachments(board_id: str = Query(...), card_id: Optional[str] = Query(None)):
    return {"attachments": att.list_attachments(board_id, _norm_card(card_id))}


@router.get("/{att_id}/status")
def attachment_status(att_id: str, board_id: str = Query(...),
                      card_id: Optional[str] = Query(None)):
    entry = att.find_entry(board_id, att_id, _norm_card(card_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    return {"id": att_id, "status": entry.get("status"), "error": entry.get("error")}


@router.get("/file/{att_id}")
def download_attachment(att_id: str, board_id: str = Query(...),
                        card_id: Optional[str] = Query(None)):
    res = att.local_file(board_id, att_id, _norm_card(card_id))
    if not res:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    path, filename, ctype = res
    return FileResponse(path, media_type=ctype, filename=filename)


@router.delete("/{att_id}")
def delete_attachment(att_id: str, board_id: str = Query(...),
                      card_id: Optional[str] = Query(None)):
    ok = att.delete_attachment(board_id, att_id, _norm_card(card_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    return {"deleted": att_id}

"""API-Router: Board-Routen (Welle 2: Reads; Welle 3 ergänzt Writes).

Routen: GET /boards, /board?id=, /board-rollup?id=, /kanban, /kanban-api?board=
"""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services import board_creation_service, board_service, card_move_service
from app.services.board_creation_service import UnclearNameError
from app.storage.board_repository import StaleRevisionError

log = logging.getLogger("dashboard.api.boards")
router = APIRouter(tags=["boards"])


@router.get("/boards")
def list_boards(parent: str = "", all: str = ""):
    try:
        return board_service.list_boards(parent=parent, all_flag=(all == "1"))
    except Exception as e:
        log.error("Fehler beim Laden der Boards-Liste: %s", e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/board")
def get_board(id: str = Query(default="")):
    if not id:
        raise HTTPException(status_code=400, detail="Query-Parameter 'id' fehlt")
    try:
        return board_service.get_board(id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Board '{id}' nicht gefunden")
    except ValueError as e:
        # Path-Traversal-Guard (board_repository._safe_under) → 400 statt 500
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Laden von Board '%s': %s", id, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/board-rollup")
def board_rollup(id: str = Query(default="")):
    if not id:
        raise HTTPException(status_code=400, detail="Parameter 'id' fehlt")
    try:
        return board_service.board_rollup(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Rollup-Fehler für %s: %s", id, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/boards", status_code=201)
def create_board(body: dict, background_tasks: BackgroundTasks):
    """Neues Board anlegen.

    - {fast:true} → synchron, ohne KI (Priority Widget +Knopf/Unterprojekt, Name exakt, <1s).
    - sonst → Board + Manifest SOFORT mit fester ID (201 in <1s), die schwere KI
      (Namenskorrektur, Tags, Ideen-Karten, CLAUDE.md, ggf. Foto-Vision) läuft als
      BackgroundTask. Das verhindert Timeout-Doppelprojekte und vereint Formular- +
      Foto-Erstellung ("ein und dasselbe"). Optionales Feld `photo` (Base64) erlaubt.
    """
    try:
        if body.get("fast"):
            return board_creation_service.create_board(body)
        response, bg_args = board_creation_service.create_board_immediate(body)
        if bg_args:
            background_tasks.add_task(board_creation_service.finalize_board_background, **bg_args)
        return response
    except UnclearNameError as e:
        # Spezial-Payload des alten Servers beibehalten
        return JSONResponse(status_code=400, content={
            "error": "Eingabe unklar",
            "message": f"'{e.raw_name}' ergibt keinen erkennbaren Projektnamen. "
                       f"Bitte mehr Informationen angeben.",
            "input": e.raw_name,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Anlegen des Boards: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/board")
def save_board(body: dict, id: str = Query(default="")):
    if not id:
        raise HTTPException(status_code=400, detail="Query-Parameter 'id' fehlt")
    try:
        rev = board_service.save_board(id, body)
        return {"status": "ok", "rev": rev}
    except StaleRevisionError as e:
        # F4: alter Browser-Tab — kein stilles Überschreiben
        return JSONResponse(status_code=409, content={
            "error": "Board wurde inzwischen geändert — bitte Seite neu laden",
            "server_rev": e.server_rev,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Speichern von Board '%s': %s", id, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.patch("/boards/{board_id}")
def patch_board(board_id: str, body: dict):
    """Manifest-Metadaten ändern. Umlaut-IDs decodiert FastAPI automatisch."""
    try:
        return board_service.patch_board(board_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim PATCH von Board '%s': %s", board_id, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.delete("/boards/{board_id}")
def delete_board(board_id: str, purge: bool = False):
    """purge=1 → zusätzlich den Projektordner ~/Projekte/<id> löschen (Dateien/Fotos)."""
    try:
        return board_service.delete_board(board_id, purge=purge)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Löschen des Boards '%s': %s", board_id, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.post("/boards/{board_id}/move-cards")
def move_cards(board_id: str, body: dict):
    """Karten aus board_id (Quelle) in ein anderes Projekt übernehmen (Leichen-Feature).

    Body: {"card_ids": [...], "target_board_id": "..."}
    Eine card_id landet direkt im Ziel-Board (Backlog). Mehrere card_ids landen
    gesammelt in einem neu angelegten Sub-Board unter dem Ziel-Projekt.
    """
    card_ids = body.get("card_ids")
    target_board_id = (body.get("target_board_id") or "").strip()
    if not isinstance(card_ids, list) or not card_ids:
        raise HTTPException(status_code=400, detail="Feld 'card_ids' muss eine nicht-leere Liste sein")
    if not target_board_id:
        raise HTTPException(status_code=400, detail="Feld 'target_board_id' fehlt")
    try:
        return card_move_service.move_cards_to_project(board_id, card_ids, target_board_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"{e}")
    except Exception as e:
        log.error("Fehler beim Karten-Verschieben '%s' -> '%s': %s", board_id, target_board_id, e,
                  exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/kanban-api")
def kanban_api(board: str = "home-stack-bugs"):
    """Rohes Board-JSON ohne CLAUDE.md-Injektion.

    Aktiver Consumer: ~/bin/kanban-split (greift direkt auf :8798 zu, nicht via nginx).
    Die alten Endpoints GET/POST /kanban wurden 2026-07-28 entfernt (toter Code +
    non-atomarer kanban.json-Direktschreiber, Kanban-Karte opt_55d9f1678f).
    """
    log.debug("GET /kanban-api board=%r", board)
    try:
        data = board_service.raw_board(board)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    if data is None:
        raise HTTPException(status_code=404, detail="Board nicht gefunden")
    return data

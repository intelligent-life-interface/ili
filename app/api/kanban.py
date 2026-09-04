"""API-Router: Tag-Suche, Verwandte-Projekte, Log-Scan (Welle 2, read-only).

Routen: /search-by-tag?q=, /find-related?project=&n=&ai=, /scan-logs?since=
Wiederverwendet: project_creator.search_projects_by_tag, related_finder.find_related,
                 log_scanner.run_full_scan
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from log_scanner import run_full_scan
from project_creator import search_projects_by_tag
from related_finder import find_related
from dedup_finder import check_duplicate
from prio_suggester import suggest_priorities, suggest_eisenhower
from board_cleanup import run_cleanup

log = logging.getLogger("dashboard.api.kanban")
router = APIRouter(tags=["kanban"])


class DedupIn(BaseModel):
    board_id: str
    title: str
    desc: str = ""
    ai: bool = True


class PrioIn(BaseModel):
    board_id: str
    ai: bool = True


class EisItem(BaseModel):
    id: str
    name: str = ""
    category: str = ""
    desc: str = ""


class EisenhowerIn(BaseModel):
    items: list[EisItem] = []
    ai: bool = True


class CleanupIn(BaseModel):
    board_id: str
    apply: bool = False          # False = Trockenlauf/Vorschau, True = wirklich aufteilen
    threshold: int | None = None


@router.post("/eisenhower-suggest")
def eisenhower_suggest(req: EisenhowerIn):
    """KI-Vorschlag für den Eisenhower-Quadranten von Projekten (Übersicht).

    Body: {items:[{id,name,category,desc}], ai?}. Der Aufrufer übergibt NUR Projekte ohne
    gesetzten Quadranten. Antwort: {count, ai, suggestions:[{id, quadrant}]} (q1..q4).
    Schreibt nichts — das Frontend setzt die Quadranten via PATCH und überspringt dabei
    inzwischen belegte (nie überschreiben).
    """
    try:
        items = [it.model_dump() for it in req.items]
        return suggest_eisenhower(items, use_ai=req.ai)
    except Exception as e:
        log.error("eisenhower-suggest Fehler: %s", e, exc_info=True)
        return {"count": 0, "ai": False, "suggestions": [], "note": f"Fehler: {e}"}


@router.post("/prio-suggest")
def prio_suggest(req: PrioIn):
    """KI-Prioritäten-Vorschlag für die Karten eines Boards (read-only).

    Body: {board_id, ai?}. Antwort: {board_id, count, ai, cards:[{title,column,priority,source,effort}]}.
    Vom User gesetzte Prioritäten bleiben unangetastet (source="user") und gehen nie an die KI;
    nur Karten ohne Priorität stuft Ollama ein (Fallback: lokale Heuristik).
    """
    if not req.board_id:
        raise HTTPException(status_code=400, detail="board_id ist Pflicht")
    try:
        return suggest_priorities(req.board_id, use_ai=req.ai)
    except Exception as e:
        log.error("prio-suggest Fehler für %r: %s", req.board_id, e, exc_info=True)
        return {"board_id": req.board_id, "count": 0, "ai": False, "cards": [], "note": f"Fehler: {e}"}


@router.post("/dedup-check")
def dedup_check(req: DedupIn):
    """Prüft, ob eine neue Wunsch-/Aufgabenkarte eine offene Karte des Boards dupliziert.

    Body: {board_id, title, desc?, ai?}. Antwort: {board_id, query, duplicates:[...]}.
    Billig: Jaccard-Vorfilter lokal; Ollama nur bei Verdacht und nur mit Titeln.
    """
    if not req.board_id or not req.title.strip():
        raise HTTPException(status_code=400, detail="board_id und title sind Pflicht")
    try:
        return check_duplicate(req.board_id, req.title, req.desc, use_ai=req.ai)
    except Exception as e:
        log.error("dedup-check Fehler für %r: %s", req.board_id, e, exc_info=True)
        # Dedup darf das Anlegen NIE blockieren -> leeres Ergebnis statt 500.
        return {"board_id": req.board_id, "query": req.title, "duplicates": [], "note": f"Fehler: {e}"}


@router.post("/cleanup-board")
def cleanup_board(req: CleanupIn):
    """Löst den zeitgesteuerten Aufräumer (kanban-split) on-demand für EIN Board aus.

    Body: {board_id, apply?, threshold?}. apply=false (Default) = Trockenlauf/Vorschau
    (schreibt nichts); apply=true = teilt das Board wirklich in thematische Unterprojekte
    auf (Backup wird vorher angelegt, Karten werden verschoben).
    Antwort: {board_id, applied, ok, nothing_to_do, output}.
    """
    if not req.board_id.strip():
        raise HTTPException(status_code=400, detail="board_id ist Pflicht")
    try:
        return run_cleanup(req.board_id, apply=req.apply, threshold=req.threshold)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    except Exception as e:
        log.error("cleanup-board Fehler für %r: %s", req.board_id, e, exc_info=True)
        return {"board_id": req.board_id, "applied": req.apply, "ok": False,
                "nothing_to_do": False, "output": "", "note": f"Fehler: {e}"}


class CardOwnerIn(BaseModel):
    board_id: str
    card_id: str
    owner: str | None = None   # "me" (👤), "ki" (🤖) oder leer/null = löschen


class CardGithubIssueIn(BaseModel):
    board_id: str
    card_id: str
    github_issue_id: str | None = None  # GitHub-Issue-URL oder leer/null = löschen


@router.post("/card-owner")
def card_owner(req: CardOwnerIn):
    """Setzt den Besitzer einer Karte (👤 me / 🤖 ki / leer) und spiegelt sofort.

    Body: {board_id, card_id, owner}. Nach dem Setzen läuft der Sammel-Job
    (mine_collector.collect) best-effort, damit 'meine' Karten ohne Wartezeit
    im Board 'meine-aufgaben' erscheinen/verschwinden.
    Antwort: {board_id, card_id, owner, collected?}.
    """
    from app.services.board_service import set_card_owner
    if not req.board_id.strip() or not req.card_id.strip():
        raise HTTPException(status_code=400, detail="board_id und card_id sind Pflicht")
    try:
        res = set_card_owner(req.board_id, req.card_id, req.owner)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    try:
        from mine_collector import collect
        res["collected"] = collect()
    except Exception as e:  # Spiegeln darf das Setzen nie scheitern lassen
        log.warning("card-owner: Sammel-Job übersprungen: %s", e)
        res["collected"] = None
    return res


@router.post("/card-github-issue")
def card_github_issue(req: CardGithubIssueIn):
    """Setzt die GitHub-Issue-URL einer Karte (für Seed-Karten → automatische Issues).

    Body: {board_id, card_id, github_issue_id}. Die ID speichert den Link
    zur automatisch erstellten GitHub-Issue. Leer/null = löschen.
    Antwort: {board_id, card_id, github_issue_id}.
    """
    from app.services.board_service import set_card_github_issue_id
    if not req.board_id.strip() or not req.card_id.strip():
        raise HTTPException(status_code=400, detail="board_id und card_id sind Pflicht")
    try:
        res = set_card_github_issue_id(req.board_id, req.card_id, req.github_issue_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e}")
    return res


@router.get("/search-by-tag")
def search_by_tag(q: str = "", tag: str = ""):
    query = q or tag
    if not query:
        raise HTTPException(status_code=400, detail="Parameter 'q' fehlt")
    results = search_projects_by_tag(query)
    log.debug("Tag-Suche %r: %d Treffer", query, len(results))
    return {"query": query, "count": len(results), "results": results}


@router.get("/find-related")
def find_related_route(project: str = "", id: str = "", n: int = 8, ai: str = "1"):
    proj = project or id
    if not proj:
        raise HTTPException(status_code=400, detail="Parameter 'project' fehlt")
    try:
        return find_related(proj, top_n=n, use_ai=(ai != "0"))
    except Exception as e:
        log.error("find-related Fehler für %r: %s", proj, e)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")


@router.get("/scan-logs")
def scan_logs(since: int = Query(default=24)):
    since_hours = max(1, min(since, 168))  # 1h–7d
    try:
        return run_full_scan(since_hours=since_hours)
    except Exception as e:
        log.error("scan-logs fehlgeschlagen: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

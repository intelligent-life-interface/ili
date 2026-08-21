"""Isehauer-Anbindung — Eisenhower-Priorität eines Projekts lesen/setzen (F1.1).

Schnittstelle
-------------
get_item(project_id)          -> dict  # {available, week, sorted, item|None}; nie Exception
patch_item(project_id, fields)-> dict  # Whitelist-Felder setzen; Isehauer down -> IsehauerDownError

Isehauer-API (Port 3005, keine Auth): GET /api/week/current, GET /api/week/{iso},
PATCH /api/week/{iso}/item/{item_id}, POST /api/week/{iso}/item.
Item-IDs sind 'project:<board_id>' — beim URL-Pfad IMMER quote()en (Umlaute!).
"""
import logging
import urllib.parse

import httpx

from constants import ISEHAUER_URL

log = logging.getLogger("dashboard.services.isehauer")

TIMEOUT = 2.5  # Sekunden — Isehauer ist lokal, länger warten lohnt nicht

# Nur diese Felder dürfen Richtung Isehauer durchgereicht werden
PATCH_WHITELIST = {"quadrant", "frog_date", "pareto", "clear_quadrant", "clear_frog"}


class IsehauerDownError(Exception):
    """Isehauer nicht erreichbar (Timeout/ConnectError) bei einer Schreib-Operation."""


def _client(client: httpx.Client | None) -> httpx.Client:
    """Injizierbarer Client (Tests: httpx.MockTransport)."""
    return client if client is not None else httpx.Client(base_url=ISEHAUER_URL, timeout=TIMEOUT)


def _find_item(week_data: dict, item_id: str) -> tuple[dict | None, bool]:
    """Sucht Item in Matrix Q1-Q4 + Inbox. Return (item|None, sorted: bool)."""
    for quad, items in (week_data.get("matrix") or {}).items():
        for it in items:
            if it.get("id") == item_id:
                return it, True
    for it in week_data.get("inbox") or []:
        if it.get("id") == item_id:
            return it, False
    return None, False


def get_item(project_id: str, client: httpx.Client | None = None) -> dict:
    """Eisenhower-Status eines Projekts in der aktuellen Woche.

    Return {available: bool, week: str, sorted: bool, item: dict|None}
    item = {quadrant: 'Q1'..'Q4'|None, frog_date: str|None, pareto: bool, title: str}
    Isehauer down -> {available: False} (log.warning, KEINE Exception).
    """
    item_id = f"project:{project_id}"
    c = _client(client)
    try:
        r = c.get("/api/week/current")
        r.raise_for_status()
        week = r.json().get("week", "")
        r = c.get(f"/api/week/{week}")
        r.raise_for_status()
        week_data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Isehauer nicht erreichbar (get_item %s): %s", project_id, e)
        return {"available": False, "week": None, "sorted": False, "item": None}
    finally:
        if client is None:
            c.close()

    raw, in_matrix = _find_item(week_data, item_id)
    if raw is None:
        log.debug("Isehauer: Projekt %s nicht in Woche %s (weder Matrix noch Inbox)", project_id, week)
        return {"available": True, "week": week, "sorted": False, "item": None}

    item = {
        "quadrant": raw.get("quadrant"),
        "frog_date": raw.get("frog_date"),
        "pareto": bool(raw.get("pareto")),
        "title": raw.get("title") or project_id,
    }
    log.debug("Isehauer: %s in Woche %s — quadrant=%s frog=%s pareto=%s (matrix=%s)",
              project_id, week, item["quadrant"], item["frog_date"], item["pareto"], in_matrix)
    return {"available": True, "week": week, "sorted": in_matrix, "item": item}


def patch_item(project_id: str, fields: dict, client: httpx.Client | None = None) -> dict:
    """Eisenhower-Felder setzen. Whitelist: quadrant, frog_date, pareto, clear_quadrant, clear_frog.

    PATCH auf das Item; 404 (Item noch nicht in der Woche) -> POST-Upsert-Fallback.
    Isehauer down -> raise IsehauerDownError.
    Return: das Service-Result von get_item() nach dem Schreiben (frischer Stand).
    """
    payload = {k: v for k, v in (fields or {}).items() if k in PATCH_WHITELIST}
    dropped = set(fields or {}) - set(payload)
    if dropped:
        log.debug("Isehauer patch_item %s: Felder ausserhalb Whitelist ignoriert: %s", project_id, dropped)
    if not payload:
        raise ValueError("Keine gültigen Felder (Whitelist: " + ", ".join(sorted(PATCH_WHITELIST)) + ")")

    item_id = f"project:{project_id}"
    quoted_id = urllib.parse.quote(item_id, safe="")  # Umlaute + ':' encodieren
    c = _client(client)
    try:
        r = c.get("/api/week/current")
        r.raise_for_status()
        week = r.json().get("week", "")

        r = c.patch(f"/api/week/{week}/item/{quoted_id}", json=payload)
        if r.status_code == 404:
            # Item noch nicht in der Woche -> Upsert via POST
            log.debug("Isehauer: %s nicht in Woche %s — POST-Fallback", item_id, week)
            body = {"type": "project", "board_id": project_id, **payload}
            # clear_* sind nur PATCH-Semantik, beim Neuanlegen sinnlos
            body.pop("clear_quadrant", None)
            body.pop("clear_frog", None)
            r = c.post(f"/api/week/{week}/item", json=body)
        r.raise_for_status()
        log.info("Isehauer: %s in Woche %s gesetzt: %s", project_id, week, payload)
    except httpx.HTTPStatusError as e:
        log.error("Isehauer-Fehler bei patch_item %s: HTTP %s — %s",
                  project_id, e.response.status_code, e.response.text[:200])
        raise IsehauerDownError(f"Isehauer antwortet mit HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        log.error("Isehauer nicht erreichbar bei patch_item %s: %s", project_id, e)
        raise IsehauerDownError(f"Isehauer nicht erreichbar: {e}") from e
    finally:
        if client is None:
            c.close()

    return get_item(project_id, client=client)

"""Dashboard-Service: aggregiert alle Daten für GET /api/dashboard.

Ersetzt die Datensammlung des statischen Generators (generate_dashboard.py):
- Projekt-Rollup: Top-Level-Boards aus dem Manifest + Karten-Zählung pro
  Spalte (backlog / in_progress / done) + Anzahl Unterprojekte
- Kategorien (constants.CATEGORIES: label/color/emoji)
- Container-Status via podman (app/services/container_status.py — seit 2026-07-23
  ein eigenes Modul, kein Import des HTML-Generators generate_dashboard.py mehr)

Schnittstelle:
    collect() -> dict   # komplettes Dashboard-Payload, crasht nie (Teilfehler
                        # werden geloggt und als leere Listen/None geliefert)

opt_dashboard_load_many_0815: _collect_projects() lud früher pro Top-Level-Board
einzeln (BoardRepository.load(), exklusiver boards/.lock-Zyklus je Board) — bei
~285 Top-Level-Boards ≈285 Lock-Zyklen pro GET /api/dashboard. Jetzt EIN
Sammel-Read über load_many() (Muster app/api/automat.py::_compute_decisions),
plus ein kurzer TTL-Cache mit Single-Flight (Muster app/api/fragen.py) um den
ganzen Payload (Projekte + Container). Semantik-Entscheid (bewusst, wie beim
load_many-Vorbild in automat.py): ein Lock-Timeout degradiert nicht mehr pro
Board (proj["load_error"]), sondern lässt den GANZEN Request fehlschlagen
(500 über die bestehende except-Klausel in app/api/dashboard.py) — bei EINEM
Lock-Zyklus statt 285 ist die Timeout-Wahrscheinlichkeit ohnehin drastisch
kleiner, ein Teilausfall pro Board ist mit einem Sammel-Read nicht mehr
sauber abbildbar (kaputte/fehlende einzelne Boards liefern weiterhin None,
das bleibt wie zuvor 0 Karten statt Fehler).
"""
import logging
from datetime import datetime, timezone

from app.services import container_status
from app.services.board_service import _get_parents
from app.services.ttl_cache import TTLCache
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository
from constants import CATEGORIES, STATUSES

log = logging.getLogger("dashboard.services.dashboard")

_manifest = ManifestRepository()
_boards = BoardRepository()

_cache = TTLCache(ttl_seconds=20.0)  # kurz genug für frische Zahlen, lang genug gegen Poll-Bursts

# Manifest-Felder, die 1:1 in die Projekt-Kachel übernommen werden
_PROJECT_FIELDS = (
    "id", "name", "description", "category", "color", "icon",
    "seq_id", "tags", "cover_photo", "created_at", "updated_at",
    "last_activity",
    # status — Lebenszyklus-Stand des Projekts (entwurf/in_bearbeitung/blockiert/
    # pausiert/abgeschlossen/archiviert, s. constants.STATUSES), orthogonal zu category
    "status",
    # Eisenhower-Priorisierung pro Projekt (q1..q4 | None) — zentral im Manifest,
    # synchron für Dashboard-Übersicht und Priority Widget.
    "eisenhower",
    # archived (bool) — True blendet das Projekt aus der Desktop-Übersicht aus
    # (verbergen ohne löschen, reversibel). Toggle "🗄 Archiv anzeigen" macht es sichtbar.
    "archived",
    # auto (bool) — Freigabe für den Kanban-Automaten (autonome Weiterentwicklung).
    # In der Eisenhower-Übersicht als 4-Status-Schalter pro Kachel bedienbar/sichtbar
    # (aus/an per Klick; „alle erledigt" abgeleitet aus counts, „Entscheidung nötig"
    # aus /api/automat/decisions). Schreibpfad: PATCH /boards/<id> {auto:…}.
    "auto",
    # type — z.B. "idea" (Foto-/Schnellideen). Frontend bietet "Ordner mitlöschen" (purge)
    # NUR für Ideen an; echte Projekte werden nur aus dem Dashboard entfernt (Ordner bleibt).
    "type",
)


def _count_columns(board_data: dict | None) -> dict:
    """Karten pro Standard-Spalte zählen (Parität zu countByColumn im alten JS:
    nackte Länge der cards-Liste, Spalten-Zuordnung über col.id)."""
    counts = {"backlog": 0, "in_progress": 0, "done": 0}
    if not board_data:
        return counts
    for col in board_data.get("columns") or []:
        cid = col.get("id")
        if cid in counts:
            cards = col.get("cards")
            counts[cid] = len(cards) if isinstance(cards, list) else 0
    return counts


# Meta-Karten, die zwar in einer Spalte liegen, aber keine Arbeit für den Kanban-Automaten
# sind (gleiche Liste wie SKIP_CARD_IDS in dedup_finder.py / kanban-automat/automat_lib.py).
# `claudemd-description` ist die Projektbeschreibung — sie wird auf der Projektseite gar nicht
# als Karte angezeigt, sondern im Projekt-Kopf.
_AUTOMAT_SKIP_CARD_IDS = {"claudemd-description"}


def _count_automat_open(board_data: dict | None) -> int:
    """Karten, die der Kanban-Automat noch abarbeiten würde (Backlog + In Arbeit).

    Basis für den Auto-Entwicklungs-Status („🤖 AN" vs. „✅ abgeschlossen") in der
    Projektliste UND auf der Projektseite. Bewusst getrennt von `counts`: `counts` sind die
    ANGEZEIGTEN Kartenzahlen (📥/🔧/✅) und dürfen sich nicht ändern, während hier die
    Meta-Karten rausfallen. Ohne diese Trennung stand jedes leergearbeitete Projekt weiter
    auf „AN", nur weil die CLAUDE.md-Beschreibungskarte im Backlog liegt (Entscheidung 06.08.26).
    """
    if not board_data:
        return 0
    n = 0
    for col in board_data.get("columns") or []:
        if col.get("id") in ("backlog", "in_progress"):
            cards = col.get("cards")
            if isinstance(cards, list):
                n += sum(1 for c in cards if c.get("id") not in _AUTOMAT_SKIP_CARD_IDS)
    return n


def _count_attachments(board_data: dict | None) -> int:
    """Datei-Anhänge zählen: Board-Ebene + alle Karten (für 📎N auf der Kachel)."""
    if not board_data:
        return 0
    n = len(board_data.get("attachments") or [])
    for col in board_data.get("columns") or []:
        for card in col.get("cards") or []:
            n += len(card.get("attachments") or [])
    return n


def _collect_projects() -> list[dict]:
    """Top-Level-Boards aus dem Manifest mit sub_count + Karten-Zählung.

    Lädt alle Top-Level-Boards in EINEM Sammel-Read (load_many(), ein
    boards/.lock-Zyklus) statt vorher pro Board einzeln — s. Modul-Docstring
    opt_dashboard_load_many_0815.
    """
    manifest = _manifest.load()
    all_boards = manifest.get("boards", [])

    sub_counts: dict[str, int] = {}
    for b in all_boards:
        for pid in _get_parents(b):
            sub_counts[pid] = sub_counts.get(pid, 0) + 1

    top_level = [b for b in all_boards if not _get_parents(b) and b.get("id")]
    bids = [b["id"] for b in top_level]
    boards_by_id = _boards.load_many(bids, inject_claude_md=False)

    projects = []
    for b in top_level:
        bid = b["id"]
        proj = {k: b.get(k) for k in _PROJECT_FIELDS}
        proj["sub_count"] = sub_counts.get(bid, 0)

        bdata = boards_by_id.get(bid)
        if bdata is None:
            log.debug("Dashboard: kein/kaputtes Board-File für %r — Zählung = 0", bid)

        counts = _count_columns(bdata)
        proj["counts"] = counts
        proj["automat_open"] = _count_automat_open(bdata)   # Basis für den Auto-Status
        proj["total_cards"] = sum(counts.values())
        proj["att_count"] = _count_attachments(bdata)
        projects.append(proj)

    log.debug("Dashboard: %d Top-Level-Projekte (von %d Boards), sub_counts=%s",
              len(projects), len(all_boards), sub_counts)
    return projects


def _collect_containers() -> dict:
    """Podman-Status + bekannte Services + Auto-Detect.

    Datensammlung liegt in app/services/container_status.py (seit 2026-07-23
    aus generate_dashboard.py herausgelöst). Liefert bei Fehlern leere
    Strukturen statt zu crashen.
    """
    try:
        running = container_status.get_running_containers()   # podman ps, timeout 10s
        known = container_status.get_known_containers()
        auto = container_status.detect_auto_containers(running, known)
        services = container_status.collect_services(running)

        log.debug("Dashboard: %d Container laufen, %d bekannte Services, %d auto-detected",
                  len(running), len(services), len(auto))
        return {
            "running": sorted(running.keys()),
            "services": services,
            "auto_detected": auto,
        }
    except FileNotFoundError:
        # `podman`-Binary fehlt — bei Docker-basierten Fremdinstallationen (docker-compose.yml,
        # ili-api läuft dort als reiner Docker-Container ohne Podman-Host-Zugriff) ist das ein
        # dauerhafter, erwarteter Zustand, kein Fehler: sonst loggt jeder /api/dashboard-Poll
        # (alle paar Sekunden vom Frontend) eine ERROR-Zeile für etwas, das nie behoben wird.
        log.debug("Dashboard: 'podman' nicht installiert — Container-Status bleibt leer "
                  "(erwartet bei Docker-Deployments ohne Podman-Host-Zugriff)")
        return {"running": [], "services": [], "auto_detected": []}
    except Exception as e:
        log.error("Dashboard: Container-Status fehlgeschlagen: %s", e)
        return {"running": [], "services": [], "auto_detected": [], "error": str(e)}


def _collect_uncached() -> dict:
    """Komplettes Dashboard-Payload frisch sammeln (ohne Cache)."""
    log.info("Dashboard-Daten sammeln…")
    projects = _collect_projects()
    containers = _collect_containers()

    online = sum(1 for s in containers["services"] if s.get("status") == "online")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "projects": projects,
        "categories": CATEGORIES,
        "statuses": STATUSES,
        "containers": containers,
        "stats": {
            "projects_total": len(projects),
            "cards_total": sum(p["total_cards"] for p in projects),
            "containers_running": len(containers["running"]),
            "services_online": online,
        },
    }
    log.info("Dashboard-Daten: %d Projekte, %d Karten, %d Container laufen",
             payload["stats"]["projects_total"], payload["stats"]["cards_total"],
             payload["stats"]["containers_running"])
    return payload


def collect() -> dict:
    """Komplettes Dashboard-Payload für GET /api/dashboard.

    Gecacht für 20 Sekunden (Single-Flight via TTLCache) — mehrere Tabs/Reloads
    innerhalb der TTL teilen sich einen Sammel-Read statt je einen auszulösen.
    """
    return _cache.get(_collect_uncached)

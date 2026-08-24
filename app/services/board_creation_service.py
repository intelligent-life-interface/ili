"""Board-ERSTELLUNG — abgetrennt von board_service.py (Lebenszyklus-Phase 1 von 2).

Schnittstelle
-------------
create_board(data)                   -> dict            # klassischer synchroner Weg (fast=True möglich)
create_board_immediate(data)         -> (dict, dict|None)  # <1s Sofort-Antwort + BG-Args für finalize
finalize_board_background(**bg_args) -> None             # BackgroundTask: Namenskorrektur/Vision/Tags/Ideen

Eigene `_boards`/`_manifest`-Singletons (wie board_service.py) — beide zeigen im Betrieb auf
dieselben Dateien unter `boards/` (Repositories locken pro Dateipfad via fcntl, nicht per
Python-Objektidentität, daher unkritisch). Tests patchen bei Bedarf DIESES Moduls Singletons.
Patch/Meta/Delete/Rollup bleiben in board_service.py (Phase 2: laufender Betrieb eines Boards).
"""
import logging
import uuid
from datetime import datetime

from constants import CATEGORIES, PROJEKTE_BASE, CLAUDE_BRIDGE_URL
from project_creator import (_create_project_folder, _correct_project_name,
                             _ensure_project_session,
                             _slugify, _text_tags, _unique_board_id,
                             _vision_tags, _vision_title, generate_idea_cards)

from app.services import claude_client
from app.storage.board_repository import BoardRepository, default_board_data
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.board_creation")


class UnclearNameError(Exception):
    """Ollama hält den Projektnamen für nicht sinnvoll (HTTP 400 mit Spezial-Payload)."""
    def __init__(self, raw_name: str):
        self.raw_name = raw_name
        super().__init__(f"'{raw_name}' ergibt keinen erkennbaren Projektnamen")


def _validate_board_id(board_id: str) -> None:
    if "/" in board_id or "\\" in board_id or board_id.startswith("."):
        raise ValueError("Ungültige Board-ID")

_boards = BoardRepository()
_manifest = ManifestRepository()


def _parent_context(parent_ids: list) -> str:
    """Baut aus den Manifest-Einträgen der Eltern-Boards einen kompakten Kontext-String.

    Für die KI-Schritte bei Unterprojekt-Erstellung (Namenskorrektur, Tags, CLAUDE.md,
    Ideen-Karten): "Name — Beschreibung (Tags: …)". Beschreibung auf 400 Zeichen gekürzt,
    damit der Prompt klein bleibt. Leerer String, wenn kein Elternteil gefunden wird.
    """
    if not parent_ids:
        return ""
    parts = []
    try:
        boards = _manifest.load().get("boards", [])
        for pid in parent_ids:
            entry = next((b for b in boards if b.get("id") == pid), None)
            if not entry:
                log.debug("Eltern-Kontext: Board %r nicht im Manifest", pid)
                continue
            desc = " ".join((entry.get("description") or "").split())[:400]
            tags = ", ".join(entry.get("tags") or [])
            part = entry.get("name") or pid
            if desc:
                part += f" — {desc}"
            if tags:
                part += f" (Tags: {tags})"
            parts.append(part)
    except Exception as e:
        log.warning("Eltern-Kontext konnte nicht geladen werden (%s): %s", parent_ids, e)
    return "; ".join(parts)


def _manifest_entry(board_id: str) -> dict | None:
    """Manifest-Eintrag zu einer Board-ID (oder None)."""
    for e in _manifest.load().get("boards", []):
        if e.get("id") == board_id:
            return e
    return None


def create_board(data: dict) -> dict:
    """Neues Board + Projektordner + Manifest-Eintrag (Semantik aus _handle_boards_create).

    fast=true überspringt ALLE Ollama-Schritte (Namenskorrektur + Tags) → <1s, Name exakt.

    Raises:
        ValueError, UnclearNameError, FileExistsError
    """
    raw_name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    board_id = (data.get("id") or "").strip()
    fast = bool(data.get("fast"))

    if not raw_name:
        raise ValueError("Feld 'name' ist Pflicht")

    # parent_ids früh parsen: Bei Unterprojekten geht der Mutterprojekt-Kontext in ALLE
    # KI-Schritte (Namenskorrektur, Tags, CLAUDE.md, Ideen-Karten), damit mehrdeutige
    # Namen im Thema des Mutterprojekts interpretiert werden statt frei ausgedeutet
    # (Vorfall 07.07.2026: "Geschichte" unter dem ADHS-Spiel wurde ohne Kontext zum
    # Schweizer-Geschichte-Bildungsprojekt erdichtet).
    parent_ids = data.get("parent_ids", [])
    if not isinstance(parent_ids, list):
        parent_ids = [parent_ids] if parent_ids else []
    parent_context = _parent_context(parent_ids)
    if parent_context:
        log.info("Unterprojekt von %s — Eltern-Kontext (%d Zeichen) geht in die KI-Schritte",
                 parent_ids, len(parent_context))

    if fast:
        name, is_meaningful = raw_name, True
        log.info("Projektname (fast, ohne Ollama): %r", name)
    else:
        name, is_meaningful = (_correct_project_name(raw_name, parent_context=parent_context)
                               if raw_name else (raw_name, True))
        log.info("Projektname: %r → %r (sinnvoll=%s)", raw_name, name, is_meaningful)
    if not is_meaningful:
        raise UnclearNameError(raw_name)

    if not board_id:
        slug = _slugify(name)
        board_id = _unique_board_id(slug) if slug else _unique_board_id(_slugify(raw_name))
    else:
        _validate_board_id(board_id)

    if _boards.exists(board_id):
        raise FileExistsError(f"Board '{board_id}' existiert bereits")

    tags: list = []
    if not fast and (description or name):
        log.info("Ollama generiert Tags …")
        tags = _text_tags(name, description, parent_context=parent_context)

    try:
        _create_project_folder(name=name, board_id=board_id, description=description,
                               tags=tags, is_idea=False, fast=fast,
                               parent_context=parent_context)
    except Exception as e:
        log.error("Projektordner anlegen fehlgeschlagen: %s", e)

    board_data = default_board_data()
    # NEU: Claude-Abo brainstormt 5–8 Ideen-Karten → Backlog (best-effort, nie blockierend).
    # fast=true (z.B. Priority Widget +Knopf) überspringt den Schritt.
    if not fast:
        try:
            ideas = generate_idea_cards(name, description, tags,
                                        parent_context=parent_context)
            if ideas:
                backlog = next((c for c in board_data["columns"] if c["id"] == "backlog"),
                               board_data["columns"][0])
                backlog["cards"].extend(ideas)
                log.info("Board '%s': %d Ideen-Karten via Claude-Abo eingefügt", board_id, len(ideas))
        except Exception as e:
            log.warning("Ideen-Brainstorm übersprungen (%s): %s", board_id, e)

    try:
        _boards.create(board_id, board_data, sync_claude_md=False)
        log.info("Board-Datei angelegt: %s", _boards.board_path(board_id))
    except FileExistsError:
        raise FileExistsError(f"Board '{board_id}' existiert bereits")

    # Auto-Kategorie für neue Projekte (User kann jederzeit per Schnellknopf ändern).
    # Bewusst OHNE Priorität (eisenhower bleibt leer) → neue Projekte zeigen sich als
    # 📥 'noch nicht einsortiert' im Eisenhower-Modus → man sieht sofort, was neu ist.
    # use_ai nur im non-fast-Pfad (dort läuft eh schon Ollama für Tags); fast bleibt instant.
    category = (data.get("category") or "").strip()
    if not category:
        try:
            from auto_categorize import categorize_one
            category = categorize_one(name, tags, description, use_ai=not fast)
        except Exception as e:
            log.warning("Auto-Kategorie übersprungen (%s): %s", board_id, e)

    entry: dict = {
        "id": board_id,
        "name": name,
        "description": description,
        "color": data.get("color") or (CATEGORIES.get(category, {}).get("color") if category else None) or "#4A9EFF",
        "icon": data.get("icon", "📋"),
        # New boards default to auto-development (Entscheid 2026-08-16): without this,
        # cards on new boards were never picked up by the kanban-automat.
        "auto": bool(data.get("auto", True)),
    }
    if category:
        entry["category"] = category
    if tags:
        entry["tags"] = tags
    if parent_ids:
        entry["parent_ids"] = parent_ids

    _manifest.update(lambda m: m["boards"].append(entry) or None)
    log.info("Board '%s' angelegt, tags=%s", board_id, tags)
    return {"status": "ok", "id": board_id, "name": name, "tags": tags}


def create_board_immediate(data: dict) -> tuple[dict, dict | None]:
    """Sync-Teil des vereinten Erstell-Flows (Formular ODER Foto): Board + Manifest
    SOFORT mit fester ID anlegen → 201 in <1s. Die schwere KI (Namenskorrektur,
    Tags, Ideen-Karten = "das Kanban", CLAUDE.md, ggf. Foto-Vision) läuft danach als
    BackgroundTask (finalize_board_background).

    Anti-Doppelprojekt: Die ID kommt idealerweise vom Client (projekt.html schreibt sie
    direkt) und ist der Idempotenz-Schlüssel. Kommt nach einem Client-Timeout derselbe
    Request nochmal, existiert das Board bereits → wir geben es zurück, statt ein
    zweites anzulegen.

    Returns:
        (response, bg_args) — bg_args=None, wenn das Board schon existierte (Idempotenz,
        also KEINE weitere Hintergrund-Analyse anstossen).
    Raises:
        ValueError: weder Name noch Foto angegeben / ungültige ID.
    """
    raw_name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    board_id = (data.get("id") or "").strip()
    photo_b64 = (data.get("photo") or "").strip()
    note = (data.get("note") or "").strip()

    gps_lat = data.get("gps_lat")
    gps_lon = data.get("gps_lon")
    gps_alt = data.get("gps_alt")
    gps_direction = data.get("gps_direction")
    gps_accuracy = data.get("gps_accuracy")
    has_gps = gps_lat is not None and gps_lon is not None

    parent_ids = data.get("parent_ids", [])
    if not isinstance(parent_ids, list):
        parent_ids = [parent_ids] if parent_ids else []

    if not raw_name and not photo_b64:
        raise ValueError("Feld 'name' ist Pflicht (oder ein Foto mitgeben)")

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    # ── Board-ID: bevorzugt die vom Client vergebene (Idempotenz gegen Timeout-Doppel) ──
    if board_id:
        _validate_board_id(board_id)
    else:
        slug = _slugify(raw_name) if raw_name else ""
        board_id = _unique_board_id(slug or f"projekt-{ts}")

    # Idempotenz: existiert das Board schon (Retry nach Timeout), NICHT nochmal anlegen.
    if _boards.exists(board_id):
        existing = _manifest_entry(board_id) or {}
        log.info("create_board_immediate: %r existiert bereits → Idempotenz, kein Duplikat", board_id)
        return ({"status": "exists", "id": board_id,
                 "name": existing.get("name") or raw_name or board_id,
                 "analyzing": bool(existing.get("analyzing"))}, None)

    # ── Foto(s) (optional) SOFORT speichern — mehrere möglich ──
    # Neu: Feld `photos` (Liste von Base64). `photo` (Einzel) bleibt als Fallback erhalten.
    photos_b64 = data.get("photos")
    if not isinstance(photos_b64, list):
        photos_b64 = [photo_b64] if photo_b64 else []
    photo_urls: list[str] = []
    first_photo_bytes, first_photo_filename = b"", ""
    if photos_b64:
        from app.services.photo_service import decode_and_save_photo
        gps = ((gps_lat, gps_lon, gps_alt, gps_direction) if has_gps else None)
        for i, pb in enumerate(photos_b64):
            if not (pb or "").strip():
                continue
            url, fname, pbytes = decode_and_save_photo(pb, ts, gps=gps, suffix=f"_{i}")
            if url:
                photo_urls.append(url)
                if not first_photo_bytes:
                    first_photo_bytes, first_photo_filename = pbytes, fname

    temp_title = raw_name or f"Projekt {now.strftime('%d.%m.%Y %H:%M')}"

    # ── Board SOFORT anlegen (Default-Spalten; je Foto eine Inspiration-Karte, Notiz auf der 1.) ──
    board_data = default_board_data()
    if photo_urls:
        for idx, url in enumerate(photo_urls):
            board_data["columns"][0]["cards"].append({
                "title": "📸 Inspiration",
                "desc": (note + "\n\n" if (note and idx == 0) else "") + "⏳ Wird analysiert…",
                "label": "#b794f4",
                "photo_url": url,
            })
    elif note:
        board_data["columns"][0]["cards"].insert(0, {
            "title": "📝 Notiz",
            "desc": note + "\n\n⏳ Wird analysiert…",
            "label": "#b794f4",
        })

    try:
        _boards.create(board_id, board_data, sync_claude_md=False)
    except FileExistsError:
        existing = _manifest_entry(board_id) or {}
        return ({"status": "exists", "id": board_id,
                 "name": existing.get("name") or temp_title, "analyzing": False}, None)

    # ── Manifest-Eintrag SOFORT (analyzing:True → UI zeigt "wird analysiert") ──
    entry: dict = {
        "id": board_id,
        "name": temp_title,
        "description": description,
        "color": "#b794f4" if photo_urls else "#4A9EFF",
        "icon": "📸" if photo_urls else "📋",
        "created_at": now.isoformat(timespec="seconds"),
        "analyzing": True,
        # New boards default to auto-development (Entscheid 2026-08-16), same as create_board().
        "auto": bool(data.get("auto", True)),
    }
    if has_gps:
        entry["gps"] = {
            "lat": float(gps_lat), "lon": float(gps_lon),
            "alt": float(gps_alt) if gps_alt is not None else None,
            "direction": float(gps_direction) if gps_direction is not None else None,
            "accuracy": float(gps_accuracy) if gps_accuracy is not None else None,
        }
    if photo_urls:
        entry["cover_photo"] = photo_urls[0]
    if parent_ids:
        entry["parent_ids"] = parent_ids
    _manifest.update(lambda m: m["boards"].append(entry) or None)

    # Create the project folder + empty tmux session synchronously: the terminal
    # panel opens right after the 201, long before the background finalize creates
    # the folder — without the folder, tmux-project.sh falls back to $HOME and the
    # tmux session stays anchored there forever (race observed 2026-08-07). The
    # background finalize later fills the folder (CLAUDE.md etc.), mkdir is exist_ok.
    try:
        project_path = PROJEKTE_BASE / board_id
        project_path.mkdir(parents=True, exist_ok=True)
        log.info("Projektordner vorab angelegt: %s", project_path)
        _ensure_project_session(board_id, project_path)
    except Exception:
        log.warning("create_board_immediate: Vorab-Ordner/Session fehlgeschlagen (ignoriert)",
                    exc_info=True)

    log.info("Board %r sofort angelegt (analyzing, %d foto(s)) — KI läuft im Hintergrund",
             board_id, len(photo_urls))
    response = {"status": "ok", "id": board_id, "name": temp_title, "analyzing": True}
    # Für Vision/Ordner reicht das erste Foto (repräsentativ); die weiteren sind bereits
    # gespeichert und als Karten sichtbar. Hält die KI-Kosten pro Erstellung beschränkt.
    bg_args = {
        "board_id": board_id, "raw_name": raw_name, "description": description,
        "note": note, "photo_bytes": first_photo_bytes, "photo_filename": first_photo_filename,
        "parent_ids": parent_ids,
    }
    return response, bg_args


def _ki_failure_card(bridge_ok: bool) -> dict:
    """Red marker card for the backlog when the KI preparation produced nothing."""
    if bridge_ok:
        reason = (f"Die Claude-Bridge ({CLAUDE_BRIDGE_URL}) war erreichbar, hat aber weder Tags "
                  "noch Ideen-Karten geliefert. Ist Claude im Terminal-Container eingeloggt "
                  "(CLAUDE_CODE_OAUTH_TOKEN oder ANTHROPIC_API_KEY)? Log: `docker logs ili-terminal`.")
    else:
        reason = (f"Die Claude-Bridge ({CLAUDE_BRIDGE_URL}) ist nicht erreichbar. Läuft der "
                  "Terminal-Container (docker-compose.terminal.yml)? Log: `docker logs ili-terminal`.")
    return {
        "id":       f"kifail_{uuid.uuid4().hex[:10]}",
        "title":    "⚠️ KI-Vorbereitung fehlgeschlagen",
        "desc":     reason + " Danach das Projekt neu anlegen oder diese Karte löschen.",
        "label":    "#e5534b",
        "priority": "hoch",
    }


def finalize_board_background(board_id: str, raw_name: str, description: str, note: str,
                             photo_bytes: bytes, photo_filename: str,
                             parent_ids: list) -> None:
    """BG-Teil des vereinten Erstell-Flows: Namenskorrektur/Vision, Tags, Projektordner,
    Ideen-Karten (das "Kanban"), Auto-Kategorie → Board + Manifest aktualisieren und
    `analyzing` entfernen. Best-effort, jeder Schritt einzeln abgesichert (nie Crash)."""
    log.info("[BG] Finalisiere Board %r (name=%r, foto=%s)", board_id, raw_name, bool(photo_bytes))
    # Fail loudly, not silently: every KI step below degrades to a bare template when the
    # Claude bridge is down. Without a visible marker the board just looks "empty".
    bridge_ok = claude_client.is_reachable()
    if not bridge_ok:
        log.error("[BG] Claude bridge unreachable (%s) — board %r will stay an empty template",
                  CLAUDE_BRIDGE_URL, board_id)
    try:
        parent_context = _parent_context(parent_ids)

        # 1. Name: Formular-Name korrigieren, sonst aus Foto (Vision), sonst Fallback.
        name = raw_name
        if raw_name:
            try:
                corrected, ok = _correct_project_name(raw_name, parent_context=parent_context)
                if ok and corrected:
                    name = corrected
            except Exception as e:
                log.warning("[BG] Namenskorrektur übersprungen (%r): %s", board_id, e)
        elif photo_bytes:
            try:
                name = _vision_title(photo_bytes, note) or name
            except Exception as e:
                log.warning("[BG] Vision-Titel übersprungen (%r): %s", board_id, e)
        if not name:
            name = raw_name or f"Projekt {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        # 2. Tags (Text + ggf. Foto-Vision), Duplikate raus.
        tags: list = []
        try:
            tags = list(_text_tags(name, description or note, parent_context=parent_context) or [])
        except Exception as e:
            log.warning("[BG] Text-Tags übersprungen (%r): %s", board_id, e)
        if photo_bytes:
            try:
                for t in (_vision_tags(photo_bytes, note) or []):
                    if t not in tags:
                        tags.append(t)
            except Exception as e:
                log.warning("[BG] Vision-Tags übersprungen (%r): %s", board_id, e)

        # 3. Projektordner (CLAUDE.md + TAGS.md + ggf. fotos/).
        try:
            _create_project_folder(name=name, board_id=board_id,
                                   description=description or note, tags=tags, is_idea=False,
                                   photo_bytes=photo_bytes or None,
                                   photo_filename=photo_filename or None,
                                   parent_context=parent_context)
        except Exception as e:
            log.error("[BG] Projektordner fehlgeschlagen (%r): %s", board_id, e)

        # 4. Ideen-Karten = "das Kanban" via Claude-Abo brainstormen.
        ideas: list = []
        try:
            ideas = generate_idea_cards(name, description or note, tags,
                                        parent_context=parent_context) or []
        except Exception as e:
            log.warning("[BG] Ideen-Brainstorm übersprungen (%r): %s", board_id, e)

        # 5. Board aktualisieren: Titel, Ideen → Backlog, Inspiration/Notiz auf "analysiert".
        #    Bei mehreren Foto-Karten kommt die Notiz nur auf die ERSTE.
        note_placed = [False]
        ki_failed = (not bridge_ok) or (not tags and not ideas)
        if ki_failed:
            log.error("[BG] KI preparation failed for %r (bridge_ok=%s, tags=%d, ideas=%d)",
                      board_id, bridge_ok, len(tags), len(ideas))
        def update_board(bd):
            bd["title"] = name
            cols = bd.get("columns", [])
            if cols:
                backlog = next((c for c in cols if c.get("id") == "backlog"), cols[0])
                if ideas:
                    backlog["cards"].extend(ideas)
                if ki_failed:
                    backlog["cards"].insert(0, _ki_failure_card(bridge_ok))
            tag_line = f"🏷️ Tags: {', '.join(tags)}" if tags else "✓ Analysiert"
            for col in cols:
                for card in col.get("cards", []):
                    if card.get("title") in ("📸 Inspiration", "📝 Notiz"):
                        prefix = ""
                        if note and not note_placed[0]:
                            prefix = note + "\n\n"
                            note_placed[0] = True
                        card["desc"] = prefix + tag_line
        try:
            _boards.update(board_id, update_board, sync_claude_md=False)
        except FileNotFoundError:
            log.warning("[BG] Board %r verschwunden — Board-Update übersprungen", board_id)

        # 6. Auto-Kategorie (async → Ollama-Fallback erlaubt).
        category = ""
        try:
            from auto_categorize import categorize_one
            category = categorize_one(name, tags, description or note, use_ai=True)
        except Exception as e:
            log.warning("[BG] Auto-Kategorie übersprungen (%r): %s", board_id, e)

        # 7. Manifest: Name/Tags/Kategorie/Farbe setzen, analyzing entfernen.
        def update_manifest(m):
            for e in m["boards"]:
                if e.get("id") == board_id:
                    e["name"] = name
                    e.pop("analyzing", None)
                    if tags:
                        e["tags"] = tags
                    if category and not e.get("category"):
                        e["category"] = category
                        e["color"] = CATEGORIES.get(category, {}).get("color", e.get("color"))
                    break
        _manifest.update(update_manifest)
        log.info("[BG] Board %r finalisiert → '%s' tags=%s cat=%s ideen=%d",
                 board_id, name, tags, category, len(ideas))
    except Exception as e:
        log.error("[BG] Finalisierung fehlgeschlagen für %r: %s", board_id, e, exc_info=True)

"""Service: Direktlinks zum (Unter-)Projekt für die Projekt-Ansicht.

Liefert pro Board die Sprung-Ziele für den Kopf von project.html:
  * webapp      — laufende Web-App (<sub>.intranet.DOMAIN), gemappt über web-adressen.json
  * filebrowser — Code-Ordner im Filebrowser (root /srv ist auf ~/ gemountet → /files/<rel-zu-home>)
  * datadir     — der data/-Unterordner im Filebrowser (nur wenn vorhanden) — Direktsprung zu
                  DuckDB/SQLite/Exporten, ohne erst durch den Code-Ordner zu navigieren
  * github      — git remote origin (falls vorhanden), normalisiert auf eine https-URL
  * claudemd    — die zum Arbeitsordner passende CLAUDE.md, direkt im Filebrowser geöffnet

Der Arbeitsordner kommt aus ``projterm_prepare.resolve_work_dir(slug)`` — exakt der Ordner,
in dem auch die Terminal-tmux-Session (Claude Code) dieses Boards läuft. Dadurch zeigt der
Link immer auf das tatsächlich bearbeitete (Unter-)Projekt: Board ``bohrprofile-3d`` mit
``code_dir=~/containers/bohr3d`` → Links zeigen auf ``bohr3d``, nicht auf das Stub.
"""
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import projterm_prepare  # Dashboard-Dir liegt via app.main auf sys.path
from app.storage.manifest_repository import ManifestRepository

log = logging.getLogger("dashboard.services.project_links")

HOME = Path.home()
WEB_ADRESSEN_JSON = Path(__file__).resolve().parents[2] / "html" / "web-adressen.json"
_DOMAIN = os.environ.get("DASHBOARD_DOMAIN", "yourdomain.example")
INTRANET_TPL = f"https://{{sub}}.intranet.{_DOMAIN}"
FILEBROWSER_BASE = f"https://filebrowser.intranet.{_DOMAIN}/files"


_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _norm(s: str) -> str:
    """Schlüssel-Normalisierung fürs Mapping: klein, Umlaute transliteriert,
    ohne Leer-/Sonderzeichen — so matcht Name 'Kursübersicht' den Slug 'kursuebersicht'."""
    return "".join(c for c in (s or "").lower().translate(_UMLAUTE) if c.isalnum())


def _load_sub_map() -> dict[str, str]:
    """Mapping <normalisierter Schlüssel> → Subdomain aus web-adressen.json.

    Schlüssel sind die Subdomain selbst UND der normalisierte Anzeige-Name — so findet
    z.B. Board/Ordner 'immobilienverwaltung' die Subdomain 'immo' (Name 'Immobilienverwaltung').
    """
    try:
        data = json.loads(WEB_ADRESSEN_JSON.read_text("utf-8"))
    except Exception as e:
        log.warning("web-adressen.json nicht lesbar (%s): %s", WEB_ADRESSEN_JSON, e)
        return {}
    mapping: dict[str, str] = {}
    for cat in data.get("categories", []):
        for it in cat.get("items", []):
            sub = (it.get("sub") or "").strip()
            if not sub:
                continue
            mapping.setdefault(_norm(sub), sub)
            name = it.get("name") or ""
            if name:
                mapping.setdefault(_norm(name), sub)
    return mapping


def _filebrowser_url(p: Path) -> str | None:
    """Host-Pfad → Filebrowser-URL. Nur Pfade unterhalb von ~/ sind erreichbar
    (Container mountet $HOME nach /srv, Filebrowser-root = /srv)."""
    try:
        rel = p.resolve().relative_to(HOME)
    except (ValueError, OSError) as e:
        log.debug("Pfad %s nicht unter HOME, kein Filebrowser-Link: %s", p, e)
        return None
    return f"{FILEBROWSER_BASE}/{rel}".rstrip("/")


_LINKS_URL_RE = re.compile(r"<(https?://[^\s>]+)>")


def _artefakt_links(work_dir: Path) -> list[str]:
    """Aus den Terminal-Protokollen gesammelte Links des Projekts (LINKS.md, erzeugt
    vom Projekt 'projekt-artefakte'). Erkennt sowohl das alte Bullet-Format ('- <url>')
    als auch das seit 2026-07-27 von write_links.py generierte, nach Typ gruppierte
    Tabellenformat ('| Host | <url> |') — beide wrappen die URL in spitzen Klammern,
    ein reiner Zeilen-Suchpattern auf '<...>' deckt beide ab. Leere Liste, wenn keine."""
    f = work_dir / "LINKS.md"
    if not f.exists():
        return []
    urls: list[str] = []
    try:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            m = _LINKS_URL_RE.search(line)
            if m:
                urls.append(m.group(1))
    except OSError as e:
        log.debug("LINKS.md nicht lesbar (%s): %s", f, e)
    return urls


def _github_url(work_dir: Path) -> str | None:
    """git remote 'origin' des Arbeitsordners → https-URL (oder None, wenn kein Remote)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(work_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=4,
        )
    except Exception as e:
        log.debug("git remote get-url fehlgeschlagen (%s): %s", work_dir, e)
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    url = out.stdout.strip()
    # git@github.com:Toa1984/x.git → https://github.com/Toa1984/x
    if url.startswith("git@"):
        url = "https://" + url.split("@", 1)[1].replace(":", "/", 1)
    if url.endswith(".git"):
        url = url[:-4]
    return url


def _match_sub(slug: str, work_dir: Path | None, sub_map: dict[str, str]) -> str | None:
    """Subdomain für ein Board finden: passt Board-Slug oder Ordnername (normalisiert) zu
    einem aktiven <sub>.intranet.DOMAIN? (z.B. Board 'bohrprofile-3d' → Ordner 'bohr3d'
    → sub 'bohr3d'; 'immobilienverwaltung' → Name-Match → sub 'immo'). Sonst None."""
    candidates = [slug]
    if work_dir is not None:
        candidates.append(work_dir.name)
    for c in candidates:
        sub = sub_map.get(_norm(c))
        if sub:
            return sub
    return None


def build_links(slug: str) -> dict:
    """Alle Direktlinks für ein Board/(Unter-)Projekt zusammenstellen.

    Rückgabe: {board_id, work_dir, links:{webapp, filebrowser, datadir, github, claudemd}} —
    nicht ermittelbare Ziele sind None (Frontend blendet sie aus).
    """
    work_dir = projterm_prepare.resolve_work_dir(slug)
    sub_map = _load_sub_map()
    sub = _match_sub(slug, work_dir, sub_map)
    links: dict[str, str | None] = {
        "webapp": INTRANET_TPL.format(sub=sub) if sub else None,
        # Eintrag des Dienstes auf der Service-/Web-Adressen-Übersicht (Projekt → Service)
        "services": f"/services.html#svc-{sub}" if sub else None,
        "filebrowser": None,
        "datadir": None,
        "github": None,
        "claudemd": None,
    }
    work_dir_str = None
    artefakt_links: list[str] = []
    if work_dir is not None:
        work_dir_str = str(work_dir)
        links["filebrowser"] = _filebrowser_url(work_dir)
        # data/-Unterordner nur verlinken, wenn er wirklich existiert (sonst toter Link)
        data_dir = work_dir / "data"
        if data_dir.is_dir():
            links["datadir"] = _filebrowser_url(data_dir)
        links["github"] = _github_url(work_dir)
        claude_md = work_dir / "CLAUDE.md"
        if claude_md.exists():
            links["claudemd"] = _filebrowser_url(claude_md)
        artefakt_links = _artefakt_links(work_dir)
    log.debug("build_links(%s): work_dir=%s links=%s artefakt_links=%d",
              slug, work_dir_str, links, len(artefakt_links))
    return {"board_id": slug, "work_dir": work_dir_str, "links": links,
            "artefakt_links": artefakt_links}


# Reverse-Mapping Service → Projekt (Subdomain → Board-Slug). Mit kleinem TTL-Cache, weil
# es über alle Boards iteriert (resolve_work_dir liest CLAUDE.md-Längen) und von der
# Services-/Web-Adressen-Seite bei jedem Laden geholt wird.
_SVC_MAP_CACHE: dict = {"ts": 0.0, "map": None}
_SVC_MAP_TTL = 120.0  # Sekunden
_manifest_repo = ManifestRepository()


def _board_ids() -> list[str]:
    """Alle Board-Slugs aus boards/manifest.json (Liste unter 'boards')."""
    manifest = _manifest_repo.load()
    out = []
    for b in manifest.get("boards", []):
        bid = (b.get("id") or "").strip() if isinstance(b, dict) else ""
        if bid:
            out.append(bid)
    return out


def service_project_map() -> dict[str, str]:
    """Mapping <Subdomain> → <Board-Slug>: welcher Dienst gehört zu welchem Projekt?
    Umkehrung von _match_sub über alle Boards. Erstes Board pro Subdomain gewinnt."""
    import time
    now = time.monotonic()
    if _SVC_MAP_CACHE["map"] is not None and (now - _SVC_MAP_CACHE["ts"]) < _SVC_MAP_TTL:
        return _SVC_MAP_CACHE["map"]
    sub_map = _load_sub_map()
    result: dict[str, str] = {}
    for slug in _board_ids():
        try:
            sub = _match_sub(slug, projterm_prepare.resolve_work_dir(slug), sub_map)
        except Exception as e:
            log.debug("service_project_map: resolve %s fehlgeschlagen: %s", slug, e)
            continue
        if sub and sub not in result:
            result[sub] = slug
    _SVC_MAP_CACHE["map"] = result
    _SVC_MAP_CACHE["ts"] = now
    log.debug("service_project_map: %d Zuordnungen", len(result))
    return result

"""Dateiliste + Markdown-Rendering fürs 📂-Datei-Panel in project.html.

* ``list_files(slug)``   — Top-Level-Einträge des Projekt-Arbeitsordners
  (work_dir via ``projterm_prepare.resolve_work_dir``, wie project_links),
  mit Filebrowser-URL pro Eintrag; ``.md``-Dateien sind zusätzlich "viewable"
  (gerenderte Ansicht via ``render_markdown``).
* ``render_markdown(slug, rel)`` — rendert eine ``.md``-Datei des Projekts zu
  HTML (python-markdown, tables/fenced_code) — Links darin sind anklickbar.

Sicherheit: ``rel`` wird gegen den aufgelösten work_dir geprüft (kein Traversal,
keine Symlinks nach draussen), nur ``.md``, Grössen-Limit.
"""
import logging
import os
from pathlib import Path

import markdown

from app.services import project_links as links_svc

log = logging.getLogger("dashboard.services.project_files")

# Rauschen, das in der Liste niemanden interessiert
SKIP_NAMES = {".git", "__pycache__", "node_modules", "venv", ".venv", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".db-shm", ".db-wal")
MAX_MD_BYTES = 2 * 1024 * 1024


def _work_dir(slug: str) -> Path | None:
    import projterm_prepare
    wd = projterm_prepare.resolve_work_dir(slug)
    if wd is None:
        log.info("kein Arbeitsordner für Board '%s'", slug)
    return wd


def _filebrowser_url(p: Path) -> str | None:
    return links_svc._filebrowser_url(p)


def list_files(slug: str) -> dict:
    """{board_id, work_dir, files: [{name, is_dir, size, filebrowser, viewable}]}"""
    wd = _work_dir(slug)
    if wd is None or not wd.is_dir():
        return {"board_id": slug, "work_dir": None, "files": []}
    files = []
    try:
        entries = sorted(wd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        log.error("Arbeitsordner nicht lesbar (%s): %s", wd, e)
        return {"board_id": slug, "work_dir": str(wd), "files": []}
    for p in entries:
        if p.name in SKIP_NAMES or p.name.endswith(SKIP_SUFFIXES):
            continue
        try:
            is_dir = p.is_dir()
            size = 0 if is_dir else p.stat().st_size
        except OSError:
            continue
        files.append({
            "name": p.name,
            "is_dir": is_dir,
            "size": size,
            "filebrowser": _filebrowser_url(p),
            "viewable": (not is_dir) and p.suffix.lower() == ".md",
        })
    log.debug("list_files(%s): %d Einträge in %s", slug, len(files), wd)
    return {"board_id": slug, "work_dir": str(wd), "files": files}


def render_markdown(slug: str, rel: str) -> dict:
    """{board_id, file, html} — wirft ValueError bei ungültigem Pfad."""
    wd = _work_dir(slug)
    if wd is None:
        raise ValueError(f"Kein Arbeitsordner für Board '{slug}'")
    wd = wd.resolve()
    target = (wd / rel).resolve()
    if not str(target).startswith(str(wd) + os.sep):
        log.warning("Traversal-Versuch abgewehrt: slug=%s rel=%r", slug, rel)
        raise ValueError("Pfad ausserhalb des Projektordners")
    if target.suffix.lower() != ".md":
        raise ValueError("Nur .md-Dateien werden gerendert")
    if not target.is_file():
        raise ValueError(f"Datei nicht gefunden: {rel}")
    if target.stat().st_size > MAX_MD_BYTES:
        raise ValueError("Datei zu gross zum Rendern")
    text = target.read_text(encoding="utf-8", errors="replace")
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    log.debug("render_markdown(%s, %s): %d Zeichen → %d HTML", slug, rel, len(text), len(html))
    return {"board_id": slug, "file": rel, "html": html}

"""Dateiliste + Markdown-Rendering fürs 🗂-Datei-Panel in project.html.

* ``list_files(slug, rel="")`` — Einträge EINES Ordners des Projekt-Arbeitsordners
  (work_dir via ``projterm_prepare.resolve_or_create_work_dir``, wie project_links);
  ``rel`` wählt einen Unterordner — das ist die eigentliche "ganzen Ordner sehen"-
  Navigation: jeder Eintrag trägt seinen Pfad relativ zum Arbeitsordner, ``parent``
  ist der Pfad eine Ebene höher (``None`` nur an der Wurzel) fürs Zurück-Navigieren
  im Frontend. ``.md``-Dateien sind zusätzlich "viewable" (gerenderte Ansicht via
  ``render_markdown``).
* ``render_markdown(slug, rel)`` — rendert eine ``.md``-Datei des Projekts (in
  einem beliebigen Unterordner) zu HTML (python-markdown, tables/fenced_code) —
  Links darin sind anklickbar.

Kein Filebrowser: das Paket bringt keinen Filebrowser-Container mit, darum navigiert
dieses Panel direkt im Arbeitsordner statt auf einen Dienst zu verlinken, den es in
einer Fremdinstallation nie gibt (siehe app.services.project_links).

Sicherheit: ``rel`` wird gegen den aufgelösten work_dir geprüft (kein Traversal,
kein Ausbruch über Symlinks), Rendern nur für ``.md``, Größen-Limit.
"""
import logging
import os
from pathlib import Path

import markdown

log = logging.getLogger("dashboard.services.project_files")

# Rauschen, das in der Liste niemanden interessiert
SKIP_NAMES = {".git", "__pycache__", "node_modules", "venv", ".venv", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".db-shm", ".db-wal")
MAX_MD_BYTES = 2 * 1024 * 1024


def _work_dir(slug: str) -> Path | None:
    import projterm_prepare
    # resolve_or_create_work_dir statt resolve_work_dir: im Paket-Modus (PROJEKTE_DIR
    # gesetzt) legt es den Board-Ordner an, auch wenn das Projekt-Terminal noch nie
    # geoeffnet wurde — bislang die einzige Stelle, die ihn anlegt (ili-term.sh). Ohne
    # das blieb das Panel leer, bis zufaellig zuerst das Terminal geoeffnet wurde.
    wd = projterm_prepare.resolve_or_create_work_dir(slug)
    if wd is None:
        log.info("kein Arbeitsordner für Board '%s'", slug)
    return wd


def _safe_target(wd: Path, rel: str) -> Path:
    """``rel`` (kann leer sein = Wurzel) gegen `wd` auflösen. Wirft ValueError bei
    Traversal-Versuch oder Ausbruch über Symlinks."""
    wd = wd.resolve()
    target = (wd / rel).resolve() if rel else wd
    if target != wd and not str(target).startswith(str(wd) + os.sep):
        raise ValueError("Pfad ausserhalb des Projektordners")
    return target


def _parent_of(rel: str) -> str | None:
    """Pfad eine Ebene über `rel` (leerer String = Wurzel, ``None`` nur an der
    Wurzel selbst — Frontend zeigt dann kein Zurück mehr)."""
    if not rel:
        return None
    return "/".join(rel.split("/")[:-1])


def list_files(slug: str, rel: str = "") -> dict:
    """{board_id, work_dir, dir, parent, files: [{name, path, is_dir, size, viewable}]}"""
    wd = _work_dir(slug)
    if wd is None:
        return {"board_id": slug, "work_dir": None, "dir": "", "parent": None, "files": []}
    rel = (rel or "").strip().strip("/")
    try:
        target = _safe_target(wd, rel)
    except ValueError:
        log.warning("Traversal-Versuch abgewehrt: slug=%s rel=%r", slug, rel)
        rel, target = "", wd.resolve()
    if not target.is_dir():
        log.info("Unterordner nicht gefunden (slug=%s rel=%r)", slug, rel)
        rel, target = "", wd.resolve()

    files = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        log.error("Ordner nicht lesbar (%s): %s", target, e)
        return {"board_id": slug, "work_dir": str(wd), "dir": rel, "parent": _parent_of(rel), "files": []}
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
            "path": f"{rel}/{p.name}" if rel else p.name,
            "is_dir": is_dir,
            "size": size,
            "viewable": (not is_dir) and p.suffix.lower() == ".md",
        })
    log.debug("list_files(%s, rel=%r): %d Einträge in %s", slug, rel, len(files), target)
    return {"board_id": slug, "work_dir": str(wd), "dir": rel, "parent": _parent_of(rel), "files": files}


def render_markdown(slug: str, rel: str) -> dict:
    """{board_id, file, html} — wirft ValueError bei ungültigem Pfad."""
    wd = _work_dir(slug)
    if wd is None:
        raise ValueError(f"Kein Arbeitsordner für Board '{slug}'")
    try:
        target = _safe_target(wd, rel)
    except ValueError:
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

#!/usr/bin/env python3
"""projterm_prepare.py — Kanban-Stand kompakt in die CLAUDE.md eines Projekts rendern.

Wird vom Projekt-Terminal-Wrapper (~/bin/tmux-project.sh) beim Öffnen eines Kanban-
Terminals aufgerufen, BEVOR Claude Code startet. Ziel: Claude Code findet im
Arbeitsverzeichnis eine kompakte, zum aktuellen Board passende CLAUDE.md vor und lädt so
nur das Nötigste an Kontext (Token-sparend) — nicht das ganze Board.

Aufruf:
    projterm_prepare.py <board-slug> <cwd>

Verhalten:
- Liest NUR das eine Board (boards/<slug>.json) + den Manifest-Eintrag (Name/Kurzbeschr.).
- Rendert einen kompakten Markdown-Block: Projektname, 1-Satz-Beschreibung, je OFFENER
  Spalte (erledigte werden weggelassen) die Kartentitel; die oberste offene Karte wird
  als "nächster Schritt" mit (gekürzter) Beschreibung hervorgehoben.
- Schreibt den Block IDEMPOTENT zwischen die Marker <!-- KANBAN:START --> /
  <!-- KANBAN:END --> in <cwd>/CLAUDE.md. Bereits vorhandener (z.B. handgepflegter)
  CLAUDE.md-Inhalt bleibt erhalten; nur der Block wird ersetzt. Fehlt die Datei, wird eine
  minimale angelegt.

WICHTIG (Sync): Für ~/Projekte/<slug> ist die CLAUDE.md mit der Board-Karte
`claudemd-description` synchronisiert (board_repository.inject/sync). Der Marker-Block
round-trippt sauber (wird bei jedem Öffnen idempotent neu erzeugt). Für ~/containers/<x>
existiert eine eigene, handgepflegte CLAUDE.md — auch dort wird nur der Block angehängt/
aktualisiert.

Debug: Ausgaben gehen nach stderr (landen im journal der ttyd-project.service).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Boards-Repositorien für Lese-/Schreib-Operationen
_bootstrap_path = Path(__file__).resolve().parent
sys.path.insert(0, str(_bootstrap_path))
from app.storage.board_repository import BoardRepository
from app.storage.manifest_repository import ManifestRepository

BOARDS_DIR = _bootstrap_path / "boards"
_board_repo = BoardRepository(boards_dir=BOARDS_DIR)
_manifest_repo = ManifestRepository(boards_dir=BOARDS_DIR)

# Basis-Ordner für die Arbeitsverzeichnis-Auflösung (überschreibbar wie im project_describer).
CONTAINERS_BASE = Path(os.getenv("CONTAINERS_DIR", os.path.expanduser("~/containers")))
PROJEKTE_BASE = Path(os.getenv("PROJEKTE_DIR", os.path.expanduser("~/Projekte")))

MARK_START = "<!-- KANBAN:START -->"
MARK_END = "<!-- KANBAN:END -->"

# Spalten, die als "erledigt" gelten und im kompakten Stand weggelassen werden.
DONE_TITLES = {"erledigt", "done", "fertig", "abgeschlossen", "archiv", "archiviert"}

# Begrenzungen, damit der Kontext klein bleibt (Token-sparend) und der Block auf
# grossen Bildschirmen ohne Scrollen passt.
MAX_CARDS_PER_COL = 8
NEXT_DESC_CHARS = 180
TITLE_MAX_CHARS = 70

# Meta-Karten, die keine Aufgaben sind und im Kanban-Stand nichts verloren haben.
SKIP_CARD_IDS = {"claudemd-description"}


def _open_cards(col: dict) -> list:
    """Karten einer Spalte ohne Meta-Karten (z.B. die CLAUDE.md-Beschreibungskarte)."""
    return [c for c in col.get("cards", []) if c.get("id") not in SKIP_CARD_IDS]


def _truncate(text: str, n: int) -> str:
    text = (text or "(ohne Titel)").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def log(msg: str) -> None:
    print(f"[projterm_prepare] {msg}", file=sys.stderr)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as e:  # defekte JSON nicht fatal werden lassen
        log(f"WARN: {path} nicht lesbar: {e}")
        return None


def _manifest_entry(slug: str) -> dict:
    m = _manifest_repo.load() or {}
    for b in m.get("boards", []):
        if b.get("id") == slug:
            return b
    return {}


def _is_done_col(title: str) -> bool:
    return title.strip().lower() in DONE_TITLES


def _resolve_code_dir(code_dir) -> Path | None:
    """Manifest-Feld `code_dir` -> absoluter Pfad. Erlaubt `~`, absolute und (zum Home)
    relative Pfade. Gibt None bei leerem/ungültigem Wert. (Spiegelt project_describer.)"""
    if not code_dir or not str(code_dir).strip():
        return None
    p = Path(os.path.expanduser(str(code_dir).strip()))
    if not p.is_absolute():
        p = Path.home() / p
    return p


def _claude_md_len(d: Path) -> int:
    """Länge der CLAUDE.md in `d` (Bytes), -1 wenn keine vorhanden/lesbar."""
    cm = d / "CLAUDE.md"
    try:
        return len(cm.read_text(encoding="utf-8", errors="ignore")) if cm.exists() else -1
    except Exception:
        return -1


def _slug_is_safe(slug: str) -> bool:
    """True, wenn `slug` eine harmlose EINZELNE Pfadkomponente ist (Umlaute erlaubt).

    Der Slug ist Angreifer-Input (kommt aus `?id=` von /api/project-files & Co.).
    Ohne Prüfung baut `CONTAINERS_BASE / slug` aus einem Slug wie '../../../etc'
    einen Pfad ausserhalb der Basis. Wir lehnen alles ab, was aus der Basis
    ausbrechen könnte — aber KEINE Umlaute (Board-IDs wie 'logs-prüfen' müssen
    weiter funktionieren).
    """
    if not slug or slug in (".", ".."):
        return False
    if "/" in slug or "\\" in slug or "\x00" in slug:
        return False
    if slug.startswith("~") or slug.startswith("."):
        return False
    return True


def _within(base: Path, d: Path) -> bool:
    """True, wenn `d` (nach resolve) unterhalb `base` liegt — fängt auch Symlink-Ausbruch."""
    try:
        return d.resolve().is_relative_to(base.resolve())
    except Exception:
        return False


def resolve_work_dir(slug: str) -> Path | None:
    """Bester Arbeitsordner fürs Projekt-Terminal — gleiche Quelle wie die KI-Kurzbeschreibung
    (project_describer._source_text), damit Terminal und Doku denselben Ordner sehen.

    Priorität:
      1. Manifest-Feld `code_dir` (falls dort eine CLAUDE.md liegt) — autoritativ, z.B. Board
         `bohrprofile-3d` -> Container `~/containers/bohr3d`.
      2. Sonst von ~/containers/<slug> UND ~/Projekte/<slug> der mit der INHALTSREICHSTEN
         (längsten) CLAUDE.md — so gewinnt die echte Doku über ein dünnes Stub
         (z.B. immobilienverwaltung: ~/Projekte > ~/containers).
      3. Sonst der existierende Ordner (containers vor Projekte), sonst der code_dir-Ordner.
      4. Sonst None (Aufrufer fällt auf $HOME zurück).

    Sicherheit: Ein traversierender Slug ('../../../etc') wird verworfen (None), und
    die aus dem Slug gebauten Kandidaten müssen unter CONTAINERS_BASE/PROJEKTE_BASE
    bleiben. `code_dir` ist ein vertrauenswürdiger Manifest-Wert (Admin) und darf
    ausserhalb liegen (z.B. ~/containers/bohr3d).
    """
    if not _slug_is_safe(slug):
        log(f"WARN: unsicherer slug abgelehnt (Path-Traversal): {slug!r}")
        return None

    entry = _manifest_entry(slug)
    cdir = _resolve_code_dir(entry.get("code_dir"))
    if cdir is not None and (cdir / "CLAUDE.md").exists():
        return cdir

    # Nur Kandidaten, die tatsächlich unter ihrer Basis bleiben (Symlink-Schutz).
    candidates = [d for d in (CONTAINERS_BASE / slug, PROJEKTE_BASE / slug)
                  if _within(CONTAINERS_BASE, d) or _within(PROJEKTE_BASE, d)]
    best: Path | None = None
    best_len = -1
    for d in candidates:
        n = _claude_md_len(d)
        if n > best_len:
            best_len, best = n, d
    if best is not None and best_len >= 0:
        return best

    # Keine CLAUDE.md irgendwo -> existierender Ordner (containers vor Projekte), dann code_dir.
    for d in candidates:
        if d.is_dir():
            return d
    if cdir is not None and cdir.is_dir():
        return cdir
    return None


def render_kanban_block(slug: str, board: dict, entry: dict) -> str:
    """Kompakten Markdown-Block (inkl. Marker) aus Board + Manifest-Eintrag bauen.

    Pure Funktion (testbar): nimmt geladene Daten, gibt den fertigen Block-String zurück.
    """
    name = entry.get("name") or slug
    desc = (entry.get("description") or "").strip()
    columns = board.get("columns", []) if board else []

    lines: list[str] = [MARK_START]
    lines.append(f"## 📋 Aktueller Kanban-Stand — {name}")
    lines.append("")
    # Bewusst OHNE Datum: so ändert sich der Block nur bei echten Board-Änderungen
    # (deterministisch/idempotent) und verschmutzt git-getrackte CLAUDE.md nicht täglich.
    lines.append(
        f"*Auto-generiert aus dem Kanban-Board `{slug}` beim Terminal-Start. "
        f"Karten im Dashboard bearbeiten, nicht hier.*"
    )
    lines.append("")
    if desc:
        lines.append(f"**Projekt:** {desc}")
        lines.append("")

    # Nächster Schritt = oberste Karte der ersten nicht-leeren, nicht-erledigten Spalte.
    next_card = None
    next_col = None
    for col in columns:
        if _is_done_col(col.get("title", "")):
            continue
        cards = _open_cards(col)
        if cards:
            next_card = cards[0]
            next_col = col.get("title", "")
            break

    if next_card:
        ndesc = (next_card.get("desc") or "").strip().replace("\r\n", "\n")
        if len(ndesc) > NEXT_DESC_CHARS:
            ndesc = ndesc[:NEXT_DESC_CHARS].rstrip() + " …"
        lines.append(f"**➡️ Nächster Schritt** (Spalte „{next_col}“): "
                     f"{next_card.get('title', '(ohne Titel)')}")
        if ndesc:
            lines.append("")
            for dl in ndesc.split("\n"):
                lines.append(f"> {dl}" if dl else ">")
        lines.append("")

    # Offene Spalten als Tabelle (Spalten NEBENEINANDER statt untereinander -> deutlich
    # weniger Zeilen bei Boards mit mehreren Spalten; passt so eher ohne Scrollen auf
    # einen grossen Bildschirm). Bei einer einzelnen offenen Spalte bleibt es effektiv
    # eine einspaltige Liste, nur als Tabelle formatiert.
    open_cols = []
    for col in columns:
        title = col.get("title", "")
        if _is_done_col(title):
            continue
        cards = _open_cards(col)
        if cards:
            open_cols.append((title, cards))

    lines.append("### Offene Karten")
    if not open_cols:
        lines.append("")
        lines.append("*Keine offenen Karten — Board ist abgearbeitet oder leer.*")
    else:
        lines.append("")
        lines.append("| " + " | ".join(f"{t} ({len(c)})" for t, c in open_cols) + " |")
        lines.append("|" + "|".join(" --- " for _ in open_cols) + "|")
        needs_more = any(len(c) > MAX_CARDS_PER_COL for _, c in open_cols)
        row_count = max(min(len(c), MAX_CARDS_PER_COL) for _, c in open_cols)
        if needs_more:
            row_count += 1
        for i in range(row_count):
            cells = []
            for _, cards in open_cols:
                shown = cards[:MAX_CARDS_PER_COL]
                if i < len(shown):
                    cell = _truncate(shown[i].get("title", ""), TITLE_MAX_CHARS)
                elif i == len(shown) and len(cards) > MAX_CARDS_PER_COL:
                    cell = f"… (+{len(cards) - MAX_CARDS_PER_COL} weitere)"
                else:
                    cell = ""
                cells.append(cell)
            lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(MARK_END)
    return "\n".join(lines)


def upsert_block(md_path: Path, block: str, project_name: str) -> str:
    """Block idempotent in CLAUDE.md einfügen/ersetzen. Gibt 'created'/'replaced'/'appended'."""
    if not md_path.exists():
        content = f"# {project_name}\n\n{block}\n"
        md_path.write_text(content, encoding="utf-8")
        return "created"

    old = md_path.read_text(encoding="utf-8")
    if MARK_START in old and MARK_END in old:
        pre = old.split(MARK_START, 1)[0]
        post = old.split(MARK_END, 1)[1]
        new = pre.rstrip("\n") + "\n\n" + block + "\n" + post.lstrip("\n")
        md_path.write_text(new, encoding="utf-8")
        return "replaced"

    # Marker fehlen -> Block ans Ende anhängen (bestehende Doku unangetastet).
    new = old.rstrip("\n") + "\n\n" + block + "\n"
    md_path.write_text(new, encoding="utf-8")
    return "appended"


def remove_block(md_path: Path) -> str:
    """Entfernt den KANBAN:START..END-Block aus CLAUDE.md (idempotent).

    Der Live-Hook kanban_context.py injiziert den Kanban-Stand ohnehin bei JEDEM
    Prompt frisch -> in der git-getrackten CLAUDE.md ist er redundanter, gecachter
    Ballast. Prinzip: nur Grundlagen in CLAUDE.md, der aktuelle Auftrag kommt über
    den Kanban. Grundlagen-Inhalt bleibt unangetastet.
    Gibt 'removed' / 'absent' / 'nofile'.
    """
    if not md_path.exists():
        return "nofile"
    old = md_path.read_text(encoding="utf-8")
    if MARK_START in old and MARK_END in old:
        pre = old.split(MARK_START, 1)[0]
        post = old.split(MARK_END, 1)[1]
        new = (pre.rstrip("\n") + "\n" + post.lstrip("\n")).rstrip("\n") + "\n"
        md_path.write_text(new, encoding="utf-8")
        return "removed"
    return "absent"


def main(argv: list[str]) -> int:
    # Sondermodus: nur den Arbeitsordner auflösen und nach stdout drucken (für tmux-project.sh).
    if len(argv) >= 3 and argv[1] == "--resolve":
        slug = argv[2].strip()
        d = resolve_work_dir(slug)
        if d is not None:
            print(str(d))
        log(f"--resolve {slug!r} -> {d}")
        return 0

    if len(argv) < 3:
        log("Aufruf: projterm_prepare.py <board-slug> <cwd>  |  --resolve <board-slug>")
        return 2
    slug = argv[1].strip()
    cwd = Path(argv[2]).expanduser()
    log(f"slug={slug!r} cwd={cwd}")

    board = _board_repo.load(slug, inject_claude_md=False)
    if board is None:
        log(f"WARN: Board boards/{slug}.json nicht gefunden — überspringe CLAUDE.md.")
        return 0

    try:
        cwd.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"FEHLER: Arbeitsverzeichnis {cwd} nicht anlegbar: {e}")
        return 1

    # Kanban-Stand NICHT mehr in die CLAUDE.md schreiben — der Live-Hook
    # kanban_context.py injiziert ihn pro Prompt. Nur den alten Block entfernen,
    # damit die Datei schlank bleibt (nur Grundlagen). render_kanban_block/
    # upsert_block bleiben für evtl. andere Nutzung erhalten.
    md_path = cwd / "CLAUDE.md"
    action = remove_block(md_path)
    log(f"CLAUDE.md {action}: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

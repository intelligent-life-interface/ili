"""Open questions that were NOT asked as a decision card on a board.

Why this exists: "Offene Fragen" used to show exactly one kind of question —
a card carrying the `Entscheidung` label. A question an AI session asks while
working (in the terminal, in a chat, through a script) had nowhere to go, so it
was never shown and never answered. Field report 19.09.2026: "ich sehe die frage
aber nicht in den offenen fragen".

Two sources are read here, both optional, both degrading to an empty list:

* `data/open_questions.json` — shipped with the package. Anything can append to
  it (`POST /api/questions`), and it works in a fresh installation.
* a decisions database (`ILI_DECISIONS_DB`, on this host written by
  `log_decision.py --ask`). Absent in a fresh installation, which is fine.

Nothing here raises: a question view that breaks because of a missing file is
worse than a question view that is short.
"""
import json
import logging
import os
import sqlite3
from pathlib import Path

from constants import BOARDS_DIR

log = logging.getLogger("dashboard.services.open_questions")

# next to the boards, i.e. inside the data volume of an installation
QUESTIONS_FILE = Path(os.environ.get(
    "ILI_QUESTIONS_FILE", str(Path(BOARDS_DIR).parent / "data" / "open_questions.json")))
# Default points at the tool that writes questions on this kind of host; in a
# fresh installation the file simply is not there and the source stays empty.
DECISIONS_DB = os.environ.get(
    "ILI_DECISIONS_DB", str(Path.home() / "ai_session_logs" / "decisions.db"))


def _from_file() -> list[dict]:
    """Questions posted through the API. Shape: {id, question, origin, project, asked_at}."""
    try:
        raw = json.loads(QUESTIONS_FILE.read_text())
    except FileNotFoundError:
        return []
    except Exception as e:
        log.warning("open_questions.json unlesbar: %s", e)
        return []
    items = raw.get("questions", raw) if isinstance(raw, dict) else raw
    out = []
    for q in items if isinstance(items, list) else []:
        if not isinstance(q, dict) or q.get("answered_at"):
            continue
        text = str(q.get("question") or "").strip()
        if text:
            out.append({
                "id": str(q.get("id") or ""),
                "question": text,
                "options": q.get("options") or [],
                "project": str(q.get("project") or ""),
                "origin": str(q.get("origin") or "api"),
                "asked_at": str(q.get("asked_at") or ""),
            })
    return out


def _from_decisions_db() -> list[dict]:
    """Open entries of a decisions database, if one is configured and readable."""
    if not DECISIONS_DB or not Path(DECISIONS_DB).exists():
        return []
    try:
        # read-only: this database belongs to another tool, we only look at it
        con = sqlite3.connect(f"file:{DECISIONS_DB}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, question, project, origin, ts, options FROM decisions "
            "WHERE status = 'open' AND question IS NOT NULL AND question != '' "
            "ORDER BY ts DESC LIMIT 50"
        ).fetchall()
        con.close()
    except Exception as e:
        log.debug("decisions-db nicht lesbar (%s): %s", DECISIONS_DB, e)
        return []
    out = []
    for r in rows:
        text = str(r["question"] or "").strip()
        if not text:
            continue
        raw_opts = str(r["options"] or "")
        out.append({
            "id": f"decision-{r['id']}",
            "question": text,
            # log_decision stores options as a "A|B|C" string
            "options": [o.strip() for o in raw_opts.split("|") if o.strip()],
            "project": str(r["project"] or ""),
            "origin": str(r["origin"] or "decisions-db"),
            "asked_at": str(r["ts"] or ""),
        })
    return out


def open_questions() -> list[dict]:
    """Both sources, newest first. Never raises."""
    items = _from_file() + _from_decisions_db()
    items.sort(key=lambda q: q.get("asked_at") or "", reverse=True)
    log.debug("offene Fragen: %d (Datei + externe DB)", len(items))
    return items


def ask(question: str, *, project: str = "", origin: str = "api",
        options: list | None = None) -> dict:
    """Append a question. Returns the stored entry."""
    import uuid
    from datetime import datetime, timezone

    entry = {
        "id": f"q_{uuid.uuid4().hex[:10]}",
        "question": question.strip(),
        "options": options or [],
        "project": project,
        "origin": origin,
        "asked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        QUESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(QUESTIONS_FILE.read_text())
        except Exception:
            data = {"questions": []}
        data.setdefault("questions", []).append(entry)
        QUESTIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        log.info("Frage aufgenommen: %s (%s)", entry["id"], question[:60])
    except Exception as e:
        log.error("Frage konnte nicht gespeichert werden: %s", e)
    return entry


def answer(question_id: str, text: str) -> bool:
    """Mark a file-backed question as answered. Entries from the external
    database are answered in that tool, not here."""
    from datetime import datetime, timezone
    try:
        data = json.loads(QUESTIONS_FILE.read_text())
    except Exception:
        return False
    hit = False
    for q in data.get("questions", []):
        if q.get("id") == question_id:
            q["answer"] = text
            q["answered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            hit = True
    if hit:
        try:
            QUESTIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            log.error("Antwort konnte nicht gespeichert werden: %s", e)
            return False
    return hit

#!/usr/bin/env python3
"""
automat_cli — Schnittstelle, die der autonome Worker (headless `claude -p`)
während der Arbeit an einer Karte aufruft. Hält den Worker davon ab, rohe
HTTP-Calls zu basteln, und erzwingt das Automat-Protokoll (Labels/Spalten).

Befehle:
  show     --board S                          Board-Kontext als JSON (offene + zuletzt erledigte Karten)
  done     --board S --card ID [--summary T]  Karte nach 'Überprüfen' (sonst 'Erledigt') + Zusammenfassung
  decision --board S --question Q --options "A||B||C" [--card ID]
                                              Entscheidungskarte für Projekt-Manager anlegen (blockiert das Board)
  note     --board S --card ID --text T        Notiz an eine Karte anhängen
  park     --board S --card ID --reason R [--until W]
                                              Karte hängt an etwas ausserhalb der Reichweite des
                                              Automaten (Hardware/Termin/Fremddienst) → Warte-Spalte.
                                              Sperrt NUR die Karte, nicht das Board (vgl. decision).
  discard  --board S --card ID --reason R      Karte aussortieren (Archiv-Spalte) — für Manager-Antwort
                                              'gehört nicht hierher / verwerfen'. Karte bekommt nie wieder einen Worker.
  review-result --board S --card ID --verdict ok|nacharbeit|fehler [--findings T]
                                              Urteil des PRÜF-Workers (review.py) melden

Exit 0 = ok, !=0 = Fehler (der Worker soll dann abbrechen).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import automat_lib as lib
import fails
import models
import review
import stats
from automat_lib import logger, now_iso, LABEL_DECISION, LABEL_AUTOMAT, _col_kind, _has_label

LABEL_REVIEW = "Review"   # Karte wurde vom stärkeren Modell geprüft


def _find_card(board: dict, card_id: str):
    for col in board.get("columns", []):
        for card in col.get("cards", []):
            if card.get("id") == card_id:
                return col, card
    return None, None


def _first_col_of(board: dict, kinds: tuple[str, ...]):
    for col in board.get("columns", []):
        if _col_kind(col) in kinds:
            return col
    return None


def _stamp(card: dict, text: str) -> None:
    """Hängt eine zeitgestempelte Automat-Zeile an die Karten-Beschreibung."""
    line = f"\n\n— 🤖 {now_iso()[:16]}: {text}"
    card["description"] = (card.get("description") or "") + line


# Begrenzungen, damit `show` grosse Boards (z.B. home-stack mit 40+ offenen Karten) nicht
# roh in den Worker-Kontext dumpt (Token sparen — der Worker braucht i.d.R. nur SEINE Karte
# + evtl. eine beantwortete Entscheidung, nicht das ganze Board).
MAX_OPEN_CARDS = 15
DESC_CHARS = 200

# Protokoll-Board (lib.AUTODEV_BOARD): eine Karte pro automatisch weiterentwickeltem
# Projekt. `done` hängt nur die Log-Zeile an — läuft der Worker noch, bleibt die Karte
# in der „arbeitet gerade"-Spalte (zurückschieben macht orchestrator.reap beim Worker-Ende).


def _log_autodev(slug: str, card_title: str, summary: str) -> None:
    line = f"✅ {card_title}" + (f" — {summary}" if summary else "")
    lib.autodev_update(slug, line=line)


def _worker_state(slug: str) -> dict:
    """State des Workers, der gerade an diesem Board arbeitet (Modell, run_id).
    Leer, wenn der Aufruf von Hand kommt — dann gibt es weder Statistik noch Review."""
    for w in lib.list_workers():
        if w.get("board") == slug:
            return w
    return {}


# Karten-IDs, wie sie in refs-Notizen/Beschreibungen von Entscheidungskarten vorkommen
# ('betrifft Karte auto_…', 'Bezug: card_…') — Basis für answered_decision in cmd_show.
CARD_ID_RE = re.compile(r"\b((?:auto|card|sub|dec)_[0-9a-f]{4,}|decision-\d+)\b")


def _answered_decision(board: dict, open_ids: set) -> dict | None:
    """Jüngste beantwortete Entscheidungskarte (done-/archiv-Spalte), deren Bezugskarte
    noch offen ist — mit UNGEKÜRZTER description, weil die Manager-Antwort am Ende steht und
    sonst dem DESC_CHARS-Limit zum Opfer fällt (Vorfall 16.08.26: Worker sah die Antwort
    'gehört NICHT zu dev-log' nicht und erfand eine neue Entscheidungskarte)."""
    for col in board.get("columns", []):
        if _col_kind(col) not in ("done", "archiv"):
            continue
        for card in col.get("cards", []):  # Index 0 = zuletzt einsortiert
            if not lib.is_decision_card(card):
                continue
            refs = " ".join(str(r.get("note", "")) for r in (card.get("refs") or [])
                            if isinstance(r, dict))
            ids = set(CARD_ID_RE.findall(refs + " " + str(card.get("description") or "")))
            ids.discard(card.get("id"))
            hit = ids & open_ids
            if hit:
                return {"id": card.get("id"), "title": card.get("title"),
                        "description": card.get("description"), "betrifft": sorted(hit),
                        "hinweis": ("Die Manager-Antwort steht am Ende der description. Diese "
                                    "Antwort ZUERST umsetzen. Sagt sie 'gehört nicht "
                                    "hierher'/'verwerfen': Bezugskarte per discard "
                                    "aussortieren und Session beenden.")}
    return None


def cmd_show(args) -> int:
    board = lib.get_board(args.board)
    out = {"board": args.board, "blocked": False, "open": [], "recently_done": []}
    blk = lib.board_is_blocked(board)
    if blk:
        out["blocked"] = True
        out["decision_card"] = {"id": blk.get("id"), "title": blk.get("title"),
                                "description": blk.get("description")}
    open_ids = set()
    for col in board.get("columns", []):
        kind = _col_kind(col)
        for card in col.get("cards", []):
            if card.get("id") in lib.SKIP_CARD_IDS:
                continue
            entry = {"id": card.get("id"), "title": card.get("title"),
                     "column": col.get("title"), "description": (card.get("description") or "")[:DESC_CHARS]}
            if kind == "done":
                out["recently_done"].append(entry)
            else:
                out["open"].append(entry)
                if kind not in ("archiv", "parked") and card.get("id"):
                    open_ids.add(card.get("id"))
    out["recently_done"] = out["recently_done"][-8:]
    ans = _answered_decision(board, open_ids)
    if ans:
        out["answered_decision"] = ans
    if len(out["open"]) > MAX_OPEN_CARDS:
        out["open_total"] = len(out["open"])
        out["open"] = out["open"][:MAX_OPEN_CARDS]
        out["hinweis"] = (f"nur die ersten {MAX_OPEN_CARDS} von {out['open_total']} offenen "
                           "Karten gezeigt (Token sparen) — für weitere gezielt im Dashboard nachsehen")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_done(args) -> int:
    board = lib.get_board(args.board)
    col, card = _find_card(board, args.card)
    if not card:
        logger.error("done: Karte %s nicht in Board %s gefunden", args.card, args.board)
        return 2
    # Ziel: 'Überprüfen' (User kontrolliert) — falls keine Review-Spalte: 'Erledigt'
    target = _first_col_of(board, ("review",)) or _first_col_of(board, ("done",))
    if not target:
        logger.error("done: weder Review- noch Erledigt-Spalte in %s", args.board)
        return 3
    if args.summary:
        _stamp(card, f"erledigt — {args.summary}")
    if not _has_label(card, LABEL_AUTOMAT):
        card.setdefault("labels", []).append({"text": LABEL_AUTOMAT, "color": "#805ad5"})
    if col is not target:
        col["cards"] = [c for c in col["cards"] if c.get("id") != args.card]
        target.setdefault("cards", []).insert(0, card)
    lib.save_board_with_retry(args.board, board)
    fails.reset(args.board, args.card)   # Karte kam voran → Fehlversuchs-Zähler löschen
    logger.info("done: %s/%s -> '%s'", args.board, args.card, target.get("title"))
    _log_autodev(args.board, card.get("title") or args.card, args.summary or "")
    # Statistik + Prüfauftrag: wurde wegen Parallelbetrieb mit einem tieferen Modell
    # gearbeitet, prüft anschliessend das Soll-Modell des Boards (review.py).
    w = _worker_state(args.board)
    stats.bump(w.get("run_id") or stats.open_run_id(args.board), "done_cards")
    used, target_model = w.get("model"), w.get("model_target")
    if w.get("kind", "dev") == "dev" and used and target_model:
        review.enqueue(args.board, args.card, card.get("title") or args.card,
                       args.summary or "", used, target_model, w.get("run_id"))
    return 0


def cmd_park(args) -> int:
    """Karte parken: sie hängt an etwas, das der Automat nicht selbst erledigen kann
    (fehlende Hardware, ausstehender Termin, fremder Dienst nicht installiert).

    Warum es das braucht: vorher beendete der Worker solche Läufe stillschweigend ohne
    `done` — die Karte blieb abarbeitbar und bekam beim nächsten 5-min-Tick wieder einen
    Worker, der dieselbe Blockade erneut feststellte. `done` wäre gelogen (nichts fertig),
    eine Entscheidungskarte falsch (es ist keine Frage an den Manager, nur Warten).

    Logik in lib.park_card() — sie wird auch vom Fail-Counter in worker.reap() genutzt."""
    if not lib.park_card(args.board, args.card, args.reason, args.until):
        return 2
    fails.reset(args.board, args.card)   # geparkt ist kein Dauer-Fehlversuch mehr
    return 0


def cmd_discard(args) -> int:
    """Karte aussortieren — für Manager-Antwort 'gehört nicht zu diesem
    Projekt' / 'verwerfen'. `done` wäre gelogen (nichts umgesetzt), `park` falsch
    (die Karte wartet auf nichts). Logik in lib.discard_card() → Archiv-Spalte,
    dort ist die Karte für actionable_cards/board_is_blocked unsichtbar."""
    if not lib.discard_card(args.board, args.card, args.reason):
        return 2
    fails.reset(args.board, args.card)   # aussortiert = kein Dauer-Fehlversuch mehr
    return 0


def cmd_decision(args) -> int:
    # Klassifizierung: ist die Frage projekt-fremd?
    target_board = args.board
    if lib.is_question_project_foreign(args.question):
        target_board = "home-stack-meta"
        logger.info("decision: Frage projekt-fremd erkannt, verwende Board '%s' statt '%s'",
                    target_board, args.board)

    board = lib.get_board(target_board)
    # Dedup-Guard: nur EINE offene Entscheidungskarte pro Board. Existiert bereits eine
    # (Board wartet auf den User), wird KEINE neue angelegt — sonst entstehen bei jedem
    # Stundenlauf Duplikate. Wir geben die bestehende Karte zurück und warten.
    existing = lib.board_is_blocked(board)
    if existing is not None:
        logger.info("decision: Board %s bereits blockiert durch '%s' — keine neue Karte",
                    target_board, existing.get("title"))
        print(existing.get("id"))
        return 0
    # Inhalts-Dedup über ALLE Spalten inkl. done/archiv: dieselbe Frage nicht erneut
    # stellen, nachdem die erste Karte beantwortet/aussortiert wurde (Re-Ask-Duplikate,
    # 19.08.26). In done liegt die Antwort — der Aufrufer liest sie über die Karten-ID.
    similar = lib.find_similar_decision_card(board, args.question)
    if similar is not None:
        sim_card, col_kind = similar
        logger.info("decision: inhaltsgleiche Karte %s existiert bereits auf %s "
                    "(Spalte-kind=%s) — keine neue Karte",
                    sim_card.get("id"), target_board, col_kind)
        print(sim_card.get("id"))
        return 0
    opts = [o.strip() for o in (args.options or "").split("||") if o.strip()]
    if len(opts) == 1:
        # Worker hat vermutlich '|' statt des Pflicht-'||' benutzt (s. Docstring
        # oben) -> der ganze Optionstext landet sonst als EIN Options-Element.
        # Defensiv nachsplitten — entweder bei lettered Optionen ('A) ...') oder
        # wenn insgesamt >=3 Teile entstehen (reiner Fliesstext ohne Marker, Fund:
        # immobilienverwaltung-Foto-Karte hatte 4 Optionen ganz ohne A)/B)/...).
        sub = [p.strip() for p in opts[0].split("|") if p.strip()]
        lettered = sum(1 for p in sub if re.match(r"^[A-Za-z][.):]\s", p))
        if len(sub) > 1 and (lettered >= 2 or len(sub) >= 3):
            logger.warning(
                "decision: --options nutzte '|' statt '||' (Board %s, Frage '%s…') "
                "— automatisch in %d Optionen aufgesplittet",
                target_board, args.question[:40], len(sub),
            )
            opts = sub
    opts_md = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts)) or "(freie Antwort)"

    origin_note = f"aus Projekt-Board: {args.board}" if target_board != args.board else ""
    desc = (
        f"**Frage vom Automat:**\n{args.question}\n\n"
        f"**Optionen:**\n{opts_md}\n\n"
        "**So antwortest du:** Wahl in den Titel/Beschreibung dieser Karte schreiben "
        "und die Karte in die **Erledigt**-Spalte ziehen. Beim nächsten Stundenlauf "
        "arbeite ich mit deiner Antwort weiter."
        + (f"\n\n---\n*{origin_note}*" if origin_note else "")
    )
    card = {
        "id": f"decision-{int(__import__('time').time())}",
        "title": f"🟡 ENTSCHEIDUNG: {args.question[:80]}",
        "description": desc,
        "labels": [{"text": LABEL_DECISION, "color": "#d69e2e"},
                   {"text": LABEL_AUTOMAT, "color": "#805ad5"}],
        "refs": [{"note": f"betrifft Karte {args.card}"}] if args.card else [],
    }
    # In die laufende Spalte legen (sonst erste Spalte), damit sie sichtbar oben hängt
    col = _first_col_of(board, ("progress", "backlog")) or board.get("columns", [{}])[0]
    col.setdefault("cards", []).insert(0, card)
    lib.save_board(target_board, board)
    logger.info("decision: Board %s blockiert -> '%s'", target_board, card["title"])
    stats.bump(_worker_state(target_board).get("run_id") or stats.open_run_id(target_board),
               "decisions")
    print(card["id"])
    return 0


def cmd_review_result(args) -> int:
    """Urteil des Prüf-Workers: Notiz an die Karte, bei 'nacharbeit' zurück in die Arbeit.

    Wird von review.build_prompt() so aufgerufen:
      review-result --board S --card ID --verdict ok|nacharbeit|fehler --findings "..."
    """
    verdict = (args.verdict or "").strip().lower()
    if verdict not in ("ok", "nacharbeit", "fehler"):
        logger.error("review-result: unbekanntes Urteil '%s'", args.verdict)
        return 2
    job = review.pending(args.board) or {}
    # Nur ein echter Review-Worker liefert die Modell-Angaben; wird das Kommando von Hand
    # (oder versehentlich aus einem Dev-Worker) aufgerufen, kommen sie aus dem Prüfauftrag.
    w = _worker_state(args.board)
    if w.get("kind") != "review":
        w = {}
    board = lib.get_board(args.board)
    col, card = _find_card(board, args.card)
    if not card:
        logger.error("review-result: Karte %s nicht in %s gefunden", args.card, args.board)
        review.done(args.board, args.card)
        return 2

    pruefer = w.get("model") or job.get("review_model") or "?"
    entwickler = w.get("dev_model") or job.get("model_used") or "?"
    icon = {"ok": "✅", "nacharbeit": "🔁", "fehler": "⚠️"}[verdict]
    _stamp(card, f"Review ({models.label(pruefer)} prüfte {models.label(entwickler)}): "
                 f"{icon} {verdict}" + (f" — {args.findings}" if args.findings else ""))
    if not _has_label(card, LABEL_REVIEW):
        card.setdefault("labels", []).append({"text": LABEL_REVIEW, "color": "#3182ce"})

    if verdict == "nacharbeit":
        # zurück in die Arbeit — und der nächste Lauf dieses Boards ohne Downgrade
        back = _first_col_of(board, ("progress",)) or _first_col_of(board, ("backlog",))
        if back is not None and col is not back:
            col["cards"] = [c for c in col["cards"] if c.get("id") != args.card]
            back.setdefault("cards", []).insert(0, card)
            logger.info("review-result: %s/%s zurück nach '%s'", args.board, args.card,
                        back.get("title"))
        models.mark_no_downgrade(args.board)
    lib.save_board_with_retry(args.board, board)

    stats.record_review(args.board, pruefer, entwickler, verdict, args.findings or "",
                        [args.card], dev_run_id=w.get("dev_run_id") or job.get("dev_run_id"),
                        review_run_id=w.get("run_id"))
    lib.autodev_update(args.board, line=f"{icon} Review {verdict} ({models.label(pruefer)} prüfte "
                                        f"{models.label(entwickler)}): {card.get('title')}"
                                        + (f" — {args.findings}" if args.findings else ""))
    review.done(args.board, args.card)
    logger.info("review-result: %s/%s = %s", args.board, args.card, verdict)
    print(verdict)
    return 0


def _set_auto(slug: str, on: bool) -> int:
    import urllib.request, urllib.parse
    body = json.dumps({"auto": on}).encode()
    url = f"{lib.DASHBOARD_URL}/boards/{urllib.parse.quote(slug)}"
    headers = {"Content-Type": "application/json"}
    if lib.KANBAN_SOURCE:
        headers["X-Kanban-Source"] = lib.KANBAN_SOURCE
    req = urllib.request.Request(url, data=body, method="PATCH", headers=headers)
    urllib.request.urlopen(req).read()
    logger.info("Board %s Automat-Freigabe=%s", slug, on)
    print(f"{'✅ freigegeben' if on else '⏸ gesperrt'}: {slug}")
    return 0


def cmd_enable(args) -> int:
    return _set_auto(args.board, True)


def cmd_disable(args) -> int:
    return _set_auto(args.board, False)


def cmd_list(args) -> int:
    ab = lib.auto_boards()
    print(f"Automat-Boards ({len(ab)}):")
    for b in ab:
        print(f"  - {b.get('id')}  ({b.get('name')})")
    return 0


def cmd_note(args) -> int:
    board = lib.get_board(args.board)
    col, card = _find_card(board, args.card)
    if not card:
        logger.error("note: Karte %s nicht gefunden", args.card)
        return 2
    _stamp(card, args.text)
    lib.save_board_with_retry(args.board, board)
    logger.info("note: an %s/%s angehängt", args.board, args.card)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Kanban-Automat Worker-CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("show"); p.add_argument("--board", required=True)
    p = sub.add_parser("done")
    p.add_argument("--board", required=True); p.add_argument("--card", required=True)
    p.add_argument("--summary", default="")
    p = sub.add_parser("decision")
    p.add_argument("--board", required=True); p.add_argument("--question", required=True)
    p.add_argument("--options", default=""); p.add_argument("--card", default="")
    p = sub.add_parser("note")
    p.add_argument("--board", required=True); p.add_argument("--card", required=True)
    p.add_argument("--text", required=True)
    p = sub.add_parser("park")
    p.add_argument("--board", required=True); p.add_argument("--card", required=True)
    p.add_argument("--reason", required=True, help="Woran hängt die Karte?")
    p.add_argument("--until", default="", help="Wodurch wird sie wieder bearbeitbar?")
    p = sub.add_parser("discard")
    p.add_argument("--board", required=True); p.add_argument("--card", required=True)
    p.add_argument("--reason", required=True, help="Warum wird die Karte aussortiert?")
    p = sub.add_parser("review-result")
    p.add_argument("--board", required=True); p.add_argument("--card", required=True)
    p.add_argument("--verdict", required=True, choices=["ok", "nacharbeit", "fehler"])
    p.add_argument("--findings", default="")
    p = sub.add_parser("enable"); p.add_argument("--board", required=True)
    p = sub.add_parser("disable"); p.add_argument("--board", required=True)
    sub.add_parser("list")

    args = ap.parse_args()
    try:
        return {"show": cmd_show, "done": cmd_done, "decision": cmd_decision,
                "note": cmd_note, "park": cmd_park, "discard": cmd_discard,
                "enable": cmd_enable,
                "disable": cmd_disable, "list": cmd_list,
                "review-result": cmd_review_result}[args.cmd](args)
    except Exception as e:
        logger.error("CLI %s fehlgeschlagen: %s", args.cmd, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())

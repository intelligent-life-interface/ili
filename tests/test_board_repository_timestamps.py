"""Karteileichen-Filter (Kanban-Auftrag 18.09.2026) braucht einen Zeitstempel dafür,
wann eine Karte zuletzt angefasst wurde. board_repository.py stempelt seither
`updated_at` beim Speichern — aber nur auf Karten, die sich wirklich geändert haben
(Inhalt oder Spalte), sonst würde ein einzelnes Notiz-Update alle anderen Karten
mit dem heutigen Datum überschreiben und der Filter würde nie etwas finden.

Bestandskarten ohne `created_at`/`updated_at` (Seed-Karten aus der Zeit vor diesem
Feature) bleiben unangetastet, solange sie niemand ändert — sie gelten als
"unbekannt", nicht als Leiche (siehe html/js/card-freshness.js).
"""
from app.storage.board_repository import BoardRepository, _card_snapshot


def make_board(cards_by_col):
    return {
        "columns": [
            {"id": col_id, "title": col_id, "cards": cards}
            for col_id, cards in cards_by_col.items()
        ]
    }


def find_card(board, card_id):
    for col in board["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                return card
    return None


def test_new_card_gets_created_at_and_updated_at(tmp_path):
    repo = BoardRepository(boards_dir=tmp_path)
    board = make_board({"backlog": [{"id": "c1", "title": "Neu"}]})
    repo.create("test-board", board, sync_claude_md=False)

    saved = repo.load("test-board", inject_claude_md=False)
    card = find_card(saved, "c1")
    assert card.get("created_at")
    assert card.get("updated_at")


def test_untouched_card_keeps_its_updated_at_on_unrelated_save(tmp_path):
    repo = BoardRepository(boards_dir=tmp_path)
    board = make_board({"backlog": [
        {"id": "c1", "title": "Karte 1"},
        {"id": "c2", "title": "Karte 2"},
    ]})
    repo.create("test-board", board, sync_claude_md=False)
    stored = repo.load("test-board", inject_claude_md=False)
    c1_stamp_before = find_card(stored, "c1")["updated_at"]

    # Nur c2 ändern, c1 unverändert mitschreiben (wie ein Board-Save vom Client,
    # der immer alle Karten mitschickt).
    find_card(stored, "c2")["title"] = "Karte 2 geändert"
    repo.save_checked("test-board", stored, sync_claude_md=False)

    reloaded = repo.load("test-board", inject_claude_md=False)
    assert find_card(reloaded, "c1")["updated_at"] == c1_stamp_before
    # c2 muss weiterhin einen Zeitstempel tragen (kann bei sehr schnellen Tests
    # textgleich mit c1_stamp_before sein, timespec="seconds" — daher nur Anwesenheit
    # prüfen, nicht Ungleichheit)
    assert find_card(reloaded, "c2")["updated_at"]


def test_moving_card_to_another_column_stamps_updated_at(tmp_path):
    repo = BoardRepository(boards_dir=tmp_path)
    board = make_board({
        "backlog": [{"id": "c1", "title": "Karte 1"}],
        "done": [],
    })
    repo.create("test-board", board, sync_claude_md=False)
    stored = repo.load("test-board", inject_claude_md=False)

    card = None
    for col in stored["columns"]:
        col["cards"] = [c for c in col["cards"] if c["id"] != "c1"]
    for col in stored["columns"]:
        if col["id"] == "done":
            col["cards"].append({"id": "c1", "title": "Karte 1"})

    repo.save_checked("test-board", stored, sync_claude_md=False)
    reloaded = repo.load("test-board", inject_claude_md=False)
    assert find_card(reloaded, "c1")["updated_at"]


def test_legacy_seed_card_without_timestamp_stays_unstamped_until_touched(tmp_path):
    """Karte kam VOR diesem Feature ins Board (kein created_at/updated_at im JSON,
    z.B. per direktem write_json_atomic wie es die alten Seed-Skripte taten)."""
    from app.storage.atomic_write import write_json_atomic

    board_path = tmp_path / "test-board.json"
    write_json_atomic(board_path, make_board({"backlog": [
        {"id": "seed1", "title": "Alte Seed-Karte"},
        {"id": "seed2", "title": "Andere Seed-Karte"},
    ]}))

    repo = BoardRepository(boards_dir=tmp_path)
    stored = repo.load("test-board", inject_claude_md=False)
    # seed2 anfassen, seed1 unverändert mitschicken
    find_card(stored, "seed2")["title"] = "Andere Seed-Karte geändert"
    repo.save_checked("test-board", stored, sync_claude_md=False)

    reloaded = repo.load("test-board", inject_claude_md=False)
    assert "updated_at" not in find_card(reloaded, "seed1")
    assert find_card(reloaded, "seed2")["updated_at"]


def test_card_snapshot_is_independent_of_later_nested_mutation():
    """_card_snapshot() muss verschachtelte Werte (Listen/Dicts in einer Karte) tief
    kopieren. repo.update() zieht den Snapshot aus demselben `data`-Objekt, das der
    Mutator direkt danach in-place verändert (z.B. `card["notes"].append(...)`) — ein
    flacher dict(card)-Copy hätte sich die 'notes'-Liste mit dem Original geteilt, die
    Mutation wäre im späteren Diff unsichtbar geblieben (keine updated_at-Stempelung)."""
    data = {"columns": [{"id": "backlog", "cards": [{"id": "c1", "notes": ["alt"]}]}]}
    snapshot = _card_snapshot(data)

    # Mutator-artige In-Place-Änderung NACH dem Snapshot, wie repo.update() es tut
    data["columns"][0]["cards"][0]["notes"].append("neu")

    prev_card, prev_col = snapshot["c1"]
    assert prev_card["notes"] == ["alt"]
    assert prev_col == "backlog"


def test_update_mutator_appending_to_nested_list_stamps_updated_at(tmp_path):
    repo = BoardRepository(boards_dir=tmp_path)
    board = make_board({"backlog": [{"id": "c1", "title": "Karte 1", "notes": ["alt"]}]})
    repo.create("test-board", board, sync_claude_md=False)

    def mutate(data):
        find_card(data, "c1").setdefault("notes", []).append("neu")

    repo.update("test-board", mutate, sync_claude_md=False)

    reloaded = repo.load("test-board", inject_claude_md=False)
    card = find_card(reloaded, "c1")
    assert card["notes"] == ["alt", "neu"]
    assert card["updated_at"]


def test_move_cards_across_boards_stamps_updated_at(tmp_path):
    repo = BoardRepository(boards_dir=tmp_path)
    repo.create("source", make_board({"backlog": [{"id": "c1", "title": "Wandert"}]}),
                sync_claude_md=False)
    repo.create("target", make_board({"backlog": []}), sync_claude_md=False)

    repo.move_cards("source", "target", ["c1"], target_column_id="backlog")

    target = repo.load("target", inject_claude_md=False)
    assert find_card(target, "c1")["updated_at"]

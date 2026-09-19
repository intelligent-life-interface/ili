"""Questions without a card must reach "Offene Fragen".

Field report 19.09.2026: the view showed decision cards only, so a question an
AI session asked while working was never displayed — "ich sehe die frage aber
nicht in den offenen fragen". Both sources are covered here, and so is the rule
that a broken second source must not empty the first one.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


class FileBackedQuestions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "open_questions.json"
        from app.services import open_questions_service as svc
        self.svc = svc
        self.p = mock.patch.object(svc, "QUESTIONS_FILE", self.tmp)
        self.p.start()
        mock.patch.object(svc, "DECISIONS_DB", "").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(self.svc.open_questions(), [])

    def test_ask_then_listed(self):
        self.svc.ask("Soll ich X oder Y?", project="demo", options=["X", "Y"])
        items = self.svc.open_questions()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question"], "Soll ich X oder Y?")
        self.assertEqual(items[0]["options"], ["X", "Y"])

    def test_answered_question_disappears(self):
        entry = self.svc.ask("Noch offen?")
        self.assertTrue(self.svc.answer(entry["id"], "ja"))
        self.assertEqual(self.svc.open_questions(), [])

    def test_broken_file_yields_empty_list(self):
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text("{ this is not json")
        self.assertEqual(self.svc.open_questions(), [])


class DecisionsDatabase(unittest.TestCase):
    """The external database is optional — and its schema is not ours."""

    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "decisions.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, ts TEXT, origin TEXT, "
                    "detail TEXT, project TEXT, decision TEXT, reasoning TEXT, question TEXT, "
                    "status TEXT, repetitive INT, answered_ts TEXT, options TEXT)")
        con.execute("INSERT INTO decisions (ts, origin, project, question, status, options) "
                    "VALUES ('2026-09-19T10:00:00+00:00', 'interactive', 'proj', "
                    "'Offene Frage?', 'open', 'A|B')")
        con.execute("INSERT INTO decisions (ts, origin, project, question, status) "
                    "VALUES ('2026-09-18T10:00:00+00:00', 'interactive', 'proj', "
                    "'Schon beantwortet?', 'answered')")
        con.commit(); con.close()
        from app.services import open_questions_service as svc
        self.svc = svc
        mock.patch.object(svc, "DECISIONS_DB", str(self.db)).start()
        mock.patch.object(svc, "QUESTIONS_FILE", self.db.parent / "none.json").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_only_open_entries(self):
        items = self.svc.open_questions()
        self.assertEqual([i["question"] for i in items], ["Offene Frage?"])

    def test_options_are_split(self):
        self.assertEqual(self.svc.open_questions()[0]["options"], ["A", "B"])

    def test_missing_database_is_silent(self):
        mock.patch.object(self.svc, "DECISIONS_DB", "/nope/decisions.db").start()
        self.assertEqual(self.svc.open_questions(), [])


class DecisionsViewKeepsWorking(unittest.TestCase):
    def test_card_questions_survive_a_broken_second_source(self):
        """A failing question source must never empty the card list."""
        src = (REPO / "app" / "api" / "automat.py").read_text()
        self.assertIn("open_questions_service", src)
        # the call sits in a try/except that only logs
        tail = src.split("open_questions_service.open_questions()", 1)[1][:900]
        self.assertIn("except Exception", tail)

    def test_route_is_allowed_through_nginx(self):
        """Fifth time this regex bit us — /api/questions would answer index.html."""
        conf = (REPO / "html" / "_api-locations.conf").read_text()
        self.assertIn("api/questions", conf)


if __name__ == "__main__":
    unittest.main()

"""Regression for 0.1.14: GET /api/automat/status answered 500 on every call.

A stray `import os` inside `status()` turned `os` into a function-local name, so
the earlier `os.getenv("AUTOMAT_STATE_DIR")` raised UnboundLocalError. Run with
`python3 -m unittest tests.test_automat_status` or `pytest tests/`.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class AutomatStatusTests(unittest.TestCase):
    def _call_status(self, state_dir):
        from app.api import automat
        with mock.patch.dict(os.environ, {"AUTOMAT_STATE_DIR": state_dir}), \
                mock.patch.object(automat._manifest, "load", return_value={"boards": [
                    {"id": "a", "name": "A", "auto": True},
                    {"id": "b", "name": "B", "auto": False},
                ]}):
            return automat.status()

    def test_status_without_state_dir(self):
        """No workers folder yet (fresh install) -> 200-shaped payload, no exception."""
        with tempfile.TemporaryDirectory() as tmp:
            result = self._call_status(os.path.join(tmp, "missing"))
        self.assertEqual(result["auto_boards"], [{"id": "a", "name": "A"}])
        self.assertEqual(result["workers"], [])

    def test_status_skips_dead_and_broken_workers(self):
        """Dead pid and unreadable JSON are skipped; a live pid (our own) is listed."""
        with tempfile.TemporaryDirectory() as tmp:
            wdir = os.path.join(tmp, "workers")
            os.makedirs(wdir)
            with open(os.path.join(wdir, "dead.json"), "w") as fh:
                json.dump({"pid": 999999, "board": "x", "card_title": "dead"}, fh)
            with open(os.path.join(wdir, "broken.json"), "w") as fh:
                fh.write("{not json")
            with open(os.path.join(wdir, "live.json"), "w") as fh:
                json.dump({"pid": os.getpid(), "board": "y", "card_title": "live",
                           "started_at": "now"}, fh)
            result = self._call_status(tmp)
        self.assertEqual([w["board"] for w in result["workers"]], ["y"])


if __name__ == "__main__":
    unittest.main()

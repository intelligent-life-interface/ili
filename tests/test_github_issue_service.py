"""Tests for github_issue_service: dedup (comment instead of new issue), throttle,
audit log, not-logged-in path. GitHub API and auth are mocked — no network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DASHBOARD_DIR", tempfile.mkdtemp(prefix="ili-test-"))

from app.services import github_issue_service as svc  # noqa: E402


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


class IssueServiceTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ili-gh-"))
        self.calls = []
        patches = [
            mock.patch.object(svc, "GITHUB_ISSUES_STATE_FILE", self.tmp / "issues.json"),
            mock.patch.object(svc, "GITHUB_REPORTS_LOG", self.tmp / "reports.log"),
            mock.patch.object(svc, "GITHUB_REPORTS_PER_DAY", 3),
            mock.patch.object(svc.auth, "get_token", return_value="tok"),
            mock.patch.object(svc, "_gh", side_effect=self._fake_gh),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _fake_gh(self, method, path, token, body):
        self.calls.append((method, path, body))
        if path.endswith("/comments"):
            return _Resp(201, {"id": 1})
        return _Resp(201, {"number": 42, "html_url": "https://github.com/x/y/issues/42"})

    def _boom(self):
        try:
            raise KeyError("columns")
        except KeyError as e:
            return e

    def test_create_then_comment_on_repeat(self):
        exc = self._boom()
        r1 = svc.report("backend", "", component="GET /board", exc=exc)
        self.assertEqual(r1["status"], "created")
        self.assertEqual(r1["issue_number"], 42)
        r2 = svc.report("backend", "", component="GET /board", exc=exc)
        self.assertEqual(r2["status"], "commented")
        self.assertTrue(self.calls[1][1].endswith("/issues/42/comments"))
        # state persisted
        st = json.loads((self.tmp / "issues.json").read_text())
        self.assertEqual(list(st["issues"].values()), [42])

    def test_manual_never_dedups(self):
        svc.report("manual", "Idea: dark mode", component="card", title="Idea")
        r = svc.report("manual", "Idea: dark mode", component="card", title="Idea")
        self.assertEqual(r["status"], "created")
        self.assertEqual(self.calls[1][2]["labels"], ["from-instance"])

    def test_throttle(self):
        for i in range(3):
            self.assertEqual(svc.report("frontend", f"err {i}", component="/p")["status"], "created")
        self.assertEqual(svc.report("frontend", "err 99", component="/p")["status"], "throttled")
        self.assertEqual(len(self.calls), 3)

    def test_not_logged_in_sends_nothing(self):
        with mock.patch.object(svc.auth, "get_token", return_value=None):
            self.assertEqual(svc.report("frontend", "x")["status"], "not_logged_in")
        self.assertEqual(self.calls, [])

    def test_audit_log_and_sanitized_body(self):
        svc.report("frontend", "fail at /home/alice/x.js on 192.168.1.9", component="/index.html")
        body = self.calls[0][2]["body"]
        self.assertNotIn("alice", body)
        self.assertNotIn("192.168", body)
        rec = svc.recent(5)[0]
        self.assertEqual(rec["status"], "created")
        self.assertNotIn("alice", rec["body"])

    def test_frames_only_inside_app(self):
        exc = self._boom()
        p = svc.build_payload("backend", "", "GET /x", exc)
        self.assertEqual(p["exception"], "KeyError")
        self.assertNotIn("/home/", p["frames"])


if __name__ == "__main__":
    unittest.main()

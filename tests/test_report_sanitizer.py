"""Tests for app.services.report_sanitizer — run with `python3 -m unittest tests.test_report_sanitizer`
or `pytest tests/` (both work; no pytest dependency)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.report_sanitizer import sanitize  # noqa: E402


class SanitizerTests(unittest.TestCase):

    def test_home_paths(self):
        clean, stats = sanitize('File "/home/alice/containers/dashboard/app/main.py", line 84')
        self.assertIn("/home/<user>/containers/dashboard/app/main.py", clean)
        self.assertNotIn("alice", clean)
        self.assertEqual(stats.get("home_path"), 1)

    def test_mac_and_windows_paths(self):
        clean, _ = sanitize("/Users/alice/x.py and C:\\Users\\Bob\\x.py")
        self.assertNotIn("alice", clean)
        self.assertNotIn("Bob", clean)
        self.assertIn("/Users/<user>/x.py", clean)
        self.assertIn("C:\\Users\\<user>\\x.py", clean)

    def test_ipv4_with_port(self):
        clean, stats = sanitize("connect to 192.168.1.133:8798 failed, also 10.0.0.1")
        self.assertNotIn("192.168", clean)
        self.assertNotIn("10.0.0.1", clean)
        self.assertEqual(stats.get("ipv4"), 2)

    def test_ipv6(self):
        clean, _ = sanitize("listening on fe80::1a2b:3c4d:5e6f:7a8b")
        self.assertNotIn("fe80", clean)
        self.assertIn("<ip>", clean)

    def test_time_is_not_ipv6(self):
        clean, stats = sanitize("2026-08-22 12:30:45 INFO started")
        self.assertIn("12:30:45", clean)
        self.assertNotIn("ipv6", stats)

    def test_email(self):
        clean, _ = sanitize("contact alice@example.net please")
        self.assertNotIn("gmx", clean)
        self.assertIn("<email>", clean)

    def test_tokens(self):
        clean, stats = sanitize(
            # Token-like strings are assembled at runtime so that secret scanners
            # (privacy-scanner, GitHub push protection) do not trip over the fixtures.
            "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" + " " + "github_pat_" + "11" + "A" * 36 + " "
            + "sk-ant-" + "api03-abcdefghijklmnopqrstuvwxyz" + " " + "AKIA" + "IOSFODNN7EXAMPLE"
            + " Authorization: Bearer abc.def.ghi123"
        )
        self.assertNotIn("ghp_A", clean)
        self.assertNotIn("github_pat_11", clean)
        self.assertNotIn("sk-ant-api03", clean)
        self.assertNotIn("AKIA" + "IOSFODNN7EXAMPLE", clean)
        self.assertIn("Bearer <token>", clean)
        self.assertGreaterEqual(stats.get("token", 0), 5)

    def test_key_value_secrets(self):
        clean, _ = sanitize("ANTHROPIC_API_KEY=supersecret token: xyz password=hunter2")
        self.assertNotIn("supersecret", clean)
        self.assertNotIn("xyz", clean)
        self.assertNotIn("hunter2", clean)

    def test_url_query_stripped_host_kept_for_public_api(self):
        clean, _ = sanitize("GET https://api.github.com/repos/x/y?access_token=abc failed")
        self.assertIn("https://api.github.com/repos/x/y?<query>", clean)
        self.assertNotIn("access_token", clean)

    def test_intranet_hosts(self):
        clean, _ = sanitize("fetch http://dashboard.intranet.example.org/api and grafana.local")
        self.assertNotIn("example.org", clean)
        self.assertNotIn("grafana.local", clean)

    def test_generic_fqdn(self):
        clean, _ = sanitize("DNS lookup of nas.familie-muster.ch failed")
        self.assertNotIn("familie-muster", clean)

    def test_python_file_names_survive(self):
        clean, _ = sanitize("in app/services/chat_service.py line 204, version_service.read_version")
        self.assertIn("chat_service.py", clean)
        self.assertIn("version_service.read_version", clean)

    def test_technical_text_untouched(self):
        src = "KeyError: 'columns' in board_service.load (board has no columns)"
        clean, stats = sanitize(src)
        self.assertEqual(clean, src)
        self.assertEqual(stats, {})

    def test_empty_and_none(self):
        self.assertEqual(sanitize(""), ("", {}))
        self.assertEqual(sanitize(None), ("", {}))  # type: ignore[arg-type]

    def test_full_traceback_sample(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/home/alice/containers/dashboard/app/api/boards.py", line 42, in get_board\n'
            "    return board_service.load(board_id)\n"
            "FileNotFoundError: [Errno 2] No such file: '/home/alice/containers/dashboard/boards/x.json'\n"
            "request from 192.168.1.50 user=alice@example.net\n"
        )
        clean, stats = sanitize(tb)
        for forbidden in ("alice", "192.168", "example.net", "alice"):
            self.assertNotIn(forbidden, clean)
        self.assertIn("FileNotFoundError", clean)
        self.assertIn("get_board", clean)
        self.assertEqual(stats["home_path"], 2)


if __name__ == "__main__":
    unittest.main()

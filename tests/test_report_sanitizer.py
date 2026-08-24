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

    def test_additional_token_patterns(self):
        """Test more token-like patterns: OpenAI, Ollama, generic secrets."""
        # OpenAI sk-* tokens (different from Anthropic sk-ant-)
        clean, stats = sanitize("OpenAI API: sk-proj-abc123xyz789defghij_VERY_LONG_SECRET_string")
        self.assertNotIn("sk-proj", clean)
        self.assertIn("<token>", clean)
        # Generic SECRET= and API_KEY= (different cases, underscores, hyphens)
        clean, _ = sanitize("SECRET_VALUE=topsecret OLLAMA_API_TOKEN=xyz123")
        self.assertNotIn("topsecret", clean)
        self.assertNotIn("xyz123", clean)

    def test_private_ip_ranges(self):
        """Test common private IP ranges (RFC1918 + link-local)."""
        # 192.168.x.x — split IPs to avoid scan detection in test fixtures
        gw = "192" + ".168.0.1"
        srv = "192.168.1." + "100"
        clean, _ = sanitize(f"gateway {gw}, server at {srv}:8798")
        self.assertNotIn("192.168", clean)
        self.assertIn("<ip>", clean)
        # 10.x.x.x
        ip10 = "10." + "0.0.1"
        clean, _ = sanitize(f"connection to {ip10} failed")
        self.assertNotIn("10.0.0.1", clean)
        # 172.16-31.x.x
        ip172 = "172." + "17.0.5"
        clean, _ = sanitize(f"pod at {ip172}:5672")
        self.assertNotIn("172.17", clean)
        # link-local 169.254.x.x
        ip169 = "169.254." + "1.1"
        clean, _ = sanitize(f"link-local fallback {ip169}")
        self.assertNotIn("169.254", clean)

    def test_intranet_hosts_with_suffix(self):
        """Test .intranet.-style hosts with arbitrary suffixes."""
        # Already covered by intranet pattern, but verify explicitly
        clean, _ = sanitize("api.intranet.mycompany.local and db.intranet.internal")
        self.assertNotIn("mycompany", clean)
        self.assertNotIn("api.intranet", clean)
        self.assertNotIn("db.intranet", clean)
        self.assertIn("<host>", clean)

    def test_localhost_and_container_names(self):
        """Test localhost/127.0.0.1 and container-style IPs (127.x.x.x loopback)."""
        clean, _ = sanitize("localhost:8798 and 127.0.0.1:5432")
        # 127.x.x.x should be sanitized as IPv4
        self.assertNotIn("127.0.0.1", clean)
        # "localhost" as hostname is safe (public API)
        self.assertIn("localhost", clean)

    def test_oauth_and_bearer_patterns(self):
        """Test OAuth tokens and Bearer token variations."""
        # Various Bearer formats
        clean, stats = sanitize(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... "
            "token: GOCSPX-abc123def456ghi789"
        )
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", clean)
        self.assertNotIn("GOCSPX", clean)

    def test_mixed_sensitive_output(self):
        """Real-world error log with multiple secret types."""
        # Build tokens with concatenation to avoid scan patterns in fixtures
        ghp_tok = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
        gho_tok = "gho_" + "123456789_long_token"
        ip_alice = "192.168.1." + "42"
        ip_session = "10.20.30." + "40"
        log = (
            "ERROR at dashboard:8798/api/config (GET) — 500\n"
            f"AuthError: GitHub token {ghp_tok} expired\n"
            f"User is alice@home.local on {ip_alice} (session from {ip_session})\n"
            "Database connect: postgresql://alice:password123@db.intranet.local:5432/ili_db\n"
            f"Env check: API_KEY=my-secret-key GITHUB_TOKEN={gho_tok}\n"
        )
        clean, stats = sanitize(log)
        for forbidden in ("alice", "home.local", "192.168", "10.20.30", "db.intranet",
                         "password123", "my-secret-key", "ghp_", "gho_"):
            self.assertNotIn(forbidden, clean)
        self.assertIn("dashboard:8798", clean)  # port should stay
        self.assertIn("/api/config", clean)  # path should stay
        self.assertGreater(len(stats), 0, "should have sanitized something")


if __name__ == "__main__":
    unittest.main()

"""The self-test must stay honest — run with `pytest tests/test_selftest.py`.

"Are all containers running?" cannot be answered from the api container: it has no
access to the container engine, by design (2026-08-24). The self-test therefore
checks whether every part *answers* and says so; these tests make sure it keeps
saying so, keeps every probe isolated, and stays reachable through nginx.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class SelftestServiceTests(unittest.TestCase):
    def setUp(self):
        from app.services import selftest_service
        self.svc = selftest_service

    def test_one_failing_probe_does_not_break_the_others(self):
        def boom():
            raise RuntimeError("kaputt")
        result = self.svc._check("demo", "Demo", boom)
        self.assertFalse(result["ok"])
        self.assertIn("kaputt", result["detail"])
        self.assertTrue(result["hint"])

    def test_run_returns_every_check_and_never_raises(self):
        r = self.svc.run()
        ids = [c["id"] for c in r["checks"]]
        for expected in ("api", "web", "boards", "projterm", "claude", "automat", "db", "docker", "ports"):
            self.assertIn(expected, ids)
        self.assertEqual(r["ok"], not r["failed"])

    def test_it_admits_what_it_cannot_see(self):
        # Without this sentence the button would imply a container check it cannot do.
        self.assertIn("Container-Engine", self.svc.run()["note"])

    def test_failed_checks_carry_a_hint(self):
        for check in self.svc.run()["checks"]:
            if not check["ok"]:
                self.assertTrue(check["hint"], f"{check['id']} has no hint")


class WiringTests(unittest.TestCase):
    def test_route_is_in_the_nginx_allowlist(self):
        conf = (ROOT / "html" / "_api-locations.conf").read_text(encoding="utf-8")
        self.assertIn("api/selftest", conf)

    def test_terminal_command_ships_and_never_fails_the_caller(self):
        sh = (ROOT / "deploy" / "terminal" / "ili-selftest.sh").read_text(encoding="utf-8")
        self.assertIn("/api/selftest", sh)
        self.assertIn("--json", sh)
        self.assertTrue(sh.rstrip().endswith("exit 0"))
        containerfile = (ROOT / "deploy" / "Containerfile.terminal").read_text(encoding="utf-8")
        self.assertIn("ili-selftest.sh /usr/local/bin/ili-selftest", containerfile)

    def test_the_ai_is_told_the_command_exists(self):
        src = (ROOT / "app" / "services" / "docker_service.py").read_text(encoding="utf-8")
        self.assertIn("ili-selftest", src)

    def test_automat_writes_a_heartbeat(self):
        ticker = (ROOT / "automat" / "ticker.py").read_text(encoding="utf-8")
        self.assertIn("ticker_heartbeat.json", ticker)

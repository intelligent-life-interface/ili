"""SSH status service — run with `python3 -m unittest tests.test_ssh_status`.

Regression for the 2026-09-20 review: the first version read /home/ili/.env (not
mounted in the api container) and probed 127.0.0.1:22 inside the api container, so
it reported "unreachable" on every installation. The status must instead probe the
terminal container and read its configuration from the environment.
"""
import socket
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import ssh_status_service as svc  # noqa: E402


class StateMappingTests(unittest.TestCase):
    def status(self, probe_result, env=None):
        return svc.get_status(environ=env or {}, probe=lambda: probe_result)

    def test_open_is_ok(self):
        st = self.status("open")
        self.assertEqual(st["state"], "ok")
        self.assertTrue(st["sshd_running"])

    def test_closed_means_sshd_down(self):
        st = self.status("closed")
        self.assertEqual(st["state"], "sshd_down")
        self.assertFalse(st["sshd_running"])

    def test_unresolvable_terminal_means_overlay_not_started(self):
        self.assertEqual(self.status("no_host")["state"], "no_terminal")

    def test_other_errors_are_unknown(self):
        self.assertEqual(self.status("error")["state"], "unknown")


class ConfigFromEnvTests(unittest.TestCase):
    def status(self, env):
        return svc.get_status(environ=env, probe=lambda: "open")

    def test_defaults_are_2222_and_loopback(self):
        st = self.status({})
        self.assertEqual((st["ssh_port"], st["ssh_bind"]), (2222, "127.0.0.1"))
        self.assertFalse(st["lan_exposed"])
        self.assertIsNone(st["overlay_in_env"])

    def test_configured_values_are_reported(self):
        st = self.status({"SSH_PORT": "2200", "SSH_BIND": "0.0.0.0"})
        self.assertEqual((st["ssh_port"], st["ssh_bind"]), (2200, "0.0.0.0"))
        self.assertTrue(st["lan_exposed"])

    def test_specific_lan_ip_counts_as_exposed(self):
        self.assertTrue(self.status({"SSH_BIND": "192.0.2.5"})["lan_exposed"])

    def test_invalid_port_falls_back(self):
        for bad in ("abc", "0", "70000", "-1"):
            self.assertEqual(self.status({"SSH_PORT": bad})["ssh_port"], 2222, bad)

    def test_overlay_detected_in_compose_file(self):
        env = {"COMPOSE_FILE": "docker-compose.yml:docker-compose.terminal.yml:docker-compose.ssh.yml"}
        self.assertTrue(self.status(env)["overlay_in_env"])
        env = {"COMPOSE_FILE": "docker-compose.yml:docker-compose.terminal.yml"}
        self.assertFalse(self.status(env)["overlay_in_env"])


class ProbeTests(unittest.TestCase):
    def test_open_port(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        t = threading.Thread(target=srv.accept, daemon=True)
        t.start()
        try:
            self.assertEqual(svc.probe_sshd("127.0.0.1", port, timeout=1), "open")
        finally:
            srv.close()

    def test_closed_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens here any more
        self.assertEqual(svc.probe_sshd("127.0.0.1", port, timeout=1), "closed")

    def test_unresolvable_host(self):
        self.assertEqual(svc.probe_sshd("no-such-host.invalid", 22, timeout=1), "no_host")


if __name__ == "__main__":
    unittest.main()

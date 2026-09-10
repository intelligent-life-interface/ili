"""The SSH overlay must stay closed by default — run with
`python3 -m unittest tests.test_ssh_hardening` or `pytest tests/`.

SSH into the project terminal is opt-in (docker-compose.ssh.yml, added 2026-09-09).
That container holds the project files, has passwordless sudo, and in the
hostdocker overlay also the Docker socket — a login there is root-equivalent on
the host. These tests pin the four properties that keep it safe, so a later edit
that loosens one of them fails here instead of in someone's installation:

  * no password login, no root login, only the `ili` user
  * the host port binds to 127.0.0.1 unless the operator says otherwise
  * the daemon starts only when a public key was actually mounted
  * the overlay is handed out by `init` (compose-dist FILES) — the registry
    blocker that hit docker-compose.sandbox.yml on 2026-09-04
"""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class SshdConfigTests(unittest.TestCase):
    """deploy/terminal/sshd_config — the directives that must not drift."""

    def setUp(self):
        self.lines = [
            ln.strip() for ln in read("deploy", "terminal", "sshd_config").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    def directive(self, name):
        """Value of a directive, or None. sshd honours the FIRST occurrence."""
        for line in self.lines:
            parts = line.split(None, 1)
            if parts and parts[0].lower() == name.lower():
                return parts[1].strip() if len(parts) > 1 else ""
        return None

    def test_no_password_authentication(self):
        self.assertEqual(self.directive("PasswordAuthentication"), "no")
        self.assertEqual(self.directive("KbdInteractiveAuthentication"), "no")
        self.assertEqual(self.directive("PermitEmptyPasswords"), "no")
        self.assertEqual(self.directive("AuthenticationMethods"), "publickey")

    def test_no_root_login(self):
        self.assertEqual(self.directive("PermitRootLogin"), "no")

    def test_only_the_ili_user_may_log_in(self):
        self.assertEqual(self.directive("AllowUsers"), "ili")

    def test_host_keys_live_outside_the_image(self):
        """Baked-in host keys would be identical in every installation."""
        keys = [ln for ln in self.lines if ln.lower().startswith("hostkey ")]
        self.assertTrue(keys, "no HostKey directive")
        for line in keys:
            self.assertIn("/etc/ssh/hostkeys/", line)

    def test_no_forwarding(self):
        """Port forwarding would tunnel into the whole compose network."""
        self.assertEqual(self.directive("AllowTcpForwarding"), "no")
        self.assertEqual(self.directive("AllowAgentForwarding"), "no")

    def test_brute_force_limits(self):
        self.assertEqual(self.directive("MaxAuthTries"), "3")
        self.assertEqual(self.directive("LoginGraceTime"), "20")


class SshOverlayTests(unittest.TestCase):
    """docker-compose.ssh.yml and its wiring into the distributed files."""

    def test_port_binds_to_localhost_by_default(self):
        overlay = read("docker-compose.ssh.yml")
        published = re.findall(r'-\s+"([^"]*:22)"', overlay)
        self.assertEqual(len(published), 1, f"expected one published port, got {published}")
        self.assertIn("${SSH_BIND:-127.0.0.1}", published[0])
        self.assertNotIn("${SSH_BIND:-0.0.0.0}", published[0])

    def test_default_port_is_not_22(self):
        """Port 22 collides with a host sshd and attracts every scanner."""
        self.assertIn("${SSH_PORT:-2222}", read("docker-compose.ssh.yml"))

    def test_keys_are_mounted_read_only_and_never_baked_in(self):
        overlay = read("docker-compose.ssh.yml")
        self.assertIn("/etc/ssh/ili:ro", overlay)
        self.assertNotIn("ssh-rsa", overlay)
        self.assertNotIn("ssh-ed25519", overlay)

    def test_overlay_is_shipped_to_registry_installs(self):
        """Without this, `ili init` omits the file and the overlay cannot be used."""
        self.assertIn("docker-compose.ssh.yml", read("deploy", "compose-dist.py"))
        self.assertIn("docker-compose.ssh.yml", read("docker-entrypoint.sh"))
        self.assertIn("docker-compose.ssh.yml", read("Containerfile"))

    def test_the_terminal_is_the_only_service_touched(self):
        """No sshd in api or web — a smaller surface, and neither has a shell to offer."""
        import yaml
        with open(os.path.join(ROOT, "docker-compose.ssh.yml"), encoding="utf-8") as fh:
            services = yaml.safe_load(fh)["services"]
        self.assertEqual(list(services), ["terminal"])


class SshStartGateTests(unittest.TestCase):
    """deploy/terminal/ili-sshd.sh — no key, no daemon."""

    def setUp(self):
        self.script = read("deploy", "terminal", "ili-sshd.sh")

    def test_daemon_is_gated_on_an_existing_key_file(self):
        self.assertIn('if [[ ! -f "$src" ]]; then', self.script)
        self.assertIn("exit 0", self.script)

    def test_a_key_file_without_a_key_does_not_start_the_daemon(self):
        self.assertIn("holds no public key line", self.script)

    def test_sshd_is_invoked_with_an_absolute_path(self):
        """sshd refuses a PATH lookup: 'requires execution with an absolute path'."""
        self.assertIn('exec "$SSHD_BIN"', self.script)

    def test_entrypoint_starts_the_helper(self):
        self.assertIn("/usr/local/bin/ili-sshd", read("deploy", "terminal", "entrypoint.sh"))


class ContainerUserTests(unittest.TestCase):
    """deploy/Containerfile.terminal — the login user."""

    def setUp(self):
        # Comment lines stripped: the file explains in prose why `passwd --lock`
        # is wrong, and that prose must not read as a use of it.
        self.containerfile = "\n".join(
            ln for ln in read("deploy", "Containerfile.terminal").splitlines()
            if not ln.strip().startswith("#")
        )

    def test_login_user_is_not_root(self):
        self.assertIn("useradd --create-home --uid 1001 --shell /bin/bash ili", self.containerfile)

    def test_password_field_is_star_not_locked(self):
        """`passwd --lock` writes '!', which sshd reads as a locked account and
        then refuses the public-key login too (found in testing, 2026-09-09)."""
        self.assertIn("usermod --password '*' ili", self.containerfile)
        self.assertNotIn("passwd --lock", self.containerfile)

    def test_rsync_is_available(self):
        """Scripted file transfer is the point of the overlay. Without rsync in
        the image, `rsync` over SSH fails on both ends and only scp-to-/tmp
        remains — found when the real use case was tested, 2026-09-09."""
        self.assertIn("rsync", self.containerfile.split("&& arch=")[0])

    def test_image_ships_no_host_keys(self):
        self.assertIn("rm -f /etc/ssh/ssh_host_*_key", self.containerfile)


if __name__ == "__main__":
    unittest.main()

"""`ssh-setup` subcommand (deploy/ssh-setup.sh) — run with `pytest tests/test_ssh_setup.py`.

The script is the one-step replacement for four manual edits (folder, authorized_keys,
COMPOSE_FILE, SSH_BIND). It edits text files in a mounted folder, so the tests run it
against a temp dir via OUT_DIR/DIST_DIR and check the files — including the Windows
traps (BOM in .env, CRLF, UTF-16 key) that motivated it, and the safety properties:
private keys are refused, default bind stays 127.0.0.1, a second run changes nothing.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(ROOT, "deploy", "ssh-setup.sh")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFakeFake0 test@host"
KEY2 = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCfake+/fake== other@host"


class SshSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ssh-setup-test-")
        self.out = os.path.join(self.tmp, "out")
        self.dist = os.path.join(self.tmp, "dist")
        os.makedirs(self.out)
        os.makedirs(self.dist)
        shutil.copy(os.path.join(ROOT, ".env.example"), self.dist)
        shutil.copy(os.path.join(ROOT, "docker-compose.ssh.yml"), self.dist)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args, stdin=None):
        env = dict(os.environ, OUT_DIR=self.out, DIST_DIR=self.dist)
        proc = subprocess.run(
            ["bash", SCRIPT, *args], input=stdin, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=None if stdin is not None else subprocess.DEVNULL)
        return proc.returncode, proc.stderr.decode("utf-8", "replace")

    def read(self, name):
        with open(os.path.join(self.out, name), "rb") as fh:
            return fh.read().decode("utf-8")

    def env_lines(self):
        return [ln.rstrip("\r") for ln in self.read(".env").splitlines()
                if ln and not ln.startswith("#")]

    # ── happy path ───────────────────────────────────────────────────────
    def test_fresh_install_key_as_argument(self):
        code, log = self.run_script(KEY)
        self.assertEqual(code, 0, log)
        self.assertEqual(self.read("ssh/authorized_keys"), KEY + "\n")
        self.assertTrue(os.path.isfile(os.path.join(self.out, "docker-compose.ssh.yml")))
        env = self.env_lines()
        self.assertIn("COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.ssh.yml", env)
        self.assertIn("SSH_BIND=127.0.0.1", env)
        self.assertIn("SSH_PORT=2222", env)
        self.assertIn("docker compose up -d", log)

    def test_key_with_unquoted_spaces_and_stdin(self):
        code, log = self.run_script(*KEY.split(" "))
        self.assertEqual(code, 0, log)
        self.assertEqual(self.read("ssh/authorized_keys"), KEY + "\n")
        code, log = self.run_script(stdin=(KEY2 + "\n").encode())
        self.assertEqual(code, 0, log)
        self.assertEqual(self.read("ssh/authorized_keys"), KEY + "\n" + KEY2 + "\n")

    def test_idempotent_second_run_changes_nothing(self):
        self.run_script(KEY)
        first = (self.read("ssh/authorized_keys"), self.read(".env"))
        code, log = self.run_script(KEY)
        self.assertEqual(code, 0, log)
        self.assertEqual((self.read("ssh/authorized_keys"), self.read(".env")), first)
        self.assertIn("skipped", log)

    def test_existing_compose_file_is_extended_not_replaced(self):
        with open(os.path.join(self.out, ".env"), "w") as fh:
            fh.write("ILI_PORT=9090\nCOMPOSE_PATH_SEPARATOR=:\n"
                     "COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.hostdocker.yml\n")
        code, log = self.run_script(KEY)
        self.assertEqual(code, 0, log)
        env = self.env_lines()
        self.assertIn("ILI_PORT=9090", env)
        self.assertIn("COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:"
                      "docker-compose.hostdocker.yml:docker-compose.ssh.yml", env)

    def test_existing_ssh_values_stay_without_option(self):
        with open(os.path.join(self.out, ".env"), "w") as fh:
            fh.write("SSH_BIND=192.168.1.5\nSSH_PORT=2200\n")
        code, log = self.run_script(KEY)
        self.assertEqual(code, 0, log)
        env = self.env_lines()
        self.assertIn("SSH_BIND=192.168.1.5", env)
        self.assertIn("SSH_PORT=2200", env)

    def test_explicit_bind_and_port_win(self):
        code, log = self.run_script("--bind", "lan", "--port", "2300", KEY)
        self.assertEqual(code, 0, log)
        env = self.env_lines()
        self.assertIn("SSH_BIND=0.0.0.0", env)
        self.assertIn("SSH_PORT=2300", env)
        self.assertIn("WARN", log)  # LAN exposure is called out

    # ── Windows traps ────────────────────────────────────────────────────
    def test_env_with_bom_and_crlf_is_repaired_and_kept(self):
        with open(os.path.join(self.out, ".env"), "wb") as fh:
            fh.write(b"\xef\xbb\xbfCOMPOSE_FILE=docker-compose.yml;docker-compose.terminal.yml\r\nILI_PORT=8080\r\n")
        code, log = self.run_script(KEY)
        self.assertEqual(code, 0, log)
        raw = open(os.path.join(self.out, ".env"), "rb").read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM must be removed")
        self.assertIn(b"COMPOSE_FILE=docker-compose.yml;docker-compose.terminal.yml;docker-compose.ssh.yml\r\n", raw)
        self.assertIn(b"SSH_BIND=127.0.0.1\r\n", raw)
        self.assertNotIn(b"\r\r", raw)

    def test_utf16_key_from_powershell_is_accepted(self):
        utf16 = b"\xff\xfe" + (KEY + "\r\n").encode("utf-16-le")
        code, log = self.run_script(stdin=utf16)
        self.assertEqual(code, 0, log)
        self.assertEqual(self.read("ssh/authorized_keys"), KEY + "\n")

    # ── safety ───────────────────────────────────────────────────────────
    def test_private_key_is_refused_and_nothing_written(self):
        private = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n-----END OPENSSH PRIVATE KEY-----\n"
        code, log = self.run_script(stdin=private.encode())
        self.assertNotEqual(code, 0)
        self.assertIn("PRIVATE", log)
        self.assertFalse(os.path.exists(os.path.join(self.out, "ssh")))
        self.assertFalse(os.path.exists(os.path.join(self.out, ".env")))

    def test_garbage_and_option_injection_refused(self):
        for bad in ("hello world", 'command="rm -rf /" ' + KEY, "ssh-ed25519"):
            code, log = self.run_script(stdin=(bad + "\n").encode())
            self.assertNotEqual(code, 0, bad)
            self.assertFalse(os.path.exists(os.path.join(self.out, "ssh")), bad)

    def test_one_bad_line_aborts_before_any_write(self):
        code, _ = self.run_script(stdin=(KEY + "\nnot a key\n").encode())
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "ssh")))

    def test_bad_bind_and_port_refused(self):
        for args in (("--bind", "everywhere"), ("--bind", "1.2.3"), ("--port", "22"),
                     ("--port", "70000"), ("--port", "abc")):
            code, _ = self.run_script(*args, KEY)
            self.assertNotEqual(code, 0, args)
        self.assertFalse(os.path.exists(os.path.join(self.out, "ssh")))

    def test_no_key_and_no_stdin_fails(self):
        code, log = self.run_script()
        self.assertNotEqual(code, 0)
        self.assertIn("no public key", log)

    def test_default_bind_never_lan(self):
        self.run_script(KEY)
        self.assertNotIn("SSH_BIND=0.0.0.0", self.env_lines())


class WiringTests(unittest.TestCase):
    """The subcommand must actually be reachable in the shipped image."""

    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_entrypoint_dispatches_ssh_setup(self):
        self.assertIn("ssh-setup)", self.read("docker-entrypoint.sh"))

    def test_containerfile_bakes_the_script(self):
        self.assertIn("deploy/ssh-setup.sh dist/ssh-setup.sh", self.read("Containerfile"))

    def test_script_is_valid_bash(self):
        self.assertEqual(subprocess.run(["bash", "-n", SCRIPT]).returncode, 0)


if __name__ == "__main__":
    unittest.main()

"""The terminal image must keep Claude startable — run with
`python3 -m unittest tests.test_claude_doctor` or `pytest tests/`.

A 0.1.16 instance reported `claude native binary not installed` on 2026-09-18:
the CLI's own updater had replaced the working installation inside the running
container with one whose native binary was never downloaded, and no board
terminal could start Claude any more. Two properties prevent that from coming
back, and these tests pin both:

  * the image decides the Claude version (DISABLE_AUTOUPDATER), so nothing
    rewrites the installation behind the operator's back
  * every container start checks Claude and repairs it if it is broken, which
    also heals installations that already damaged themselves
"""
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class SelfUpdaterOffTests(unittest.TestCase):
    """deploy/Containerfile.terminal — the version comes from the image."""

    def setUp(self):
        self.containerfile = read("deploy", "Containerfile.terminal")

    def test_autoupdater_disabled(self):
        self.assertIn("DISABLE_AUTOUPDATER=1", self.containerfile)

    def test_build_verifies_claude_starts(self):
        # The build must fail loudly rather than ship an image without Claude.
        self.assertIn("claude --version", self.containerfile)

    def test_doctor_is_installed(self):
        self.assertIn(
            "deploy/terminal/ili-claude-doctor.sh /usr/local/bin/ili-claude-doctor",
            self.containerfile,
        )


class DoctorRunsAtStartTests(unittest.TestCase):
    """deploy/terminal/entrypoint.sh — the check happens without being asked."""

    def setUp(self):
        self.entrypoint = read("deploy", "terminal", "entrypoint.sh")

    def test_entrypoint_calls_the_doctor(self):
        self.assertIn("/usr/local/bin/ili-claude-doctor", self.entrypoint)

    def test_doctor_never_blocks_the_terminal(self):
        # A failed repair must not keep the shell from coming up.
        self.assertIn("/usr/local/bin/ili-claude-doctor || true", self.entrypoint)


class DoctorBehaviourTests(unittest.TestCase):
    """deploy/terminal/ili-claude-doctor.sh — repair steps and their order."""

    def setUp(self):
        self.doctor = read("deploy", "terminal", "ili-claude-doctor.sh")

    def test_checks_before_repairing(self):
        self.assertIn("claude --version", self.doctor)

    def test_runs_the_package_postinstall(self):
        # The step the CLI itself names when the native binary is missing.
        self.assertIn("install.cjs", self.doctor)

    def test_falls_back_to_a_reinstall_with_scripts_allowed(self):
        self.assertIn("--allow-scripts=@anthropic-ai/claude-code", self.doctor)

    def test_exits_zero_even_when_it_cannot_repair(self):
        self.assertTrue(self.doctor.rstrip().endswith("exit 0"))

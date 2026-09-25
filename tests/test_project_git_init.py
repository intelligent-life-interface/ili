"""New project folders are Git repos from the start (F-19) — run with
`python3 -m unittest tests.test_project_git_init` or `pytest tests/`.

A fresh project folder used to be plain files: nothing versioned the work an AI
session did inside it. The api container has no `git` binary (adding it would pull
~50 MB of git+perl into an image that deliberately dropped pip to shrink scanner
surface), so the fix lives where `git` already ships: the terminal container, which
runs both the interactive board terminal (`ili-term.sh`) and the kanban automat
(`automat/worker.py`) — the two places an AI session actually writes to a project
folder.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "automat"))

import worker  # noqa: E402


def read(*parts):
    with open(ROOT.joinpath(*parts), encoding="utf-8") as fh:
        return fh.read()


class WorkerEnsureGitRepoTests(unittest.TestCase):
    """automat/worker.py — the automated path: a card can be worked without a
    human ever having opened that board's terminal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project_path = Path(self.tmp.name) / "some-project"
        self.project_path.mkdir()

    def test_initializes_repo(self):
        worker._ensure_git_repo(self.project_path)
        self.assertTrue((self.project_path / ".git").is_dir())

    def test_idempotent_on_existing_repo(self):
        worker._ensure_git_repo(self.project_path)
        marker = self.project_path / ".git" / "HEAD"
        before = marker.read_text()
        worker._ensure_git_repo(self.project_path)
        self.assertEqual(before, marker.read_text())

    def test_skips_silently_when_git_missing(self):
        with mock.patch("shutil.which", return_value=None):
            worker._ensure_git_repo(self.project_path)  # must not raise
        self.assertFalse((self.project_path / ".git").exists())

    def test_skips_silently_on_missing_directory(self):
        missing = self.project_path / "does-not-exist"
        worker._ensure_git_repo(missing)  # must not raise, must not create it
        self.assertFalse(missing.exists())

    @unittest.skipUnless(shutil.which("git"), "git not installed on this host")
    def test_sets_local_identity_when_none_configured(self):
        with mock.patch("subprocess.run") as run:
            def fake_run(cmd, **kwargs):
                result = mock.Mock(returncode=0)
                if cmd[:2] == ["git", "-C"] and cmd[3:5] == ["config", "user.name"] \
                        and len(cmd) == 5:
                    result.returncode = 1  # nothing configured anywhere
                return result
            run.side_effect = fake_run
            worker._ensure_git_repo(self.project_path)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["git", "-C", str(self.project_path), "config", "user.name", "ili"],
                       commands)
        self.assertIn(
            ["git", "-C", str(self.project_path), "config", "user.email", "ili@localhost"],
            commands,
        )

    def test_resolve_workdir_calls_ensure_git_repo(self):
        # resolve_workdir has three return paths (resolver hit, AUTOMAT_PROJECT_DIRS/
        # fallback candidates, Path.home()) — only the first two name a real project
        # folder and must be versioned; Path.home() must never be touched.
        with mock.patch.object(worker, "_ensure_git_repo") as ensure, \
             mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(stdout=str(self.project_path) + "\n")
            result = worker.resolve_workdir("some-project")
        self.assertEqual(result, self.project_path)
        ensure.assert_called_once_with(self.project_path)


class TermWrapperGitInitTests(unittest.TestCase):
    """deploy/terminal/ili-term.sh — the interactive path, covering the folders the
    api container already created before anyone ever opened a terminal for them."""

    def setUp(self):
        self.sh = read("deploy", "terminal", "ili-term.sh")

    def test_syntax_is_valid(self):
        import subprocess
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "deploy" / "terminal" / "ili-term.sh")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_checks_for_missing_git_dir_not_missing_folder(self):
        # The api container creates the folder itself before any terminal opens —
        # ".git missing" is the real signal, "folder missing" is not (F-19).
        self.assertIn('! -d "$DIR/.git"', self.sh)

    def test_runs_only_for_the_real_per_board_path(self):
        # Not just "-d $DIR": if mkdir failed above, DIR falls back to PROJECTS_DIR
        # while SLUG stays set — git-initing PROJECTS_DIR itself would turn it into
        # one repo that silently absorbs every neighbouring project.
        self.assertIn('"$DIR" == "${PROJECTS_DIR}/${SLUG}"', self.sh)

    def test_sets_placeholder_identity_only_if_none_configured(self):
        self.assertIn('git -C "$DIR" config user.name >/dev/null 2>&1', self.sh)
        self.assertIn('git -C "$DIR" config user.name "ili"', self.sh)
        self.assertIn('git -C "$DIR" config user.email "ili@localhost"', self.sh)

    def test_git_init_never_breaks_the_connection(self):
        # set -euo pipefail is active for the whole script — a bare `git init`
        # failure would otherwise kill the terminal connection.
        self.assertIn("set -euo pipefail", self.sh)
        self.assertIn('if git -C "$DIR" init -q --initial-branch=main', self.sh)


if __name__ == "__main__":
    unittest.main()

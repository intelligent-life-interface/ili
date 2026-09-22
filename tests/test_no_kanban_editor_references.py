"""The shipped image has no `kanban-editor` subagent.

That subagent exists only in this host's Claude configuration (~/.claude), not in
anything the terminal or automat image ships. A prompt or skill that tells the AI
to delegate to it gives an instruction it cannot follow (fix 90d57ad4, F-13/F-17/F-22
of the v0.1.22/v0.2.0 field reports). `automat/worker.py` is a copy of
~/containers/kanban-automat kept in sync by rsync + a manual patch list
(automat/README.md) — a future rsync would silently reintroduce this without a
test catching it. README.md files document the history and are allowed to name
it.
"""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WATCHED_DIRS = ("deploy/terminal", "automat")


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


class NoKanbanEditorReferences(unittest.TestCase):
    def test_shipped_files_do_not_name_the_missing_subagent(self):
        hits = []
        for rel in _tracked_files():
            if not rel.startswith(WATCHED_DIRS) or rel.endswith("README.md"):
                continue
            path = REPO / rel
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "kanban-editor" in text:
                hits.append(rel)
        self.assertEqual(
            hits, [],
            "names the kanban-editor subagent, which no shipped image has — "
            "use automat_cli.py instead:\n  " + "\n  ".join(sorted(hits)))


if __name__ == "__main__":
    unittest.main()

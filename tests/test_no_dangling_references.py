"""Files that the code names must exist.

On 20.09.2026 a cleanup commit removed `deploy/terminal/ili-mcp-docker.py` as a
"foreign change" that had been swept into an unrelated commit. The observation
was right; the conclusion was not. Four places still referenced the file, the
image no longer copied it, and the Docker-MCP switch answered "ili-mcp-docker
script missing". Nobody noticed until the test suite could not even collect.

A rule in a prompt would have been forgotten. This test makes the class visible:
delete a file that something still names, and it fails — regardless of who
deleted it and why.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Scripts the images install and the services call by name. A missing one is not
# a syntax error anywhere — it surfaces at runtime, in a container, as a string.
WATCHED_DIRS = ("deploy/terminal", "deploy/gateway", "deploy")

# Referenced from Python, shell, HTML and Containerfiles alike.
# ohne "" — `str.endswith("")` ist immer wahr und machte den Filter wirkungslos
SEARCHED_SUFFIXES = (".py", ".sh", ".html", ".js", ".conf", ".yml", ".yaml")


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


class DeployScriptsAreReferencedAndPresent(unittest.TestCase):
    def test_every_referenced_deploy_script_exists(self):
        """Any `deploy/...` path named in the tree must be a file that is there."""
        tracked = set(_tracked_files())
        searchable = [f for f in tracked
                      if f.endswith(SEARCHED_SUFFIXES) and not f.startswith("tests/")
                      and "Containerfile" not in f or f.startswith("deploy/")]
        # Containerfiles carry the COPY lines, include them explicitly
        searchable += [f for f in tracked if "Containerfile" in f]

        pattern = re.compile(r"deploy/[A-Za-z0-9_./-]+\.(?:py|sh|conf|yml|yaml)")
        missing: dict[str, list[str]] = {}
        for rel in set(searchable):
            path = REPO / rel
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for hit in set(pattern.findall(text)):
                if hit.startswith(WATCHED_DIRS) and hit not in tracked:
                    missing.setdefault(hit, []).append(rel)

        self.assertEqual(
            missing, {},
            "referenced but not in the repo — a delete went too far:\n" +
            "\n".join(f"  {f} ← {', '.join(sorted(w))}" for f, w in sorted(missing.items())))

    def test_container_copies_only_existing_files(self):
        """A COPY of a file that is gone breaks the image build, not the tests."""
        tracked = set(_tracked_files())
        # Mehrere Quellen pro COPY sind erlaubt (Containerfile:82 kopiert zwei
        # Gateway-Dateien in ein Verzeichnis). Die alte Regex verlangte genau
        # zwei Operanden und liess solche Zeilen ungeprueft durch — genau die
        # Luecke, die dieser Test schliessen soll.
        copy_re = re.compile(r"^COPY(?:\s+--\S+)*\s+(.+?)\s*$", re.M)
        broken = []
        for cf in (f for f in tracked if "Containerfile" in f):
            for line in copy_re.findall((REPO / cf).read_text()):
              parts = line.split()
              for src in parts[:-1]:          # letzter Operand ist das Ziel
                if not src.startswith("deploy/"):
                    continue
                if src.endswith("/"):
                    # directory copy: at least one tracked file has to live there
                    if not any(t.startswith(src) for t in tracked):
                        broken.append(f"{cf}: COPY {src} (leeres Verzeichnis)")
                elif src not in tracked:
                    broken.append(f"{cf}: COPY {src}")
        self.assertEqual(broken, [], "COPY of a missing file:\n  " + "\n  ".join(broken))


class BridgeScriptConstantsResolve(unittest.TestCase):
    """The bridge calls helpers by their installed path; check the source exists."""

    def test_installed_script_paths_have_a_source(self):
        bridge = (REPO / "deploy" / "terminal" / "claude_cli_bridge.py").read_text()
        tracked = set(_tracked_files())
        for name in re.findall(r'"/usr/local/bin/([a-z0-9-]+)"', bridge):
            candidates = [f"deploy/terminal/{name}{ext}" for ext in (".py", ".sh", "")]
            self.assertTrue(
                any(c in tracked for c in candidates),
                f"{name} is installed to /usr/local/bin but no source in deploy/terminal/")


if __name__ == "__main__":
    unittest.main()

"""Local-Git-Status-Service: git status/ahead-behind für alle lokalen Repos.

Scannt `~/containers/*` und `~/Projekte/*` (jeweils direkte Kind-Ordner mit
`.git`) und liefert pro Repo: aktuellen Branch, Anzahl offener Änderungen
sowie Commits ahead/behind des konfigurierten Upstreams. Liefert die lokale
Hälfte des "Commit- und Push-Status" — die GitHub-Hälfte kommt aus
`github_status_service`, zusammengeführt in `git_status_service`.
"""
import logging
import re
import subprocess
from pathlib import Path

from app.services.ttl_cache import TTLCache

log = logging.getLogger("dashboard.services.local_git_status")

_SCAN_ROOTS = [Path.home() / "containers", Path.home() / "Projekte"]
# Single-Flight gegen Cache-Stampede (opt_cache_stampede_0806): ein Scan spawnt
# ~90 Repos × 6 git-Subprozesse (~540 Prozesse). Ohne Lock würden parallele
# Requests nach Cache-Ablauf ALLE gleichzeitig scannen und den Threadpool fluten.
_cache = TTLCache(ttl_seconds=60)

_GH_URL_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$")


def _git(repo: Path, args: list[str], timeout: float = 5.0) -> tuple[str, int]:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip(), r.returncode
    except Exception as e:
        log.warning("git %s in %s fehlgeschlagen: %s", args, repo, e)
        return "", 1


def _full_name_from_remote(url: str) -> str | None:
    if not url:
        return None
    m = _GH_URL_RE.search(url.strip())
    return m.group(1) if m else None


def _scan_repo(repo_dir: Path) -> dict:
    branch, _ = _git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
    status_out, _ = _git(repo_dir, ["status", "--porcelain"])
    changed = len([l for l in status_out.splitlines() if l.strip()])
    remote_url, _ = _git(repo_dir, ["remote", "get-url", "origin"])
    last_commit_at, _ = _git(repo_dir, ["log", "-1", "--format=%cI"])

    ahead = behind = 0
    has_upstream = False
    upstream, rc = _git(repo_dir, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if rc == 0 and upstream:
        has_upstream = True
        counts, rc2 = _git(repo_dir, ["rev-list", "--left-right", "--count", "@{u}...HEAD"])
        if rc2 == 0 and counts:
            parts = counts.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

    return {
        "name": repo_dir.name,
        "path": str(repo_dir.relative_to(Path.home())),
        "branch": branch or None,
        "dirty": changed > 0,
        "changed_files": changed,
        "has_upstream": has_upstream,
        "ahead": ahead,
        "behind": behind,
        "remote_url": remote_url or None,
        "full_name": _full_name_from_remote(remote_url),
        "last_commit_at": last_commit_at or None,
    }


def _scan_local_repos_uncached() -> list[dict]:
    """Scant alle lokalen Repos, ohne Cache zu nutzen."""
    repo_dirs = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for git_dir in root.glob("*/.git"):
            if git_dir.is_dir():
                repo_dirs.append(git_dir.parent)

    items = []
    for repo_dir in sorted(repo_dirs):
        try:
            items.append(_scan_repo(repo_dir))
        except Exception as e:
            log.error("Scan von %s fehlgeschlagen: %s", repo_dir, e, exc_info=True)

    items.sort(key=lambda x: x["last_commit_at"] or "", reverse=True)
    log.info("Lokaler Git-Status: %d Repos gescannt (Cache erneuert)", len(items))
    return items


def scan_local_repos(force: bool = False) -> dict:
    """Lokale Repos unter containers/ und Projekte/ mit Status, neueste zuerst.

    Mit TTL-Cache (60s) gegen Cache-Stampede: nur der erste Request nach TTL-Ablauf
    scannt wirklich; parallele Requests warten auf sein Ergebnis.
    """
    if force:
        _cache.invalidate()
    items = _cache.get(_scan_local_repos_uncached)
    # cached ist True, wenn wir nicht force hatten und der Cache noch gültig ist
    cached = not force and _cache.is_valid()
    return {"repos": items, "total": len(items), "cached": cached}

"""GitHub-Import-Service: Repo-Listing und Board-Import.

Schnittstelle:
  - list_github_repos(user_login, force=False) -> [dict]  # GitHub-User-Repos + viewer
  - import_github_repos(full_names: list) -> dict  # cloned/exists/failed pro Repo
  - Sync-Helfer: clone_github_repo(full_name, board_id)
"""
import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from constants import PROJEKTE_BASE
from app.services.board_creation_service import create_board
from app.storage.manifest_repository import ManifestRepository
from app.services.ttl_cache import TTLCache

log = logging.getLogger("dashboard.services.github_import")


def _github_token() -> str:
    """Personal access token for the GitHub import, from ILI_GITHUB_TOKEN.

    Deliberately NOT the device-flow login next door: that GitHub App is scoped
    to issues on a single repository on purpose, because the alternative
    (``public_repo``) would mean write access to every public repository the user
    owns. Importing repositories needs ``contents`` read access instead, so it
    asks for a token the user creates and owns. Public repositories clone
    without a token; only private ones and the profile lookup need one.
    """
    return os.environ.get("ILI_GITHUB_TOKEN", "").strip()

_cache = TTLCache(ttl_seconds=300.0)
_manifest = ManifestRepository()


def _set_github_repo_field(manifest: dict, board_id: str, github_repo: str) -> None:
    """Setzt das github_repo-Feld in einem Manifest-Eintrag."""
    for entry in manifest.get("boards", []):
        if entry.get("id") == board_id:
            entry["github_repo"] = github_repo
            log.debug("Manifest-Feld github_repo gesetzt für %s: %s", board_id, github_repo)
            break


def _get_user_info(token: str) -> dict | None:
    """GET /user — Authentifizierter Nutzer (login, name, etc.)."""
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "dashboard-github-import",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.debug("_get_user_info fehlgeschlagen: %s", e)
        return None


def _fetch_user_repos(login: str, token: str) -> tuple[list[dict], str | None]:
    """GitHub-Repos eines Users auflisten mit Pagination.

    - login == Token-Owner → /user/repos (privat inkl.)
    - Sonst: /users/<login>/repos (öffentlich nur)
    """
    repos = []
    page = 1
    token_owner = _get_user_info(token)
    is_owner = token_owner and token_owner.get("login") == login if login else False

    # Endpoint: eigene Repos (/user/repos) oder User-Repos (/users/<login>/repos)
    endpoint = "https://api.github.com/user/repos" if is_owner else f"https://api.github.com/users/{login}/repos"

    viewer_login = token_owner.get("login") if token_owner else None

    while True:
        req = urllib.request.Request(
            f"{endpoint}?per_page=100&affiliation=owner&sort=pushed&page={page}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "dashboard-github-import",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("User %r nicht gefunden (404)", login)
                break
            raise
        except Exception as e:
            log.error("_fetch_user_repos: %s", e)
            break

        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return repos, viewer_login


def list_github_repos(user_login: str = "", force: bool = False) -> dict:
    """Repos des übergebenen Users (oder Viewer-Owner, wenn user_login leer).

    Rückgabe: {
      "viewer_login": "octocat",
      "requested_user": "octocat",
      "repos": [{"id": 123, "full_name": "octocat/my-repo", ...}, ...]
    }
    """
    token = _github_token()
    if not token:
        raise RuntimeError("ILI_GITHUB_TOKEN nicht konfiguriert")

    # Wenn user_login leer → Viewer (Token-Owner)
    if not user_login.strip():
        user_info = _get_user_info(token)
        if not user_info:
            raise RuntimeError("Viewer-Info konnte nicht geladen werden")
        user_login = user_info.get("login")

    # TTLCache mit Single-Flight-Pattern
    def _fetch() -> dict:
        repos, viewer_login = _fetch_user_repos(user_login, token)
        result = {
            "viewer_login": viewer_login,
            "requested_user": user_login,
            "repos": [
                {
                    "id": r.get("id"),
                    "full_name": r.get("full_name"),
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "private": r.get("private", False),
                    "url": r.get("html_url"),
                }
                for r in repos
            ],
        }
        log.info("list_github_repos: %s → %d Repos", user_login, len(repos))
        return result

    if force:
        return _fetch()
    return _cache.get(_fetch)


def clone_github_repo(full_name: str, board_id: str, work_dir: Path) -> bool:
    """Fetcht ein GitHub-Repo in den existierenden Projekt-Ordner.

    Full name: "octocat/my-repo"

    Tut: git init (fallback wenn noch nicht) → remote add → fetch → checkout.
    Das funktioniert auch, wenn der Ordner bereits CLAUDE.md o.ä. enthält (von create_board).

    Returns: True bei Erfolg, False sonst.
    """
    import tempfile

    token = _github_token()
    if not token:
        log.info("clone_github_repo: kein ILI_GITHUB_TOKEN — versuche %s "
                 "ohne Anmeldung (funktioniert bei oeffentlichen Repos)", full_name)

    clone_url = f"https://github.com/{full_name}.git"
    work_dir.mkdir(parents=True, exist_ok=True)

    # ASKPASS-Skript in tempfile (nicht /tmp/.gh_askpass.sh — Race Condition bei parallel Clones)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write('#!/bin/sh\necho "$GH_TOKEN"\n')
        askpass_path = Path(f.name)
    askpass_path.chmod(0o755)

    env = {
        "GIT_TERMINAL_PROMPT": "0",  # Nicht hängen bei Fehler
    }
    if token:
        env["GIT_ASKPASS"] = str(askpass_path)
        env["GH_TOKEN"] = token

    try:
        # 1. git init (fallback, wenn noch nicht initialisiert)
        subprocess.run(
            ["git", "-C", str(work_dir), "init"],
            capture_output=True,
            timeout=10,
        )

        # 2. Remote hinzufügen (oder updaten)
        subprocess.run(
            ["git", "-C", str(work_dir), "remote", "remove", "origin"],
            capture_output=True,
            timeout=10,
        )
        result = subprocess.run(
            ["git", "-C", str(work_dir), "remote", "add", "origin", clone_url],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log.error("git remote add fehlgeschlagen für %s: %s", full_name, result.stderr[:200])
            return False

        # 3. Fetch
        result = subprocess.run(
            ["git", "-C", str(work_dir), "fetch", "origin", "--depth=1"],
            env={**subprocess.os.environ, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log.error("git fetch fehlgeschlagen für %s: %s", full_name, result.stderr[:200])
            return False

        # 4. Checkout default branch
        result = subprocess.run(
            ["git", "-C", str(work_dir), "checkout", "-f", "origin/HEAD"],
            env={**subprocess.os.environ, **env},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            # Fallback: HEAD → main probieren
            result = subprocess.run(
                ["git", "-C", str(work_dir), "checkout", "-f", "origin/main"],
                env={**subprocess.os.environ, **env},
                capture_output=True,
                text=True,
                timeout=30,
            )

        if result.returncode != 0:
            log.error("git checkout fehlgeschlagen für %s: %s", full_name, result.stderr[:200])
            return False

        log.info("git fetch+checkout erfolgreich: %s → %s", full_name, work_dir)
        return True
    except Exception as e:
        log.error("clone_github_repo Exception für %s: %s", full_name, e)
        return False
    finally:
        try:
            askpass_path.unlink(missing_ok=True)
        except Exception:
            pass


def import_github_repos(full_names: list, auto: bool = False) -> dict:
    """Importiert mehrere GitHub-Repos als neue Boards.

    Pro Repo: Board anlegen (fast=True zur Bridge-Stampede), Manifest-Feld github_repo setzen,
    Clone in ~/Projekte/<slug>.

    Rückgabe: {
      "octocat/my-repo": {"status": "created", "board_id": "my-repo", ...},
      "octocat/other": {"status": "skipped", "reason": "exists"},
      "octocat/bad": {"status": "clone_failed", ...}
    }
    """
    from project_creator import _slugify

    results = {}
    manifest = _manifest.load()

    for full_name in full_names:
        full_name = (full_name or "").strip()
        if not full_name or "/" not in full_name:
            results[full_name] = {"status": "skipped", "reason": "invalid_name"}
            continue

        # Slug aus Repo-Name
        repo_name = full_name.split("/", 1)[1]
        slug = _slugify(repo_name)
        board_id = slug

        # Prüfe ob Board existiert
        if any(b.get("id") == board_id for b in manifest.get("boards", [])):
            results[full_name] = {"status": "skipped", "reason": "board_exists"}
            log.info("import_github_repos: Board %r existiert bereits", board_id)
            continue

        # Board anlegen (fast=True, keine KI-Schritte → schneller, konservativ)
        try:
            create_board({
                "name": repo_name,
                "description": f"GitHub-Repo: {full_name}",
                "id": board_id,
                "fast": True,  # Wichtig: Bridge-Stampede vermeiden
                "auto": auto,  # Konservativ: auto=False, User schaltet ein
            })
        except FileExistsError:
            results[full_name] = {"status": "skipped", "reason": "board_exists"}
            log.info("import_github_repos: Board %r kurzfristig dazwischen angelegt", board_id)
            continue
        except Exception as e:
            results[full_name] = {"status": "board_creation_failed", "error": str(e)[:100]}
            log.error("import_github_repos: Board-Anlage fehlgeschlagen für %s: %s", full_name, e)
            continue

        # Manifest-Feld github_repo setzen
        try:
            _manifest.update(lambda m: _set_github_repo_field(m, board_id, full_name))
        except Exception as e:
            log.warning("import_github_repos: Manifest-Update fehlgeschlagen für %s: %s", board_id, e)

        # Clone
        work_dir = PROJEKTE_BASE / board_id
        clone_ok = clone_github_repo(full_name, board_id, work_dir)

        if clone_ok:
            results[full_name] = {
                "status": "created",
                "board_id": board_id,
                "work_dir": str(work_dir),
            }
            log.info("import_github_repos: erfolgreich importiert %s → %s", full_name, board_id)
        else:
            # Board ist angelegt, aber Clone fehlgeschlagen → nicht rollbacken, nur melden
            results[full_name] = {
                "status": "created_no_clone",
                "board_id": board_id,
                "work_dir": str(work_dir),
                "clone_error": "Clone fehlgeschlagen, Board angelegt",
            }
            log.warning("import_github_repos: Board angelegt, aber Clone fehlgeschlagen %s", full_name)

    return results

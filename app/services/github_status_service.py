"""GitHub-Status-Service: eigene Repos + letzter Commit für GET /api/projects/github.

Datenquelle: GitHub REST API `/user/repos` (Owner-Repos, alle Sichtbarkeiten),
authenticated with the device-flow token from github_auth_service (same source as
github_issue_service) or, as a headless fallback, the GITHUB_TOKEN env variable.
26.08.2026: previously imported `_gh_admin_token` from the home-stack-only
`github_integration.py`, which the release cleanup (97b8371) removed — that
ModuleNotFoundError crash-looped v0.1.11 at startup. Kurzer In-Memory-Cache, damit
wiederholtes Laden der Seite nicht bei jedem Aufruf gegen die GitHub-API geht.

Bewusst OHNE Pro-Repo-Zusatzcalls für offene PRs/CI-Status (v1): bei >100 Repos
wären das >200 zusätzliche Requests pro Seitenaufruf — Scope-Entscheidung laut
Kanban-Karte "Anzeige-Felder für Projektstatus klären".
"""
import json
import logging
import os
import urllib.error
import urllib.request

from app.services import github_auth_service
from app.services.ttl_cache import TTLCache

log = logging.getLogger("dashboard.services.github_status")

_cache = TTLCache(ttl_seconds=180.0)


def _fetch_all_repos(token: str) -> list[dict]:
    repos = []
    page = 1
    while True:
        req = urllib.request.Request(
            "https://api.github.com/user/repos"
            f"?per_page=100&affiliation=owner&sort=pushed&page={page}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "dashboard-github-status",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def _github_token() -> str:
    """Device-flow token (github_auth_service) first, GITHUB_TOKEN env as fallback, else ""."""
    tok = github_auth_service.get_token()
    if tok:
        log.debug("_github_token: using github_auth_service token")
        return tok
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    log.debug("_github_token: github_auth_service has no token, GITHUB_TOKEN env %s",
              "set" if tok else "unset")
    return tok


def _fetch_and_process_repos() -> list[dict]:
    """Hole Repos von GitHub-API und verarbeite sie."""
    token = _github_token()
    if not token:
        log.error("no GitHub token (not logged in via GitHub auth, GITHUB_TOKEN unset) — "
                  "cannot load repo list")
        raise RuntimeError("GitHub-Login fehlt (GitHub-Anmeldung im Dashboard oder GITHUB_TOKEN)")

    try:
        raw = _fetch_all_repos(token)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        log.error("GitHub-Repo-Liste fehlgeschlagen (HTTP %s): %s", e.code, body[:300])
        raise RuntimeError(f"GitHub API HTTP {e.code}") from e
    except Exception as e:
        log.error("GitHub-Repo-Liste fehlgeschlagen: %s", e, exc_info=True)
        raise RuntimeError(str(e)) from e

    items = [
        {
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "html_url": r.get("html_url"),
            "private": r.get("private", False),
            "default_branch": r.get("default_branch"),
            "pushed_at": r.get("pushed_at"),
            "description": r.get("description"),
        }
        for r in raw
    ]
    items.sort(key=lambda x: x["pushed_at"] or "", reverse=True)
    log.info("GitHub-Repo-Status: %d Repos geladen (Cache erneuert)", len(items))
    return items


def collect_github_repos(force: bool = False) -> dict:
    """Liste aller eigenen GitHub-Repos, neueste Aktivität zuerst.

    Gecacht für 180 Sekunden; `force=True` erzwingt einen frischen Abruf.
    """
    if force:
        _cache.invalidate()

    repos = _cache.get(_fetch_and_process_repos)
    return {"repos": repos, "total": len(repos), "cached": _cache.is_valid()}

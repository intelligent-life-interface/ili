"""Git-Status-Service: führt GitHub-Repo-Liste + lokalen Git-Status zusammen.

Für GET /api/projects/git-status — die eigentliche "Commit- und Push-Status"-
Übersicht (Board github-projekt-committ-und-push-osz5sb): pro Repo, ob lokal
uncommittete Änderungen liegen, ob Commits noch nicht gepusht wurden, und der
letzte GitHub-Push. Matching lokal↔remote über die `origin`-URL (full_name
`owner/repo`), nicht über den Ordnernamen — Ordner heissen nicht immer wie das
Repo.
"""
import logging

from app.services import github_status_service, local_git_status_service

log = logging.getLogger("dashboard.services.git_status")

# Priorität, welcher Zustand im Zweifel den Status-Badge bestimmt.
_STATUS_ORDER = ["dirty", "unpushed", "behind", "no_upstream", "no_remote", "synced", "no_local"]


def _status_for(local: dict | None, remote_found: bool) -> str:
    if local is None:
        return "no_local"
    if local["dirty"]:
        return "dirty"
    if local["ahead"] > 0:
        return "unpushed"
    if local["behind"] > 0:
        return "behind"
    if not local["has_upstream"]:
        return "no_upstream"
    if not remote_found:
        return "no_remote"
    return "synced"


def collect_git_status(force: bool = False) -> dict:
    remote = github_status_service.collect_github_repos(force=force)
    local = local_git_status_service.scan_local_repos(force=force)

    by_full_name = {r["full_name"]: r for r in remote["repos"] if r.get("full_name")}
    local_by_full_name = {r["full_name"]: r for r in local["repos"] if r.get("full_name")}

    seen_full_names = set()
    items = []

    for full_name, rr in by_full_name.items():
        lr = local_by_full_name.get(full_name)
        seen_full_names.add(full_name)
        items.append({
            "name": rr["name"],
            "full_name": full_name,
            "html_url": rr["html_url"],
            "private": rr["private"],
            "default_branch": rr["default_branch"],
            "pushed_at": rr["pushed_at"],
            "description": rr["description"],
            "local": lr,
            "status": _status_for(lr, remote_found=True),
        })

    # Lokale Repos ohne passendes GitHub-Repo (z.B. noch nicht gepusht, kein origin)
    for full_name, lr in local_by_full_name.items():
        if full_name in seen_full_names:
            continue
        items.append({
            "name": lr["name"],
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}" if full_name else None,
            "private": None,
            "default_branch": lr["branch"],
            "pushed_at": None,
            "description": None,
            "local": lr,
            "status": _status_for(lr, remote_found=False),
        })

    # Lokale Repos ganz ohne origin-Remote (kein full_name) einzeln durchreichen
    for lr in local["repos"]:
        if lr.get("full_name"):
            continue
        items.append({
            "name": lr["name"],
            "full_name": None,
            "html_url": None,
            "private": None,
            "default_branch": lr["branch"],
            "pushed_at": None,
            "description": None,
            "local": lr,
            "status": _status_for(lr, remote_found=False),
        })

    items.sort(key=lambda x: _STATUS_ORDER.index(x["status"]))
    log.info("Git-Status kombiniert: %d Einträge (%d GitHub, %d lokal)",
              len(items), len(remote["repos"]), len(local["repos"]))
    return {
        "repos": items,
        "total": len(items),
        "remote_total": remote["total"],
        "local_total": local["total"],
    }

"""\ngithub_integration.py — GitHub-Integration-Funktionen\nAutogeneriert von script_splitter.py\n"""
import re as _re
import os
import json
import logging
import urllib.request
from pathlib import Path
from constants import GITHUB_OWNER

log = logging.getLogger("dashboard.github_integration")


def _gh_admin_token() -> str:
    """
    Token, das GitHub-Repos ANLEGEN darf — der classic PAT GH_ADMIN_TOKEN
    (Scopes repo/delete_repo/workflow) aus der Umgebung oder ~/config.env.

    WICHTIG: Das gh-Default-Keyring-Token und GH_PUSH_TOKEN sind fine-grained
    PATs OHNE Account-Permission 'Administration' → `gh repo create` / REST
    `POST /user/repos` schlagen mit HTTP 403 fehl. Nur GH_ADMIN_TOKEN kann anlegen.
    Siehe Memory feedback_github_push_token.
    """
    tok = os.environ.get("GH_ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    cfg = Path.home() / "config.env"
    try:
        m = _re.search(r"^GH_ADMIN_TOKEN=(.+)$", cfg.read_text(encoding="utf-8"), _re.M)
        if m:
            return m.group(1).strip()
    except Exception as e:
        log.error(f"config.env nicht lesbar für GH_ADMIN_TOKEN: {e}")
    return ""


def _create_github_repo(repo_name: str) -> str:
    """
    Legt ein privates GitHub-Repo GITHUB_OWNER/<repo_name> an.
    Gibt die Repo-URL zurück, oder '' bei Fehler / bereits vorhanden.

    Nutzt GH_ADMIN_TOKEN (classic PAT) via REST-API — NICHT das gh-Keyring-
    Token (fine-grained, read-only → 403 beim Anlegen). Ohne Admin-Token wird
    KEIN Repo angelegt (statt eines toten origin-Remotes ohne GitHub-Repo).
    """
    full_name = f"{GITHUB_OWNER}/{repo_name}"
    url = f"https://github.com/{full_name}"

    token = _gh_admin_token()
    if not token:
        log.error(
            "GH_ADMIN_TOKEN fehlt (env/config.env) — kann GitHub-Repo '%s' nicht "
            "anlegen. fine-grained gh/GH_PUSH_TOKEN dürfen keine Repos erstellen.",
            full_name,
        )
        return ""

    payload = json.dumps({
        "name": repo_name,
        "private": True,
        "description": f"Auto-Projekt {repo_name} (Dashboard create_app_project)",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dashboard-create-app-project",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                log.info(f"GitHub-Repo angelegt: {url}")
                return url
            log.error(f"Repo-Anlegen '{full_name}': unerwarteter Status {resp.status}")
            return ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        # 422 = existiert bereits (oder Name-Validierung) → als vorhanden behandeln
        if e.code == 422 and "already exists" in body:
            log.info(f"GitHub-Repo existiert bereits: {url}")
            return url
        log.error(f"Repo-Anlegen '{full_name}' fehlgeschlagen (HTTP {e.code}): {body[:300]}")
        return ""
    except Exception as e:
        log.error(f"_create_github_repo Exception: {e}")
        return ""
